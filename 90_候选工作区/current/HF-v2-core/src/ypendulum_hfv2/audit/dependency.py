"""Canonical import and classification-dependency audit for G2."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DependencyViolation:
    source_path: str
    source_classification: str
    imported_name: str
    target_classification: str
    reason: str


@dataclass(frozen=True)
class G2DependencyAudit:
    discovered_files: tuple[str, ...]
    classified_files: tuple[str, ...]
    unclassified_files: tuple[str, ...]
    missing_manifest_files: tuple[str, ...]
    canonical_imports: tuple[tuple[str, tuple[str, ...]], ...]
    dependency_violations: tuple[DependencyViolation, ...]
    path_classification_violations: tuple[str, ...]
    production_try_statement_count: int
    production_random_call_count: int

    @property
    def passed(self) -> bool:
        return (
            not self.unclassified_files
            and not self.missing_manifest_files
            and not self.dependency_violations
            and not self.path_classification_violations
            and self.production_try_statement_count == 0
            and self.production_random_call_count == 0
        )


def _module_name(relative_path: str, package_name: str) -> str:
    path = Path(relative_path)
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    suffix = ".".join(parts)
    return package_name if not suffix else f"{package_name}.{suffix}"


def _canonical_imports(
    tree: ast.AST,
    current_module: str,
    is_package: bool,
) -> tuple[str, ...]:
    names: list[str] = []
    current_package = current_module if is_package else current_module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module is not None:
                    names.append(node.module)
            else:
                relative = "." * node.level + (node.module or "")
                names.append(importlib.util.resolve_name(relative, current_package))
    return tuple(sorted(set(names)))


def _call_name(node: ast.Call) -> str:
    parts: list[str] = []
    value: ast.expr = node.func
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def _prefix_allowed(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes)


def _target_classification(
    imported_name: str,
    module_classification: dict[str, str],
) -> str | None:
    candidates = [
        (name, classification)
        for name, classification in module_classification.items()
        if imported_name == name or imported_name.startswith(f"{name}.")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(item[0]))[1]


def audit_g2_dependencies(
    source_root: str | Path,
    module_manifest: str | Path,
    package_name: str = "ypendulum_hfv2",
) -> G2DependencyAudit:
    root = Path(source_root)
    document: dict[str, Any] = json.loads(Path(module_manifest).read_text(encoding="utf-8"))
    modules = document["modules"]
    classifications = tuple(document["classifications"])
    if len(classifications) != len(set(classifications)):
        raise ValueError("G2 module classifications must be unique.")
    paths = tuple(str(entry["path"]) for entry in modules)
    if len(paths) != len(set(paths)):
        raise ValueError("G2 module paths must be unique.")
    by_path = {str(entry["path"]): str(entry["classification"]) for entry in modules}
    if any(value not in classifications for value in by_path.values()):
        raise ValueError("Every G2 module must use a declared classification.")
    discovered = tuple(sorted(path.relative_to(root).as_posix() for path in root.rglob("*.py")))
    unclassified = tuple(sorted(set(discovered) - set(paths)))
    missing = tuple(sorted(set(paths) - set(discovered)))

    path_violations: list[str] = []
    exact_rules = document["exact_path_classification"]
    for relative, expected in exact_rules.items():
        if relative in by_path and by_path[relative] != expected:
            path_violations.append(f"{relative}: expected {expected}, got {by_path[relative]}")
    for rule in document["path_classification_rules"]:
        prefix = str(rule["path_prefix"])
        allowed = set(rule["allowed_classifications"])
        for relative, classification in by_path.items():
            if relative.startswith(prefix) and classification not in allowed:
                path_violations.append(
                    f"{relative}: classification {classification} forbidden under {prefix}"
                )
    for relative, classification in by_path.items():
        if classification == "audit" and not relative.startswith("audit/"):
            path_violations.append(f"{relative}: audit classification is restricted to audit/")

    module_classification = {
        _module_name(relative, package_name): classification
        for relative, classification in by_path.items()
    }
    allowed_internal = {
        key: frozenset(value)
        for key, value in document["allowed_internal_dependencies"].items()
    }
    allowed_external = {
        key: tuple(value)
        for key, value in document["allowed_external_import_prefixes"].items()
    }
    production = frozenset(document["production_classifications"])
    canonical_by_file: list[tuple[str, tuple[str, ...]]] = []
    violations: list[DependencyViolation] = []
    try_count = 0
    random_count = 0
    for relative in discovered:
        if relative not in by_path:
            continue
        path = root / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        source_classification = by_path[relative]
        module_name = _module_name(relative, package_name)
        imports = _canonical_imports(tree, module_name, relative.endswith("/__init__.py") or relative == "__init__.py")
        canonical_by_file.append((relative, imports))
        if source_classification in production:
            try_count += sum(isinstance(node, ast.Try) for node in ast.walk(tree))
            random_count += sum(
                "random" in _call_name(node).split(".")
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
            )
        for imported in imports:
            target = _target_classification(imported, module_classification)
            if target is not None:
                if target not in allowed_internal[source_classification]:
                    violations.append(
                        DependencyViolation(
                            relative,
                            source_classification,
                            imported,
                            target,
                            "internal_classification_not_allowed",
                        )
                    )
                continue
            root_name = imported.split(".", maxsplit=1)[0]
            if root_name in sys.stdlib_module_names or root_name == "__future__":
                continue
            if not _prefix_allowed(imported, allowed_external[source_classification]):
                violations.append(
                    DependencyViolation(
                        relative,
                        source_classification,
                        imported,
                        "external",
                        "external_prefix_not_allowed",
                    )
                )
    return G2DependencyAudit(
        discovered_files=discovered,
        classified_files=tuple(sorted(paths)),
        unclassified_files=unclassified,
        missing_manifest_files=missing,
        canonical_imports=tuple(sorted(canonical_by_file)),
        dependency_violations=tuple(violations),
        path_classification_violations=tuple(sorted(set(path_violations))),
        production_try_statement_count=try_count,
        production_random_call_count=random_count,
    )

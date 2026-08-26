"""Manifest-complete dependency audit for the HF-v2 candidate package."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_IMPORT_PREFIXES = (
    "h5py",
    "matplotlib",
    "pandas",
    "streamlit",
    "ypendulum.analysis",
    "ypendulum.hf.validation",
    "ypendulum.io",
    "ypendulum.ui",
)

FORBIDDEN_SOLVER_IMPORT_PREFIXES = (
    "scipy.integrate",
    "scipy.optimize",
)


@dataclass(frozen=True)
class ArchitectureAudit:
    discovered_files: tuple[str, ...]
    classified_files: tuple[str, ...]
    files: tuple[str, ...]
    unclassified_files: tuple[str, ...]
    missing_manifest_files: tuple[str, ...]
    imports: tuple[str, ...]
    forbidden_imports: tuple[str, ...]
    try_statement_count: int
    random_call_count: int
    solver_imports: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            not self.unclassified_files
            and not self.missing_manifest_files
            and not self.forbidden_imports
            and self.try_statement_count == 0
            and self.random_call_count == 0
            and not self.solver_imports
        )


def _module_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append(node.module)
    return names


def _call_name(node: ast.Call) -> str:
    parts: list[str] = []
    value: ast.expr = node.func
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def _manifest_entries(
    path: Path,
) -> tuple[tuple[dict[str, object], ...], frozenset[str]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    modules = document.get("modules")
    if not isinstance(modules, list):
        raise ValueError("Module manifest must contain a modules list.")
    if any(not isinstance(entry, dict) for entry in modules):
        raise ValueError("Every module-manifest entry must be an object.")
    entries: tuple[dict[str, object], ...] = tuple(modules)
    paths = [entry.get("path") for entry in entries]
    if any(not isinstance(relative, str) or not relative for relative in paths):
        raise ValueError("Every module-manifest entry must have a non-empty path.")
    if len(paths) != len(set(paths)):
        raise ValueError("Module-manifest paths must be unique.")
    classifications = document.get("classifications")
    scan_classifications = document.get("architecture_scan_classifications")
    if (
        not isinstance(classifications, list)
        or not classifications
        or any(not isinstance(value, str) or not value for value in classifications)
        or len(classifications) != len(set(classifications))
    ):
        raise ValueError("Module manifest must declare unique classification names.")
    if (
        not isinstance(scan_classifications, list)
        or any(value not in classifications for value in scan_classifications)
    ):
        raise ValueError("Architecture-scan classifications must be declared classifications.")
    if any(entry.get("classification") not in classifications for entry in entries):
        raise ValueError("Every module must use one declared classification.")
    return entries, frozenset(scan_classifications)


def audit_physical_core(
    source_root: str | Path, module_manifest: str | Path
) -> ArchitectureAudit:
    """Audit every discovered package module against an explicit classification.

    The manifest determines which classifications belong to the dependency-clean
    production core.  Auto-discovery is independent of that list, so a newly
    added but unclassified Python module fails the audit instead of bypassing it.
    """

    root = Path(source_root)
    entries, scan_classifications = _manifest_entries(Path(module_manifest))
    discovered = tuple(
        sorted(path.relative_to(root).as_posix() for path in root.rglob("*.py"))
    )
    classified = tuple(sorted(str(entry["path"]) for entry in entries))
    discovered_set = set(discovered)
    classified_set = set(classified)
    unclassified = tuple(sorted(discovered_set - classified_set))
    missing = tuple(sorted(classified_set - discovered_set))
    scanned = tuple(
        sorted(
            str(entry["path"])
            for entry in entries
            if entry["classification"] in scan_classifications
            and str(entry["path"]) in discovered_set
        )
    )

    imports: list[str] = []
    try_count = 0
    random_count = 0
    for relative in scanned:
        path = root / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports.extend(_module_names(tree))
        try_count += sum(isinstance(node, ast.Try) for node in ast.walk(tree))
        random_count += sum(
            "random" in _call_name(node).split(".")
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        )
    unique_imports = tuple(sorted(set(imports)))
    forbidden = tuple(
        name
        for name in unique_imports
        if any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in FORBIDDEN_IMPORT_PREFIXES
        )
    )
    solver_imports = tuple(
        name
        for name in unique_imports
        if any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in FORBIDDEN_SOLVER_IMPORT_PREFIXES
        )
    )
    return ArchitectureAudit(
        discovered_files=discovered,
        classified_files=classified,
        files=scanned,
        unclassified_files=unclassified,
        missing_manifest_files=missing,
        imports=unique_imports,
        forbidden_imports=forbidden,
        try_statement_count=try_count,
        random_call_count=random_count,
        solver_imports=solver_imports,
    )

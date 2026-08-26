"""Static dependency and no-silent-fallback audit for physical-core modules."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

PHYSICAL_CORE_FILES = (
    "topology.py",
    "state.py",
    "mass.py",
    "loads.py",
    "constitutive/axial.py",
    "constitutive/bending.py",
    "rigid/rotation.py",
    "rigid/attachment.py",
)

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
    files: tuple[str, ...]
    imports: tuple[str, ...]
    forbidden_imports: tuple[str, ...]
    try_statement_count: int
    random_call_count: int
    solver_imports: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            not self.forbidden_imports
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


def audit_physical_core(source_root: str | Path) -> ArchitectureAudit:
    root = Path(source_root)
    imports: list[str] = []
    try_count = 0
    random_count = 0
    for relative in PHYSICAL_CORE_FILES:
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
            name == prefix or name.startswith(f"{prefix}.") for prefix in FORBIDDEN_IMPORT_PREFIXES
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
        files=PHYSICAL_CORE_FILES,
        imports=unique_imports,
        forbidden_imports=forbidden,
        try_statement_count=try_count,
        random_call_count=random_count,
        solver_imports=solver_imports,
    )

"""Read-only adapters to the repository's formal forward package."""

from __future__ import annotations

import importlib
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

FORMAL_FORWARD_RELATIVE = Path("02_模拟程序/01_前向预测数值求解器/y_pendulum_forward_solver")

TORUS_READY = "READY_FOR_FORMAL_RUN"
TORUS_INCOMPATIBLE = "TORUS_INPUT_OR_DOMAIN_INCOMPATIBLE"
CABLE_INCOMPLETE = "FWD_CABLE_INPUT_INCOMPLETE"
ADAPTER_LIMITATION = "ADAPTER_LIMITATION_MEASURED_INITIAL_STATE_NOT_REPRESENTABLE"

CABLE_REQUIRED_FIELDS = {
    "support_motion",
    "branch_unloaded_lengths",
    "branch_linear_density",
    "axial_stiffness",
    "axial_damping",
    "bob_mass",
    "junction_mass",
    "initial_centerlines",
    "initial_velocity_fields",
    "air_drag",
    "external_fields",
}


class FormalAdapterError(RuntimeError):
    pass


def _formal_root(repository_root: Path) -> Path:
    root = repository_root.resolve() / FORMAL_FORWARD_RELATIVE
    if not (root / "y_pendulum_forward" / "__init__.py").is_file():
        raise FormalAdapterError(f"formal forward package not found: {root}")
    return root


def _hash_formal_tree(root: Path) -> str:
    paths = [
        *sorted((root / "y_pendulum_forward").glob("*.py")),
        root / "run.py",
        root / "pyproject.toml",
        root / "requirements.txt",
    ]
    digest = sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_formal_forward(repository_root: Path):
    formal_root = _formal_root(repository_root)
    previous_path = list(sys.path)
    try:
        sys.path.insert(0, str(formal_root))
        module = importlib.import_module("y_pendulum_forward")
    finally:
        sys.path[:] = previous_path
    actual = Path(module.__file__).resolve()
    if formal_root not in actual.parents:
        raise FormalAdapterError(f"wrong y_pendulum_forward imported: {actual}")
    for name in ("run_config", "run_ensemble", "SimulationResult", "THEORY_SHA256"):
        if not hasattr(module, name):
            raise FormalAdapterError(f"formal package lacks public symbol: {name}")
    return module


def formal_identity(repository_root: Path) -> dict[str, str]:
    formal_root = _formal_root(repository_root)
    module = load_formal_forward(repository_root)
    return {
        "formal_package_path": FORMAL_FORWARD_RELATIVE.as_posix(),
        "program_version": str(module.PROGRAM_VERSION),
        "theory_sha256": str(module.THEORY_SHA256),
        "formal_source_sha256": _hash_formal_tree(formal_root),
    }


def run_formal_config(repository_root: Path, config: dict[str, Any]):
    return load_formal_forward(repository_root).run_config(config)


def run_formal_ensemble(repository_root: Path, specification: dict[str, Any]):
    return load_formal_forward(repository_root).run_ensemble(specification)


def torus_compatibility(binding: dict[str, Any]) -> str:
    required_true = (
        "geometry_embedding_compatible",
        "initial_state_mappable",
        "no_slack_or_contact_in_window",
    )
    if not all(binding.get(key) is True for key in required_true):
        return TORUS_INCOMPATIBLE
    residual = binding.get("mapping_residual")
    uncertainty = binding.get("mapping_standard_uncertainty")
    if not all(isinstance(value, (int, float)) for value in (residual, uncertainty)):
        return TORUS_INCOMPATIBLE
    if float(uncertainty) <= 0 or abs(float(residual)) > float(uncertainty):
        return TORUS_INCOMPATIBLE
    return TORUS_READY


def cable_compatibility(binding: dict[str, Any]) -> tuple[str, list[str]]:
    sources = binding.get("parameter_sources", {})
    purpose = binding.get("purpose")
    allowed_sources = {
        "EXPERIMENT_COMPARISON": {"MEASURED", "DERIVED_FROM_MEASURED"},
        "SENSITIVITY_ONLY": {
            "MEASURED",
            "DERIVED_FROM_MEASURED",
            "ASSUMPTION_SENSITIVITY_ONLY",
        },
    }
    missing = sorted(CABLE_REQUIRED_FIELDS - set(sources))
    if purpose not in allowed_sources:
        missing.append("purpose:INVALID_OR_MISSING")
        valid_sources: set[str] = set()
    else:
        valid_sources = allowed_sources[purpose]
    invalid_sources = sorted(
        key
        for key, value in sources.items()
        if key in CABLE_REQUIRED_FIELDS and value not in valid_sources
    )
    missing.extend(f"{key}:INVALID_SOURCE" for key in invalid_sources)
    if binding.get("initial_state_representable") is False:
        return ADAPTER_LIMITATION, sorted(set(missing))
    if missing:
        return CABLE_INCOMPLETE, sorted(set(missing))
    return TORUS_READY, []


def model_input_binding(
    repository_root: Path,
    *,
    model_id: str,
    purpose: str,
    parameter_sources: dict[str, str],
    compatibility_status: str,
    missing_fields: list[str],
) -> dict[str, Any]:
    identity = formal_identity(repository_root)
    return {
        "schema_id": "YPS-E0-MODEL-INPUT-BINDING-1.0",
        "model_id": model_id,
        "purpose": purpose,
        "formal_package_path": identity["formal_package_path"],
        "formal_source_sha256": identity["formal_source_sha256"],
        "parameter_sources": dict(parameter_sources),
        "compatibility_status": compatibility_status,
        "missing_fields": list(missing_fields),
    }

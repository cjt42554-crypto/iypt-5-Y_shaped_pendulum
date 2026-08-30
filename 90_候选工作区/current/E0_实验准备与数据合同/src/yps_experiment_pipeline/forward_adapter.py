"""Read-only adapters to the repository's formal forward package."""

from __future__ import annotations

import importlib
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

from .contracts import sha256_document

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


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def torus_compatibility(binding: dict[str, Any]) -> str:
    evidence = binding.get("torus_evidence")
    if evidence is None:
        evidence = binding.get("compatibility_evidence", {}).get("torus")
    if not isinstance(evidence, dict):
        return TORUS_INCOMPATIBLE
    for key in ("geometry_embedding", "initial_state_mapping", "domain_window"):
        check = evidence.get(key)
        if (
            not isinstance(check, dict)
            or check.get("decision") is not True
            or not _is_sha256(check.get("evidence_sha256"))
        ):
            return TORUS_INCOMPATIBLE
    residual = evidence.get("mapping_residual")
    uncertainty = evidence.get("mapping_standard_uncertainty")
    if not all(isinstance(value, (int, float)) for value in (residual, uncertainty)):
        return TORUS_INCOMPATIBLE
    if float(uncertainty) <= 0 or abs(float(residual)) > float(uncertainty):
        return TORUS_INCOMPATIBLE
    return TORUS_READY


def cable_compatibility(binding: dict[str, Any]) -> tuple[str, list[str]]:
    raw_bindings = binding.get("parameter_bindings")
    if not isinstance(raw_bindings, list):
        raw_bindings = []
    sources: dict[str, str] = {}
    provenance_invalid: list[str] = []
    for record in raw_bindings:
        if not isinstance(record, dict) or not isinstance(record.get("parameter_name"), str):
            provenance_invalid.append("parameter_binding:INVALID_RECORD")
            continue
        name = record["parameter_name"]
        if name in sources:
            provenance_invalid.append(f"{name}:DUPLICATE_BINDING")
            continue
        sources[name] = str(record.get("source_type"))
        measurement_ids = record.get("measurement_ids")
        source_type = record.get("source_type")
        if not (
            _is_sha256(record.get("measurement_bundle_sha256"))
            and _is_sha256(record.get("source_record_sha256"))
            and isinstance(measurement_ids, list)
        ):
            provenance_invalid.append(f"{name}:INVALID_PROVENANCE")
        elif source_type in {"MEASURED", "DERIVED_FROM_MEASURED"} and not measurement_ids:
            provenance_invalid.append(f"{name}:MISSING_MEASUREMENT_IDS")
        elif source_type == "DERIVED_FROM_MEASURED" and not _is_sha256(
            record.get("derivation_sha256")
        ):
            provenance_invalid.append(f"{name}:MISSING_DERIVATION_HASH")
    purpose = binding.get("purpose")
    allowed_sources = {
        "EXPERIMENT_COMPARISON": {"MEASURED", "DERIVED_FROM_MEASURED"},
        "SENSITIVITY_ONLY": {
            "MEASURED",
            "DERIVED_FROM_MEASURED",
            "ASSUMPTION_SENSITIVITY_ONLY",
        },
        "SYNTHETIC_CONTRACT_TEST": {"SYNTHETIC_REAL_SHAPE_FIXTURE"},
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
    missing.extend(provenance_invalid)
    evidence = binding.get("cable_evidence")
    if evidence is None:
        evidence = binding.get("compatibility_evidence", {}).get("cable")
    if not isinstance(evidence, dict):
        missing.append("cable_evidence:MISSING")
        return CABLE_INCOMPLETE, sorted(set(missing))
    if not (
        _is_sha256(evidence.get("input_completeness_sha256"))
        and _is_sha256(evidence.get("initial_state_evidence_sha256"))
    ):
        missing.append("cable_evidence:INVALID_HASH_BINDING")
    if evidence.get("initial_state_representable") is False:
        return ADAPTER_LIMITATION, sorted(set(missing))
    if missing:
        return CABLE_INCOMPLETE, sorted(set(missing))
    return TORUS_READY, []


def model_input_binding(
    repository_root: Path,
    *,
    model_id: str,
    purpose: str,
    measurement_document: dict[str, Any],
    measurement_bundle_sha256: str,
    trajectory_bundle_sha256: str,
    parameter_bindings: list[dict[str, Any]],
    compatibility_evidence: dict[str, Any],
    compatibility_status: str,
    missing_fields: list[str],
) -> dict[str, Any]:
    identity = formal_identity(repository_root)
    names = [record.get("parameter_name") for record in parameter_bindings]
    if len(names) != len(set(names)):
        raise FormalAdapterError("parameter bindings must have unique names")
    if not (_is_sha256(measurement_bundle_sha256) and _is_sha256(trajectory_bundle_sha256)):
        raise FormalAdapterError("model input bundles require SHA-256 identities")
    if sha256_document(measurement_document) != measurement_bundle_sha256:
        raise FormalAdapterError("measurement document does not match its declared bundle hash")
    measurement_records = {
        record.get("measurement_id"): record
        for record in measurement_document.get("measurements", [])
        if isinstance(record, dict) and isinstance(record.get("measurement_id"), str)
    }
    if any(
        record.get("measurement_bundle_sha256") != measurement_bundle_sha256
        for record in parameter_bindings
    ):
        raise FormalAdapterError("parameter binding does not match the measurement bundle")
    for binding in parameter_bindings:
        measurement_ids = binding.get("measurement_ids")
        if not isinstance(measurement_ids, list):
            raise FormalAdapterError("parameter binding measurement_ids must be a list")
        missing_ids = sorted(set(measurement_ids) - set(measurement_records))
        if missing_ids:
            raise FormalAdapterError(
                f"parameter binding cites absent measurement IDs: {missing_ids}"
            )
        selected = [measurement_records[measurement_id] for measurement_id in measurement_ids]
        source_type = binding.get("source_type")
        if source_type == "MEASURED" and any(
            record.get("source_type") != "MEASURED" for record in selected
        ):
            raise FormalAdapterError("MEASURED parameter binding cites a non-measured record")
        if source_type == "SYNTHETIC_REAL_SHAPE_FIXTURE" and any(
            record.get("source_type") != "SYNTHETIC_REAL_SHAPE_FIXTURE" for record in selected
        ):
            raise FormalAdapterError("synthetic parameter binding cites a non-synthetic record")
        if source_type in {"MEASURED", "DERIVED_FROM_MEASURED", "SYNTHETIC_REAL_SHAPE_FIXTURE"}:
            expected_record_hash = sha256_document(selected)
            if binding.get("source_record_sha256") != expected_record_hash:
                raise FormalAdapterError(
                    "parameter source record hash does not match cited records"
                )
    return {
        "schema_id": "YPS-E0-MODEL-INPUT-BINDING-1.1",
        "model_id": model_id,
        "purpose": purpose,
        "formal_package_path": identity["formal_package_path"],
        "formal_source_sha256": identity["formal_source_sha256"],
        "measurement_bundle_sha256": measurement_bundle_sha256,
        "trajectory_bundle_sha256": trajectory_bundle_sha256,
        "parameter_bindings": [dict(record) for record in parameter_bindings],
        "compatibility_evidence": compatibility_evidence,
        "compatibility_evidence_sha256": sha256_document(compatibility_evidence),
        "compatibility_status": compatibility_status,
        "missing_fields": list(missing_fields),
    }

"""Strict shared-input contract for two physically distinct Y-pendulum backends."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ypendulum.config import (
    SimulationConfig,
    load_config,
    load_unique_yaml,
    resolved_config_dict,
)
from ypendulum.config.units import as_vector3, to_si

_SCHEMA = "YPS-UNIFIED-CASE-1.0"
_PROBLEM_ID = "IYPT-2027-05-Y-PENDULUM"
_FORWARD_MODEL = "FWD-CABLE-1.0"
_HF_MODEL = "HF-DISCRETE-ROD-RIGID-BOB-1.0"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _unique_json(path: Path) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"Duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-finite JSON constant in {path}: {value}")

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=pairs,
        parse_constant=reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _resolve(base: Path, value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty path string.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    if not path.is_file() and name != "forward.project_root":
        raise FileNotFoundError(f"{name} does not exist: {path}")
    if name == "forward.project_root" and not path.is_dir():
        raise FileNotFoundError(f"{name} is not a directory: {path}")
    return path


def _resolve_beneath(root: Path, value: Any, name: str) -> Path:
    """Resolve one manifest path without permitting an absolute/path traversal escape."""

    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f"{name} must be a non-empty relative path.")
    root = root.resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"{name} escapes its frozen scope root: {value}")
    if not path.is_file():
        raise FileNotFoundError(f"{name} does not exist: {path}")
    return path


def _file_identity(path: Path) -> tuple[int, str]:
    return path.stat().st_size, _sha256_file(path)


def _forward_source_hash(files: tuple[tuple[str, bytes], ...]) -> str:
    digest = hashlib.sha256()
    for relative, payload in sorted(files):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def _forward_chain_snapshot_sha256(chain: dict[str, Any]) -> str:
    return _canonical_hash(
        {
            "delivery_root_sha256": chain["delivery_root_sha256"],
            "artifact_manifest_sha256": chain["artifact_manifest_sha256"],
            "verified_payloads": chain["verified_payloads"],
            "verified_files": chain["verified_files"],
            "source_tree_sha256": chain["source_tree_sha256"],
            "config_canonical_sha256": chain["config_canonical_sha256"],
            "config_file_sha256": chain["config_file_sha256"],
            "config_relative_path": chain["config_relative_path"],
            "config_bytes_sha256": hashlib.sha256(chain["config_bytes"]).hexdigest(),
            "dispatch": [
                {
                    "path": path,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                for path, payload in chain["dispatch_files"]
            ],
            "frozen_theory_sha256": chain["frozen_theory_sha256"],
            "numerical_theory_sha256": chain["numerical_theory_sha256"],
        }
    )


def _forward_delivery_chain(
    project_root: Path,
    delivery_root_path: Path,
    expected_delivery_root_sha256: str,
    forward_config_path: Path,
) -> dict[str, Any]:
    """Verify the complete frozen Stage-2 chain and capture executable bytes.

    The Stage-2 delivery root explicitly requires
    ``delivery_root -> payload_roots -> artifact_manifest -> every file``.
    Merely hashing ``delivery_root.json`` is not sufficient because it does not
    authenticate any file that is actually executed.
    """

    if not isinstance(expected_delivery_root_sha256, str) or len(
        expected_delivery_root_sha256
    ) != 64:
        raise ValueError("forward.expected_delivery_root_sha256 must be a SHA-256 string.")
    delivery_bytes, delivery_sha = _file_identity(delivery_root_path)
    if delivery_sha != expected_delivery_root_sha256:
        raise ValueError("forward delivery root SHA-256 does not match the unified case.")
    root = _unique_json(delivery_root_path)
    if root.get("schema_version") != "YPS-FWD-DELIVERY-ROOT-1.0":
        raise ValueError("Unsupported frozen forward delivery-root schema.")
    if root.get("stage") != "forward_numerical_computation_stage_2":
        raise ValueError("Forward delivery root is not the frozen Stage-2 delivery.")
    if root.get("gate_status") != "READY_FOR_INDEPENDENT_READ_ONLY_GATE":
        raise ValueError("Forward delivery root is not ready for independent use.")
    scope_value = root.get("scope_root")
    if not isinstance(scope_value, str):
        raise ValueError("Forward delivery root lacks a finite scope_root identity.")
    scope_root = Path(scope_value).expanduser().resolve()
    if not scope_root.is_dir() or not project_root.resolve().is_relative_to(scope_root):
        raise ValueError("Forward project root is outside the frozen delivery scope.")

    payload_roots = root.get("payload_roots")
    if not isinstance(payload_roots, list) or len(payload_roots) < 2:
        raise ValueError("Forward delivery root lacks its required payload roots.")
    verified_payloads: list[dict[str, Any]] = []
    artifact_paths: list[Path] = []
    for index, entry in enumerate(payload_roots):
        if not isinstance(entry, dict):
            raise ValueError("Forward payload-root entry must be an object.")
        path = _resolve_beneath(scope_root, entry.get("path"), f"payload_roots[{index}]")
        actual_bytes, actual_sha = _file_identity(path)
        if entry.get("bytes") != actual_bytes or entry.get("sha256") != actual_sha:
            raise ValueError(f"Forward payload-root identity mismatch: {path}")
        verified_payloads.append(
            {"path": str(path), "bytes": actual_bytes, "sha256": actual_sha}
        )
        if path.name == "artifact_manifest.json":
            artifact_paths.append(path)
    if len(artifact_paths) != 1:
        raise ValueError("Forward delivery must bind exactly one artifact manifest.")

    artifact_path = artifact_paths[0]
    artifact = _unique_json(artifact_path)
    entries = artifact.get("files")
    if not isinstance(entries, list) or artifact.get("file_count") != len(entries):
        raise ValueError("Forward artifact manifest file_count is not closed.")
    verified_files: list[tuple[str, int, str]] = []
    paths_seen: set[str] = set()
    manifest_by_path: dict[Path, tuple[int, str]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError("Forward artifact-manifest entry must be an object.")
        relative = entry.get("path")
        if not isinstance(relative, str) or relative in paths_seen:
            raise ValueError("Forward artifact manifest contains a duplicate/invalid path.")
        paths_seen.add(relative)
        path = _resolve_beneath(scope_root, relative, f"artifact.files[{index}]")
        actual_bytes, actual_sha = _file_identity(path)
        if entry.get("bytes") != actual_bytes or entry.get("sha256") != actual_sha:
            raise ValueError(f"Forward artifact identity mismatch: {path}")
        verified_files.append((str(path), actual_bytes, actual_sha))
        manifest_by_path[path] = (actual_bytes, actual_sha)

    forward_config_path = forward_config_path.resolve()
    if forward_config_path not in manifest_by_path:
        raise ValueError("The selected forward config is not in the frozen artifact manifest.")
    forward_config = _unique_json(forward_config_path)
    config_canonical_sha = _canonical_hash(forward_config)
    production_hashes = root.get("production_config_sha256")
    if not isinstance(production_hashes, dict) or production_hashes.get(
        _FORWARD_MODEL
    ) != config_canonical_sha:
        raise ValueError("Forward config is not the qualified production configuration.")

    executable_paths = [
        *sorted((project_root / "y_pendulum_forward").glob("*.py")),
        project_root / "run.py",
        project_root / "pyproject.toml",
        project_root / "requirements.txt",
    ]
    dispatch_files: list[tuple[str, bytes]] = []
    for path in executable_paths:
        resolved_path = path.resolve()
        if resolved_path not in manifest_by_path:
            raise ValueError(f"Forward executable is not frozen by the manifest: {path}")
        dispatch_files.append(
            (resolved_path.relative_to(project_root.resolve()).as_posix(), path.read_bytes())
        )
    dispatch_tuple = tuple(dispatch_files)
    source_sha = _forward_source_hash(dispatch_tuple)
    if source_sha != root.get("source_tree_sha256"):
        raise ValueError("Forward executable source-tree hash disagrees with delivery root.")
    if root.get("frozen_theory_sha256") != _unique_json(forward_config_path).get(
        "theory_sha256"
    ):
        raise ValueError("Forward config theory identity disagrees with delivery root.")

    return {
        "delivery_root_sha256": delivery_sha,
        "delivery_root_bytes": delivery_bytes,
        "delivery_root_payload": root,
        "scope_root": str(scope_root),
        "artifact_manifest_path": str(artifact_path),
        "artifact_manifest_sha256": _sha256_file(artifact_path),
        "verified_payloads": tuple(
            (item["path"], item["bytes"], item["sha256"])
            for item in verified_payloads
        ),
        "verified_files": tuple(verified_files),
        "dispatch_files": dispatch_tuple,
        "source_tree_sha256": source_sha,
        "config_canonical_sha256": config_canonical_sha,
        "config_file_sha256": _sha256_file(forward_config_path),
        "config_relative_path": forward_config_path.relative_to(
            project_root.resolve()
        ).as_posix(),
        "config_bytes": forward_config_path.read_bytes(),
        "frozen_theory_sha256": root["frozen_theory_sha256"],
        "numerical_theory_sha256": root["numerical_theory_sha256"],
    }


def _finite_array(value: Any) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(array)):
        raise ValueError("Shared-input comparison encountered a non-finite value.")
    return array


def _high_fidelity_auxiliary_files(
    config: SimulationConfig,
) -> tuple[tuple[str, int, str], ...]:
    """Freeze every external file consumed by the resolved HF configuration."""

    if config.source_path is None:
        raise ValueError("Unified HF config must retain its source path.")
    base = Path(config.source_path).resolve().parent
    values: list[tuple[str, str | None]] = [
        ("run.validation_manifest", config.run.validation_manifest),
        ("initial_condition.state_file", config.initial_condition.state_file),
        ("initial_condition.positions_file", config.initial_condition.positions_file),
        ("initial_condition.velocities_file", config.initial_condition.velocities_file),
    ]
    for support_name in ("A", "B"):
        support = getattr(config.supports, support_name)
        values.append(
            (
                f"supports.{support_name}.motion.table_file",
                None if support.motion is None else support.motion.table_file,
            )
        )
    for branch_name in ("upper_A", "upper_B", "lower"):
        branch = getattr(config.cables, branch_name)
        values.append((f"cables.{branch_name}.table_file", branch.table_file))
    identities: list[tuple[str, int, str]] = []
    seen: set[Path] = set()
    for field, value in values:
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty path string when present.")
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = base / path
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Unified HF auxiliary input does not exist: {path}")
        if path in seen:
            continue
        seen.add(path)
        size, sha = _file_identity(path)
        identities.append((str(path), size, sha))
    return tuple(sorted(identities))


def _shared_input_audit(
    forward: dict[str, Any], hf: SimulationConfig
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add_semantic(
        field: str,
        forward_value: Any,
        hf_value: Any,
        expected_relation: str,
        passed: bool,
    ) -> None:
        checks.append(
            {
                "field": field,
                "unit": "semantic",
                "forward_value": forward_value,
                "high_fidelity_value": hf_value,
                "expected_relation": expected_relation,
                "passed": bool(passed),
            }
        )

    def add(
        field: str,
        forward_value: Any,
        hf_value: Any,
        unit: str,
        *,
        atol: float = 1.0e-12,
        rtol: float = 1.0e-10,
    ) -> None:
        left = _finite_array(forward_value)
        right = _finite_array(hf_value)
        same_shape = left.shape == right.shape
        error = (
            float(np.max(np.abs(left - right)))
            if same_shape and left.size
            else (0.0 if same_shape else float("inf"))
        )
        scale = max(
            float(np.max(np.abs(left))) if left.size else 0.0,
            float(np.max(np.abs(right))) if right.size else 0.0,
        )
        tolerance = atol + rtol * scale
        checks.append(
            {
                "field": field,
                "unit": unit,
                "forward_value": left.tolist() if left.ndim else float(left),
                "high_fidelity_value": right.tolist() if right.ndim else float(right),
                "maximum_absolute_error": error,
                "tolerance": tolerance,
                "passed": same_shape and error <= tolerance,
            }
        )

    physical = forward["physical"]
    inputs = forward["inputs"]
    initial = forward["initial_state"]
    add_semantic(
        "support_A.activation",
        inputs["support_A"].get("kind"),
        {"type": hf.supports.A.type, "motion_is_none": hf.supports.A.motion is None},
        "FWD constant provider <=> HF fixed support without a motion provider",
        inputs["support_A"].get("kind") == "constant"
        and hf.supports.A.type == "fixed"
        and hf.supports.A.motion is None,
    )
    add_semantic(
        "support_B.activation",
        inputs["support_B"].get("kind"),
        {"type": hf.supports.B.type, "motion_is_none": hf.supports.B.motion is None},
        "FWD constant provider <=> HF fixed support without a motion provider",
        inputs["support_B"].get("kind") == "constant"
        and hf.supports.B.type == "fixed"
        and hf.supports.B.motion is None,
    )
    add_semantic(
        "air_velocity.activation",
        inputs["air_velocity"].get("kind"),
        "constant zero vector",
        "FWD zero provider <=> HF finite zero air velocity",
        inputs["air_velocity"].get("kind") == "zero"
        and np.array_equal(
            as_vector3(hf.environment.air_velocity, default_unit="m/s"),
            np.zeros(3),
        ),
    )
    for force_name, provider in (
        ("junction_force", inputs["junction_force"]),
        ("bob_force", inputs["bob_force"]),
        *(
            (f"distributed_force.{name}", inputs["distributed_forces"][name])
            for name in ("A", "B", "lower")
        ),
    ):
        add_semantic(
            f"{force_name}.activation",
            provider.get("kind"),
            "no corresponding HF external-force provider",
            "FWD provider must be identically zero when HF has no mapped provider",
            provider.get("kind") == "zero",
        )
    add(
        "gravity_vector",
        float(physical["g"]) * _finite_array(physical["e_z"]),
        as_vector3(hf.environment.gravity, default_unit="m/s^2"),
        "m/s^2",
    )
    add(
        "support_A_position",
        inputs["support_A"]["value"],
        as_vector3(hf.supports.A.position, default_unit="m"),
        "m",
    )
    add(
        "support_B_position",
        inputs["support_B"]["value"],
        as_vector3(hf.supports.B.position, default_unit="m"),
        "m",
    )
    add("junction_mass", physical["junction_mass"], to_si(hf.junction.mass, default_unit="kg"), "kg")
    add("bob_mass", physical["bob_mass"], to_si(hf.bob.mass, default_unit="kg"), "kg")
    add("air_density", physical["rho_air"], to_si(hf.environment.air_density, default_unit="kg/m^3"), "kg/m^3")
    add("air_velocity", [0.0, 0.0, 0.0], as_vector3(hf.environment.air_velocity, default_unit="m/s"), "m/s")

    bob_radius = float(to_si(hf.bob.radius, default_unit="m"))
    bob_area = np.pi * bob_radius**2
    expected_bob_drag_model = (
        "quadratic_plus_linear"
        if float(physical["bob_c1"]) > 0.0 and float(physical["bob_c2"]) > 0.0
        else ("linear" if float(physical["bob_c1"]) > 0.0 else "quadratic")
    )
    add_semantic(
        "bob.buoyancy.activation",
        {"rho_air": physical["rho_air"], "bob_volume": physical["bob_volume"]},
        hf.bob.buoyancy,
        "HF buoyancy must be enabled for the FWD displaced-volume buoyancy term",
        hf.bob.buoyancy is True,
    )
    add_semantic(
        "bob.drag.activation",
        {
            "linear_nonzero": float(physical["bob_c1"]) > 0.0,
            "quadratic_nonzero": float(physical["bob_c2"]) > 0.0,
        },
        {"enabled": hf.bob.drag.enabled, "model": hf.bob.drag.model},
        "HF drag switch/model must activate exactly the FWD linear/quadratic terms",
        hf.bob.drag.enabled
        and hf.bob.drag.model == expected_bob_drag_model,
    )
    add("bob_volume", physical["bob_volume"], 4.0 * np.pi * bob_radius**3 / 3.0, "m^3")
    add(
        "bob_linear_drag",
        physical["bob_c1"],
        to_si(hf.bob.drag.linear_coefficient, default_unit="N*s/m"),
        "N*s/m",
    )
    add(
        "bob_quadratic_drag_coefficient",
        physical["bob_c2"],
        0.5
        * float(to_si(hf.environment.air_density, default_unit="kg/m^3"))
        * float(to_si(hf.bob.drag.cd, default_unit="dimensionless"))
        * bob_area,
        "kg/m",
    )

    branch_map = {"A": "upper_A", "B": "upper_B", "lower": "lower"}
    for forward_name, hf_name in branch_map.items():
        f_branch = physical["branches"][forward_name]
        h_branch = getattr(hf.cables, hf_name)
        diameter = float(to_si(h_branch.diameter, default_unit="m"))
        area = np.pi * diameter**2 / 4.0
        rho = float(to_si(h_branch.density, default_unit="kg/m^3"))
        young = float(to_si(h_branch.young_modulus, default_unit="Pa"))
        viscosity = float(to_si(h_branch.axial_viscosity, default_unit="Pa*s"))
        prefix = f"branch.{forward_name}"
        expected_drag_enabled = any(
            float(f_branch[name]) > 0.0
            for name in ("c_parallel", "c_perp", "d_parallel", "d_perp")
        )
        add_semantic(
            f"{prefix}.drag.activation",
            expected_drag_enabled,
            h_branch.drag_enabled,
            "HF branch drag switch must activate all mapped FWD drag coefficients",
            h_branch.drag_enabled is expected_drag_enabled,
        )
        add(f"{prefix}.rest_length", f_branch["L0"], to_si(h_branch.rest_length, default_unit="m"), "m")
        add(f"{prefix}.linear_density", f_branch["mu"], rho * area, "kg/m")
        add(f"{prefix}.EA", f_branch["EA"], young * area, "N")
        add(f"{prefix}.Ca", f_branch["Ca"], viscosity * area, "N*s")
        add(
            f"{prefix}.linear_drag_parallel",
            f_branch["c_parallel"],
            to_si(h_branch.drag_linear_tangent_per_length, default_unit="N*s/m^2"),
            "N*s/m^2",
        )
        add(
            f"{prefix}.linear_drag_perpendicular",
            f_branch["c_perp"],
            to_si(h_branch.drag_linear_normal_per_length, default_unit="N*s/m^2"),
            "N*s/m^2",
        )
        air_density = float(to_si(hf.environment.air_density, default_unit="kg/m^3"))
        add(
            f"{prefix}.quadratic_drag_parallel",
            f_branch["d_parallel"],
            0.5 * air_density * float(h_branch.drag_cd_tangent) * diameter,
            "kg/m^2",
        )
        add(
            f"{prefix}.quadratic_drag_perpendicular",
            f_branch["d_perp"],
            0.5 * air_density * float(h_branch.drag_cd_normal) * diameter,
            "kg/m^2",
        )

    add_semantic(
        "initial.protocol",
        initial.get("mode"),
        {
            "type": hf.initial_condition.type,
            "compression_regularization_scale": (
                hf.high_fidelity.compression_regularization_scale
            ),
            "controlled_limit_study": hf.high_fidelity.controlled_limit_study,
        },
        (
            "The frozen FWD complete cable state uses DIRECT_STATE while HF "
            "preserves the same J/bob state and independently equilibrates its "
            "additional rod material coordinates with the bilateral finite-rod law"
        ),
        initial.get("mode") == "DIRECT_STATE"
        and hf.initial_condition.type == "held_endpoint_equilibrium_release"
        and hf.high_fidelity.compression_regularization_scale == 1.0
        and not hf.high_fidelity.controlled_limit_study,
    )
    add("initial.junction_position", initial["r_J"], as_vector3(hf.initial_condition.junction_position, default_unit="m"), "m")
    add("initial.junction_velocity", initial["v_J"], as_vector3(hf.initial_condition.junction_velocity, default_unit="m/s"), "m/s")
    add("initial.bob_com_position", initial["r_m"], as_vector3(hf.initial_condition.bob_position, default_unit="m"), "m")
    add("initial.bob_com_velocity", initial["v_m"], as_vector3(hf.initial_condition.bob_velocity, default_unit="m/s"), "m/s")
    add("comparison_horizon", physical["T"], to_si(hf.solver.t_end, default_unit="s"), "s")
    return {
        "schema_version": "YPS-SHARED-INPUT-AUDIT-1.0",
        "passed": all(check["passed"] for check in checks),
        "check_count": len(checks),
        "checks": checks,
        "hf_only_fields": [
            "cable diameter and three-point bending stiffness",
            "finite bob radius, inertia, quaternion and eccentric attachment",
            "bob/rod and rod/rod clearance guards",
            "HF-specific numerical tolerances and accepted-step certificate",
        ],
        "forward_only_fields": [
            "activation regularisation delta",
            "material-domain and lambda guards",
            "FWD-specific P1 quadrature and convergence thresholds",
        ],
    }


@dataclass(frozen=True)
class ResolvedUnifiedCase:
    source_path: Path
    case_hash_sha256: str
    payload: dict[str, Any]
    forward_project_root: Path
    forward_config_path: Path
    forward_delivery_root_path: Path
    high_fidelity_config_path: Path
    high_fidelity_validation_spec_path: Path
    forward_config: dict[str, Any]
    high_fidelity_config: SimulationConfig
    shared_input_audit: dict[str, Any]
    case_file_sha256: str
    forward_chain: dict[str, Any]
    forward_chain_snapshot_sha256: str
    high_fidelity_config_file_sha256: str
    high_fidelity_config_bytes: bytes
    high_fidelity_validation_spec_file_sha256: str
    high_fidelity_validation_spec_bytes: bytes
    high_fidelity_resolved_config_sha256: str
    high_fidelity_auxiliary_files: tuple[tuple[str, int, str], ...]


def verify_unified_case_identities(case: ResolvedUnifiedCase) -> dict[str, Any]:
    """Re-verify every live input while retaining immutable dispatch bytes."""

    if _sha256_file(case.source_path) != case.case_file_sha256:
        raise RuntimeError("Unified case file drifted after it was loaded.")
    if _canonical_hash(case.payload) != case.case_hash_sha256:
        raise RuntimeError("In-memory unified case payload was mutated after loading.")
    if (
        _forward_chain_snapshot_sha256(case.forward_chain)
        != case.forward_chain_snapshot_sha256
    ):
        raise RuntimeError("In-memory frozen forward dispatch snapshot was mutated.")
    if _sha256_file(case.high_fidelity_config_path) != case.high_fidelity_config_file_sha256:
        raise RuntimeError("High-fidelity config drifted after the unified case was loaded.")
    if (
        _sha256_file(case.high_fidelity_validation_spec_path)
        != case.high_fidelity_validation_spec_file_sha256
    ):
        raise RuntimeError(
            "High-fidelity validation specification drifted after the unified "
            "case was loaded."
        )
    if (
        _canonical_hash(resolved_config_dict(case.high_fidelity_config))
        != case.high_fidelity_resolved_config_sha256
    ):
        raise RuntimeError("In-memory high-fidelity resolved config was mutated after loading.")
    if _high_fidelity_auxiliary_files(case.high_fidelity_config) != (
        case.high_fidelity_auxiliary_files
    ):
        raise RuntimeError("High-fidelity auxiliary input identity drifted after loading.")
    forward_block = case.payload["forward"]
    current = _forward_delivery_chain(
        case.forward_project_root,
        case.forward_delivery_root_path,
        forward_block["expected_delivery_root_sha256"],
        case.forward_config_path,
    )
    frozen = case.forward_chain
    compared = (
        "delivery_root_sha256",
        "artifact_manifest_sha256",
        "source_tree_sha256",
        "config_canonical_sha256",
        "config_file_sha256",
        "verified_payloads",
        "verified_files",
    )
    mismatches = [name for name in compared if current[name] != frozen[name]]
    if mismatches:
        raise RuntimeError(f"Frozen forward delivery chain drifted: {mismatches}")
    return {
        "case_file_sha256": case.case_file_sha256,
        "high_fidelity_config_file_sha256": case.high_fidelity_config_file_sha256,
        "high_fidelity_validation_spec_file_sha256": (
            case.high_fidelity_validation_spec_file_sha256
        ),
        "high_fidelity_resolved_config_sha256": (
            case.high_fidelity_resolved_config_sha256
        ),
        "high_fidelity_auxiliary_files": [
            {"path": path, "bytes": size, "sha256": sha}
            for path, size, sha in case.high_fidelity_auxiliary_files
        ],
        "forward_delivery_root_sha256": current["delivery_root_sha256"],
        "forward_artifact_manifest_sha256": current["artifact_manifest_sha256"],
        "forward_source_tree_sha256": current["source_tree_sha256"],
        "forward_config_file_sha256": current["config_file_sha256"],
        "forward_config_canonical_sha256": current["config_canonical_sha256"],
        "forward_verified_file_count": len(current["verified_files"]),
    }


def load_unified_case(value: str | Path) -> ResolvedUnifiedCase:
    source = Path(value).expanduser().resolve()
    raw = load_unique_yaml(source)
    required = {
        "schema_version",
        "problem_id",
        "units",
        "forward",
        "high_fidelity",
        "comparison",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise ValueError("Unified case must contain exactly the frozen top-level fields.")
    if raw["schema_version"] != _SCHEMA or raw["problem_id"] != _PROBLEM_ID:
        raise ValueError("Unified case schema/problem identity mismatch.")
    if raw["units"] != "SI":
        raise ValueError("Unified case currently requires units: SI.")
    forward_block = raw["forward"]
    hf_block = raw["high_fidelity"]
    comparison = raw["comparison"]
    if not isinstance(forward_block, dict) or set(forward_block) != {
        "project_root",
        "config",
        "delivery_root",
        "expected_config_file_sha256",
        "expected_delivery_root_sha256",
        "model_id",
    }:
        raise ValueError("Unified forward block does not match its frozen schema.")
    if not isinstance(hf_block, dict) or set(hf_block) != {
        "config",
        "expected_config_file_sha256",
        "validation_spec",
        "expected_validation_spec_file_sha256",
        "model_id",
    }:
        raise ValueError("Unified HF block does not match its frozen schema.")
    if not isinstance(comparison, dict) or set(comparison) != {
        "window_s",
        "observer_contract",
    }:
        raise ValueError("Unified comparison block does not match its frozen schema.")
    if comparison["observer_contract"] != "ORTHOGRAPHIC_XY_METRE-1.0":
        raise ValueError("Unsupported unified observer contract.")

    base = source.parent
    project_root = _resolve(base, forward_block["project_root"], "forward.project_root")
    forward_config_path = _resolve(project_root, forward_block["config"], "forward.config")
    forward_delivery_path = _resolve(
        project_root, forward_block["delivery_root"], "forward.delivery_root"
    )
    hf_config_path = _resolve(base, hf_block["config"], "high_fidelity.config")
    hf_validation_spec_path = _resolve(
        base,
        hf_block["validation_spec"],
        "high_fidelity.validation_spec",
    )
    identity_expectations = (
        (forward_config_path, forward_block["expected_config_file_sha256"], "forward config"),
        (forward_delivery_path, forward_block["expected_delivery_root_sha256"], "forward delivery root"),
        (hf_config_path, hf_block["expected_config_file_sha256"], "HF config"),
        (
            hf_validation_spec_path,
            hf_block["expected_validation_spec_file_sha256"],
            "HF validation specification",
        ),
    )
    for path, expected, name in identity_expectations:
        if not isinstance(expected, str) or _sha256_file(path) != expected:
            raise ValueError(f"{name} SHA-256 does not match the unified case.")
    forward_config = _unique_json(forward_config_path)
    hf_config = load_config(hf_config_path)
    hf_validation_spec = load_unique_yaml(hf_validation_spec_path)
    if not isinstance(hf_validation_spec, dict) or hf_validation_spec.get(
        "schema_version"
    ) != "YPS-HF-VALIDATION-1.0":
        raise ValueError("Unified HF validation specification identity mismatch.")
    if forward_block["model_id"] != _FORWARD_MODEL or forward_config.get("model_id") != _FORWARD_MODEL:
        raise ValueError("Unified forward backend must be FWD-CABLE-1.0.")
    if hf_block["model_id"] != _HF_MODEL or hf_config.high_fidelity.model_id != _HF_MODEL:
        raise ValueError("Unified HF backend model identity mismatch.")
    horizon = float(to_si(hf_config.solver.t_end, default_unit="s"))
    if not isinstance(comparison["window_s"], (int, float)) or isinstance(
        comparison["window_s"], bool
    ):
        raise ValueError("comparison.window_s must be a finite real number.")
    if not np.isfinite(float(comparison["window_s"])) or not np.isclose(
        float(comparison["window_s"]), horizon, rtol=0.0, atol=1.0e-14
    ):
        raise ValueError("Unified comparison window must equal the HF run horizon.")
    audit = _shared_input_audit(forward_config, hf_config)
    if not audit["passed"]:
        failed = [item["field"] for item in audit["checks"] if not item["passed"]]
        raise ValueError(f"Shared-input audit failed: {failed}")
    forward_chain = _forward_delivery_chain(
        project_root,
        forward_delivery_path,
        forward_block["expected_delivery_root_sha256"],
        forward_config_path,
    )
    return ResolvedUnifiedCase(
        source_path=source,
        case_hash_sha256=_canonical_hash(raw),
        payload=raw,
        forward_project_root=project_root,
        forward_config_path=forward_config_path,
        forward_delivery_root_path=forward_delivery_path,
        high_fidelity_config_path=hf_config_path,
        high_fidelity_validation_spec_path=hf_validation_spec_path,
        forward_config=forward_config,
        high_fidelity_config=hf_config,
        shared_input_audit=audit,
        case_file_sha256=_sha256_file(source),
        forward_chain=forward_chain,
        forward_chain_snapshot_sha256=_forward_chain_snapshot_sha256(forward_chain),
        high_fidelity_config_file_sha256=_sha256_file(hf_config_path),
        high_fidelity_config_bytes=hf_config_path.read_bytes(),
        high_fidelity_validation_spec_file_sha256=_sha256_file(
            hf_validation_spec_path
        ),
        high_fidelity_validation_spec_bytes=hf_validation_spec_path.read_bytes(),
        high_fidelity_resolved_config_sha256=_canonical_hash(
            resolved_config_dict(hf_config)
        ),
        high_fidelity_auxiliary_files=_high_fidelity_auxiliary_files(hf_config),
    )

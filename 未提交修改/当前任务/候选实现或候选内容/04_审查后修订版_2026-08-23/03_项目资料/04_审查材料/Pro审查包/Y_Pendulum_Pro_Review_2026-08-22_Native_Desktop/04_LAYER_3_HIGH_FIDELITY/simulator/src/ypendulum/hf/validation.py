"""Identity-bound convergence and independent dynamics checks for the HF backend."""

from __future__ import annotations

import hashlib
import json
import platform
import struct
import sys
from collections import Counter
from dataclasses import dataclass, field, fields
from numbers import Integral, Real
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from ypendulum.config import (
    SimulationConfig,
    auxiliary_input_identities,
    load_config,
    load_unique_yaml,
    resolved_config_dict,
    resolved_config_sha256,
    validate_physical_config,
)
from ypendulum.config.units import to_si
from ypendulum.io.provenance import dependency_versions, source_hash
from ypendulum.version import __version__

from .model import HighFidelityModel
from .reference import (
    cumulative_trapezoid_reference,
    junction_socket_projective_opening_squared_reference,
    material_point_from_joint_reference,
    material_segments_outside_socket_reference,
    materially_separated_segment_distance_reference,
    normalize_quaternion_reference,
    origin_invariant_energy_scale,
    pack_reference_state,
    point_segment_distance_reference,
    reference_rhs,
    reference_snapshot_from_state,
    rotate_body_vector_reference,
    segment_segment_distance_reference,
    socket_material_breakpoints_reference,
)
from .solver import PreparationResult, prepare_initial_state, simulate_high_fidelity
from .state import HighFidelityResult

_COMPARISON_METRICS = (
    "rms_bob_position_m",
    "max_bob_position_m",
    "rms_bob_velocity_m_s",
    "max_bob_velocity_m_s",
    "rms_junction_position_m",
    "max_junction_position_m",
    "rms_junction_velocity_m_s",
    "max_junction_velocity_m_s",
    "rms_bob_attachment_position_m",
    "max_bob_attachment_position_m",
    "rms_bob_orientation_angle_rad",
    "max_bob_orientation_angle_rad",
    "rms_bob_angular_velocity_rad_s",
    "max_bob_angular_velocity_rad_s",
    "rms_rod_position_m",
    "max_rod_position_m",
    "rms_rod_velocity_m_s",
    "max_rod_velocity_m_s",
    "rms_rod_tension_N",
    "max_rod_tension_N",
    "rms_rod_signed_axial_force_N",
    "max_rod_signed_axial_force_N",
    "rms_mechanical_energy_J",
    "max_mechanical_energy_J",
    "rms_support_reaction_N",
    "max_support_reaction_N",
)

_PHYSICS_THRESHOLDS = (
    "minimum_normalized_guard_margin",
    "maximum_negative_dissipation_W",
    "maximum_energy_balance_residual",
    "maximum_quaternion_norm_error",
    "maximum_normalized_rate_defect",
    "maximum_normalized_nonsmooth_increment_defect",
    "maximum_normalized_signed_cumulative_defect",
    "maximum_normalized_absolute_cumulative_defect",
    "maximum_nonsmooth_time_fraction",
    "maximum_nonsmooth_step_s",
)

_ACCURACY_FIELDS = (
    "energy_balance_residual",
    "maximum_normalized_rate_defect",
    "maximum_normalized_nonsmooth_increment_defect",
    "maximum_normalized_signed_cumulative_defect",
    "maximum_normalized_absolute_cumulative_defect",
)

_VALIDATION_TARGET_SCHEMA = "YPS-HF-CERTIFICATION-TARGET-1.0"
_VALIDATION_TARGET_BRANCHES = ("upper_A", "upper_B", "lower")

_SINGLE_BUNDLE_CERTIFICATE_FIELDS = frozenset(
    {
        "schema_version",
        "model_id",
        "passed",
        "guard_domain_certified",
        "certification_level",
        "raw_result_status_pair",
        "certified_status_pair",
        "full_accuracy_spec_bound",
        "minimum_normalized_guard_margin",
        "validation_spec_sha256",
        "certification_target",
        "identity",
        "identity_checks",
        "checks",
        "presentation_certificate_binding",
        "canonical_series_consistency",
        "preparation_certificate",
        "energy_balance",
        "dynamics_defect",
        "continuous_guard_certificate",
        "contract_evaluation_error",
        "certificate_sha256",
    }
)


def _runtime_identity() -> dict[str, Any]:
    return {
        "project_version": __version__,
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "dependencies": dependency_versions(
            ["numpy", "scipy", "pydantic", "pint", "PyYAML", "h5py"]
        ),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_framed_bytes(
    digest: Any, tag: bytes, payload: bytes | memoryview
) -> None:
    """Append an unambiguous typed byte frame to a streaming digest."""

    digest.update(struct.pack(">H", len(tag)))
    digest.update(tag)
    digest.update(struct.pack(">Q", len(payload)))
    digest.update(payload)


def _update_canonical_digest(digest: Any, value: Any) -> None:
    """Stream finite canonical Python/NumPy data without materialising arrays."""

    if value is None:
        _hash_framed_bytes(digest, b"none", b"")
        return
    if isinstance(value, (bool, np.bool_)):
        _hash_framed_bytes(digest, b"bool", b"true" if value else b"false")
        return
    if isinstance(value, (Integral, np.integer)) and not isinstance(value, bool):
        _hash_framed_bytes(digest, b"int", str(int(value)).encode("ascii"))
        return
    if isinstance(value, (Real, np.floating)) and not isinstance(value, bool):
        scalar = float(value)
        if not np.isfinite(scalar):
            raise ValueError("Canonical HF identity rejects non-finite scalars.")
        _hash_framed_bytes(digest, b"float64-be", struct.pack(">d", scalar))
        return
    if isinstance(value, str):
        _hash_framed_bytes(digest, b"utf8", value.encode("utf-8"))
        return
    if isinstance(value, Path):
        _hash_framed_bytes(digest, b"path-utf8", str(value).encode("utf-8"))
        return
    if isinstance(value, np.ndarray):
        array = np.asarray(value)
        if array.dtype.hasobject:
            raise ValueError("Canonical HF identity rejects object arrays.")
        if array.dtype.kind in "fc" and not bool(np.all(np.isfinite(array))):
            raise ValueError("Canonical HF identity rejects non-finite arrays.")
        little_dtype = array.dtype.newbyteorder("<")
        canonical = np.ascontiguousarray(array.astype(little_dtype, copy=False))
        metadata = json.dumps(
            {
                "dtype": little_dtype.str,
                "shape": list(canonical.shape),
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
        _hash_framed_bytes(digest, b"ndarray-metadata", metadata)
        view = memoryview(canonical).cast("B")
        _hash_framed_bytes(digest, b"ndarray-c-bytes", view)
        return
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("Canonical HF identity requires string mapping keys.")
        _hash_framed_bytes(digest, b"dict-length", struct.pack(">Q", len(value)))
        for key in sorted(value):
            _update_canonical_digest(digest, key)
            _update_canonical_digest(digest, value[key])
        return
    if isinstance(value, (list, tuple)):
        tag = b"list-length" if isinstance(value, list) else b"tuple-length"
        _hash_framed_bytes(digest, tag, struct.pack(">Q", len(value)))
        for item in value:
            _update_canonical_digest(digest, item)
        return
    raise ValueError(
        f"Canonical HF identity does not support values of type {type(value).__name__}."
    )


def canonical_hf_result_sha256(result: HighFidelityResult) -> str:
    """Return a finite, streaming identity for the complete in-memory result.

    The non-physical ``run_directory`` location is excluded.  Every dataclass
    field otherwise participates, and transitional signed-force attributes are
    included even before they become first-class dataclass fields.
    """

    payload: dict[str, Any] = {
        "identity_schema": "YPS-HF-IN-MEMORY-RESULT-SHA256-1.0"
    }
    field_names = {item.name for item in fields(result)}
    for item in fields(result):
        if item.name != "run_directory":
            payload[item.name] = getattr(result, item.name)
    for name in ("cable_axial_force", "branch_axial_force"):
        if name not in field_names and hasattr(result, name):
            payload[name] = getattr(result, name)
    digest = hashlib.sha256()
    _update_canonical_digest(digest, payload)
    return digest.hexdigest()


@dataclass
class _RunBundle:
    config: SimulationConfig
    config_hash: str
    model: HighFidelityModel
    preparation: PreparationResult
    result: HighFidelityResult
    source_start: str
    source_end: str
    config_hash_end: str | None = None
    runtime_identity_start: dict[str, Any] = field(default_factory=dict)
    runtime_identity_end: dict[str, Any] = field(default_factory=dict)
    auxiliary_input_hash_start: dict[str, Any] = field(default_factory=dict)
    auxiliary_input_hash_end: dict[str, Any] = field(default_factory=dict)
    result_hash_start: str | None = None


@dataclass(frozen=True)
class _AcceptedStepReferenceCache:
    """One candidate's independently reconstructed accepted-step endpoints."""

    time: np.ndarray
    state: np.ndarray
    rhs: np.ndarray
    axial_active_signature: tuple[np.ndarray, ...]


def _canonical_config_hash(cfg: SimulationConfig) -> str:
    """Compatibility alias for the shared canonical resolved-config hash."""

    return resolved_config_sha256(cfg)


def _auxiliary_input_identity(cfg: SimulationConfig) -> dict[str, Any]:
    return auxiliary_input_identities(cfg)


def _quantity_scaled(value: Any, factor: float, unit: str) -> dict[str, Any]:
    return {"value": factor * float(to_si(value, default_unit=unit)), "unit": unit}


def _json_safe_finite(value: Any, active: set[int] | None = None) -> bool:
    """Return whether *value* has a finite, unambiguous JSON representation."""

    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, Integral) and not isinstance(value, bool):
        return True
    if isinstance(value, Real) and not isinstance(value, bool):
        try:
            return bool(np.isfinite(float(value)))
        except (OverflowError, TypeError, ValueError):
            return False
    if active is None:
        active = set()
    if isinstance(value, dict):
        identity = id(value)
        if identity in active or not all(isinstance(key, str) for key in value):
            return False
        active.add(identity)
        valid = all(_json_safe_finite(item, active) for item in value.values())
        active.remove(identity)
        return valid
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active:
            return False
        active.add(identity)
        valid = all(_json_safe_finite(item, active) for item in value)
        active.remove(identity)
        return valid
    return False


def _finite_real(value: Any, *, name: str, minimum: float, strict: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number.")
    try:
        scalar = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite real number.") from exc
    if not np.isfinite(scalar) or (scalar <= minimum if strict else scalar < minimum):
        relation = ">" if strict else ">="
        raise ValueError(f"{name} must be finite and {relation} {minimum}.")
    return scalar


def _validation_target_payload(
    spec: dict[str, Any], *, required: bool
) -> dict[str, Any] | None:
    """Extract the frozen production target without binding incidental run paths."""

    metadata = spec.get("metadata")
    if metadata is None:
        if required:
            raise ValueError(
                "HF validation metadata must define intended_window_s and "
                "production_mesh_beads for production certification."
            )
        return None
    if not isinstance(metadata, dict):
        raise ValueError("HF validation metadata must be a JSON object.")

    target_fields = {"intended_window_s", "production_mesh_beads"}
    present = target_fields.intersection(metadata)
    if not present and not required:
        return None
    if present != target_fields:
        raise ValueError(
            "HF validation metadata must provide intended_window_s and "
            "production_mesh_beads together."
        )

    intended_window_s = _finite_real(
        metadata["intended_window_s"],
        name="metadata.intended_window_s",
        minimum=0.0,
        strict=True,
    )
    mesh = metadata["production_mesh_beads"]
    if not isinstance(mesh, dict) or set(mesh) != set(_VALIDATION_TARGET_BRANCHES):
        raise ValueError(
            "metadata.production_mesh_beads must contain exactly upper_A, "
            "upper_B and lower."
        )
    frozen_mesh: dict[str, int] = {}
    for branch in _VALIDATION_TARGET_BRANCHES:
        value = mesh[branch]
        if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
            raise ValueError(
                f"metadata.production_mesh_beads.{branch} must be a positive integer."
            )
        frozen_mesh[branch] = int(value)
    return {
        "schema_version": _VALIDATION_TARGET_SCHEMA,
        "intended_window_s": intended_window_s,
        "production_mesh_beads": frozen_mesh,
    }


def _validation_target_applicability(
    cfg: SimulationConfig, spec: dict[str, Any]
) -> dict[str, Any]:
    """Compare a resolved config with the spec's exact production target.

    This deliberately excludes ``run.output_directory`` and every other
    incidental execution field.  Those fields remain covered by the ordinary
    resolved-config identity, but changing them cannot make a different
    physical window or mesh eligible for the production qualification target.
    """

    actual = {
        "intended_window_s": float(to_si(cfg.solver.t_end, default_unit="s")),
        "production_mesh_beads": {
            branch: int(getattr(cfg.cables, branch).elements)
            for branch in _VALIDATION_TARGET_BRANCHES
        },
    }
    try:
        target = _validation_target_payload(spec, required=True)
    except ValueError as exc:
        return {
            "schema_version": _VALIDATION_TARGET_SCHEMA,
            "passed": False,
            "comparison_policy": "exact_after_SI_resolution",
            "bound_config_fields": [
                "solver.t_end",
                *[
                    f"cables.{branch}.elements"
                    for branch in _VALIDATION_TARGET_BRANCHES
                ],
            ],
            "explicitly_unbound_config_fields": ["run.output_directory"],
            "target_sha256": None,
            "target": None,
            "actual": actual,
            "checks": {
                "intended_window_s_exact": False,
                "production_mesh_beads_exact": False,
            },
            "failure_reason": str(exc),
        }
    assert target is not None
    target_bytes = json.dumps(
        target,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    checks = {
        "intended_window_s_exact": (
            actual["intended_window_s"] == target["intended_window_s"]
        ),
        "production_mesh_beads_exact": (
            actual["production_mesh_beads"] == target["production_mesh_beads"]
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": _VALIDATION_TARGET_SCHEMA,
        "passed": all(checks.values()),
        "comparison_policy": "exact_after_SI_resolution",
        "bound_config_fields": [
            "solver.t_end",
            *[
                f"cables.{branch}.elements"
                for branch in _VALIDATION_TARGET_BRANCHES
            ],
        ],
        "explicitly_unbound_config_fields": ["run.output_directory"],
        "target_sha256": hashlib.sha256(target_bytes).hexdigest(),
        "target": target,
        "actual": actual,
        "checks": checks,
        "failure_reason": (
            None
            if not failed
            else "Resolved configuration does not exactly match: "
            + ", ".join(failed)
        ),
    }


def _freeze_and_validate_spec(raw: Any) -> dict[str, Any]:
    """Validate and detach the qualification contract before any run starts."""

    if not isinstance(raw, dict) or not _json_safe_finite(raw):
        raise ValueError("HF validation specification must be finite canonical JSON data.")
    try:
        spec = json.loads(
            json.dumps(
                raw,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("HF validation specification is not canonically serializable.") from exc

    required = {
        "schema_version",
        "material_comparison_points",
        "cauchy_ratio_slack",
        "numerical_floor_fraction",
        "maximum_event_time_spread_s",
        "cross_solver_tolerance_factors",
        "thresholds",
        "physics_checks",
    }
    allowed = required | {"metadata"}
    if set(spec) - allowed or required - set(spec):
        raise ValueError(
            "HF validation specification fields must be exactly the frozen contract "
            "plus optional metadata."
        )
    if spec["schema_version"] != "YPS-HF-VALIDATION-1.0":
        raise ValueError("Invalid HF validation specification schema.")
    points = spec["material_comparison_points"]
    if isinstance(points, bool) or not isinstance(points, Integral) or not 5 <= points <= 4097:
        raise ValueError("material_comparison_points must be an integer in [5,4097].")
    _finite_real(
        spec["cauchy_ratio_slack"],
        name="cauchy_ratio_slack",
        minimum=1.0,
        strict=False,
    )
    floor_fraction = _finite_real(
        spec["numerical_floor_fraction"],
        name="numerical_floor_fraction",
        minimum=0.0,
        strict=False,
    )
    if floor_fraction > 1.0:
        raise ValueError("numerical_floor_fraction must not exceed one.")
    _finite_real(
        spec["maximum_event_time_spread_s"],
        name="maximum_event_time_spread_s",
        minimum=0.0,
        strict=False,
    )
    cross_factors = spec["cross_solver_tolerance_factors"]
    if not isinstance(cross_factors, dict) or set(cross_factors) != {"Radau", "BDF"}:
        raise ValueError(
            "cross_solver_tolerance_factors must contain exactly Radau and BDF."
        )
    for method, value in cross_factors.items():
        factor = _finite_real(
            value,
            name=f"cross_solver_tolerance_factors.{method}",
            minimum=0.0,
            strict=True,
        )
        if factor > 1.0:
            raise ValueError("Cross-solver tolerance factors must not exceed one.")

    thresholds = spec["thresholds"]
    if not isinstance(thresholds, dict) or set(thresholds) != {
        "space",
        "time",
        "cross_solver",
    }:
        raise ValueError("thresholds must contain exactly space, time and cross_solver.")
    for study_name, study_thresholds in thresholds.items():
        if not isinstance(study_thresholds, dict) or set(study_thresholds) != set(
            _COMPARISON_METRICS
        ):
            raise ValueError(
                f"thresholds.{study_name} must contain every canonical comparison metric exactly once."
            )
        for metric, value in study_thresholds.items():
            _finite_real(
                value,
                name=f"thresholds.{study_name}.{metric}",
                minimum=0.0,
                strict=True,
            )

    physics = spec["physics_checks"]
    if isinstance(physics, dict) and "minimum_guard_margin_m" in physics:
        raise ValueError(
            "physics_checks.minimum_guard_margin_m is dimensionally invalid for "
            "mixed-unit HF guards; use minimum_normalized_guard_margin."
        )
    if not isinstance(physics, dict) or set(physics) != set(_PHYSICS_THRESHOLDS):
        raise ValueError("physics_checks does not match the frozen HF physics contract.")
    for key, value in physics.items():
        _finite_real(
            value,
            name=f"physics_checks.{key}",
            minimum=0.0,
            strict=key not in {
                "minimum_normalized_guard_margin",
                "maximum_negative_dissipation_W",
            },
        )
    if float(physics["maximum_nonsmooth_time_fraction"]) > 1.0:
        raise ValueError("maximum_nonsmooth_time_fraction must not exceed one.")
    _validation_target_payload(spec, required=False)
    return spec


def _state_matrix(bundle: _RunBundle) -> np.ndarray:
    result = bundle.result
    return np.vstack(
        [
            pack_reference_state(
                result.particle_positions[index],
                result.bob_position[index],
                result.bob_quaternion[index],
                result.particle_velocities[index],
                result.bob_velocity[index],
                result.bob_angular_velocity[index],
            )
            for index in range(result.time.size)
        ]
    )


def _integration_state_matrix(bundle: _RunBundle) -> np.ndarray:
    result = bundle.result
    return np.vstack(
        [
            pack_reference_state(
                result.integration_particle_positions[index],
                result.integration_bob_position[index],
                result.integration_bob_quaternion[index],
                result.integration_particle_velocities[index],
                result.integration_bob_velocity[index],
                result.integration_bob_angular_velocity[index],
            )
            for index in range(result.integration_time.size)
        ]
    )


def _axial_active_signature(
    model: HighFidelityModel, t: float, state: np.ndarray
) -> np.ndarray:
    """Reconstruct the unilateral local-link active set without diagnostics."""

    snapshot = reference_snapshot_from_state(model, t, state, compute_contact=False)
    signatures: list[np.ndarray] = []
    for branch in model.branches.values():
        points = snapshot.branch_positions[branch.name]
        velocities = snapshot.branch_velocities[branch.name]
        segment = points[1:] - points[:-1]
        length = np.linalg.norm(segment, axis=1)
        tangent = segment / length[:, None]
        extension_rate = np.einsum(
            "ij,ij->i", velocities[1:] - velocities[:-1], tangent
        )
        extension = length - branch.segment_rest_length
        trial = (
            branch.ea / branch.segment_rest_length * extension
            + branch.eta_a / branch.segment_rest_length * extension_rate
        )
        unilateral_has_weight = (
            float(model.compression_regularization_scale) < 1.0
        )
        signatures.append(
            ((extension > 0.0) & (trial > 0.0))
            if unilateral_has_weight
            else np.ones(extension.shape, dtype=bool)
        )
    return np.concatenate(signatures)


def _accepted_step_reference_cache(
    bundle: _RunBundle,
) -> _AcceptedStepReferenceCache:
    time = np.asarray(bundle.result.integration_time, dtype=float)
    state = _integration_state_matrix(bundle)
    rhs = np.vstack(
        [
            reference_rhs(bundle.model, float(t), y)
            for t, y in zip(time, state, strict=True)
        ]
    )
    signature = tuple(
        _axial_active_signature(bundle.model, float(t), y)
        for t, y in zip(time, state, strict=True)
    )
    return _AcceptedStepReferenceCache(
        time=time,
        state=state,
        rhs=rhs,
        axial_active_signature=signature,
    )


def _dynamics_defect(
    bundle: _RunBundle,
    accepted_cache: _AcceptedStepReferenceCache | None = None,
) -> dict[str, float]:
    """Independent Hermite-midpoint/Simpson defect on accepted solver steps.

    The fixed presentation grid can straddle a unilateral-tension activation
    and is therefore not a valid high-order quadrature partition.  The solver's
    accepted-step state is a public certificate, not a hidden diagnostic; the
    RHS is recomputed here independently on that adaptive partition.
    """

    cache = accepted_cache or _accepted_step_reference_cache(bundle)
    time = cache.time
    state = cache.state
    model = bundle.model
    if time.size < 2:
        return {
            "certificate_step_count": int(max(time.size - 1, 0)),
            "smooth_step_count": 0,
            "nonsmooth_step_count": 0,
            "maximum_normalized_rate_defect": float("inf"),
            "rms_normalized_rate_defect": float("inf"),
            "maximum_normalized_nonsmooth_increment_defect": float("inf"),
            "maximum_normalized_signed_cumulative_defect": float("inf"),
            "maximum_normalized_absolute_cumulative_defect": float("inf"),
            "nonsmooth_time_fraction": float("inf"),
            "maximum_nonsmooth_step_s": float("inf"),
        }
    rhs_endpoint = cache.rhs
    residuals: list[np.ndarray] = []
    rate_normalized: list[np.ndarray] = []
    nonsmooth_increment_normalized: list[np.ndarray] = []
    nonsmooth_steps: list[float] = []
    length = model.characteristic_length
    gravity = float(np.linalg.norm(model.gravity))
    time_scale = np.sqrt(length / gravity)
    velocity = length / time_scale
    acceleration = velocity / time_scale
    angular_velocity = 1.0 / time_scale
    angular_acceleration = 1.0 / time_scale**2
    n = model.position_size
    state_scale = np.concatenate(
        [
            np.full(n, length),
            np.full(3, length),
            np.ones(4),
            np.full(n, velocity),
            np.full(3, velocity),
            np.full(3, angular_velocity),
        ]
    )
    derivative_scale = np.concatenate(
        [
            np.full(n, velocity),
            np.full(3, velocity),
            np.full(4, angular_velocity),
            np.full(n, acceleration),
            np.full(3, acceleration),
            np.full(3, angular_acceleration),
        ]
    )
    endpoint_signatures = cache.axial_active_signature
    for index in range(time.size - 1):
        step = float(time[index + 1] - time[index])
        midpoint_state = (
            0.5 * (state[index] + state[index + 1])
            + step / 8.0 * (rhs_endpoint[index] - rhs_endpoint[index + 1])
        )
        midpoint_rhs = reference_rhs(
            model,
            0.5 * float(time[index] + time[index + 1]), midpoint_state
        )
        midpoint_signature = _axial_active_signature(
            model,
            0.5 * float(time[index] + time[index + 1]),
            midpoint_state,
        )
        increment = step / 6.0 * (
            rhs_endpoint[index] + 4.0 * midpoint_rhs + rhs_endpoint[index + 1]
        )
        residual = state[index + 1] - state[index] - increment
        residuals.append(residual)
        smooth = (
            np.array_equal(endpoint_signatures[index], midpoint_signature)
            and np.array_equal(midpoint_signature, endpoint_signatures[index + 1])
        )
        if smooth:
            roundoff_floor = 512.0 * np.finfo(float).eps * (
                np.abs(state[index]) + np.abs(state[index + 1]) + state_scale
            )
            denominator = np.maximum(step * derivative_scale, roundoff_floor)
            rate_normalized.append(residual / denominator)
        else:
            nonsmooth_steps.append(step)
            nonsmooth_increment_normalized.append(residual / state_scale)
    residual_array = np.vstack(residuals)
    normalized_rate = (
        np.vstack(rate_normalized)
        if rate_normalized
        else np.zeros((1, state_scale.size))
    )
    nonsmooth_increment = (
        np.vstack(nonsmooth_increment_normalized)
        if nonsmooth_increment_normalized
        else np.zeros((1, state_scale.size))
    )
    duration = float(time[-1] - time[0])
    return {
        "certificate_step_count": int(time.size - 1),
        "smooth_step_count": int(len(rate_normalized)),
        "smooth_rate_metric_applicable": bool(rate_normalized),
        "nonsmooth_step_count": int(len(nonsmooth_steps)),
        "maximum_normalized_rate_defect": float(np.max(np.abs(normalized_rate))),
        "rms_normalized_rate_defect": float(np.sqrt(np.mean(normalized_rate**2))),
        "maximum_normalized_nonsmooth_increment_defect": float(
            np.max(np.abs(nonsmooth_increment))
        ),
        "maximum_normalized_signed_cumulative_defect": float(
            np.max(np.abs(np.sum(residual_array, axis=0) / state_scale))
        ),
        "maximum_normalized_absolute_cumulative_defect": float(
            np.max(np.sum(np.abs(residual_array), axis=0) / state_scale)
        ),
        "nonsmooth_time_fraction": (
            float(sum(nonsmooth_steps) / duration) if duration > 0.0 else float("inf")
        ),
        "maximum_nonsmooth_step_s": (
            float(max(nonsmooth_steps)) if nonsmooth_steps else 0.0
        ),
    }


def _hermite_bezier_controls(
    state_left: np.ndarray,
    state_right: np.ndarray,
    rhs_left: np.ndarray,
    rhs_right: np.ndarray,
    step: float,
    *,
    quaternion_slice: slice,
) -> np.ndarray:
    """Return cubic Bezier controls, aligning physically equivalent q/-q data."""

    left = np.asarray(state_left, dtype=float).copy()
    right = np.asarray(state_right, dtype=float).copy()
    left_rhs = np.asarray(rhs_left, dtype=float).copy()
    right_rhs = np.asarray(rhs_right, dtype=float).copy()
    if float(left[quaternion_slice] @ right[quaternion_slice]) < 0.0:
        right[quaternion_slice] *= -1.0
        right_rhs[quaternion_slice] *= -1.0
    return np.vstack(
        [
            left,
            left + step * left_rhs / 3.0,
            right - step * right_rhs / 3.0,
            right,
        ]
    )


def _bezier_value(controls: np.ndarray, parameter: float) -> np.ndarray:
    u = float(parameter)
    v = 1.0 - u
    return (
        v**3 * controls[0]
        + 3.0 * v**2 * u * controls[1]
        + 3.0 * v * u**2 * controls[2]
        + u**3 * controls[3]
    )


def _split_bezier_half(controls: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    first = 0.5 * (controls[:-1] + controls[1:])
    second = 0.5 * (first[:-1] + first[1:])
    midpoint = 0.5 * (second[0] + second[1])
    return (
        np.vstack([controls[0], first[0], second[0], midpoint]),
        np.vstack([midpoint, second[1], first[2], controls[3]]),
    )


def _vector_motion_bound(controls: np.ndarray) -> float:
    """Bound displacement from u=1/2 using the derivative convex hull."""

    derivative_controls = 3.0 * np.diff(np.asarray(controls), axis=0)
    return 0.5 * float(np.max(np.linalg.norm(derivative_controls, axis=1)))


def _state_error_budget(bundle: _RunBundle) -> dict[str, float]:
    cfg = bundle.config
    if (
        cfg.solver.position_atol is None
        or cfg.solver.velocity_atol is None
        or cfg.solver.quaternion_atol is None
        or cfg.solver.angular_velocity_atol is None
        or cfg.solver.rtol is None
    ):
        raise ValueError("HF accepted-step binding requires explicit solver tolerances.")
    return {
        "rtol": float(cfg.solver.rtol),
        "position": float(to_si(cfg.solver.position_atol, default_unit="m")),
        "velocity": float(to_si(cfg.solver.velocity_atol, default_unit="m/s")),
        "quaternion": float(cfg.solver.quaternion_atol),
        "angular_velocity": float(
            to_si(cfg.solver.angular_velocity_atol, default_unit="rad/s")
        ),
    }


def _presentation_certificate_binding(
    bundle: _RunBundle,
    accepted_cache: _AcceptedStepReferenceCache | None = None,
) -> dict[str, Any]:
    """Bind every public t>0 sample to an independent accepted-step Hermite trace."""

    cache = accepted_cache or _accepted_step_reference_cache(bundle)
    integration_time = cache.time
    accepted_state = cache.state
    public_time = np.asarray(bundle.result.time, dtype=float)
    public_state = _state_matrix(bundle)
    model = bundle.model
    n = model.position_size
    q_slice = slice(n + 3, n + 7)
    velocity_offset = n + 7
    endpoint_rhs = cache.rhs
    budgets = _state_error_budget(bundle)
    eps = np.finfo(float).eps
    length = model.characteristic_length
    gravity_time = np.sqrt(length / float(np.linalg.norm(model.gravity)))
    velocity_scale = length / gravity_time
    angular_scale = 1.0 / gravity_time
    time_tolerance = 4096.0 * eps * max(
        float(integration_time[-1]), gravity_time, 1.0
    )
    sample_certificates: list[dict[str, Any]] = []
    passed = True

    for sample_index in range(1, public_time.size):
        time = float(public_time[sample_index])
        right = int(np.searchsorted(integration_time, time, side="left"))
        exact_index: int | None = None
        for candidate in (right - 1, right):
            if 0 <= candidate < integration_time.size and abs(
                float(integration_time[candidate]) - time
            ) <= time_tolerance:
                exact_index = candidate
                break
        if exact_index is not None:
            reconstructed = accepted_state[exact_index].copy()
            step_index = max(min(exact_index, integration_time.size - 2), 0)
            exact = True
        elif 0 < right < integration_time.size:
            left = right - 1
            step = float(integration_time[right] - integration_time[left])
            controls = _hermite_bezier_controls(
                accepted_state[left],
                accepted_state[right],
                endpoint_rhs[left],
                endpoint_rhs[right],
                step,
                quaternion_slice=q_slice,
            )
            reconstructed = _bezier_value(
                controls, (time - float(integration_time[left])) / step
            )
            step_index = left
            exact = False
        else:
            sample_certificates.append(
                {
                    "sample_index": sample_index,
                    "time_s": time,
                    "passed": False,
                    "reason": "outside accepted-step certificate",
                }
            )
            passed = False
            continue

        public = public_state[sample_index]
        reconstructed_q = normalize_quaternion_reference(reconstructed[q_slice])
        public_q = normalize_quaternion_reference(public[q_slice])
        quaternion_error = min(
            float(np.linalg.norm(public_q - reconstructed_q)),
            float(np.linalg.norm(public_q + reconstructed_q)),
        )
        position_error = float(
            np.max(
                np.abs(
                    np.concatenate(
                        [public[: n + 3] - reconstructed[: n + 3]]
                    )
                )
            )
        )
        particle_velocity_error = float(
            np.max(
                np.abs(
                    public[velocity_offset : velocity_offset + n + 3]
                    - reconstructed[velocity_offset : velocity_offset + n + 3]
                )
            )
        )
        angular_velocity_error = float(
            np.max(
                np.abs(
                    public[velocity_offset + n + 3 :]
                    - reconstructed[velocity_offset + n + 3 :]
                )
            )
        )
        if exact:
            position_tolerance = 8192.0 * eps * max(
                length,
                float(np.max(np.abs(reconstructed[: n + 3]))),
            )
            velocity_tolerance = 8192.0 * eps * max(
                velocity_scale,
                float(
                    np.max(
                        np.abs(reconstructed[velocity_offset : velocity_offset + n + 3])
                    )
                ),
            )
            quaternion_tolerance = 16384.0 * eps
            angular_tolerance = 8192.0 * eps * max(
                angular_scale,
                float(np.max(np.abs(reconstructed[velocity_offset + n + 3 :]))),
            )
        else:
            rtol = budgets["rtol"]
            position_tolerance = 32.0 * (
                budgets["position"]
                + rtol
                * max(length, float(np.max(np.abs(reconstructed[: n + 3]))))
            )
            velocity_tolerance = 32.0 * (
                budgets["velocity"]
                + rtol
                * max(
                    velocity_scale,
                    float(
                        np.max(
                            np.abs(
                                reconstructed[
                                    velocity_offset : velocity_offset + n + 3
                                ]
                            )
                        )
                    ),
                )
            )
            quaternion_tolerance = 32.0 * (budgets["quaternion"] + rtol)
            angular_tolerance = 32.0 * (
                budgets["angular_velocity"]
                + rtol
                * max(
                    angular_scale,
                    float(
                        np.max(
                            np.abs(reconstructed[velocity_offset + n + 3 :])
                        )
                    ),
                )
            )
        checks = {
            "position": position_error <= position_tolerance,
            "velocity": particle_velocity_error <= velocity_tolerance,
            "quaternion_q_or_minus_q": quaternion_error <= quaternion_tolerance,
            "angular_velocity": angular_velocity_error <= angular_tolerance,
        }
        passed &= all(checks.values())
        sample_certificates.append(
            {
                "sample_index": sample_index,
                "time_s": time,
                "accepted_step_index": step_index,
                "accepted_endpoint_exact": exact,
                "passed": all(checks.values()),
                "checks": checks,
                "errors": {
                    "position_m": position_error,
                    "velocity_m_s": particle_velocity_error,
                    "quaternion_q_or_minus_q": quaternion_error,
                    "angular_velocity_rad_s": angular_velocity_error,
                },
                "tolerances": {
                    "position_m": position_tolerance,
                    "velocity_m_s": velocity_tolerance,
                    "quaternion_q_or_minus_q": quaternion_tolerance,
                    "angular_velocity_rad_s": angular_tolerance,
                },
            }
        )
    return {
        "passed": bool(passed and len(sample_certificates) == public_time.size - 1),
        "method": "independent_cubic_Hermite_on_every_accepted_step",
        "quaternion_equivalence": "min_norm_q_minus_qhat_or_q_plus_qhat",
        "coverage": "every public sample with t>0 through the full valid window",
        "public_sample_count_t_gt_0": int(max(public_time.size - 1, 0)),
        "certified_sample_count": int(sum(item.get("passed", False) for item in sample_certificates)),
        "sample_certificates": sample_certificates,
    }


def _support_motion_bound(motion: Any, start: float, end: float) -> float:
    """Conservative displacement-from-midpoint bound for registered supports."""

    half_width = 0.5 * (end - start)
    if motion.kind == "fixed":
        return 0.0
    if motion.kind == "sinusoidal":
        assert motion.amplitude is not None
        return float(np.linalg.norm(motion.amplitude) * abs(motion.angular_frequency) * half_width)
    # A table motion is a piecewise cubic.  Bound its vector speed by the
    # coordinate-wise extrema of each quadratic derivative on intersected knots.
    assert motion.spline is not None
    knots = np.asarray(motion.spline.x, dtype=float)
    component_speed_bound = np.zeros(3, dtype=float)
    for interval in range(knots.size - 1):
        left = max(start, float(knots[interval]))
        right = min(end, float(knots[interval + 1]))
        if right <= left:
            continue
        coefficients = np.asarray(motion.spline.c[:, interval, :], dtype=float)
        local_left = left - knots[interval]
        local_right = right - knots[interval]
        for component in range(3):
            a = 3.0 * coefficients[0, component]
            b = 2.0 * coefficients[1, component]
            c = coefficients[2, component]
            candidates = [local_left, local_right]
            if abs(a) > np.finfo(float).tiny:
                vertex = -b / (2.0 * a)
                if local_left < vertex < local_right:
                    candidates.append(float(vertex))
            component_speed_bound[component] = max(
                component_speed_bound[component],
                *(abs(a * value**2 + b * value + c) for value in candidates),
            )
    speed_bound = float(np.linalg.norm(component_speed_bound))
    return speed_bound * half_width


def _guard_component_metadata_contract(
    model: HighFidelityModel,
) -> dict[str, dict[str, float | str]]:
    """Freeze and validate the guard units/scales used by a certificate.

    Guard components intentionally do not all have dimensions of length.  A
    continuous certificate therefore compares each raw lower bound only after
    division by its declared positive physical scale, while retaining the raw
    unit and machine tolerance as audit evidence.
    """

    raw = model.guard_component_metadata()
    if not isinstance(raw, dict) or not raw:
        raise ValueError("HF guard-component metadata must be a non-empty mapping.")
    frozen: dict[str, dict[str, float | str]] = {}
    for name, item in raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError("HF guard-component names must be non-empty strings.")
        if not isinstance(item, dict) or set(item) != {"unit", "scale", "tolerance"}:
            raise ValueError(
                f"Guard metadata for {name} must contain unit, scale and tolerance."
            )
        unit = item["unit"]
        if not isinstance(unit, str) or not unit:
            raise ValueError(f"Guard metadata unit for {name} is invalid.")
        scale = _finite_real(
            item["scale"], name=f"guard_metadata.{name}.scale", minimum=0.0, strict=True
        )
        tolerance = _finite_real(
            item["tolerance"],
            name=f"guard_metadata.{name}.tolerance",
            minimum=0.0,
            strict=False,
        )
        if tolerance >= scale:
            raise ValueError(f"Guard metadata tolerance for {name} is not sub-scale.")
        frozen[name] = {
            "unit": unit,
            "scale": scale,
            "tolerance": tolerance,
        }
    return frozen


def _affine_material_motion_bound(
    reference: tuple[int, int, float], point_bounds: np.ndarray
) -> float:
    """Bound a fixed rest-material affine point from the interval midpoint."""

    left, right, fraction = reference
    return float(
        (1.0 - fraction) * point_bounds[left]
        + fraction * point_bounds[right]
    )


def _socket_projective_motion_rate_bound(
    point_bounds: np.ndarray,
    segment_rest_length: np.ndarray,
    side: str,
    socket_length: float,
) -> float:
    """Bound normalized socket-trace motion relative to its common junction."""

    bounds = np.asarray(point_bounds, dtype=float)
    rest = np.asarray(segment_rest_length, dtype=float)
    if side == "end":
        bounds = bounds[::-1]
        rest = rest[::-1]
    elif side != "start":
        raise ValueError("Material socket side must be 'start' or 'end'.")
    if not 0.0 < socket_length < float(np.sum(rest)):
        return float("inf")
    cumulative = np.concatenate([[0.0], np.cumsum(rest)])
    active = np.flatnonzero(cumulative[:-1] < socket_length)
    if active.size == 0:
        return float("inf")
    # For edge e, ||delta(p_{e+1}-p_e)|| <= B_e+B_{e+1}.  Summing edge
    # increments from the common junction gives ||delta r(s)|| <= K*s.
    return float(
        np.max((bounds[active] + bounds[active + 1]) / rest[active])
    )


def _guard_interval_lower_bounds(
    model: HighFidelityModel,
    controls: np.ndarray,
    time_start: float,
    time_end: float,
) -> tuple[dict[str, float], dict[str, float], bool]:
    """Lower-bound every guard over one Hermite/Bezier subinterval."""

    metadata = _guard_component_metadata_contract(model)
    midpoint_time = 0.5 * (time_start + time_end)
    midpoint_state = _bezier_value(controls, 0.5)
    try:
        snapshot = reference_snapshot_from_state(
            model,
            midpoint_time,
            midpoint_state,
            include_aero=False,
            compute_contact=False,
        )
    except (FloatingPointError, ValueError):
        # A collapsed segment, aerodynamic chord or quaternion is itself an
        # invalid midpoint.  Preserve fail-closed event semantics instead of
        # letting the reference force kernel abort before the guard certificate
        # can record the violation.
        invalid = {name: -float("inf") for name in metadata}
        return invalid.copy(), invalid, False
    n = model.position_size
    q_slice = slice(n + 3, n + 7)
    position_controls = controls[:, :n].reshape(4, model.particle_count, 3)
    particle_bounds = np.array(
        [
            _vector_motion_bound(position_controls[:, index, :])
            for index in range(model.particle_count)
        ]
    )
    bob_controls = controls[:, n : n + 3]
    bob_bound = _vector_motion_bound(bob_controls)
    quaternion_controls = controls[:, q_slice]
    quaternion_bound = _vector_motion_bound(quaternion_controls)
    midpoint_quaternion = _bezier_value(quaternion_controls, 0.5)
    quaternion_norm_lower = float(np.linalg.norm(midpoint_quaternion)) - quaternion_bound
    quaternion_certifiable = quaternion_norm_lower > 1.0e-12
    attachment_bound = float("inf")
    if quaternion_certifiable:
        attachment_bound = bob_bound + (
            4.0
            * float(np.linalg.norm(model.attachment_body))
            * quaternion_bound
            / quaternion_norm_lower
        )

    branch_point_bounds: dict[str, np.ndarray] = {}
    for name, branch in model.branches.items():
        if branch.start_kind in model.support_motion:
            start_bound = _support_motion_bound(
                model.support_motion[branch.start_kind], time_start, time_end
            )
        else:
            start_bound = float(particle_bounds[model.junction_index])
        if branch.end_kind == "junction":
            end_bound = float(particle_bounds[model.junction_index])
        else:
            end_bound = attachment_bound
        branch_point_bounds[name] = np.concatenate(
            [
                [start_bound],
                particle_bounds[branch.bead_indices],
                [end_bound],
            ]
        )

    minimum_segment_lower = float("inf")
    minimum_turn_lower = float("inf")
    minimum_aerodynamic_chord_lower = float("inf")
    for name, points in snapshot.branch_positions.items():
        bounds = branch_point_bounds[name]
        segments = np.diff(points, axis=0)
        lengths = np.linalg.norm(segments, axis=1)
        segment_motion = bounds[:-1] + bounds[1:]
        minimum_segment_lower = min(
            minimum_segment_lower,
            float(np.min(lengths - segment_motion - model.length_guard)),
        )
        if np.any(lengths <= segment_motion):
            minimum_turn_lower = -float("inf")
        else:
            tangent = segments / lengths[:, None]
            tangent_motion = 2.0 * segment_motion / (lengths - segment_motion)
            center_turn = 1.0 + np.einsum(
                "ij,ij->i", tangent[:-1], tangent[1:]
            )
            minimum_turn_lower = min(
                minimum_turn_lower,
                float(
                    np.min(
                        center_turn
                        - tangent_motion[:-1]
                        - tangent_motion[1:]
                        - model.bending_turn_clearance_floor
                    )
                ),
            )
        chord = points[2:] - points[:-2]
        chord_motion = bounds[2:] + bounds[:-2]
        minimum_aerodynamic_chord_lower = min(
            minimum_aerodynamic_chord_lower,
            float(
                np.min(
                    np.linalg.norm(chord, axis=1)
                    - chord_motion
                    - model.aerodynamic_chord_guard
                )
            ),
        )
    lower = {
        "MINIMUM_SEGMENT_LENGTH": minimum_segment_lower,
        "BENDING_TURN_CLEARANCE": minimum_turn_lower,
        "AERODYNAMIC_CHORD_LENGTH": minimum_aerodynamic_chord_lower,
    }
    midpoint = dict(snapshot.guard_margins)
    if model.contact_guard_enabled:
        bob_center = midpoint_state[n : n + 3]
        bob_rod_lower = float("inf")
        bob_rod_midpoint = float("inf")
        bob_socket_material_extent = float("inf")
        bob_socket_radial_midpoint = float("inf")
        bob_socket_radial_lower = float("inf")
        bob_socket_cut_midpoint = float("inf")
        bob_socket_cut_lower = float("inf")
        for name, points in snapshot.branch_positions.items():
            branch = model.branches[name]
            bounds = branch_point_bounds[name]
            diameter = branch.diameter
            if name == "lower":
                socket_length = (
                    model.bob_contact_radius
                    + 0.5 * diameter
                    + model.minimum_clearance
                )
                total = float(np.sum(branch.segment_rest_length))
                bob_socket_material_extent = min(
                    bob_socket_material_extent, total - socket_length
                )
                if socket_length >= total:
                    checked_segments = []
                else:
                    checked_segments = material_segments_outside_socket_reference(
                        points,
                        branch.segment_rest_length,
                        "end",
                        socket_length,
                    )
                    breakpoints = socket_material_breakpoints_reference(
                        branch.segment_rest_length, "end", socket_length
                    )
                    for left, right in zip(
                        breakpoints[:-1], breakpoints[1:], strict=True
                    ):
                        start, start_reference = material_point_from_joint_reference(
                            points,
                            branch.segment_rest_length,
                            "end",
                            float(left),
                        )
                        end, end_reference = material_point_from_joint_reference(
                            points,
                            branch.segment_rest_length,
                            "end",
                            float(right),
                        )
                        radial = start - bob_center
                        increment = end - start
                        center_value = float(radial @ increment)
                        bob_socket_radial_midpoint = min(
                            bob_socket_radial_midpoint, center_value
                        )
                        start_bound = _affine_material_motion_bound(
                            start_reference, bounds
                        )
                        end_bound = _affine_material_motion_bound(
                            end_reference, bounds
                        )
                        radial_bound = start_bound + bob_bound
                        increment_bound = start_bound + end_bound
                        bob_socket_radial_lower = min(
                            bob_socket_radial_lower,
                            center_value
                            - float(np.linalg.norm(radial)) * increment_bound
                            - float(np.linalg.norm(increment)) * radial_bound
                            - radial_bound * increment_bound,
                        )
                    boundary, boundary_reference = (
                        material_point_from_joint_reference(
                            points,
                            branch.segment_rest_length,
                            "end",
                            socket_length,
                        )
                    )
                    boundary_bound = _affine_material_motion_bound(
                        boundary_reference, bounds
                    )
                    bob_socket_cut_midpoint = min(
                        bob_socket_cut_midpoint,
                        float(np.linalg.norm(boundary - bob_center))
                        - socket_length,
                    )
                    bob_socket_cut_lower = min(
                        bob_socket_cut_lower,
                        float(np.linalg.norm(boundary - bob_center))
                        - boundary_bound
                        - bob_bound
                        - socket_length,
                    )
            else:
                checked_segments = [
                    (
                        points[index],
                        points[index + 1],
                        (index, index, 0.0),
                        (index + 1, index + 1, 0.0),
                    )
                    for index in range(points.shape[0] - 1)
                ]
            for start, end, start_reference, end_reference in checked_segments:
                center_margin = (
                    point_segment_distance_reference(
                        bob_center,
                        start,
                        end,
                    )
                    - model.bob_contact_radius
                    - 0.5 * diameter
                    - model.minimum_clearance
                )
                start_bound = _affine_material_motion_bound(
                    start_reference, bounds
                )
                end_bound = _affine_material_motion_bound(end_reference, bounds)
                bob_rod_midpoint = min(bob_rod_midpoint, center_margin)
                bob_rod_lower = min(
                    bob_rod_lower,
                    center_margin
                    - bob_bound
                    - max(start_bound, end_bound),
                )

        rod_rod_midpoint = float("inf")
        rod_rod_lower = float("inf")
        junction_material_extent = float("inf")
        junction_projective_midpoint = float("inf")
        junction_projective_lower = float("inf")
        junction_cut_midpoint = float("inf")
        junction_cut_lower = float("inf")
        for name, points in snapshot.branch_positions.items():
            branch = model.branches[name]
            bounds = branch_point_bounds[name]
            material_nodes = np.concatenate(
                [[0.0], np.cumsum(branch.segment_rest_length)]
            )
            registration_length = 1.01 * (
                branch.diameter + model.minimum_clearance
            )
            segment_count = points.shape[0] - 1
            for first in range(segment_count):
                for second in range(first + 1, segment_count):
                    center_distance = materially_separated_segment_distance_reference(
                        points[first],
                        points[first + 1],
                        points[second],
                        points[second + 1],
                        first_material_start=float(material_nodes[first]),
                        first_material_end=float(material_nodes[first + 1]),
                        second_material_start=float(material_nodes[second]),
                        second_material_end=float(material_nodes[second + 1]),
                        minimum_material_separation=registration_length,
                    )
                    if not np.isfinite(center_distance):
                        continue
                    center_margin = (
                        center_distance - branch.diameter - model.minimum_clearance
                    )
                    first_bound = max(
                        float(bounds[first]), float(bounds[first + 1])
                    )
                    second_bound = max(
                        float(bounds[second]), float(bounds[second + 1])
                    )
                    rod_rod_midpoint = min(rod_rod_midpoint, center_margin)
                    rod_rod_lower = min(
                        rod_rod_lower,
                        center_margin - first_bound - second_bound,
                    )

        branch_items = list(snapshot.branch_positions.items())
        for first_branch_index, (name_a, points_a) in enumerate(branch_items):
            branch_a = model.branches[name_a]
            bounds_a = branch_point_bounds[name_a]
            side_a = "start" if branch_a.start_kind == "junction" else "end"
            for name_b, points_b in branch_items[first_branch_index + 1 :]:
                branch_b = model.branches[name_b]
                bounds_b = branch_point_bounds[name_b]
                side_b = "start" if branch_b.start_kind == "junction" else "end"
                required_separation = (
                    0.5 * (branch_a.diameter + branch_b.diameter)
                    + model.minimum_clearance
                )
                socket_length = 2.0 * required_separation
                total_a = float(np.sum(branch_a.segment_rest_length))
                total_b = float(np.sum(branch_b.segment_rest_length))
                junction_material_extent = min(
                    junction_material_extent,
                    total_a - socket_length,
                    total_b - socket_length,
                )
                active_a = material_segments_outside_socket_reference(
                    points_a,
                    branch_a.segment_rest_length,
                    side_a,
                    socket_length,
                )
                active_b = material_segments_outside_socket_reference(
                    points_b,
                    branch_b.segment_rest_length,
                    side_b,
                    socket_length,
                )
                if not active_a or not active_b:
                    continue

                opening_squared = (
                    junction_socket_projective_opening_squared_reference(
                        points_a,
                        branch_a.segment_rest_length,
                        side_a,
                        points_b,
                        branch_b.segment_rest_length,
                        side_b,
                        socket_length,
                    )
                )
                registered_opening_squared = (
                    required_separation / (2.0 * socket_length)
                ) ** 2
                projective_midpoint = (
                    opening_squared - registered_opening_squared
                )
                junction_projective_midpoint = min(
                    junction_projective_midpoint, projective_midpoint
                )
                projective_motion = max(
                    _socket_projective_motion_rate_bound(
                        bounds_a,
                        branch_a.segment_rest_length,
                        side_a,
                        socket_length,
                    ),
                    _socket_projective_motion_rate_bound(
                        bounds_b,
                        branch_b.segment_rest_length,
                        side_b,
                        socket_length,
                    ),
                )
                projective_norm_lower = max(
                    np.sqrt(max(opening_squared, 0.0)) - projective_motion,
                    0.0,
                )
                junction_projective_lower = min(
                    junction_projective_lower,
                    projective_norm_lower**2 - registered_opening_squared,
                )

                boundary_a, boundary_a_reference = (
                    material_point_from_joint_reference(
                        points_a,
                        branch_a.segment_rest_length,
                        side_a,
                        socket_length,
                    )
                )
                boundary_b, boundary_b_reference = (
                    material_point_from_joint_reference(
                        points_b,
                        branch_b.segment_rest_length,
                        side_b,
                        socket_length,
                    )
                )
                boundary_a_bound = _affine_material_motion_bound(
                    boundary_a_reference, bounds_a
                )
                boundary_b_bound = _affine_material_motion_bound(
                    boundary_b_reference, bounds_b
                )
                cut_midpoint = (
                    float(np.linalg.norm(boundary_a - boundary_b))
                    - required_separation
                )
                junction_cut_midpoint = min(
                    junction_cut_midpoint, cut_midpoint
                )
                junction_cut_lower = min(
                    junction_cut_lower,
                    cut_midpoint - boundary_a_bound - boundary_b_bound,
                )

                all_a = [
                    (
                        points_a[index],
                        points_a[index + 1],
                        (index, index, 0.0),
                        (index + 1, index + 1, 0.0),
                    )
                    for index in range(points_a.shape[0] - 1)
                ]
                all_b = [
                    (
                        points_b[index],
                        points_b[index + 1],
                        (index, index, 0.0),
                        (index + 1, index + 1, 0.0),
                    )
                    for index in range(points_b.shape[0] - 1)
                ]
                for first_segments, second_segments in (
                    (active_a, all_b),
                    (all_a, active_b),
                ):
                    for start_a, end_a, start_a_ref, end_a_ref in first_segments:
                        first_bound = max(
                            _affine_material_motion_bound(start_a_ref, bounds_a),
                            _affine_material_motion_bound(end_a_ref, bounds_a),
                        )
                        for start_b, end_b, start_b_ref, end_b_ref in second_segments:
                            second_bound = max(
                                _affine_material_motion_bound(start_b_ref, bounds_b),
                                _affine_material_motion_bound(end_b_ref, bounds_b),
                            )
                            center_margin = (
                                segment_segment_distance_reference(
                                    start_a, end_a, start_b, end_b
                                )
                                - 0.5 * (branch_a.diameter + branch_b.diameter)
                                - model.minimum_clearance
                            )
                            rod_rod_midpoint = min(
                                rod_rod_midpoint, center_margin
                            )
                            rod_rod_lower = min(
                                rod_rod_lower,
                                center_margin - first_bound - second_bound,
                            )

        midpoint.update(
            {
                "BOB_ROD_CLEARANCE": bob_rod_midpoint,
                "ROD_SELF_CLEARANCE": rod_rod_midpoint,
                "BOB_SOCKET_MATERIAL_EXTENT": bob_socket_material_extent,
                "BOB_SOCKET_RADIAL_MONOTONICITY": bob_socket_radial_midpoint,
                "BOB_SOCKET_CUT_CLEARANCE": bob_socket_cut_midpoint,
                "JUNCTION_SOCKET_MATERIAL_EXTENT": junction_material_extent,
                "JUNCTION_SOCKET_PROJECTIVE_OPENING": (
                    junction_projective_midpoint
                ),
                "JUNCTION_SOCKET_CUT_CLEARANCE": junction_cut_midpoint,
            }
        )
        lower.update(
            {
                "BOB_ROD_CLEARANCE": bob_rod_lower,
                "ROD_SELF_CLEARANCE": rod_rod_lower,
                "BOB_SOCKET_MATERIAL_EXTENT": bob_socket_material_extent,
                "BOB_SOCKET_RADIAL_MONOTONICITY": bob_socket_radial_lower,
                "BOB_SOCKET_CUT_CLEARANCE": bob_socket_cut_lower,
                "JUNCTION_SOCKET_MATERIAL_EXTENT": junction_material_extent,
                "JUNCTION_SOCKET_PROJECTIVE_OPENING": (
                    junction_projective_lower
                ),
                "JUNCTION_SOCKET_CUT_CLEARANCE": junction_cut_lower,
            }
        )
    return lower, midpoint, quaternion_certifiable


def _continuous_guard_certificate(
    bundle: _RunBundle,
    minimum_normalized_guard_margin: float,
    accepted_cache: _AcceptedStepReferenceCache | None = None,
) -> dict[str, Any]:
    """Certify positive continuous guard margins on every accepted step.

    Cubic state coordinates are bounded with their Bezier derivative convex
    hull.  Distance guards are Lipschitz in their defining material points.
    A positive lower bound therefore excludes a missed positive-negative-positive
    crossing; tangency cannot be certified and fails closed as EVENT_UNRESOLVED.
    """

    cache = accepted_cache or _accepted_step_reference_cache(bundle)
    time = cache.time
    state = cache.state
    model = bundle.model
    metadata = _guard_component_metadata_contract(model)
    minimum_normalized_guard_margin = _finite_real(
        minimum_normalized_guard_margin,
        name="minimum_normalized_guard_margin",
        minimum=0.0,
        strict=False,
    )
    n = model.position_size
    q_slice = slice(n + 3, n + 7)
    rhs = cache.rhs
    maximum_depth = 20
    step_certificates: list[dict[str, Any]] = []
    overall_passed = True
    overall_status = "CERTIFIED_POSITIVE"

    def required_raw(component: str) -> float:
        component_metadata = metadata[component]
        return max(
            float(component_metadata["tolerance"]),
            minimum_normalized_guard_margin * float(component_metadata["scale"]),
        )

    for step_index in range(time.size - 1):
        step = float(time[step_index + 1] - time[step_index])
        root_controls = _hermite_bezier_controls(
            state[step_index],
            state[step_index + 1],
            rhs[step_index],
            rhs[step_index + 1],
            step,
            quaternion_slice=q_slice,
        )
        stack = [
            (
                root_controls,
                float(time[step_index]),
                float(time[step_index + 1]),
                0,
            )
        ]
        certified_lower = {name: float("inf") for name in metadata}
        leaf_count = 0
        step_status = "CERTIFIED_POSITIVE"
        evidence: dict[str, Any] | None = None
        while stack:
            controls, interval_start, interval_end, depth = stack.pop()
            lower, midpoint, quaternion_ok = _guard_interval_lower_bounds(
                model, controls, interval_start, interval_end
            )
            nonpositive_midpoint = {
                name: value
                for name, value in midpoint.items()
                if name not in metadata or not value > required_raw(name)
            }
            missing_midpoint = set(metadata) - set(midpoint)
            if missing_midpoint:
                nonpositive_midpoint.update(
                    {name: -float("inf") for name in sorted(missing_midpoint)}
                )
            if nonpositive_midpoint:
                step_status = "GUARD_CROSSING_OR_TANGENCY_DETECTED"
                evidence = {
                    "interval_s": [interval_start, interval_end],
                    "midpoint_s": 0.5 * (interval_start + interval_end),
                    "guard_margins_raw": {
                        name: float(value) if np.isfinite(value) else None
                        for name, value in midpoint.items()
                    },
                    "nonpositive_components": {
                        name: float(value) if np.isfinite(value) else None
                        for name, value in nonpositive_midpoint.items()
                    },
                }
                break
            if quaternion_ok and all(
                name in lower and lower[name] > required_raw(name)
                for name in metadata
            ) and not (set(lower) - set(metadata)):
                leaf_count += 1
                for name, value in lower.items():
                    certified_lower[name] = min(certified_lower[name], float(value))
                continue
            if depth >= maximum_depth:
                step_status = "EVENT_UNRESOLVED"
                evidence = {
                    "interval_s": [interval_start, interval_end],
                    "midpoint_s": 0.5 * (interval_start + interval_end),
                    "guard_margins_raw": {
                        name: float(value) if np.isfinite(value) else None
                        for name, value in midpoint.items()
                    },
                    "candidate_lower_bounds_raw": {
                        name: float(value) if np.isfinite(value) else None
                        for name, value in lower.items()
                    },
                    "quaternion_norm_certified": quaternion_ok,
                    "reason": "continuous positive margin could not be certified",
                }
                break
            left, right = _split_bezier_half(controls)
            midpoint_time = 0.5 * (interval_start + interval_end)
            stack.append((right, midpoint_time, interval_end, depth + 1))
            stack.append((left, interval_start, midpoint_time, depth + 1))
        step_passed = step_status == "CERTIFIED_POSITIVE"
        overall_passed &= step_passed
        if not step_passed:
            overall_status = (
                "EVENT_UNRESOLVED"
                if step_status == "EVENT_UNRESOLVED"
                else "GUARD_VIOLATION"
            )
        step_certificates.append(
            {
                "accepted_step_index": step_index,
                "time_bracket_s": [float(time[step_index]), float(time[step_index + 1])],
                "status": step_status,
                "passed": step_passed,
                "guard_components": {
                    name: {
                        "unit": metadata[name]["unit"],
                        "scale": float(metadata[name]["scale"]),
                        "raw_tolerance": float(metadata[name]["tolerance"]),
                        "required_normalized_lower_bound": max(
                            minimum_normalized_guard_margin,
                            float(metadata[name]["tolerance"])
                            / float(metadata[name]["scale"]),
                        ),
                        "certified_raw_lower_bound": (
                            float(certified_lower[name])
                            if np.isfinite(certified_lower[name])
                            else None
                        ),
                        "certified_normalized_lower_bound": (
                            float(
                                certified_lower[name]
                                / float(metadata[name]["scale"])
                            )
                            if np.isfinite(certified_lower[name])
                            else None
                        ),
                    }
                    for name in metadata
                },
                "certified_leaf_count": leaf_count,
                "evidence": evidence,
            }
        )
    return {
        "passed": overall_passed,
        "status": overall_status,
        "failure_physical_status": None if overall_passed else "UNDETERMINED",
        "failure_numerical_status": None if overall_passed else "EVENT_UNRESOLVED",
        "minimum_normalized_guard_margin": minimum_normalized_guard_margin,
        "normalization_definition": "raw_guard_margin / component_physical_scale",
        "strict_comparison": True,
        "guard_component_metadata": metadata,
        "accepted_step_count": int(max(time.size - 1, 0)),
        "step_certificates": step_certificates,
    }


def _expected_output_grid(cfg: SimulationConfig) -> np.ndarray:
    horizon = float(to_si(cfg.solver.t_end, default_unit="s"))
    step = float(to_si(cfg.solver.output_dt, default_unit="s"))
    count = int(np.floor(horizon / step + 1.0e-12))
    expected = np.arange(count + 1, dtype=float) * step
    if expected[-1] < horizon - 1.0e-12:
        expected = np.append(expected, horizon)
    return expected


def _finite_nested(value: Any) -> bool:
    if isinstance(value, dict):
        return all(_finite_nested(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_finite_nested(item) for item in value)
    if isinstance(value, np.ndarray):
        return bool(np.all(np.isfinite(value)))
    if isinstance(value, (float, np.floating)):
        return bool(np.isfinite(value))
    return True


def _signed_axial_force_series(
    result: HighFidelityResult,
) -> dict[str, np.ndarray] | None:
    """Consume the registered signed-force series, with a fail-closed legacy probe."""

    for attribute in ("cable_axial_force", "branch_axial_force"):
        value = getattr(result, attribute, None)
        if isinstance(value, dict):
            return value
    return None


def _result_shape_checks(bundle: _RunBundle) -> dict[str, bool]:
    """Bind every canonical trajectory family to the candidate mesh and time grid."""

    result = bundle.result
    model = bundle.model
    time = np.asarray(result.time)
    nt = time.size
    integration_time = np.asarray(result.integration_time)
    ni = integration_time.size
    expected_branches = set(model.branches)
    expected_guards = set(_guard_component_metadata_contract(model))
    expected_energy = {
        "kinetic",
        "kinetic_particles",
        "kinetic_bob_translation",
        "kinetic_bob_rotation",
        "gravitational",
        "elastic_axial",
        "elastic_bending",
        "mechanical",
        "axial_dissipation_rate",
        "aero_dissipation_rate",
        "air_work_rate",
        "support_work_rate",
        "dissipation_axial",
        "dissipation_aero",
        "work_air",
        "work_support",
        "balance_residual",
    }
    branch_shapes = True
    signed_axial_force = _signed_axial_force_series(result)
    if (
        set(result.cable_positions) != expected_branches
        or set(result.cable_velocities) != expected_branches
        or set(result.cable_tension) != expected_branches
        or signed_axial_force is None
        or set(signed_axial_force) != expected_branches
    ):
        branch_shapes = False
    else:
        for name, branch in model.branches.items():
            bead_count = int(branch.bead_indices.size)
            branch_shapes &= result.cable_positions[name].shape == (
                nt,
                bead_count + 2,
                3,
            )
            branch_shapes &= result.cable_velocities[name].shape == (
                nt,
                bead_count + 2,
                3,
            )
            branch_shapes &= result.cable_tension[name].shape == (
                nt,
                bead_count + 1,
            )
            branch_shapes &= signed_axial_force[name].shape == (  # type: ignore[index]
                nt,
                bead_count + 1,
            )
    scalar_series_shapes = (
        set(result.energy) == expected_energy
        and all(np.asarray(values).shape == (nt,) for values in result.energy.values())
        and set(result.guard_margins) == expected_guards
        and all(
            np.asarray(values).shape == (nt,)
            for values in result.guard_margins.values()
        )
    )
    reaction_shapes = set(result.reactions) == {"support_A", "support_B"} and all(
        np.asarray(values).shape == (nt, 3) for values in result.reactions.values()
    )
    return {
        "model_id_exact": result.model_id == HighFidelityModel.model_id,
        "time_vector_shape": time.ndim == 1 and nt >= 2,
        "integration_certificate_shapes": (
            integration_time.ndim == 1
            and ni >= 2
            and result.integration_particle_positions.shape
            == (ni, model.particle_count, 3)
            and result.integration_particle_velocities.shape
            == (ni, model.particle_count, 3)
            and result.integration_bob_position.shape == (ni, 3)
            and result.integration_bob_velocity.shape == (ni, 3)
            and result.integration_bob_quaternion.shape == (ni, 4)
            and result.integration_bob_angular_velocity.shape == (ni, 3)
        ),
        "integration_certificate_time_order": (
            ni >= 2
            and integration_time[0] == 0.0
            and bool(np.all(np.diff(integration_time) > 0.0))
            and integration_time[-1]
            == float(to_si(bundle.config.solver.t_end, default_unit="s"))
        ),
        "canonical_state_shapes": (
            result.particle_positions.shape == (nt, model.particle_count, 3)
            and result.particle_velocities.shape == (nt, model.particle_count, 3)
            and result.junction_position.shape == (nt, 3)
            and result.junction_velocity.shape == (nt, 3)
            and result.bob_position.shape == (nt, 3)
            and result.bob_velocity.shape == (nt, 3)
            and result.bob_quaternion.shape == (nt, 4)
            and result.bob_angular_velocity.shape == (nt, 3)
            and result.bob_attachment_position.shape == (nt, 3)
        ),
        "canonical_branch_shapes": bool(branch_shapes),
        "signed_axial_force_series_present": signed_axial_force is not None,
        "canonical_scalar_series_shapes": bool(scalar_series_shapes),
        "canonical_reaction_shapes": bool(reaction_shapes),
        "junction_state_binding": (
            result.particle_positions.shape == (nt, model.particle_count, 3)
            and result.particle_velocities.shape == (nt, model.particle_count, 3)
            and result.junction_position.shape == (nt, 3)
            and result.junction_velocity.shape == (nt, 3)
            and bool(
                np.array_equal(
                    result.junction_position,
                    result.particle_positions[:, model.junction_index],
                )
            )
            and bool(
                np.array_equal(
                    result.junction_velocity,
                    result.particle_velocities[:, model.junction_index],
                )
            )
        ),
    }


def _legacy_canonical_series_consistency(bundle: _RunBundle) -> dict[str, Any]:
    """Reconstruct canonical local-link fields from the returned HF state."""

    result = bundle.result
    model = bundle.model
    time = np.asarray(result.time, dtype=float)
    nt = time.size
    length_scale = model.characteristic_length
    gravity_time = np.sqrt(length_scale / float(np.linalg.norm(model.gravity)))
    velocity_scale = length_scale / gravity_time
    force_scale = model.force_scale
    energy_scale = max(force_scale * length_scale, 1.0e-15)
    eps = np.finfo(float).eps
    tolerances = {
        "position_m": 4096.0 * eps * length_scale,
        "velocity_m_s": 4096.0 * eps * velocity_scale,
        "tension_N": 4096.0 * eps * force_scale,
        "energy_J": 8192.0 * eps * energy_scale,
        "power_W": 8192.0 * eps * force_scale * velocity_scale,
    }

    attachment = np.vstack(
        [
            result.bob_position[index]
            + rotate_body_vector_reference(
                result.bob_quaternion[index], model.attachment_body
            )
            for index in range(nt)
        ]
    )
    attachment_velocity = np.vstack(
        [
            result.bob_velocity[index]
            + np.cross(
                result.bob_angular_velocity[index],
                attachment[index] - result.bob_position[index],
            )
            for index in range(nt)
        ]
    )
    errors: dict[str, float] = {
        "bob_attachment_position_m": float(
            np.max(np.abs(attachment - result.bob_attachment_position))
        ),
        "material_path_position_m": 0.0,
        "material_path_velocity_m_s": 0.0,
        "signed_axial_force_N": 0.0,
        "tension_N": 0.0,
        "minimum_segment_guard_m": 0.0,
    }
    expected_axial_energy = np.zeros(nt)
    expected_axial_dissipation = np.zeros(nt)
    minimum_segment = np.full(nt, np.inf)

    support_state = {
        name: [model.support_motion[name].state(float(t)) for t in time]
        for name in ("support_A", "support_B")
    }
    for name, branch in model.branches.items():
        if branch.start_kind in support_state:
            start_position = np.vstack(
                [item[0] for item in support_state[branch.start_kind]]
            )
            start_velocity = np.vstack(
                [item[1] for item in support_state[branch.start_kind]]
            )
        else:
            start_position = result.junction_position
            start_velocity = result.junction_velocity
        if branch.end_kind == "junction":
            end_position = result.junction_position
            end_velocity = result.junction_velocity
        else:
            end_position = attachment
            end_velocity = attachment_velocity
        expected_position = np.concatenate(
            [
                start_position[:, None, :],
                result.particle_positions[:, branch.bead_indices, :],
                end_position[:, None, :],
            ],
            axis=1,
        )
        expected_velocity = np.concatenate(
            [
                start_velocity[:, None, :],
                result.particle_velocities[:, branch.bead_indices, :],
                end_velocity[:, None, :],
            ],
            axis=1,
        )
        errors["material_path_position_m"] = max(
            errors["material_path_position_m"],
            float(
                np.max(
                    np.abs(expected_position - result.cable_positions[name])
                )
            ),
        )
        errors["material_path_velocity_m_s"] = max(
            errors["material_path_velocity_m_s"],
            float(
                np.max(
                    np.abs(expected_velocity - result.cable_velocities[name])
                )
            ),
        )
        segment = expected_position[:, 1:, :] - expected_position[:, :-1, :]
        segment_length = np.linalg.norm(segment, axis=2)
        tangent = segment / segment_length[:, :, None]
        relative_velocity = expected_velocity[:, 1:, :] - expected_velocity[:, :-1, :]
        extension_rate = np.einsum("tij,tij->ti", relative_velocity, tangent)
        extension = segment_length - branch.segment_rest_length[None, :]
        stiffness = branch.ea / branch.segment_rest_length
        viscosity = branch.eta_a / branch.segment_rest_length
        trial = stiffness[None, :] * extension + viscosity[None, :] * extension_rate
        taut = (extension > 0.0) & (trial > 0.0)
        expected_tension = np.where(taut, trial, 0.0)
        errors["tension_N"] = max(
            errors["tension_N"],
            float(np.max(np.abs(expected_tension - result.cable_tension[name]))),
        )
        positive_extension = np.maximum(extension, 0.0)
        expected_axial_energy += 0.5 * np.sum(
            stiffness[None, :] * positive_extension**2, axis=1
        )
        expected_axial_dissipation += np.sum(
            np.where(taut, viscosity[None, :] * extension_rate**2, 0.0),
            axis=1,
        )
        release = (extension > 0.0) & ~taut & (extension_rate < 0.0)
        expected_axial_dissipation += np.sum(
            np.where(
                release,
                -stiffness[None, :] * extension * extension_rate,
                0.0,
            ),
            axis=1,
        )
        minimum_segment = np.minimum(minimum_segment, np.min(segment_length, axis=1))

    kinetic_particles = 0.5 * np.sum(
        model.particle_mass[None, :, None] * result.particle_velocities**2,
        axis=(1, 2),
    )
    kinetic_bob_translation = 0.5 * model.bob_mass * np.sum(
        result.bob_velocity**2, axis=1
    )
    kinetic_bob_rotation = 0.5 * model.bob_inertia * np.sum(
        result.bob_angular_velocity**2, axis=1
    )
    kinetic = kinetic_particles + kinetic_bob_translation + kinetic_bob_rotation
    gravitational = -np.sum(
        model.particle_mass[None, :, None]
        * result.particle_positions
        * model.gravity[None, None, :],
        axis=(1, 2),
    ) - model.bob_mass * np.einsum("ti,i->t", result.bob_position, model.gravity)
    gravitational -= np.einsum("ti,i->t", result.bob_position, model.bob_buoyancy)
    mechanical_composition = (
        kinetic
        + gravitational
        + result.energy["elastic_axial"]
        + result.energy["elastic_bending"]
    )
    errors.update(
        {
            "kinetic_particles_J": float(
                np.max(
                    np.abs(
                        kinetic_particles - result.energy["kinetic_particles"]
                    )
                )
            ),
            "kinetic_bob_translation_J": float(
                np.max(
                    np.abs(
                        kinetic_bob_translation
                        - result.energy["kinetic_bob_translation"]
                    )
                )
            ),
            "kinetic_bob_rotation_J": float(
                np.max(
                    np.abs(
                        kinetic_bob_rotation
                        - result.energy["kinetic_bob_rotation"]
                    )
                )
            ),
            "kinetic_total_J": float(
                np.max(np.abs(kinetic - result.energy["kinetic"]))
            ),
            "gravitational_J": float(
                np.max(np.abs(gravitational - result.energy["gravitational"]))
            ),
            "elastic_axial_J": float(
                np.max(
                    np.abs(expected_axial_energy - result.energy["elastic_axial"])
                )
            ),
            "axial_dissipation_W": float(
                np.max(
                    np.abs(
                        expected_axial_dissipation
                        - result.energy["axial_dissipation_rate"]
                    )
                )
            ),
            "mechanical_composition_J": float(
                np.max(
                    np.abs(mechanical_composition - result.energy["mechanical"])
                )
            ),
            "minimum_segment_guard_m": float(
                np.max(
                    np.abs(
                        minimum_segment
                        - model.length_guard
                        - result.guard_margins["MINIMUM_SEGMENT_LENGTH"]
                    )
                )
            ),
        }
    )
    checks = {
        "bob_attachment_position_consistent": errors[
            "bob_attachment_position_m"
        ]
        <= tolerances["position_m"],
        "material_path_position_consistent": errors[
            "material_path_position_m"
        ]
        <= tolerances["position_m"],
        "material_path_velocity_consistent": errors[
            "material_path_velocity_m_s"
        ]
        <= tolerances["velocity_m_s"],
        "local_tension_consistent": errors["tension_N"]
        <= tolerances["tension_N"],
        "minimum_segment_guard_consistent": errors[
            "minimum_segment_guard_m"
        ]
        <= tolerances["position_m"],
        "kinetic_energy_consistent": max(
            errors["kinetic_particles_J"],
            errors["kinetic_bob_translation_J"],
            errors["kinetic_bob_rotation_J"],
            errors["kinetic_total_J"],
        )
        <= tolerances["energy_J"],
        "gravitational_energy_consistent": errors["gravitational_J"]
        <= tolerances["energy_J"],
        "axial_energy_consistent": errors["elastic_axial_J"]
        <= tolerances["energy_J"],
        "axial_dissipation_consistent": errors["axial_dissipation_W"]
        <= tolerances["power_W"],
        "mechanical_energy_composition_consistent": errors[
            "mechanical_composition_J"
        ]
        <= tolerances["energy_J"],
    }
    return {"passed": all(checks.values()), "checks": checks, "errors": errors, "tolerances": tolerances}


def _canonical_series_consistency(bundle: _RunBundle) -> dict[str, Any]:
    """Rebuild all decisive derived series with the independent reference kernel."""

    result = bundle.result
    model = bundle.model
    time = np.asarray(result.time, dtype=float)
    state = _state_matrix(bundle)
    snapshots = [
        reference_snapshot_from_state(model, float(t), y, compute_contact=True)
        for t, y in zip(time, state, strict=True)
    ]
    nt = time.size
    length_scale = model.characteristic_length
    gravity_time = np.sqrt(length_scale / float(np.linalg.norm(model.gravity)))
    velocity_scale = length_scale / gravity_time
    force_scale = model.force_scale
    energy_scale = origin_invariant_energy_scale(model)
    power_scale = force_scale * velocity_scale
    eps = np.finfo(float).eps
    guard_metadata = _guard_component_metadata_contract(model)
    expected_guard_names = set(guard_metadata)
    if (
        set(result.guard_margins) != expected_guard_names
        or any(
            set(snapshot.guard_margins) != expected_guard_names
            for snapshot in snapshots
        )
    ):
        raise ValueError(
            "Independent and reported guard vocabularies must exactly match "
            "the frozen component metadata."
        )
    guard_tolerances = {
        name: max(
            64.0 * float(item["tolerance"]),
            65536.0 * eps * float(item["scale"]),
        )
        for name, item in guard_metadata.items()
    }
    tolerances: dict[str, Any] = {
        "position_m": 16384.0 * eps * max(
            length_scale,
            float(np.max(np.abs(state[:, : model.position_size + 3]))),
        ),
        "velocity_m_s": 16384.0 * eps * max(
            velocity_scale,
            float(
                np.max(
                    np.abs(
                        state[
                            :,
                            model.position_size
                            + 7 : model.position_size
                            + 7
                            + model.position_size
                            + 3,
                        ]
                    )
                )
            ),
        ),
        "tension_or_reaction_N": 32768.0 * eps * force_scale,
        "energy_J": 65536.0 * eps * energy_scale,
        "power_W": 65536.0 * eps * max(power_scale, np.finfo(float).tiny),
        "guard_m": 32768.0 * eps * length_scale,
        "dimensionless_guard": 65536.0 * eps,
        "guard_components_raw": guard_tolerances,
        "cumulative_J": (
            131072.0 * eps * energy_scale * max(1.0, np.sqrt(float(nt)))
        ),
    }

    expected_attachment = np.vstack(
        [
            result.bob_position[index]
            + rotate_body_vector_reference(
                result.bob_quaternion[index], model.attachment_body
            )
            for index in range(nt)
        ]
    )
    errors: dict[str, float] = {
        "bob_attachment_position_m": float(
            np.max(np.abs(expected_attachment - result.bob_attachment_position))
        ),
        "material_path_position_m": 0.0,
        "material_path_velocity_m_s": 0.0,
        "tension_N": 0.0,
        "signed_axial_force_N": 0.0,
        "support_reaction_N": 0.0,
        **{f"guard_{name}": 0.0 for name in guard_metadata},
    }
    reported_signed_axial_force = _signed_axial_force_series(result)
    if reported_signed_axial_force is None:
        raise ValueError("Signed axial-force series is absent from the HF result.")
    for name in model.branches:
        expected_position = np.stack(
            [snapshot.branch_positions[name] for snapshot in snapshots]
        )
        expected_velocity = np.stack(
            [snapshot.branch_velocities[name] for snapshot in snapshots]
        )
        expected_tension = np.stack(
            [snapshot.branch_tension[name] for snapshot in snapshots]
        )
        expected_signed_axial_force = np.stack(
            [snapshot.branch_axial_force[name] for snapshot in snapshots]
        )
        errors["material_path_position_m"] = max(
            errors["material_path_position_m"],
            float(np.max(np.abs(expected_position - result.cable_positions[name]))),
        )
        errors["material_path_velocity_m_s"] = max(
            errors["material_path_velocity_m_s"],
            float(np.max(np.abs(expected_velocity - result.cable_velocities[name]))),
        )
        errors["tension_N"] = max(
            errors["tension_N"],
            float(np.max(np.abs(expected_tension - result.cable_tension[name]))),
        )
        errors["signed_axial_force_N"] = max(
            errors["signed_axial_force_N"],
            float(
                np.max(
                    np.abs(
                        expected_signed_axial_force
                        - reported_signed_axial_force[name]
                    )
                )
            ),
        )

    expected_reaction = {
        name: -np.stack([snapshot.support_force[name] for snapshot in snapshots])
        for name in ("support_A", "support_B")
    }
    errors["support_reaction_N"] = max(
        float(np.max(np.abs(expected_reaction[name] - result.reactions[name])))
        for name in expected_reaction
    )
    for guard_name in guard_metadata:
        expected = np.asarray(
            [snapshot.guard_margins[guard_name] for snapshot in snapshots]
        )
        errors[f"guard_{guard_name}"] = float(
            np.max(np.abs(expected - result.guard_margins[guard_name]))
        )

    expected_energy = {
        "kinetic_particles": np.asarray(
            [snapshot.kinetic_particles for snapshot in snapshots]
        ),
        "kinetic_bob_translation": np.asarray(
            [snapshot.kinetic_bob_translation for snapshot in snapshots]
        ),
        "kinetic_bob_rotation": np.asarray(
            [snapshot.kinetic_bob_rotation for snapshot in snapshots]
        ),
        "gravitational": np.asarray(
            [snapshot.gravitational for snapshot in snapshots]
        ),
        "elastic_axial": np.asarray(
            [snapshot.axial_energy for snapshot in snapshots]
        ),
        "elastic_bending": np.asarray(
            [snapshot.bending_energy for snapshot in snapshots]
        ),
        "mechanical": np.asarray(
            [snapshot.mechanical_energy for snapshot in snapshots]
        ),
        "axial_dissipation_rate": np.asarray(
            [snapshot.axial_dissipation_rate for snapshot in snapshots]
        ),
        "aero_dissipation_rate": np.asarray(
            [snapshot.aero_dissipation_rate for snapshot in snapshots]
        ),
        "air_work_rate": np.asarray(
            [snapshot.air_work_rate for snapshot in snapshots]
        ),
        "support_work_rate": np.asarray(
            [snapshot.support_work_rate for snapshot in snapshots]
        ),
    }
    expected_energy["kinetic"] = (
        expected_energy["kinetic_particles"]
        + expected_energy["kinetic_bob_translation"]
        + expected_energy["kinetic_bob_rotation"]
    )
    for name, expected in expected_energy.items():
        errors[f"energy_{name}"] = float(
            np.max(np.abs(expected - np.asarray(result.energy[name], dtype=float)))
        )

    cumulative = {
        "dissipation_axial": cumulative_trapezoid_reference(
            time, expected_energy["axial_dissipation_rate"]
        ),
        "dissipation_aero": cumulative_trapezoid_reference(
            time, expected_energy["aero_dissipation_rate"]
        ),
        "work_air": cumulative_trapezoid_reference(
            time, expected_energy["air_work_rate"]
        ),
        "work_support": cumulative_trapezoid_reference(
            time, expected_energy["support_work_rate"]
        ),
    }
    for name, expected in cumulative.items():
        errors[f"cumulative_{name}"] = float(
            np.max(np.abs(expected - np.asarray(result.energy[name], dtype=float)))
        )

    guard_check_names = {
        "MINIMUM_SEGMENT_LENGTH": "minimum_segment_guard_consistent",
        "BENDING_TURN_CLEARANCE": "bending_turn_guard_consistent",
        "AERODYNAMIC_CHORD_LENGTH": "aerodynamic_chord_guard_consistent",
        "BOB_ROD_CLEARANCE": "bob_rod_guard_consistent",
        "ROD_SELF_CLEARANCE": "rod_rod_guard_consistent",
        "BOB_SOCKET_MATERIAL_EXTENT": "bob_socket_material_extent_consistent",
        "BOB_SOCKET_RADIAL_MONOTONICITY": (
            "bob_socket_radial_monotonicity_consistent"
        ),
        "BOB_SOCKET_CUT_CLEARANCE": "bob_socket_cut_clearance_consistent",
        "JUNCTION_SOCKET_MATERIAL_EXTENT": (
            "junction_socket_material_extent_consistent"
        ),
        "JUNCTION_SOCKET_PROJECTIVE_OPENING": (
            "junction_socket_projective_opening_consistent"
        ),
        "JUNCTION_SOCKET_CUT_CLEARANCE": (
            "junction_socket_cut_clearance_consistent"
        ),
    }
    guard_checks = {
        guard_check_names[name]: (
            errors[f"guard_{name}"] <= guard_tolerances[name]
        )
        for name in guard_metadata
    }
    checks = {
        "bob_attachment_position_consistent": errors[
            "bob_attachment_position_m"
        ]
        <= tolerances["position_m"],
        "material_path_position_consistent": errors[
            "material_path_position_m"
        ]
        <= tolerances["position_m"],
        "material_path_velocity_consistent": errors[
            "material_path_velocity_m_s"
        ]
        <= tolerances["velocity_m_s"],
        "nonnegative_tension_consistent": errors["tension_N"]
        <= tolerances["tension_or_reaction_N"],
        "signed_axial_force_consistent": errors["signed_axial_force_N"]
        <= tolerances["tension_or_reaction_N"],
        "support_reaction_consistent": errors["support_reaction_N"]
        <= tolerances["tension_or_reaction_N"],
        **guard_checks,
        "instantaneous_energy_consistent": all(
            errors[f"energy_{name}"] <= tolerances["energy_J"]
            for name in (
                "kinetic",
                "kinetic_particles",
                "kinetic_bob_translation",
                "kinetic_bob_rotation",
                "gravitational",
                "elastic_axial",
                "elastic_bending",
                "mechanical",
            )
        ),
        "instantaneous_power_consistent": all(
            errors[f"energy_{name}"] <= tolerances["power_W"]
            for name in (
                "axial_dissipation_rate",
                "aero_dissipation_rate",
                "air_work_rate",
                "support_work_rate",
            )
        ),
        "cumulative_work_and_dissipation_consistent": all(
            errors[f"cumulative_{name}"] <= tolerances["cumulative_J"]
            for name in cumulative
        ),
    }
    return {
        "passed": all(checks.values()),
        "oracle": "ypendulum.hf.reference.evaluate_reference_no_model_evaluate",
        "checks": checks,
        "errors": errors,
        "tolerances": tolerances,
    }


def _independent_energy_balance(bundle: _RunBundle) -> dict[str, Any]:
    """Rebuild the energy ledger with an origin-invariant physical scale."""

    result = bundle.result
    time = np.asarray(result.time, dtype=float)
    snapshots = [
        reference_snapshot_from_state(bundle.model, float(t), state, compute_contact=False)
        for t, state in zip(time, _state_matrix(bundle), strict=True)
    ]
    mechanical = np.asarray(
        [snapshot.mechanical_energy for snapshot in snapshots], dtype=float
    )
    dissipation_axial = cumulative_trapezoid_reference(
        time,
        np.asarray(
            [snapshot.axial_dissipation_rate for snapshot in snapshots], dtype=float
        ),
    )
    dissipation_aero = cumulative_trapezoid_reference(
        time,
        np.asarray(
            [snapshot.aero_dissipation_rate for snapshot in snapshots], dtype=float
        ),
    )
    work_air = cumulative_trapezoid_reference(
        time,
        np.asarray([snapshot.air_work_rate for snapshot in snapshots], dtype=float),
    )
    work_support = cumulative_trapezoid_reference(
        time,
        np.asarray([snapshot.support_work_rate for snapshot in snapshots], dtype=float),
    )
    scale = origin_invariant_energy_scale(bundle.model)
    axial_rate = np.asarray(
        [snapshot.axial_dissipation_rate for snapshot in snapshots], dtype=float
    )
    aero_rate = np.asarray(
        [snapshot.aero_dissipation_rate for snapshot in snapshots], dtype=float
    )
    length = bundle.model.characteristic_length
    gravity_time = np.sqrt(length / float(np.linalg.norm(bundle.model.gravity)))
    physical_power_scale = bundle.model.force_scale * length / gravity_time
    cancellation_scale = max(
        physical_power_scale,
        *(snapshot.axial_power_roundoff_scale for snapshot in snapshots),
        *(snapshot.aero_power_roundoff_scale for snapshot in snapshots),
    )
    raw_passivity_tolerance = 512.0 * np.finfo(float).eps * cancellation_scale
    minimum_raw_dissipation = min(float(np.min(axial_rate)), float(np.min(aero_rate)))
    balance = (
        mechanical
        - mechanical[0]
        + dissipation_axial
        + dissipation_aero
        - work_air
        - work_support
    ) / scale
    maximum = float(np.max(np.abs(balance)))
    return {
        "maximum_abs_residual": maximum,
        "normalization_scale_J": float(scale),
        "normalization_definition": "model.force_scale_N * model.characteristic_length_m",
        "origin_translation_invariant": True,
        "reported_balance_series_used_as_oracle": False,
        "minimum_raw_dissipation_rate_W": minimum_raw_dissipation,
        "raw_passivity_roundoff_tolerance_W": float(raw_passivity_tolerance),
        "raw_passivity_certified": (
            minimum_raw_dissipation >= -raw_passivity_tolerance
        ),
    }


def _preparation_certificate(bundle: _RunBundle) -> dict[str, Any]:
    """Bind held-equilibrium stability and fixture fields to the initial state."""

    preparation = bundle.preparation
    if bundle.config.initial_condition.type != "held_endpoint_equilibrium_release":
        return {
            "applicability": "not_a_held_endpoint_equilibrium_release",
            "passed": True,
            "checks": {},
        }

    audit = preparation.audit
    required_audit = {
        "protocol",
        "fixed_dofs",
        "static_free_material_residual_inf_N",
        "static_fixture_reaction_force_world_N",
        "static_fixture_reaction_torque_world_Nm",
        "actual_release_free_material_net_force_inf_N",
        "actual_release_junction_net_force_world_N",
        "actual_release_bob_net_force_world_N",
        "actual_release_bob_net_torque_world_Nm",
        "minimum_hessian_eigenvalue_N_per_m",
        "hessian_tolerance_N_per_m",
        "stability_class",
        "selected_seed",
        "candidate_records",
    }
    if not isinstance(audit, dict) or not required_audit.issubset(audit):
        return {
            "applicability": "held_endpoint_equilibrium_release",
            "passed": False,
            "checks": {"held_preparation_audit_schema": False},
            "reason": "held preparation audit is absent or incomplete",
        }

    model = bundle.model
    state = np.asarray(preparation.state, dtype=float)
    velocity_offset = model.position_size + 7
    equilibrium_state = state.copy()
    equilibrium_state[velocity_offset:] = 0.0
    equilibrium = reference_snapshot_from_state(
        model,
        0.0,
        equilibrium_state,
        include_aero=False,
        compute_contact=False,
    )
    release = reference_snapshot_from_state(
        model, 0.0, state, compute_contact=False
    )
    free_indices = np.concatenate(
        [branch.bead_indices for branch in model.branches.values()]
    )
    independent_residual = float(
        np.max(np.abs(equilibrium.particle_force[free_indices]))
    )
    independent_release_residual = float(
        np.max(np.abs(release.particle_force[free_indices]))
    )
    expected_fixture_force = {
        "support_A": -equilibrium.support_force["support_A"],
        "support_B": -equilibrium.support_force["support_B"],
        "junction": -equilibrium.particle_force[model.junction_index],
        "bob_com": -equilibrium.bob_force,
    }
    reported_fixture_force = audit["static_fixture_reaction_force_world_N"]
    fixture_force_error = float("inf")
    if (
        isinstance(reported_fixture_force, dict)
        and set(reported_fixture_force) == set(expected_fixture_force)
    ):
        fixture_force_error = max(
            float(
                np.max(
                    np.abs(
                        np.asarray(reported_fixture_force[name], dtype=float)
                        - expected
                    )
                )
            )
            for name, expected in expected_fixture_force.items()
        )
    reported_fixture_torque = audit["static_fixture_reaction_torque_world_Nm"]
    fixture_torque_error = float("inf")
    if (
        isinstance(reported_fixture_torque, dict)
        and set(reported_fixture_torque) == {"bob"}
    ):
        fixture_torque_error = float(
            np.max(
                np.abs(
                    np.asarray(reported_fixture_torque["bob"], dtype=float)
                    + equilibrium.bob_torque
                )
            )
        )
    actual_release_errors = {
        "free_material_force_N": abs(
            independent_release_residual
            - float(audit["actual_release_free_material_net_force_inf_N"])
        ),
        "junction_force_N": float(
            np.max(
                np.abs(
                    np.asarray(
                        audit["actual_release_junction_net_force_world_N"],
                        dtype=float,
                    )
                    - release.particle_force[model.junction_index]
                )
            )
        ),
        "bob_force_N": float(
            np.max(
                np.abs(
                    np.asarray(
                        audit["actual_release_bob_net_force_world_N"], dtype=float
                    )
                    - release.bob_force
                )
            )
        ),
        "bob_torque_Nm": float(
            np.max(
                np.abs(
                    np.asarray(
                        audit["actual_release_bob_net_torque_world_Nm"], dtype=float
                    )
                    - release.bob_torque
                )
            )
        ),
    }
    eps = np.finfo(float).eps
    force_tolerance = 65536.0 * eps * model.force_scale
    torque_tolerance = force_tolerance * model.characteristic_length
    requested_residual = float(
        to_si(bundle.config.solver.static.force_tolerance, default_unit="N")
    )
    residual_reporting_error = max(
        abs(independent_residual - preparation.residual_inf_N),
        abs(
            independent_residual
            - float(audit["static_free_material_residual_inf_N"])
        ),
    )
    hessian_value = float(audit["minimum_hessian_eigenvalue_N_per_m"])
    hessian_tolerance = float(audit["hessian_tolerance_N_per_m"])
    candidate_records = audit["candidate_records"]
    selected_seed = audit["selected_seed"]
    selected_candidates = (
        [
            item
            for item in candidate_records
            if isinstance(item, dict) and item.get("seed") == selected_seed
        ]
        if isinstance(candidate_records, list)
        else []
    )
    result_diagnostics = bundle.result.diagnostics
    checks = {
        "held_preparation_audit_schema": True,
        "held_flag_and_mode": (
            preparation.bob_held
            and preparation.preparation_mode
            in {
                "held_endpoint_bilateral_stable_equilibrium",
                "held_endpoint_stable_equilibrium_with_prescribed_release_velocity",
            }
        ),
        "held_protocol_exact": audit["protocol"]
        == "HELD_ENDPOINT_STABLE_BILATERAL_EQUILIBRIUM_V1",
        "fixed_dof_contract_exact": audit["fixed_dofs"]
        == [
            "junction_position",
            "bob_com_position",
            "bob_orientation",
            "bob_attachment_position",
            "support_A_position",
            "support_B_position",
        ],
        "independent_free_material_residual": (
            independent_residual <= requested_residual
        ),
        "residual_audit_consistent": residual_reporting_error <= force_tolerance,
        "fixture_force_reactions_consistent": fixture_force_error
        <= force_tolerance,
        "fixture_torque_reaction_consistent": fixture_torque_error
        <= torque_tolerance,
        "actual_release_force_torque_consistent": (
            actual_release_errors["free_material_force_N"] <= force_tolerance
            and actual_release_errors["junction_force_N"] <= force_tolerance
            and actual_release_errors["bob_force_N"] <= force_tolerance
            and actual_release_errors["bob_torque_Nm"] <= torque_tolerance
        ),
        "stability_class_psd": (
            np.isfinite(hessian_value)
            and np.isfinite(hessian_tolerance)
            and hessian_tolerance >= 0.0
            and hessian_value >= -hessian_tolerance
            and audit["stability_class"] == "PSD_STABLE_LOCAL_MINIMUM"
        ),
        "selected_stable_candidate_bound": (
            len(selected_candidates) == 1
            and selected_candidates[0].get("accepted_stable_candidate") is True
        ),
        "result_preparation_diagnostics_bound": (
            result_diagnostics.get("preparation_audit")
            == audit
            and float(
                result_diagnostics.get(
                    "preparation_force_residual_inf_N", np.nan
                )
            )
            == float(preparation.residual_inf_N)
            and result_diagnostics.get("preparation_iterations")
            == preparation.iterations
            and result_diagnostics.get("preparation_bob_held")
            == preparation.bob_held
            and result_diagnostics.get("preparation_mode")
            == preparation.preparation_mode
        ),
    }
    return {
        "applicability": "held_endpoint_equilibrium_release",
        "passed": all(checks.values()),
        "checks": checks,
        "independent_static_free_material_residual_inf_N": independent_residual,
        "requested_static_force_tolerance_N": requested_residual,
        "residual_reporting_error_N": residual_reporting_error,
        "fixture_force_max_abs_error_N": (
            fixture_force_error if np.isfinite(fixture_force_error) else None
        ),
        "fixture_torque_max_abs_error_Nm": (
            fixture_torque_error if np.isfinite(fixture_torque_error) else None
        ),
        "actual_release_errors": actual_release_errors,
        "stability_eigenvalue_source": (
            "preparation_audit_bound_to_selected_candidate; independent force/reaction "
            "reconstruction performed"
        ),
    }


def _preparation_view_from_result(
    result: HighFidelityResult,
) -> PreparationResult:
    """Build a read-only preparation view from the sealed result diagnostics."""

    diagnostics = result.diagnostics
    required = {
        "preparation_force_residual_inf_N",
        "preparation_iterations",
        "preparation_bob_held",
        "preparation_mode",
        "preparation_audit",
    }
    if not isinstance(diagnostics, dict) or not required.issubset(diagnostics):
        raise ValueError("HF result lacks its sealed preparation diagnostics.")
    if result.integration_time.size < 1:
        raise ValueError("HF result lacks an accepted initial state.")
    residual = _finite_real(
        diagnostics["preparation_force_residual_inf_N"],
        name="diagnostics.preparation_force_residual_inf_N",
        minimum=0.0,
        strict=False,
    )
    iterations = diagnostics["preparation_iterations"]
    bob_held = diagnostics["preparation_bob_held"]
    mode = diagnostics["preparation_mode"]
    audit = diagnostics["preparation_audit"]
    if (
        isinstance(iterations, bool)
        or not isinstance(iterations, Integral)
        or iterations < 0
        or not isinstance(bob_held, bool)
        or not isinstance(mode, str)
        or not isinstance(audit, dict)
    ):
        raise ValueError("HF result preparation diagnostics have invalid types.")
    state = pack_reference_state(
        result.integration_particle_positions[0],
        result.integration_bob_position[0],
        result.integration_bob_quaternion[0],
        result.integration_particle_velocities[0],
        result.integration_bob_velocity[0],
        result.integration_bob_angular_velocity[0],
    )
    return PreparationResult(
        state=state,
        residual_inf_N=residual,
        iterations=int(iterations),
        bob_held=bob_held,
        preparation_mode=mode,
        audit=audit,
    )


def _level_contract(
    bundle: _RunBundle,
    spec: dict[str, Any],
    *,
    apply_accuracy: bool,
) -> dict[str, Any]:
    result = bundle.result
    try:
        result_hash_before = canonical_hf_result_sha256(result)
    except ValueError as exc:
        return {
            "passed": False,
            "accuracy_role": (
                "finest_accuracy_required"
                if apply_accuracy
                else "coarse_finite_and_trend_only"
            ),
            "checks": {"canonical_result_identity_finite": False},
            "contract_evaluation_error": str(exc),
            "validation_physical_status": "UNDETERMINED",
            "validation_numerical_status": "EVENT_UNRESOLVED",
        }
    registered_result_hash = bundle.result_hash_start or result_hash_before
    expected_time = _expected_output_grid(bundle.config)
    shape_checks = _result_shape_checks(bundle)
    if not all(shape_checks.values()):
        return {
            "passed": False,
            "accuracy_role": (
                "finest_accuracy_required"
                if apply_accuracy
                else "coarse_finite_and_trend_only"
            ),
            "checks": shape_checks,
            "contract_evaluation_error": "canonical result schema/topology mismatch",
            "validation_physical_status": "UNDETERMINED",
            "validation_numerical_status": "EVENT_UNRESOLVED",
        }
    state = _state_matrix(bundle)
    initial_error = float(np.max(np.abs(state[0] - bundle.preparation.state)))
    integration_initial_error = float(
        np.max(
            np.abs(
                _integration_state_matrix(bundle)[0] - bundle.preparation.state
            )
        )
    )
    guard_minima = {
        name: float(np.min(values)) for name, values in result.guard_margins.items()
    }
    reported_dissipation_minimum = min(
        float(np.min(result.energy["axial_dissipation_rate"])),
        float(np.min(result.energy["aero_dissipation_rate"])),
    )
    try:
        accepted_cache = _accepted_step_reference_cache(bundle)
        dynamics = _dynamics_defect(bundle, accepted_cache)
        energy_balance = _independent_energy_balance(bundle)
        series_consistency = _canonical_series_consistency(bundle)
        preparation_certificate = _preparation_certificate(bundle)
        presentation_binding = _presentation_certificate_binding(
            bundle, accepted_cache
        )
        guard_metadata = _guard_component_metadata_contract(bundle.model)
        minimum_normalized_guard_margin = float(
            spec["minimum_normalized_guard_margin"]
        )
        continuous_guards = _continuous_guard_certificate(
            bundle, minimum_normalized_guard_margin, accepted_cache
        )
        result_hash_end = canonical_hf_result_sha256(result)
    except (FloatingPointError, ValueError) as exc:
        return {
            "passed": False,
            "accuracy_role": (
                "finest_accuracy_required"
                if apply_accuracy
                else "coarse_finite_and_trend_only"
            ),
            "checks": shape_checks,
            "contract_evaluation_error": (
                f"independent certificate unresolved: {type(exc).__name__}: {exc}"
            ),
            "validation_physical_status": "UNDETERMINED",
            "validation_numerical_status": "EVENT_UNRESOLVED",
        }
    quaternion_norm_error = float(
        np.max(np.abs(np.linalg.norm(result.bob_quaternion, axis=1) - 1.0))
    )
    machine_consistency = 4096.0 * np.finfo(float).eps
    provisional_solver_status = (
        result.physical_status == "UNDETERMINED"
        and result.numerical_status == "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"
    )
    allowed_negative_dissipation = min(
        float(spec["maximum_negative_dissipation_W"]),
        float(energy_balance["raw_passivity_roundoff_tolerance_W"]),
    )
    sampled_guard_certificates = {
        name: {
            "unit": guard_metadata[name]["unit"],
            "scale": float(guard_metadata[name]["scale"]),
            "raw_tolerance": float(guard_metadata[name]["tolerance"]),
            "raw_minimum": float(guard_minima[name]),
            "normalized_minimum": float(
                guard_minima[name] / float(guard_metadata[name]["scale"])
            ),
            "passed": bool(
                guard_minima[name]
                > max(
                    float(guard_metadata[name]["tolerance"]),
                    minimum_normalized_guard_margin
                    * float(guard_metadata[name]["scale"]),
                )
            ),
        }
        for name in guard_metadata
    }
    minimum_normalized_guard = min(
        float(item["normalized_minimum"])
        for item in sampled_guard_certificates.values()
    )
    structural_checks = {
        **shape_checks,
        **series_consistency["checks"],
        "source_stable": bundle.source_start == bundle.source_end,
        "resolved_config_stable": (
            bundle.config_hash_end is not None
            and bundle.config_hash == bundle.config_hash_end
        ),
        "model_config_bound_to_candidate": (
            _canonical_config_hash(bundle.model.cfg) == bundle.config_hash
        ),
        "runtime_stable": (
            bool(bundle.runtime_identity_start)
            and bundle.runtime_identity_start == bundle.runtime_identity_end
        ),
        "auxiliary_inputs_stable": (
            bundle.auxiliary_input_hash_start == bundle.auxiliary_input_hash_end
        ),
        "canonical_result_identity_finite": True,
        "canonical_result_stable": (
            registered_result_hash == result_hash_before == result_hash_end
        ),
        "solver_status_eligible_for_independent_guard_certification": (
            provisional_solver_status
        ),
        "solver_did_not_overclaim_uncertified_continuous_guards": (
            provisional_solver_status
        ),
        "valid_interval_exact": result.valid_interval
        == (0.0, float(to_si(bundle.config.solver.t_end, default_unit="s"))),
        "output_grid_exact": result.time.shape == expected_time.shape
        and bool(np.array_equal(result.time, expected_time)),
        "initial_state_exact": initial_error <= 32.0 * np.finfo(float).eps,
        "integration_initial_state_exact": integration_initial_error
        <= 32.0 * np.finfo(float).eps,
        "all_outputs_finite": _finite_nested(
            {
                "state": state,
                "integration_state": _integration_state_matrix(bundle),
                "tension": result.cable_tension,
                "signed_axial_force": _signed_axial_force_series(result),
                "energy": result.energy,
                "reaction": result.reactions,
                "guards": result.guard_margins,
            }
        ),
        "sampled_normalized_guard_margins": all(
            bool(item["passed"]) for item in sampled_guard_certificates.values()
        ),
        "accepted_step_continuous_guard_certificate": continuous_guards["passed"],
        "presentation_bound_to_accepted_steps": presentation_binding["passed"],
        "held_preparation_and_fixture_contract": preparation_certificate[
            "passed"
        ],
        "passive_dissipation": (
            energy_balance["raw_passivity_certified"]
            and reported_dissipation_minimum >= -allowed_negative_dissipation
        ),
        "accuracy_metrics_finite_nonnegative": all(
            np.isfinite(value) and value >= 0.0
            for value in (
                energy_balance["maximum_abs_residual"],
                dynamics["maximum_normalized_rate_defect"],
                dynamics["maximum_normalized_nonsmooth_increment_defect"],
                dynamics["maximum_normalized_signed_cumulative_defect"],
                dynamics["maximum_normalized_absolute_cumulative_defect"],
            )
        ),
        "quaternion_diagnostic_consistent": abs(
            quaternion_norm_error
            - float(result.diagnostics["maximum_quaternion_norm_error"])
        )
        <= machine_consistency,
        "quaternion_norm": quaternion_norm_error
        <= float(spec["maximum_quaternion_norm_error"]),
        "nonsmooth_time_coverage": dynamics["nonsmooth_time_fraction"]
        <= float(spec["maximum_nonsmooth_time_fraction"]),
        "nonsmooth_step_width": dynamics["maximum_nonsmooth_step_s"]
        <= float(spec["maximum_nonsmooth_step_s"]),
    }
    accuracy_checks = {
        "energy_balance": energy_balance["maximum_abs_residual"]
        <= float(spec["maximum_energy_balance_residual"]),
        "dynamics_rate": dynamics["maximum_normalized_rate_defect"]
        <= float(spec["maximum_normalized_rate_defect"]),
        "dynamics_nonsmooth_increment": dynamics[
            "maximum_normalized_nonsmooth_increment_defect"
        ]
        <= float(spec["maximum_normalized_nonsmooth_increment_defect"]),
        "dynamics_signed_cumulative": dynamics[
            "maximum_normalized_signed_cumulative_defect"
        ]
        <= float(spec["maximum_normalized_signed_cumulative_defect"]),
        "dynamics_absolute_cumulative": dynamics[
            "maximum_normalized_absolute_cumulative_defect"
        ]
        <= float(spec["maximum_normalized_absolute_cumulative_defect"]),
    }
    applied_accuracy_checks = accuracy_checks if apply_accuracy else {}
    checks = {**structural_checks, **applied_accuracy_checks}
    independently_guard_certified = all(structural_checks.values())
    controlled_limit_study = bool(
        getattr(bundle.config.high_fidelity, "controlled_limit_study", False)
    )
    fully_numerically_certified = (
        apply_accuracy and all(checks.values()) and not controlled_limit_study
    )
    controlled_limit_numerically_certified = (
        apply_accuracy and all(checks.values()) and controlled_limit_study
    )
    return {
        "passed": all(checks.values()),
        "accuracy_role": (
            "finest_accuracy_required"
            if apply_accuracy
            else "coarse_finite_and_trend_only"
        ),
        "checks": checks,
        "reported_accuracy_checks": accuracy_checks,
        "applied_accuracy_checks": applied_accuracy_checks,
        "candidate_identity": {
            "canonical_resolved_config_sha256_start": bundle.config_hash,
            "canonical_resolved_config_sha256_end": bundle.config_hash_end,
            "source_hash_start_sha256": bundle.source_start,
            "source_hash_end_sha256": bundle.source_end,
            "runtime_identity_start": bundle.runtime_identity_start,
            "runtime_identity_end": bundle.runtime_identity_end,
            "auxiliary_input_identity_start": bundle.auxiliary_input_hash_start,
            "auxiliary_input_identity_end": bundle.auxiliary_input_hash_end,
            "canonical_result_sha256_registered": registered_result_hash,
            "canonical_result_sha256_before": result_hash_before,
            "canonical_result_sha256_after": result_hash_end,
        },
        "initial_state_max_abs_error": initial_error,
        "integration_initial_state_max_abs_error": integration_initial_error,
        "guard_minima_raw": guard_minima,
        "sampled_guard_certificates": sampled_guard_certificates,
        "minimum_normalized_guard_margin": minimum_normalized_guard,
        "minimum_dissipation_rate_W": reported_dissipation_minimum,
        "minimum_independent_raw_dissipation_rate_W": energy_balance[
            "minimum_raw_dissipation_rate_W"
        ],
        "allowed_negative_dissipation_W": allowed_negative_dissipation,
        "dynamics_defect": dynamics,
        "energy_balance": energy_balance,
        "canonical_series_consistency": series_consistency,
        "preparation_certificate": preparation_certificate,
        "presentation_certificate_binding": presentation_binding,
        "continuous_guard_certificate": continuous_guards,
        "validation_physical_status": (
            "COMPLETED_INDEPENDENTLY_CERTIFIED"
            if fully_numerically_certified
            else (
                "OUT_OF_SCOPE"
                if controlled_limit_numerically_certified
                else (
                    "GUARD_DOMAIN_CERTIFIED"
                    if independently_guard_certified and not controlled_limit_study
                    else (
                        "OUT_OF_SCOPE"
                        if independently_guard_certified
                        else "UNDETERMINED"
                    )
                )
            )
        ),
        "validation_numerical_status": (
            "SUCCESS_SINGLE_RUN_GUARDS_CERTIFIED_BY_VALIDATION"
            if fully_numerically_certified
            else (
                "SUCCESS_CONTROLLED_LIMIT_CANDIDATE_CERTIFIED_BY_VALIDATION"
                if controlled_limit_numerically_certified
                else (
                    "GUARD_DOMAIN_CERTIFIED_ONLY_FULL_ACCURACY_NOT_APPLIED"
                    if independently_guard_certified
                    and not apply_accuracy
                    and not controlled_limit_study
                    else (
                        "GUARD_DOMAIN_CERTIFIED_ONLY_FULL_ACCURACY_FAILED"
                        if independently_guard_certified
                        and not controlled_limit_study
                        else (
                            "CONTROLLED_LIMIT_GUARD_DOMAIN_CERTIFIED_ONLY"
                            if independently_guard_certified
                            else "EVENT_UNRESOLVED"
                        )
                    )
                )
            )
        ),
        "solver_reported_physical_status": result.physical_status,
        "solver_reported_numerical_status": result.numerical_status,
        "energy_balance_residual": energy_balance["maximum_abs_residual"],
        "maximum_quaternion_norm_error": quaternion_norm_error,
    }


def certify_single_hf_bundle(
    config: SimulationConfig | str | Path | dict[str, Any],
    result: HighFidelityResult,
    model: HighFidelityModel | None = None,
    *,
    validation_spec: str | Path | dict[str, Any] | None = None,
    minimum_normalized_guard_margin: float | None = None,
) -> dict[str, Any]:
    """Independently certify one immutable HF result without modifying it.

    With no ``validation_spec`` this can issue only a
    ``GUARD_DOMAIN_CERTIFIED`` certificate.  The completed/certified status
    pair is available solely when the complete frozen validation specification
    is supplied and all structural *and* finest-run accuracy checks pass.
    """

    cfg = config if isinstance(config, SimulationConfig) else load_config(config)
    validate_physical_config(cfg)
    if cfg.run.mode != "high_fidelity":
        raise ValueError("Single-bundle HF certification requires high_fidelity mode.")
    package_root = Path(__file__).resolve().parents[1]
    source_start = source_hash(package_root)
    runtime_start = _runtime_identity()
    config_hash_start = _canonical_config_hash(cfg)
    auxiliary_start = _auxiliary_input_identity(cfg)
    raw_status_pair = {
        "physical_status": result.physical_status,
        "numerical_status": result.numerical_status,
    }

    spec_input_path = (
        Path(validation_spec).expanduser().resolve()
        if isinstance(validation_spec, (str, Path))
        else None
    )
    spec_file_hash_start = (
        _sha256_file(spec_input_path) if spec_input_path is not None else None
    )
    frozen_spec: dict[str, Any] | None
    certification_target: dict[str, Any] | None
    if validation_spec is None:
        frozen_spec = None
        certification_target = None
        required_normalized_margin = _finite_real(
            0.0
            if minimum_normalized_guard_margin is None
            else minimum_normalized_guard_margin,
            name="minimum_normalized_guard_margin",
            minimum=0.0,
            strict=False,
        )
        physics = {
            "minimum_normalized_guard_margin": required_normalized_margin,
            "maximum_negative_dissipation_W": float(np.finfo(float).max),
            "maximum_energy_balance_residual": float(np.finfo(float).max),
            "maximum_quaternion_norm_error": float(np.finfo(float).max),
            "maximum_normalized_rate_defect": float(np.finfo(float).max),
            "maximum_normalized_nonsmooth_increment_defect": float(
                np.finfo(float).max
            ),
            "maximum_normalized_signed_cumulative_defect": float(
                np.finfo(float).max
            ),
            "maximum_normalized_absolute_cumulative_defect": float(
                np.finfo(float).max
            ),
            "maximum_nonsmooth_time_fraction": 1.0,
            "maximum_nonsmooth_step_s": float(np.finfo(float).max),
        }
        validation_spec_hash = None
        apply_accuracy = False
    else:
        raw_spec = (
            load_unique_yaml(validation_spec)
            if isinstance(validation_spec, (str, Path))
            else validation_spec
        )
        frozen_spec = _freeze_and_validate_spec(raw_spec)
        certification_target = _validation_target_applicability(cfg, frozen_spec)
        physics = frozen_spec["physics_checks"]
        required_normalized_margin = float(
            physics["minimum_normalized_guard_margin"]
        )
        if (
            minimum_normalized_guard_margin is not None
            and float(minimum_normalized_guard_margin) != required_normalized_margin
        ):
            raise ValueError(
                "Explicit minimum_normalized_guard_margin must exactly match the "
                "frozen validation specification."
            )
        validation_spec_hash = hashlib.sha256(
            json.dumps(
                frozen_spec,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        apply_accuracy = True

    target_applicable_for_full = bool(
        frozen_spec is not None
        and certification_target is not None
        and certification_target["passed"]
    )
    target_failure_reason = (
        certification_target["failure_reason"]
        if certification_target is not None
        else "No frozen production certification target was supplied."
    )

    result_hash_error: str | None = None
    try:
        result_hash_start = canonical_hf_result_sha256(result)
    except ValueError as exc:
        result_hash_start = None
        result_hash_error = str(exc)

    active_model = HighFidelityModel(cfg) if model is None else model
    model_config_hash_start = _canonical_config_hash(active_model.cfg)
    level: dict[str, Any]
    if frozen_spec is not None and not target_applicable_for_full:
        level = {
            "passed": False,
            "checks": {"validation_target_applicable": False},
            "contract_evaluation_error": target_failure_reason,
            "validation_physical_status": "UNDETERMINED",
            "validation_numerical_status": "EVENT_UNRESOLVED",
        }
    elif result_hash_start is None:
        level = {
            "passed": False,
            "checks": {"canonical_result_identity_finite": False},
            "contract_evaluation_error": result_hash_error,
            "validation_physical_status": "UNDETERMINED",
            "validation_numerical_status": "EVENT_UNRESOLVED",
        }
    else:
        try:
            preparation = _preparation_view_from_result(result)
            bundle = _RunBundle(
                config=cfg,
                config_hash=config_hash_start,
                model=active_model,
                preparation=preparation,
                result=result,
                source_start=source_start,
                source_end=source_start,
                config_hash_end=config_hash_start,
                runtime_identity_start=runtime_start,
                runtime_identity_end=runtime_start,
                auxiliary_input_hash_start=auxiliary_start,
                auxiliary_input_hash_end=auxiliary_start,
                result_hash_start=result_hash_start,
            )
            level = _level_contract(bundle, physics, apply_accuracy=apply_accuracy)
        except (FloatingPointError, ValueError) as exc:
            level = {
                "passed": False,
                "checks": {"single_bundle_evaluation_completed": False},
                "contract_evaluation_error": (
                    f"{type(exc).__name__}: {exc}"
                ),
                "validation_physical_status": "UNDETERMINED",
                "validation_numerical_status": "EVENT_UNRESOLVED",
            }

    config_hash_end = _canonical_config_hash(cfg)
    model_config_hash_end = _canonical_config_hash(active_model.cfg)
    auxiliary_end = _auxiliary_input_identity(cfg)
    runtime_end = _runtime_identity()
    source_end = source_hash(package_root)
    spec_file_hash_end = (
        _sha256_file(spec_input_path) if spec_input_path is not None else None
    )
    try:
        result_hash_end = canonical_hf_result_sha256(result)
    except ValueError as exc:
        result_hash_end = None
        result_hash_error = str(exc)

    identity_checks = {
        "source_stable": source_start == source_end,
        "resolved_config_stable": config_hash_start == config_hash_end,
        "runtime_stable": runtime_start == runtime_end,
        "auxiliary_inputs_stable": auxiliary_start == auxiliary_end,
        "canonical_result_stable": (
            result_hash_start is not None
            and result_hash_start == result_hash_end
        ),
        "model_config_bound_to_requested_config": (
            model_config_hash_start
            == model_config_hash_end
            == config_hash_start
        ),
        "validation_spec_file_stable": spec_file_hash_start == spec_file_hash_end,
    }
    level_checks = {
        name: bool(value) for name, value in level.get("checks", {}).items()
    }
    level_checks["validation_target_applicable_for_full_certification"] = bool(
        target_applicable_for_full
    )
    level_checks.update(identity_checks)
    guard_domain_certified = (
        all(identity_checks.values())
        and level.get("validation_physical_status")
        in {"GUARD_DOMAIN_CERTIFIED", "COMPLETED_INDEPENDENTLY_CERTIFIED"}
    )
    fully_certified = (
        frozen_spec is not None
        and target_applicable_for_full
        and all(identity_checks.values())
        and bool(level.get("passed", False))
        and level.get("validation_physical_status")
        == "COMPLETED_INDEPENDENTLY_CERTIFIED"
        and level.get("validation_numerical_status")
        == "SUCCESS_SINGLE_RUN_GUARDS_CERTIFIED_BY_VALIDATION"
    )
    if fully_certified:
        certification_level = "FULL_NUMERICAL_AND_GUARD_DOMAIN_CERTIFIED"
        certified_status_pair = {
            "physical_status": "COMPLETED_INDEPENDENTLY_CERTIFIED",
            "numerical_status": (
                "SUCCESS_SINGLE_RUN_GUARDS_CERTIFIED_BY_VALIDATION"
            ),
        }
    elif guard_domain_certified:
        certification_level = "GUARD_DOMAIN_CERTIFIED"
        certified_status_pair = {
            "physical_status": "GUARD_DOMAIN_CERTIFIED",
            "numerical_status": "FULL_NUMERICAL_ACCURACY_NOT_CERTIFIED",
        }
    else:
        certification_level = "UNDETERMINED"
        certified_status_pair = {
            "physical_status": "UNDETERMINED",
            "numerical_status": "EVENT_UNRESOLVED",
        }

    certificate: dict[str, Any] = {
        "schema_version": "YPS-HF-SINGLE-BUNDLE-CERTIFICATE-1.0",
        "model_id": result.model_id,
        "passed": fully_certified,
        "guard_domain_certified": guard_domain_certified,
        "certification_level": certification_level,
        "raw_result_status_pair": raw_status_pair,
        "certified_status_pair": certified_status_pair,
        "full_accuracy_spec_bound": bool(
            target_applicable_for_full
        ),
        "minimum_normalized_guard_margin": required_normalized_margin,
        "validation_spec_sha256": validation_spec_hash,
        "certification_target": certification_target,
        "identity": {
            "canonical_resolved_config_sha256_start": config_hash_start,
            "canonical_resolved_config_sha256_end": config_hash_end,
            "canonical_model_config_sha256_start": model_config_hash_start,
            "canonical_model_config_sha256_end": model_config_hash_end,
            "canonical_result_sha256_start": result_hash_start,
            "canonical_result_sha256_end": result_hash_end,
            "canonical_result_hash_error": result_hash_error,
            "source_hash_start_sha256": source_start,
            "source_hash_end_sha256": source_end,
            "runtime_identity_start": runtime_start,
            "runtime_identity_end": runtime_end,
            "auxiliary_input_identity_start": auxiliary_start,
            "auxiliary_input_identity_end": auxiliary_end,
            "validation_spec_file_sha256_start": spec_file_hash_start,
            "validation_spec_file_sha256_end": spec_file_hash_end,
        },
        "identity_checks": identity_checks,
        "checks": level_checks,
        "presentation_certificate_binding": level.get(
            "presentation_certificate_binding"
        ),
        "canonical_series_consistency": level.get(
            "canonical_series_consistency"
        ),
        "preparation_certificate": level.get("preparation_certificate"),
        "energy_balance": level.get("energy_balance"),
        "dynamics_defect": level.get("dynamics_defect"),
        "continuous_guard_certificate": level.get(
            "continuous_guard_certificate"
        ),
        "contract_evaluation_error": level.get("contract_evaluation_error"),
    }
    certificate_digest = hashlib.sha256()
    _update_canonical_digest(certificate_digest, certificate)
    certificate["certificate_sha256"] = certificate_digest.hexdigest()
    return certificate


def verify_single_hf_certificate_digest(certificate: Any) -> bool:
    """Fail closed unless a strict single-bundle certificate digest matches."""

    if (
        not isinstance(certificate, dict)
        or set(certificate) != _SINGLE_BUNDLE_CERTIFICATE_FIELDS
        or certificate.get("schema_version")
        != "YPS-HF-SINGLE-BUNDLE-CERTIFICATE-1.0"
    ):
        return False
    claimed = certificate.get("certificate_sha256")
    if (
        not isinstance(claimed, str)
        or len(claimed) != 64
        or any(character not in "0123456789abcdef" for character in claimed)
    ):
        return False
    payload = dict(certificate)
    payload.pop("certificate_sha256")
    try:
        digest = hashlib.sha256()
        _update_canonical_digest(digest, payload)
    except (OverflowError, TypeError, ValueError):
        return False
    return digest.hexdigest() == claimed


def _interpolate_material_path(
    values: np.ndarray, rest_length: np.ndarray, common_s: np.ndarray
) -> np.ndarray:
    """Interpolate nodal rod fields at their actual rest-material coordinates."""

    source_s = np.concatenate([[0.0], np.cumsum(rest_length)])
    source_s /= source_s[-1]
    if source_s.size != values.shape[1]:
        raise ValueError("Material path topology does not match segment rest lengths.")
    output = np.empty((values.shape[0], common_s.size, values.shape[2]))
    for time_index in range(values.shape[0]):
        for component in range(values.shape[2]):
            output[time_index, :, component] = np.interp(
                common_s, source_s, values[time_index, :, component]
            )
    return output


def _interpolate_tension(
    values: np.ndarray,
    rest_length: np.ndarray,
    common_s: np.ndarray,
) -> np.ndarray:
    """Sample the piecewise-constant segment field without artificial smoothing."""

    edge = np.concatenate([[0.0], np.cumsum(rest_length)])
    edge /= edge[-1]
    # At an interface choose the right material trace; s=1 belongs to the last cell.
    cell = np.searchsorted(edge, common_s, side="right") - 1
    cell = np.clip(cell, 0, values.shape[1] - 1)
    return np.asarray(values)[:, cell]


def _rms_and_max(prefix: str, difference: np.ndarray) -> dict[str, float]:
    return {
        f"rms_{prefix}": float(np.sqrt(np.mean(np.asarray(difference) ** 2))),
        f"max_{prefix}": float(np.max(np.abs(difference))),
    }


def _compare(left: _RunBundle, right: _RunBundle, material_points: int) -> dict[str, float]:
    a = left.result
    b = right.result
    if not np.array_equal(a.time, b.time):
        raise ValueError("HF validation levels must share the frozen output grid.")
    metrics: dict[str, float] = {}
    metrics.update(_rms_and_max("bob_position_m", a.bob_position - b.bob_position))
    metrics.update(_rms_and_max("bob_velocity_m_s", a.bob_velocity - b.bob_velocity))
    metrics.update(
        _rms_and_max("junction_position_m", a.junction_position - b.junction_position)
    )
    metrics.update(
        _rms_and_max("junction_velocity_m_s", a.junction_velocity - b.junction_velocity)
    )
    metrics.update(
        _rms_and_max(
            "bob_attachment_position_m",
            a.bob_attachment_position - b.bob_attachment_position,
        )
    )
    dot = np.abs(np.sum(a.bob_quaternion * b.bob_quaternion, axis=1))
    orientation_angle = 2.0 * np.arccos(np.clip(dot, 0.0, 1.0))
    metrics.update(_rms_and_max("bob_orientation_angle_rad", orientation_angle))
    metrics.update(
        _rms_and_max(
            "bob_angular_velocity_rad_s",
            a.bob_angular_velocity - b.bob_angular_velocity,
        )
    )
    common_s = np.linspace(0.0, 1.0, material_points)
    position_differences = []
    velocity_differences = []
    tension_differences = []
    signed_axial_force_differences = []
    left_signed_series = _signed_axial_force_series(a)
    right_signed_series = _signed_axial_force_series(b)
    if left_signed_series is None or right_signed_series is None:
        raise ValueError("HF comparison requires signed axial-force series.")
    for name in ("upper_A", "upper_B", "lower"):
        left_branch = left.model.branches[name]
        right_branch = right.model.branches[name]
        left_position = _interpolate_material_path(
            a.cable_positions[name], left_branch.segment_rest_length, common_s
        )
        right_position = _interpolate_material_path(
            b.cable_positions[name], right_branch.segment_rest_length, common_s
        )
        left_velocity = _interpolate_material_path(
            a.cable_velocities[name], left_branch.segment_rest_length, common_s
        )
        right_velocity = _interpolate_material_path(
            b.cable_velocities[name], right_branch.segment_rest_length, common_s
        )
        left_tension = _interpolate_tension(
            a.cable_tension[name], left_branch.segment_rest_length, common_s
        )
        right_tension = _interpolate_tension(
            b.cable_tension[name], right_branch.segment_rest_length, common_s
        )
        left_signed_axial_force = _interpolate_tension(
            left_signed_series[name], left_branch.segment_rest_length, common_s
        )
        right_signed_axial_force = _interpolate_tension(
            right_signed_series[name], right_branch.segment_rest_length, common_s
        )
        position_differences.append(left_position - right_position)
        velocity_differences.append(left_velocity - right_velocity)
        tension_differences.append(left_tension - right_tension)
        signed_axial_force_differences.append(
            left_signed_axial_force - right_signed_axial_force
        )
    metrics.update(
        _rms_and_max("rod_position_m", np.concatenate(position_differences, axis=1))
    )
    metrics.update(
        _rms_and_max("rod_velocity_m_s", np.concatenate(velocity_differences, axis=1))
    )
    metrics.update(
        _rms_and_max("rod_tension_N", np.concatenate(tension_differences, axis=1))
    )
    metrics.update(
        _rms_and_max(
            "rod_signed_axial_force_N",
            np.concatenate(signed_axial_force_differences, axis=1),
        )
    )
    metrics.update(
        _rms_and_max(
            "mechanical_energy_J", a.energy["mechanical"] - b.energy["mechanical"]
        )
    )
    metrics.update(
        _rms_and_max(
            "support_reaction_N",
            np.concatenate(
                [
                    a.reactions["support_A"] - b.reactions["support_A"],
                    a.reactions["support_B"] - b.reactions["support_B"],
                ],
                axis=1,
            ),
        )
    )
    return metrics


def _expected_axial_event_fingerprints(
    bundle: _RunBundle,
) -> Counter[tuple[Any, ...]] | None:
    """Independently derive the sampled axial event ledger from canonical series."""

    result = bundle.result
    if not hasattr(result, "time") or not hasattr(result, "cable_tension"):
        return None
    time = np.asarray(result.time, dtype=float)
    tolerance = float(bundle.model.tension_zero_tolerance)
    alpha = float(bundle.model.compression_regularization_scale)
    fingerprints: Counter[tuple[Any, ...]] = Counter()
    if alpha > 0.0:
        signed_series = _signed_axial_force_series(result)
        if signed_series is None:
            return None
        for branch_name, raw_signed in signed_series.items():
            signed = np.asarray(raw_signed, dtype=float)
            regime = np.full(signed.shape, "PURE_ZERO", dtype=object)
            regime[signed > tolerance] = "TENSION"
            regime[signed < -tolerance] = "COMPRESSION"
            for segment in range(signed.shape[1]):
                initial = str(regime[0, segment])
                if initial != "TENSION":
                    fingerprints[
                        (
                            "HF_SEGMENT_INITIAL_AXIAL_REGIME",
                            branch_name,
                            segment,
                            float(time[0]),
                            float(time[0]),
                            initial,
                        )
                    ] += 1
                changes = np.flatnonzero(
                    regime[1:, segment] != regime[:-1, segment]
                ) + 1
                for sample in changes:
                    fingerprints[
                        (
                            "HF_SEGMENT_AXIAL_REGIME_CHANGE_SAMPLED_BRACKET",
                            branch_name,
                            segment,
                            float(time[sample - 1]),
                            float(time[sample]),
                            f"{regime[sample - 1, segment]}->{regime[sample, segment]}",
                        )
                    ] += 1
        return fingerprints

    for branch_name, raw_tension in result.cable_tension.items():
        tension = np.asarray(raw_tension, dtype=float)
        active = tension > tolerance
        for segment in range(active.shape[1]):
            if not active[0, segment]:
                fingerprints[
                    (
                        "HF_SEGMENT_INITIALLY_SLACK",
                        branch_name,
                        segment,
                        float(time[0]),
                        float(time[0]),
                        None,
                    )
                ] += 1
            changes = np.flatnonzero(
                active[1:, segment] != active[:-1, segment]
            ) + 1
            for sample in changes:
                fingerprints[
                    (
                        (
                            "HF_SEGMENT_RETENSION_SAMPLED_BRACKET"
                            if active[sample, segment]
                            else "HF_SEGMENT_SLACKENING_SAMPLED_BRACKET"
                        ),
                        branch_name,
                        segment,
                        float(time[sample - 1]),
                        float(time[sample]),
                        None,
                    )
                ] += 1
        fully_active = np.all(active, axis=1)
        fully_slack = ~np.any(active, axis=1)
        for mask, inactive_type, active_type in (
            (
                fully_active,
                "HF_BRANCH_NOT_FULLY_TAUT",
                "HF_BRANCH_FULLY_RETENSIONED",
            ),
            (
                fully_slack,
                "HF_BRANCH_LEFT_FULL_SLACK",
                "HF_BRANCH_FULLY_SLACK",
            ),
        ):
            changes = np.flatnonzero(mask[1:] != mask[:-1]) + 1
            for sample in changes:
                fingerprints[
                    (
                        active_type if mask[sample] else inactive_type,
                        branch_name,
                        None,
                        float(time[sample - 1]),
                        float(time[sample]),
                        None,
                    )
                ] += 1
    return fingerprints


def _raw_axial_event_fingerprint(
    event: dict[str, Any], *, bilateral_weight: float
) -> tuple[Any, ...] | None:
    event_type = event.get("type")
    bilateral_types = {
        "HF_SEGMENT_INITIAL_AXIAL_REGIME",
        "HF_SEGMENT_AXIAL_REGIME_CHANGE_SAMPLED_BRACKET",
    }
    unilateral_types = {
        "HF_SEGMENT_INITIALLY_SLACK",
        "HF_SEGMENT_RETENSION_SAMPLED_BRACKET",
        "HF_SEGMENT_SLACKENING_SAMPLED_BRACKET",
        "HF_BRANCH_NOT_FULLY_TAUT",
        "HF_BRANCH_FULLY_RETENSIONED",
        "HF_BRANCH_LEFT_FULL_SLACK",
        "HF_BRANCH_FULLY_SLACK",
    }
    if event_type not in bilateral_types | unilateral_types:
        return None
    branch = event.get("branch")
    if not isinstance(branch, str):
        return ("INVALID_AXIAL_EVENT",)
    raw_segment = event.get("material_segment")
    if event_type.startswith("HF_SEGMENT_"):
        if isinstance(raw_segment, bool) or not isinstance(raw_segment, Integral):
            return ("INVALID_AXIAL_EVENT",)
        segment: int | None = int(raw_segment)
    else:
        segment = None
    try:
        time = float(event.get("time", 0.0))
        start = float(event.get("bracket_start_s", time))
        end = float(event.get("bracket_end_s", time))
    except (OverflowError, TypeError, ValueError):
        return ("INVALID_AXIAL_EVENT",)
    regime_identity: str | None = None
    if event_type == "HF_SEGMENT_INITIAL_AXIAL_REGIME":
        raw = event.get("axial_regime")
        regime_identity = "PURE_ZERO" if raw == "NEUTRAL" else raw
    elif event_type == "HF_SEGMENT_AXIAL_REGIME_CHANGE_SAMPLED_BRACKET":
        before = event.get("axial_regime_before")
        after = event.get("axial_regime_after")
        before = "PURE_ZERO" if before == "NEUTRAL" else before
        after = "PURE_ZERO" if after == "NEUTRAL" else after
        regime_identity = f"{before}->{after}"
    if bilateral_weight > 0.0 and event_type in unilateral_types:
        return ("INVALID_AXIAL_EVENT",)
    if bilateral_weight <= 0.0 and event_type in bilateral_types:
        return ("INVALID_AXIAL_EVENT",)
    return (event_type, branch, segment, start, end, regime_identity)


def _canonical_event_records(bundle: _RunBundle) -> list[dict[str, Any]]:
    """Map every registered event to mesh-independent material/time brackets."""

    raw_records: list[dict[str, Any]] = []
    bilateral_weight = float(bundle.model.compression_regularization_scale)
    expected_axial_events = _expected_axial_event_fingerprints(bundle)
    reported_axial_events: Counter[tuple[Any, ...]] = Counter()

    def axial_regime(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        if value in {"NEUTRAL", "PURE_ZERO"}:
            return "PURE_ZERO"
        if value in {"TENSION", "COMPRESSION"}:
            return str(value)
        return None

    for event_index, event in enumerate(bundle.result.events):
        if not isinstance(event, dict):
            raw_records.append(
                {
                    "type": "INVALID_EVENT_RECORD",
                    "branch": None,
                    "guard_component": None,
                    "time_bracket_s": [0.0, 0.0],
                    "material_coordinate_bracket": None,
                    "material_reference_declared": False,
                    "axial_regime_identity": None,
                    "semantic_errors": ["event record is not a mapping"],
                    "source_event_index": event_index,
                }
            )
            continue
        axial_fingerprint = _raw_axial_event_fingerprint(
            event, bilateral_weight=bilateral_weight
        )
        if axial_fingerprint is not None:
            reported_axial_events[axial_fingerprint] += 1
        event_type = event.get("type")
        if not isinstance(event_type, str):
            raw_records.append(
                {
                    "type": "INVALID_EVENT_WITHOUT_TYPE",
                    "branch": None,
                    "guard_component": None,
                    "time_bracket_s": [0.0, 0.0],
                    "material_coordinate_bracket": None,
                    "material_reference_declared": False,
                    "axial_regime_identity": None,
                    "semantic_errors": ["event type is absent or invalid"],
                    "source_event_index": event_index,
                }
            )
            continue
        semantic_errors: list[str] = []
        try:
            time_value = float(event.get("time", 0.0))
            time_bracket = [
                float(event.get("bracket_start_s", time_value)),
                float(event.get("bracket_end_s", time_value)),
            ]
        except (OverflowError, TypeError, ValueError):
            time_value = 0.0
            time_bracket = [0.0, 0.0]
            semantic_errors.append("event time or time bracket is invalid")
        branch_name = event.get("branch")
        material_bracket: list[float] | None = None
        material_reference_declared = any(
            name in event
            for name in (
                "material_coordinate_bracket",
                "material_coordinate",
                "material_segment",
            )
        )
        try:
            if "material_coordinate_bracket" in event:
                candidate = event["material_coordinate_bracket"]
                if isinstance(candidate, (list, tuple)) and len(candidate) == 2:
                    material_bracket = [float(candidate[0]), float(candidate[1])]
            elif "material_coordinate" in event:
                coordinate = float(event["material_coordinate"])
                material_bracket = [coordinate, coordinate]
            elif (
                "material_segment" in event
                and branch_name in bundle.model.branches
            ):
                branch = bundle.model.branches[str(branch_name)]
                raw_segment = event["material_segment"]
                if isinstance(raw_segment, bool):
                    raise ValueError
                segment = int(raw_segment)
                edge = np.concatenate(
                    [[0.0], np.cumsum(branch.segment_rest_length)]
                )
                edge /= edge[-1]
                if 0 <= segment < edge.size - 1:
                    material_bracket = [
                        float(edge[segment]),
                        float(edge[segment + 1]),
                    ]
        except (OverflowError, TypeError, ValueError):
            semantic_errors.append("event material reference is invalid")

        guard_components: list[str | None]
        reasons = event.get("reasons")
        if isinstance(reasons, list) and reasons:
            guard_components = sorted(str(reason) for reason in reasons)
        elif isinstance(event.get("guard_component"), str):
            guard_components = [str(event["guard_component"])]
        elif isinstance(event.get("guard_components"), dict):
            guard_components = sorted(str(name) for name in event["guard_components"])
        else:
            guard_components = [None]
        regime_identity: str | None = None
        if event_type == "HF_SEGMENT_INITIAL_AXIAL_REGIME":
            regime_identity = axial_regime(event.get("axial_regime"))
            if bilateral_weight <= 0.0:
                semantic_errors.append(
                    "signed axial-regime events are invalid at the exact unilateral endpoint"
                )
            if regime_identity is None:
                semantic_errors.append("invalid initial signed axial regime")
        elif event_type == "HF_SEGMENT_AXIAL_REGIME_CHANGE_SAMPLED_BRACKET":
            before = axial_regime(event.get("axial_regime_before"))
            after = axial_regime(event.get("axial_regime_after"))
            regime_identity = (
                f"{before}->{after}"
                if before is not None and after is not None
                else None
            )
            if bilateral_weight <= 0.0:
                semantic_errors.append(
                    "signed axial-regime events are invalid at the exact unilateral endpoint"
                )
            if regime_identity is None or before == after:
                semantic_errors.append("invalid signed axial-regime transition")
        elif bilateral_weight > 0.0 and any(
            token in event_type for token in ("SLACK", "TAUT", "RETENSION")
        ):
            semantic_errors.append(
                "bilateral compression must use TENSION/PURE_ZERO/COMPRESSION, not slack/taut semantics"
            )
        if event_type.startswith("HF_SEGMENT_") and material_bracket is None:
            semantic_errors.append("segment event lacks a valid material reference")
        for guard_component in guard_components:
            raw_records.append(
                {
                    "type": event_type,
                    "branch": branch_name if isinstance(branch_name, str) else None,
                    "guard_component": guard_component,
                    "time_bracket_s": time_bracket,
                    "material_coordinate_bracket": material_bracket,
                    "material_reference_declared": material_reference_declared,
                    "axial_regime_identity": regime_identity,
                    "semantic_errors": semantic_errors.copy(),
                    "source_event_index": event_index,
                }
            )

    if (
        expected_axial_events is not None
        and reported_axial_events != expected_axial_events
    ):
        raw_records.append(
            {
                "type": "INVALID_AXIAL_EVENT_LEDGER",
                "branch": None,
                "guard_component": None,
                "time_bracket_s": [0.0, 0.0],
                "material_coordinate_bracket": None,
                "material_reference_declared": False,
                "axial_regime_identity": None,
                "semantic_errors": [
                    "reported axial events do not equal the independently derived "
                    f"sampled ledger (reported={sum(reported_axial_events.values())}, "
                    f"expected={sum(expected_axial_events.values())})"
                ],
                "source_event_index": -1,
            }
        )

    for record in raw_records:
        errors: list[str] = list(record.pop("semantic_errors", []))
        start_time, end_time = record["time_bracket_s"]
        if not np.isfinite(start_time) or not np.isfinite(end_time):
            errors.append("non-finite time bracket")
        elif start_time > end_time:
            errors.append("reversed time bracket")
        material = record["material_coordinate_bracket"]
        if record["material_reference_declared"] and material is None:
            errors.append("invalid declared material reference")
        elif material is not None:
            start_material, end_material = material
            if not np.isfinite(start_material) or not np.isfinite(end_material):
                errors.append("non-finite material bracket")
            elif not 0.0 <= start_material <= end_material <= 1.0:
                errors.append("material bracket outside [0,1] or reversed")
        record["valid"] = not errors
        record["validation_errors"] = errors

    # Segment events at one sampled time can number differently on N/2N/4N.
    # Merge adjacent material cells into physical material-coordinate regions.
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    ungrouped: list[dict[str, Any]] = []
    for record in raw_records:
        if record["material_coordinate_bracket"] is None:
            ungrouped.append(record)
            continue
        key = (
            record["type"],
            record["branch"],
            record["guard_component"],
            record["axial_regime_identity"],
            *record["time_bracket_s"],
        )
        grouped.setdefault(key, []).append(record)
    merged: list[dict[str, Any]] = []
    material_tolerance = 64.0 * np.finfo(float).eps
    for records in grouped.values():
        records.sort(key=lambda item: item["material_coordinate_bracket"][0])
        current = dict(records[0])
        current["source_event_indices"] = [current.pop("source_event_index")]
        for record in records[1:]:
            left, right = record["material_coordinate_bracket"]
            if left <= current["material_coordinate_bracket"][1] + material_tolerance:
                current["material_coordinate_bracket"][1] = max(
                    current["material_coordinate_bracket"][1], right
                )
                current["source_event_indices"].append(record["source_event_index"])
            else:
                merged.append(current)
                current = dict(record)
                current["source_event_indices"] = [current.pop("source_event_index")]
        merged.append(current)
    canonical = ungrouped + merged
    canonical.sort(
        key=lambda item: (
            item["type"],
            item["branch"] or "",
            item["guard_component"] or "",
            item["axial_regime_identity"] or "",
            sum(item["time_bracket_s"]),
            (
                -1.0
                if item["material_coordinate_bracket"] is None
                else sum(item["material_coordinate_bracket"])
            ),
        )
    )
    return canonical


def _event_stability(levels: list[_RunBundle], tolerance: float) -> dict[str, Any]:
    summaries = [_canonical_event_records(level) for level in levels]
    grouped_summaries: list[
        dict[tuple[str, str | None, str | None, str | None], list[dict[str, Any]]]
    ] = []
    for summary in summaries:
        grouped: dict[
            tuple[str, str | None, str | None, str | None], list[dict[str, Any]]
        ] = {}
        for record in summary:
            if not record["valid"]:
                continue
            key = (
                record["type"],
                record["branch"],
                record["guard_component"],
                record["axial_regime_identity"],
            )
            grouped.setdefault(key, []).append(record)
        grouped_summaries.append(grouped)
    keys = sorted(
        set().union(*(set(grouped) for grouped in grouped_summaries)),
        key=lambda value: tuple(item or "" for item in value),
    )
    invalid_records = [
        [record for record in summary if not record["valid"]]
        for summary in summaries
    ]
    comparisons: dict[str, Any] = {}
    passed = not any(invalid_records)
    if any(invalid_records):
        comparisons["INVALID_EVENT_RECORDS"] = {
            "passed": False,
            "invalid_records_by_level": invalid_records,
            "reason": "non-finite, reversed or non-material event identity",
        }
    for key in keys:
        records_by_level = [grouped.get(key, []) for grouped in grouped_summaries]
        counts = [len(records) for records in records_by_level]
        key_name = ":".join(item or "-" for item in key)
        if len(set(counts)) != 1:
            comparisons[key_name] = {
                "passed": False,
                "event_counts": counts,
                "reason": "event multiplicity changed across refinement levels",
            }
            passed = False
            continue
        instances: list[dict[str, Any]] = []
        for ordinal in range(counts[0]):
            records = [level_records[ordinal] for level_records in records_by_level]
            time_start = [record["time_bracket_s"][0] for record in records]
            time_end = [record["time_bracket_s"][1] for record in records]
            separated_time = max(0.0, max(time_start) - min(time_end))
            time_passed = separated_time <= tolerance
            material = [record["material_coordinate_bracket"] for record in records]
            if all(item is None for item in material):
                material_passed = True
                material_separation = None
            elif any(item is None for item in material):
                material_passed = False
                material_separation = None
            else:
                material_start = [item[0] for item in material]  # type: ignore[index]
                material_end = [item[1] for item in material]  # type: ignore[index]
                material_separation = max(
                    0.0, max(material_start) - min(material_end)
                )
                material_passed = material_separation <= 64.0 * np.finfo(float).eps
            instance_passed = time_passed and material_passed
            passed &= instance_passed
            instances.append(
                {
                    "ordinal": ordinal,
                    "passed": instance_passed,
                    "minimum_separation_between_time_brackets_s": separated_time,
                    "maximum_allowed_separation_s": tolerance,
                    "minimum_separation_between_material_brackets": material_separation,
                    "records": records,
                }
            )
        comparisons[key_name] = {
            "passed": all(instance["passed"] for instance in instances),
            "event_counts": counts,
            "instances": instances,
        }
    return {
        "passed": passed,
        "coverage": "all registered validity, segment, branch, bending and contact events",
        "identity_basis": (
            "event type + branch + guard + signed axial regime + "
            "material-coordinate/time brackets"
        ),
        "comparisons": comparisons,
        "summaries": summaries,
    }


def _cauchy_gate(
    comparisons: list[dict[str, float]],
    thresholds: dict[str, float],
    *,
    ratio_slack: float,
    numerical_floor_fraction: float,
) -> dict[str, Any]:
    coarse_to_middle, middle_to_fine = comparisons
    checks: dict[str, Any] = {}
    for metric, threshold in thresholds.items():
        coarse = float(coarse_to_middle[metric])
        fine = float(middle_to_fine[metric])
        metric_floor = float(threshold) * numerical_floor_fraction
        checks[metric] = {
            "coarse_to_middle": coarse,
            "middle_to_fine": fine,
            "threshold": float(threshold),
            "metric_numerical_floor": metric_floor,
            "finest_threshold_passed": fine <= float(threshold),
            "required_contraction_ratio": ratio_slack,
            "decreasing_or_at_floor": fine <= coarse / ratio_slack
            or fine <= metric_floor,
        }
    return {
        "passed": all(
            item["finest_threshold_passed"] and item["decreasing_or_at_floor"]
            for item in checks.values()
        ),
        "metrics": checks,
    }


def _accuracy_trend_gate(
    contracts: list[dict[str, Any]],
    physics_thresholds: dict[str, float],
    *,
    ratio_slack: float,
    numerical_floor_fraction: float,
) -> dict[str, Any]:
    """Require time-refinement improvement for each independent accuracy metric."""

    if len(contracts) != 3 or any(
        "energy_balance_residual" not in contract
        or "dynamics_defect" not in contract
        for contract in contracts
    ):
        return {
            "applicability": "time_refinement_only",
            "passed": False,
            "metrics": {},
            "reason": "one or more independent level certificates are unresolved",
        }

    threshold_for_field = {
        "energy_balance_residual": "maximum_energy_balance_residual",
        "maximum_normalized_rate_defect": "maximum_normalized_rate_defect",
        "maximum_normalized_nonsmooth_increment_defect": (
            "maximum_normalized_nonsmooth_increment_defect"
        ),
        "maximum_normalized_signed_cumulative_defect": (
            "maximum_normalized_signed_cumulative_defect"
        ),
        "maximum_normalized_absolute_cumulative_defect": (
            "maximum_normalized_absolute_cumulative_defect"
        ),
    }
    values_by_field = {
        "energy_balance_residual": [
            float(contract["energy_balance_residual"]) for contract in contracts
        ],
        "maximum_normalized_rate_defect": [
            float(contract["dynamics_defect"]["maximum_normalized_rate_defect"])
            for contract in contracts
        ],
        "maximum_normalized_nonsmooth_increment_defect": [
            float(
                contract["dynamics_defect"][
                    "maximum_normalized_nonsmooth_increment_defect"
                ]
            )
            for contract in contracts
        ],
        "maximum_normalized_signed_cumulative_defect": [
            float(
                contract["dynamics_defect"][
                    "maximum_normalized_signed_cumulative_defect"
                ]
            )
            for contract in contracts
        ],
        "maximum_normalized_absolute_cumulative_defect": [
            float(
                contract["dynamics_defect"][
                    "maximum_normalized_absolute_cumulative_defect"
                ]
            )
            for contract in contracts
        ],
    }
    checks: dict[str, Any] = {}
    for metric_field in _ACCURACY_FIELDS:
        values = values_by_field[metric_field]
        threshold = float(physics_thresholds[threshold_for_field[metric_field]])
        floor = threshold * numerical_floor_fraction
        step_checks = [
            values[index + 1] <= values[index] / ratio_slack
            or values[index + 1] <= floor
            for index in range(2)
        ]
        checks[metric_field] = {
            "values_coarse_middle_fine": values,
            "finest_threshold": threshold,
            "metric_numerical_floor": floor,
            "coarse_to_middle_decreasing_or_at_floor": step_checks[0],
            "middle_to_fine_decreasing_or_at_floor": step_checks[1],
            "passed": all(step_checks) and values[-1] <= threshold,
        }
    return {
        "applicability": "time_refinement_only",
        "passed": all(item["passed"] for item in checks.values()),
        "metrics": checks,
    }


def _run_bundle(
    cfg: SimulationConfig,
    cache: dict[str, _RunBundle],
    package_root: Path,
) -> _RunBundle:
    validate_physical_config(cfg)
    config_hash = _canonical_config_hash(cfg)
    if config_hash in cache:
        return cache[config_hash]
    source_start = source_hash(package_root)
    runtime_identity_start = _runtime_identity()
    auxiliary_input_hash_start = _auxiliary_input_identity(cfg)
    model = HighFidelityModel(cfg)
    preparation = prepare_initial_state(cfg, model)
    result = simulate_high_fidelity(cfg, model=model, preparation=preparation)
    result_hash_start = canonical_hf_result_sha256(result)
    config_hash_end = _canonical_config_hash(cfg)
    auxiliary_input_hash_end = _auxiliary_input_identity(cfg)
    runtime_identity_end = _runtime_identity()
    source_end = source_hash(package_root)
    bundle = _RunBundle(
        config=cfg,
        config_hash=config_hash,
        model=model,
        preparation=preparation,
        result=result,
        source_start=source_start,
        source_end=source_end,
        config_hash_end=config_hash_end,
        runtime_identity_start=runtime_identity_start,
        runtime_identity_end=runtime_identity_end,
        auxiliary_input_hash_start=auxiliary_input_hash_start,
        auxiliary_input_hash_end=auxiliary_input_hash_end,
        result_hash_start=result_hash_start,
    )
    cache[config_hash] = bundle
    return bundle


def _write_candidate_artifacts(
    directory: Path,
    cache: dict[str, _RunBundle],
) -> dict[str, Any]:
    """Persist every unique qualification trajectory with a local manifest."""

    if directory.exists():
        raise FileExistsError(f"HF candidate artifact directory already exists: {directory}")
    from ypendulum.io.hdf5 import write_hf_result

    directory.mkdir(parents=True)
    records: dict[str, Any] = {}
    for config_hash, bundle in sorted(cache.items()):
        result_hash_at_write = canonical_hf_result_sha256(bundle.result)
        registered_result_hash = bundle.result_hash_start or result_hash_at_write
        candidate = directory / f"candidate_{config_hash[:16]}"
        candidate.mkdir()
        resolved_path = candidate / "config_resolved.json"
        resolved_path.write_text(
            json.dumps(
                resolved_config_dict(bundle.config),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        result_path = candidate / "result.h5"
        write_hf_result(result_path, bundle.result, bundle.model)
        identity = {
            "schema_version": "YPS-HF-CANDIDATE-IDENTITY-1.0",
            "model_id": bundle.result.model_id,
            "config_sha256": config_hash,
            "canonical_resolved_config_sha256_start": config_hash,
            "canonical_resolved_config_sha256_end": bundle.config_hash_end,
            "resolved_config_stable_during_run": (
                bundle.config_hash_end == config_hash
            ),
            "source_hash_start_sha256": bundle.source_start,
            "source_hash_end_sha256": bundle.source_end,
            "source_stable_during_run": bundle.source_start == bundle.source_end,
            "runtime_identity_start": bundle.runtime_identity_start,
            "runtime_identity_end": bundle.runtime_identity_end,
            "runtime_stable_during_run": (
                bundle.runtime_identity_start == bundle.runtime_identity_end
            ),
            "auxiliary_input_identity_start": bundle.auxiliary_input_hash_start,
            "auxiliary_input_identity_end": bundle.auxiliary_input_hash_end,
            "auxiliary_inputs_stable_during_run": (
                bundle.auxiliary_input_hash_start
                == bundle.auxiliary_input_hash_end
            ),
            "canonical_result_sha256_registered": registered_result_hash,
            "canonical_result_sha256_at_artifact_write": result_hash_at_write,
            "canonical_result_stable_before_artifact_write": (
                registered_result_hash == result_hash_at_write
            ),
            "controlled_physics_limit": bool(
                getattr(bundle.config.high_fidelity, "controlled_limit_study", False)
            ),
            "physical_status": bundle.result.physical_status,
            "numerical_status": bundle.result.numerical_status,
            "solver_method": bundle.config.solver.method,
            "elements": {
                name: getattr(bundle.config.cables, name).elements
                for name in ("upper_A", "upper_B", "lower")
            },
            "output_sample_count": int(bundle.result.time.size),
            "accepted_step_count": int(bundle.result.integration_time.size - 1),
            "units": "SI",
        }
        identity_path = candidate / "identity.json"
        identity_path.write_text(
            json.dumps(
                identity,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        files = []
        for path in (resolved_path, result_path, identity_path):
            files.append(
                {
                    "path": path.name,
                    "sha256": _sha256_file(path),
                    "bytes": path.stat().st_size,
                }
            )
        manifest_path = candidate / "candidate_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "YPS-HF-CANDIDATE-MANIFEST-1.0",
                    "config_sha256": config_hash,
                    "files": files,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        records[config_hash] = {
            "relative_directory": candidate.name,
            "candidate_manifest_sha256": _sha256_file(manifest_path),
            "candidate_manifest_bytes": manifest_path.stat().st_size,
        }
    return records


def _space_configs(base: SimulationConfig) -> list[SimulationConfig]:
    finest = [
        base.cables.upper_A.elements,
        base.cables.upper_B.elements,
        base.cables.lower.elements,
    ]
    if any(value % 4 for value in finest):
        raise ValueError("HF production element counts must be divisible by four.")
    levels: list[SimulationConfig] = []
    for divisor in (4, 2, 1):
        candidate = base.model_copy(deep=True)
        for name, value in zip(("upper_A", "upper_B", "lower"), finest, strict=True):
            getattr(candidate.cables, name).elements = value // divisor
        candidate.solver.allow_subminimum_mesh = divisor != 1
        levels.append(candidate)
    return levels


def _time_configs(base: SimulationConfig) -> list[SimulationConfig]:
    required = {
        "rtol": base.solver.rtol,
        "position_atol": base.solver.position_atol,
        "velocity_atol": base.solver.velocity_atol,
        "quaternion_atol": base.solver.quaternion_atol,
        "angular_velocity_atol": base.solver.angular_velocity_atol,
    }
    if any(value is None for value in required.values()) or base.solver.max_step == "auto":
        raise ValueError("HF convergence requires explicit finest tolerances and max_step.")
    levels: list[SimulationConfig] = []
    for tolerance_factor, step_factor in ((16.0, 4.0), (4.0, 2.0), (1.0, 1.0)):
        candidate = base.model_copy(deep=True)
        candidate.solver.rtol = float(base.solver.rtol) * tolerance_factor  # type: ignore[arg-type]
        candidate.solver.position_atol = _quantity_scaled(
            base.solver.position_atol, tolerance_factor, "m"
        )
        candidate.solver.velocity_atol = _quantity_scaled(
            base.solver.velocity_atol, tolerance_factor, "m/s"
        )
        candidate.solver.quaternion_atol = (
            float(base.solver.quaternion_atol) * tolerance_factor  # type: ignore[arg-type]
        )
        candidate.solver.angular_velocity_atol = _quantity_scaled(
            base.solver.angular_velocity_atol, tolerance_factor, "rad/s"
        )
        candidate.solver.max_step = _quantity_scaled(
            base.solver.max_step, step_factor, "s"
        )
        levels.append(candidate)
    return levels


def _cross_solver_config(
    base: SimulationConfig, spec: dict[str, Any]
) -> SimulationConfig:
    """Build an alternate-integrator candidate at a certified error budget.

    Equal relative tolerances do not imply equal local defects for different
    algorithms.  The factors are frozen before the study, applied to every
    scalar/vector tolerance, and persisted through the candidate config hash.
    """

    candidate = base.model_copy(deep=True)
    candidate.solver.method = "BDF" if base.solver.method == "Radau" else "Radau"
    factor = float(spec["cross_solver_tolerance_factors"][candidate.solver.method])
    required = (
        base.solver.rtol,
        base.solver.position_atol,
        base.solver.velocity_atol,
        base.solver.quaternion_atol,
        base.solver.angular_velocity_atol,
    )
    if any(value is None for value in required):
        raise ValueError("HF cross-solver validation requires explicit tolerances.")
    candidate.solver.rtol = float(base.solver.rtol) * factor  # type: ignore[arg-type]
    candidate.solver.position_atol = _quantity_scaled(
        base.solver.position_atol, factor, "m"
    )
    candidate.solver.velocity_atol = _quantity_scaled(
        base.solver.velocity_atol, factor, "m/s"
    )
    candidate.solver.quaternion_atol = (
        float(base.solver.quaternion_atol) * factor  # type: ignore[arg-type]
    )
    candidate.solver.angular_velocity_atol = _quantity_scaled(
        base.solver.angular_velocity_atol, factor, "rad/s"
    )
    return candidate


def run_hf_validation(
    base_config: SimulationConfig | str | Path | dict[str, Any],
    validation_spec: str | Path | dict[str, Any],
    *,
    artifact_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Run the frozen space/time/two-integrator HF qualification matrix."""

    base_input_path = (
        Path(base_config).expanduser().resolve()
        if isinstance(base_config, (str, Path))
        else None
    )
    spec_input_path = (
        Path(validation_spec).expanduser().resolve()
        if isinstance(validation_spec, (str, Path))
        else None
    )
    input_file_hash_start = {
        "base_config": (
            _sha256_file(base_input_path) if base_input_path is not None else None
        ),
        "validation_spec": (
            _sha256_file(spec_input_path) if spec_input_path is not None else None
        ),
    }
    base = (
        base_config
        if isinstance(base_config, SimulationConfig)
        else load_config(base_config)
    )
    if isinstance(validation_spec, (str, Path)):
        raw_spec = load_unique_yaml(validation_spec)
    else:
        raw_spec = validation_spec
    spec = _freeze_and_validate_spec(raw_spec)
    validate_physical_config(base)
    if base.run.mode != "high_fidelity":
        raise ValueError("HF validation requires run.mode=high_fidelity.")
    if base.solver.method not in {"Radau", "BDF"}:
        raise ValueError("HF validation requires Radau or BDF as the production method.")
    certification_target = _validation_target_applicability(base, spec)
    if not certification_target["passed"]:
        raise ValueError(
            "HF validation specification is not applicable to the resolved "
            f"production target: {certification_target['failure_reason']}"
        )
    base_hash = _canonical_config_hash(base)
    spec_hash = hashlib.sha256(
        json.dumps(
            spec,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    package_root = Path(__file__).resolve().parents[1]
    study_source_start = source_hash(package_root)
    runtime_identity_start = _runtime_identity()
    cache: dict[str, _RunBundle] = {}
    started = perf_counter()

    study_reports: dict[str, Any] = {}
    for study_name, candidates in (
        ("space", _space_configs(base)),
        ("time", _time_configs(base)),
    ):
        bundles = [_run_bundle(candidate, cache, package_root) for candidate in candidates]
        level_contracts = [
            _level_contract(
                bundle,
                spec["physics_checks"],
                apply_accuracy=index == len(bundles) - 1,
            )
            for index, bundle in enumerate(bundles)
        ]
        comparisons = [
            _compare(bundles[0], bundles[1], int(spec["material_comparison_points"])),
            _compare(bundles[1], bundles[2], int(spec["material_comparison_points"])),
        ]
        cauchy = _cauchy_gate(
            comparisons,
            spec["thresholds"][study_name],
            ratio_slack=float(spec["cauchy_ratio_slack"]),
            numerical_floor_fraction=float(spec["numerical_floor_fraction"]),
        )
        events = _event_stability(
            bundles, float(spec["maximum_event_time_spread_s"])
        )
        accuracy_trend = (
            _accuracy_trend_gate(
                level_contracts,
                spec["physics_checks"],
                ratio_slack=float(spec["cauchy_ratio_slack"]),
                numerical_floor_fraction=float(spec["numerical_floor_fraction"]),
            )
            if study_name == "time"
            else {
                "applicability": "not_applicable_to_space_refinement",
                "passed": True,
                "metrics": {},
            }
        )
        study_reports[study_name] = {
            "passed": all(level["passed"] for level in level_contracts)
            and cauchy["passed"]
            and events["passed"]
            and accuracy_trend["passed"],
            "levels": [
                {
                    "config_sha256": bundle.config_hash,
                    "elements": {
                        name: getattr(bundle.config.cables, name).elements
                        for name in ("upper_A", "upper_B", "lower")
                    },
                    "rtol": bundle.config.solver.rtol,
                    "max_step_s": float(
                        to_si(bundle.config.solver.max_step, default_unit="s")
                    ),
                    "runtime_seconds": bundle.result.diagnostics["runtime_seconds"],
                    "contract": contract,
                }
                for bundle, contract in zip(bundles, level_contracts, strict=True)
            ],
            "comparisons": comparisons,
            "cauchy": cauchy,
            "events": events,
            "accuracy_trend": accuracy_trend,
        }

    fine_bundle = _run_bundle(base, cache, package_root)
    cross_cfg = _cross_solver_config(base, spec)
    cross_bundle = _run_bundle(cross_cfg, cache, package_root)
    cross_comparison = _compare(
        fine_bundle, cross_bundle, int(spec["material_comparison_points"])
    )
    cross_checks = {
        metric: float(cross_comparison[metric]) <= float(threshold)
        for metric, threshold in spec["thresholds"]["cross_solver"].items()
    }
    cross_contracts = [
        _level_contract(bundle, spec["physics_checks"], apply_accuracy=True)
        for bundle in (fine_bundle, cross_bundle)
    ]
    cross_report = {
        "passed": all(cross_checks.values())
        and all(contract["passed"] for contract in cross_contracts),
        "methods": [base.solver.method, cross_cfg.solver.method],
        "alternate_tolerance_factor": float(
            spec["cross_solver_tolerance_factors"][cross_cfg.solver.method]
        ),
        "config_sha256": [fine_bundle.config_hash, cross_bundle.config_hash],
        "comparison": cross_comparison,
        "threshold_checks": cross_checks,
        "contracts": cross_contracts,
    }
    candidate_artifacts = (
        _write_candidate_artifacts(Path(artifact_directory), cache)
        if artifact_directory is not None
        else {}
    )
    study_source_end = source_hash(package_root)
    runtime_identity_end = _runtime_identity()
    input_file_hash_end = {
        "base_config": (
            _sha256_file(base_input_path) if base_input_path is not None else None
        ),
        "validation_spec": (
            _sha256_file(spec_input_path) if spec_input_path is not None else None
        ),
    }
    base_is_finest = (
        study_reports["space"]["levels"][-1]["config_sha256"] == base_hash
        and study_reports["time"]["levels"][-1]["config_sha256"] == base_hash
    )
    passed = (
        certification_target["passed"]
        and study_source_start == study_source_end
        and runtime_identity_start == runtime_identity_end
        and input_file_hash_start == input_file_hash_end
        and base_is_finest
        and all(report["passed"] for report in study_reports.values())
        and cross_report["passed"]
    )
    return {
        "schema_version": "YPS-HF-VALIDATION-REPORT-1.0",
        "qualification": (
            "HF_REFINEMENT_SUPPORTED" if passed else "HF_CONVERGENCE_NOT_DEMONSTRATED"
        ),
        "passed": passed,
        "model_id": HighFidelityModel.model_id,
        "base_config_sha256": base_hash,
        "validation_spec_sha256": spec_hash,
        "certification_target": certification_target,
        "base_config_is_finest_level": base_is_finest,
        "source_hash_start_sha256": study_source_start,
        "source_hash_end_sha256": study_source_end,
        "source_stable_during_study": study_source_start == study_source_end,
        "runtime_identity_start": runtime_identity_start,
        "runtime_identity_end": runtime_identity_end,
        "runtime_stable_during_study": runtime_identity_start
        == runtime_identity_end,
        "input_file_hash_start": input_file_hash_start,
        "input_file_hash_end": input_file_hash_end,
        "input_files_stable_during_study": input_file_hash_start
        == input_file_hash_end,
        "unique_run_count": len(cache),
        "wall_time_seconds": perf_counter() - started,
        "studies": study_reports,
        "cross_solver": cross_report,
        "candidate_artifacts": candidate_artifacts,
        "validation_spec": spec,
    }

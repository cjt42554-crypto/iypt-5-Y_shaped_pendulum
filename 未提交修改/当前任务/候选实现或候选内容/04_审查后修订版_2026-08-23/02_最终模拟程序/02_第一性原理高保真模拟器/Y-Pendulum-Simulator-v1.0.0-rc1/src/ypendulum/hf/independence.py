"""Controlled-limit evidence that the HF backend contains additional physics."""

from __future__ import annotations

import hashlib
import json
from numbers import Integral, Real
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from ypendulum.config import SimulationConfig, load_config, load_unique_yaml
from ypendulum.io.provenance import source_hash

from .model import HighFidelityModel
from .validation import (
    _COMPARISON_METRICS,
    _canonical_config_hash,
    _compare,
    _cross_solver_config,
    _freeze_and_validate_spec,
    _json_safe_finite,
    _level_contract,
    _run_bundle,
    _runtime_identity,
    _sha256_file,
    _validation_target_applicability,
    _write_candidate_artifacts,
)

_LOCKED_ALPHA_SCALES = [1.0, 1.0e-2, 1.0e-4, 1.0e-6]


def _positive_real(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a positive finite real number.")
    scalar = float(value)
    if not np.isfinite(scalar) or scalar <= 0.0:
        raise ValueError(f"{name} must be a positive finite real number.")
    return scalar


def _freeze_independence_spec(raw: Any) -> dict[str, Any]:
    required = {
        "schema_version",
        "limit_scales",
        "cauchy_ratio_slack",
        "cross_solver_floor_multiplier",
        "separation_factor",
        "minimum_separation_metric_count",
        "minimum_finite_to_limit",
        "minimum_peak_bending_energy_J",
        "minimum_peak_angular_velocity_rad_s",
        "material_comparison_points",
    }
    allowed = required | {"metadata"}
    if (
        not isinstance(raw, dict)
        or not _json_safe_finite(raw)
        or set(raw) - allowed
        or required - set(raw)
    ):
        raise ValueError("HF independence specification fields do not match the frozen schema.")
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
        raise ValueError("HF independence specification is not finite canonical JSON.") from exc
    if spec["schema_version"] != "YPS-HF-INDEPENDENCE-1.0":
        raise ValueError("Invalid HF independence specification schema.")
    scales = spec["limit_scales"]
    if not isinstance(scales, list):
        raise ValueError("limit_scales must be the locked alpha scale list.")
    scale_values = [_positive_real(value, "limit_scales[]") for value in scales]
    if scale_values != _LOCKED_ALPHA_SCALES:
        raise ValueError(
            "limit_scales must equal the locked list [1, 1e-2, 1e-4, 1e-6]."
        )
    ratio_slack = _positive_real(spec["cauchy_ratio_slack"], "cauchy_ratio_slack")
    if ratio_slack < 1.0:
        raise ValueError("cauchy_ratio_slack must be at least one.")
    floor_multiplier = _positive_real(
        spec["cross_solver_floor_multiplier"], "cross_solver_floor_multiplier"
    )
    if floor_multiplier < 1.0:
        raise ValueError("cross_solver_floor_multiplier must be at least one.")
    separation_factor = _positive_real(spec["separation_factor"], "separation_factor")
    if separation_factor < 1.0:
        raise ValueError("separation_factor must be at least one.")
    count = spec["minimum_separation_metric_count"]
    if isinstance(count, bool) or not isinstance(count, Integral) or count < 1:
        raise ValueError("minimum_separation_metric_count must be a positive integer.")
    points = spec["material_comparison_points"]
    if isinstance(points, bool) or not isinstance(points, Integral) or not 5 <= points <= 4097:
        raise ValueError("material_comparison_points must be an integer in [5,4097].")
    selected = spec["minimum_finite_to_limit"]
    if not isinstance(selected, dict) or not selected:
        raise ValueError("minimum_finite_to_limit must contain selected canonical metrics.")
    if not set(selected).issubset(_COMPARISON_METRICS):
        raise ValueError("minimum_finite_to_limit contains a non-canonical metric.")
    if count > len(selected):
        raise ValueError("minimum_separation_metric_count exceeds selected metrics.")
    for metric, value in selected.items():
        _positive_real(value, f"minimum_finite_to_limit.{metric}")
    _positive_real(
        spec["minimum_peak_bending_energy_J"], "minimum_peak_bending_energy_J"
    )
    _positive_real(
        spec["minimum_peak_angular_velocity_rad_s"],
        "minimum_peak_angular_velocity_rad_s",
    )
    return spec


def _input_path(value: Any) -> Path | None:
    return Path(value).expanduser().resolve() if isinstance(value, (str, Path)) else None


def run_hf_independence_study(
    base_config: SimulationConfig | str | Path | dict[str, Any],
    validation_spec: str | Path | dict[str, Any],
    independence_spec: str | Path | dict[str, Any],
    *,
    artifact_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Run a finite-physics versus controlled-zero-limit separation study."""

    base_path = _input_path(base_config)
    validation_path = _input_path(validation_spec)
    independence_path = _input_path(independence_spec)
    input_start = {
        "base_config": _sha256_file(base_path) if base_path else None,
        "validation_spec": _sha256_file(validation_path) if validation_path else None,
        "independence_spec": (
            _sha256_file(independence_path) if independence_path else None
        ),
    }
    base = base_config if isinstance(base_config, SimulationConfig) else load_config(base_config)
    raw_validation = (
        load_unique_yaml(validation_spec)
        if isinstance(validation_spec, (str, Path))
        else validation_spec
    )
    physics_spec = _freeze_and_validate_spec(raw_validation)
    raw_independence = (
        load_unique_yaml(independence_spec)
        if isinstance(independence_spec, (str, Path))
        else independence_spec
    )
    spec = _freeze_independence_spec(raw_independence)
    if base.run.mode != "high_fidelity":
        raise ValueError("HF independence study requires run.mode=high_fidelity.")
    if base.solver.method not in {"Radau", "BDF"}:
        raise ValueError("HF independence study requires Radau or BDF as the base solver.")
    certification_target = _validation_target_applicability(base, physics_spec)
    if not certification_target["passed"]:
        raise ValueError(
            "HF independence validation specification is not applicable to the "
            f"resolved production target: {certification_target['failure_reason']}"
        )
    if (
        base.high_fidelity.bending_stiffness_scale != 1.0
        or base.high_fidelity.compression_regularization_scale != 1.0
        or base.high_fidelity.bob_attachment_radius_fraction != 1.0
        or base.high_fidelity.bob_contact_radius_fraction != 1.0
        or base.high_fidelity.controlled_limit_study
    ):
        raise ValueError(
            "The finite-physics base must use unit bending, compression, attachment "
            "and contact scales with controlled_limit_study=false."
        )

    package_root = Path(__file__).resolve().parents[1]
    source_start = source_hash(package_root)
    runtime_start = _runtime_identity()
    cache = {}
    started = perf_counter()
    full = _run_bundle(base, cache, package_root)
    limit_bundles = []
    for scale in spec["limit_scales"][1:]:
        candidate = base.model_copy(deep=True)
        candidate.high_fidelity.bending_stiffness_scale = float(scale)
        candidate.high_fidelity.compression_regularization_scale = float(scale)
        candidate.high_fidelity.bob_attachment_radius_fraction = float(scale)
        candidate.high_fidelity.bob_contact_radius_fraction = float(scale)
        candidate.high_fidelity.controlled_limit_study = True
        candidate.run.claim_level = "OUT_OF_SCOPE"
        limit_bundles.append(_run_bundle(candidate, cache, package_root))
    alternate = _cross_solver_config(base, physics_spec)
    cross = _run_bundle(alternate, cache, package_root)

    contracts = {
        bundle.config_hash: _level_contract(
            bundle, physics_spec["physics_checks"], apply_accuracy=True
        )
        for bundle in [full, *limit_bundles, cross]
    }
    material_points = int(spec["material_comparison_points"])
    alpha_bundles = [full, *limit_bundles]
    adjacent = [
        _compare(left, right, material_points)
        for left, right in zip(alpha_bundles, alpha_bundles[1:], strict=True)
    ]
    full_to_limit = _compare(full, limit_bundles[-1], material_points)
    cross_solver = _compare(full, cross, material_points)
    ratio = float(spec["cauchy_ratio_slack"])
    floor_multiplier = float(spec["cross_solver_floor_multiplier"])
    contraction_checks = {}
    for metric in _COMPARISON_METRICS:
        values = [float(comparison[metric]) for comparison in adjacent]
        floor = floor_multiplier * float(cross_solver[metric])
        steps = [
            values[index + 1] <= values[index] / ratio
            or values[index + 1] <= floor
            for index in range(len(values) - 1)
        ]
        contraction_checks[metric] = {
            "alpha_scales": spec["limit_scales"],
            "successive_alpha_differences": values,
            "cross_solver_floor": floor,
            "step_checks": steps,
            "passed": all(steps),
        }
    separation_checks = {}
    for metric, minimum in spec["minimum_finite_to_limit"].items():
        difference = float(full_to_limit[metric])
        numerical = float(cross_solver[metric])
        required = max(float(minimum), float(spec["separation_factor"]) * numerical)
        separation_checks[metric] = {
            "finite_to_limit_difference": difference,
            "full_cross_solver_difference": numerical,
            "required_difference": required,
            "passed": difference > required,
        }
    separation_count = sum(item["passed"] for item in separation_checks.values())
    peak_bending = float(np.max(full.result.energy["elastic_bending"]))
    peak_angular_velocity = float(
        np.max(np.linalg.norm(full.result.bob_angular_velocity, axis=1))
    )
    physical_evidence = {
        "peak_bending_energy_J": peak_bending,
        "peak_bending_energy_passed": peak_bending
        >= float(spec["minimum_peak_bending_energy_J"]),
        "peak_bob_angular_velocity_rad_s": peak_angular_velocity,
        "peak_bob_angular_velocity_passed": peak_angular_velocity
        >= float(spec["minimum_peak_angular_velocity_rad_s"]),
    }
    artifacts = (
        _write_candidate_artifacts(Path(artifact_directory), cache)
        if artifact_directory is not None
        else {}
    )
    source_end = source_hash(package_root)
    runtime_end = _runtime_identity()
    input_end = {
        "base_config": _sha256_file(base_path) if base_path else None,
        "validation_spec": _sha256_file(validation_path) if validation_path else None,
        "independence_spec": (
            _sha256_file(independence_path) if independence_path else None
        ),
    }
    passed = (
        certification_target["passed"]
        and source_start == source_end
        and runtime_start == runtime_end
        and input_start == input_end
        and all(contract["passed"] for contract in contracts.values())
        and all(item["passed"] for item in contraction_checks.values())
        and separation_count >= int(spec["minimum_separation_metric_count"])
        and all(
            physical_evidence[key]
            for key in (
                "peak_bending_energy_passed",
                "peak_bob_angular_velocity_passed",
            )
        )
    )
    spec_hash = hashlib.sha256(
        json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return {
        "schema_version": "YPS-HF-INDEPENDENCE-REPORT-1.0",
        "qualification": (
            "HF_INDEPENDENCE_SUPPORTED"
            if passed
            else "HF_INDEPENDENCE_NOT_DEMONSTRATED"
        ),
        "passed": passed,
        "model_id": HighFidelityModel.model_id,
        "base_config_sha256": _canonical_config_hash(base),
        "validation_spec_sha256": hashlib.sha256(
            json.dumps(
                physics_spec,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest(),
        "certification_target": certification_target,
        "independence_spec_sha256": spec_hash,
        "source_hash_start_sha256": source_start,
        "source_hash_end_sha256": source_end,
        "source_stable_during_study": source_start == source_end,
        "runtime_identity_start": runtime_start,
        "runtime_identity_end": runtime_end,
        "runtime_stable_during_study": runtime_start == runtime_end,
        "input_file_hash_start": input_start,
        "input_file_hash_end": input_end,
        "input_files_stable_during_study": input_start == input_end,
        "wall_time_seconds": perf_counter() - started,
        "unique_run_count": len(cache),
        "finite_config_sha256": full.config_hash,
        "limit_scales": spec["limit_scales"],
        "alpha_candidate_configs": [
            {
                "alpha": float(scale),
                "config_sha256": bundle.config_hash,
                "controlled_limit_study": bool(
                    bundle.config.high_fidelity.controlled_limit_study
                ),
                "claim_level": bundle.config.run.claim_level,
            }
            for scale, bundle in zip(
                spec["limit_scales"], alpha_bundles, strict=True
            )
        ],
        "jointly_scaled_parameters": [
            "bending_stiffness_scale",
            "compression_regularization_scale",
            "bob_attachment_radius_fraction",
            "bob_contact_radius_fraction",
        ],
        "limit_config_sha256": [bundle.config_hash for bundle in limit_bundles],
        "cross_solver_config_sha256": cross.config_hash,
        "contracts": contracts,
        "limit_contraction": contraction_checks,
        "finite_to_limit": full_to_limit,
        "full_cross_solver": cross_solver,
        "separation_checks": separation_checks,
        "separation_metric_pass_count": separation_count,
        "physical_evidence": physical_evidence,
        "candidate_artifacts": artifacts,
        "independence_spec": spec,
    }

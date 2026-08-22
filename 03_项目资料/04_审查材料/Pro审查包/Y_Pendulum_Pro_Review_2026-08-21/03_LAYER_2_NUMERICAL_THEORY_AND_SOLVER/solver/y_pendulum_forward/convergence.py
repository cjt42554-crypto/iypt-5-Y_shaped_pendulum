"""Pre-thresholded, whole-state Cauchy refinement qualification.

The studies in this module are empirical numerical evidence for the frozen
forward models.  They are deliberately fail-closed: an invalid base input,
unexpected status/event, identity mismatch, missing canonical field, unsafe
guard sample, or unmet pre-frozen threshold prevents
``REFINEMENT_SUPPORTED``.  The result is not a verified PDE error enclosure.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np
from scipy.integrate import cumulative_trapezoid
from scipy.linalg import cho_factor, cho_solve

from .activation import activation_primitive, tension_components
from .cable import (
    BRANCHES,
    CableFEM,
    _validate_cable_numerics,
    parse_cable_physical,
)
from .contracts import (
    MIN_SOLVER_RTOL,
    PROGRAM_VERSION,
    THEORY_SHA256,
    SimulationResult,
    is_finite_number,
    json_input_issues,
    numerical_time_resource_issues,
    run_identity_hashes,
    source_tree_sha256,
)
from .runner import run_config
from .observations import evaluate_observations
from .torus import (
    _output_times,
    _validate_torus_numerics,
    torus_derived,
    torus_rhs,
    validate_torus_config,
)


VALIDATION_SCHEMA_VERSION = "YPS-FWD-VALIDATION-1.0"
STUDY_CONTROL_FIELDS = {
    "max_finest_event_time_difference",
    "cauchy_ratio_slack",
    "normalized_numerical_floor",
    "energy_ratio_slack",
    "energy_floor",
    "comparison_time_step",
    "minimum_comparison_samples",
    "guard_variation_safety_factor",
}
COMMON_METRIC_FIELDS = {
    "max_finest_rms_bob_position",
    "max_finest_max_bob_position",
}
CABLE_METRIC_FIELDS = {
    "max_finest_rms_bob_velocity",
    "max_finest_max_bob_velocity",
    "max_finest_rms_junction_position",
    "max_finest_max_junction_position",
    "max_finest_rms_junction_velocity",
    "max_finest_max_junction_velocity",
    "max_finest_rms_cable_position",
    "max_finest_max_cable_position",
    "max_finest_rms_cable_velocity",
    "max_finest_max_cable_velocity",
    "max_finest_rms_stretch",
    "max_finest_max_stretch",
    "max_finest_rms_stretch_rate",
    "max_finest_max_stretch_rate",
    "max_finest_rms_tension",
    "max_finest_max_tension",
    "max_finest_rms_energy",
    "max_finest_max_energy",
    "max_finest_rms_dissipation_power",
    "max_finest_max_dissipation_power",
    "max_finest_rms_input_power",
    "max_finest_max_input_power",
    "material_comparison_points",
}
CABLE_AUXILIARY_STUDY_FIELDS = {
    "max_finest_boundary_reaction_difference",
}
TORUS_METRIC_FIELDS = {
    "max_finest_rms_angle",
    "max_finest_max_angle",
    "max_finest_rms_angular_rate",
    "max_finest_max_angular_rate",
    "max_finest_rms_tension",
    "max_finest_max_tension",
    "max_finest_rms_energy",
    "max_finest_max_energy",
}

COMMON_PHYSICS_FIELDS = {
    "maximum_energy_metric",
    "maximum_normalized_dynamics_defect",
    "maximum_normalized_cumulative_dynamics_defect",
    "maximum_normalized_absolute_dynamics_defect",
}
FINEST_ONLY_ACCURACY_CHECKS = {
    "energy_metric_finite_and_bounded",
    "dynamics_defect_finite_and_bounded",
    "dynamics_cumulative_defect_finite_and_bounded",
    "dynamics_absolute_defect_finite_and_bounded",
}
ACCURACY_METRIC_FIELDS = (
    "energy_metric",
    "maximum_normalized_dynamics_defect",
    "maximum_normalized_cumulative_dynamics_defect",
    "maximum_normalized_absolute_dynamics_defect",
)
CABLE_PHYSICS_FIELDS = {
    "maximum_negative_dissipation",
    "minimum_mass_eigenvalue",
    "maximum_mass_condition_number",
    "maximum_mass_symmetry_inf_norm",
    "boundary_reaction_ratio_slack",
    "boundary_reaction_floor",
    "minimum_completed_lambda_margin",
    "minimum_completed_material_lambda_margin",
    "minimum_completed_material_rate_margin",
    "minimum_completed_custom_guard_margin",
    "maximum_negative_returned_lambda_margin",
    "maximum_negative_returned_material_lambda_margin",
    "maximum_negative_returned_material_rate_margin",
    "maximum_negative_returned_custom_guard_margin",
}
TORUS_PHYSICS_FIELDS = {
    "maximum_abs_geometry_residual",
    "maximum_negative_Q_T",
    "minimum_completed_R",
    "minimum_completed_tension",
    "maximum_negative_returned_R",
    "maximum_negative_returned_tension",
}

IDENTITY_FIELDS = (
    "program_version",
    "config_schema_version",
    "numerical_model_id",
    "theory_sha256",
    "units",
    "config_sha256",
    "physical_input_sha256",
    "numerical_config_sha256",
    "observation_input_sha256",
    "source_tree_sha256",
    "runtime_versions",
)


def run_refinement_study(config: dict[str, Any]) -> dict[str, Any]:
    """Run isolated three-level studies and apply pre-frozen acceptance gates."""

    try:
        base = deepcopy(config)
    except Exception as exc:
        return _invalid_report(
            None,
            "INVALID_BASE_CONFIG",
            [_validation_error("config", repr(exc), "deep-copyable JSON object")],
        )
    if not isinstance(base, dict):
        return _invalid_report(
            None,
            "INVALID_BASE_CONFIG",
            [_validation_error("config", type(base).__name__, "JSON object")],
        )
    json_issues = json_input_issues(base, "config")
    if json_issues:
        return _invalid_report(
            base.get("model_id"),
            "INVALID_BASE_CONFIG",
            [issue.as_dict() for issue in json_issues],
        )
    study_start_identity = run_identity_hashes(base)
    model_id = base.get("model_id")
    if model_id not in ("FWD-CABLE-1.0", "FWD-TORUS-1.0"):
        return _invalid_report(
            model_id,
            "INVALID_MODEL_ID",
            [
                _validation_error(
                    "model_id",
                    model_id,
                    "FWD-CABLE-1.0 or FWD-TORUS-1.0",
                )
            ],
        )

    validation, validation_errors = _parse_validation(base, model_id)
    if validation_errors:
        return _invalid_report(
            model_id, "INVALID_VALIDATION_CONFIG", validation_errors
        )
    assert validation is not None

    base_errors = _preflight_base_config(base, model_id)
    if base_errors:
        return _invalid_report(model_id, "INVALID_BASE_CONFIG", base_errors)

    generated, generation_errors = _generate_isolated_studies(base, model_id)
    if generation_errors:
        return _invalid_report(
            model_id, "INVALID_VALIDATION_CONFIG", generation_errors
        )
    assert generated is not None

    cache: dict[str, tuple[dict[str, Any], SimulationResult]] = {}
    studies: dict[str, Any] = {}
    for study_name, configs in generated.items():
        studies[study_name] = _study(
            study_name,
            configs,
            validation["studies"][study_name],
            validation["physics_checks"],
            validation["expected_contract_status"],
            model_id,
            study_start_identity,
            cache,
        )

    source_end = source_tree_sha256()
    whole_study_source_stable = (
        source_end == study_start_identity["source_tree_sha256"]
    )
    base_config_is_finest_level = bool(studies) and all(
        study.get("levels")
        and study["levels"][-1].get("expected_config_sha256")
        == study_start_identity["config_sha256"]
        for study in studies.values()
    )
    all_passed = (
        bool(studies)
        and whole_study_source_stable
        and base_config_is_finest_level
        and all(study.get("passed") is True for study in studies.values())
    )
    return {
        "qualification": (
            "REFINEMENT_SUPPORTED"
            if all_passed
            else "CONVERGENCE_NOT_DEMONSTRATED"
        ),
        "model_id": model_id,
        "program_version": PROGRAM_VERSION,
        "theory_sha256": THEORY_SHA256,
        "base_config_sha256": study_start_identity["config_sha256"],
        "physical_input_sha256": study_start_identity[
            "physical_input_sha256"
        ],
        "source_tree_sha256": study_start_identity["source_tree_sha256"],
        "source_tree_sha256_at_end": source_end,
        "whole_study_source_stable": bool(whole_study_source_stable),
        "runtime_versions": study_start_identity["runtime_versions"],
        "validation_schema_version": VALIDATION_SCHEMA_VERSION,
        "thresholds_source": "pre-frozen config.validation",
        "base_config_is_finest_level": bool(base_config_is_finest_level),
        "expected_contract_status": validation["expected_contract_status"],
        "physics_criteria": validation["physics_checks"],
        "unique_run_count": len(cache),
        "studies": studies,
        "interpretation": (
            "empirical whole-run Cauchy, event, identity, and invariant evidence "
            "under pre-frozen thresholds; not a verified continuous-PDE "
            "existence or error proof"
        ),
    }


def _preflight_base_config(
    config: dict[str, Any], model_id: str
) -> list[dict[str, Any]]:
    """Use the same strict physical/numerical schemas before generating levels."""

    errors: list[dict[str, Any]] = []
    numerics = config.get("numerics")
    if not isinstance(numerics, dict):
        errors.append(_validation_error("numerics", numerics, "object"))
        return errors
    if model_id == "FWD-CABLE-1.0":
        physical_issues, _physical = parse_cable_physical(config)
        numerical_issues = _validate_cable_numerics(numerics)
    else:
        physical_issues, _physical = validate_torus_config(config)
        numerical_issues = _validate_torus_numerics(numerics)
    errors.extend(issue.as_dict() for issue in physical_issues)
    errors.extend(issue.as_dict() for issue in numerical_issues)
    if _physical is not None:
        default_max_step = float(_physical.T) / 200.0
        default_output_dt = float(_physical.T) / (
            500.0 if model_id == "FWD-CABLE-1.0" else 1000.0
        )
        errors.extend(
            issue.as_dict()
            for issue in numerical_time_resource_issues(
                _physical.T,
                numerics.get("max_step", default_max_step),
                numerics.get("output_dt", default_output_dt),
            )
        )
    return errors


def _generate_isolated_studies(
    config: dict[str, Any], model_id: str
) -> tuple[dict[str, list[dict[str, Any]]] | None, list[dict[str, Any]]]:
    """Vary one error source while freezing the other two at their finest level."""

    errors: list[dict[str, Any]] = []
    numerics = config["numerics"]
    physical = config.get("physical", {})
    T = physical.get("T") if isinstance(physical, dict) else None
    if not is_finite_number(T) or float(T) <= 0.0:
        errors.append(_validation_error("physical.T", T, "positive finite real"))
        return None, errors

    default_rtol = 1e-7 if model_id == "FWD-CABLE-1.0" else 1e-9
    default_atol = 1e-9 if model_id == "FWD-CABLE-1.0" else 1e-11
    refinement_values: dict[str, float] = {}
    for key, default in (
        ("rtol", default_rtol),
        ("atol", default_atol),
        ("max_step", float(T) / 200.0),
    ):
        value = numerics.get(key, default)
        if not is_finite_number(value) or float(value) <= 0.0:
            errors.append(
                _validation_error(
                    f"numerics.{key}", value, "positive finite real"
                )
            )
        else:
            refinement_values[key] = float(value)
    for key in (
        "atol_position",
        "atol_velocity",
        "atol_angle",
        "atol_rate",
    ):
        if key not in numerics:
            continue
        value = numerics[key]
        if not is_finite_number(value) or float(value) <= 0.0:
            errors.append(
                _validation_error(
                    f"numerics.{key}", value, "positive finite real"
                )
            )
        else:
            refinement_values[key] = float(value)
    if errors:
        return None, errors
    if refinement_values["rtol"] < MIN_SOLVER_RTOL:
        errors.append(
            _validation_error(
                "numerics.rtol",
                refinement_values["rtol"],
                f"rtol >= machine floor {MIN_SOLVER_RTOL:.17g}",
            )
        )
        return None, errors
    if refinement_values["rtol"] * 16.0 >= 1.0:
        errors.append(
            _validation_error(
                "numerics.rtol",
                refinement_values["rtol"],
                "16*rtol < 1 for the distinct coarser time level",
            )
        )
        return None, errors

    def time_level(coarsening_factor: int) -> dict[str, Any]:
        candidate = deepcopy(config)
        target = candidate["numerics"]
        target["rtol"] = refinement_values["rtol"] * coarsening_factor
        target["atol"] = refinement_values["atol"] * coarsening_factor
        for name in (
            "atol_position",
            "atol_velocity",
            "atol_angle",
            "atol_rate",
        ):
            if name in refinement_values:
                target[name] = refinement_values[name] * coarsening_factor
        target["max_step"] = (
            refinement_values["max_step"] * np.sqrt(coarsening_factor)
        )
        return candidate

    if model_id == "FWD-TORUS-1.0":
        return {
            "time": [
                time_level(factor) for factor in (16, 4, 1)
            ]
        }, []

    elements = numerics.get("elements")
    if (
        not isinstance(elements, dict)
        or set(elements) != set(BRANCHES)
        or any(
            not isinstance(elements.get(name), int)
            or isinstance(elements.get(name), bool)
            or elements[name] < 4
            or elements[name] % 4 != 0
            for name in BRANCHES
        )
    ):
        errors.append(
            _validation_error(
                "numerics.elements",
                elements,
                "exact A, B, and lower integer counts divisible by 4 and >= 4",
            )
        )
        return None, errors
    base_q = numerics.get("quadrature_order", 3)
    if (
        not isinstance(base_q, int)
        or isinstance(base_q, bool)
        or base_q < 5
        or base_q > 8
    ):
        errors.append(
            _validation_error(
                "numerics.quadrature_order",
                base_q,
                "integer in [5,8] for distinct q-4,q-2,q finest levels",
            )
        )
        return None, errors

    finest_q = base_q
    finest_elements = {name: int(elements[name]) for name in BRANCHES}

    space: list[dict[str, Any]] = []
    for divisor in (4, 2, 1):
        candidate = time_level(1)
        candidate["numerics"]["quadrature_order"] = finest_q
        candidate["numerics"]["elements"] = {
            name: int(elements[name]) // divisor for name in BRANCHES
        }
        space.append(candidate)

    quadrature: list[dict[str, Any]] = []
    for order in (base_q - 4, base_q - 2, base_q):
        candidate = time_level(1)
        candidate["numerics"]["elements"] = deepcopy(finest_elements)
        candidate["numerics"]["quadrature_order"] = order
        quadrature.append(candidate)

    time: list[dict[str, Any]] = []
    for factor in (16, 4, 1):
        candidate = time_level(factor)
        candidate["numerics"]["elements"] = deepcopy(finest_elements)
        candidate["numerics"]["quadrature_order"] = finest_q
        time.append(candidate)
    return {"space": space, "quadrature": quadrature, "time": time}, []


def _parse_validation(
    config: dict[str, Any], model_id: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    raw = config.get("validation")
    if not isinstance(raw, dict):
        return None, [
            _validation_error(
                "validation", raw, "object with pre-frozen thresholds"
            )
        ]
    _reject_unknown(
        raw,
        {"schema_version", "expected_contract_status", "studies", "physics_checks"},
        "validation",
        errors,
    )
    if raw.get("schema_version") != VALIDATION_SCHEMA_VERSION:
        errors.append(
            _validation_error(
                "validation.schema_version",
                raw.get("schema_version"),
                VALIDATION_SCHEMA_VERSION,
            )
        )

    expected = raw.get("expected_contract_status")
    if expected not in (["COMPLETED"], ["OUT_OF_SCOPE"]):
        errors.append(
            _validation_error(
                "validation.expected_contract_status",
                expected,
                "exactly ['COMPLETED'] or ['OUT_OF_SCOPE']",
            )
        )

    required_studies = (
        {"space", "quadrature", "time"}
        if model_id == "FWD-CABLE-1.0"
        else {"time"}
    )
    metric_fields = COMMON_METRIC_FIELDS | (
        CABLE_METRIC_FIELDS
        if model_id == "FWD-CABLE-1.0"
        else TORUS_METRIC_FIELDS
    )
    required_study_fields = STUDY_CONTROL_FIELDS | metric_fields
    if model_id == "FWD-CABLE-1.0":
        required_study_fields |= CABLE_AUXILIARY_STUDY_FIELDS
    studies = raw.get("studies")
    normalized_studies: dict[str, dict[str, Any]] = {}
    if not isinstance(studies, dict):
        errors.append(
            _validation_error(
                "validation.studies",
                studies,
                f"object with exactly {sorted(required_studies)}",
            )
        )
    else:
        if set(studies) != required_studies:
            errors.append(
                _validation_error(
                    "validation.studies",
                    sorted(studies),
                    f"exact keys {sorted(required_studies)}",
                )
            )
        for name in sorted(required_studies):
            path = f"validation.studies.{name}"
            criterion = studies.get(name)
            if not isinstance(criterion, dict):
                errors.append(_validation_error(path, criterion, "threshold object"))
                continue
            _reject_unknown(criterion, required_study_fields, path, errors)
            if set(criterion) != required_study_fields:
                errors.append(
                    _validation_error(
                        path,
                        sorted(criterion),
                        f"all required keys {sorted(required_study_fields)}",
                    )
                )
            normalized: dict[str, Any] = {}
            for field in required_study_fields:
                value = criterion.get(field)
                if field in {"minimum_comparison_samples", "material_comparison_points"}:
                    minimum = 3 if field == "minimum_comparison_samples" else 5
                    if (
                        not isinstance(value, int)
                        or isinstance(value, bool)
                        or value < minimum
                    ):
                        errors.append(
                            _validation_error(
                                f"{path}.{field}", value, f"integer >= {minimum}"
                            )
                        )
                        value = minimum
                    normalized[field] = value
                    continue
                minimum = 1.0 if field.endswith("ratio_slack") else 0.0
                if field == "guard_variation_safety_factor":
                    minimum = 1.0
                strict = (
                    field.startswith("max_")
                    or field.endswith("ratio_slack")
                    or field == "comparison_time_step"
                    or field == "guard_variation_safety_factor"
                )
                normalized[field] = _finite_number(
                    value,
                    f"{path}.{field}",
                    errors,
                    minimum=minimum,
                    strict=strict,
                )
            normalized_studies[name] = normalized

    required_physics = COMMON_PHYSICS_FIELDS | (
        CABLE_PHYSICS_FIELDS
        if model_id == "FWD-CABLE-1.0"
        else TORUS_PHYSICS_FIELDS
    )
    physics = raw.get("physics_checks")
    normalized_physics: dict[str, float] = {}
    if not isinstance(physics, dict):
        errors.append(
            _validation_error(
                "validation.physics_checks",
                physics,
                f"object with all keys {sorted(required_physics)}",
            )
        )
    else:
        _reject_unknown(
            physics, required_physics, "validation.physics_checks", errors
        )
        if set(physics) != required_physics:
            errors.append(
                _validation_error(
                    "validation.physics_checks",
                    sorted(physics),
                    f"all required keys {sorted(required_physics)}",
                )
            )
        strict_positive = {
            "maximum_energy_metric",
            "maximum_normalized_dynamics_defect",
            "maximum_normalized_cumulative_dynamics_defect",
            "maximum_normalized_absolute_dynamics_defect",
            "minimum_mass_eigenvalue",
            "maximum_mass_condition_number",
            "maximum_mass_symmetry_inf_norm",
            "boundary_reaction_ratio_slack",
            "boundary_reaction_floor",
            "minimum_completed_lambda_margin",
            "minimum_completed_material_lambda_margin",
            "minimum_completed_material_rate_margin",
            "minimum_completed_custom_guard_margin",
            "minimum_completed_R",
            "minimum_completed_tension",
        }
        for field in required_physics:
            minimum = (
                1.0 if field == "boundary_reaction_ratio_slack" else 0.0
            )
            normalized_physics[field] = _finite_number(
                physics.get(field),
                f"validation.physics_checks.{field}",
                errors,
                minimum=minimum,
                strict=field in strict_positive,
            )

    if errors:
        return None, errors
    return {
        "expected_contract_status": list(expected),
        "studies": normalized_studies,
        "physics_checks": normalized_physics,
    }, []


def _study(
    study_name: str,
    configs: list[dict[str, Any]],
    criterion: dict[str, Any],
    physics_criteria: dict[str, float],
    expected_contract_status: list[str],
    model_id: str,
    study_start_identity: dict[str, Any],
    cache: dict[str, tuple[dict[str, Any], SimulationResult]],
) -> dict[str, Any]:
    executed_configs = [deepcopy(config) for config in configs]
    for candidate in executed_configs:
        candidate["numerics"]["output_dt"] = criterion["comparison_time_step"]

    expected_identities: list[dict[str, Any]] = []
    results: list[SimulationResult] = []
    reused: list[bool] = []
    for candidate in executed_configs:
        expected = run_identity_hashes(candidate)
        key = expected["config_sha256"]
        if key in cache:
            cached_expected, result = cache[key]
            expected = cached_expected
            reused.append(True)
        else:
            result = run_config(candidate)
            cache[key] = (expected, result)
            reused.append(False)
        expected_identities.append(expected)
        results.append(result)

    level_reports: list[dict[str, Any]] = []
    energy_metrics: list[float] = []
    dynamics_fields = (
        "maximum_normalized_dynamics_defect",
        "maximum_normalized_cumulative_dynamics_defect",
        "maximum_normalized_absolute_dynamics_defect",
    )
    dynamics_by_field: dict[str, list[float]] = {
        field: [] for field in dynamics_fields
    }
    dynamics_metrics: list[float] = []
    event_signatures: list[list[dict[str, Any]]] = []
    expected_guard_schemas: list[dict[str, Any] | None] = []
    for index, (candidate, expected, result) in enumerate(
        zip(executed_configs, expected_identities, results)
    ):
        expected_guard_schema = _expected_guard_schema(candidate, model_id)
        expected_guard_schemas.append(expected_guard_schema)
        guard_output_contract = _guard_output_contract(
            result,
            expected_guard_schema,
            model_id,
            expected_contract_status,
        )
        canonical_output_contract = _canonical_output_contract(
            candidate,
            result,
            model_id,
            expected_contract_status,
            expected_guard_schema,
        )
        physics_checks, energy_metric, physics_metrics = _physics_checks(
            result,
            model_id,
            physics_criteria,
            expected_contract_status,
            canonical_output_contract.get("recomputed_diagnostics"),
        )
        is_finest_level = index == len(results) - 1
        physics_checks_applied = _refinement_level_physics_checks(
            physics_checks,
            physics_metrics,
            is_finest=is_finest_level,
        )
        event_schema_valid, signature = _event_contract(
            result,
            expected_contract_status,
            model_id,
            expected_guard_schema,
            candidate,
        )
        event_signatures.append(signature)
        energy_metrics.append(energy_metric)
        level_dynamics = {
            field: _float_or_nan(physics_metrics.get(field))
            for field in dynamics_fields
        }
        for field, value in level_dynamics.items():
            dynamics_by_field[field].append(value)
        dynamics_ratios = [
            level_dynamics[field] / physics_criteria[field]
            for field in dynamics_fields
            if np.isfinite(level_dynamics[field])
            and np.isfinite(physics_criteria[field])
            and physics_criteria[field] > 0.0
        ]
        dynamics_metrics.append(
            max(dynamics_ratios)
            if len(dynamics_ratios) == len(dynamics_fields)
            else float("nan")
        )
        exact_numerical_status = (
            "SUCCESS_SINGLE_RUN"
            if expected_contract_status == ["COMPLETED"]
            else "SUCCESS_EVENT"
        )
        numerical_success = result.numerical_status == exact_numerical_status
        contract_expected = result.contract_status == expected_contract_status
        observation_contract = _observation_result_contract(
            candidate,
            result,
            model_id,
        )
        observation_valid = observation_contract["passed"]
        identity_checks = {
            field: result.metadata.get(field) == expected.get(field)
            for field in IDENTITY_FIELDS
        }
        identity_checks["source_stable_during_run"] = (
            result.metadata.get("source_tree_stable_during_run") is True
        )
        identity_checks["source_matches_study_start"] = (
            expected.get("source_tree_sha256")
            == study_start_identity.get("source_tree_sha256")
        )
        identity_checks["runtime_matches_study_start"] = (
            expected.get("runtime_versions")
            == study_start_identity.get("runtime_versions")
        )
        identity_checks["result_model_matches_requested"] = (
            result.model_id == model_id
        )
        identity_valid = all(identity_checks.values())
        level_passed = all(
            (
                numerical_success,
                contract_expected,
                observation_valid,
                event_schema_valid,
                guard_output_contract["passed"],
                canonical_output_contract["passed"],
                identity_valid,
                all(physics_checks_applied.values()),
            )
        )
        level_reports.append(
            {
                "level": index,
                "cache_reused": reused[index],
                "model_id": result.model_id,
                "contract_status": list(result.contract_status),
                "numerical_status": result.numerical_status,
                "tau": float(result.tau),
                "event_signature": signature,
                "expected_config_sha256": expected["config_sha256"],
                "actual_config_sha256": result.metadata.get("config_sha256"),
                "physical_input_sha256": result.metadata.get(
                    "physical_input_sha256"
                ),
                "numerical_config_sha256": result.metadata.get(
                    "numerical_config_sha256"
                ),
                "observation_input_sha256": result.metadata.get(
                    "observation_input_sha256"
                ),
                "source_tree_sha256": result.metadata.get(
                    "source_tree_sha256"
                ),
                "runtime_versions": result.metadata.get("runtime_versions"),
                "numerical_success_exact": bool(numerical_success),
                "contract_expected": bool(contract_expected),
                "observation_valid": bool(observation_valid),
                "observation_contract": observation_contract,
                "event_schema_valid": bool(event_schema_valid),
                "guard_output_contract": guard_output_contract,
                "canonical_output_contract": {
                    key: value
                    for key, value in canonical_output_contract.items()
                    if key != "recomputed_diagnostics"
                },
                "identity_checks": identity_checks,
                "identity_valid": bool(identity_valid),
                "physics_metrics": physics_metrics,
                "physics_checks": physics_checks,
                "physics_checks_applied": physics_checks_applied,
                "accuracy_threshold_role": (
                    "qualified_finest_level"
                    if is_finest_level
                    else "refinement_coarse_level_finite_trend_only"
                ),
                "passed": bool(level_passed),
            }
        )

    material_points = int(criterion.get("material_comparison_points", 0))
    comparisons = [
        _compare(
            coarse,
            fine,
            model_id=model_id,
            comparison_time_step=criterion["comparison_time_step"],
            material_comparison_points=material_points,
        )
        for coarse, fine in zip(results[:-1], results[1:])
    ]
    threshold_map = _metric_threshold_map(criterion, model_id)
    normalized_errors: list[float] = []
    for comparison in comparisons:
        ratios = []
        for metric, threshold in threshold_map.items():
            value = comparison.get(metric, float("nan"))
            ratios.append(
                float(value) / float(threshold)
                if _is_finite(value) and float(value) >= 0.0
                else float("nan")
            )
        comparison["maximum_normalized_metric"] = (
            max(ratios) if ratios and all(np.isfinite(ratios)) else float("nan")
        )
        normalized_errors.append(comparison["maximum_normalized_metric"])

    cauchy_decreasing = _decreases_or_at_floor(
        normalized_errors,
        criterion["cauchy_ratio_slack"],
        criterion["normalized_numerical_floor"],
    )
    energy_improves = _decreases_or_at_floor(
        energy_metrics,
        criterion["energy_ratio_slack"],
        criterion["energy_floor"],
    )
    dynamics_trend_checks = _dynamics_trend_checks(
        study_name,
        dynamics_by_field,
        physics_criteria,
        criterion["energy_ratio_slack"],
        criterion["normalized_numerical_floor"],
    )
    dynamics_improves = all(dynamics_trend_checks.values())
    finest = comparisons[-1] if comparisons else {}
    finest_thresholds = {
        metric: bool(
            _is_finite(finest.get(metric))
            and float(finest[metric]) <= threshold
        )
        for metric, threshold in threshold_map.items()
    }
    finest_thresholds["minimum_comparison_samples"] = bool(
        comparisons
        and all(
            comparison.get("comparison_sample_count", 0)
            >= criterion["minimum_comparison_samples"]
            for comparison in comparisons
        )
        and all(
            np.asarray(result.time).size
            >= criterion["minimum_comparison_samples"]
            for result in results
        )
    )
    if level_reports:
        finest_physics = level_reports[-1]["physics_checks"]
        for check_name in sorted(FINEST_ONLY_ACCURACY_CHECKS):
            finest_thresholds[f"finest_{check_name}"] = bool(
                finest_physics.get(check_name) is True
            )
    boundary_reaction_values: list[float] = []
    boundary_reaction_improves = True
    if model_id == "FWD-CABLE-1.0":
        boundary_reaction_values = [
            _float_or_nan(
                level["physics_metrics"].get(
                    "maximum_boundary_reaction_difference"
                )
            )
            for level in level_reports
        ]
        finest_boundary_reaction = (
            boundary_reaction_values[-1]
            if boundary_reaction_values
            else float("nan")
        )
        finest_thresholds["maximum_boundary_reaction_difference"] = bool(
            np.isfinite(finest_boundary_reaction)
            and finest_boundary_reaction
            <= criterion["max_finest_boundary_reaction_difference"]
        )
        if study_name == "space":
            boundary_reaction_improves = _decreases_or_at_floor(
                boundary_reaction_values,
                physics_criteria["boundary_reaction_ratio_slack"],
                physics_criteria["boundary_reaction_floor"],
            )

    event_set_stable = _event_sets_stable(results, model_id)
    guard_budget = _guard_error_budget(
        results[-2:],
        model_id,
        criterion["comparison_time_step"],
        criterion["guard_variation_safety_factor"],
        criterion["max_finest_event_time_difference"],
        expected_contract_status,
        expected_guard_schemas[-2:],
    )
    level_pass = all(level["passed"] for level in level_reports)
    passed = all(
        (
            level_pass,
            event_set_stable,
            guard_budget["passed"],
            cauchy_decreasing,
            energy_improves,
            dynamics_improves,
            boundary_reaction_improves,
            all(finest_thresholds.values()),
        )
    )
    observed_order = None
    if len(normalized_errors) == 2 and all(
        np.isfinite(value) and value > 0.0 for value in normalized_errors
    ):
        observed_order = float(
            np.log2(normalized_errors[0] / normalized_errors[1])
        )
    return {
        "passed": bool(passed),
        "criteria": criterion,
        "levels": level_reports,
        "comparisons": comparisons,
        "all_levels_pass": bool(level_pass),
        "event_set_stable": bool(event_set_stable),
        "guard_error_budget": guard_budget,
        "whole_state_cauchy_decreasing_or_at_floor": bool(cauchy_decreasing),
        "energy_metric_decreasing_or_at_floor": bool(energy_improves),
        "dynamics_defect_by_level": dynamics_by_field[
            "maximum_normalized_dynamics_defect"
        ],
        "dynamics_cumulative_defect_by_level": dynamics_by_field[
            "maximum_normalized_cumulative_dynamics_defect"
        ],
        "dynamics_absolute_defect_by_level": dynamics_by_field[
            "maximum_normalized_absolute_dynamics_defect"
        ],
        "maximum_normalized_dynamics_threshold_ratio_by_level": (
            dynamics_metrics
        ),
        "dynamics_defect_trend_checks": dynamics_trend_checks,
        "dynamics_defect_decreasing_or_at_floor": bool(dynamics_improves),
        "boundary_reaction_difference_by_level": boundary_reaction_values,
        "boundary_reaction_decreasing_or_at_floor": bool(
            boundary_reaction_improves
        ),
        "finest_threshold_checks": finest_thresholds,
        "observed_normalized_ratio_order": observed_order,
    }


def _fixed_torus_guard_names() -> set[str]:
    return {
        "R_ZERO",
        "T_A_ZERO",
        "T_B_ZERO",
        "T_LOWER_ZERO",
    }


def _expected_guard_schema(
    config: dict[str, Any], model_id: str
) -> dict[str, Any] | None:
    """Derive the exhaustive scalar guard registry from input, never output."""

    if model_id == "FWD-TORUS-1.0":
        physical = config.get("physical")
        if not isinstance(physical, dict):
            return None
        try:
            A = np.asarray(physical.get("A"), dtype=float)
            B = np.asarray(physical.get("B"), dtype=float)
            s_A = float(physical.get("s_A"))
            s_B = float(physical.get("s_B"))
            lower_length = float(physical.get("lower_length"))
            mass = float(physical.get("mass"))
            gravity = float(physical.get("g"))
            d = float(np.linalg.norm(B - A))
            x_C = (s_A * s_A - s_B * s_B) / (2.0 * d)
            a_A = x_C + d / 2.0
            h = float(np.sqrt(s_A * s_A - a_A * a_A))
        except (TypeError, ValueError, ZeroDivisionError, FloatingPointError):
            return None
        values = np.asarray(
            [*A.reshape(-1), *B.reshape(-1), s_A, s_B, lower_length, mass, gravity, d, h]
        )
        if A.shape != (3,) or B.shape != (3,) or not np.all(np.isfinite(values)):
            return None
        length_scale = max(
            s_A,
            s_B,
            lower_length,
            d,
            h,
            np.finfo(float).tiny,
        )
        tension_scale = max(mass * gravity, np.finfo(float).tiny)
        components = _fixed_torus_guard_names()
        return {
            "components": components,
            "scales": {
                "R_ZERO": float(length_scale),
                "T_A_ZERO": float(tension_scale),
                "T_B_ZERO": float(tension_scale),
                "T_LOWER_ZERO": float(tension_scale),
            },
            "minima": None,
            "aggregates": None,
            "custom_names": set(),
            "elements": None,
        }
    if model_id != "FWD-CABLE-1.0":
        return None
    numerics = config.get("numerics")
    elements = numerics.get("elements") if isinstance(numerics, dict) else None
    if not isinstance(elements, dict) or set(elements) != set(BRANCHES):
        return None
    normalized_elements: dict[str, int] = {}
    for branch in BRANCHES:
        count = elements.get(branch)
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or count <= 0
        ):
            return None
        normalized_elements[branch] = count
    inputs = config.get("inputs")
    guard_specs = inputs.get("exit_guards") if isinstance(inputs, dict) else None
    if not isinstance(guard_specs, list):
        return None
    custom_names: set[str] = set()
    for spec in guard_specs:
        name = spec.get("name") if isinstance(spec, dict) else None
        if not isinstance(name, str) or not name or name in custom_names:
            return None
        custom_names.add(name)
    physical = config.get("physical")
    branches = physical.get("branches") if isinstance(physical, dict) else None
    gravity = physical.get("g") if isinstance(physical, dict) else None
    lambda_min = physical.get("lambda_min") if isinstance(physical, dict) else None
    if (
        not isinstance(branches, dict)
        or set(branches) != set(BRANCHES)
        or not is_finite_number(gravity)
        or float(gravity) <= 0.0
        or not is_finite_number(lambda_min)
        or float(lambda_min) <= 0.0
    ):
        return None
    lengths: dict[str, float] = {}
    for branch in BRANCHES:
        spec = branches.get(branch)
        length = spec.get("L0") if isinstance(spec, dict) else None
        if not is_finite_number(length) or float(length) <= 0.0:
            return None
        lengths[branch] = float(length)
    characteristic_rate = float(
        np.sqrt(float(gravity) / min(lengths.values()))
    )
    components: set[str] = set()
    scales: dict[str, float] = {}
    minima: set[str] = set()
    for branch, count in normalized_elements.items():
        minima.add(f"lambda_min:{branch}")
        for element in range(count):
            name = f"LAMBDA_MIN:{branch}:element:{element}"
            components.add(name)
            scales[name] = max(1.0, float(lambda_min))
        branch_spec = branches[branch]
        domain = branch_spec.get("material_domain")
        if not isinstance(domain, dict):
            return None
        finite_lambda: list[float] = []
        finite_rate: list[float] = []
        for key, target in (
            ("lambda_lower", finite_lambda),
            ("lambda_upper", finite_lambda),
            ("rate_lower", finite_rate),
            ("rate_upper", finite_rate),
        ):
            value = domain.get(key)
            if value is None:
                continue
            if not is_finite_number(value):
                return None
            target.append(float(value))
        if len(finite_lambda) == 2:
            finite_lambda.append(abs(finite_lambda[1] - finite_lambda[0]))
        if len(finite_rate) == 2:
            finite_rate.append(abs(finite_rate[1] - finite_rate[0]))
        lambda_scale = max(
            1.0,
            float(lambda_min),
            *(abs(value) for value in finite_lambda),
        )
        rate_scale = max(
            characteristic_rate,
            *(abs(value) for value in finite_rate),
        )
        for boundary in (
            "lambda_lower",
            "lambda_upper",
            "rate_lower",
            "rate_upper",
        ):
            minima.add(f"material:{branch}:{boundary}")
            for element in range(count):
                name = (
                    "MATERIAL_DOMAIN:"
                    f"{branch}:{boundary}:element:{element}"
                )
                components.add(name)
                scales[name] = (
                    lambda_scale if boundary.startswith("lambda_") else rate_scale
                )
    default_length_scale = max(lengths.values())
    for spec in guard_specs:
        name = spec["name"]
        kind = spec.get("kind")
        if kind == "bob_plane":
            offset = spec.get("offset")
            if not is_finite_number(offset):
                return None
            scale = max(default_length_scale, abs(float(offset)))
        elif kind in ("bob_sphere_inside", "bob_sphere_outside"):
            radius = spec.get("radius")
            if not is_finite_number(radius) or float(radius) <= 0.0:
                return None
            scale = float(radius)
        elif kind == "node_distance":
            minimum = spec.get("minimum")
            if not is_finite_number(minimum) or float(minimum) < 0.0:
                return None
            scale = max(default_length_scale, float(minimum))
        else:
            return None
        trigger = f"EXIT_GUARD:{name}"
        components.add(trigger)
        scales[trigger] = float(scale)
    minima.update(f"custom:{name}" for name in custom_names)
    aggregates = {
        "lambda",
        "material_lambda",
        "material_rate",
        *(f"custom:{name}" for name in custom_names),
    }
    return {
        "components": components,
        "scales": scales,
        "minima": minima,
        "aggregates": aggregates,
        "custom_names": custom_names,
        "elements": normalized_elements,
    }


def _guard_output_contract(
    result: SimulationResult,
    schema: dict[str, Any] | None,
    model_id: str,
    expected_contract_status: list[str],
) -> dict[str, Any]:
    """Require exact guard coverage, including optional guards from input."""

    if not isinstance(schema, dict):
        return {
            "passed": False,
            "reason": "expected guard registry could not be derived",
        }
    components = schema.get("components")
    expected_scales = schema.get("scales")
    if (
        not isinstance(components, set)
        or not components
        or not isinstance(expected_scales, dict)
        or set(expected_scales) != components
    ):
        return {"passed": False, "reason": "empty expected guard registry"}
    diagnostics = result.diagnostics
    if not isinstance(diagnostics, dict):
        return {"passed": False, "reason": "diagnostics is not an object"}
    series = diagnostics.get("sampled_guard_component_series")
    scales = diagnostics.get("guard_component_scales")
    time = np.asarray(result.time)
    checks: dict[str, bool] = {
        "component_series_key_set_exact": isinstance(series, dict)
        and set(series) == components,
        "component_scale_key_set_exact": isinstance(scales, dict)
        and set(scales) == components,
    }
    checks["component_series_finite_and_aligned"] = _guard_series_valid(
        series,
        components,
        time,
        checks["component_series_key_set_exact"],
    )
    checks["component_scales_positive_finite"] = bool(
        isinstance(scales, dict)
        and checks["component_scale_key_set_exact"]
        and all(
            is_finite_number(scales[name]) and float(scales[name]) > 0.0
            for name in components
        )
    )
    checks["component_scales_match_input_registry"] = _guard_scales_match(
        scales,
        expected_scales,
        components,
    )
    if model_id == "FWD-CABLE-1.0":
        minima = diagnostics.get("sampled_guard_minima")
        aggregate = diagnostics.get("sampled_guard_series")
        expected_minima = schema.get("minima")
        expected_aggregates = schema.get("aggregates")
        expected_elements = schema.get("elements")
        checks["metadata_elements_exact"] = (
            result.metadata.get("elements") == expected_elements
        )
        checks["guard_minima_key_set_exact"] = bool(
            isinstance(minima, dict)
            and isinstance(expected_minima, set)
            and set(minima) == expected_minima
        )
        checks["guard_minima_finite"] = bool(
            checks["guard_minima_key_set_exact"]
            and isinstance(minima, dict)
            and isinstance(expected_minima, set)
            and all(is_finite_number(minima[name]) for name in expected_minima)
        )
        checks["aggregate_guard_series_key_set_exact"] = bool(
            isinstance(aggregate, dict)
            and isinstance(expected_aggregates, set)
            and set(aggregate) == expected_aggregates
        )
        checks["aggregate_guard_series_finite_and_aligned"] = (
            _guard_series_valid(
                aggregate,
                expected_aggregates,
                time,
                checks["aggregate_guard_series_key_set_exact"],
            )
        )
    checks["event_root_payload_complete"] = _event_guard_payload_complete(
        result,
        schema,
        model_id,
        expected_contract_status,
    )
    return {
        "passed": bool(checks) and all(checks.values()),
        "expected_component_count": len(components),
        "expected_components": sorted(components),
        "checks": checks,
    }


def _guard_series_valid(
    mapping: Any,
    expected: Any,
    time: np.ndarray,
    exact_keys: bool,
) -> bool:
    if not (
        isinstance(mapping, dict)
        and isinstance(expected, set)
        and exact_keys
        and time.ndim == 1
    ):
        return False
    try:
        for name in expected:
            array = np.asarray(mapping[name])
            if (
                array.shape != time.shape
                or array.dtype == object
                or not np.all(np.isfinite(np.asarray(array, dtype=float)))
            ):
                return False
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return True


def _guard_scales_match(
    observed: Any,
    expected: Any,
    names: set[str],
) -> bool:
    if not (
        isinstance(observed, dict)
        and isinstance(expected, dict)
        and set(observed) == names
        and set(expected) == names
    ):
        return False
    tolerance = 64.0 * np.finfo(float).eps
    return all(
        is_finite_number(observed[name])
        and is_finite_number(expected[name])
        and float(expected[name]) > 0.0
        and np.isclose(
            float(observed[name]),
            float(expected[name]),
            rtol=tolerance,
            atol=np.finfo(float).tiny,
        )
        for name in names
    )


def _event_guard_payload_complete(
    result: SimulationResult,
    schema: dict[str, Any],
    model_id: str,
    expected_contract_status: list[str],
) -> bool:
    if expected_contract_status == ["COMPLETED"]:
        return result.events == []
    if expected_contract_status != ["OUT_OF_SCOPE"] or len(result.events) != 1:
        return False
    event = result.events[0]
    if not isinstance(event, dict):
        return False
    expected = schema["components"]
    expected_scales = schema.get("scales")
    triggers = event.get("triggers")
    tolerances = event.get("guard_zero_tolerances")
    if not (
        isinstance(triggers, list)
        and bool(triggers)
        and all(isinstance(name, str) and name for name in triggers)
        and set(triggers).issubset(expected)
        and len(triggers) == len(set(triggers))
        and isinstance(tolerances, dict)
        and set(tolerances) == set(triggers)
        and isinstance(expected_scales, dict)
        and set(expected_scales) == expected
        and all(
            is_finite_number(tolerances[name])
            and _matches_canonical_zero_tolerance(
                tolerances[name], expected_scales[name]
            )
            for name in triggers
        )
    ):
        return False
    if model_id == "FWD-TORUS-1.0":
        values = event.get("guard_values")
        return bool(
            isinstance(values, dict)
            and set(values) == expected
            and all(is_finite_number(values[name]) for name in expected)
            and all(
                abs(float(values[name]))
                <= _canonical_zero_tolerance(expected_scales[name])
                for name in triggers
            )
        )
    if model_id != "FWD-CABLE-1.0":
        return False
    observed = _cable_event_guard_names(event.get("guard_components"), schema)
    return bool(
        observed == expected
        and all(
            (value := _event_trigger_value(event, name, model_id)) is not None
            and is_finite_number(value)
            and abs(float(value))
            <= _canonical_zero_tolerance(expected_scales[name])
            for name in triggers
        )
    )


def _canonical_zero_tolerance(scale: Any) -> float:
    if not is_finite_number(scale) or float(scale) <= 0.0:
        return float("nan")
    return 1024.0 * np.finfo(float).eps * float(scale)


def _matches_canonical_zero_tolerance(observed: Any, scale: Any) -> bool:
    if not is_finite_number(observed):
        return False
    expected = _canonical_zero_tolerance(scale)
    return bool(
        np.isfinite(expected)
        and expected > 0.0
        and np.isclose(
            float(observed),
            expected,
            rtol=64.0 * np.finfo(float).eps,
            atol=np.finfo(float).tiny,
        )
    )


def _cable_event_guard_names(
    components: Any, schema: dict[str, Any]
) -> set[str] | None:
    if not isinstance(components, dict) or set(components) != {
        "lambda",
        "material",
        "custom",
    }:
        return None
    elements = schema.get("elements")
    custom_names = schema.get("custom_names")
    if not isinstance(elements, dict) or not isinstance(custom_names, set):
        return None
    if not all(
        isinstance(components[name], dict)
        for name in ("lambda", "material", "custom")
    ):
        return None
    if set(components["lambda"]) != set(BRANCHES) or set(
        components["material"]
    ) != set(BRANCHES) or set(components["custom"]) != custom_names:
        return None
    names: set[str] = set()
    for branch in BRANCHES:
        count = elements[branch]
        try:
            values = np.asarray(components["lambda"][branch])
        except (TypeError, ValueError):
            return None
        if (
            values.shape != (count,)
            or values.dtype == object
            or not np.all(np.isfinite(values))
        ):
            return None
        names.update(
            f"LAMBDA_MIN:{branch}:element:{element}"
            for element in range(count)
        )
        boundaries = components["material"][branch]
        expected_boundaries = {
            "lambda_lower",
            "lambda_upper",
            "rate_lower",
            "rate_upper",
        }
        if not isinstance(boundaries, dict) or set(boundaries) != expected_boundaries:
            return None
        for boundary in expected_boundaries:
            try:
                boundary_values = np.asarray(boundaries[boundary])
            except (TypeError, ValueError):
                return None
            if (
                boundary_values.shape != (count,)
                or boundary_values.dtype == object
                or not np.all(np.isfinite(boundary_values))
            ):
                return None
            names.update(
                "MATERIAL_DOMAIN:"
                f"{branch}:{boundary}:element:{element}"
                for element in range(count)
            )
    if not all(
        is_finite_number(components["custom"][name])
        for name in custom_names
    ):
        return None
    names.update(f"EXIT_GUARD:{name}" for name in custom_names)
    return names


def _guard_error_budget(
    finest_two: list[SimulationResult],
    model_id: str,
    comparison_time_step: float,
    safety_factor: float,
    event_time_threshold: float,
    expected_contract_status: list[str],
    expected_guard_schemas: list[dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Propagate sampled guard variation and inter-level error to a margin budget.

    This is an empirical, explicitly reported bound: finest-level secant and
    curvature estimates are multiplied by a pre-frozen safety factor and added
    to the finest-two-level guard discrepancy.  It is stronger than comparing
    a raw minimum with an arbitrary tolerance, but remains numerical evidence,
    not interval arithmetic.
    """

    if len(finest_two) != 2:
        return {"passed": False, "applicable": True, "guards": {}}
    coarse, fine = finest_two
    if expected_contract_status == ["COMPLETED"]:
        excluded_roots: set[str] = set()
    elif expected_contract_status == ["OUT_OF_SCOPE"]:
        root_sets = [_physical_event_trigger_set(item) for item in finest_two]
        if any(root_set is None for root_set in root_sets) or not _event_sets_stable(
            finest_two, model_id
        ):
            return {
                "passed": False,
                "applicable": True,
                "guards": {},
                "reason": "malformed or unstable expected root set",
            }
        excluded_roots = set(root_sets[1] or ())
    else:
        return {
            "passed": False,
            "applicable": True,
            "guards": {},
            "reason": "unsupported expected physical status",
        }
    if expected_guard_schemas is None:
        return {
            "passed": False,
            "applicable": True,
            "guards": {},
            "reason": "input-derived guard registry was not supplied",
        }
    series_pairs = _aligned_guard_series(
        coarse,
        fine,
        model_id,
        expected_guard_schemas,
    )
    if not series_pairs or not excluded_roots.issubset(series_pairs):
        return {"passed": False, "applicable": True, "guards": {}}
    fine_expected_scales = expected_guard_schemas[1].get("scales")
    if not isinstance(fine_expected_scales, dict):
        return {
            "passed": False,
            "applicable": True,
            "guards": {},
            "reason": "missing input-derived guard scales",
        }
    end = min(float(coarse.tau), float(fine.tau))
    cluster_tolerances = [
        item.metadata.get("event_cluster_tolerance", 0.0)
        for item in finest_two
    ]
    if any(
        not is_finite_number(value) or float(value) < 0.0
        for value in cluster_tolerances
    ):
        return {
            "passed": False,
            "applicable": True,
            "guards": {},
            "reason": "missing or malformed event-cluster tolerance identity",
        }
    capture_width = (
        max(
            comparison_time_step,
            event_time_threshold,
            *(float(value) for value in cluster_tolerances),
        )
        if excluded_roots
        else 0.0
    )
    times = _comparison_times(
        coarse, fine, end, comparison_time_step
    )
    reports: dict[str, Any] = {}
    for name in sorted(series_pairs):
        coarse_source, fine_source, machine_scale, coarse_name = series_pairs[
            name
        ]
        triggered = name in excluded_roots
        evaluation_times = (
            times[
                times
                <= end
                - capture_width
                + 64.0 * np.finfo(float).eps * max(end, 1.0)
            ]
            if triggered
            else times
        )
        try:
            coarse_values = _time_interp(
                _strict_array(coarse_source), coarse.time, evaluation_times
            ).reshape(-1)
            fine_values = _time_interp(
                _strict_array(fine_source), fine.time, evaluation_times
            ).reshape(-1)
            full_fine_values = _time_interp(
                _strict_array(fine_source), fine.time, times
            ).reshape(-1)
        except (TypeError, ValueError):
            reports[name] = {"passed": False, "reason": "malformed series"}
            continue
        if evaluation_times.size < 3 or not (
            np.all(np.isfinite(coarse_values))
            and np.all(np.isfinite(fine_values))
            and np.all(np.isfinite(full_fine_values))
        ):
            reports[name] = {"passed": False, "reason": "insufficient series"}
            continue
        dt = np.diff(evaluation_times)
        first_secants = np.diff(fine_values) / dt
        if first_secants.size >= 2:
            midpoint_dt = 0.5 * (dt[:-1] + dt[1:])
            second_secants = np.diff(first_secants) / midpoint_dt
            curvature = float(np.max(np.abs(second_secants)))
        else:
            curvature = 0.0
        slope = float(np.max(np.abs(first_secants)))
        half_step_budget = safety_factor * (
            0.5 * comparison_time_step * slope
            + 0.125 * comparison_time_step**2 * curvature
        )
        interlevel_budget = float(
            np.max(np.abs(coarse_values - fine_values))
        )
        coarse_event_value = None
        fine_event_value = None
        if excluded_roots:
            coarse_event_value = _event_trigger_value(
                coarse.events[0], coarse_name, model_id
            )
            fine_event_value = _event_trigger_value(
                fine.events[0], name, model_id
            )
            if not (
                is_finite_number(coarse_event_value)
                and is_finite_number(fine_event_value)
            ):
                reports[name] = {
                    "passed": False,
                    "reason": "event state omits this scalar guard value",
                }
                continue
            interlevel_budget = max(
                interlevel_budget,
                abs(float(coarse_event_value) - float(fine_event_value)),
            )
        machine_budget = 1024.0 * np.finfo(float).eps * machine_scale
        total_budget = interlevel_budget + half_step_budget + machine_budget
        minimum = float(np.min(fine_values))
        if not triggered and fine_event_value is not None:
            minimum = min(minimum, float(fine_event_value))
        sampled_pre_root_nonnegative = bool(
            np.min(full_fine_values) >= -machine_budget
            and (
                fine_event_value is None
                or float(fine_event_value) >= -machine_budget
            )
        )
        root_residual_valid = True
        root_value = None
        root_tolerance = None
        if triggered:
            fine_event = fine.events[0]
            root_value = _event_trigger_value(fine_event, name, model_id)
            tolerances = fine_event.get("guard_zero_tolerances")
            reported_root_tolerance = (
                tolerances.get(name) if isinstance(tolerances, dict) else None
            )
            root_tolerance = _canonical_zero_tolerance(
                fine_expected_scales.get(name)
            )
            root_residual_valid = bool(
                is_finite_number(root_value)
                and _matches_canonical_zero_tolerance(
                    reported_root_tolerance,
                    fine_expected_scales.get(name),
                )
                and np.isfinite(root_tolerance)
                and root_tolerance > 0.0
                and abs(float(root_value)) <= root_tolerance
            )
        margin_passed = minimum > total_budget
        reports[name] = {
            "passed": bool(
                margin_passed
                and sampled_pre_root_nonnegative
                and root_residual_valid
            ),
            "scope": (
                "trigger_pre_capture_and_root"
                if triggered
                else "nontrigger_full_returned_window"
            ),
            "expected_root_component": bool(triggered),
            "capture_window_width": float(capture_width) if triggered else 0.0,
            "evaluation_end": float(evaluation_times[-1]),
            "minimum_finest_margin": minimum,
            "interlevel_guard_discrepancy": interlevel_budget,
            "sampled_maximum_guard_slope": slope,
            "sampled_maximum_guard_curvature": curvature,
            "within_step_variation_budget": half_step_budget,
            "machine_budget": machine_budget,
            "total_event_error_budget": total_budget,
            "sampled_pre_root_nonnegative": sampled_pre_root_nonnegative,
            "root_residual_valid": root_residual_valid,
            "root_value": root_value,
            "root_zero_tolerance": root_tolerance,
            "reported_root_zero_tolerance": (
                reported_root_tolerance if triggered else None
            ),
            "coarse_event_guard_value": coarse_event_value,
            "fine_event_guard_value": fine_event_value,
            "margin_to_budget_ratio": (
                minimum / total_budget if total_budget > 0.0 else float("inf")
            ),
        }
    return {
        "passed": bool(reports) and all(
            report.get("passed") is True for report in reports.values()
        ),
        "applicable": True,
        "method": (
            "each non-triggered scalar guard: finest-two-level discrepancy "
            "plus sampled secant/curvature variation with pre-frozen safety "
            "factor; only exact expected root components are excluded"
        ),
        "safety_factor": float(safety_factor),
        "trigger_capture_width": float(capture_width),
        "guards": reports,
        "limitation": "empirical propagated budget, not interval arithmetic",
    }


def _physical_event_trigger_set(
    result: SimulationResult,
) -> set[str] | None:
    if len(result.events) != 1 or not isinstance(result.events[0], dict):
        return None
    event = result.events[0]
    triggers = event.get("triggers")
    if (
        event.get("kind") != "physical_exit"
        or not isinstance(triggers, list)
        or not triggers
        or any(not isinstance(value, str) or not value for value in triggers)
        or len(triggers) != len(set(triggers))
    ):
        return None
    return set(triggers)


def _event_sets_stable(
    results: list[SimulationResult], model_id: str
) -> bool:
    """Compare event causes in a mesh-aware physical signature."""

    if not results:
        return False
    if all(result.events == [] for result in results):
        return True
    root_sets = [_physical_event_trigger_set(result) for result in results]
    if any(root_set is None for root_set in root_sets):
        return False
    if model_id == "FWD-TORUS-1.0":
        return all(root_set == root_sets[0] for root_set in root_sets[1:])
    if model_id != "FWD-CABLE-1.0":
        return False
    for coarse, fine, coarse_roots, fine_roots in zip(
        results[:-1], results[1:], root_sets[:-1], root_sets[1:]
    ):
        coarse_elements = coarse.metadata.get("elements")
        fine_elements = fine.metadata.get("elements")
        if not isinstance(coarse_elements, dict) or not isinstance(
            fine_elements, dict
        ):
            return False
        mapped_fine = {
            _coarse_guard_name(name, coarse_elements, fine_elements)
            for name in fine_roots or ()
        }
        if None in mapped_fine or mapped_fine != coarse_roots:
            return False
    return True


def _aligned_guard_series(
    coarse: SimulationResult,
    fine: SimulationResult,
    model_id: str,
    expected_guard_schemas: list[dict[str, Any] | None],
) -> dict[str, tuple[Any, Any, float, str]] | None:
    """Align every fine scalar guard with the same material location/coarse guard."""

    coarse_series = coarse.diagnostics.get("sampled_guard_component_series")
    fine_series = fine.diagnostics.get("sampled_guard_component_series")
    coarse_scales = coarse.diagnostics.get("guard_component_scales")
    fine_scales = fine.diagnostics.get("guard_component_scales")
    if not all(
        isinstance(value, dict)
        for value in (coarse_series, fine_series, coarse_scales, fine_scales)
    ) or not fine_series or len(expected_guard_schemas) != 2:
        return None
    coarse_schema, fine_schema = expected_guard_schemas
    if not isinstance(coarse_schema, dict) or not isinstance(
        fine_schema, dict
    ):
        return None
    coarse_expected = coarse_schema.get("components")
    fine_expected = fine_schema.get("components")
    coarse_expected_scales = coarse_schema.get("scales")
    fine_expected_scales = fine_schema.get("scales")
    if not isinstance(coarse_expected, set) or not isinstance(
        fine_expected, set
    ):
        return None
    if not (
        set(coarse_series) == coarse_expected
        and set(coarse_scales) == coarse_expected
        and set(fine_series) == fine_expected
        and set(fine_scales) == fine_expected
        and _guard_scales_match(
            coarse_scales, coarse_expected_scales, coarse_expected
        )
        and _guard_scales_match(
            fine_scales, fine_expected_scales, fine_expected
        )
    ):
        return None
    pairs: dict[str, tuple[Any, Any, float, str]] = {}
    if model_id == "FWD-TORUS-1.0":
        if coarse_expected != fine_expected:
            return None
        for name in fine_series:
            scale = fine_expected_scales.get(name)
            if not is_finite_number(scale) or float(scale) <= 0.0:
                return None
            pairs[name] = (
                coarse_series[name],
                fine_series[name],
                float(scale),
                name,
            )
        return pairs
    if model_id != "FWD-CABLE-1.0":
        return None
    coarse_elements = coarse.metadata.get("elements")
    fine_elements = fine.metadata.get("elements")
    if not isinstance(coarse_elements, dict) or not isinstance(
        fine_elements, dict
    ):
        return None
    for fine_name, fine_values in fine_series.items():
        coarse_name = _coarse_guard_name(
            fine_name, coarse_elements, fine_elements
        )
        scale = fine_expected_scales.get(fine_name)
        if (
            coarse_name is None
            or coarse_name not in coarse_series
            or not is_finite_number(scale)
            or float(scale) <= 0.0
        ):
            return None
        pairs[fine_name] = (
            coarse_series[coarse_name],
            fine_values,
            float(scale),
            coarse_name,
        )
    return pairs


def _coarse_guard_name(
    fine_name: Any,
    coarse_elements: dict[str, Any],
    fine_elements: dict[str, Any],
) -> str | None:
    if not isinstance(fine_name, str):
        return None
    if fine_name.startswith("EXIT_GUARD:"):
        return fine_name
    parts = fine_name.split(":")
    if (
        len(parts) == 4
        and parts[0] == "LAMBDA_MIN"
        and parts[2] == "element"
    ):
        branch, element_text = parts[1], parts[3]
        prefix = f"LAMBDA_MIN:{branch}:element"
    elif (
        len(parts) == 5
        and parts[0] == "MATERIAL_DOMAIN"
        and parts[3] == "element"
    ):
        branch, boundary, element_text = parts[1], parts[2], parts[4]
        prefix = f"MATERIAL_DOMAIN:{branch}:{boundary}:element"
    else:
        return None
    coarse_count = coarse_elements.get(branch)
    fine_count = fine_elements.get(branch)
    try:
        fine_index = int(element_text)
    except (TypeError, ValueError):
        return None
    if (
        not isinstance(coarse_count, int)
        or isinstance(coarse_count, bool)
        or not isinstance(fine_count, int)
        or isinstance(fine_count, bool)
        or coarse_count <= 0
        or fine_count <= 0
        or fine_index < 0
        or fine_index >= fine_count
    ):
        return None
    material_midpoint = (fine_index + 0.5) / fine_count
    coarse_index = min(int(np.floor(material_midpoint * coarse_count)), coarse_count - 1)
    return f"{prefix}:{coarse_index}"


def _canonical_output_contract(
    config: dict[str, Any],
    result: SimulationResult,
    model_id: str,
    expected_status: list[str],
    guard_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate a complete result against input-derived canonical quantities.

    This gate deliberately does not accept self-reported shapes, topology,
    derived fields, invariant summaries, or returned intervals as evidence.
    Every check below is rebuilt from the candidate input and canonical state.
    """

    horizon = _horizon_contract(config, result, expected_status)
    if model_id == "FWD-TORUS-1.0":
        trajectory = _torus_trajectory_contract(
            config, result, expected_status, guard_schema
        )
    elif model_id == "FWD-CABLE-1.0":
        trajectory = _cable_trajectory_contract(
            config, result, expected_status, guard_schema
        )
    else:
        trajectory = {
            "passed": False,
            "checks": {"known_model": False},
            "recomputed_diagnostics": None,
        }
    return {
        "passed": bool(horizon["passed"] and trajectory["passed"]),
        "horizon": horizon,
        "trajectory": {
            key: value
            for key, value in trajectory.items()
            if key != "recomputed_diagnostics"
        },
        "recomputed_diagnostics": trajectory.get("recomputed_diagnostics"),
    }


def _horizon_contract(
    config: dict[str, Any],
    result: SimulationResult,
    expected_status: list[str],
) -> dict[str, Any]:
    physical = config.get("physical")
    T = physical.get("T") if isinstance(physical, dict) else None
    numerics = config.get("numerics")
    output_dt = (
        numerics.get("output_dt") if isinstance(numerics, dict) else None
    )
    time = np.asarray(result.time)
    common = {
        "candidate_T_positive_finite": bool(
            is_finite_number(T) and float(T) > 0.0
        ),
        "tau_finite": bool(is_finite_number(result.tau)),
        "output_dt_positive_finite": bool(
            is_finite_number(output_dt) and float(output_dt) > 0.0
        ),
        "time_is_finite_strict_grid": bool(
            time.ndim == 1
            and time.dtype != object
            and time.size > 0
            and np.all(np.isfinite(time))
            and float(time[0]) == 0.0
            and (time.size < 2 or np.all(np.diff(time) > 0.0))
        ),
    }
    if not common["candidate_T_positive_finite"]:
        return {"passed": False, "checks": common}
    target = float(T)
    if expected_status == ["COMPLETED"]:
        expected_time = (
            _output_times(target, float(output_dt), include_end=True)
            if common["output_dt_positive_finite"]
            else np.empty(0)
        )
        checks = {
            **common,
            "tau_equals_candidate_T": bool(
                common["tau_finite"] and float(result.tau) == target
            ),
            "returned_interval_exact": result.returned_interval
            == f"[0,{target}]",
            "time_ends_at_candidate_T": bool(
                common["time_is_finite_strict_grid"]
                and float(time[-1]) == target
            ),
            "no_samples_after_tau": bool(
                common["time_is_finite_strict_grid"]
                and np.all(time <= target)
            ),
            "output_grid_matches_candidate_output_dt": _array_matches(
                time,
                expected_time,
                scale=max(target, float(output_dt))
                if common["output_dt_positive_finite"]
                else 1.0,
            ),
        }
    elif expected_status == ["OUT_OF_SCOPE"]:
        tau = float(result.tau) if common["tau_finite"] else float("nan")
        event_time = (
            result.events[0].get("time")
            if len(result.events) == 1 and isinstance(result.events[0], dict)
            else None
        )
        expected_time = (
            _output_times(tau, float(output_dt), include_end=False)
            if common["output_dt_positive_finite"] and np.isfinite(tau)
            else np.empty(0)
        )
        checks = {
            **common,
            "tau_in_candidate_window": bool(
                np.isfinite(tau) and 0.0 < tau <= target
            ),
            "returned_interval_exact": result.returned_interval
            == f"[0,{tau})",
            "half_open_samples_strictly_before_tau": bool(
                common["time_is_finite_strict_grid"] and np.all(time < tau)
            ),
            "event_time_equals_tau": bool(
                is_finite_number(event_time) and float(event_time) == tau
            ),
            "output_grid_matches_candidate_output_dt": _array_matches(
                time,
                expected_time,
                scale=max(abs(tau), float(output_dt))
                if common["output_dt_positive_finite"] and np.isfinite(tau)
                else 1.0,
            ),
        }
    else:
        checks = {**common, "supported_expected_status": False}
    return {"passed": bool(checks) and all(checks.values()), "checks": checks}


def _array_matches(
    observed: Any,
    expected: Any,
    *,
    scale: float | None = None,
    boolean: bool = False,
) -> bool:
    try:
        left = np.asarray(observed)
        right = np.asarray(expected)
    except (TypeError, ValueError, OverflowError):
        return False
    if left.shape != right.shape or left.dtype == object or right.dtype == object:
        return False
    if boolean:
        return bool(left.dtype == bool and right.dtype == bool and np.array_equal(left, right))
    try:
        left_float = np.asarray(left, dtype=float)
        right_float = np.asarray(right, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return False
    if not (
        np.all(np.isfinite(left_float)) and np.all(np.isfinite(right_float))
    ):
        return False
    if scale is None:
        magnitude = (
            float(np.max(np.abs(right_float))) if right_float.size else 0.0
        )
        scale = max(magnitude, np.finfo(float).tiny)
    if not is_finite_number(scale) or float(scale) <= 0.0:
        return False
    return bool(
        np.allclose(
            left_float,
            right_float,
            rtol=2.0e-11,
            atol=2.0e-12 * float(scale),
        )
    )


def _scalar_matches(observed: Any, expected: Any, *, scale: float) -> bool:
    return _array_matches(observed, expected, scale=scale)


def _torus_trajectory_contract(
    config: dict[str, Any],
    result: SimulationResult,
    expected_status: list[str],
    guard_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    issues, params = validate_torus_config(config)
    if issues or params is None or not isinstance(guard_schema, dict):
        return {
            "passed": False,
            "checks": {"candidate_revalidated": False},
            "recomputed_diagnostics": None,
        }
    time = np.asarray(result.time)
    state = result.state
    derived = result.derived
    expected_names = {
        "J",
        "r_m",
        "R",
        "T_A",
        "T_B",
        "T_lower",
        "E_torus",
        "r_perp",
        "Q_T",
        "torus_unsquared_residual",
        "physical_branch_residual",
    }
    checks: dict[str, bool] = {
        "state_key_set_exact": isinstance(state, dict)
        and set(state) == {"X_torus"},
        "derived_key_set_exact": isinstance(derived, dict)
        and set(derived) == expected_names,
    }
    try:
        states = np.asarray(state.get("X_torus"))
    except (AttributeError, TypeError, ValueError):
        states = np.empty((0, 0))
    checks["state_shape_and_finiteness"] = bool(
        time.ndim == 1
        and states.shape == (time.size, 4)
        and states.dtype != object
        and np.all(np.isfinite(states))
    )
    if not checks["state_shape_and_finiteness"]:
        return {
            "passed": False,
            "checks": checks,
            "recomputed_diagnostics": None,
        }
    checks["initial_state_matches_candidate"] = _array_matches(
        states[0], params.initial_state, scale=1.0
    )
    canonical = torus_derived(params, np.asarray(states, dtype=float))
    length_scale = max(
        params.s_A,
        params.s_B,
        params.lower_length,
        params.d,
        params.h,
        np.finfo(float).tiny,
    )
    force_scale = max(params.mass * params.g, np.finfo(float).tiny)
    energy_scale_base = max(
        params.mass * params.g * params.lower_length,
        np.finfo(float).tiny,
    )
    field_scales = {
        "J": length_scale,
        "r_m": length_scale,
        "R": length_scale,
        "T_A": force_scale,
        "T_B": force_scale,
        "T_lower": force_scale,
        "E_torus": energy_scale_base,
        "r_perp": length_scale,
        "Q_T": length_scale * length_scale,
        "torus_unsquared_residual": length_scale * length_scale,
        "physical_branch_residual": length_scale * length_scale,
    }
    for name in sorted(expected_names):
        expected_shape = (time.size, 3) if name in {"J", "r_m"} else (time.size,)
        observed = derived.get(name) if isinstance(derived, dict) else None
        checks[f"derived_{name}_shape"] = bool(
            np.asarray(observed).shape == expected_shape
        )
        checks[f"derived_{name}_matches_state"] = _array_matches(
            observed,
            canonical[name],
            scale=field_scales[name],
        )

    energy = np.asarray(canonical["E_torus"], dtype=float)
    energy_variation = (
        float(np.max(np.abs(energy - energy[0]))) if energy.size else 0.0
    )
    energy_scale = max(energy_scale_base, energy_variation, np.finfo(float).tiny)
    defect_time = np.asarray(time, dtype=float)
    defect_states = np.asarray(states, dtype=float)
    if expected_status == ["OUT_OF_SCOPE"]:
        event_state = (
            result.events[0].get("state_left")
            if len(result.events) == 1 and isinstance(result.events[0], dict)
            else None
        )
        try:
            event_state_array = np.asarray(event_state, dtype=float)
        except (TypeError, ValueError, OverflowError):
            event_state_array = np.empty(0)
        output_dt = config.get("numerics", {}).get("output_dt")
        gap = float(result.tau) - float(time[-1])
        checks["event_terminal_gap_bounded"] = bool(
            event_state_array.shape == (4,)
            and np.all(np.isfinite(event_state_array))
            and is_finite_number(output_dt)
            and gap > 0.0
            and gap
            <= float(output_dt)
            + 64.0 * np.finfo(float).eps * max(abs(float(result.tau)), float(output_dt))
        )
        if checks["event_terminal_gap_bounded"]:
            defect_time = np.append(defect_time, float(result.tau))
            defect_states = np.vstack((defect_states, event_state_array))
    else:
        checks["event_terminal_gap_bounded"] = True
    dynamics = _torus_dynamics_defect(
        params,
        defect_time,
        defect_states,
    )
    recomputed = {
        "energy_scale": float(energy_scale),
        "max_absolute_energy_drift": float(energy_variation),
        "max_relative_energy_drift": float(energy_variation / energy_scale),
        "max_abs_torus_unsquared_residual": float(
            np.max(np.abs(canonical["torus_unsquared_residual"]))
        ),
        "max_abs_physical_branch_residual": float(
            np.max(np.abs(canonical["physical_branch_residual"]))
        ),
        "min_Q_T": float(np.min(canonical["Q_T"])),
        "minimum_R": float(np.min(canonical["R"])),
        "minimum_tension": min(
            float(np.min(canonical[name]))
            for name in ("T_A", "T_B", "T_lower")
        ),
        **dynamics,
    }
    diagnostic_scales = {
        "energy_scale": energy_scale,
        "max_absolute_energy_drift": energy_scale,
        "max_relative_energy_drift": 1.0,
        "max_abs_torus_unsquared_residual": length_scale * length_scale,
        "max_abs_physical_branch_residual": length_scale * length_scale,
        "min_Q_T": length_scale * length_scale,
    }
    diagnostics = result.diagnostics if isinstance(result.diagnostics, dict) else {}
    for name, scale in diagnostic_scales.items():
        checks[f"diagnostic_{name}_recomputed"] = _scalar_matches(
            diagnostics.get(name), recomputed[name], scale=scale
        )
    series = diagnostics.get("sampled_guard_component_series")
    expected_series = {
        "R_ZERO": canonical["R"],
        "T_A_ZERO": canonical["T_A"],
        "T_B_ZERO": canonical["T_B"],
        "T_LOWER_ZERO": canonical["T_lower"],
    }
    checks["guard_series_matches_state"] = bool(
        isinstance(series, dict)
        and set(series) == set(expected_series)
        and all(
            _array_matches(
                series[name],
                values,
                scale=(length_scale if name == "R_ZERO" else force_scale),
            )
            for name, values in expected_series.items()
        )
    )
    checks["event_left_limit_matches_state"] = _event_left_limit_consistent(
        config,
        result,
        "FWD-TORUS-1.0",
        expected_status,
        guard_schema,
    )
    return {
        "passed": bool(checks) and all(checks.values()),
        "checks": checks,
        "recomputed_diagnostics": recomputed,
    }


def _torus_dynamics_defect(
    params: Any, time: np.ndarray, states: np.ndarray
) -> dict[str, float]:
    if time.size < 2:
        return {
            "maximum_normalized_dynamics_defect": 0.0,
            "rms_normalized_dynamics_defect": 0.0,
            "maximum_normalized_cumulative_dynamics_defect": 0.0,
            "maximum_normalized_absolute_dynamics_defect": 0.0,
        }
    rhs = np.asarray(
        [torus_rhs(params, float(t), state) for t, state in zip(time, states)],
        dtype=float,
    )
    step = np.diff(time)
    midpoint_state = (
        0.5 * (states[1:] + states[:-1])
        + step[:, None] / 8.0 * (rhs[:-1] - rhs[1:])
    )
    midpoint_time = 0.5 * (time[1:] + time[:-1])
    midpoint_rhs = np.asarray(
        [
            torus_rhs(params, float(t), state)
            for t, state in zip(midpoint_time, midpoint_state)
        ],
        dtype=float,
    )
    defect = (
        states[1:]
        - states[:-1]
        - step[:, None] / 6.0
        * (rhs[:-1] + 4.0 * midpoint_rhs + rhs[1:])
    )
    rate_scale = max(
        np.sqrt(params.g / params.lower_length), np.finfo(float).tiny
    )
    acceleration_scale = max(rate_scale * rate_scale, np.finfo(float).tiny)
    rate_normalized = np.column_stack(
        (
            defect[:, :2] / (step[:, None] * rate_scale),
            defect[:, 2:] / (step[:, None] * acceleration_scale),
        )
    )
    signed_cumulative = np.cumsum(defect, axis=0)
    cumulative_normalized = np.column_stack(
        (
            signed_cumulative[:, :2],
            signed_cumulative[:, 2:] / rate_scale,
        )
    )
    absolute_normalized = np.column_stack(
        (
            np.cumsum(np.abs(defect[:, :2]), axis=0),
            np.cumsum(np.abs(defect[:, 2:]), axis=0) / rate_scale,
        )
    )
    return {
        "maximum_normalized_dynamics_defect": float(
            np.max(np.abs(rate_normalized))
        ),
        "rms_normalized_dynamics_defect": float(
            np.sqrt(np.mean(rate_normalized * rate_normalized))
        ),
        "maximum_normalized_cumulative_dynamics_defect": float(
            np.max(np.abs(cumulative_normalized))
        ),
        "maximum_normalized_absolute_dynamics_defect": float(
            np.max(absolute_normalized)
        ),
    }


def _expected_cable_topology(
    config: dict[str, Any],
) -> dict[str, Any] | None:
    numerics = config.get("numerics")
    elements = numerics.get("elements") if isinstance(numerics, dict) else None
    if not isinstance(elements, dict) or set(elements) != set(BRANCHES):
        return None
    counts: dict[str, int] = {}
    for branch in BRANCHES:
        value = elements.get(branch)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 1
        ):
            return None
        counts[branch] = value
    node_ids = ["support_A", "support_B", "junction", "bob"]
    node_index = {name: index for index, name in enumerate(node_ids)}
    branch_nodes: dict[str, np.ndarray] = {}
    for branch in BRANCHES:
        if branch == "A":
            start, end = node_index["support_A"], node_index["junction"]
        elif branch == "B":
            start, end = node_index["support_B"], node_index["junction"]
        else:
            start, end = node_index["junction"], node_index["bob"]
        internal: list[int] = []
        for local in range(1, counts[branch]):
            label = f"{branch}:node:{local}"
            node_index[label] = len(node_ids)
            node_ids.append(label)
            internal.append(node_index[label])
        branch_nodes[branch] = np.asarray([start, *internal, end], dtype=int)
    return {
        "elements": counts,
        "node_ids": node_ids,
        "node_index": node_index,
        "branch_nodes": branch_nodes,
        "node_count": sum(counts.values()) + 1,
    }


def _assemble_cable_mass(
    physical: Any, topology: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray]:
    node_count = topology["node_count"]
    mass = np.zeros((node_count, node_count), dtype=float)
    gravity_weights = np.zeros(node_count, dtype=float)
    for branch in BRANCHES:
        parameters = physical.branches[branch]
        count = topology["elements"][branch]
        nodes = topology["branch_nodes"][branch]
        h = parameters.L0 / count
        local = parameters.mu * h / 6.0 * np.asarray(
            [[2.0, 1.0], [1.0, 2.0]]
        )
        for left, right in zip(nodes[:-1], nodes[1:]):
            indices = np.asarray([left, right], dtype=int)
            mass[np.ix_(indices, indices)] += local
            gravity_weights[indices] += parameters.mu * h / 2.0
    junction = topology["node_index"]["junction"]
    bob = topology["node_index"]["bob"]
    mass[junction, junction] += physical.junction_mass
    mass[bob, bob] += physical.bob_mass
    gravity_weights[junction] += physical.junction_mass
    gravity_weights[bob] += physical.bob_mass
    return mass, gravity_weights


def _canonical_cable_kinematics(
    physical: Any,
    topology: dict[str, Any],
    positions: np.ndarray,
    velocities: np.ndarray,
) -> dict[str, dict[str, np.ndarray]]:
    branches: dict[str, dict[str, np.ndarray]] = {}
    for branch in BRANCHES:
        nodes = topology["branch_nodes"][branch]
        count = topology["elements"][branch]
        parameters = physical.branches[branch]
        h = parameters.L0 / count
        delta_r = positions[:, nodes[1:], :] - positions[:, nodes[:-1], :]
        delta_v = velocities[:, nodes[1:], :] - velocities[:, nodes[:-1], :]
        lengths = np.linalg.norm(delta_r, axis=2)
        if np.any(lengths <= 100.0 * np.finfo(float).tiny):
            raise FloatingPointError(f"zero cable tangent in {branch}")
        tangent = delta_r / lengths[:, :, None]
        stretch = lengths / h
        rate = np.sum(tangent * delta_v, axis=2) / h
        elastic, viscous, tension = tension_components(
            stretch,
            rate,
            EA=parameters.EA,
            Ca=parameters.Ca,
            delta=parameters.delta,
        )
        branches[branch] = {
            "lambda": np.asarray(stretch, dtype=float),
            "lambda_dot": np.asarray(rate, dtype=float),
            "tangent": np.asarray(tangent, dtype=float),
            "N_elastic": np.asarray(elastic, dtype=float),
            "N_viscous": np.asarray(viscous, dtype=float),
            "N": np.asarray(tension, dtype=float),
            "active": np.asarray(tension > 0.0, dtype=bool),
            "slack": np.asarray(tension == 0.0, dtype=bool),
            "loaded_length": np.sum(h * stretch, axis=1),
            "f_drag_center": np.zeros_like(tangent),
        }
    return branches


def _canonical_cable_guard_data(
    physical: Any,
    topology: dict[str, Any],
    time: np.ndarray,
    positions: np.ndarray,
    branches: dict[str, dict[str, np.ndarray]],
) -> dict[str, Any]:
    component_series: dict[str, np.ndarray] = {}
    minima: dict[str, float] = {}
    aggregate: dict[str, np.ndarray] = {
        "lambda": np.full(time.size, np.inf),
        "material_lambda": np.full(time.size, np.inf),
        "material_rate": np.full(time.size, np.inf),
    }
    for branch in BRANCHES:
        stretch = branches[branch]["lambda"]
        rate = branches[branch]["lambda_dot"]
        lambda_margin = stretch - physical.lambda_min
        aggregate["lambda"] = np.minimum(
            aggregate["lambda"], np.min(lambda_margin, axis=1)
        )
        minima[f"lambda_min:{branch}"] = float(np.min(lambda_margin))
        margins = physical.branches[branch].material_domain.component_margins(
            stretch, rate
        )
        for element in range(topology["elements"][branch]):
            component_series[
                f"LAMBDA_MIN:{branch}:element:{element}"
            ] = lambda_margin[:, element]
        for boundary, values in margins.items():
            family = (
                "material_lambda"
                if boundary.startswith("lambda_")
                else "material_rate"
            )
            aggregate[family] = np.minimum(
                aggregate[family], np.min(values, axis=1)
            )
            minima[f"material:{branch}:{boundary}"] = float(np.min(values))
            for element in range(topology["elements"][branch]):
                component_series[
                    "MATERIAL_DOMAIN:"
                    f"{branch}:{boundary}:element:{element}"
                ] = np.asarray(values[:, element], dtype=float)
    for guard in physical.guards:
        values = np.asarray(
            [
                guard.evaluate(positions[index], float(t_value), topology["node_index"])
                for index, t_value in enumerate(time)
            ],
            dtype=float,
        )
        component_series[f"EXIT_GUARD:{guard.name}"] = values
        aggregate[f"custom:{guard.name}"] = values
        minima[f"custom:{guard.name}"] = float(np.min(values))
    return {
        "component_series": component_series,
        "aggregate": aggregate,
        "minima": minima,
    }


def _recompute_cable_output(
    config: dict[str, Any],
    physical: Any,
    topology: dict[str, Any],
    time: np.ndarray,
    positions: np.ndarray,
    velocities: np.ndarray,
    *,
    compute_dynamics: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Rebuild every canonical cable field from node state and frozen input."""

    sample_count = time.size
    branches = _canonical_cable_kinematics(
        physical, topology, positions, velocities
    )
    mass, gravity_weights = _assemble_cable_mass(physical, topology)
    node_count = topology["node_count"]
    applied = np.broadcast_to(
        gravity_weights[None, :, None] * physical.g * physical.e_z,
        (sample_count, node_count, 3),
    ).copy()
    internal = np.zeros_like(applied)
    bob = topology["node_index"]["bob"]
    junction = topology["node_index"]["junction"]
    applied[:, bob, :] -= (
        physical.rho_air
        * physical.bob_volume
        * physical.g
        * physical.e_z
    )
    scalar = {
        name: np.zeros(sample_count, dtype=float)
        for name in (
            "T_kin",
            "V_g",
            "V_buoy",
            "V_ax",
            "E_F",
            "D_ax",
            "D_string",
            "D_b",
            "P_base",
            "P_air",
            "P_ext",
        )
    }
    vector = {
        name: np.zeros((sample_count, 3), dtype=float)
        for name in ("F_drag_b", "R_A", "R_B")
    }
    quadrature_order = int(config["numerics"].get("quadrature_order", 3))
    raw_points, raw_weights = np.polynomial.legendre.leggauss(quadrature_order)
    gauss_xi = 0.5 * (raw_points + 1.0)
    gauss_weights = 0.5 * raw_weights
    for branch in BRANCHES:
        parameters = physical.branches[branch]
        count = topology["elements"][branch]
        nodes = topology["branch_nodes"][branch]
        h = parameters.L0 / count
        tension = branches[branch]["N"]
        tangent = branches[branch]["tangent"]
        elastic = branches[branch]["N_elastic"]
        rate = branches[branch]["lambda_dot"]
        stretch = branches[branch]["lambda"]
        force = tension[:, :, None] * tangent
        internal[:, nodes[:-1], :] -= force
        internal[:, nodes[1:], :] += force
        scalar["D_ax"] += np.sum(h * (tension - elastic) * rate, axis=1)
        scalar["V_ax"] += np.sum(
            parameters.EA
            * h
            * activation_primitive(stretch - 1.0, parameters.delta),
            axis=1,
        )
        for element, (left, right) in enumerate(zip(nodes[:-1], nodes[1:])):
            for xi_local, weight in zip(gauss_xi, gauss_weights):
                shape = np.asarray([1.0 - xi_local, xi_local])
                xi_global = (element + xi_local) / count
                for index, t_value in enumerate(time):
                    r_q = (
                        shape[0] * positions[index, left]
                        + shape[1] * positions[index, right]
                    )
                    v_q = (
                        shape[0] * velocities[index, left]
                        + shape[1] * velocities[index, right]
                    )
                    air_q = physical.air.value(r_q, float(t_value))
                    relative = v_q - air_q
                    local_tangent = tangent[index, element]
                    parallel = local_tangent * float(local_tangent @ relative)
                    perpendicular = relative - parallel
                    drag = (
                        -parameters.c_parallel * parallel
                        -parameters.c_perp * perpendicular
                        -parameters.d_parallel * np.linalg.norm(parallel) * parallel
                        -parameters.d_perp
                        * np.linalg.norm(perpendicular)
                        * perpendicular
                    )
                    external = physical.distributed_forces[branch].value(
                        float(xi_global), float(t_value)
                    )
                    nodal = h * float(weight) * shape
                    applied[index, left] += nodal[0] * (drag + external)
                    applied[index, right] += nodal[1] * (drag + external)
                    scalar["D_string"][index] += h * float(weight) * (
                        -float(drag @ relative)
                    )
                    scalar["P_air"][index] += h * float(weight) * float(
                        drag @ air_q
                    )
                    scalar["P_ext"][index] += h * float(weight) * float(
                        external @ v_q
                    )
            for index, t_value in enumerate(time):
                r_center = 0.5 * (
                    positions[index, left] + positions[index, right]
                )
                v_center = 0.5 * (
                    velocities[index, left] + velocities[index, right]
                )
                air_center = physical.air.value(r_center, float(t_value))
                relative = v_center - air_center
                local_tangent = tangent[index, element]
                parallel = local_tangent * float(local_tangent @ relative)
                perpendicular = relative - parallel
                branches[branch]["f_drag_center"][index, element] = (
                    -parameters.c_parallel * parallel
                    -parameters.c_perp * perpendicular
                    -parameters.d_parallel * np.linalg.norm(parallel) * parallel
                    -parameters.d_perp
                    * np.linalg.norm(perpendicular)
                    * perpendicular
                )

    for index, t_value in enumerate(time):
        junction_force = physical.junction_force.value(float(t_value))
        bob_force = physical.bob_force.value(float(t_value))
        applied[index, junction] += junction_force
        applied[index, bob] += bob_force
        air_b = physical.air.value(positions[index, bob], float(t_value))
        relative_b = velocities[index, bob] - air_b
        drag_b = (
            -physical.bob_c1 * relative_b
            - physical.bob_c2 * np.linalg.norm(relative_b) * relative_b
        )
        vector["F_drag_b"][index] = drag_b
        applied[index, bob] += drag_b
        scalar["D_b"][index] = -float(drag_b @ relative_b)
        scalar["P_air"][index] += float(drag_b @ air_b)
        scalar["P_ext"][index] += float(
            junction_force @ velocities[index, junction]
            + bob_force @ velocities[index, bob]
        )

    for coordinate in range(3):
        scalar["T_kin"] += 0.5 * np.einsum(
            "ti,ij,tj->t",
            velocities[:, :, coordinate],
            mass,
            velocities[:, :, coordinate],
        )
    scalar["V_g"] = -physical.g * np.sum(
        gravity_weights[None, :] * (positions @ physical.e_z), axis=1
    )
    scalar["V_buoy"] = (
        physical.rho_air
        * physical.bob_volume
        * physical.g
        * (positions[:, bob, :] @ physical.e_z)
    )
    scalar["E_F"] = (
        scalar["T_kin"]
        + scalar["V_g"]
        + scalar["V_buoy"]
        + scalar["V_ax"]
    )
    vector["R_A"] = (
        -branches["A"]["N"][:, 0, None]
        * branches["A"]["tangent"][:, 0, :]
    )
    vector["R_B"] = (
        -branches["B"]["N"][:, 0, None]
        * branches["B"]["tangent"][:, 0, :]
    )
    scalar["P_base"] = np.sum(
        vector["R_A"] * velocities[:, 0, :]
        + vector["R_B"] * velocities[:, 1, :],
        axis=1,
    )

    prescribed = np.asarray([0, 1], dtype=int)
    free = np.asarray(
        [index for index in range(node_count) if index not in {0, 1}],
        dtype=int,
    )
    M_ff = mass[np.ix_(free, free)]
    M_fp = mass[np.ix_(free, prescribed)]
    factor = cho_factor(M_ff, lower=True, check_finite=True)
    algebraic_reaction = np.zeros((sample_count, 2, 3), dtype=float)
    algebraic_base_power = np.zeros(sample_count, dtype=float)
    acceleration_series = np.zeros_like(positions)
    for index, t_value in enumerate(time):
        support_acceleration = np.vstack(
            (
                physical.support_A.acceleration(float(t_value)),
                physical.support_B.acceleration(float(t_value)),
            )
        )
        free_rhs = (
            applied[index, free]
            - internal[index, free]
            - M_fp @ support_acceleration
        )
        free_acceleration = np.column_stack(
            [
                cho_solve(factor, free_rhs[:, coordinate])
                for coordinate in range(3)
            ]
        )
        acceleration = np.empty((node_count, 3), dtype=float)
        acceleration[free] = free_acceleration
        acceleration[prescribed] = support_acceleration
        acceleration_series[index] = acceleration
        algebraic_reaction[index] = (
            mass @ acceleration + internal[index] - applied[index]
        )[prescribed]
        algebraic_base_power[index] = float(
            np.sum(algebraic_reaction[index] * velocities[index, prescribed])
        )

    canonical_derived: dict[str, Any] = {
        "branches": branches,
        **scalar,
        **vector,
    }
    physical_power = (
        -scalar["D_ax"]
        - scalar["D_string"]
        - scalar["D_b"]
        + scalar["P_air"]
        + scalar["P_base"]
        + scalar["P_ext"]
    )
    algebraic_power = (
        -scalar["D_ax"]
        - scalar["D_string"]
        - scalar["D_b"]
        + scalar["P_air"]
        + algebraic_base_power
        + scalar["P_ext"]
    )
    if sample_count >= 2:
        physical_integral = cumulative_trapezoid(
            physical_power, time, initial=0.0
        )
        algebraic_integral = cumulative_trapezoid(
            algebraic_power, time, initial=0.0
        )
        physical_residual = scalar["E_F"] - scalar["E_F"][0] - physical_integral
        algebraic_residual = (
            scalar["E_F"] - scalar["E_F"][0] - algebraic_integral
        )
        work_scale = max(
            float(np.trapz(np.abs(physical_power), time)),
            float(np.trapz(np.abs(algebraic_power), time)),
        )
    else:
        physical_residual = np.zeros(sample_count)
        algebraic_residual = np.zeros(sample_count)
        work_scale = 0.0
    total_mass = (
        physical.junction_mass
        + physical.bob_mass
        + sum(
            branch.mu * branch.L0 for branch in physical.branches.values()
        )
    )
    characteristic_length = sum(
        branch.L0 for branch in physical.branches.values()
    )
    gravitational_scale = total_mass * physical.g * characteristic_length
    energy_variation = float(
        np.max(np.abs(scalar["E_F"] - scalar["E_F"][0]))
    )
    stored_scale = max(
        float(np.max(np.abs(scalar["T_kin"]))),
        float(np.max(np.abs(scalar["V_ax"]))),
    )
    energy_scale = max(
        gravitational_scale,
        energy_variation,
        stored_scale,
        work_scale,
        np.finfo(float).tiny,
    )
    length_scale = max(
        *(branch.L0 for branch in physical.branches.values()),
        np.finfo(float).tiny,
    )
    velocity_scale = max(
        length_scale
        * np.sqrt(
            physical.g
            / min(branch.L0 for branch in physical.branches.values())
        ),
        np.finfo(float).tiny,
    )
    acceleration_scale = max(
        velocity_scale * velocity_scale / length_scale,
        np.finfo(float).tiny,
    )
    if compute_dynamics and sample_count >= 2:
        step = np.diff(time)[:, None, None]
        midpoint_time = 0.5 * (time[1:] + time[:-1])
        midpoint_positions = (
            0.5 * (positions[1:] + positions[:-1])
            + step / 8.0 * (velocities[:-1] - velocities[1:])
        )
        midpoint_velocities = (
            0.5 * (velocities[1:] + velocities[:-1])
            + step / 8.0
            * (acceleration_series[:-1] - acceleration_series[1:])
        )
        # The two prescribed supports are not dynamical unknowns.  Their
        # midpoint states therefore come from the frozen C^2 providers rather
        # than from a Hermite approximation of the endpoint samples.
        for index, t_value in enumerate(midpoint_time):
            midpoint_positions[index, 0] = physical.support_A.position(
                float(t_value)
            )
            midpoint_positions[index, 1] = physical.support_B.position(
                float(t_value)
            )
            midpoint_velocities[index, 0] = physical.support_A.velocity(
                float(t_value)
            )
            midpoint_velocities[index, 1] = physical.support_B.velocity(
                float(t_value)
            )
        _, midpoint_diagnostics, _ = _recompute_cable_output(
            config,
            physical,
            topology,
            midpoint_time,
            midpoint_positions,
            midpoint_velocities,
            compute_dynamics=False,
        )
        dynamics = _cable_dynamics_defect(
            time,
            positions,
            velocities,
            acceleration_series,
            midpoint_velocities,
            np.asarray(
                midpoint_diagnostics["canonical_acceleration"], dtype=float
            ),
            length_scale,
            velocity_scale,
            acceleration_scale,
        )
    else:
        dynamics = {
            "maximum_normalized_dynamics_defect": 0.0,
            "rms_normalized_dynamics_defect": 0.0,
            "maximum_normalized_cumulative_dynamics_defect": 0.0,
            "maximum_normalized_absolute_dynamics_defect": 0.0,
        }
    reaction_difference = np.stack(
        (
            vector["R_A"] - algebraic_reaction[:, 0],
            vector["R_B"] - algebraic_reaction[:, 1],
        ),
        axis=1,
    )
    guard_data = _canonical_cable_guard_data(
        physical, topology, time, positions, branches
    )
    recomputed_diagnostics = {
        "energy_scale": float(energy_scale),
        "max_absolute_energy_power_residual_physical_traction": float(
            np.max(np.abs(physical_residual))
        ),
        "max_absolute_energy_power_residual_algebraic_reaction": float(
            np.max(np.abs(algebraic_residual))
        ),
        "max_relative_energy_power_residual_physical_traction": float(
            np.max(np.abs(physical_residual)) / energy_scale
        ),
        "max_relative_energy_power_residual_algebraic_reaction": float(
            np.max(np.abs(algebraic_residual)) / energy_scale
        ),
        "min_D_ax": float(np.min(scalar["D_ax"])),
        "min_D_string": float(np.min(scalar["D_string"])),
        "min_D_b": float(np.min(scalar["D_b"])),
        "max_boundary_reaction_difference": float(
            np.max(np.linalg.norm(reaction_difference, axis=2))
        ),
        **dynamics,
        "canonical_acceleration": acceleration_series,
        "mass_matrix": {
            "symmetry_inf_norm": float(
                np.linalg.norm(M_ff - M_ff.T, ord=np.inf)
            ),
            "minimum_eigenvalue": float(np.linalg.eigvalsh(M_ff)[0]),
            "condition_number": float(np.linalg.cond(M_ff)),
        },
        "reaction_algebraic": {
            "A": algebraic_reaction[:, 0],
            "B": algebraic_reaction[:, 1],
        },
        "P_base_algebraic": algebraic_base_power,
        "sampled_guard_component_series": guard_data["component_series"],
        "sampled_guard_series": guard_data["aggregate"],
        "sampled_guard_minima": guard_data["minima"],
    }
    return canonical_derived, recomputed_diagnostics, guard_data


def _cable_dynamics_defect(
    time: np.ndarray,
    positions: np.ndarray,
    velocities: np.ndarray,
    acceleration: np.ndarray,
    midpoint_velocities: np.ndarray,
    midpoint_acceleration: np.ndarray,
    length_scale: float,
    velocity_scale: float,
    acceleration_scale: float,
) -> dict[str, float]:
    if time.size < 2:
        return {
            "maximum_normalized_dynamics_defect": 0.0,
            "rms_normalized_dynamics_defect": 0.0,
            "maximum_normalized_cumulative_dynamics_defect": 0.0,
            "maximum_normalized_absolute_dynamics_defect": 0.0,
        }
    step = np.diff(time)[:, None, None]
    position_defect = (
        positions[1:]
        - positions[:-1]
        - step
        / 6.0
        * (velocities[:-1] + 4.0 * midpoint_velocities + velocities[1:])
    )
    velocity_defect = (
        velocities[1:]
        - velocities[:-1]
        - step
        / 6.0
        * (acceleration[:-1] + 4.0 * midpoint_acceleration + acceleration[1:])
    )
    position_rate = np.linalg.norm(
        position_defect / (step * velocity_scale), axis=2
    )
    velocity_rate = np.linalg.norm(
        velocity_defect / (step * acceleration_scale), axis=2
    )
    rate_values = np.concatenate(
        (position_rate.reshape(-1), velocity_rate.reshape(-1))
    )
    signed_position = np.cumsum(position_defect, axis=0)
    signed_velocity = np.cumsum(velocity_defect, axis=0)
    signed_values = np.concatenate(
        (
            (
                np.linalg.norm(signed_position, axis=2) / length_scale
            ).reshape(-1),
            (
                np.linalg.norm(signed_velocity, axis=2) / velocity_scale
            ).reshape(-1),
        )
    )
    absolute_position = np.cumsum(
        np.linalg.norm(position_defect, axis=2), axis=0
    ) / length_scale
    absolute_velocity = np.cumsum(
        np.linalg.norm(velocity_defect, axis=2), axis=0
    ) / velocity_scale
    absolute_values = np.concatenate(
        (absolute_position.reshape(-1), absolute_velocity.reshape(-1))
    )
    return {
        "maximum_normalized_dynamics_defect": float(np.max(rate_values)),
        "rms_normalized_dynamics_defect": float(
            np.sqrt(np.mean(rate_values * rate_values))
        ),
        "maximum_normalized_cumulative_dynamics_defect": float(
            np.max(signed_values)
        ),
        "maximum_normalized_absolute_dynamics_defect": float(
            np.max(absolute_values)
        ),
    }


def _cable_initial_state_matches(
    config: dict[str, Any],
    physical: Any,
    topology: dict[str, Any],
    observed_positions: np.ndarray,
    observed_velocities: np.ndarray,
    length_scale: float,
    velocity_scale: float,
) -> bool:
    if physical.initial_mode == "STATIC_HOLD_RELEASE":
        try:
            model = CableFEM(physical, config["numerics"])
        except Exception:
            return False
        return bool(
            not model.numerical_issues
            and _array_matches(
                observed_positions,
                model.initial_positions,
                scale=length_scale,
            )
            and _array_matches(
                observed_velocities,
                model.initial_velocities,
                scale=velocity_scale,
            )
        )
    if physical.initial_mode != "DIRECT_STATE":
        return False
    expected_positions = np.full_like(observed_positions, np.nan, dtype=float)
    expected_velocities = np.full_like(observed_velocities, np.nan, dtype=float)
    for branch in BRANCHES:
        nodes = topology["branch_nodes"][branch]
        xi = np.linspace(0.0, 1.0, nodes.size)
        expected_positions[nodes] = physical.initial_branches[
            branch
        ].position.value(xi)
        expected_velocities[nodes] = physical.initial_branches[
            branch
        ].velocity.value(xi)
    junction = topology["node_index"]["junction"]
    bob = topology["node_index"]["bob"]
    expected_positions[junction] = physical.r_J0
    expected_velocities[junction] = physical.v_J0
    expected_positions[bob] = physical.r_m0
    expected_velocities[bob] = physical.v_m0
    expected_positions[0] = physical.support_A.position(0.0)
    expected_velocities[0] = physical.support_A.velocity(0.0)
    expected_positions[1] = physical.support_B.position(0.0)
    expected_velocities[1] = physical.support_B.velocity(0.0)
    return bool(
        np.all(np.isfinite(expected_positions))
        and np.all(np.isfinite(expected_velocities))
        and _array_matches(
            observed_positions, expected_positions, scale=length_scale
        )
        and _array_matches(
            observed_velocities, expected_velocities, scale=velocity_scale
        )
    )


def _cable_trajectory_contract(
    config: dict[str, Any],
    result: SimulationResult,
    expected_status: list[str],
    guard_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    issues, physical = parse_cable_physical(config)
    topology = _expected_cable_topology(config)
    if issues or physical is None or topology is None or not isinstance(guard_schema, dict):
        return {
            "passed": False,
            "checks": {"candidate_revalidated": False},
            "recomputed_diagnostics": None,
        }
    time = np.asarray(result.time)
    state = result.state
    derived = result.derived
    expected_state_names = {
        "node_positions",
        "node_velocities",
        "r_J",
        "v_J",
        "r_m",
        "v_m",
    }
    expected_scalar_names = {
        "T_kin",
        "V_g",
        "V_buoy",
        "V_ax",
        "E_F",
        "D_ax",
        "D_string",
        "D_b",
        "P_base",
        "P_air",
        "P_ext",
    }
    expected_vector_names = {"F_drag_b", "R_A", "R_B"}
    checks: dict[str, bool] = {
        "state_key_set_exact": isinstance(state, dict)
        and set(state) == expected_state_names,
        "derived_key_set_exact": isinstance(derived, dict)
        and set(derived)
        == {"branches", *expected_scalar_names, *expected_vector_names},
        "metadata_elements_exact": result.metadata.get("elements")
        == topology["elements"],
        "metadata_node_ids_exact": result.metadata.get("node_ids")
        == topology["node_ids"],
    }
    branch_metadata = result.metadata.get("branch_nodes")
    checks["metadata_branch_topology_exact"] = bool(
        isinstance(branch_metadata, dict)
        and set(branch_metadata) == set(BRANCHES)
        and all(
            np.array_equal(
                np.asarray(branch_metadata[branch]),
                topology["branch_nodes"][branch],
            )
            for branch in BRANCHES
        )
    )
    try:
        positions = np.asarray(state.get("node_positions"))
        velocities = np.asarray(state.get("node_velocities"))
    except (AttributeError, TypeError, ValueError):
        positions = np.empty((0, 0, 0))
        velocities = np.empty((0, 0, 0))
    expected_node_shape = (time.size, topology["node_count"], 3)
    checks["node_state_shape_and_finiteness"] = bool(
        positions.shape == expected_node_shape
        and velocities.shape == expected_node_shape
        and positions.dtype != object
        and velocities.dtype != object
        and np.all(np.isfinite(positions))
        and np.all(np.isfinite(velocities))
    )
    if not checks["node_state_shape_and_finiteness"]:
        return {
            "passed": False,
            "checks": checks,
            "recomputed_diagnostics": None,
        }
    length_scale = max(
        *(branch.L0 for branch in physical.branches.values()),
        np.finfo(float).tiny,
    )
    rate_scale = max(
        np.sqrt(physical.g / min(branch.L0 for branch in physical.branches.values())),
        np.finfo(float).tiny,
    )
    velocity_scale = length_scale * rate_scale
    force_scale = max(
        (
            physical.junction_mass
            + physical.bob_mass
            + sum(
                branch.mu * branch.L0
                for branch in physical.branches.values()
            )
        )
        * physical.g,
        np.finfo(float).tiny,
    )
    energy_scale = force_scale * sum(
        branch.L0 for branch in physical.branches.values()
    )
    power_scale = energy_scale * rate_scale
    junction = topology["node_index"]["junction"]
    bob = topology["node_index"]["bob"]
    for name, expected, scale in (
        ("r_J", positions[:, junction], length_scale),
        ("v_J", velocities[:, junction], velocity_scale),
        ("r_m", positions[:, bob], length_scale),
        ("v_m", velocities[:, bob], velocity_scale),
    ):
        checks[f"state_{name}_matches_node_state"] = _array_matches(
            state.get(name), expected, scale=scale
        )
    support_A_positions = np.asarray(
        [physical.support_A.position(float(t)) for t in time]
    )
    support_B_positions = np.asarray(
        [physical.support_B.position(float(t)) for t in time]
    )
    support_A_velocities = np.asarray(
        [physical.support_A.velocity(float(t)) for t in time]
    )
    support_B_velocities = np.asarray(
        [physical.support_B.velocity(float(t)) for t in time]
    )
    checks["support_state_matches_prescribed_input"] = bool(
        _array_matches(positions[:, 0], support_A_positions, scale=length_scale)
        and _array_matches(positions[:, 1], support_B_positions, scale=length_scale)
        and _array_matches(
            velocities[:, 0], support_A_velocities, scale=velocity_scale
        )
        and _array_matches(
            velocities[:, 1], support_B_velocities, scale=velocity_scale
        )
    )
    checks["initial_state_matches_candidate_preparation"] = (
        _cable_initial_state_matches(
            config,
            physical,
            topology,
            np.asarray(positions[0], dtype=float),
            np.asarray(velocities[0], dtype=float),
            length_scale,
            velocity_scale,
        )
    )
    try:
        canonical, recomputed, guard_data = _recompute_cable_output(
            config,
            physical,
            topology,
            np.asarray(time, dtype=float),
            np.asarray(positions, dtype=float),
            np.asarray(velocities, dtype=float),
        )
    except Exception:
        checks["canonical_recomputation_succeeded"] = False
        return {
            "passed": False,
            "checks": checks,
            "recomputed_diagnostics": None,
        }
    checks["canonical_recomputation_succeeded"] = True
    if expected_status == ["OUT_OF_SCOPE"]:
        state_left = (
            result.events[0].get("state_left")
            if len(result.events) == 1 and isinstance(result.events[0], dict)
            else None
        )
        event_positions = (
            state_left.get("positions") if isinstance(state_left, dict) else None
        )
        event_velocities = (
            state_left.get("velocities") if isinstance(state_left, dict) else None
        )
        try:
            event_positions_array = np.asarray(event_positions, dtype=float)
            event_velocities_array = np.asarray(event_velocities, dtype=float)
        except (TypeError, ValueError, OverflowError):
            event_positions_array = np.empty((0, 0))
            event_velocities_array = np.empty((0, 0))
        output_dt = config.get("numerics", {}).get("output_dt")
        gap = float(result.tau) - float(time[-1])
        expected_event_shape = (topology["node_count"], 3)
        checks["event_terminal_gap_bounded"] = bool(
            event_positions_array.shape == expected_event_shape
            and event_velocities_array.shape == expected_event_shape
            and np.all(np.isfinite(event_positions_array))
            and np.all(np.isfinite(event_velocities_array))
            and is_finite_number(output_dt)
            and gap > 0.0
            and gap
            <= float(output_dt)
            + 64.0 * np.finfo(float).eps * max(abs(float(result.tau)), float(output_dt))
        )
        if checks["event_terminal_gap_bounded"]:
            try:
                _event_canonical, event_recomputed, _event_guards = (
                    _recompute_cable_output(
                        config,
                        physical,
                        topology,
                        np.append(np.asarray(time, dtype=float), float(result.tau)),
                        np.concatenate(
                            (
                                np.asarray(positions, dtype=float),
                                event_positions_array[None, :, :],
                            ),
                            axis=0,
                        ),
                        np.concatenate(
                            (
                                np.asarray(velocities, dtype=float),
                                event_velocities_array[None, :, :],
                            ),
                            axis=0,
                        ),
                    )
                )
                for field in (
                    "maximum_normalized_dynamics_defect",
                    "rms_normalized_dynamics_defect",
                    "maximum_normalized_cumulative_dynamics_defect",
                    "maximum_normalized_absolute_dynamics_defect",
                ):
                    recomputed[field] = event_recomputed[field]
            except Exception:
                checks["event_terminal_gap_bounded"] = False
    else:
        checks["event_terminal_gap_bounded"] = True
    observed_branches = derived.get("branches") if isinstance(derived, dict) else None
    branch_fields = {
        "lambda": (1.0, False),
        "lambda_dot": (rate_scale, False),
        "tangent": (1.0, False),
        "N_elastic": (force_scale, False),
        "N_viscous": (force_scale, False),
        "N": (force_scale, False),
        "active": (1.0, True),
        "slack": (1.0, True),
        "loaded_length": (length_scale, False),
        "f_drag_center": (force_scale / length_scale, False),
    }
    checks["branch_set_exact"] = bool(
        isinstance(observed_branches, dict)
        and set(observed_branches) == set(BRANCHES)
    )
    for branch in BRANCHES:
        raw = (
            observed_branches.get(branch)
            if isinstance(observed_branches, dict)
            else None
        )
        checks[f"branch_{branch}_field_set_exact"] = bool(
            isinstance(raw, dict) and set(raw) == set(branch_fields)
        )
        for field, (scale, boolean) in branch_fields.items():
            checks[f"branch_{branch}_{field}_matches_state"] = bool(
                isinstance(raw, dict)
                and _array_matches(
                    raw.get(field),
                    canonical["branches"][branch][field],
                    scale=scale,
                    boolean=boolean,
                )
            )
    global_scales = {
        "T_kin": energy_scale,
        "V_g": energy_scale,
        "V_buoy": energy_scale,
        "V_ax": energy_scale,
        "E_F": energy_scale,
        "D_ax": power_scale,
        "D_string": power_scale,
        "D_b": power_scale,
        "P_base": power_scale,
        "P_air": power_scale,
        "P_ext": power_scale,
        "F_drag_b": force_scale,
        "R_A": force_scale,
        "R_B": force_scale,
    }
    for name, scale in global_scales.items():
        checks[f"derived_{name}_matches_state_and_input"] = _array_matches(
            derived.get(name) if isinstance(derived, dict) else None,
            canonical[name],
            scale=scale,
        )
    diagnostics = result.diagnostics if isinstance(result.diagnostics, dict) else {}
    diagnostic_scales = {
        "energy_scale": energy_scale,
        "max_absolute_energy_power_residual_physical_traction": energy_scale,
        "max_absolute_energy_power_residual_algebraic_reaction": energy_scale,
        "max_relative_energy_power_residual_physical_traction": 1.0,
        "max_relative_energy_power_residual_algebraic_reaction": 1.0,
        "min_D_ax": power_scale,
        "min_D_string": power_scale,
        "min_D_b": power_scale,
        "max_boundary_reaction_difference": force_scale,
    }
    for name, scale in diagnostic_scales.items():
        checks[f"diagnostic_{name}_recomputed"] = _scalar_matches(
            diagnostics.get(name), recomputed[name], scale=scale
        )
    mass_observed = diagnostics.get("mass_matrix")
    checks["mass_diagnostics_recomputed"] = bool(
        isinstance(mass_observed, dict)
        and all(
            _scalar_matches(
                mass_observed.get(name),
                recomputed["mass_matrix"][name],
                scale=max(abs(recomputed["mass_matrix"][name]), np.finfo(float).tiny),
            )
            for name in (
                "symmetry_inf_norm",
                "minimum_eigenvalue",
                "condition_number",
            )
        )
    )
    reaction = diagnostics.get("reaction_algebraic")
    checks["algebraic_reaction_series_recomputed"] = bool(
        isinstance(reaction, dict)
        and set(reaction) == {"A", "B"}
        and all(
            _array_matches(
                reaction[branch],
                recomputed["reaction_algebraic"][branch],
                scale=force_scale,
            )
            for branch in ("A", "B")
        )
    )
    checks["algebraic_base_power_series_recomputed"] = _array_matches(
        diagnostics.get("P_base_algebraic"),
        recomputed["P_base_algebraic"],
        scale=power_scale,
    )
    checks["guard_component_series_matches_state"] = bool(
        isinstance(diagnostics.get("sampled_guard_component_series"), dict)
        and all(
            _array_matches(
                diagnostics["sampled_guard_component_series"].get(name),
                values,
                scale=guard_schema["scales"][name],
            )
            for name, values in guard_data["component_series"].items()
        )
    )
    checks["aggregate_guard_series_matches_state"] = bool(
        isinstance(diagnostics.get("sampled_guard_series"), dict)
        and set(diagnostics["sampled_guard_series"])
        == set(guard_data["aggregate"])
        and all(
            _array_matches(
                diagnostics["sampled_guard_series"].get(name),
                values,
                scale=(
                    rate_scale if name == "material_rate" else length_scale
                    if name.startswith("custom:")
                    else 1.0
                ),
            )
            for name, values in guard_data["aggregate"].items()
        )
    )
    checks["guard_minima_recomputed"] = bool(
        isinstance(diagnostics.get("sampled_guard_minima"), dict)
        and set(diagnostics["sampled_guard_minima"])
        == set(guard_data["minima"])
        and all(
            _scalar_matches(
                diagnostics["sampled_guard_minima"].get(name),
                value,
                scale=(rate_scale if ":rate_" in name else 1.0),
            )
            for name, value in guard_data["minima"].items()
        )
    )
    checks["event_left_limit_matches_state"] = _event_left_limit_consistent(
        config,
        result,
        "FWD-CABLE-1.0",
        expected_status,
        guard_schema,
    )
    return {
        "passed": bool(checks) and all(checks.values()),
        "checks": checks,
        "recomputed_diagnostics": recomputed,
    }


def _event_left_limit_consistent(
    config: dict[str, Any],
    result: SimulationResult,
    model_id: str,
    expected_status: list[str],
    guard_schema: dict[str, Any] | None,
) -> bool:
    """Recompute the event state, derived output, and every scalar guard."""

    if expected_status == ["COMPLETED"]:
        return result.events == []
    if (
        expected_status != ["OUT_OF_SCOPE"]
        or len(result.events) != 1
        or not isinstance(result.events[0], dict)
        or not isinstance(guard_schema, dict)
    ):
        return False
    event = result.events[0]
    if not (
        is_finite_number(event.get("time"))
        and is_finite_number(result.tau)
        and float(event["time"]) == float(result.tau)
    ):
        return False
    tau = float(result.tau)
    expected_scales = guard_schema.get("scales")
    if not isinstance(expected_scales, dict):
        return False
    if model_id == "FWD-TORUS-1.0":
        issues, params = validate_torus_config(config)
        if issues or params is None:
            return False
        try:
            state_left = np.asarray(event.get("state_left"), dtype=float)
        except (TypeError, ValueError, OverflowError):
            return False
        if state_left.shape != (4,) or not np.all(np.isfinite(state_left)):
            return False
        canonical = torus_derived(params, state_left[None, :])
        derived_left = event.get("derived_left")
        guard_values = event.get("guard_values")
        if not (
            isinstance(derived_left, dict)
            and set(derived_left) == set(canonical)
            and isinstance(guard_values, dict)
            and set(guard_values) == _fixed_torus_guard_names()
        ):
            return False
        length_scale = max(
            params.s_A,
            params.s_B,
            params.lower_length,
            params.d,
            params.h,
            np.finfo(float).tiny,
        )
        force_scale = max(params.mass * params.g, np.finfo(float).tiny)
        energy_scale = max(
            params.mass * params.g * params.lower_length,
            np.finfo(float).tiny,
        )
        scales = {
            "J": length_scale,
            "r_m": length_scale,
            "R": length_scale,
            "T_A": force_scale,
            "T_B": force_scale,
            "T_lower": force_scale,
            "E_torus": energy_scale,
            "r_perp": length_scale,
            "Q_T": length_scale * length_scale,
            "torus_unsquared_residual": length_scale * length_scale,
            "physical_branch_residual": length_scale * length_scale,
        }
        if not all(
            _array_matches(
                derived_left.get(name),
                np.asarray(value)[0],
                scale=scales[name],
            )
            for name, value in canonical.items()
        ):
            return False
        canonical_guards = {
            "R_ZERO": float(canonical["R"][0]),
            "T_A_ZERO": float(canonical["T_A"][0]),
            "T_B_ZERO": float(canonical["T_B"][0]),
            "T_LOWER_ZERO": float(canonical["T_lower"][0]),
        }
        if not all(
            _scalar_matches(
                guard_values.get(name), value, scale=expected_scales[name]
            )
            for name, value in canonical_guards.items()
        ):
            return False
    elif model_id == "FWD-CABLE-1.0":
        issues, physical = parse_cable_physical(config)
        topology = _expected_cable_topology(config)
        state_left = event.get("state_left")
        if (
            issues
            or physical is None
            or topology is None
            or not isinstance(state_left, dict)
            or set(state_left) != {"positions", "velocities"}
        ):
            return False
        try:
            positions = np.asarray(state_left["positions"], dtype=float)
            velocities = np.asarray(state_left["velocities"], dtype=float)
        except (TypeError, ValueError, OverflowError):
            return False
        shape = (topology["node_count"], 3)
        if (
            positions.shape != shape
            or velocities.shape != shape
            or not np.all(np.isfinite(positions))
            or not np.all(np.isfinite(velocities))
        ):
            return False
        length_scale = max(
            *(branch.L0 for branch in physical.branches.values()),
            np.finfo(float).tiny,
        )
        velocity_scale = max(
            length_scale
            * np.sqrt(
                physical.g
                / min(branch.L0 for branch in physical.branches.values())
            ),
            np.finfo(float).tiny,
        )
        if not (
            _array_matches(
                positions[0], physical.support_A.position(tau), scale=length_scale
            )
            and _array_matches(
                positions[1], physical.support_B.position(tau), scale=length_scale
            )
            and _array_matches(
                velocities[0], physical.support_A.velocity(tau), scale=velocity_scale
            )
            and _array_matches(
                velocities[1], physical.support_B.velocity(tau), scale=velocity_scale
            )
        ):
            return False
        try:
            canonical, _diagnostics, guard_data = _recompute_cable_output(
                config,
                physical,
                topology,
                np.asarray([tau]),
                positions[None, :, :],
                velocities[None, :, :],
            )
        except Exception:
            return False
        derived_left = event.get("derived_left")
        if not _cable_event_derived_matches(
            derived_left, canonical, physical
        ):
            return False
        canonical_guards = {
            name: float(values[0])
            for name, values in guard_data["component_series"].items()
        }
        if set(canonical_guards) != set(expected_scales):
            return False
        if not all(
            (
                value := _event_trigger_value(event, name, model_id)
            )
            is not None
            and _scalar_matches(
                value,
                canonical_guards[name],
                scale=expected_scales[name],
            )
            for name in canonical_guards
        ):
            return False
    else:
        return False
    triggers = event.get("triggers")
    if not isinstance(triggers, list):
        return False
    rooted = {
        name
        for name, value in canonical_guards.items()
        if abs(float(value)) <= _canonical_zero_tolerance(expected_scales[name])
    }
    return bool(rooted and set(triggers) == rooted)


def _cable_event_derived_matches(
    observed: Any,
    canonical: dict[str, Any],
    physical: Any,
) -> bool:
    if not isinstance(observed, dict) or set(observed) != set(canonical):
        return False
    observed_branches = observed.get("branches")
    canonical_branches = canonical["branches"]
    if not (
        isinstance(observed_branches, dict)
        and set(observed_branches) == set(BRANCHES)
    ):
        return False
    length_scale = max(
        *(branch.L0 for branch in physical.branches.values()),
        np.finfo(float).tiny,
    )
    rate_scale = max(
        np.sqrt(physical.g / min(branch.L0 for branch in physical.branches.values())),
        np.finfo(float).tiny,
    )
    velocity_scale = length_scale * rate_scale
    total_mass = (
        physical.junction_mass
        + physical.bob_mass
        + sum(branch.mu * branch.L0 for branch in physical.branches.values())
    )
    force_scale = max(total_mass * physical.g, np.finfo(float).tiny)
    energy_scale = force_scale * sum(
        branch.L0 for branch in physical.branches.values()
    )
    power_scale = energy_scale * rate_scale
    branch_scales = {
        "lambda": (1.0, False),
        "lambda_dot": (rate_scale, False),
        "tangent": (1.0, False),
        "N_elastic": (force_scale, False),
        "N_viscous": (force_scale, False),
        "N": (force_scale, False),
        "active": (1.0, True),
        "slack": (1.0, True),
        "loaded_length": (length_scale, False),
        "f_drag_center": (force_scale / length_scale, False),
    }
    for branch in BRANCHES:
        raw = observed_branches.get(branch)
        if not isinstance(raw, dict) or set(raw) != set(branch_scales):
            return False
        for field, (scale, boolean) in branch_scales.items():
            expected = np.asarray(canonical_branches[branch][field])[0]
            if not _array_matches(
                raw.get(field), expected, scale=scale, boolean=boolean
            ):
                return False
    global_scales = {
        "T_kin": energy_scale,
        "V_g": energy_scale,
        "V_buoy": energy_scale,
        "V_ax": energy_scale,
        "E_F": energy_scale,
        "D_ax": power_scale,
        "D_string": power_scale,
        "D_b": power_scale,
        "P_base": power_scale,
        "P_air": power_scale,
        "P_ext": power_scale,
        "F_drag_b": force_scale,
        "R_A": force_scale,
        "R_B": force_scale,
    }
    return all(
        _array_matches(
            observed.get(name),
            np.asarray(canonical[name])[0],
            scale=scale,
        )
        for name, scale in global_scales.items()
    )


def _event_contract(
    result: SimulationResult,
    expected_status: list[str],
    model_id: str,
    expected_guard_schema: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    signature = []
    for event in result.events:
        if not isinstance(event, dict):
            signature.append({"kind": "MALFORMED", "triggers": []})
            continue
        raw_triggers = event.get("triggers")
        signature.append(
            {
                "kind": str(event.get("kind")),
                "triggers": sorted(
                    str(value)
                    for value in (
                        raw_triggers
                        if isinstance(raw_triggers, (list, tuple))
                        else []
                    )
                ),
            }
        )
    if expected_status == ["COMPLETED"]:
        return result.events == [], signature
    if not isinstance(expected_guard_schema, dict):
        return False, signature
    if len(result.events) != 1:
        return False, signature
    event = result.events[0]
    if not isinstance(event, dict):
        return False, signature
    triggers = event.get("triggers")
    tolerances = event.get("guard_zero_tolerances")
    time = np.asarray(result.time)
    common_valid = bool(
        event.get("kind") == "physical_exit"
        and is_finite_number(event.get("time"))
        and is_finite_number(result.tau)
        and float(event["time"]) == float(result.tau)
        and float(result.tau) > 0.0
        and isinstance(triggers, list)
        and bool(triggers)
        and all(isinstance(trigger, str) and trigger for trigger in triggers)
        and len(triggers) == len(set(triggers))
        and isinstance(tolerances, dict)
        and set(triggers) == set(tolerances)
        and time.ndim == 1
        and np.all(np.isfinite(time))
        and (not time.size or np.all(time < float(result.tau)))
        and (time.size < 2 or np.all(np.diff(time) > 0.0))
        and _event_state_schema_valid(event.get("state_left"), model_id)
        and _event_derived_schema_valid(event.get("derived_left"), model_id)
        and _event_guard_payload_complete(
            result,
            expected_guard_schema,
            model_id,
            expected_status,
        )
        and isinstance(config, dict)
        and _event_left_limit_consistent(
            config,
            result,
            model_id,
            expected_status,
            expected_guard_schema,
        )
    )
    if not common_valid:
        return False, signature
    for trigger in triggers:
        value = _event_trigger_value(event, trigger, model_id)
        tolerance = tolerances.get(trigger)
        expected_scales = expected_guard_schema.get("scales")
        expected_scale = (
            expected_scales.get(trigger)
            if isinstance(expected_scales, dict)
            else None
        )
        canonical_tolerance = _canonical_zero_tolerance(expected_scale)
        if not (
            is_finite_number(value)
            and is_finite_number(tolerance)
            and _matches_canonical_zero_tolerance(tolerance, expected_scale)
            and np.isfinite(canonical_tolerance)
            and abs(float(value)) <= canonical_tolerance
        ):
            return False, signature
    return True, signature


def _event_state_schema_valid(value: Any, model_id: str) -> bool:
    if model_id == "FWD-TORUS-1.0":
        array = np.asarray(value)
        return bool(
            array.shape == (4,)
            and array.dtype != object
            and np.all(np.isfinite(array))
        )
    if not isinstance(value, dict) or set(value) != {
        "positions",
        "velocities",
    }:
        return False
    positions = np.asarray(value["positions"])
    velocities = np.asarray(value["velocities"])
    return bool(
        positions.ndim == 2
        and positions.shape[0] >= 4
        and positions.shape[1] == 3
        and velocities.shape == positions.shape
        and positions.dtype != object
        and velocities.dtype != object
        and np.all(np.isfinite(positions))
        and np.all(np.isfinite(velocities))
    )


def _event_derived_schema_valid(value: Any, model_id: str) -> bool:
    if not isinstance(value, dict) or not _nested_numeric_finite(value):
        return False
    if model_id == "FWD-TORUS-1.0":
        return {
            "J",
            "r_m",
            "R",
            "T_A",
            "T_B",
            "T_lower",
            "E_torus",
            "r_perp",
            "Q_T",
            "torus_unsquared_residual",
            "physical_branch_residual",
        }.issubset(value)
    required = {
        "branches",
        "T_kin",
        "V_g",
        "V_buoy",
        "V_ax",
        "E_F",
        "D_ax",
        "D_string",
        "D_b",
        "P_base",
        "P_air",
        "P_ext",
        "F_drag_b",
        "R_A",
        "R_B",
    }
    if not required.issubset(value) or not isinstance(value["branches"], dict):
        return False
    branch_fields = {
        "lambda",
        "lambda_dot",
        "tangent",
        "N_elastic",
        "N_viscous",
        "N",
        "active",
        "slack",
        "loaded_length",
        "f_drag_center",
    }
    return set(value["branches"]) == set(BRANCHES) and all(
        isinstance(value["branches"][branch], dict)
        and branch_fields.issubset(value["branches"][branch])
        for branch in BRANCHES
    )


def _event_trigger_value(
    event: dict[str, Any], trigger: str, model_id: str
) -> float | None:
    try:
        if model_id == "FWD-TORUS-1.0":
            values = event.get("guard_values")
            return float(values[trigger]) if isinstance(values, dict) else None
        components = event.get("guard_components")
        if not isinstance(components, dict):
            return None
        if trigger.startswith("LAMBDA_MIN:"):
            _kind, branch, _label, element = trigger.split(":")
            return float(components["lambda"][branch][int(element)])
        if trigger.startswith("MATERIAL_DOMAIN:"):
            _kind, branch, boundary, _label, element = trigger.split(":")
            return float(
                components["material"][branch][boundary][int(element)]
            )
        if trigger.startswith("EXIT_GUARD:"):
            return float(components["custom"][trigger.split(":", 1)[1]])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return None


def _observation_result_contract(
    config: dict[str, Any],
    result: SimulationResult,
    model_id: str,
) -> dict[str, Any]:
    """Re-evaluate the complete observation schema from input and state.

    In particular, an empty self-reported observation cannot satisfy a
    nonempty record-time request.  The frozen time map, validity masks,
    ambiguity mask, operator and values are all checked independently.
    """

    spec = config.get("observation")
    if spec is None:
        passed = result.observations == {}
        return {
            "passed": bool(passed),
            "checks": {"optional_observation_absent": bool(passed)},
        }
    if not isinstance(spec, dict):
        return {
            "passed": False,
            "checks": {"observation_spec_is_object": False},
        }
    try:
        interpolator, e_z, position_scale = _observation_position_interpolator(
            config, result, model_id
        )
    except Exception:
        return {
            "passed": False,
            "checks": {"canonical_position_interpolator_built": False},
        }
    numerics = config.get("numerics")
    tolerance = (
        numerics.get("event_cluster_tolerance")
        if isinstance(numerics, dict)
        else None
    )
    if not is_finite_number(tolerance) or float(tolerance) <= 0.0:
        return {
            "passed": False,
            "checks": {"event_time_tolerance_valid": False},
        }
    try:
        expected = evaluate_observations(
            spec,
            position_at=interpolator,
            interval_end=float(result.tau),
            completed=result.contract_status == ["COMPLETED"],
            e_z=e_z,
            event_time_tolerance=float(tolerance),
        )
    except Exception:
        return {
            "passed": False,
            "checks": {"canonical_observation_evaluation_succeeded": False},
        }
    observed = result.observations
    if not isinstance(observed, dict):
        return {
            "passed": False,
            "checks": {"observation_result_is_object": False},
        }
    checks: dict[str, bool] = {
        "status_exact": observed.get("status") == expected.get("status"),
        "key_set_exact": set(observed) == set(expected),
        "operator_exact": observed.get("operator") == expected.get("operator"),
    }
    if expected.get("status") != ["OBSERVATION_INPUT_VALID"]:
        checks["valid_input_required_for_qualification"] = False
        return {"passed": False, "checks": checks}
    for name in ("record_time", "model_time", "time"):
        checks[f"{name}_exact"] = _array_matches(
            observed.get(name), expected.get(name), scale=max(float(result.tau), 1.0e-12)
        )
    for name in ("valid_mask", "event_ambiguous_mask"):
        checks[f"{name}_exact"] = _array_matches(
            observed.get(name), expected.get(name), boolean=True
        )
    checks["values_exact_from_canonical_position"] = _observation_values_match(
        observed.get("values"),
        expected.get("values"),
        position_scale,
    )
    checks["errors_exact"] = _nested_observation_matches(
        observed.get("errors"), expected.get("errors")
    )
    expected_record = np.asarray(expected.get("record_time"))
    checks["nonempty_request_not_deleted"] = bool(
        expected_record.size == 0
        or np.asarray(observed.get("record_time")).size == expected_record.size
    )
    return {"passed": bool(checks) and all(checks.values()), "checks": checks}


def _observation_position_interpolator(
    config: dict[str, Any],
    result: SimulationResult,
    model_id: str,
):
    time = np.asarray(result.time, dtype=float)
    if (
        time.ndim != 1
        or time.size < 1
        or not np.all(np.isfinite(time))
        or (time.size > 1 and np.any(np.diff(time) <= 0.0))
    ):
        raise ValueError("invalid returned time grid")
    if model_id == "FWD-TORUS-1.0":
        issues, params = validate_torus_config(config)
        states = np.asarray(result.state.get("X_torus"), dtype=float)
        if issues or params is None or states.shape != (time.size, 4):
            raise ValueError("invalid torus state")
        position = torus_derived(params, states)["r_m"]
        phi, theta, phi_dot, theta_dot = states.T
        ell = params.lower_length
        R = params.h + ell * np.cos(phi)
        radial = (
            np.sin(theta)[:, None] * params.e_y
            + np.cos(theta)[:, None] * params.e_z
        )
        theta_direction = (
            np.cos(theta)[:, None] * params.e_y
            - np.sin(theta)[:, None] * params.e_z
        )
        velocity = (
            (ell * np.cos(phi) * phi_dot)[:, None] * params.e_x
            + (-ell * np.sin(phi) * phi_dot)[:, None] * radial
            + (R * theta_dot)[:, None] * theta_direction
        )
        scale = max(
            params.s_A,
            params.s_B,
            params.lower_length,
            params.d,
            params.h,
            np.finfo(float).tiny,
        )
        e_z = params.e_z
    elif model_id == "FWD-CABLE-1.0":
        issues, physical = parse_cable_physical(config)
        topology = _expected_cable_topology(config)
        if issues or physical is None or topology is None:
            raise ValueError("invalid cable input")
        positions = np.asarray(result.state.get("node_positions"), dtype=float)
        velocities = np.asarray(result.state.get("node_velocities"), dtype=float)
        shape = (time.size, topology["node_count"], 3)
        if positions.shape != shape or velocities.shape != shape:
            raise ValueError("invalid cable state")
        bob = topology["node_index"]["bob"]
        position = positions[:, bob]
        velocity = velocities[:, bob]
        scale = max(
            *(branch.L0 for branch in physical.branches.values()),
            np.finfo(float).tiny,
        )
        e_z = physical.e_z
    else:
        raise ValueError("unknown model")
    if result.contract_status == ["OUT_OF_SCOPE"]:
        if len(result.events) != 1 or not isinstance(result.events[0], dict):
            raise ValueError("missing event left state")
        event = result.events[0]
        tau = float(result.tau)
        if not tau > float(time[-1]):
            raise ValueError("event is not after the returned half-open grid")
        if model_id == "FWD-TORUS-1.0":
            event_state = np.asarray(event.get("state_left"), dtype=float)
            if event_state.shape != (4,) or not np.all(np.isfinite(event_state)):
                raise ValueError("invalid torus event state")
            event_position = torus_derived(params, event_state[None, :])["r_m"][0]
            phi, theta, phi_dot, theta_dot = event_state
            radial = np.sin(theta) * params.e_y + np.cos(theta) * params.e_z
            theta_direction = (
                np.cos(theta) * params.e_y - np.sin(theta) * params.e_z
            )
            event_R = params.h + params.lower_length * np.cos(phi)
            event_velocity = (
                params.lower_length * np.cos(phi) * phi_dot * params.e_x
                - params.lower_length * np.sin(phi) * phi_dot * radial
                + event_R * theta_dot * theta_direction
            )
        else:
            state_left = event.get("state_left")
            if not isinstance(state_left, dict):
                raise ValueError("invalid cable event state")
            event_positions = np.asarray(state_left.get("positions"), dtype=float)
            event_velocities = np.asarray(state_left.get("velocities"), dtype=float)
            expected_shape = (topology["node_count"], 3)
            if (
                event_positions.shape != expected_shape
                or event_velocities.shape != expected_shape
                or not np.all(np.isfinite(event_positions))
                or not np.all(np.isfinite(event_velocities))
            ):
                raise ValueError("invalid cable event state")
            bob = topology["node_index"]["bob"]
            event_position = event_positions[bob]
            event_velocity = event_velocities[bob]
        time = np.append(time, tau)
        position = np.vstack((position, event_position))
        velocity = np.vstack((velocity, event_velocity))
    if not (
        np.all(np.isfinite(position)) and np.all(np.isfinite(velocity))
    ):
        raise ValueError("nonfinite canonical position")

    def position_at(target: np.ndarray) -> np.ndarray:
        return _hermite_interpolate_position(
            time,
            position,
            velocity,
            np.asarray(target, dtype=float),
        )

    return position_at, np.asarray(e_z, dtype=float), float(scale)


def _hermite_interpolate_position(
    time: np.ndarray,
    position: np.ndarray,
    velocity: np.ndarray,
    target: np.ndarray,
) -> np.ndarray:
    if target.ndim != 1 or not np.all(np.isfinite(target)):
        raise ValueError("invalid observation target grid")
    output = np.empty((target.size, 3), dtype=float)
    for index, value in enumerate(target):
        exact = np.flatnonzero(time == value)
        if exact.size:
            output[index] = position[int(exact[0])]
            continue
        right = int(np.searchsorted(time, value, side="right"))
        if right <= 0 or right >= time.size:
            raise ValueError("observation target outside returned samples")
        left = right - 1
        width = float(time[right] - time[left])
        coordinate = float((value - time[left]) / width)
        s2 = coordinate * coordinate
        s3 = s2 * coordinate
        output[index] = (
            (2.0 * s3 - 3.0 * s2 + 1.0) * position[left]
            + (s3 - 2.0 * s2 + coordinate) * width * velocity[left]
            + (-2.0 * s3 + 3.0 * s2) * position[right]
            + (s3 - s2) * width * velocity[right]
        )
    return output


def _observation_values_match(
    observed: Any, expected: Any, position_scale: float
) -> bool:
    try:
        left = np.asarray(observed, dtype=float)
        right = np.asarray(expected, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return False
    if left.shape != right.shape or left.ndim != 2 or left.shape[1] != 2:
        return False
    if not np.array_equal(np.isfinite(left), np.isfinite(right)):
        return False
    finite = np.isfinite(right)
    if not np.any(finite):
        return True
    magnitude = max(
        float(np.max(np.abs(right[finite]))),
        float(position_scale),
        np.finfo(float).tiny,
    )
    return bool(
        np.allclose(
            left[finite],
            right[finite],
            rtol=2.0e-8,
            atol=2.0e-10 * magnitude,
        )
    )


def _nested_observation_matches(observed: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return bool(
            isinstance(observed, dict)
            and set(observed) == set(expected)
            and all(
                _nested_observation_matches(observed[key], expected[key])
                for key in expected
            )
        )
    if isinstance(expected, list):
        return bool(
            isinstance(observed, list)
            and len(observed) == len(expected)
            and all(
                _nested_observation_matches(left, right)
                for left, right in zip(observed, expected)
            )
        )
    if is_finite_number(expected):
        return bool(
            is_finite_number(observed)
            and np.isclose(
                float(observed),
                float(expected),
                rtol=2.0e-8,
                atol=2.0e-10 * max(abs(float(expected)), np.finfo(float).tiny),
            )
        )
    return observed == expected


def _physics_checks(
    result: SimulationResult,
    model_id: str,
    criteria: dict[str, float],
    expected_contract_status: list[str],
    recomputed_diagnostics: dict[str, Any] | None = None,
) -> tuple[dict[str, bool], float, dict[str, Any]]:
    diagnostics = result.diagnostics
    certified = (
        recomputed_diagnostics
        if isinstance(recomputed_diagnostics, dict)
        else {}
    )
    completed = expected_contract_status == ["COMPLETED"]
    all_fields_finite = _nested_numeric_finite(result.state) and _nested_numeric_finite(
        result.derived
    )
    dynamics_defect = _float_or_nan(
        certified.get("maximum_normalized_dynamics_defect")
    )
    dynamics_cumulative_defect = _float_or_nan(
        certified.get("maximum_normalized_cumulative_dynamics_defect")
    )
    dynamics_absolute_defect = _float_or_nan(
        certified.get("maximum_normalized_absolute_dynamics_defect")
    )
    if model_id == "FWD-CABLE-1.0":
        energy_metric = _finite_max(
            [
                diagnostics.get(
                    "max_relative_energy_power_residual_physical_traction"
                ),
                diagnostics.get(
                    "max_relative_energy_power_residual_algebraic_reaction"
                ),
            ]
        )
        energy_metric = _finite_max(
            [
                certified.get(
                    "max_relative_energy_power_residual_physical_traction"
                ),
                certified.get(
                    "max_relative_energy_power_residual_algebraic_reaction"
                ),
            ]
        )
        dissipations = [
            certified.get("min_D_ax"),
            certified.get("min_D_string"),
            certified.get("min_D_b"),
        ]
        minimum_dissipation = (
            min(float(value) for value in dissipations)
            if len(dissipations) == 3
            and all(_is_finite(value) for value in dissipations)
            else float("nan")
        )
        guard_groups = _cable_guard_groups(
            certified.get("sampled_guard_minima") or {}
        )
        guard_metrics = {
            name: (min(values) if values else None)
            for name, values in guard_groups.items()
        }
        if completed:
            guard_limits = {
                "lambda": criteria["minimum_completed_lambda_margin"],
                "material_lambda": criteria[
                    "minimum_completed_material_lambda_margin"
                ],
                "material_rate": criteria[
                    "minimum_completed_material_rate_margin"
                ],
                "custom": criteria["minimum_completed_custom_guard_margin"],
            }
        else:
            guard_limits = {
                "lambda": -criteria[
                    "maximum_negative_returned_lambda_margin"
                ],
                "material_lambda": -criteria[
                    "maximum_negative_returned_material_lambda_margin"
                ],
                "material_rate": -criteria[
                    "maximum_negative_returned_material_rate_margin"
                ],
                "custom": -criteria[
                    "maximum_negative_returned_custom_guard_margin"
                ],
            }
        guard_checks = {}
        for name in ("lambda", "material_lambda", "material_rate", "custom"):
            metric = guard_metrics[name]
            # A configuration with no optional custom guard has no custom
            # inequality to check.  The three intrinsic groups are mandatory.
            guard_checks[f"{name}_guard_safe"] = bool(
                (name == "custom" and metric is None)
                or (
                    metric is not None
                    and _is_finite(metric)
                    and float(metric) > guard_limits[name]
                )
            )
        mass = certified.get("mass_matrix") or {}
        minimum_eigenvalue = _float_or_nan(mass.get("minimum_eigenvalue"))
        condition_number = _float_or_nan(mass.get("condition_number"))
        symmetry_inf_norm = _float_or_nan(mass.get("symmetry_inf_norm"))
        boundary_reaction_difference = _float_or_nan(
            certified.get("max_boundary_reaction_difference")
        )
        checks = {
            "canonical_fields_finite": bool(all_fields_finite),
            "energy_metric_finite_and_bounded": bool(
                np.isfinite(energy_metric)
                and energy_metric >= 0.0
                and energy_metric <= criteria["maximum_energy_metric"]
            ),
            "dynamics_defect_finite_and_bounded": bool(
                np.isfinite(dynamics_defect)
                and dynamics_defect >= 0.0
                and dynamics_defect
                <= criteria["maximum_normalized_dynamics_defect"]
            ),
            "dynamics_cumulative_defect_finite_and_bounded": bool(
                np.isfinite(dynamics_cumulative_defect)
                and dynamics_cumulative_defect >= 0.0
                and dynamics_cumulative_defect
                <= criteria[
                    "maximum_normalized_cumulative_dynamics_defect"
                ]
            ),
            "dynamics_absolute_defect_finite_and_bounded": bool(
                np.isfinite(dynamics_absolute_defect)
                and dynamics_absolute_defect >= 0.0
                and dynamics_absolute_defect
                <= criteria[
                    "maximum_normalized_absolute_dynamics_defect"
                ]
            ),
            "dissipations_nonnegative_within_tolerance": bool(
                np.isfinite(minimum_dissipation)
                and minimum_dissipation
                >= -criteria["maximum_negative_dissipation"]
            ),
            "no_sampled_guard_violation": diagnostics.get(
                "sampled_guard_violation"
            )
            is None,
            "mass_matrix_positive": bool(
                np.isfinite(minimum_eigenvalue)
                and minimum_eigenvalue
                >= criteria["minimum_mass_eigenvalue"]
            ),
            "mass_matrix_condition_bounded": bool(
                np.isfinite(condition_number)
                and condition_number
                <= criteria["maximum_mass_condition_number"]
            ),
            "mass_matrix_symmetry_bounded": bool(
                np.isfinite(symmetry_inf_norm)
                and symmetry_inf_norm
                <= criteria["maximum_mass_symmetry_inf_norm"]
            ),
            "boundary_reaction_difference_finite": bool(
                np.isfinite(boundary_reaction_difference)
                and boundary_reaction_difference >= 0.0
            ),
            **guard_checks,
        }
        metrics = {
            "energy_metric": energy_metric,
            "maximum_normalized_dynamics_defect": dynamics_defect,
            "maximum_normalized_cumulative_dynamics_defect": (
                dynamics_cumulative_defect
            ),
            "maximum_normalized_absolute_dynamics_defect": (
                dynamics_absolute_defect
            ),
            "minimum_dissipation": minimum_dissipation,
            "guard_minima_by_family": guard_metrics,
            "minimum_mass_eigenvalue": minimum_eigenvalue,
            "mass_condition_number": condition_number,
            "mass_symmetry_inf_norm": symmetry_inf_norm,
            "maximum_boundary_reaction_difference": (
                boundary_reaction_difference
            ),
        }
        return checks, energy_metric, metrics

    energy_metric = _float_or_nan(certified.get("max_relative_energy_drift"))
    geometry_metric = _finite_max(
        [
            certified.get("max_abs_torus_unsquared_residual"),
            certified.get("max_abs_physical_branch_residual"),
        ]
    )
    min_q_t = _float_or_nan(certified.get("min_Q_T"))
    min_R = _float_or_nan(certified.get("minimum_R"))
    min_tension = _float_or_nan(certified.get("minimum_tension"))
    R_limit = (
        criteria["minimum_completed_R"]
        if completed
        else -criteria["maximum_negative_returned_R"]
    )
    tension_limit = (
        criteria["minimum_completed_tension"]
        if completed
        else -criteria["maximum_negative_returned_tension"]
    )
    checks = {
        "canonical_fields_finite": bool(all_fields_finite),
        "energy_metric_finite_and_bounded": bool(
            np.isfinite(energy_metric)
            and energy_metric >= 0.0
            and energy_metric <= criteria["maximum_energy_metric"]
        ),
        "dynamics_defect_finite_and_bounded": bool(
            np.isfinite(dynamics_defect)
            and dynamics_defect >= 0.0
            and dynamics_defect
            <= criteria["maximum_normalized_dynamics_defect"]
        ),
        "dynamics_cumulative_defect_finite_and_bounded": bool(
            np.isfinite(dynamics_cumulative_defect)
            and dynamics_cumulative_defect >= 0.0
            and dynamics_cumulative_defect
            <= criteria[
                "maximum_normalized_cumulative_dynamics_defect"
            ]
        ),
        "dynamics_absolute_defect_finite_and_bounded": bool(
            np.isfinite(dynamics_absolute_defect)
            and dynamics_absolute_defect >= 0.0
            and dynamics_absolute_defect
            <= criteria[
                "maximum_normalized_absolute_dynamics_defect"
            ]
        ),
        "geometry_residuals_bounded": bool(
            np.isfinite(geometry_metric)
            and geometry_metric <= criteria["maximum_abs_geometry_residual"]
        ),
        "Q_T_on_physical_branch": bool(
            np.isfinite(min_q_t)
            and min_q_t >= -criteria["maximum_negative_Q_T"]
        ),
        "returned_R_safe": bool(np.isfinite(min_R) and min_R > R_limit),
        "returned_tensions_safe": bool(
            np.isfinite(min_tension) and min_tension > tension_limit
        ),
        "no_postrun_failure": diagnostics.get("postrun_failure") is None,
    }
    metrics = {
        "energy_metric": energy_metric,
        "maximum_normalized_dynamics_defect": dynamics_defect,
        "maximum_normalized_cumulative_dynamics_defect": (
            dynamics_cumulative_defect
        ),
        "maximum_normalized_absolute_dynamics_defect": (
            dynamics_absolute_defect
        ),
        "maximum_abs_geometry_residual": geometry_metric,
        "minimum_Q_T": min_q_t,
        "minimum_returned_R": min_R,
        "minimum_returned_tension": min_tension,
    }
    return checks, energy_metric, metrics


def _cable_guard_groups(values: dict[str, Any]) -> dict[str, list[float]]:
    groups: dict[str, list[float]] = {
        "lambda": [],
        "material_lambda": [],
        "material_rate": [],
        "custom": [],
    }
    for name, value in values.items():
        if not _is_finite(value):
            groups["lambda"].append(float("nan"))
            continue
        if name.startswith("lambda_min:"):
            group = "lambda"
        elif name.startswith("material:") and any(
            boundary in name for boundary in (":lambda_lower", ":lambda_upper")
        ):
            group = "material_lambda"
        elif name.startswith("material:") and any(
            boundary in name for boundary in (":rate_lower", ":rate_upper")
        ):
            group = "material_rate"
        elif name.startswith("custom:"):
            group = "custom"
        else:
            groups["lambda"].append(float("nan"))
            continue
        groups[group].append(float(value))
    return groups


def _compare(
    first: SimulationResult,
    second: SimulationResult,
    *,
    model_id: str,
    comparison_time_step: float,
    material_comparison_points: int,
) -> dict[str, Any]:
    end = min(float(first.tau), float(second.tau))
    event_difference = abs(float(first.tau) - float(second.tau))
    times = _comparison_times(first, second, end, comparison_time_step)
    result: dict[str, Any] = {}
    metric_names = list(_metric_threshold_map({}, model_id, names_only=True))
    for name in metric_names:
        result[name] = float("nan")
    result.update(
        common_end=end,
        event_time_difference=event_difference,
        comparison_sample_count=int(times.size),
    )
    if not times.size:
        try:
            _merge_event_left_errors(
                result, first, second, model_id, material_comparison_points
            )
        except (KeyError, TypeError, ValueError, IndexError):
            pass
        return result
    try:
        first_bob = _position_field(first, "r_m", times)
        second_bob = _position_field(second, "r_m", times)
        result.update(
            _error_pair("bob_position", first_bob - second_bob, vector=True)
        )
        if model_id == "FWD-TORUS-1.0":
            first_state = _time_interp(
                _strict_array(first.state.get("X_torus")), first.time, times
            )
            second_state = _time_interp(
                _strict_array(second.state.get("X_torus")), second.time, times
            )
            angle_difference = _wrap_angle(
                first_state[:, :2] - second_state[:, :2]
            )
            result.update(_error_pair("angle", angle_difference, vector=True))
            result.update(
                _error_pair(
                    "angular_rate",
                    first_state[:, 2:] - second_state[:, 2:],
                    vector=True,
                )
            )
            first_tension = np.column_stack(
                [
                    _time_interp(
                        _strict_array(first.derived.get(name)), first.time, times
                    )
                    for name in ("T_A", "T_B", "T_lower")
                ]
            )
            second_tension = np.column_stack(
                [
                    _time_interp(
                        _strict_array(second.derived.get(name)), second.time, times
                    )
                    for name in ("T_A", "T_B", "T_lower")
                ]
            )
            result.update(
                _error_pair(
                    "tension", first_tension - second_tension, vector=True
                )
            )
            first_energy = _time_interp(
                _strict_array(first.derived.get("E_torus")), first.time, times
            )
            second_energy = _time_interp(
                _strict_array(second.derived.get("E_torus")), second.time, times
            )
            result.update(
                _error_pair(
                    "energy", first_energy - second_energy, vector=False
                )
            )
            _merge_event_left_errors(
                result, first, second, model_id, material_comparison_points
            )
            return result

        first_bob_velocity = _position_field(first, "v_m", times)
        second_bob_velocity = _position_field(second, "v_m", times)
        first_junction = _position_field(first, "r_J", times)
        second_junction = _position_field(second, "r_J", times)
        first_junction_velocity = _position_field(first, "v_J", times)
        second_junction_velocity = _position_field(second, "v_J", times)
        result.update(
            _error_pair(
                "bob_velocity",
                first_bob_velocity - second_bob_velocity,
                vector=True,
            )
        )
        result.update(
            _error_pair(
                "junction_position",
                first_junction - second_junction,
                vector=True,
            )
        )
        result.update(
            _error_pair(
                "junction_velocity",
                first_junction_velocity - second_junction_velocity,
                vector=True,
            )
        )
        points = np.linspace(0.0, 1.0, material_comparison_points)
        for output_name, state_name in (
            ("cable_position", "node_positions"),
            ("cable_velocity", "node_velocities"),
        ):
            first_field = _cable_nodal_field(first, state_name, times, points)
            second_field = _cable_nodal_field(second, state_name, times, points)
            result.update(
                _error_pair(
                    output_name, first_field - second_field, vector=True
                )
            )
        for output_name, derived_name in (
            ("stretch", "lambda"),
            ("stretch_rate", "lambda_dot"),
            ("tension", "N"),
        ):
            first_field = _cable_element_field(
                first, derived_name, times, points
            )
            second_field = _cable_element_field(
                second, derived_name, times, points
            )
            result.update(
                _error_pair(
                    output_name, first_field - second_field, vector=False
                )
            )
        first_energy = _time_interp(
            _strict_array(first.derived.get("E_F")), first.time, times
        )
        second_energy = _time_interp(
            _strict_array(second.derived.get("E_F")), second.time, times
        )
        result.update(
            _error_pair("energy", first_energy - second_energy, vector=False)
        )
        for output_name, field_names in (
            ("dissipation_power", ("D_ax", "D_string", "D_b")),
            ("input_power", ("P_base", "P_air", "P_ext")),
        ):
            first_values = np.column_stack(
                [
                    _time_interp(
                        _strict_array(first.derived.get(name)), first.time, times
                    )
                    for name in field_names
                ]
            )
            second_values = np.column_stack(
                [
                    _time_interp(
                        _strict_array(second.derived.get(name)), second.time, times
                    )
                    for name in field_names
                ]
            )
            result.update(
                _error_pair(
                    output_name,
                    first_values - second_values,
                    vector=True,
                )
            )
    except (KeyError, TypeError, ValueError, IndexError):
        # Missing/malformed canonical data is represented by NaN metrics, which
        # fail every threshold instead of being silently ignored.
        return result
    try:
        _merge_event_left_errors(
            result, first, second, model_id, material_comparison_points
        )
    except (KeyError, TypeError, ValueError, IndexError):
        pass
    return result


def _merge_event_left_errors(
    comparison: dict[str, Any],
    first: SimulationResult,
    second: SimulationResult,
    model_id: str,
    material_comparison_points: int,
) -> None:
    event_errors = _event_left_errors(
        first, second, model_id, material_comparison_points
    )
    comparison["event_left_errors"] = event_errors
    for name, value in event_errors.items():
        current = comparison.get(name)
        if _is_finite(value) and float(value) >= 0.0:
            comparison[name] = (
                max(float(current), float(value))
                if _is_finite(current) and float(current) >= 0.0
                else float(value)
            )


def _event_left_errors(
    first: SimulationResult,
    second: SimulationResult,
    model_id: str,
    material_comparison_points: int,
) -> dict[str, float]:
    if not (
        first.contract_status == ["OUT_OF_SCOPE"]
        and second.contract_status == ["OUT_OF_SCOPE"]
        and len(first.events) == 1
        and len(second.events) == 1
        and isinstance(first.events[0], dict)
        and isinstance(second.events[0], dict)
    ):
        return {}
    first_event = first.events[0]
    second_event = second.events[0]
    output: dict[str, float] = {}
    if model_id == "FWD-TORUS-1.0":
        first_state = _strict_array(first_event.get("state_left"))
        second_state = _strict_array(second_event.get("state_left"))
        if first_state.shape != (4,) or second_state.shape != (4,):
            raise ValueError("malformed torus event state")
        output.update(
            _error_pair(
                "angle",
                _wrap_angle(first_state[:2] - second_state[:2])[None, :],
                vector=True,
            )
        )
        output.update(
            _error_pair(
                "angular_rate",
                (first_state[2:] - second_state[2:])[None, :],
                vector=True,
            )
        )
        first_derived = first_event.get("derived_left")
        second_derived = second_event.get("derived_left")
        if not isinstance(first_derived, dict) or not isinstance(second_derived, dict):
            raise ValueError("malformed torus event derived output")
        output.update(
            _error_pair(
                "bob_position",
                (
                    _strict_array(first_derived.get("r_m"))
                    - _strict_array(second_derived.get("r_m"))
                )[None, :],
                vector=True,
            )
        )
        output.update(
            _error_pair(
                "tension",
                np.asarray(
                    [
                        float(first_derived[name]) - float(second_derived[name])
                        for name in ("T_A", "T_B", "T_lower")
                    ]
                )[None, :],
                vector=True,
            )
        )
        output.update(
            _error_pair(
                "energy",
                np.asarray(
                    [
                        float(first_derived["E_torus"])
                        - float(second_derived["E_torus"])
                    ]
                ),
                vector=False,
            )
        )
        return output

    if model_id != "FWD-CABLE-1.0":
        raise ValueError("unknown event comparison model")
    first_state = first_event.get("state_left")
    second_state = second_event.get("state_left")
    if not isinstance(first_state, dict) or not isinstance(second_state, dict):
        raise ValueError("malformed cable event state")
    first_positions = _strict_array(first_state.get("positions"))
    second_positions = _strict_array(second_state.get("positions"))
    first_velocities = _strict_array(first_state.get("velocities"))
    second_velocities = _strict_array(second_state.get("velocities"))
    first_ids = first.metadata.get("node_ids")
    second_ids = second.metadata.get("node_ids")
    if not isinstance(first_ids, list) or not isinstance(second_ids, list):
        raise ValueError("missing cable node identities")
    first_index = {name: index for index, name in enumerate(first_ids)}
    second_index = {name: index for index, name in enumerate(second_ids)}
    for prefix, name, vector in (
        ("bob_position", "bob", True),
        ("junction_position", "junction", True),
    ):
        output.update(
            _error_pair(
                prefix,
                (
                    first_positions[first_index[name]]
                    - second_positions[second_index[name]]
                )[None, :],
                vector=vector,
            )
        )
    for prefix, name in (
        ("bob_velocity", "bob"),
        ("junction_velocity", "junction"),
    ):
        output.update(
            _error_pair(
                prefix,
                (
                    first_velocities[first_index[name]]
                    - second_velocities[second_index[name]]
                )[None, :],
                vector=True,
            )
        )
    points = np.linspace(0.0, 1.0, material_comparison_points)
    first_nodal = first.metadata.get("branch_nodes")
    second_nodal = second.metadata.get("branch_nodes")
    for prefix, first_values, second_values in (
        ("cable_position", first_positions, second_positions),
        ("cable_velocity", first_velocities, second_velocities),
    ):
        first_field = _event_nodal_material_field(
            first_values, first_nodal, points
        )
        second_field = _event_nodal_material_field(
            second_values, second_nodal, points
        )
        output.update(
            _error_pair(
                prefix,
                (first_field - second_field)[None, :, :],
                vector=True,
            )
        )
    first_derived = first_event.get("derived_left")
    second_derived = second_event.get("derived_left")
    if not isinstance(first_derived, dict) or not isinstance(second_derived, dict):
        raise ValueError("malformed cable event derived output")
    for prefix, field in (
        ("stretch", "lambda"),
        ("stretch_rate", "lambda_dot"),
        ("tension", "N"),
    ):
        first_field = _event_element_material_field(
            first_derived, field, points
        )
        second_field = _event_element_material_field(
            second_derived, field, points
        )
        output.update(
            _error_pair(
                prefix, first_field - second_field, vector=False
            )
        )
    output.update(
        _error_pair(
            "energy",
            np.asarray(
                [float(first_derived["E_F"]) - float(second_derived["E_F"])]
            ),
            vector=False,
        )
    )
    for prefix, names in (
        ("dissipation_power", ("D_ax", "D_string", "D_b")),
        ("input_power", ("P_base", "P_air", "P_ext")),
    ):
        difference = np.asarray(
            [float(first_derived[name]) - float(second_derived[name]) for name in names]
        )
        output.update(
            _error_pair(prefix, difference[None, :], vector=True)
        )
    return output


def _event_nodal_material_field(
    values: np.ndarray, branch_nodes: Any, points: np.ndarray
) -> np.ndarray:
    if not isinstance(branch_nodes, dict) or set(branch_nodes) != set(BRANCHES):
        raise ValueError("invalid event branch topology")
    output = []
    for branch in BRANCHES:
        nodes = np.asarray(branch_nodes[branch], dtype=int)
        source = np.linspace(0.0, 1.0, nodes.size)
        field = np.column_stack(
            [np.interp(points, source, values[nodes, coordinate]) for coordinate in range(3)]
        )
        output.append(field)
    return np.concatenate(output, axis=0)


def _event_element_material_field(
    derived: dict[str, Any], field: str, points: np.ndarray
) -> np.ndarray:
    branches = derived.get("branches")
    if not isinstance(branches, dict) or set(branches) != set(BRANCHES):
        raise ValueError("invalid event branch fields")
    output = []
    for branch in BRANCHES:
        values = _strict_array(branches[branch].get(field))
        if values.ndim != 1 or values.size < 1:
            raise ValueError("invalid event element field")
        cell = np.minimum(
            np.floor(points * values.size).astype(int), values.size - 1
        )
        output.append(values[cell])
    return np.concatenate(output)


def _comparison_times(
    first: SimulationResult,
    second: SimulationResult,
    end: float,
    step: float,
) -> np.ndarray:
    if (
        not is_finite_number(end)
        or end <= 0.0
        or not first.time.size
        or not second.time.size
    ):
        return np.empty(0)
    completed = (
        first.contract_status == ["COMPLETED"]
        and second.contract_status == ["COMPLETED"]
    )
    count = int(np.floor(end / step + 1e-13)) + 1
    times = step * np.arange(count)
    if completed and (
        not times.size
        or times[-1] < end - 1e-13 * max(1.0, abs(end))
    ):
        times = np.append(times, end)
    if not completed:
        times = times[times < end]
    if not times.size:
        return times
    tolerance = 1e-12 * max(1.0, abs(end))
    if (
        times[-1] > float(first.time[-1]) + tolerance
        or times[-1] > float(second.time[-1]) + tolerance
    ):
        return np.empty(0)
    return times


def _position_field(
    result: SimulationResult, name: str, times: np.ndarray
) -> np.ndarray:
    source = result.state.get(name)
    if source is None:
        source = result.derived.get(name)
    values = _strict_array(source)
    interpolated = _time_interp(values, result.time, times)
    if interpolated.shape != (times.size, 3):
        raise ValueError(name)
    return interpolated


def _time_interp(
    values: np.ndarray, source_time: np.ndarray, target_time: np.ndarray
) -> np.ndarray:
    source_time = _strict_array(source_time)
    if (
        values.ndim < 1
        or values.shape[0] != source_time.size
        or source_time.ndim != 1
        or not source_time.size
        or not np.all(np.isfinite(values))
        or not np.all(np.isfinite(source_time))
        or np.any(np.diff(source_time) <= 0.0)
    ):
        raise ValueError("malformed time series")
    flat = values.reshape(values.shape[0], -1)
    output = np.column_stack(
        [np.interp(target_time, source_time, flat[:, index]) for index in range(flat.shape[1])]
    )
    return output.reshape((target_time.size,) + values.shape[1:])


def _cable_nodal_field(
    result: SimulationResult,
    state_name: str,
    times: np.ndarray,
    material_points: np.ndarray,
) -> np.ndarray:
    values = _strict_array(result.state.get(state_name))
    branch_nodes = result.metadata.get("branch_nodes")
    if not isinstance(branch_nodes, dict) or set(branch_nodes) != set(BRANCHES):
        raise ValueError("missing branch topology")
    branches = []
    for branch in BRANCHES:
        nodes = np.asarray(branch_nodes[branch], dtype=int)
        if nodes.ndim != 1 or nodes.size < 2:
            raise ValueError("invalid branch topology")
        timed = _time_interp(values[:, nodes, :], result.time, times)
        source_points = np.linspace(0.0, 1.0, nodes.size)
        interpolated = np.empty((times.size, material_points.size, 3))
        for time_index in range(times.size):
            for coordinate in range(3):
                interpolated[time_index, :, coordinate] = np.interp(
                    material_points,
                    source_points,
                    timed[time_index, :, coordinate],
                )
        branches.append(interpolated)
    return np.concatenate(branches, axis=1)


def _cable_element_field(
    result: SimulationResult,
    field_name: str,
    times: np.ndarray,
    material_points: np.ndarray,
) -> np.ndarray:
    branches_raw = result.derived.get("branches")
    if not isinstance(branches_raw, dict) or set(branches_raw) != set(BRANCHES):
        raise ValueError("missing branch derived fields")
    output = []
    for branch in BRANCHES:
        raw = branches_raw[branch]
        if not isinstance(raw, dict):
            raise ValueError(branch)
        values = _strict_array(raw.get(field_name))
        timed = _time_interp(values, result.time, times)
        if timed.ndim != 2 or timed.shape[1] < 1:
            raise ValueError(field_name)
        # P1 kinematics makes lambda, lambda_dot, and tension piecewise
        # constant per element.  Compare that actual discrete field instead of
        # smoothing cell values between element centers.  Interfaces use a
        # fixed right trace; S=1 is assigned to the final cell.
        cell_index = np.minimum(
            np.floor(material_points * timed.shape[1]).astype(int),
            timed.shape[1] - 1,
        )
        interpolated = timed[:, cell_index]
        output.append(interpolated)
    return np.concatenate(output, axis=1)


def _error_pair(prefix: str, difference: np.ndarray, *, vector: bool) -> dict[str, float]:
    difference = _strict_array(difference)
    if not difference.size or not np.all(np.isfinite(difference)):
        return {
            f"rms_{prefix}": float("nan"),
            f"max_{prefix}": float("nan"),
        }
    magnitudes = (
        np.linalg.norm(difference, axis=-1) if vector else np.abs(difference)
    )
    return {
        f"rms_{prefix}": float(np.sqrt(np.mean(magnitudes * magnitudes))),
        f"max_{prefix}": float(np.max(magnitudes)),
    }


def _wrap_angle(value: np.ndarray) -> np.ndarray:
    return (value + np.pi) % (2.0 * np.pi) - np.pi


def _metric_threshold_map(
    criterion: dict[str, Any], model_id: str, *, names_only: bool = False
) -> dict[str, float] | list[str]:
    fields = {
        "rms_bob_position": "max_finest_rms_bob_position",
        "max_bob_position": "max_finest_max_bob_position",
        "event_time_difference": "max_finest_event_time_difference",
    }
    if model_id == "FWD-CABLE-1.0":
        for name in (
            "bob_velocity",
            "junction_position",
            "junction_velocity",
            "cable_position",
            "cable_velocity",
            "stretch",
            "stretch_rate",
            "tension",
            "energy",
            "dissipation_power",
            "input_power",
        ):
            fields[f"rms_{name}"] = f"max_finest_rms_{name}"
            fields[f"max_{name}"] = f"max_finest_max_{name}"
    else:
        for name in ("angle", "angular_rate", "tension", "energy"):
            fields[f"rms_{name}"] = f"max_finest_rms_{name}"
            fields[f"max_{name}"] = f"max_finest_max_{name}"
    if names_only:
        return list(fields)
    return {metric: float(criterion[field]) for metric, field in fields.items()}


def _decreases_or_at_floor(
    values: list[float], ratio_slack: float, floor: float
) -> bool:
    if len(values) < 2 or not all(
        np.isfinite(value) and value >= 0.0 for value in values
    ):
        return False
    return all(
        fine <= coarse * ratio_slack or (coarse <= floor and fine <= floor)
        for coarse, fine in zip(values[:-1], values[1:])
    )


def _dynamics_trend_checks(
    study_name: str,
    values_by_field: dict[str, list[float]],
    thresholds: dict[str, float],
    ratio_slack: float,
    normalized_floor: float,
) -> dict[str, bool]:
    """Check each independent dynamics certificate across time levels.

    A maximum over the three normalized certificates is useful for display but
    is not a valid trend gate: a non-dominant cumulative certificate could then
    deteriorate unnoticed.  Each field is therefore normalized by its own
    frozen threshold and checked separately.
    """

    checks: dict[str, bool] = {}
    for field, values in values_by_field.items():
        threshold = thresholds.get(field)
        if (
            not _is_finite(threshold)
            or float(threshold) <= 0.0
            or not isinstance(values, list)
        ):
            checks[field] = False
            continue
        normalized = [
            float(value) / float(threshold)
            if _is_finite(value) and float(value) >= 0.0
            else float("nan")
            for value in values
        ]
        checks[field] = bool(
            study_name != "time"
            or _decreases_or_at_floor(
                normalized, ratio_slack, normalized_floor
            )
        )
    return checks


def _refinement_level_physics_checks(
    checks: dict[str, bool],
    metrics: dict[str, Any],
    *,
    is_finest: bool,
) -> dict[str, bool]:
    """Apply absolute accuracy bounds only to the qualified finest level.

    Deliberately coarse levels exist to expose convergence.  Requiring them to
    satisfy the production accuracy bound would reject a valid decreasing
    sequence for the very reason refinement is being performed.  Coarse
    levels still have to satisfy every structural/physical check, and their
    energy plus three dynamics certificates must remain nonnegative and
    finite so that the independent three-level trend gates are meaningful.
    """

    if is_finest:
        return dict(checks)
    applied = {
        name: bool(value)
        for name, value in checks.items()
        if name not in FINEST_ONLY_ACCURACY_CHECKS
    }
    applied["coarse_accuracy_metrics_nonnegative_finite"] = all(
        _is_finite(metrics.get(field)) and float(metrics[field]) >= 0.0
        for field in ACCURACY_METRIC_FIELDS
    )
    return applied


def _nested_numeric_finite(value: Any) -> bool:
    if isinstance(value, dict):
        return all(_nested_numeric_finite(child) for child in value.values())
    try:
        array = np.asarray(value)
    except (TypeError, ValueError):
        return False
    return array.dtype != object and bool(np.all(np.isfinite(array)))


def _strict_array(value: Any) -> np.ndarray:
    try:
        array = np.asarray(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("not an array") from exc
    if array.dtype == object or not np.issubdtype(array.dtype, np.number):
        raise ValueError("not a numeric array")
    return np.asarray(array, dtype=float)


def _finite_max(values: list[Any]) -> float:
    if not values or not all(_is_finite(value) for value in values):
        return float("nan")
    return max(float(value) for value in values)


def _is_finite(value: Any) -> bool:
    return is_finite_number(value)


def _float_or_nan(value: Any) -> float:
    return float(value) if _is_finite(value) else float("nan")


def _finite_number(
    value: Any,
    path: str,
    errors: list[dict[str, Any]],
    *,
    minimum: float,
    strict: bool,
) -> float:
    if not is_finite_number(value):
        errors.append(_validation_error(path, value, "finite JSON real number"))
        return 0.0
    number = float(value)
    valid = number > minimum if strict else number >= minimum
    if not valid:
        relation = ">" if strict else ">="
        errors.append(_validation_error(path, value, f"{relation} {minimum}"))
    return number


def _reject_unknown(
    mapping: dict[str, Any],
    allowed: set[str],
    path: str,
    errors: list[dict[str, Any]],
) -> None:
    for key in sorted(set(mapping) - allowed):
        errors.append(
            _validation_error(
                f"{path}.{key}", mapping[key], f"one of {sorted(allowed)}"
            )
        )


def _validation_error(path: str, actual: Any, expected: str) -> dict[str, Any]:
    return {"path": path, "actual": actual, "expected": expected}


def _invalid_report(
    model_id: Any, qualification: str, errors: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "qualification": qualification,
        "model_id": model_id,
        "validation_errors": errors,
        "studies": {},
    }

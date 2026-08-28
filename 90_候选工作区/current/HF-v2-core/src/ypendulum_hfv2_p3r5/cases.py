"""P3R5 observed-development, holdout and qualification case construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ypendulum_hfv2.statics.contracts import StaticSeed
from ypendulum_hfv2_p3r3.cases import (
    _assembly_kwargs,
    _historical_contract,
    _static_assembly,
)

from . import (
    P3R5_ACTUAL_MULTISEED_ID,
    P3R5_MANIFOLD_RETRACTION_ID,
    P3R5_REFERENCE_CONSTRUCTOR_ID,
    P3R5_SECOND_ORDER_ID,
    P3R5_TARGET_ADMISSIBILITY_ID,
)
from .assembly import P3R5ContactAssembly
from .domain import canonical_sha256


@dataclass(frozen=True)
class P3R5DesignCase:
    design_id: str
    category: str
    assembly: P3R5ContactAssembly
    initial_coordinates: object
    declared_active_constraint_ids: tuple[str, ...]
    contract: dict[str, Any]


@dataclass(frozen=True)
class P3R5CaseExpectation:
    reference_coordinates: np.ndarray
    near_active_constraint_ids: tuple[str, ...]
    supported_constraint_ids: tuple[str, ...]
    supported_multipliers_N: np.ndarray
    near_active_rank: int
    supported_rank: int


@dataclass(frozen=True)
class P3R5StaticContactCase:
    case_id: str
    role: str
    assembly: P3R5ContactAssembly
    seeds: tuple[StaticSeed, ...]
    expectation: P3R5CaseExpectation
    contract: dict[str, Any]


def _assert_physical_numerics_match(
    manifest: dict[str, Any],
    predecessor_manifest: dict[str, Any],
) -> None:
    for key in ("geometry_tolerances", "assembly_numerics"):
        if manifest[key] != predecessor_manifest[key]:
            raise ValueError(f"P3R5 {key} must remain byte-value equal to P3R4.")


def _declared_ids(contract: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        contract.get(
            "declared_active_constraint_ids",
            (
                "bob:upper_A:upper_A_s000",
                "bob:upper_B:upper_B_s000",
            ),
        )
    )


def build_design_case(
    manifest: dict[str, Any],
    predecessor_manifest: dict[str, Any],
    contract: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> P3R5DesignCase:
    _assert_physical_numerics_match(manifest, predecessor_manifest)
    analytic = np.asarray(contract["analytic_stationary_bob_position_m"], dtype=float)
    base = _static_assembly(contract, analytic)
    assembly = P3R5ContactAssembly(
        **_assembly_kwargs(
            manifest,
            contract,
            base,
            adapter_contract_sha256=adapter_contract_sha256,
            frozen_protocol_sha256=frozen_protocol_sha256,
        )
    )
    initial = assembly.coordinates_from_values(np.concatenate([analytic, np.zeros(3)]))
    design_id = str(contract.get("holdout_id", contract["design_id"]))
    return P3R5DesignCase(
        design_id=design_id,
        category=str(contract["category"]),
        assembly=assembly,
        initial_coordinates=initial,
        declared_active_constraint_ids=_declared_ids(contract),
        contract=contract,
    )


def build_design_cases(
    manifest: dict[str, Any],
    predecessor_manifest: dict[str, Any],
    cards: list[dict[str, Any]],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> tuple[P3R5DesignCase, ...]:
    return tuple(
        build_design_case(
            manifest,
            predecessor_manifest,
            contract,
            adapter_contract_sha256=adapter_contract_sha256,
            frozen_protocol_sha256=frozen_protocol_sha256,
        )
        for contract in cards
    )


def build_case_from_contract(
    manifest: dict[str, Any],
    contract: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> P3R5StaticContactCase:
    reference = np.asarray(contract["expected_reference_coordinates"], dtype=float)
    if reference.shape != (6,):
        raise ValueError("P3R5 target reference must contain six coordinates.")
    base = _static_assembly(contract, reference[:3])
    assembly = P3R5ContactAssembly(
        **_assembly_kwargs(
            manifest,
            contract,
            base,
            adapter_contract_sha256=adapter_contract_sha256,
            frozen_protocol_sha256=frozen_protocol_sha256,
        )
    )
    seeds = tuple(
        StaticSeed(
            seed_id=str(seed_contract["seed_id"]),
            free_node_ids=(),
            free_node_positions=np.empty((0, 3)),
            bob_position=reference[:3] + np.asarray(seed_contract["bob_offset_m"], dtype=float),
            bob_rotation_vector=np.asarray(seed_contract["rotation_vector_rad"], dtype=float),
        )
        for seed_contract in contract["deterministic_solver_initial_guesses"]
    )
    supported_ids = tuple(contract["expected_supported_constraint_ids"])
    multiplier_contract = contract["expected_supported_multipliers_N"]
    if set(multiplier_contract) != set(supported_ids):
        raise ValueError("P3R5 multiplier identities must match support identities.")
    return P3R5StaticContactCase(
        case_id=str(contract["case_id"]),
        role=str(contract["role"]),
        assembly=assembly,
        seeds=seeds,
        expectation=P3R5CaseExpectation(
            reference_coordinates=np.array(reference, copy=True),
            near_active_constraint_ids=tuple(contract["expected_near_active_constraint_ids"]),
            supported_constraint_ids=supported_ids,
            supported_multipliers_N=np.asarray(
                [float(multiplier_contract[item]) for item in supported_ids]
            ),
            near_active_rank=int(contract["expected_near_active_rank"]),
            supported_rank=int(contract["expected_supported_rank"]),
        ),
        contract=contract,
    )


def build_historical_cases(
    manifest: dict[str, Any],
    p3r2_manifest: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> tuple[P3R5StaticContactCase, P3R5StaticContactCase]:
    converted = []
    for key in ("observed_symmetric_regression", "observed_p3r_35_degree_regression"):
        contract = _historical_contract(p3r2_manifest[key])
        contract["deterministic_solver_initial_guesses"] = contract.pop("deterministic_seeds")
        converted.append(
            build_case_from_contract(
                manifest,
                contract,
                adapter_contract_sha256=adapter_contract_sha256,
                frozen_protocol_sha256=frozen_protocol_sha256,
            )
        )
    return converted[0], converted[1]


def build_qualification_targets(
    manifest: dict[str, Any],
    target_freeze: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> tuple[P3R5StaticContactCase, ...]:
    return tuple(
        build_case_from_contract(
            manifest,
            contract,
            adapter_contract_sha256=adapter_contract_sha256,
            frozen_protocol_sha256=frozen_protocol_sha256,
        )
        for contract in target_freeze["qualification_targets"]
    )


def select_admissible_holdouts(
    outcomes: list[dict[str, Any]],
    required_categories: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    selected = {}
    for category in required_categories:
        candidates = sorted(
            (
                item
                for item in outcomes
                if item["category"] == category and item["status"] == "ADMISSIBLE"
            ),
            key=lambda item: item["holdout_id"],
        )
        if candidates:
            selected[category] = candidates[0]
    return selected


def build_admissibility_selection(
    manifest: dict[str, Any],
    holdout_freeze: dict[str, Any],
    outcomes: list[dict[str, Any]],
    *,
    implementation_commit: str,
    holdout_freeze_commit: str,
    attempt_ledger_sha256: str,
    generated_at: str,
) -> dict[str, Any]:
    categories = tuple(manifest["holdout_design_and_selection"]["required_categories"])
    frozen_order = [item["holdout_id"] for item in holdout_freeze["holdout_cards"]]
    all_attempted_once = bool(
        [item["holdout_id"] for item in outcomes] == frozen_order
        and all(item["input_assembly_execution_count"] == 1 for item in outcomes)
    )
    protocol_failure = any(
        item["status"] == manifest["protocol_construction_fail_status"] for item in outcomes
    )
    internal = any(item["status"] == manifest["certifier_internal_status"] for item in outcomes)
    selected = select_admissible_holdouts(outcomes, categories)
    complete = all_attempted_once and len(selected) == len(categories)
    if protocol_failure:
        status = manifest["protocol_construction_fail_status"]
        selected = {}
    elif internal:
        status = manifest["certifier_internal_status"]
        selected = {}
    elif complete:
        status = "TARGETS_ADMISSIBLE_PENDING_SEPARATE_FREEZE"
    else:
        status = manifest["target_suite_fail_status"]
        selected = {}
    return {
        "schema": "YPS-HFV2-P3R5-ADMISSIBILITY-SELECTION-1.0",
        "generated_at": generated_at,
        "implementation_commit": implementation_commit,
        "holdout_freeze_commit": holdout_freeze_commit,
        "attempt_ledger_sha256": attempt_ledger_sha256,
        "reference_constructor_identity": P3R5_REFERENCE_CONSTRUCTOR_ID,
        "target_admissibility_identity": P3R5_TARGET_ADMISSIBILITY_ID,
        "second_order_identity": P3R5_SECOND_ORDER_ID,
        "manifold_retraction_identity": P3R5_MANIFOLD_RETRACTION_ID,
        "selection_rule": manifest["holdout_design_and_selection"]["target_selection_rule"],
        "all_holdout_cards_executed_exactly_once": all_attempted_once,
        "selected_holdout_ids": {
            category: selected[category]["holdout_id"] for category in selected
        },
        "selected_admissibility_record_sha256": {
            category: canonical_sha256(selected[category]) for category in selected
        },
        "admissibility_payload_sha256": canonical_sha256(outcomes),
        "status": status,
        "target_freeze_generated": False,
        "qualification_seed_results_observed_before_separate_target_freeze": 0,
        "qualification_seed_execution_counts_before_separate_target_freeze": {},
    }


def _qualification_seeds(
    reference: np.ndarray,
    basis: np.ndarray,
    coordinate_scales: np.ndarray,
    *,
    radius: float,
    radius_fraction: float,
    holdout_id: str,
) -> list[dict[str, Any]]:
    first = basis[:, 0] + basis[:, 1]
    first /= np.linalg.norm(first)
    second = basis[:, 0] - basis[:, 2]
    second /= np.linalg.norm(second)
    directions = (np.zeros(6), first, -second)
    labels = ("reference", "first_noncollinear_positive", "second_noncollinear_negative")
    roles = (
        "reference_solver_initial_guess",
        "solver_initial_guess_allowed_off_manifold",
        "solver_initial_guess_allowed_off_manifold",
    )
    seeds = []
    for index, (label, role, direction) in enumerate(zip(labels, roles, directions, strict=True)):
        values = reference + radius_fraction * radius * coordinate_scales * direction
        seeds.append(
            {
                "seed_id": f"{holdout_id}_qualification_{index:02d}_{label}",
                "seed_role": role,
                "pre_retraction_required": False,
                "bob_offset_m": (values[:3] - reference[:3]).tolist(),
                "rotation_vector_rad": values[3:].tolist(),
                "dimensionless_offset": ((values - reference) / coordinate_scales).tolist(),
                "dimensionless_radius": float(
                    np.linalg.norm((values - reference) / coordinate_scales)
                ),
            }
        )
    return seeds


def _target_contract(
    holdout_contract: dict[str, Any],
    outcome: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    excluded = {
        "pure_constructibility",
        "input_assembly_execution_count_before_holdout_freeze",
        "reference_construction_execution_count_before_holdout_freeze",
        "target_admissibility_execution_count_before_holdout_freeze",
        "second_order_execution_count_before_holdout_freeze",
        "manifold_neighborhood_execution_count_before_holdout_freeze",
        "qualification_seed_execution_count_before_holdout_freeze",
    }
    contract = {key: value for key, value in holdout_contract.items() if key not in excluded}
    reference = np.asarray(outcome["reference_coordinates"], dtype=float)
    scales = np.asarray(outcome["characteristic_scales"]["coordinate_scales"], dtype=float)
    basis = np.asarray(outcome["manifold_neighborhood"]["tangent_basis"], dtype=float)
    radius = float(manifest["manifold_neighborhood"]["coordinate_radius_dimensionless"])
    radius_fraction = float(
        manifest["actual_multiseed_attraction"]["qualification_seed_radius_fraction"]
    )
    supported_ids = tuple(outcome["supported_ids"])
    active_values = outcome["dual_certificate"]["canonical_active_multipliers_N"]
    multiplier_map = {
        identity: float(value) for identity, value in zip(supported_ids, active_values, strict=True)
    }
    branch_identity = canonical_sha256(
        {
            "holdout_id": outcome["holdout_id"],
            "assembly_token": outcome["contact_assembly_token"],
            "reference_coordinates": reference.tolist(),
            "supported_ids": supported_ids,
            "tangent_basis": basis.tolist(),
            "manifold_radius": radius,
            "reference_constructor_identity": P3R5_REFERENCE_CONSTRUCTOR_ID,
            "second_order_identity": P3R5_SECOND_ORDER_ID,
            "manifold_retraction_identity": P3R5_MANIFOLD_RETRACTION_ID,
        }
    )
    contract.update(
        {
            "case_id": f"P3R5_{outcome['holdout_id']}_HOLDOUT_TARGET",
            "role": "new_unobserved_P3R5_holdout_static_contact_target_not_apparatus_prediction",
            "branch_identity_sha256": branch_identity,
            "expected_reference_coordinates": reference.tolist(),
            "expected_near_active_constraint_ids": list(outcome["near_active_ids"]),
            "expected_supported_constraint_ids": list(supported_ids),
            "expected_supported_multipliers_N": multiplier_map,
            "expected_near_active_rank": int(outcome["near_active_rank"]),
            "expected_supported_rank": int(outcome["supported_rank"]),
            "tangent_basis_dimensionless": basis.tolist(),
            "manifold_neighborhood_radius_dimensionless": radius,
            "geometry_probe_role": "constraint_manifold_geometry_probe",
            "deterministic_solver_initial_guesses": _qualification_seeds(
                reference,
                basis,
                scales,
                radius=radius,
                radius_fraction=radius_fraction,
                holdout_id=str(outcome["holdout_id"]),
            ),
            "admissibility_record_sha256": canonical_sha256(outcome),
            "qualification_seed_results_observed_before_target_freeze": 0,
        }
    )
    return contract


def build_target_freeze(
    manifest: dict[str, Any],
    holdout_freeze: dict[str, Any],
    metrics: dict[str, Any],
    selection: dict[str, Any],
    *,
    admissibility_commit: str,
    admissibility_metrics_sha256: str,
    admissibility_selection_sha256: str,
    generated_at: str,
) -> dict[str, Any]:
    if selection["status"] != "TARGETS_ADMISSIBLE_PENDING_SEPARATE_FREEZE":
        raise ValueError("P3R5 targets require a complete committed admissibility selection.")
    categories = tuple(manifest["holdout_design_and_selection"]["required_categories"])
    outcomes = {item["holdout_id"]: item for item in metrics["outcomes"]}
    cards = {item["holdout_id"]: item for item in holdout_freeze["holdout_cards"]}
    targets = []
    for category in categories:
        holdout_id = selection["selected_holdout_ids"][category]
        outcome = outcomes[holdout_id]
        if outcome["status"] != "ADMISSIBLE" or outcome["category"] != category:
            raise ValueError("P3R5 selected target no longer matches its admissibility record.")
        expected = selection["selected_admissibility_record_sha256"][category]
        if canonical_sha256(outcome) != expected:
            raise ValueError("P3R5 selected admissibility record changed before freeze.")
        targets.append(_target_contract(cards[holdout_id], outcome, manifest))
    counts = {item["case_id"]: 0 for item in targets}
    return {
        "schema": "YPS-HFV2-P3R5-QUALIFICATION-TARGETS-1.0",
        "generated_at": generated_at,
        "admissibility_commit": admissibility_commit,
        "admissibility_metrics_sha256": admissibility_metrics_sha256,
        "admissibility_selection_sha256": admissibility_selection_sha256,
        "reference_constructor_identity": P3R5_REFERENCE_CONSTRUCTOR_ID,
        "target_admissibility_identity": P3R5_TARGET_ADMISSIBILITY_ID,
        "second_order_identity": P3R5_SECOND_ORDER_ID,
        "manifold_retraction_identity": P3R5_MANIFOLD_RETRACTION_ID,
        "actual_multiseed_attraction_identity": P3R5_ACTUAL_MULTISEED_ID,
        "selection_rule": manifest["holdout_design_and_selection"]["target_selection_rule"],
        "selected_holdout_ids": dict(selection["selected_holdout_ids"]),
        "status": "TARGETS_AND_SOLVER_INITIAL_GUESSES_FROZEN",
        "qualification_seed_results_observed_before_target_freeze": 0,
        "qualification_seed_execution_counts_before_target_freeze": counts,
        "qualification_targets": targets,
    }


__all__ = [
    "P3R5CaseExpectation",
    "P3R5DesignCase",
    "P3R5StaticContactCase",
    "build_admissibility_selection",
    "build_case_from_contract",
    "build_design_case",
    "build_design_cases",
    "build_historical_cases",
    "build_qualification_targets",
    "build_target_freeze",
    "select_admissible_holdouts",
]

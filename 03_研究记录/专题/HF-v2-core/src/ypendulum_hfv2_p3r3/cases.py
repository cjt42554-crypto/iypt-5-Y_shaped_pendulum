"""Manifest-driven design cards, historical regressions and frozen P3R3 targets."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np

from ypendulum_hfv2.contact import ContactSurfaceSpec, GeometryTolerances
from ypendulum_hfv2.state import HFV2State
from ypendulum_hfv2.statics.assembly import StaticAssembly
from ypendulum_hfv2.statics.contracts import (
    BranchMaterial,
    RigidBobProperties,
    StaticEnvironment,
    StaticSeed,
)
from ypendulum_hfv2.topology import HFV2Topology, MaterialNode, MaterialSegment
from ypendulum_hfv2_p3r2.assembly import P3R2ContactAssembly

from . import (
    P3R3_LOCAL_BASIN_ID,
    P3R3_REFERENCE_DISCOVERY_ID,
    P3R3_TARGET_ADMISSIBILITY_ID,
)
from .assembly import P3R3ContactAssembly


@dataclass(frozen=True)
class P3R3DesignCase:
    design_id: str
    category: str
    predecessor_assembly: P3R2ContactAssembly
    assembly: P3R3ContactAssembly
    discovery_seed: StaticSeed
    contract: dict[str, Any]


@dataclass(frozen=True)
class P3R3CaseExpectation:
    reference_coordinates: np.ndarray
    near_active_constraint_ids: tuple[str, ...]
    supported_constraint_ids: tuple[str, ...]
    supported_multipliers_N: np.ndarray
    near_active_rank: int
    supported_rank: int


@dataclass(frozen=True)
class P3R3StaticContactCase:
    case_id: str
    role: str
    assembly: P3R3ContactAssembly
    seeds: tuple[StaticSeed, ...]
    expectation: P3R3CaseExpectation
    contract: dict[str, Any]


def _reference_state(bob_position: np.ndarray) -> HFV2State:
    return HFV2State(
        free_node_ids=(),
        free_node_positions=np.empty((0, 3)),
        free_node_velocities=np.empty((0, 3)),
        bob_position=bob_position,
        bob_velocity=np.zeros(3),
        bob_rotation=np.eye(3),
        bob_angular_velocity_body=np.zeros(3),
    )


def _geometry_tolerances(manifest: dict[str, Any]) -> GeometryTolerances:
    return GeometryTolerances(**manifest["geometry_tolerances"])


def _static_assembly(
    contract: dict[str, Any],
    reference_bob_position: np.ndarray,
) -> StaticAssembly:
    support_a = np.asarray(contract["support_A_position_m"], dtype=float)
    support_b = np.asarray(contract["support_B_position_m"], dtype=float)
    junction = np.asarray(contract["junction_position_m"], dtype=float)
    upper_rest = contract["upper_branch_rest_length_m"]
    for branch_id, support in (("upper_A", support_a), ("upper_B", support_b)):
        rest = float(upper_rest[branch_id])
        if not np.isclose(
            np.linalg.norm(support - junction),
            rest,
            rtol=0.0,
            atol=2.0e-15,
        ):
            raise ValueError(
                f"P3R3 {branch_id} support geometry conflicts with its reference length."
            )
    lower_rest = float(contract["lower_branch_rest_length_m"])
    topology = HFV2Topology(
        nodes=(
            MaterialNode("support_A", "prescribed"),
            MaterialNode("support_B", "prescribed"),
            MaterialNode("junction", "prescribed"),
            MaterialNode("attachment", "bob_attachment"),
        ),
        segments=(
            MaterialSegment(
                "upper_A_s000",
                "upper_A",
                "support_A",
                "junction",
                0.0,
                float(upper_rest["upper_A"]),
            ),
            MaterialSegment(
                "upper_B_s000",
                "upper_B",
                "support_B",
                "junction",
                0.0,
                float(upper_rest["upper_B"]),
            ),
            MaterialSegment(
                "lower_s000",
                "lower",
                "junction",
                "attachment",
                0.0,
                lower_rest,
            ),
        ),
    )
    rigidity = float(contract["axial_rigidity_N"])
    line_density = float(contract["line_density_kg_per_m"])
    materials = tuple(
        BranchMaterial(
            branch_id=branch_id,
            axial_rigidity=rigidity,
            bending_stiffness=0.0,
            line_density=line_density,
            displaced_volume_per_length=0.0,
        )
        for branch_id in ("upper_A", "upper_B", "lower")
    )
    return StaticAssembly(
        topology=topology,
        reference_state=_reference_state(reference_bob_position),
        branch_materials=materials,
        prescribed_node_positions={
            "support_A": support_a,
            "support_B": support_b,
            "junction": junction,
        },
        environment=StaticEnvironment(
            gravity=np.asarray(contract["gravity_m_per_s2"], dtype=float),
            fluid_density=0.0,
            buoyancy_enabled=False,
        ),
        bob=RigidBobProperties(
            mass=float(contract["bob_mass_kg"]),
            displaced_volume=0.0,
            inertia_body=np.asarray(contract["bob_inertia_body_kg_m2"], dtype=float),
            attachment_arm_body=np.asarray(
                contract["attachment_arm_body_m"],
                dtype=float,
            ),
        ),
    )


def _surface(contract: dict[str, Any]) -> ContactSurfaceSpec:
    radii = tuple(
        (branch_id, float(contract["branch_contact_radius_m"][branch_id]))
        for branch_id in ("upper_A", "upper_B", "lower")
    )
    return ContactSurfaceSpec(
        branch_contact_radii_m=radii,
        bob_contact_radius_m=float(contract["bob_contact_radius_m"]),
        minimum_clearance_m=float(contract["minimum_clearance_m"]),
    )


def _assembly_kwargs(
    manifest: dict[str, Any],
    contract: dict[str, Any],
    base: StaticAssembly,
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> dict[str, object]:
    numerics = manifest["assembly_numerics"]
    return {
        "base_assembly": base,
        "surface": _surface(contract),
        "tolerances": _geometry_tolerances(manifest),
        "adapter_contract_sha256": adapter_contract_sha256,
        "frozen_protocol_sha256": frozen_protocol_sha256,
        "contact_gap_scale_m": float(numerics["contact_gap_scale_m"]),
        "validity_scale_m": float(numerics["validity_scale_m"]),
        "validity_scale_m2": float(numerics["validity_scale_m2"]),
        "validity_scale_dimensionless": float(numerics["validity_scale_dimensionless"]),
        "translation_difference_step_m": float(numerics["translation_difference_step_m"]),
        "rotation_difference_step_rad": float(numerics["rotation_difference_step_rad"]),
    }


def _assert_physical_numerics_match(
    manifest: dict[str, Any],
    predecessor_manifest: dict[str, Any],
) -> None:
    if manifest["geometry_tolerances"] != predecessor_manifest["geometry_tolerances"]:
        raise ValueError("P3R3 geometry tolerances must remain byte-value equal to P3R2.")
    if manifest["assembly_numerics"] != predecessor_manifest["assembly_numerics"]:
        raise ValueError("P3R3 assembly numerics must remain byte-value equal to P3R2.")


def build_design_cases(
    manifest: dict[str, Any],
    predecessor_manifest: dict[str, Any],
    design_cards: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
    predecessor_adapter_sha256: str,
    predecessor_protocol_sha256: str,
) -> tuple[P3R3DesignCase, ...]:
    _assert_physical_numerics_match(manifest, predecessor_manifest)
    cases = []
    for contract in design_cards["design_cards"]:
        analytic = np.asarray(
            contract["analytic_stationary_bob_position_m"],
            dtype=float,
        )
        base = _static_assembly(contract, analytic)
        predecessor = P3R2ContactAssembly(
            **_assembly_kwargs(
                predecessor_manifest,
                contract,
                base,
                adapter_contract_sha256=predecessor_adapter_sha256,
                frozen_protocol_sha256=predecessor_protocol_sha256,
            )
        )
        assembly = P3R3ContactAssembly(
            **_assembly_kwargs(
                manifest,
                contract,
                base,
                adapter_contract_sha256=adapter_contract_sha256,
                frozen_protocol_sha256=frozen_protocol_sha256,
            )
        )
        seed_contract = contract["reference_discovery_seed"]
        seed = StaticSeed(
            seed_id=f"{contract['design_id']}_reference_discovery",
            free_node_ids=(),
            free_node_positions=np.empty((0, 3)),
            bob_position=analytic + np.asarray(seed_contract["bob_offset_m"], dtype=float),
            bob_rotation_vector=np.asarray(
                seed_contract["rotation_vector_rad"],
                dtype=float,
            ),
        )
        cases.append(
            P3R3DesignCase(
                design_id=str(contract["design_id"]),
                category=str(contract["category"]),
                predecessor_assembly=predecessor,
                assembly=assembly,
                discovery_seed=seed,
                contract=contract,
            )
        )
    return tuple(cases)


def build_case_from_contract(
    manifest: dict[str, Any],
    contract: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> P3R3StaticContactCase:
    reference = np.asarray(contract["expected_reference_coordinates"], dtype=float)
    if reference.shape != (6,):
        raise ValueError("P3R3 target reference must contain six coordinates.")
    base = _static_assembly(contract, reference[:3])
    assembly = P3R3ContactAssembly(
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
            bob_rotation_vector=np.asarray(
                seed_contract["rotation_vector_rad"],
                dtype=float,
            ),
        )
        for seed_contract in contract["deterministic_seeds"]
    )
    supported_ids = tuple(contract["expected_supported_constraint_ids"])
    multiplier_contract = contract["expected_supported_multipliers_N"]
    if set(multiplier_contract) != set(supported_ids):
        raise ValueError("P3R3 multiplier identities must match support identities.")
    return P3R3StaticContactCase(
        case_id=str(contract["case_id"]),
        role=str(contract["role"]),
        assembly=assembly,
        seeds=seeds,
        expectation=P3R3CaseExpectation(
            reference_coordinates=np.array(reference, copy=True),
            near_active_constraint_ids=tuple(contract["expected_near_active_constraint_ids"]),
            supported_constraint_ids=supported_ids,
            supported_multipliers_N=np.array(
                [float(multiplier_contract[item]) for item in supported_ids]
            ),
            near_active_rank=int(contract["expected_near_active_rank"]),
            supported_rank=int(contract["expected_supported_rank"]),
        ),
        contract=contract,
    )


def _historical_contract(contract: dict[str, Any]) -> dict[str, Any]:
    converted = dict(contract)
    expected_position = np.asarray(contract["expected_bob_position_m"], dtype=float)
    expected_rotation = np.asarray(
        contract["expected_bob_rotation_vector_rad"],
        dtype=float,
    )
    converted["expected_reference_coordinates"] = np.concatenate(
        [expected_position, expected_rotation]
    ).tolist()
    return converted


def build_historical_cases(
    manifest: dict[str, Any],
    predecessor_manifest: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> tuple[P3R3StaticContactCase, P3R3StaticContactCase]:
    symmetric = build_case_from_contract(
        manifest,
        _historical_contract(predecessor_manifest["observed_symmetric_regression"]),
        adapter_contract_sha256=adapter_contract_sha256,
        frozen_protocol_sha256=frozen_protocol_sha256,
    )
    p3r_35 = build_case_from_contract(
        manifest,
        _historical_contract(predecessor_manifest["observed_p3r_35_degree_regression"]),
        adapter_contract_sha256=adapter_contract_sha256,
        frozen_protocol_sha256=frozen_protocol_sha256,
    )
    return symmetric, p3r_35


def build_qualification_targets(
    manifest: dict[str, Any],
    target_freeze: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> tuple[P3R3StaticContactCase, ...]:
    return tuple(
        build_case_from_contract(
            manifest,
            contract,
            adapter_contract_sha256=adapter_contract_sha256,
            frozen_protocol_sha256=frozen_protocol_sha256,
        )
        for contract in target_freeze["qualification_targets"]
    )


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def select_admissible_designs(
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
            key=lambda item: item["design_id"],
        )
        if candidates:
            selected[category] = candidates[0]
    return selected


def _qualification_seeds(
    reference: np.ndarray,
    basis: np.ndarray,
    coordinate_scales: np.ndarray,
    *,
    radius: float,
    radius_fraction: float,
    design_id: str,
) -> list[dict[str, Any]]:
    first = basis[:, 0] + basis[:, 1]
    first /= np.linalg.norm(first)
    second = basis[:, 0] - basis[:, 1]
    second /= np.linalg.norm(second)
    directions = (np.zeros(6), first, -second)
    labels = (
        "reference",
        "first_combination_positive",
        "second_combination_negative",
    )
    seeds = []
    for index, (label, direction) in enumerate(zip(labels, directions, strict=True)):
        values = reference + (radius_fraction * radius * coordinate_scales * direction)
        seeds.append(
            {
                "seed_id": f"{design_id}_qualification_{index:02d}_{label}",
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
    design_contract: dict[str, Any],
    outcome: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    excluded = {
        "reference_discovery_seed",
        "reference_discovery_execution_count_before_freeze",
    }
    contract = {key: value for key, value in design_contract.items() if key not in excluded}
    reference = np.asarray(outcome["reference_coordinates"], dtype=float)
    scales = np.asarray(
        outcome["characteristic_scales"]["coordinate_scales"],
        dtype=float,
    )
    basis = np.asarray(outcome["local_basin"]["tangent_basis"], dtype=float)
    radius = float(manifest["local_basin"]["coordinate_radius_dimensionless"])
    radius_fraction = float(manifest["local_basin"]["qualification_seed_radius_fraction"])
    supported_ids = tuple(outcome["supported_ids"])
    near_ids = tuple(outcome["near_active_ids"])
    active_values = outcome["dual_certificate"]["canonical_active_multipliers_N"]
    multiplier_map = {
        identity: float(value) for identity, value in zip(supported_ids, active_values, strict=True)
    }
    branch_identity = _canonical_sha256(
        {
            "design_id": outcome["design_id"],
            "assembly_token": outcome["contact_assembly_token"],
            "reference_coordinates": reference.tolist(),
            "supported_ids": supported_ids,
            "tangent_basis": basis.tolist(),
            "basin_radius": radius,
        }
    )
    contract.update(
        {
            "case_id": f"P3R3_{outcome['design_id']}_LOCAL_BASIN_TARGET",
            "role": "new_unobserved_before_P3R3_freeze_static_contact_local_basin_target_not_apparatus_prediction",
            "branch_identity_sha256": branch_identity,
            "expected_reference_coordinates": reference.tolist(),
            "expected_near_active_constraint_ids": list(near_ids),
            "expected_supported_constraint_ids": list(supported_ids),
            "expected_supported_multipliers_N": multiplier_map,
            "expected_near_active_rank": int(outcome["near_active_rank"]),
            "expected_supported_rank": int(outcome["supported_rank"]),
            "tangent_basis_dimensionless": basis.tolist(),
            "local_basin_radius_dimensionless": radius,
            "deterministic_seeds": _qualification_seeds(
                reference,
                basis,
                scales,
                radius=radius,
                radius_fraction=radius_fraction,
                design_id=str(outcome["design_id"]),
            ),
            "admissibility_record_sha256": _canonical_sha256(outcome),
            "qualification_seed_results_observed_before_target_freeze": 0,
        }
    )
    return contract


def build_target_freeze(
    manifest: dict[str, Any],
    design_cards: dict[str, Any],
    outcomes: list[dict[str, Any]],
    *,
    implementation_commit: str,
    generated_at: str,
) -> dict[str, Any]:
    categories = tuple(manifest["target_design_and_selection"]["required_categories"])
    selected = select_admissible_designs(outcomes, categories)
    design_by_id = {item["design_id"]: item for item in design_cards["design_cards"]}
    sufficient = len(selected) == len(categories)
    targets = (
        [
            _target_contract(
                design_by_id[selected[category]["design_id"]],
                selected[category],
                manifest,
            )
            for category in categories
        ]
        if sufficient
        else []
    )
    counts = {item["case_id"]: 0 for item in targets}
    payload_hash = _canonical_sha256(
        {
            "outcomes": outcomes,
            "selected_design_ids": {
                category: selected[category]["design_id"] for category in selected
            },
        }
    )
    return {
        "schema": "YPS-HFV2-P3R3-QUALIFICATION-TARGETS-1.0",
        "generated_at": generated_at,
        "implementation_commit": implementation_commit,
        "reference_discovery_identity": P3R3_REFERENCE_DISCOVERY_ID,
        "target_admissibility_identity": P3R3_TARGET_ADMISSIBILITY_ID,
        "local_basin_identity": P3R3_LOCAL_BASIN_ID,
        "selection_rule": manifest["target_design_and_selection"]["selection_rule"],
        "all_design_cards_executed_exactly_once": len(outcomes) == len(design_cards["design_cards"])
        and all(item["reference_discovery_execution_count"] == 1 for item in outcomes),
        "selected_design_ids": {category: selected[category]["design_id"] for category in selected},
        "admissibility_payload_sha256": payload_hash,
        "status": ("TARGETS_FROZEN" if sufficient else "TARGET_SUITE_NOT_ADMISSIBLE"),
        "qualification_seed_results_observed_before_target_freeze": 0,
        "qualification_seed_execution_counts_before_target_freeze": counts,
        "qualification_targets": targets,
    }

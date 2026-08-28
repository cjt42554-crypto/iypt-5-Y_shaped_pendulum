"""Manifest-driven P3R2 historical regressions and prefrozen targets."""

from __future__ import annotations

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

from .assembly import P3R2ContactAssembly


@dataclass(frozen=True)
class P3R2CaseExpectation:
    bob_position_m: np.ndarray
    bob_rotation_vector_rad: np.ndarray
    near_active_constraint_ids: tuple[str, ...]
    supported_constraint_ids: tuple[str, ...]
    supported_multipliers_N: np.ndarray
    near_active_rank: int
    supported_rank: int


@dataclass(frozen=True)
class P3R2StaticContactCase:
    case_id: str
    role: str
    assembly: P3R2ContactAssembly
    seeds: tuple[StaticSeed, ...]
    expectation: P3R2CaseExpectation
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


def build_case_from_contract(
    manifest: dict[str, Any],
    contract: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> P3R2StaticContactCase:
    support_a = np.asarray(contract["support_A_position_m"], dtype=float)
    support_b = np.asarray(contract["support_B_position_m"], dtype=float)
    junction = np.asarray(contract["junction_position_m"], dtype=float)
    expected_bob = np.asarray(contract["expected_bob_position_m"], dtype=float)
    expected_rotation = np.asarray(
        contract["expected_bob_rotation_vector_rad"],
        dtype=float,
    )
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
                f"P3R2 {branch_id} support geometry conflicts with its reference length."
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
    arm = np.asarray(contract["attachment_arm_body_m"], dtype=float)
    base = StaticAssembly(
        topology=topology,
        reference_state=_reference_state(expected_bob),
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
            attachment_arm_body=arm,
        ),
    )
    radii = tuple(
        (branch_id, float(contract["branch_contact_radius_m"][branch_id]))
        for branch_id in ("upper_A", "upper_B", "lower")
    )
    numerics = manifest["assembly_numerics"]
    assembly = P3R2ContactAssembly(
        base_assembly=base,
        surface=ContactSurfaceSpec(
            branch_contact_radii_m=radii,
            bob_contact_radius_m=float(contract["bob_contact_radius_m"]),
            minimum_clearance_m=float(contract["minimum_clearance_m"]),
        ),
        tolerances=_geometry_tolerances(manifest),
        adapter_contract_sha256=adapter_contract_sha256,
        frozen_protocol_sha256=frozen_protocol_sha256,
        contact_gap_scale_m=float(numerics["contact_gap_scale_m"]),
        validity_scale_m=float(numerics["validity_scale_m"]),
        validity_scale_m2=float(numerics["validity_scale_m2"]),
        validity_scale_dimensionless=float(
            numerics["validity_scale_dimensionless"]
        ),
        translation_difference_step_m=float(
            numerics["translation_difference_step_m"]
        ),
        rotation_difference_step_rad=float(
            numerics["rotation_difference_step_rad"]
        ),
    )
    seeds = tuple(
        StaticSeed(
            seed_id=str(seed_contract["seed_id"]),
            free_node_ids=(),
            free_node_positions=np.empty((0, 3)),
            bob_position=expected_bob
            + np.asarray(seed_contract["bob_offset_m"], dtype=float),
            bob_rotation_vector=np.asarray(
                seed_contract["rotation_vector_rad"],
                dtype=float,
            ),
        )
        for seed_contract in contract["deterministic_seeds"]
    )
    expected_ids = tuple(contract["expected_supported_constraint_ids"])
    multiplier_contract = contract["expected_supported_multipliers_N"]
    if set(multiplier_contract) != set(expected_ids):
        raise ValueError("P3R2 expected multiplier identities must match support identities.")
    return P3R2StaticContactCase(
        case_id=str(contract["case_id"]),
        role=str(contract["role"]),
        assembly=assembly,
        seeds=seeds,
        expectation=P3R2CaseExpectation(
            bob_position_m=np.array(expected_bob, copy=True),
            bob_rotation_vector_rad=np.array(expected_rotation, copy=True),
            near_active_constraint_ids=tuple(
                contract["expected_near_active_constraint_ids"]
            ),
            supported_constraint_ids=expected_ids,
            supported_multipliers_N=np.array(
                [float(multiplier_contract[identity]) for identity in expected_ids]
            ),
            near_active_rank=int(contract["expected_near_active_rank"]),
            supported_rank=int(contract["expected_supported_rank"]),
        ),
        contract=contract,
    )


def build_observed_symmetric_regression(
    manifest: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> P3R2StaticContactCase:
    return build_case_from_contract(
        manifest,
        manifest["observed_symmetric_regression"],
        adapter_contract_sha256=adapter_contract_sha256,
        frozen_protocol_sha256=frozen_protocol_sha256,
    )


def build_observed_p3r_35_degree_regression(
    manifest: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> P3R2StaticContactCase:
    return build_case_from_contract(
        manifest,
        manifest["observed_p3r_35_degree_regression"],
        adapter_contract_sha256=adapter_contract_sha256,
        frozen_protocol_sha256=frozen_protocol_sha256,
    )


def build_qualification_targets(
    manifest: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> tuple[P3R2StaticContactCase, ...]:
    return tuple(
        build_case_from_contract(
            manifest,
            contract,
            adapter_contract_sha256=adapter_contract_sha256,
            frozen_protocol_sha256=frozen_protocol_sha256,
        )
        for contract in manifest["qualification_targets"]
    )

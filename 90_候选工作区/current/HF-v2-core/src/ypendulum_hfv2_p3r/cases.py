"""Manifest-driven P3R regression and unobserved qualification cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ypendulum_hfv2.contact import ContactSurfaceSpec, GeometryTolerances
from ypendulum_hfv2.rigid.rotation import exp_so3
from ypendulum_hfv2.state import HFV2State
from ypendulum_hfv2.statics.assembly import StaticAssembly
from ypendulum_hfv2.statics.contracts import (
    BranchMaterial,
    RigidBobProperties,
    StaticEnvironment,
    StaticSeed,
)
from ypendulum_hfv2.topology import HFV2Topology, MaterialNode, MaterialSegment

from .assembly import P3RContactAssembly


@dataclass(frozen=True)
class P3RCaseExpectation:
    bob_position_m: np.ndarray
    near_active_constraint_ids: tuple[str, ...]
    supported_constraint_ids: tuple[str, ...]
    near_active_rank: int
    supported_rank: int
    each_supported_multiplier_N: float


@dataclass(frozen=True)
class P3RStaticContactCase:
    case_id: str
    assembly: P3RContactAssembly
    seeds: tuple[StaticSeed, ...]
    expectation: P3RCaseExpectation


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


def _build_case(
    manifest: dict[str, Any],
    contract: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> P3RStaticContactCase:
    support_a = np.asarray(contract["support_A_position_m"], dtype=float)
    support_b = np.asarray(contract["support_B_position_m"], dtype=float)
    junction = np.asarray(contract["junction_position_m"], dtype=float)
    expected_bob = np.asarray(contract["expected_bob_position_m"], dtype=float)
    arm = np.asarray(contract["attachment_arm_body_m"], dtype=float)
    expected_support_b = np.array([-support_a[0], support_a[1], support_a[2]])
    if not np.allclose(support_b, expected_support_b, rtol=0.0, atol=1.0e-15):
        raise ValueError("P3R symmetric-case supports must be exact mirror images.")
    upper_rest = float(contract["upper_branch_rest_length_m"])
    if not np.isclose(
        np.linalg.norm(support_a - junction),
        upper_rest,
        rtol=0.0,
        atol=2.0e-15,
    ):
        raise ValueError("P3R upper support geometry conflicts with its reference length.")
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
                upper_rest,
            ),
            MaterialSegment(
                "upper_B_s000",
                "upper_B",
                "support_B",
                "junction",
                0.0,
                upper_rest,
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
    gravity = np.asarray(contract["gravity_m_per_s2"], dtype=float)
    bob_mass = float(contract["bob_mass_kg"])
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
            gravity=gravity,
            fluid_density=0.0,
            buoyancy_enabled=False,
        ),
        bob=RigidBobProperties(
            mass=bob_mass,
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
    assembly = P3RContactAssembly(
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
        validity_scale_dimensionless=float(numerics["validity_scale_dimensionless"]),
        translation_difference_step_m=float(
            numerics["translation_difference_step_m"]
        ),
        rotation_difference_step_rad=float(
            numerics["rotation_difference_step_rad"]
        ),
    )
    seeds = []
    for seed_contract in contract["deterministic_seeds"]:
        offset = np.asarray(seed_contract["bob_offset_m"], dtype=float)
        rotation = np.asarray(seed_contract["rotation_vector_rad"], dtype=float)
        attachment = expected_bob + offset + exp_so3(rotation) @ arm
        if not np.all(np.isfinite(attachment)):
            raise ValueError("P3R deterministic seed attachment must be finite.")
        seeds.append(
            StaticSeed(
                seed_id=str(seed_contract["seed_id"]),
                free_node_ids=(),
                free_node_positions=np.empty((0, 3)),
                bob_position=expected_bob + offset,
                bob_rotation_vector=rotation,
            )
        )

    attachment = expected_bob + arm
    current_lower_length = float(np.linalg.norm(attachment - junction))
    tension = rigidity / lower_rest * (current_lower_length - lower_rest)
    moving_mass = bob_mass + 0.5 * line_density * lower_rest
    weight = moving_mass * float(np.linalg.norm(gravity))
    required = (
        float(contract["bob_contact_radius_m"])
        + float(contract["branch_contact_radius_m"]["upper_A"])
        + float(contract["minimum_clearance_m"])
    )
    depth = abs(float(expected_bob[2] - junction[2]))
    sine = required / depth
    multiplier = (tension - weight) / (2.0 * sine)
    if multiplier <= 0.0:
        raise ValueError("P3R symmetric case requires positive analytic contact support.")
    expected_multiplier = float(contract["expected_each_multiplier_N"])
    if not np.isclose(multiplier, expected_multiplier, rtol=0.0, atol=2.0e-12):
        raise ValueError("P3R manifest multiplier conflicts with its analytic force balance.")
    return P3RStaticContactCase(
        case_id=str(contract["case_id"]),
        assembly=assembly,
        seeds=tuple(seeds),
        expectation=P3RCaseExpectation(
            bob_position_m=np.array(expected_bob, copy=True),
            near_active_constraint_ids=tuple(
                contract["expected_near_active_constraint_ids"]
            ),
            supported_constraint_ids=tuple(contract["expected_supported_constraint_ids"]),
            near_active_rank=int(contract["expected_near_active_rank"]),
            supported_rank=int(contract["expected_supported_rank"]),
            each_supported_multiplier_N=expected_multiplier,
        ),
    )


def build_observed_symmetric_regression(
    manifest: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> P3RStaticContactCase:
    return _build_case(
        manifest,
        manifest["observed_symmetric_regression"],
        adapter_contract_sha256=adapter_contract_sha256,
        frozen_protocol_sha256=frozen_protocol_sha256,
    )


def build_unobserved_qualification_target(
    manifest: dict[str, Any],
    *,
    adapter_contract_sha256: str,
    frozen_protocol_sha256: str,
) -> P3RStaticContactCase:
    return _build_case(
        manifest,
        manifest["qualification_target"],
        adapter_contract_sha256=adapter_contract_sha256,
        frozen_protocol_sha256=frozen_protocol_sha256,
    )

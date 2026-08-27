"""Manifest-driven analytic contact benchmark and the single frozen G3 target case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ypendulum_hfv2.contact import ContactSurfaceSpec, GeometryTolerances
from ypendulum_hfv2.rigid.rotation import exp_so3
from ypendulum_hfv2.state import HFV2State
from ypendulum_hfv2.statics.assembly import StaticAssembly
from ypendulum_hfv2.statics.contact_assembly import ContactStaticAssembly
from ypendulum_hfv2.statics.contracts import (
    BranchMaterial,
    RigidBobProperties,
    StaticEnvironment,
    StaticSeed,
)
from ypendulum_hfv2.topology import HFV2Topology, MaterialNode, MaterialSegment


@dataclass(frozen=True)
class SymmetricContactExpectation:
    bob_position_m: np.ndarray
    active_constraint_ids: tuple[str, ...]
    each_multiplier_N: float
    active_rank: int


@dataclass(frozen=True)
class StaticContactCase:
    case_id: str
    assembly: ContactStaticAssembly
    seeds: tuple[StaticSeed, ...]
    expectation: SymmetricContactExpectation


def geometry_tolerances(manifest: dict[str, Any]) -> GeometryTolerances:
    return GeometryTolerances(**manifest["geometry_tolerances"])


def _state(bob_position: np.ndarray, arm: np.ndarray) -> HFV2State:
    return HFV2State(
        free_node_ids=(),
        free_node_positions=np.empty((0, 3)),
        free_node_velocities=np.empty((0, 3)),
        bob_position=bob_position,
        bob_velocity=np.zeros(3),
        bob_rotation=np.eye(3),
        bob_angular_velocity_body=np.zeros(3),
    )


def _symmetric_case(
    *,
    case_id: str,
    support_horizontal_m: float,
    support_depth_m: float,
    upper_rest_length_m: float,
    lower_rest_length_m: float,
    axial_rigidity_N: float,
    line_density_kg_per_m: float,
    branch_radius_m: float,
    minimum_clearance_m: float,
    bob_mass_kg: float,
    bob_radius_m: float,
    bob_inertia: np.ndarray,
    gravity: np.ndarray,
    expected_bob_depth_m: float,
    seed_contracts: tuple[dict[str, Any], ...],
    tolerances: GeometryTolerances,
    formal_sha256: str,
    amendment_sha256: str,
) -> StaticContactCase:
    support_a = np.array([-support_horizontal_m, 0.0, -support_depth_m])
    support_b = np.array([support_horizontal_m, 0.0, -support_depth_m])
    junction = np.zeros(3)
    arm = np.array([0.0, 0.0, bob_radius_m])
    bob_position = np.array([0.0, 0.0, -expected_bob_depth_m])
    attachment = bob_position + arm
    if not np.isclose(np.linalg.norm(support_a), upper_rest_length_m, rtol=0.0, atol=2.0e-15):
        raise ValueError("Frozen upper support geometry conflicts with its reference length.")
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
                upper_rest_length_m,
            ),
            MaterialSegment(
                "upper_B_s000",
                "upper_B",
                "support_B",
                "junction",
                0.0,
                upper_rest_length_m,
            ),
            MaterialSegment(
                "lower_s000",
                "lower",
                "junction",
                "attachment",
                0.0,
                lower_rest_length_m,
            ),
        ),
    )
    materials = tuple(
        BranchMaterial(
            branch_id=branch_id,
            axial_rigidity=axial_rigidity_N,
            bending_stiffness=0.0,
            line_density=line_density_kg_per_m,
            displaced_volume_per_length=0.0,
        )
        for branch_id in ("upper_A", "upper_B", "lower")
    )
    base = StaticAssembly(
        topology=topology,
        reference_state=_state(bob_position, arm),
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
            mass=bob_mass_kg,
            displaced_volume=0.0,
            inertia_body=bob_inertia,
            attachment_arm_body=arm,
        ),
    )
    contact = ContactStaticAssembly(
        base_assembly=base,
        surface=ContactSurfaceSpec(
            branch_contact_radii_m=tuple(
                (branch_id, branch_radius_m)
                for branch_id in ("upper_A", "upper_B", "lower")
            ),
            bob_contact_radius_m=bob_radius_m,
            minimum_clearance_m=minimum_clearance_m,
        ),
        tolerances=tolerances,
        formal_registration_contract_sha256=formal_sha256,
        protocol_amendment_sha256=amendment_sha256,
    )
    seeds = []
    for contract in seed_contracts:
        offset = np.asarray(contract["bob_offset_m"], dtype=float)
        rotation_vector = np.asarray(contract["rotation_vector_rad"], dtype=float)
        seed_bob = bob_position + offset
        seed_attachment = seed_bob + exp_so3(rotation_vector) @ arm
        if not np.all(np.isfinite(seed_attachment)):
            raise ValueError("Frozen contact seed attachment is non-finite.")
        seeds.append(
            StaticSeed(
                seed_id=str(contract["seed_id"]),
                free_node_ids=(),
                free_node_positions=np.empty((0, 3)),
                bob_position=seed_bob,
                bob_rotation_vector=rotation_vector,
            )
        )
    current_lower_length = float(np.linalg.norm(attachment - junction))
    tension = axial_rigidity_N / lower_rest_length_m * (
        current_lower_length - lower_rest_length_m
    )
    moving_mass = bob_mass_kg + 0.5 * line_density_kg_per_m * lower_rest_length_m
    weight = moving_mass * float(np.linalg.norm(gravity))
    sine = (bob_radius_m + branch_radius_m + minimum_clearance_m) / expected_bob_depth_m
    multiplier = (tension - weight) / (2.0 * sine)
    if multiplier <= 0.0:
        raise ValueError("Frozen symmetric benchmark requires positive contact multipliers.")
    return StaticContactCase(
        case_id=case_id,
        assembly=contact,
        seeds=tuple(seeds),
        expectation=SymmetricContactExpectation(
            bob_position_m=bob_position,
            active_constraint_ids=(
                "bob:upper_A:upper_A_s000",
                "bob:upper_B:upper_B_s000",
            ),
            each_multiplier_N=float(multiplier),
            active_rank=2,
        ),
    )


def build_small_symmetric_contact_benchmark(
    manifest: dict[str, Any],
    *,
    formal_sha256: str,
    amendment_sha256: str,
) -> StaticContactCase:
    depth = 0.4
    horizontal = depth * np.tan(np.deg2rad(30.0))
    upper_rest = float(np.hypot(horizontal, depth))
    return _symmetric_case(
        case_id="SMALL_SYMMETRIC_TWO_CONTACT_BENCHMARK",
        support_horizontal_m=float(horizontal),
        support_depth_m=depth,
        upper_rest_length_m=upper_rest,
        lower_rest_length_m=0.029,
        axial_rigidity_N=40.0,
        line_density_kg_per_m=0.001,
        branch_radius_m=0.004,
        minimum_clearance_m=0.001,
        bob_mass_kg=0.08,
        bob_radius_m=0.02,
        bob_inertia=np.diag([4.0e-5, 4.0e-5, 4.0e-5]),
        gravity=np.array([0.0, 0.0, -9.81]),
        expected_bob_depth_m=0.05,
        seed_contracts=(
            {
                "seed_id": "small_analytic",
                "bob_offset_m": [0.0, 0.0, 0.0],
                "rotation_vector_rad": [0.0, 0.0, 0.0],
            },
        ),
        tolerances=geometry_tolerances(manifest),
        formal_sha256=formal_sha256,
        amendment_sha256=amendment_sha256,
    )


def build_target_contact_case(
    manifest: dict[str, Any],
    *,
    formal_sha256: str,
    amendment_sha256: str,
) -> StaticContactCase:
    case = manifest["target_case"]
    support_a = np.asarray(case["support_A_position_m"], dtype=float)
    support_b = np.asarray(case["support_B_position_m"], dtype=float)
    expected_b = np.array([-support_a[0], support_a[1], support_a[2]])
    if not np.allclose(support_b, expected_b, rtol=0.0, atol=1.0e-15):
        raise ValueError("Frozen target supports must be exactly symmetric.")
    if not np.isclose(
        float(case["upper_axial_rigidity_N"]),
        float(case["lower_axial_rigidity_N"]),
        rtol=0.0,
        atol=0.0,
    ):
        raise ValueError("Frozen symmetric target requires one common axial rigidity.")
    radii = case["branch_contact_radius_m"]
    unique_radii = {float(value) for value in radii.values()}
    if len(unique_radii) != 1:
        raise ValueError("Frozen symmetric target requires one common branch contact radius.")
    return _symmetric_case(
        case_id=str(case["case_id"]),
        support_horizontal_m=abs(float(support_a[0])),
        support_depth_m=abs(float(support_a[2])),
        upper_rest_length_m=float(case["upper_branch_rest_length_m"]),
        lower_rest_length_m=float(case["lower_branch_rest_length_m"]),
        axial_rigidity_N=float(case["lower_axial_rigidity_N"]),
        line_density_kg_per_m=float(case["line_density_kg_per_m"]),
        branch_radius_m=next(iter(unique_radii)),
        minimum_clearance_m=float(case["minimum_clearance_m"]),
        bob_mass_kg=float(case["bob_mass_kg"]),
        bob_radius_m=float(case["bob_contact_radius_m"]),
        bob_inertia=np.asarray(case["bob_inertia_body_kg_m2"], dtype=float),
        gravity=np.asarray(case["gravity_m_per_s2"], dtype=float),
        expected_bob_depth_m=abs(float(case["expected_bob_position_m"][2])),
        seed_contracts=tuple(case["deterministic_seeds"]),
        tolerances=geometry_tolerances(manifest),
        formal_sha256=formal_sha256,
        amendment_sha256=amendment_sha256,
    )

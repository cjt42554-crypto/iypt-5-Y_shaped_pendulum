from __future__ import annotations

import numpy as np
import pytest

from ypendulum_hfv2.contact import ContactSurfaceSpec, GeometryTolerances
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

FORMAL_SHA = "37fe00beeefbd6f51208c3b3476cb51acefc10ddc3c10c59122e0068400be221"
AMENDMENT_SHA = "28463583b48c8691325c49972a4d53926b30ae6d466b5d6ba4d77168fc5b9a41"


def _tolerances() -> GeometryTolerances:
    return GeometryTolerances(
        collapsed_segment_length_m=1.0e-12,
        zero_witness_distance_m=1.0e-12,
        parameter_merge_absolute=2.0e-11,
        squared_distance_tie_relative=2.0e-11,
        polygon_halfspace_absolute=2.0e-14,
        polygon_area_absolute=1.0e-14,
        socket_radial_monotonicity_min_m2=1.0e-12,
        socket_projective_opening_margin_min=-1.0e-12,
        socket_cut_gap_min_m=-1.0e-10,
    )


def _base_assembly() -> tuple[StaticAssembly, StaticSeed]:
    support_a = np.array([-0.35, 0.01, -0.35])
    support_b = np.array([0.28, -0.02, -0.34])
    junction = np.zeros(3)
    bob_position = np.array([0.02, 0.01, -0.25])
    arm = np.array([0.0, 0.0, 0.04])
    attachment = bob_position + arm
    upper_a_rest = float(np.linalg.norm(support_a - junction))
    upper_b_rest = float(np.linalg.norm(support_b - junction))
    lower_rest = float(np.linalg.norm(attachment - junction))
    topology = HFV2Topology(
        nodes=(
            MaterialNode("support_A", "prescribed"),
            MaterialNode("support_B", "prescribed"),
            MaterialNode("junction", "prescribed"),
            MaterialNode("attachment", "bob_attachment"),
        ),
        segments=(
            MaterialSegment("upper_A_s000", "upper_A", "support_A", "junction", 0.0, upper_a_rest),
            MaterialSegment("upper_B_s000", "upper_B", "support_B", "junction", 0.0, upper_b_rest),
            MaterialSegment("lower_s000", "lower", "junction", "attachment", 0.0, lower_rest),
        ),
    )
    state = HFV2State(
        free_node_ids=(),
        free_node_positions=np.empty((0, 3)),
        free_node_velocities=np.empty((0, 3)),
        bob_position=bob_position,
        bob_velocity=np.zeros(3),
        bob_rotation=np.eye(3),
        bob_angular_velocity_body=np.zeros(3),
    )
    materials = tuple(
        BranchMaterial(
            branch_id=branch_id,
            axial_rigidity=60.0,
            bending_stiffness=0.0,
            line_density=0.001,
            displaced_volume_per_length=0.0,
        )
        for branch_id in ("upper_A", "upper_B", "lower")
    )
    assembly = StaticAssembly(
        topology=topology,
        reference_state=state,
        branch_materials=materials,
        prescribed_node_positions={
            "support_A": support_a,
            "support_B": support_b,
            "junction": junction,
        },
        environment=StaticEnvironment(
            gravity=np.array([0.0, 0.0, -9.81]),
            fluid_density=0.0,
            buoyancy_enabled=False,
        ),
        bob=RigidBobProperties(
            mass=0.08,
            displaced_volume=0.0,
            inertia_body=np.diag([8.0e-5, 9.0e-5, 1.0e-4]),
            attachment_arm_body=arm,
        ),
    )
    seed = StaticSeed(
        seed_id="contact_assembly_benchmark",
        free_node_ids=(),
        free_node_positions=np.empty((0, 3)),
        bob_position=bob_position,
        bob_rotation_vector=np.zeros(3),
    )
    return assembly, seed


def _contact_assembly(
    *,
    clearance: float = 0.001,
    amendment_sha: str = AMENDMENT_SHA,
) -> tuple[ContactStaticAssembly, StaticSeed]:
    base, seed = _base_assembly()
    contact = ContactStaticAssembly(
        base_assembly=base,
        surface=ContactSurfaceSpec(
            branch_contact_radii_m=(
                ("upper_A", 0.003),
                ("upper_B", 0.0035),
                ("lower", 0.0025),
            ),
            bob_contact_radius_m=0.04,
            minimum_clearance_m=clearance,
        ),
        tolerances=_tolerances(),
        formal_registration_contract_sha256=FORMAL_SHA,
        protocol_amendment_sha256=amendment_sha,
    )
    return contact, seed


def test_contact_evaluation_is_a_read_only_layer_over_p2_potential() -> None:
    contact, seed = _contact_assembly()
    coordinates = contact.coordinates_from_seed(seed)
    result = contact.evaluate(coordinates)
    base_coordinates = contact.base_assembly.coordinates_from_seed(seed)
    base = contact.base_assembly.evaluate(base_coordinates)
    assert result.total_potential == base.total_potential
    np.testing.assert_array_equal(result.generalized_force, base.generalized_force)
    np.testing.assert_array_equal(result.base_evaluation.node_positions, base.node_positions)
    assert result.constraint_ids == contact.registry.constraint_ids
    assert result.gaps_m.shape == (len(result.constraint_ids),)
    assert result.gap_jacobian.shape == (
        len(result.constraint_ids),
        contact.base_assembly.layout.generalized_size,
    )
    assert np.all(result.gaps_m > 0.0)


def test_contact_gap_jacobian_matches_centered_difference() -> None:
    contact, seed = _contact_assembly()
    coordinates = contact.coordinates_from_seed(seed)
    analytic = contact.evaluate(coordinates).gap_jacobian
    step = 1.0e-7
    finite_difference = np.empty_like(analytic)
    for column in range(coordinates.values.size):
        plus = coordinates.values.copy()
        minus = coordinates.values.copy()
        plus[column] += step
        minus[column] -= step
        plus_gap = contact.evaluate(contact.coordinates_from_values(plus)).gaps_m
        minus_gap = contact.evaluate(contact.coordinates_from_values(minus)).gaps_m
        finite_difference[:, column] = (plus_gap - minus_gap) / (2.0 * step)
    denominator = np.maximum(
        np.maximum(np.linalg.norm(analytic, axis=1), np.linalg.norm(finite_difference, axis=1)),
        np.finfo(float).tiny,
    )
    relative = np.linalg.norm(analytic - finite_difference, axis=1) / denominator
    assert float(np.max(relative)) < 2.0e-7


def test_contact_identity_binds_surface_and_protocol_amendment() -> None:
    first, seed = _contact_assembly()
    changed_surface, _ = _contact_assembly(clearance=0.0011)
    changed_protocol, _ = _contact_assembly(amendment_sha="1" * 64)
    assert len(first.contact_assembly_token) == 64
    assert first.contact_assembly_token != changed_surface.contact_assembly_token
    assert first.contact_assembly_token != changed_protocol.contact_assembly_token
    foreign = changed_surface.coordinates_from_seed(seed)
    with pytest.raises(ValueError, match="different contact assembly"):
        first.evaluate(foreign)


def test_socket_validity_metrics_remain_inside_the_frozen_domain() -> None:
    contact, seed = _contact_assembly()
    validity = contact.evaluate(contact.coordinates_from_seed(seed)).validity
    assert validity.bob_socket_material_extent_m > 0.0
    assert validity.bob_socket_radial_monotonicity_m2 > 0.0
    assert validity.bob_socket_cut_gap_m > 0.0
    assert len(validity.junction_socket_metrics) == 3
    for _, material_extent, projective_margin, cut_gap in validity.junction_socket_metrics:
        assert material_extent > 0.0
        assert projective_margin > 0.0
        assert cut_gap > 0.0

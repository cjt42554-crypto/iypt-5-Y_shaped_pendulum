from __future__ import annotations

import numpy as np
import pytest

from ypendulum_hfv2.contact import (
    ContactGeometryError,
    ContactSurfaceSpec,
    GeometryTolerances,
    build_contact_registry,
)
from ypendulum_hfv2.topology import HFV2Topology, MaterialNode, MaterialSegment


@pytest.fixture
def tolerances() -> GeometryTolerances:
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


def _target_topology() -> HFV2Topology:
    upper_rest = 0.6928203230275509
    return HFV2Topology(
        nodes=(
            MaterialNode("support_A", "prescribed"),
            MaterialNode("support_B", "prescribed"),
            MaterialNode("junction", "prescribed"),
            MaterialNode("attachment", "bob_attachment"),
        ),
        segments=(
            MaterialSegment("upper_A_s000", "upper_A", "support_A", "junction", 0.0, upper_rest),
            MaterialSegment("upper_B_s000", "upper_B", "support_B", "junction", 0.0, upper_rest),
            MaterialSegment("lower_s000", "lower", "junction", "attachment", 0.0, 0.063),
        ),
    )


def _surface() -> ContactSurfaceSpec:
    return ContactSurfaceSpec(
        branch_contact_radii_m=(("upper_A", 0.005), ("upper_B", 0.005), ("lower", 0.005)),
        bob_contact_radius_m=0.05,
        minimum_clearance_m=0.002,
    )


def test_formal_y_registration_expands_to_unique_individual_domains(
    tolerances: GeometryTolerances,
) -> None:
    registry = build_contact_registry(_target_topology(), _surface(), tolerances)
    assert registry.formal_registration_id == "FIXED_REST_MATERIAL_SOCKETS_PROJECTIVE_V2"
    assert registry.constraint_ids == (
        "junction:junction:upper_A:upper_A_s000|upper_B:upper_B_s000:first_outside",
        "junction:junction:upper_A:upper_A_s000|upper_B:upper_B_s000:second_outside_first_inside",
        "junction:junction:upper_A:upper_A_s000|lower:lower_s000:first_outside",
        "junction:junction:upper_A:upper_A_s000|lower:lower_s000:second_outside_first_inside",
        "junction:junction:upper_B:upper_B_s000|lower:lower_s000:first_outside",
        "junction:junction:upper_B:upper_B_s000|lower:lower_s000:second_outside_first_inside",
        "bob:upper_A:upper_A_s000",
        "bob:upper_B:upper_B_s000",
        "bob:lower:lower_s000",
    )
    upper_lower = registry.segment_pair_constraints[2]
    assert len(upper_lower.parameter_domains) == 1
    assert upper_lower.required_center_distance_m == pytest.approx(0.012)
    assert registry.junction_sockets[0].registered_projective_opening_squared == pytest.approx(0.0625)
    assert registry.bob_socket.socket.socket_length_m == pytest.approx(0.057)
    lower_bob = registry.bob_segment_constraints[-1]
    assert lower_bob.parameter_min == pytest.approx(0.0)
    assert lower_bob.parameter_max == pytest.approx((0.063 - 0.057) / 0.063)


def test_registration_is_deterministic_and_serializable(
    tolerances: GeometryTolerances,
) -> None:
    first = build_contact_registry(_target_topology(), _surface(), tolerances)
    second = build_contact_registry(_target_topology(), _surface(), tolerances)
    assert first.serializable() == second.serializable()


def test_surface_branch_order_must_match_topology(tolerances: GeometryTolerances) -> None:
    reordered = ContactSurfaceSpec(
        branch_contact_radii_m=(("lower", 0.005), ("upper_A", 0.005), ("upper_B", 0.005)),
        bob_contact_radius_m=0.05,
        minimum_clearance_m=0.002,
    )
    with pytest.raises(ValueError, match="branch order"):
        build_contact_registry(_target_topology(), reordered, tolerances)


def test_socket_that_consumes_a_branch_fails_closed(tolerances: GeometryTolerances) -> None:
    oversized = ContactSurfaceSpec(
        branch_contact_radii_m=(("upper_A", 0.005), ("upper_B", 0.005), ("lower", 0.04)),
        bob_contact_radius_m=0.05,
        minimum_clearance_m=0.002,
    )
    with pytest.raises(ContactGeometryError, match="positive active material extent"):
        build_contact_registry(_target_topology(), oversized, tolerances)


def test_partial_same_branch_pair_uses_material_halfspace(
    tolerances: GeometryTolerances,
) -> None:
    topology = HFV2Topology(
        nodes=(
            MaterialNode("support", "prescribed"),
            MaterialNode("n1", "free"),
            MaterialNode("n2", "free"),
            MaterialNode("attachment", "bob_attachment"),
        ),
        segments=(
            MaterialSegment("s0", "only", "support", "n1", 0.0, 0.01),
            MaterialSegment("s1", "only", "n1", "n2", 0.01, 0.02),
            MaterialSegment("s2", "only", "n2", "attachment", 0.02, 0.03),
        ),
    )
    surface = ContactSurfaceSpec(
        branch_contact_radii_m=(("only", 0.004),),
        bob_contact_radius_m=0.005,
        minimum_clearance_m=0.001,
    )
    registry = build_contact_registry(topology, surface, tolerances)
    same = registry.segment_pair_constraints
    assert len(same) == 3
    assert {constraint.category for constraint in same} == {
        "same_branch_full",
        "same_branch_partial",
    }
    partial = next(constraint for constraint in same if constraint.category == "same_branch_partial")
    vertices = partial.parameter_domains[0].vertices
    first = next(segment for segment in topology.segments if segment.segment_id == partial.first_segment_id)
    second = next(segment for segment in topology.segments if segment.segment_id == partial.second_segment_id)
    material_separation = (
        second.material_start
        + vertices[:, 1] * second.rest_length
        - first.material_start
        - vertices[:, 0] * first.rest_length
    )
    np.testing.assert_array_less(1.01 * 0.009 - 1.0e-14, material_separation)

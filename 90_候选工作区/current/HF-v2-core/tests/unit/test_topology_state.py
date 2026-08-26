from __future__ import annotations

import numpy as np
import pytest

from ypendulum_hfv2.state import HFV2State
from ypendulum_hfv2.topology import HFV2Topology, MaterialNode, MaterialSegment


def _topology() -> HFV2Topology:
    nodes = (
        MaterialNode("support_A", "prescribed"),
        MaterialNode("upper_A_mid", "free"),
        MaterialNode("junction", "free"),
        MaterialNode("support_B", "prescribed"),
        MaterialNode("upper_B_mid", "free"),
        MaterialNode("lower_mid", "free"),
        MaterialNode("bob_attachment", "bob_attachment"),
    )
    segments = (
        MaterialSegment("a0", "upper_A", "support_A", "upper_A_mid", 0.0, 0.5),
        MaterialSegment("a1", "upper_A", "upper_A_mid", "junction", 0.5, 1.0),
        MaterialSegment("b0", "upper_B", "support_B", "upper_B_mid", 0.0, 0.5),
        MaterialSegment("b1", "upper_B", "upper_B_mid", "junction", 0.5, 1.0),
        MaterialSegment("l0", "lower", "junction", "lower_mid", 0.0, 0.4),
        MaterialSegment("l1", "lower", "lower_mid", "bob_attachment", 0.4, 0.8),
    )
    return HFV2Topology(nodes=nodes, segments=segments)


def test_shared_junction_is_explicit_and_dof_map_is_contiguous() -> None:
    topology = _topology()
    assert topology.node_ids.count("junction") == 1
    assert topology.free_node_ids == (
        "upper_A_mid",
        "junction",
        "upper_B_mid",
        "lower_mid",
    )
    assert topology.free_position_slice("junction") == slice(3, 6)
    assert topology.bob_position_slice == slice(12, 15)
    assert topology.bob_rotation_tangent_slice == slice(15, 18)
    assert topology.generalized_position_tangent_size == 18
    assert [segment.segment_id for segment in topology.branch_segments("upper_A")] == [
        "a0",
        "a1",
    ]


def test_incidence_matrix_closes_each_oriented_segment() -> None:
    topology = _topology()
    incidence = topology.incidence_matrix()
    assert incidence.shape == (6, 7)
    np.testing.assert_array_equal(np.sum(incidence, axis=1), 0.0)
    junction_column = incidence[:, topology.node_index("junction")]
    assert np.count_nonzero(junction_column) == 3


def test_topology_rejects_implicit_or_invalid_registration() -> None:
    with pytest.raises(ValueError, match="unique"):
        HFV2Topology(
            nodes=(MaterialNode("same", "free"), MaterialNode("same", "prescribed")),
            segments=(),
        )
    with pytest.raises(ValueError, match="unknown"):
        HFV2Topology(
            nodes=(MaterialNode("known", "free"),),
            segments=(MaterialSegment("s", "branch", "known", "missing", 0.0, 1.0),),
        )


def test_topology_rejects_disconnected_material_chain() -> None:
    nodes = (
        MaterialNode("support", "prescribed"),
        MaterialNode("first", "free"),
        MaterialNode("second", "free"),
        MaterialNode("bob", "bob_attachment"),
    )
    with pytest.raises(ValueError, match="connected oriented material chain"):
        HFV2Topology(
            nodes=nodes,
            segments=(
                MaterialSegment("s0", "branch", "support", "first", 0.0, 0.5),
                MaterialSegment("s1", "branch", "second", "bob", 0.5, 1.0),
            ),
        )


def test_state_validates_topology_and_immutable_so3_contract() -> None:
    topology = _topology()
    state = HFV2State(
        free_node_ids=topology.free_node_ids,
        free_node_positions=np.zeros((4, 3)),
        free_node_velocities=np.zeros((4, 3)),
        bob_position=np.array([0.0, 0.0, -1.0]),
        bob_velocity=np.zeros(3),
        bob_rotation=np.eye(3),
        bob_angular_velocity_body=np.array([0.1, -0.2, 0.3]),
    )
    state.validate_topology(topology)
    np.testing.assert_allclose(state.bob_angular_velocity_world, state.bob_angular_velocity_body)
    with pytest.raises(ValueError, match="read-only"):
        state.bob_position[0] = 1.0
    with pytest.raises(ValueError, match=r"SO\(3\)"):
        HFV2State(
            free_node_ids=topology.free_node_ids,
            free_node_positions=np.zeros((4, 3)),
            free_node_velocities=np.zeros((4, 3)),
            bob_position=np.zeros(3),
            bob_velocity=np.zeros(3),
            bob_rotation=np.diag([1.0, 1.0, -1.0]),
            bob_angular_velocity_body=np.zeros(3),
        )


def test_state_count_mismatch_fails_closed() -> None:
    state = HFV2State(
        free_node_ids=("only",),
        free_node_positions=np.zeros((1, 3)),
        free_node_velocities=np.zeros((1, 3)),
        bob_position=np.zeros(3),
        bob_velocity=np.zeros(3),
        bob_rotation=np.eye(3),
        bob_angular_velocity_body=np.zeros(3),
    )
    with pytest.raises(ValueError, match="does not exactly match"):
        state.validate_topology(_topology())


def test_material_rest_length_is_a_read_only_derived_arc_coordinate() -> None:
    segment = MaterialSegment("s", "branch", "start", "end", 0.25, 0.85)
    assert segment.rest_length == pytest.approx(0.6)
    assert "rest_length" not in MaterialSegment.__dataclass_fields__
    with pytest.raises(TypeError, match="rest_length"):
        MaterialSegment(
            "bad", "branch", "start", "end", 0.25, 0.85, rest_length=0.5
        )
    with pytest.raises((AttributeError, TypeError)):
        segment.rest_length = 0.5


def test_branch_span_and_subdivision_preserve_length_mass_and_equivalent_stiffness() -> None:
    topology = _topology()
    branch = topology.branch_segments("lower")
    assert sum(segment.rest_length for segment in branch) == pytest.approx(0.8)
    assert topology.branch_rest_length("lower") == pytest.approx(0.8)

    density_per_length = 0.23
    axial_rigidity = 120.0
    coarse = (MaterialSegment("whole", "branch", "support", "bob", 0.0, 1.0),)
    refined = (
        MaterialSegment("left", "branch", "support", "mid", 0.0, 0.4),
        MaterialSegment("right", "branch", "mid", "bob", 0.4, 1.0),
    )
    assert sum(density_per_length * item.rest_length for item in coarse) == pytest.approx(
        sum(density_per_length * item.rest_length for item in refined)
    )
    coarse_equivalent = 1.0 / sum(item.rest_length / axial_rigidity for item in coarse)
    refined_equivalent = 1.0 / sum(item.rest_length / axial_rigidity for item in refined)
    assert coarse_equivalent == pytest.approx(refined_equivalent)


def test_equal_count_but_permuted_state_layout_fails_closed() -> None:
    topology = _topology()
    state = HFV2State(
        free_node_ids=("junction", "upper_A_mid", "upper_B_mid", "lower_mid"),
        free_node_positions=np.zeros((4, 3)),
        free_node_velocities=np.zeros((4, 3)),
        bob_position=np.zeros(3),
        bob_velocity=np.zeros(3),
        bob_rotation=np.eye(3),
        bob_angular_velocity_body=np.zeros(3),
    )
    with pytest.raises(ValueError, match="layout"):
        state.validate_topology(topology)

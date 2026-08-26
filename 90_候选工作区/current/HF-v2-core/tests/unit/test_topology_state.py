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
        MaterialSegment("a0", "upper_A", "support_A", "upper_A_mid", 0.0, 0.5, 0.5),
        MaterialSegment("a1", "upper_A", "upper_A_mid", "junction", 0.5, 1.0, 0.5),
        MaterialSegment("b0", "upper_B", "support_B", "upper_B_mid", 0.0, 0.5, 0.5),
        MaterialSegment("b1", "upper_B", "upper_B_mid", "junction", 0.5, 1.0, 0.5),
        MaterialSegment("l0", "lower", "junction", "lower_mid", 0.0, 0.4, 0.4),
        MaterialSegment("l1", "lower", "lower_mid", "bob_attachment", 0.4, 0.8, 0.4),
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
            segments=(MaterialSegment("s", "branch", "known", "missing", 0.0, 1.0, 1.0),),
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
                MaterialSegment("s0", "branch", "support", "first", 0.0, 0.5, 0.5),
                MaterialSegment("s1", "branch", "second", "bob", 0.5, 1.0, 0.5),
            ),
        )


def test_state_validates_topology_and_immutable_so3_contract() -> None:
    topology = _topology()
    state = HFV2State(
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
            free_node_positions=np.zeros((4, 3)),
            free_node_velocities=np.zeros((4, 3)),
            bob_position=np.zeros(3),
            bob_velocity=np.zeros(3),
            bob_rotation=np.diag([1.0, 1.0, -1.0]),
            bob_angular_velocity_body=np.zeros(3),
        )


def test_state_count_mismatch_fails_closed() -> None:
    state = HFV2State(
        free_node_positions=np.zeros((1, 3)),
        free_node_velocities=np.zeros((1, 3)),
        bob_position=np.zeros(3),
        bob_velocity=np.zeros(3),
        bob_rotation=np.eye(3),
        bob_angular_velocity_body=np.zeros(3),
    )
    with pytest.raises(ValueError, match="does not match"):
        state.validate_topology(_topology())

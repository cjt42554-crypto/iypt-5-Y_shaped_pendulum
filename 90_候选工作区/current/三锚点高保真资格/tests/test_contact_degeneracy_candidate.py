from __future__ import annotations

import numpy as np
import pytest

from hard_contact_candidate import (
    ContactConstraint,
    DegenerateContactGeometry,
    KKTThresholds,
    assemble_gap_system,
    audit_projected_hessian,
    audit_static_kkt,
    closest_segment_pair_witness,
    full_parameter_polygon,
    material_separation_polygon,
    solve_static_contact_problem,
)

def test_parallel_overlap_is_rejected_as_nondifferentiable() -> None:
    witness = closest_segment_pair_witness(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]), np.array([0.2, 0.3, 0.0]), np.array([0.8, 0.3, 0.0]), required_center_distance_m=0.2)
    assert not witness.unique
    assert not witness.differentiable
    assert witness.competing_minimizer_count >= 2

def test_collapsed_segment_fails_closed() -> None:
    with pytest.raises(DegenerateContactGeometry):
        closest_segment_pair_witness(np.zeros(3), np.zeros(3), np.array([0.0, 1.0, 0.0]), np.array([1.0, 1.0, 0.0]), required_center_distance_m=0.1)

def test_global_gap_assembly_maps_endpoint_gradients() -> None:
    positions = np.array([[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, -1.0, 0.3], [0.0, 1.0, 0.3]])
    constraint = ContactConstraint(label='crossing', first_start_node=0, first_end_node=1, second_start_node=2, second_end_node=3, required_center_distance_m=0.2)
    gaps, jacobian, witnesses = assemble_gap_system(positions, [constraint])
    assert gaps == pytest.approx([0.1])
    assert jacobian.shape == (1, 12)
    np.testing.assert_allclose(jacobian.reshape(1, 4, 3)[0], witnesses[0].endpoint_gap_gradient)
    np.testing.assert_allclose(jacobian.sum(axis=1), 0.0, atol=1e-15)

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

def test_full_parameter_polygon_is_counter_clockwise_unit_square() -> None:
    polygon = full_parameter_polygon()
    assert polygon.shape == (4, 2)
    assert np.all((polygon >= 0.0) & (polygon <= 1.0))
    area2 = np.sum(polygon[:, 0] * np.roll(polygon[:, 1], -1) - polygon[:, 1] * np.roll(polygon[:, 0], -1))
    assert area2 > 0.0

def test_material_separation_polygon_enforces_rest_material_exclusion() -> None:
    polygon = material_separation_polygon(first_material_start=0.0, first_material_end=1.0, second_material_start=1.0, second_material_end=2.0, minimum_material_separation=1.5)
    assert polygon.shape[0] >= 3
    xi = polygon[:, 0]
    eta = polygon[:, 1]
    first_material = xi
    second_material = 1.0 + eta
    assert np.all(second_material - first_material >= 1.5 - 1e-14)
    assert np.any(np.isclose(second_material - first_material, 1.5))

def test_material_separation_domain_retains_point_limit() -> None:
    domain = material_separation_polygon(first_material_start=0.0, first_material_end=1.0, second_material_start=1.0, second_material_end=2.0, minimum_material_separation=2.0)
    assert domain.shape == (1, 2)
    np.testing.assert_allclose(domain[0], [0.0, 1.0], atol=1e-14)
    witness = closest_segment_pair_witness(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.2]), np.array([1.0, 1.0, 0.2]), required_center_distance_m=0.1, parameter_polygon=domain)
    assert witness.unique
    assert witness.first_parameter == pytest.approx(0.0)
    assert witness.second_parameter == pytest.approx(1.0)

def test_interior_segment_witness_and_gap_gradient_match_finite_difference() -> None:
    endpoints = np.array([[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, -1.0, 0.3], [0.0, 1.0, 0.3]])
    witness = closest_segment_pair_witness(*endpoints, required_center_distance_m=0.2)
    assert witness.unique
    assert witness.differentiable
    assert witness.first_parameter == pytest.approx(0.5)
    assert witness.second_parameter == pytest.approx(0.5)
    assert witness.distance_m == pytest.approx(0.3)
    assert witness.gap_m == pytest.approx(0.1)
    step = 1e-07
    finite_difference = np.empty((4, 3))
    for endpoint_index in range(4):
        for coordinate in range(3):
            plus = endpoints.copy()
            minus = endpoints.copy()
            plus[endpoint_index, coordinate] += step
            minus[endpoint_index, coordinate] -= step
            plus_gap = closest_segment_pair_witness(*plus, required_center_distance_m=0.2).gap_m
            minus_gap = closest_segment_pair_witness(*minus, required_center_distance_m=0.2).gap_m
            finite_difference[endpoint_index, coordinate] = (plus_gap - minus_gap) / (2.0 * step)
    np.testing.assert_allclose(witness.endpoint_gap_gradient, finite_difference, rtol=2e-07, atol=2e-09)

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tests.helpers.invariance import internal_balance, objectivity_audit
from ypendulum_static_reference.audit.energy_gradient import (
    central_difference_gradient,
    force_gradient_samples,
)
from ypendulum_static_reference.audit.statics import strict_decrease_interval
from ypendulum_static_reference.constitutive.bending import (
    BendingGeometryError,
    bending_energy,
    bending_energy_forces,
)
from ypendulum_static_reference.rigid.rotation import exp_so3

FORMAL_PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = json.loads(
    (FORMAL_PROJECT_ROOT / "tests/fixtures/historical/g1r_acceptance_manifest.json").read_text(
        encoding="utf-8"
    )
)
FINITE_DIFFERENCE = ACCEPTANCE["finite_difference"]
BENDING_CONTRACT = ACCEPTANCE["bending_equation"]
RELATIVE_STEPS = tuple(FINITE_DIFFERENCE["relative_step_sequence"])


def _gradient_samples(points: np.ndarray, rest: np.ndarray, stiffness: float):
    response = bending_energy_forces(points, rest, stiffness)
    return force_gradient_samples(
        lambda coordinates: bending_energy(coordinates, rest, stiffness),
        points,
        response.forces,
        RELATIVE_STEPS,
        coordinate_scale=float(np.mean(rest)),
    )


def test_straight_rod_has_zero_energy_force_and_gradient() -> None:
    points = np.column_stack([np.linspace(0.0, 1.5, 4), np.zeros((4, 2))])
    rest = np.full(3, 0.5)
    response = bending_energy_forces(points, rest, 0.2)
    assert response.energy == 0.0
    np.testing.assert_array_equal(response.forces, np.zeros_like(points))
    gradient = central_difference_gradient(
        lambda coordinates: bending_energy(coordinates, rest, 0.2), points, 5.0e-7
    )
    np.testing.assert_allclose(gradient, 0.0, atol=2.0e-13)


@pytest.mark.parametrize(
    "case_id",
    tuple(ACCEPTANCE["gradient_cases"]["bending"]),
)
def test_bending_force_is_negative_energy_gradient(case_id: str) -> None:
    case = ACCEPTANCE["gradient_cases"]["bending"][case_id]
    points = np.asarray(case["points_m"], dtype=float)
    rest = np.asarray(case["segment_rest_length_m"], dtype=float)
    samples = _gradient_samples(points, rest, float(case["bending_stiffness_N_m2"]))
    errors = [sample.relative_error for sample in samples]
    assert (
        strict_decrease_interval(errors, FINITE_DIFFERENCE["minimum_strict_decrease_steps"])
        is not None
    )
    assert samples[-1].relative_error <= FINITE_DIFFERENCE["final_relative_error_max"]


def test_bending_resultants_and_objectivity_close() -> None:
    points = np.array([[0.2, -0.1, 0.3], [0.65, 0.0, 0.2], [1.02, 0.25, 0.37], [1.3, 0.55, 0.7]])
    rest = np.array([0.46, 0.46, 0.46])
    stiffness = 0.08
    response = bending_energy_forces(points, rest, stiffness)
    force_scale = max(float(np.linalg.norm(response.forces)), 1.0e-12)
    balance = internal_balance(
        points,
        response.forces,
        np.array([-0.8, 0.4, 1.2]),
        force_scale=force_scale,
        length_scale=float(np.sum(rest)),
    )
    assert balance.scaled_force_resultant <= ACCEPTANCE["balance"]["scaled_force_resultant_max"]
    assert balance.scaled_moment_resultant <= ACCEPTANCE["balance"]["scaled_moment_resultant_max"]

    def energy_and_force(coordinates: np.ndarray) -> tuple[float, np.ndarray]:
        candidate = bending_energy_forces(coordinates, rest, stiffness)
        return candidate.energy, candidate.forces

    rotation = exp_so3(np.array([0.37, -0.51, 0.22]))
    audit = objectivity_audit(
        energy_and_force,
        points,
        rotation,
        np.array([1.3, -2.1, 0.7]),
        energy_scale=max(response.energy, 1.0e-12),
        force_scale=force_scale,
    )
    assert audit.relative_energy_change <= ACCEPTANCE["objectivity"]["relative_energy_change_max"]
    assert (
        audit.relative_force_covariance_error
        <= ACCEPTANCE["objectivity"]["relative_force_covariance_error_max"]
    )


def test_exact_antiparallel_and_collapsed_geometry_fail_closed() -> None:
    with pytest.raises(BendingGeometryError, match="curvature denominator"):
        bending_energy_forces(
            np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.2, 0.0, 0.0]]),
            np.ones(2),
            0.1,
        )
    with pytest.raises(BendingGeometryError, match="Collapsed"):
        bending_energy_forces(
            np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
            np.ones(2),
            0.1,
        )


def test_zero_stiffness_returns_exact_zero_without_evaluating_singular_geometry() -> None:
    singular_cases = (
        np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.2, 0.0, 0.0]]),
        np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
    )
    for points in singular_cases:
        response = bending_energy_forces(points, np.ones(2), 0.0)
        assert response.energy == BENDING_CONTRACT["zero_stiffness_exact_energy"]
        np.testing.assert_array_equal(response.forces, np.zeros_like(points))
        assert response.minimum_segment_length is None
        assert response.minimum_turn_clearance is None


def test_curvature_energy_grows_without_bound_along_frozen_turn_sequence() -> None:
    energies: list[float] = []
    for offset in BENDING_CONTRACT["turn_to_pi_offsets_rad"]:
        angle = np.pi - offset
        points = np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0 + np.cos(angle), np.sin(angle), 0.0]]
        )
        energies.append(bending_energy(points, np.ones(2), 0.12))
    ratios = [right / left for left, right in zip(energies[:-1], energies[1:], strict=True)]
    assert all(ratio >= BENDING_CONTRACT["minimum_successive_energy_ratio"] for ratio in ratios)


def test_curvature_energy_matches_the_declared_equation() -> None:
    angle = 0.83
    stiffness = 0.17
    dual_length = 0.6
    points = np.array(
        [[0.0, 0.0, 0.0], [0.8, 0.0, 0.0], [0.8 + 1.1 * np.cos(angle), 1.1 * np.sin(angle), 0.0]]
    )
    expected = 2.0 * stiffness / dual_length * (1.0 - np.cos(angle)) / (1.0 + np.cos(angle))
    assert bending_energy(points, np.full(2, dual_length), stiffness) == pytest.approx(
        expected, rel=2.0e-15
    )


def test_smooth_circular_arc_bending_energy_converges_under_refinement() -> None:
    radius = BENDING_CONTRACT["circular_arc_radius_m"]
    total_angle = BENDING_CONTRACT["circular_arc_total_angle_rad"]
    stiffness = BENDING_CONTRACT["circular_arc_stiffness_N_m2"]
    continuum_energy = 0.5 * stiffness * total_angle / radius
    errors: list[float] = []
    for segment_count in BENDING_CONTRACT["circular_arc_segment_counts"]:
        angles = np.linspace(0.0, total_angle, segment_count + 1)
        points = np.column_stack(
            [radius * np.sin(angles), radius * (1.0 - np.cos(angles)), np.zeros_like(angles)]
        )
        rest = np.full(segment_count, radius * total_angle / segment_count)
        energy = bending_energy(points, rest, stiffness)
        errors.append(abs(energy - continuum_energy))
    assert errors[1] < errors[0]
    assert errors[2] < errors[1]
    assert errors[3] < errors[2]

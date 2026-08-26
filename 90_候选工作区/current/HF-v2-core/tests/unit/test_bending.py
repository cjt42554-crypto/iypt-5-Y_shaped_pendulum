from __future__ import annotations

import numpy as np
import pytest

from ypendulum_hfv2.audit.energy_gradient import (
    central_difference_gradient,
    force_gradient_samples,
)
from ypendulum_hfv2.audit.invariance import internal_balance, objectivity_audit
from ypendulum_hfv2.constitutive.bending import (
    BendingGeometryError,
    bending_energy,
    bending_energy_forces,
)
from ypendulum_hfv2.rigid.rotation import exp_so3

RELATIVE_STEPS = (1.0e-3, 3.0e-4, 1.0e-4, 3.0e-5, 1.0e-5, 3.0e-6, 1.0e-6)


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
    "points",
    [
        np.array([[0.0, 0.0, 0.0], [0.45, 0.0, 0.0], [0.88, 0.11, 0.0], [1.28, 0.28, 0.0]]),
        np.array([[0.1, -0.2, 0.3], [0.52, -0.08, 0.22], [0.9, 0.15, 0.34], [1.21, 0.42, 0.61]]),
        np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.02, 0.01, 0.004]]),
    ],
    ids=("planar", "three_dimensional", "near_antiparallel_but_legal"),
)
def test_bending_force_is_negative_energy_gradient(points: np.ndarray) -> None:
    rest = np.full(points.shape[0] - 1, 0.45 if points.shape[0] == 4 else 1.0)
    samples = _gradient_samples(points, rest, 0.035)
    assert min(sample.relative_error for sample in samples[2:]) <= 5.0e-7
    assert samples[2].relative_error < samples[0].relative_error


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
    assert balance.scaled_force_resultant <= 5.0e-13
    assert balance.scaled_moment_resultant <= 2.0e-12

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
    assert audit.relative_energy_change <= 2.0e-13
    assert audit.relative_force_covariance_error <= 2.0e-12


def test_exact_antiparallel_and_collapsed_geometry_fail_closed() -> None:
    with pytest.raises(BendingGeometryError, match="Anti-parallel"):
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


def test_smooth_circular_arc_bending_energy_converges_under_refinement() -> None:
    radius = 1.7
    total_angle = 0.9
    stiffness = 0.12
    continuum_energy = 0.5 * stiffness * total_angle / radius
    errors: list[float] = []
    for segment_count in (20, 40, 80, 160):
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

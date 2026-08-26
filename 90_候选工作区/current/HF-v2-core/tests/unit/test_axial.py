from __future__ import annotations

import numpy as np
import pytest

from ypendulum_hfv2.audit.energy_gradient import force_gradient_samples
from ypendulum_hfv2.audit.invariance import internal_balance, objectivity_audit
from ypendulum_hfv2.audit.passivity import audit_axial_passivity
from ypendulum_hfv2.constitutive.axial import AxialMaterial, axial_segment_response
from ypendulum_hfv2.rigid.rotation import exp_so3

RELATIVE_STEPS = (1.0e-3, 3.0e-4, 1.0e-4, 3.0e-5, 1.0e-5, 3.0e-6, 1.0e-6)


def _static_response(coordinates: np.ndarray, material: AxialMaterial):
    return axial_segment_response(
        coordinates[0], coordinates[1], np.zeros(3), np.zeros(3), material
    )


def test_axial_static_force_is_negative_energy_gradient_with_step_convergence() -> None:
    material = AxialMaterial(rest_length=1.1, axial_rigidity=780.0, axial_viscosity=0.0)
    coordinates = np.array([[0.2, -0.3, 0.1], [1.25, 0.35, -0.15]])
    response = _static_response(coordinates, material)
    analytic_force = np.vstack([response.force_on_start, response.force_on_end])
    samples = force_gradient_samples(
        lambda points: _static_response(points, material).stored_energy,
        coordinates,
        analytic_force,
        RELATIVE_STEPS,
        coordinate_scale=material.rest_length,
    )
    assert samples[2].relative_error < samples[0].relative_error
    assert samples[4].relative_error < samples[2].relative_error
    assert samples[-1].relative_error <= 5.0e-7


@pytest.mark.parametrize(
    ("end_position", "end_velocity"),
    [
        (np.array([0.8, 0.0, 0.0]), np.array([100.0, 0.0, 0.0])),
        (np.array([0.99, 0.0, 0.0]), np.array([-100.0, 0.0, 0.0])),
        (np.array([0.5, 0.2, 0.0]), np.array([20.0, -10.0, 0.0])),
    ],
)
def test_compression_state_has_exactly_zero_axial_force(
    end_position: np.ndarray, end_velocity: np.ndarray
) -> None:
    material = AxialMaterial(rest_length=1.0, axial_rigidity=100.0, axial_viscosity=10.0)
    response = axial_segment_response(
        np.zeros(3), end_position, np.zeros(3), end_velocity, material
    )
    assert response.extension < 0.0
    assert response.active is False
    assert response.tension == 0.0
    np.testing.assert_array_equal(response.force_on_start, np.zeros(3))
    np.testing.assert_array_equal(response.force_on_end, np.zeros(3))
    assert response.stored_energy == 0.0


def test_active_viscosity_is_passive_and_power_balance_closes() -> None:
    material = AxialMaterial(rest_length=1.0, axial_rigidity=100.0, axial_viscosity=10.0)
    response = axial_segment_response(
        np.zeros(3),
        np.array([1.1, 0.0, 0.0]),
        np.zeros(3),
        np.array([-0.2, 0.0, 0.0]),
        material,
    )
    assert response.active is True
    assert response.tension == pytest.approx(8.0)
    assert response.viscous_dissipation_rate == pytest.approx(0.4)
    assert response.unilateral_release_dissipation_rate == 0.0
    audit = audit_axial_passivity(response, power_scale=2.0)
    assert audit.passed


def test_projected_unloading_reports_nonnegative_release_dissipation() -> None:
    material = AxialMaterial(rest_length=1.0, axial_rigidity=100.0, axial_viscosity=10.0)
    response = axial_segment_response(
        np.zeros(3),
        np.array([1.1, 0.0, 0.0]),
        np.zeros(3),
        np.array([-2.0, 0.0, 0.0]),
        material,
    )
    assert response.trial_force < 0.0
    assert response.active is False
    assert response.tension == 0.0
    assert response.viscous_dissipation_rate == 0.0
    assert response.unilateral_release_dissipation_rate == pytest.approx(20.0)
    assert abs(response.power_balance_residual) <= 2.0e-15
    assert audit_axial_passivity(response, power_scale=20.0).passed


def test_axial_action_reaction_and_arbitrary_origin_moment_close() -> None:
    material = AxialMaterial(rest_length=0.9, axial_rigidity=500.0, axial_viscosity=2.0)
    points = np.array([[0.3, -0.4, 0.2], [1.1, 0.3, 0.7]])
    response = axial_segment_response(
        points[0], points[1], np.array([0.1, 0.2, -0.1]), np.array([0.4, -0.1, 0.3]), material
    )
    forces = np.vstack([response.force_on_start, response.force_on_end])
    balance = internal_balance(
        points,
        forces,
        np.array([-0.7, 0.5, 0.9]),
        force_scale=max(response.tension, 1.0),
        length_scale=material.rest_length,
    )
    assert balance.scaled_force_resultant <= 5.0e-13
    assert balance.scaled_moment_resultant <= 2.0e-12


def test_axial_energy_and_force_are_objective() -> None:
    material = AxialMaterial(rest_length=0.7, axial_rigidity=350.0, axial_viscosity=0.0)
    points = np.array([[0.2, -0.1, 0.4], [0.95, 0.35, 0.25]])
    rotation = exp_so3(np.array([0.31, -0.22, 0.47]))

    def energy_and_force(coordinates: np.ndarray) -> tuple[float, np.ndarray]:
        response = _static_response(coordinates, material)
        return response.stored_energy, np.vstack([response.force_on_start, response.force_on_end])

    base_energy, base_force = energy_and_force(points)
    audit = objectivity_audit(
        energy_and_force,
        points,
        rotation,
        np.array([1.7, -2.2, 0.8]),
        energy_scale=max(base_energy, 1.0),
        force_scale=max(float(np.linalg.norm(base_force)), 1.0),
    )
    assert audit.relative_energy_change <= 2.0e-13
    assert audit.relative_force_covariance_error <= 2.0e-12

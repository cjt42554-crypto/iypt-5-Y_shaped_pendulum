from __future__ import annotations

import numpy as np
import pytest

from ypendulum_hfv2.loads import IsotropicDragLaw, point_external_load
from ypendulum_hfv2.mass import MassProperties


def test_mass_properties_compute_positive_kinetic_energy_and_momentum() -> None:
    properties = MassProperties(
        free_node_mass=np.array([0.1, 0.2]),
        bob_mass=0.5,
        bob_inertia_body=np.diag([0.01, 0.02, 0.03]),
    )
    node_velocity = np.array([[1.0, 0.0, 0.0], [0.0, 2.0, 0.0]])
    bob_velocity = np.array([0.0, 0.0, 3.0])
    omega = np.array([1.0, 2.0, 3.0])
    expected_energy = (
        0.5 * 0.1 + 0.5 * 0.2 * 4.0 + 0.5 * 0.5 * 9.0 + 0.5 * (0.01 + 0.02 * 4.0 + 0.03 * 9.0)
    )
    assert properties.kinetic_energy(node_velocity, bob_velocity, omega) == pytest.approx(
        expected_energy
    )
    np.testing.assert_allclose(
        properties.total_linear_momentum(node_velocity, bob_velocity),
        np.array([0.1, 0.4, 1.5]),
    )


def test_mass_properties_reject_nonphysical_inertia() -> None:
    with pytest.raises(ValueError, match="positive definite"):
        MassProperties(np.ones(2), 1.0, np.diag([1.0, 1.0, 0.0]))


def test_gravity_buoyancy_and_drag_power_identity() -> None:
    drag = IsotropicDragLaw(enabled=True, linear_coefficient=0.3, quadratic_coefficient=0.2)
    velocity = np.array([1.0, -0.4, 0.2])
    air_velocity = np.array([0.2, 0.1, -0.3])
    response = point_external_load(
        mass=2.0,
        displaced_volume=0.03,
        fluid_density=1.2,
        gravity=np.array([0.0, 0.0, -9.81]),
        velocity=velocity,
        air_velocity=air_velocity,
        drag=drag,
        buoyancy_enabled=True,
    )
    np.testing.assert_allclose(response.gravity_force, np.array([0.0, 0.0, -19.62]))
    np.testing.assert_allclose(response.buoyancy_force, np.array([0.0, 0.0, 1.2 * 0.03 * 9.81]))
    assert response.relative_air_dissipation_rate > 0.0
    assert float(np.dot(response.air_force, velocity)) == pytest.approx(
        response.body_air_power, abs=2.0e-16
    )
    np.testing.assert_allclose(
        response.total_force,
        response.gravity_force + response.buoyancy_force + response.air_force,
    )


def test_disabled_air_force_is_exactly_zero() -> None:
    drag = IsotropicDragLaw(enabled=False, linear_coefficient=1.0, quadratic_coefficient=2.0)
    response = point_external_load(
        mass=1.0,
        displaced_volume=0.0,
        fluid_density=1.2,
        gravity=np.zeros(3),
        velocity=np.array([10.0, 0.0, 0.0]),
        air_velocity=np.zeros(3),
        drag=drag,
        buoyancy_enabled=False,
    )
    np.testing.assert_array_equal(response.air_force, np.zeros(3))
    assert response.relative_air_dissipation_rate == 0.0
    assert response.air_work_rate == 0.0

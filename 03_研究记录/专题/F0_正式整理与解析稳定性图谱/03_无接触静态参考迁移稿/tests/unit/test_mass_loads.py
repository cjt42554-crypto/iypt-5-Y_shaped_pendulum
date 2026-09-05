from __future__ import annotations

import inspect

import numpy as np
import pytest

from ypendulum_static_reference.loads import point_static_load
from ypendulum_static_reference.mass import StaticMassDistribution
from ypendulum_static_reference.state import StaticReferenceState


def test_static_mass_distribution_validates_positive_registered_masses() -> None:
    distribution = StaticMassDistribution(
        free_node_ids=("first", "second"),
        free_node_mass=np.array([0.1, 0.2]),
        bob_mass=0.5,
    )
    np.testing.assert_array_equal(distribution.free_node_mass, np.array([0.1, 0.2]))
    assert distribution.bob_mass == 0.5
    with pytest.raises(ValueError, match="positive"):
        StaticMassDistribution(("first",), np.array([0.0]), 0.5)


def test_mass_layout_permutation_fails_closed() -> None:
    distribution = StaticMassDistribution(
        free_node_ids=("first", "second"),
        free_node_mass=np.array([0.1, 0.2]),
        bob_mass=0.5,
    )
    permuted_state = StaticReferenceState(
        free_node_ids=("second", "first"),
        free_node_positions=np.zeros((2, 3)),
        bob_position=np.zeros(3),
        bob_rotation=np.eye(3),
    )
    with pytest.raises(ValueError, match="layouts"):
        distribution.validate_state(permuted_state)


def test_gravity_and_buoyancy_are_separate_conservative_static_forces() -> None:
    response = point_static_load(
        mass=2.0,
        displaced_volume=0.03,
        fluid_density=1.2,
        gravity=np.array([0.0, 0.0, -9.81]),
        buoyancy_enabled=True,
    )
    np.testing.assert_allclose(response.gravity_force, np.array([0.0, 0.0, -19.62]))
    np.testing.assert_allclose(
        response.buoyancy_force,
        np.array([0.0, 0.0, 1.2 * 0.03 * 9.81]),
    )
    np.testing.assert_allclose(
        response.total_force,
        response.gravity_force + response.buoyancy_force,
    )


def test_disabled_buoyancy_is_exactly_zero_and_api_has_no_motion_inputs() -> None:
    response = point_static_load(
        mass=1.0,
        displaced_volume=0.1,
        fluid_density=1.2,
        gravity=np.array([0.0, 0.0, -9.81]),
        buoyancy_enabled=False,
    )
    np.testing.assert_array_equal(response.buoyancy_force, np.zeros(3))
    parameter_names = set(inspect.signature(point_static_load).parameters)
    assert parameter_names == {
        "mass",
        "displaced_volume",
        "fluid_density",
        "gravity",
        "buoyancy_enabled",
    }

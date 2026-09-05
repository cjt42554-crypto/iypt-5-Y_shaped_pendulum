from __future__ import annotations

import inspect

import numpy as np
import pytest

from ypendulum_static_reference.rigid.attachment import (
    attachment_action_reaction,
    attachment_geometry,
)
from ypendulum_static_reference.rigid.rotation import (
    SO3_ROUNDOFF_TOLERANCE,
    compose_rotation,
    exp_so3,
    rotation_metrics,
)


def test_exponential_map_matches_axis_rotation() -> None:
    rotation = exp_so3(np.array([0.0, 0.0, 0.5 * np.pi]))
    np.testing.assert_allclose(
        rotation,
        np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]),
        atol=2.0e-16,
    )
    metrics = rotation_metrics(rotation)
    assert metrics.orthogonality_error <= 5.0e-16
    assert metrics.determinant_error <= 5.0e-16


def test_small_angle_exponential_has_correct_first_derivative() -> None:
    vector = np.array([2.0e-10, -3.0e-10, 4.0e-10])
    rotation = exp_so3(vector)
    recovered = np.array(
        [
            0.5 * (rotation[2, 1] - rotation[1, 2]),
            0.5 * (rotation[0, 2] - rotation[2, 0]),
            0.5 * (rotation[1, 0] - rotation[0, 1]),
        ]
    )
    np.testing.assert_allclose(recovered, vector, rtol=0.0, atol=1.0e-25)


def test_static_rotation_composition_stays_in_so3() -> None:
    left = exp_so3(np.array([0.3, -0.4, 0.2]))
    right = exp_so3(np.array([-0.15, 0.22, 0.31]))
    result = compose_rotation(left, right)
    metrics = rotation_metrics(result)
    assert metrics.orthogonality_error <= SO3_ROUNDOFF_TOLERANCE
    assert metrics.determinant_error <= SO3_ROUNDOFF_TOLERANCE


def test_attachment_geometry_uses_only_position_orientation_and_arm() -> None:
    center = np.array([0.2, -0.7, 1.1])
    rotation = exp_so3(np.array([0.31, -0.27, 0.18]))
    arm_body = np.array([0.05, -0.02, 0.11])
    geometry = attachment_geometry(center, rotation, arm_body)
    np.testing.assert_allclose(geometry.world_arm, rotation @ arm_body)
    np.testing.assert_allclose(geometry.position, center + rotation @ arm_body)
    assert set(inspect.signature(attachment_geometry).parameters) == {
        "bob_position",
        "rotation",
        "attachment_arm_body",
    }


def test_attachment_action_reaction_closes_force_and_moment_about_any_origin() -> None:
    center = np.array([0.3, -0.4, 0.8])
    rotation = exp_so3(np.array([-0.2, 0.4, 0.1]))
    arm_body = np.array([0.06, 0.02, -0.09])
    force_on_body = np.array([1.7, -0.8, 2.1])
    interaction = attachment_action_reaction(center, rotation, arm_body, force_on_body)
    np.testing.assert_array_equal(
        interaction.force_on_material + interaction.body_wrench.force,
        np.zeros(3),
    )
    origin = np.array([-1.2, 0.5, 0.9])
    total_moment = (
        np.cross(interaction.connection_position - origin, interaction.force_on_material)
        + np.cross(center - origin, interaction.body_wrench.force)
        + interaction.body_wrench.torque_about_center
    )
    np.testing.assert_allclose(total_moment, 0.0, atol=5.0e-16)


def test_attachment_geometry_is_objective_under_common_rotation() -> None:
    center = np.array([0.2, 0.3, -0.4])
    rotation = exp_so3(np.array([0.2, -0.3, 0.4]))
    common = exp_so3(np.array([-0.5, 0.1, 0.25]))
    arm_body = np.array([0.03, 0.06, -0.08])
    base = attachment_geometry(center, rotation, arm_body)
    transformed = attachment_geometry(common @ center, common @ rotation, arm_body)
    np.testing.assert_allclose(transformed.position, common @ base.position, atol=3.0e-16)


def test_invalid_rotation_is_rejected_instead_of_normalized() -> None:
    with pytest.raises(ValueError, match=r"SO\(3\)"):
        attachment_geometry(
            np.zeros(3),
            np.diag([1.0, 1.0, 1.01]),
            np.zeros(3),
        )

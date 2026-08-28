from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ypendulum_static_reference.rigid.attachment import (
    attachment_action_reaction,
    attachment_kinematics,
)
from ypendulum_static_reference.rigid.rotation import (
    SO3_ROUNDOFF_TOLERANCE,
    advance_rotation_body,
    advance_rotation_world,
    body_to_world_angular_velocity,
    exp_so3,
    rotation_metrics,
    world_to_body_angular_velocity,
)

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = json.loads(
    (CANDIDATE_ROOT / "contracts" / "g1r_acceptance_manifest.json").read_text(encoding="utf-8")
)
ROTATION_CONTRACT = ACCEPTANCE["rotation"]


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


@pytest.mark.parametrize("case", ROTATION_CONTRACT["sequences"], ids=lambda case: case["case_id"])
def test_manifest_rotation_sequences_remain_in_so3_without_projection(case: dict) -> None:
    rotation = np.eye(3)
    angular_velocity_body = np.asarray(case["angular_velocity_body_rad_per_s"], dtype=float)
    for _ in range(case["update_count"]):
        rotation = advance_rotation_body(rotation, angular_velocity_body, case["time_step_s"])
    metrics = rotation_metrics(rotation)
    assert SO3_ROUNDOFF_TOLERANCE == ROTATION_CONTRACT["shared_roundoff_tolerance"]
    assert metrics.orthogonality_error <= ROTATION_CONTRACT["shared_roundoff_tolerance"]
    assert metrics.determinant_error <= ROTATION_CONTRACT["shared_roundoff_tolerance"]


def test_body_and_world_angular_velocity_updates_are_equivalent() -> None:
    rotation = exp_so3(np.array([0.3, -0.4, 0.2]))
    omega_body = np.array([0.7, -0.2, 0.5])
    omega_world = body_to_world_angular_velocity(rotation, omega_body)
    np.testing.assert_allclose(
        world_to_body_angular_velocity(rotation, omega_world), omega_body, atol=2.0e-16
    )
    body_update = advance_rotation_body(rotation, omega_body, 0.003)
    world_update = advance_rotation_world(rotation, omega_world, 0.003)
    np.testing.assert_allclose(body_update, world_update, atol=3.0e-16)


def test_attachment_velocity_matches_group_kinematic_difference() -> None:
    center = np.array([0.2, -0.7, 1.1])
    center_velocity = np.array([0.4, 0.2, -0.1])
    rotation = exp_so3(np.array([0.31, -0.27, 0.18]))
    omega_body = np.array([0.8, -0.35, 0.42])
    arm_body = np.array([0.05, -0.02, 0.11])
    kinematics = attachment_kinematics(center, center_velocity, rotation, omega_body, arm_body)
    step = 1.0e-5
    plus_rotation = advance_rotation_body(rotation, omega_body, step)
    minus_rotation = advance_rotation_body(rotation, omega_body, -step)
    plus_position = center + step * center_velocity + plus_rotation @ arm_body
    minus_position = center - step * center_velocity + minus_rotation @ arm_body
    finite_difference_velocity = (plus_position - minus_position) / (2.0 * step)
    np.testing.assert_allclose(
        kinematics.velocity, finite_difference_velocity, rtol=0.0, atol=2.0e-11
    )


def test_attachment_action_reaction_closes_force_and_moment_about_any_origin() -> None:
    center = np.array([0.3, -0.4, 0.8])
    rotation = exp_so3(np.array([-0.2, 0.4, 0.1]))
    arm_body = np.array([0.06, 0.02, -0.09])
    force_on_body = np.array([1.7, -0.8, 2.1])
    interaction = attachment_action_reaction(center, rotation, arm_body, force_on_body)
    np.testing.assert_array_equal(
        interaction.force_on_material + interaction.body_wrench.force, np.zeros(3)
    )
    origin = np.array([-1.2, 0.5, 0.9])
    total_moment = (
        np.cross(interaction.connection_position - origin, interaction.force_on_material)
        + np.cross(center - origin, interaction.body_wrench.force)
        + interaction.body_wrench.torque_about_center
    )
    np.testing.assert_allclose(total_moment, 0.0, atol=5.0e-16)


def test_attachment_kinematics_is_objective_under_common_rotation() -> None:
    center = np.array([0.2, 0.3, -0.4])
    center_velocity = np.array([-0.1, 0.5, 0.2])
    rotation = exp_so3(np.array([0.2, -0.3, 0.4]))
    common = exp_so3(np.array([-0.5, 0.1, 0.25]))
    omega_body = np.array([0.8, 0.2, -0.3])
    arm_body = np.array([0.03, 0.06, -0.08])
    base = attachment_kinematics(center, center_velocity, rotation, omega_body, arm_body)
    transformed = attachment_kinematics(
        common @ center,
        common @ center_velocity,
        common @ rotation,
        omega_body,
        arm_body,
    )
    np.testing.assert_allclose(transformed.position, common @ base.position, atol=3.0e-16)
    np.testing.assert_allclose(transformed.velocity, common @ base.velocity, atol=3.0e-16)


def test_invalid_rotation_is_rejected_instead_of_normalized() -> None:
    with pytest.raises(ValueError, match=r"SO\(3\)"):
        advance_rotation_body(np.diag([1.0, 1.0, 1.01]), np.zeros(3), 0.1)

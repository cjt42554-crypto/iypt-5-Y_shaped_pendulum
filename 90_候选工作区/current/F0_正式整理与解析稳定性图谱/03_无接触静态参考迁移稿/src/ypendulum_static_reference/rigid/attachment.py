"""Eccentric rigid-bob attachment kinematics and force/torque mapping."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .rotation import body_to_world_angular_velocity, validate_rotation


def _vector3(value: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape != (3,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be a finite three-vector.")
    return array


def _rotation(rotation: np.ndarray) -> np.ndarray:
    return validate_rotation(rotation)


@dataclass(frozen=True)
class AttachmentKinematics:
    position: np.ndarray
    velocity: np.ndarray
    world_arm: np.ndarray
    angular_velocity_world: np.ndarray


@dataclass(frozen=True)
class RigidWrench:
    force: np.ndarray
    torque_about_center: np.ndarray


@dataclass(frozen=True)
class AttachmentInteraction:
    connection_position: np.ndarray
    force_on_material: np.ndarray
    body_wrench: RigidWrench


def attachment_kinematics(
    bob_position: np.ndarray,
    bob_velocity: np.ndarray,
    rotation: np.ndarray,
    angular_velocity_body: np.ndarray,
    attachment_arm_body: np.ndarray,
) -> AttachmentKinematics:
    center = _vector3(bob_position, "bob_position")
    center_velocity = _vector3(bob_velocity, "bob_velocity")
    matrix = _rotation(rotation)
    body_arm = _vector3(attachment_arm_body, "attachment_arm_body")
    angular_world = body_to_world_angular_velocity(matrix, angular_velocity_body)
    world_arm = matrix @ body_arm
    return AttachmentKinematics(
        position=center + world_arm,
        velocity=center_velocity + np.cross(angular_world, world_arm),
        world_arm=world_arm,
        angular_velocity_world=angular_world,
    )


def map_attachment_force_to_body(
    rotation: np.ndarray,
    attachment_arm_body: np.ndarray,
    force_on_body: np.ndarray,
) -> RigidWrench:
    matrix = _rotation(rotation)
    world_arm = matrix @ _vector3(attachment_arm_body, "attachment_arm_body")
    force = _vector3(force_on_body, "force_on_body")
    return RigidWrench(force=force, torque_about_center=np.cross(world_arm, force))


def attachment_action_reaction(
    bob_position: np.ndarray,
    rotation: np.ndarray,
    attachment_arm_body: np.ndarray,
    force_on_body: np.ndarray,
) -> AttachmentInteraction:
    """Return the paired endpoint force and exactly opposite rigid-body wrench."""

    center = _vector3(bob_position, "bob_position")
    matrix = _rotation(rotation)
    body_arm = _vector3(attachment_arm_body, "attachment_arm_body")
    world_arm = matrix @ body_arm
    wrench = map_attachment_force_to_body(matrix, body_arm, force_on_body)
    return AttachmentInteraction(
        connection_position=center + world_arm,
        force_on_material=-wrench.force,
        body_wrench=wrench,
    )

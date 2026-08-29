"""Static eccentric rigid-bob attachment geometry and force mapping."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .rotation import validate_rotation


def _vector3(value: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape != (3,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be a finite three-vector.")
    return array


@dataclass(frozen=True)
class AttachmentGeometry:
    position: np.ndarray
    world_arm: np.ndarray


@dataclass(frozen=True)
class RigidWrench:
    force: np.ndarray
    torque_about_center: np.ndarray


@dataclass(frozen=True)
class AttachmentInteraction:
    connection_position: np.ndarray
    force_on_material: np.ndarray
    body_wrench: RigidWrench


def attachment_geometry(
    bob_position: np.ndarray,
    rotation: np.ndarray,
    attachment_arm_body: np.ndarray,
) -> AttachmentGeometry:
    center = _vector3(bob_position, "bob_position")
    matrix = validate_rotation(rotation)
    body_arm = _vector3(attachment_arm_body, "attachment_arm_body")
    world_arm = matrix @ body_arm
    return AttachmentGeometry(position=center + world_arm, world_arm=world_arm)


def map_attachment_force_to_body(
    rotation: np.ndarray,
    attachment_arm_body: np.ndarray,
    force_on_body: np.ndarray,
) -> RigidWrench:
    matrix = validate_rotation(rotation)
    world_arm = matrix @ _vector3(attachment_arm_body, "attachment_arm_body")
    force = _vector3(force_on_body, "force_on_body")
    return RigidWrench(force=force, torque_about_center=np.cross(world_arm, force))


def attachment_action_reaction(
    bob_position: np.ndarray,
    rotation: np.ndarray,
    attachment_arm_body: np.ndarray,
    force_on_body: np.ndarray,
) -> AttachmentInteraction:
    """Return paired static endpoint force and opposite rigid-body wrench."""

    geometry = attachment_geometry(bob_position, rotation, attachment_arm_body)
    wrench = map_attachment_force_to_body(rotation, attachment_arm_body, force_on_body)
    return AttachmentInteraction(
        connection_position=geometry.position,
        force_on_material=-wrench.force,
        body_wrench=wrench,
    )

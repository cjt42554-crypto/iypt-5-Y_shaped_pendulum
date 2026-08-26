"""Small state contract for the HF-v2 pure-physics kernel."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .topology import HFV2Topology


def _frozen_array(value: np.ndarray, shape: tuple[int, ...], name: str) -> np.ndarray:
    array = np.array(value, dtype=float, copy=True)
    if array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {array.shape}.")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite.")
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class HFV2State:
    """Free material nodes plus one finite rigid bob.

    ``bob_rotation`` maps body coordinates to world coordinates and
    ``bob_angular_velocity_body`` is expressed in body coordinates.
    """

    free_node_positions: np.ndarray
    free_node_velocities: np.ndarray
    bob_position: np.ndarray
    bob_velocity: np.ndarray
    bob_rotation: np.ndarray
    bob_angular_velocity_body: np.ndarray

    def __post_init__(self) -> None:
        positions = np.array(self.free_node_positions, dtype=float, copy=True)
        velocities = np.array(self.free_node_velocities, dtype=float, copy=True)
        if positions.ndim != 2 or positions.shape[1:] != (3,):
            raise ValueError("free_node_positions must have shape (n, 3).")
        if velocities.shape != positions.shape:
            raise ValueError("free_node_velocities must match free_node_positions.")
        if not np.all(np.isfinite(positions)) or not np.all(np.isfinite(velocities)):
            raise ValueError("Free material-node state must be finite.")
        positions.setflags(write=False)
        velocities.setflags(write=False)
        rotation = _frozen_array(self.bob_rotation, (3, 3), "bob_rotation")
        orthogonality = float(np.linalg.norm(rotation.T @ rotation - np.eye(3), ord="fro"))
        determinant = float(np.linalg.det(rotation))
        if orthogonality > 5.0e-12 or abs(determinant - 1.0) > 5.0e-12:
            raise ValueError("bob_rotation must lie in SO(3) to roundoff tolerance.")
        object.__setattr__(self, "free_node_positions", positions)
        object.__setattr__(self, "free_node_velocities", velocities)
        object.__setattr__(
            self, "bob_position", _frozen_array(self.bob_position, (3,), "bob_position")
        )
        object.__setattr__(
            self, "bob_velocity", _frozen_array(self.bob_velocity, (3,), "bob_velocity")
        )
        object.__setattr__(self, "bob_rotation", rotation)
        object.__setattr__(
            self,
            "bob_angular_velocity_body",
            _frozen_array(
                self.bob_angular_velocity_body,
                (3,),
                "bob_angular_velocity_body",
            ),
        )

    def validate_topology(self, topology: HFV2Topology) -> None:
        if self.free_node_positions.shape[0] != topology.free_node_count:
            raise ValueError(
                "State free-node count does not match the explicit topology registration."
            )

    @property
    def bob_angular_velocity_world(self) -> np.ndarray:
        return self.bob_rotation @ self.bob_angular_velocity_body

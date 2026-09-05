"""Small state contract for the HF-v2 pure-physics kernel."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .rigid.rotation import validate_rotation
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

    free_node_ids: tuple[str, ...]
    free_node_positions: np.ndarray
    free_node_velocities: np.ndarray
    bob_position: np.ndarray
    bob_velocity: np.ndarray
    bob_rotation: np.ndarray
    bob_angular_velocity_body: np.ndarray

    def __post_init__(self) -> None:
        free_node_ids = tuple(self.free_node_ids)
        if any(not node_id or node_id.strip() != node_id for node_id in free_node_ids):
            raise ValueError("free_node_ids must contain non-empty, stripped strings.")
        if len(free_node_ids) != len(set(free_node_ids)):
            raise ValueError("free_node_ids must be unique.")
        positions = np.array(self.free_node_positions, dtype=float, copy=True)
        velocities = np.array(self.free_node_velocities, dtype=float, copy=True)
        if positions.ndim != 2 or positions.shape[1:] != (3,):
            raise ValueError("free_node_positions must have shape (n, 3).")
        if velocities.shape != positions.shape:
            raise ValueError("free_node_velocities must match free_node_positions.")
        if not np.all(np.isfinite(positions)) or not np.all(np.isfinite(velocities)):
            raise ValueError("Free material-node state must be finite.")
        if positions.shape[0] != len(free_node_ids):
            raise ValueError("free_node_ids must exactly label the free-node state rows.")
        positions.setflags(write=False)
        velocities.setflags(write=False)
        rotation = np.array(validate_rotation(self.bob_rotation, "bob_rotation"), copy=True)
        rotation.setflags(write=False)
        object.__setattr__(self, "free_node_ids", free_node_ids)
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
        if self.free_node_ids != topology.free_node_ids:
            raise ValueError(
                "State free-node layout does not exactly match the topology registration."
            )

    @property
    def bob_angular_velocity_world(self) -> np.ndarray:
        return self.bob_rotation @ self.bob_angular_velocity_body

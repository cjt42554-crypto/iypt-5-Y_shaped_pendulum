"""Position-and-orientation state contract for the static reference package."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .rigid.rotation import validate_rotation
from .topology import StaticReferenceTopology


def _frozen_array(value: np.ndarray, shape: tuple[int, ...], name: str) -> np.ndarray:
    array = np.array(value, dtype=float, copy=True)
    if array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {array.shape}.")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite.")
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class StaticReferenceState:
    """Free material-node positions plus rigid-bob position and orientation."""

    free_node_ids: tuple[str, ...]
    free_node_positions: np.ndarray
    bob_position: np.ndarray
    bob_rotation: np.ndarray

    def __post_init__(self) -> None:
        free_node_ids = tuple(self.free_node_ids)
        if any(not node_id or node_id.strip() != node_id for node_id in free_node_ids):
            raise ValueError("free_node_ids must contain non-empty, stripped strings.")
        if len(free_node_ids) != len(set(free_node_ids)):
            raise ValueError("free_node_ids must be unique.")
        positions = np.array(self.free_node_positions, dtype=float, copy=True)
        if positions.ndim != 2 or positions.shape[1:] != (3,):
            raise ValueError("free_node_positions must have shape (n, 3).")
        if not np.all(np.isfinite(positions)):
            raise ValueError("Free material-node positions must be finite.")
        if positions.shape[0] != len(free_node_ids):
            raise ValueError("free_node_ids must exactly label the free-node position rows.")
        positions.setflags(write=False)
        rotation = np.array(validate_rotation(self.bob_rotation, "bob_rotation"), copy=True)
        rotation.setflags(write=False)
        object.__setattr__(self, "free_node_ids", free_node_ids)
        object.__setattr__(self, "free_node_positions", positions)
        object.__setattr__(
            self, "bob_position", _frozen_array(self.bob_position, (3,), "bob_position")
        )
        object.__setattr__(self, "bob_rotation", rotation)

    def validate_topology(self, topology: StaticReferenceTopology) -> None:
        if self.free_node_ids != topology.free_node_ids:
            raise ValueError(
                "State free-node layout does not exactly match the topology registration."
            )

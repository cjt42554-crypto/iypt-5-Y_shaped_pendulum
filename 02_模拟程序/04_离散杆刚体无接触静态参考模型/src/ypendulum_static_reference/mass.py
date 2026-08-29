"""Static lumped-mass registration without dynamic observables."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .state import StaticReferenceState
from .topology import StaticReferenceTopology


@dataclass(frozen=True)
class StaticMassDistribution:
    """Positive material-node and rigid-bob masses used by static loading."""

    free_node_ids: tuple[str, ...]
    free_node_mass: np.ndarray
    bob_mass: float

    def __post_init__(self) -> None:
        free_node_ids = tuple(self.free_node_ids)
        if any(not node_id or node_id.strip() != node_id for node_id in free_node_ids):
            raise ValueError("free_node_ids must contain non-empty, stripped strings.")
        if len(free_node_ids) != len(set(free_node_ids)):
            raise ValueError("free_node_ids must be unique.")
        masses = np.array(self.free_node_mass, dtype=float, copy=True)
        if masses.ndim != 1 or not np.all(np.isfinite(masses)) or np.any(masses <= 0.0):
            raise ValueError("free_node_mass must be a one-dimensional positive finite array.")
        if masses.size != len(free_node_ids):
            raise ValueError("free_node_ids must exactly label the free-node mass entries.")
        bob_mass = float(self.bob_mass)
        if not np.isfinite(bob_mass) or bob_mass <= 0.0:
            raise ValueError("bob_mass must be positive and finite.")
        masses.setflags(write=False)
        object.__setattr__(self, "free_node_ids", free_node_ids)
        object.__setattr__(self, "free_node_mass", masses)
        object.__setattr__(self, "bob_mass", bob_mass)

    def validate_topology(self, topology: StaticReferenceTopology) -> None:
        if self.free_node_ids != topology.free_node_ids:
            raise ValueError(
                "Mass free-node layout does not exactly match the topology registration."
            )

    def validate_state(self, state: StaticReferenceState) -> None:
        if self.free_node_ids != state.free_node_ids:
            raise ValueError("Mass and state free-node layouts do not exactly match.")

"""Lumped translational mass and finite rigid-body inertia contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .state import HFV2State
    from .topology import HFV2Topology


@dataclass(frozen=True)
class MassProperties:
    """Positive material-node masses and a body-frame bob inertia tensor."""

    free_node_ids: tuple[str, ...]
    free_node_mass: np.ndarray
    bob_mass: float
    bob_inertia_body: np.ndarray

    def __post_init__(self) -> None:
        free_node_ids = tuple(self.free_node_ids)
        if any(not node_id or node_id.strip() != node_id for node_id in free_node_ids):
            raise ValueError("free_node_ids must contain non-empty, stripped strings.")
        if len(free_node_ids) != len(set(free_node_ids)):
            raise ValueError("free_node_ids must be unique.")
        masses = np.array(self.free_node_mass, dtype=float, copy=True)
        inertia = np.array(self.bob_inertia_body, dtype=float, copy=True)
        if masses.ndim != 1 or not np.all(np.isfinite(masses)) or np.any(masses <= 0.0):
            raise ValueError("free_node_mass must be a one-dimensional positive finite array.")
        if masses.size != len(free_node_ids):
            raise ValueError("free_node_ids must exactly label the free-node mass entries.")
        if not np.isfinite(self.bob_mass) or self.bob_mass <= 0.0:
            raise ValueError("bob_mass must be positive and finite.")
        if inertia.shape != (3, 3) or not np.all(np.isfinite(inertia)):
            raise ValueError("bob_inertia_body must be a finite 3-by-3 matrix.")
        if not np.allclose(inertia, inertia.T, rtol=0.0, atol=1.0e-14):
            raise ValueError("bob_inertia_body must be symmetric.")
        principal_moments = np.linalg.eigvalsh(inertia)
        if float(np.min(principal_moments)) <= 0.0:
            raise ValueError("bob_inertia_body must be positive definite.")
        realizability_tolerance = (
            64.0 * np.finfo(float).eps * float(np.max(principal_moments))
        )
        if principal_moments[2] > principal_moments[0] + principal_moments[1] + realizability_tolerance:
            raise ValueError(
                "bob_inertia_body principal moments must satisfy the triangle inequalities."
            )
        masses.setflags(write=False)
        inertia.setflags(write=False)
        object.__setattr__(self, "free_node_ids", free_node_ids)
        object.__setattr__(self, "free_node_mass", masses)
        object.__setattr__(self, "bob_mass", float(self.bob_mass))
        object.__setattr__(self, "bob_inertia_body", inertia)

    def validate_topology(self, topology: HFV2Topology) -> None:
        if self.free_node_ids != topology.free_node_ids:
            raise ValueError(
                "Mass free-node layout does not exactly match the topology registration."
            )

    def validate_state(self, state: HFV2State) -> None:
        if self.free_node_ids != state.free_node_ids:
            raise ValueError("Mass and state free-node layouts do not exactly match.")

    def kinetic_energy(
        self,
        free_node_velocity: np.ndarray,
        bob_velocity: np.ndarray,
        bob_angular_velocity_body: np.ndarray,
    ) -> float:
        node_velocity = np.asarray(free_node_velocity, dtype=float)
        linear_velocity = np.asarray(bob_velocity, dtype=float)
        angular_velocity = np.asarray(bob_angular_velocity_body, dtype=float)
        if node_velocity.shape != (self.free_node_mass.size, 3):
            raise ValueError("free_node_velocity shape does not match free_node_mass.")
        if linear_velocity.shape != (3,) or angular_velocity.shape != (3,):
            raise ValueError("Bob linear and angular velocities must be three-vectors.")
        if not all(
            np.all(np.isfinite(value))
            for value in (node_velocity, linear_velocity, angular_velocity)
        ):
            raise ValueError("Velocities must be finite.")
        node_energy = 0.5 * float(np.sum(self.free_node_mass[:, None] * node_velocity**2))
        bob_linear = 0.5 * self.bob_mass * float(np.dot(linear_velocity, linear_velocity))
        bob_rotational = 0.5 * float(angular_velocity @ self.bob_inertia_body @ angular_velocity)
        return node_energy + bob_linear + bob_rotational

    def total_linear_momentum(
        self, free_node_velocity: np.ndarray, bob_velocity: np.ndarray
    ) -> np.ndarray:
        node_velocity = np.asarray(free_node_velocity, dtype=float)
        linear_velocity = np.asarray(bob_velocity, dtype=float)
        if node_velocity.shape != (self.free_node_mass.size, 3):
            raise ValueError("free_node_velocity shape does not match free_node_mass.")
        if linear_velocity.shape != (3,):
            raise ValueError("bob_velocity must be a three-vector.")
        if not np.all(np.isfinite(node_velocity)) or not np.all(np.isfinite(linear_velocity)):
            raise ValueError("Velocities used for momentum must be finite.")
        momentum = np.sum(self.free_node_mass[:, None] * node_velocity, axis=0) + (
            self.bob_mass * linear_velocity
        )
        if not np.all(np.isfinite(momentum)):
            raise FloatingPointError("Total linear momentum is non-finite.")
        return momentum

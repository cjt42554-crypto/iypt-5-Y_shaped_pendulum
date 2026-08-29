"""Immutable contracts for the formal no-contact static reference."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _frozen_array(value: np.ndarray, shape: tuple[int, ...], name: str) -> np.ndarray:
    array = np.array(value, dtype=float, copy=True)
    if array.shape != shape or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite with shape {shape}.")
    array.setflags(write=False)
    return array


def _nonnegative_finite(value: float, name: str) -> float:
    scalar = float(value)
    if not np.isfinite(scalar) or scalar < 0.0:
        raise ValueError(f"{name} must be finite and non-negative.")
    return scalar


@dataclass(frozen=True)
class BranchMaterial:
    """Branch-wise material data with no independent rest-length input."""

    branch_id: str
    axial_rigidity: float
    bending_stiffness: float
    line_density: float
    displaced_volume_per_length: float

    def __post_init__(self) -> None:
        if not self.branch_id or self.branch_id.strip() != self.branch_id:
            raise ValueError("branch_id must be a non-empty, stripped string.")
        axial = float(self.axial_rigidity)
        if not np.isfinite(axial) or axial <= 0.0:
            raise ValueError("axial_rigidity must be finite and strictly positive.")
        object.__setattr__(self, "axial_rigidity", axial)
        object.__setattr__(
            self,
            "bending_stiffness",
            _nonnegative_finite(self.bending_stiffness, "bending_stiffness"),
        )
        density = float(self.line_density)
        if not np.isfinite(density) or density <= 0.0:
            raise ValueError("line_density must be finite and strictly positive.")
        object.__setattr__(self, "line_density", density)
        object.__setattr__(
            self,
            "displaced_volume_per_length",
            _nonnegative_finite(
                self.displaced_volume_per_length,
                "displaced_volume_per_length",
            ),
        )


@dataclass(frozen=True)
class StaticEnvironment:
    gravity: np.ndarray
    fluid_density: float
    buoyancy_enabled: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "gravity", _frozen_array(self.gravity, (3,), "gravity"))
        object.__setattr__(
            self,
            "fluid_density",
            _nonnegative_finite(self.fluid_density, "fluid_density"),
        )
        if type(self.buoyancy_enabled) is not bool:
            raise ValueError("buoyancy_enabled must be a boolean without conversion.")


@dataclass(frozen=True)
class RigidBobProperties:
    mass: float
    displaced_volume: float
    attachment_arm_body: np.ndarray

    def __post_init__(self) -> None:
        mass = float(self.mass)
        if not np.isfinite(mass) or mass <= 0.0:
            raise ValueError("Bob mass must be finite and strictly positive.")
        object.__setattr__(self, "mass", mass)
        object.__setattr__(
            self,
            "displaced_volume",
            _nonnegative_finite(self.displaced_volume, "displaced_volume"),
        )
        object.__setattr__(
            self,
            "attachment_arm_body",
            _frozen_array(self.attachment_arm_body, (3,), "attachment_arm_body"),
        )


@dataclass(frozen=True)
class StaticSeed:
    """One explicitly identified initial coordinate set."""

    seed_id: str
    free_node_ids: tuple[str, ...]
    free_node_positions: np.ndarray
    bob_position: np.ndarray
    bob_rotation_vector: np.ndarray

    def __post_init__(self) -> None:
        if not self.seed_id or self.seed_id.strip() != self.seed_id:
            raise ValueError("seed_id must be a non-empty, stripped string.")
        identifiers = tuple(self.free_node_ids)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("StaticSeed free_node_ids must be unique.")
        if any(not value or value.strip() != value for value in identifiers):
            raise ValueError("StaticSeed free_node_ids must be non-empty and stripped.")
        positions = _frozen_array(
            self.free_node_positions,
            (len(identifiers), 3),
            "free_node_positions",
        )
        object.__setattr__(self, "free_node_ids", identifiers)
        object.__setattr__(self, "free_node_positions", positions)
        object.__setattr__(
            self,
            "bob_position",
            _frozen_array(self.bob_position, (3,), "bob_position"),
        )
        object.__setattr__(
            self,
            "bob_rotation_vector",
            _frozen_array(self.bob_rotation_vector, (3,), "bob_rotation_vector"),
        )


@dataclass(frozen=True)
class StaticCoordinates:
    """Opaque coordinate vector carrying its complete static-assembly token."""

    assembly_token: str
    values: np.ndarray

    def __post_init__(self) -> None:
        if not self.assembly_token:
            raise ValueError("assembly_token must be non-empty.")
        values = np.array(self.values, dtype=float, copy=True)
        if values.ndim != 1 or not np.all(np.isfinite(values)):
            raise ValueError("StaticCoordinates values must be a finite vector.")
        values.setflags(write=False)
        object.__setattr__(self, "values", values)

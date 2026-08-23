"""Result types for the independent high-fidelity backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class HighFidelityResult:
    """Complete sampled state of ``HF-DISCRETE-ROD-RIGID-BOB-1.0``."""

    time: np.ndarray
    integration_time: np.ndarray
    integration_particle_positions: np.ndarray
    integration_particle_velocities: np.ndarray
    integration_bob_position: np.ndarray
    integration_bob_velocity: np.ndarray
    integration_bob_quaternion: np.ndarray
    integration_bob_angular_velocity: np.ndarray
    particle_positions: np.ndarray
    particle_velocities: np.ndarray
    junction_position: np.ndarray
    junction_velocity: np.ndarray
    bob_position: np.ndarray
    bob_velocity: np.ndarray
    bob_quaternion: np.ndarray
    bob_angular_velocity: np.ndarray
    bob_attachment_position: np.ndarray
    cable_positions: dict[str, np.ndarray]
    cable_velocities: dict[str, np.ndarray]
    cable_axial_force: dict[str, np.ndarray]
    cable_tension: dict[str, np.ndarray]
    guard_margins: dict[str, np.ndarray]
    energy: dict[str, np.ndarray]
    reactions: dict[str, np.ndarray]
    events: list[dict[str, Any]]
    diagnostics: dict[str, Any]
    physical_status: str
    numerical_status: str
    valid_interval: tuple[float, float]
    model_id: str = "HF-DISCRETE-ROD-RIGID-BOB-1.0"
    run_directory: Path | None = field(default=None, repr=False)

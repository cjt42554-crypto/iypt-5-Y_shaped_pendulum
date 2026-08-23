"""Result and diagnostic data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class StaticEquilibrium:
    positions: np.ndarray
    velocities: np.ndarray
    force_residual_max: float
    iterations: int
    converged: bool
    fixed_nodes: tuple[int, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationResult:
    time: np.ndarray
    positions: np.ndarray
    velocities: np.ndarray
    tension: np.ndarray
    stretch: np.ndarray
    active: np.ndarray
    energy: dict[str, np.ndarray]
    reactions: dict[str, np.ndarray]
    events: list[dict[str, Any]]
    diagnostics: dict[str, Any]
    run_directory: Path | None = None
    model_name: str = "H1"
    claim_level: str = "VERIFIED"


@dataclass
class TorusResult:
    time: np.ndarray
    state: np.ndarray
    position: np.ndarray
    tensions: np.ndarray
    energy: np.ndarray
    event: dict[str, Any] | None
    model_name: str = "A1"

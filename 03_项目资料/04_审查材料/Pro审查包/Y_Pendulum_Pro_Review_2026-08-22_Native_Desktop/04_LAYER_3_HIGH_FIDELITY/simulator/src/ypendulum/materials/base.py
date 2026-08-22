"""Material model interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import numpy.typing as npt

Array = npt.NDArray[np.float64]


@dataclass(frozen=True)
class AxialResponse:
    tension: Array
    active: npt.NDArray[np.bool_]
    elastic_energy: Array
    dissipation_rate: Array
    d_tension_d_delta: Array
    d_tension_d_delta_dot: Array


class AxialMaterial(Protocol):
    def evaluate(self, delta: Array, delta_dot: Array, rest_length: Array) -> AxialResponse: ...

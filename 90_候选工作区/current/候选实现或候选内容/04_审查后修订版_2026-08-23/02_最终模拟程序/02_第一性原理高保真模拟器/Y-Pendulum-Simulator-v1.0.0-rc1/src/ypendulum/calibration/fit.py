"""Bounded least-squares wrapper used by explicit calibration workflows."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from scipy.optimize import least_squares


def bounded_fit(
    residual_function: Callable[[np.ndarray], np.ndarray],
    initial: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
):
    return least_squares(residual_function, initial, bounds=(lower, upper), method="trf")

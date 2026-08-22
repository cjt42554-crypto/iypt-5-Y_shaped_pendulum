"""Deterministic synthetic measurement noise."""

from __future__ import annotations

import numpy as np


def add_gaussian_noise(values: np.ndarray, sigma: float, rng: np.random.Generator) -> np.ndarray:
    if sigma < 0:
        raise ValueError("Noise standard deviation cannot be negative.")
    return np.asarray(values, dtype=float) + rng.normal(0.0, sigma, size=np.shape(values))

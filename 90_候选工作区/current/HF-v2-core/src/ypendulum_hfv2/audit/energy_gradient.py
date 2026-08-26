"""Coordinatewise centered finite-difference audits for conservative forces."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class GradientSample:
    relative_step: float
    absolute_step: float
    absolute_error: float
    relative_error: float


def central_difference_gradient(
    energy: Callable[[np.ndarray], float], coordinates: np.ndarray, absolute_step: float
) -> np.ndarray:
    values = np.asarray(coordinates, dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("coordinates must be finite.")
    if not np.isfinite(absolute_step) or absolute_step <= 0.0:
        raise ValueError("absolute_step must be positive and finite.")
    flat = values.reshape(-1)
    gradient = np.empty_like(flat)
    for index in range(flat.size):
        plus = flat.copy()
        minus = flat.copy()
        plus[index] += absolute_step
        minus[index] -= absolute_step
        positive_energy = float(energy(plus.reshape(values.shape)))
        negative_energy = float(energy(minus.reshape(values.shape)))
        if not np.isfinite(positive_energy) or not np.isfinite(negative_energy):
            raise FloatingPointError("Finite-difference energy evaluation was non-finite.")
        gradient[index] = (positive_energy - negative_energy) / (2.0 * absolute_step)
    return gradient.reshape(values.shape)


def force_gradient_samples(
    energy: Callable[[np.ndarray], float],
    coordinates: np.ndarray,
    analytic_force: np.ndarray,
    relative_steps: Iterable[float],
    *,
    coordinate_scale: float,
) -> tuple[GradientSample, ...]:
    values = np.asarray(coordinates, dtype=float)
    force = np.asarray(analytic_force, dtype=float)
    if force.shape != values.shape or not np.all(np.isfinite(force)):
        raise ValueError("analytic_force must be finite and match coordinates.")
    if not np.isfinite(coordinate_scale) or coordinate_scale <= 0.0:
        raise ValueError("coordinate_scale must be positive and finite.")
    samples: list[GradientSample] = []
    for relative_step in relative_steps:
        if not np.isfinite(relative_step) or relative_step <= 0.0:
            raise ValueError("Finite-difference relative steps must be positive and finite.")
        absolute_step = float(relative_step) * coordinate_scale
        gradient = central_difference_gradient(energy, values, absolute_step)
        absolute_error = float(np.linalg.norm(force + gradient))
        denominator = max(
            float(np.linalg.norm(force)),
            float(np.linalg.norm(gradient)),
            np.finfo(float).tiny,
        )
        samples.append(
            GradientSample(
                relative_step=float(relative_step),
                absolute_step=absolute_step,
                absolute_error=absolute_error,
                relative_error=absolute_error / denominator,
            )
        )
    return tuple(samples)

"""Independent physical-gap and socket-validity Jacobian cross-checks."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ypendulum_hfv2.statics.contact_assembly import ContactCoordinates

from .assembly import P3RContactAssembly


@dataclass(frozen=True)
class JacobianSample:
    difference_step: float
    maximum_row_relative_error: float
    matrix_relative_error: float


def _errors(
    reference: np.ndarray,
    comparison: np.ndarray,
    *,
    denominator_floor: float,
) -> tuple[float, float]:
    row_denominator = np.maximum(
        np.maximum(np.linalg.norm(reference, axis=1), np.linalg.norm(comparison, axis=1)),
        denominator_floor,
    )
    row_relative = np.linalg.norm(reference - comparison, axis=1) / row_denominator
    matrix_denominator = max(
        float(np.linalg.norm(reference)),
        float(np.linalg.norm(comparison)),
        denominator_floor,
    )
    return (
        float(np.max(row_relative)),
        float(np.linalg.norm(reference - comparison) / matrix_denominator),
    )


def physical_gap_jacobian_samples(
    assembly: P3RContactAssembly,
    coordinates: ContactCoordinates,
    difference_steps: tuple[float, ...],
) -> tuple[JacobianSample, ...]:
    analytic = assembly.evaluate(coordinates).contact.gap_jacobian
    samples = []
    for value in difference_steps:
        step = float(value)
        if not np.isfinite(step) or step <= 0.0:
            raise ValueError("Physical-gap difference steps must be finite and positive.")
        finite_difference = np.empty_like(analytic)
        for column in range(coordinates.values.size):
            plus = np.array(coordinates.values, copy=True)
            minus = np.array(coordinates.values, copy=True)
            plus[column] += step
            minus[column] -= step
            plus_gaps = assembly.evaluate(
                assembly.coordinates_from_values(plus)
            ).contact.gaps_m
            minus_gaps = assembly.evaluate(
                assembly.coordinates_from_values(minus)
            ).contact.gaps_m
            finite_difference[:, column] = (plus_gaps - minus_gaps) / (2.0 * step)
        maximum, matrix = _errors(
            analytic,
            finite_difference,
            denominator_floor=np.finfo(float).tiny,
        )
        samples.append(JacobianSample(step, maximum, matrix))
    return tuple(samples)


def validity_jacobian_samples(
    assembly: P3RContactAssembly,
    coordinates: ContactCoordinates,
    difference_steps: tuple[float, ...],
) -> tuple[JacobianSample, ...]:
    """Compare the solver Jacobian with an independent five-point stencil."""

    validity = assembly.evaluate(coordinates).validity
    primary = validity.normalized_jacobian
    samples = []
    for value in difference_steps:
        step = float(value)
        if not np.isfinite(step) or step <= 0.0:
            raise ValueError("Validity difference steps must be finite and positive.")
        five_point = np.empty_like(primary)
        for column in range(coordinates.values.size):
            minus_two = np.array(coordinates.values, copy=True)
            minus_one = np.array(coordinates.values, copy=True)
            plus_one = np.array(coordinates.values, copy=True)
            plus_two = np.array(coordinates.values, copy=True)
            minus_two[column] -= 2.0 * step
            minus_one[column] -= step
            plus_one[column] += step
            plus_two[column] += 2.0 * step
            raw_column = (
                assembly._validity_values_from_coordinates(minus_two)
                - 8.0 * assembly._validity_values_from_coordinates(minus_one)
                + 8.0 * assembly._validity_values_from_coordinates(plus_one)
                - assembly._validity_values_from_coordinates(plus_two)
            ) / (12.0 * step)
            five_point[:, column] = raw_column / validity.scales
        maximum, matrix = _errors(
            primary,
            five_point,
            denominator_floor=1.0,
        )
        samples.append(JacobianSample(step, maximum, matrix))
    return tuple(samples)

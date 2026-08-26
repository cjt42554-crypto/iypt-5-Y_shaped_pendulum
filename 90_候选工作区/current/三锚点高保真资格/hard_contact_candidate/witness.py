"""Closest-point witnesses and envelope-theorem gap gradients."""

from __future__ import annotations

import numpy as np

from .parameter_domain import _validate_parameter_polygon
from .types import Array, ContactWitness, DegenerateContactGeometry
from .witness_candidates import closest_parameter_candidates


def closest_segment_pair_witness(
    first_start: Array,
    first_end: Array,
    second_start: Array,
    second_end: Array,
    *,
    required_center_distance_m: float,
    parameter_polygon: Array | None = None,
    geometry_singularity_m: float = 1.0e-14,
    tie_absolute_m: float = 1.0e-12,
    tie_relative: float = 1.0e-10,
) -> ContactWitness:
    p0, p1, q0, q1 = (np.asarray(value, dtype=float) for value in (first_start, first_end, second_start, second_end))
    if any(value.shape != (3,) for value in (p0, p1, q0, q1)):
        raise ValueError("Segment endpoints must be three-vectors.")
    if not all(np.all(np.isfinite(value)) for value in (p0, p1, q0, q1)):
        raise ValueError("Segment endpoints must be finite.")
    if not np.isfinite(required_center_distance_m) or required_center_distance_m < 0.0:
        raise ValueError("required_center_distance_m must be finite and non-negative.")
    if not np.isfinite(geometry_singularity_m) or geometry_singularity_m <= 0.0:
        raise ValueError("geometry_singularity_m must be finite and positive.")
    u, v = p1 - p0, q1 - q0
    if np.linalg.norm(u) <= geometry_singularity_m or np.linalg.norm(v) <= geometry_singularity_m:
        raise DegenerateContactGeometry("Collapsed contact segment has no admissible KKT witness.")
    candidates = closest_parameter_candidates(p0, p1, q0, q1, _validate_parameter_polygon(parameter_polygon), geometry_singularity_m)
    minimum = min(item[2] for item in candidates)
    tie = tie_absolute_m + tie_relative * max(minimum, required_center_distance_m, geometry_singularity_m)
    minimizers = [item for item in candidates if item[2] <= minimum + tie]
    minimizers.sort(key=lambda item: (float(item[1][0]), float(item[1][1]), item[0]))
    label, parameter, _ = minimizers[0]
    s, t = float(np.clip(parameter[0], 0.0, 1.0)), float(np.clip(parameter[1], 0.0, 1.0))
    first_point, second_point = p0 + s * u, q0 + t * v
    delta = first_point - second_point
    distance = float(np.linalg.norm(delta))
    unique = len(minimizers) == 1
    differentiable = unique and distance > geometry_singularity_m
    if differentiable:
        normal = delta / distance
        gradient = np.vstack([(1.0 - s) * normal, s * normal, -(1.0 - t) * normal, -t * normal])
    else:
        normal, gradient = np.full(3, np.nan), np.full((4, 3), np.nan)
    return ContactWitness(
        first_parameter=s,
        second_parameter=t,
        first_point_m=first_point,
        second_point_m=second_point,
        distance_m=distance,
        required_center_distance_m=float(required_center_distance_m),
        gap_m=distance - float(required_center_distance_m),
        normal_second_to_first=normal,
        endpoint_gap_gradient=gradient,
        unique=unique,
        differentiable=differentiable,
        active_feature=label,
        competing_minimizer_count=len(minimizers),
    )

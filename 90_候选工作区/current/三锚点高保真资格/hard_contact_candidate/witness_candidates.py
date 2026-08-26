"""Candidate generation for fixed-domain segment-pair distance minimization."""

from __future__ import annotations

import numpy as np

from .parameter_domain import _inside_convex_polygon
from .types import Array, DegenerateContactGeometry


def closest_parameter_candidates(
    p0: Array,
    p1: Array,
    q0: Array,
    q1: Array,
    polygon: Array,
    geometry_singularity_m: float,
) -> list[tuple[str, Array, float]]:
    u, v, w = p1 - p0, q1 - q0, p0 - q0
    raw: list[tuple[str, Array, float]] = []

    def add(label: str, parameter: Array) -> None:
        value = np.asarray(parameter, dtype=float)
        distance = float(np.linalg.norm(w + value[0] * u - value[1] * v))
        if np.isfinite(distance):
            raw.append((label, value, distance))

    for index, vertex in enumerate(polygon):
        add(f"vertex:{index}", vertex)
    if polygon.shape[0] == 2:
        edges = [(polygon[0], polygon[1])]
    elif polygon.shape[0] >= 3:
        edges = list(zip(polygon, np.roll(polygon, -1, axis=0), strict=True))
    else:
        edges = []
    for index, (current, following) in enumerate(edges):
        direction = following - current
        spatial_start = w + current[0] * u - current[1] * v
        spatial_direction = direction[0] * u - direction[1] * v
        denominator = float(np.dot(spatial_direction, spatial_direction))
        fraction = 0.0
        if denominator > geometry_singularity_m**2:
            fraction = float(np.clip(-np.dot(spatial_start, spatial_direction) / denominator, 0.0, 1.0))
        add(f"edge:{index}", current + fraction * direction)
    if polygon.shape[0] >= 3:
        parameter, _, rank, _ = np.linalg.lstsq(np.column_stack([u, -v]), -w, rcond=None)
        if rank == 2 and _inside_convex_polygon(parameter, polygon, 256.0 * np.finfo(float).eps):
            add("interior", parameter)
    if not raw:
        raise DegenerateContactGeometry("No finite closest-point candidate was generated.")

    unique: list[tuple[str, Array, float]] = []
    tolerance = 512.0 * np.finfo(float).eps
    for label, parameter, distance in raw:
        prior = next((i for i, (_, value, _) in enumerate(unique) if np.linalg.norm(parameter - value) <= tolerance), None)
        if prior is None:
            unique.append((label, parameter, distance))
        elif distance < unique[prior][2]:
            unique[prior] = (label, parameter, distance)
    return unique

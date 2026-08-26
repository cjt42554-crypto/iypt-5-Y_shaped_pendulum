"""Fixed closest-point parameter domains for registered rod contacts."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from .types import Array, DegenerateContactGeometry

def full_parameter_polygon() -> Array:
    """Return the closed unit-square parameter domain in counter-clockwise order."""

    return np.array(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        dtype=float,
    )


def _deduplicate_polygon(vertices: Sequence[Array], tolerance: float) -> Array:
    """Deduplicate an ordered convex domain, including line/point limits."""

    unique: list[Array] = []
    for item in vertices:
        point = np.asarray(item, dtype=float)
        if not unique or np.linalg.norm(point - unique[-1]) > tolerance:
            unique.append(point)
    if len(unique) >= 2 and np.linalg.norm(unique[0] - unique[-1]) <= tolerance:
        unique.pop()
    if not unique:
        return np.empty((0, 2), dtype=float)
    polygon = np.asarray(unique, dtype=float)
    if polygon.shape[0] >= 3:
        signed_double_area = float(
            np.sum(
                polygon[:, 0] * np.roll(polygon[:, 1], -1)
                - polygon[:, 1] * np.roll(polygon[:, 0], -1)
            )
        )
        if signed_double_area < 0.0:
            polygon = polygon[::-1].copy()
    return polygon


def _clip_polygon_halfspace(
    polygon: Array,
    value: Callable[[Array], float],
    *,
    tolerance: float,
) -> Array:
    clipped: list[Array] = []
    vertices = [np.asarray(item, dtype=float) for item in polygon]
    for current, following in zip(vertices, vertices[1:] + vertices[:1], strict=True):
        current_value = float(value(current))
        following_value = float(value(following))
        current_inside = current_value >= -tolerance
        following_inside = following_value >= -tolerance
        if current_inside:
            clipped.append(current)
        if current_inside != following_inside:
            denominator = current_value - following_value
            if denominator == 0.0:
                raise DegenerateContactGeometry("Half-space clipping lost a finite edge intersection.")
            fraction = current_value / denominator
            clipped.append(current + fraction * (following - current))
    return _deduplicate_polygon(clipped, tolerance=max(tolerance, 1.0e-15))


def material_separation_polygon(
    *,
    first_material_start: float,
    first_material_end: float,
    second_material_start: float,
    second_material_end: float,
    minimum_material_separation: float,
) -> Array:
    """Return the formal same-rod admissible ``(xi, eta)`` contact domain.

    The retained domain satisfies

    ``second_material(eta) - first_material(xi) >= minimum_material_separation``.

    It is the same fixed rest-material exclusion used by the formal scalar
    clearance calculation, but exposed as a convex parameter polygon so each
    gap has a closest-point witness and Jacobian.
    """

    values = np.asarray(
        [
            first_material_start,
            first_material_end,
            second_material_start,
            second_material_end,
            minimum_material_separation,
        ],
        dtype=float,
    )
    if not np.all(np.isfinite(values)):
        raise ValueError("Material coordinates must be finite.")
    ds = float(first_material_end - first_material_start)
    dt = float(second_material_end - second_material_start)
    if ds <= 0.0 or dt <= 0.0 or minimum_material_separation < 0.0:
        raise ValueError("Material intervals must be increasing and separation non-negative.")
    offset = float(
        minimum_material_separation
        - (second_material_start - first_material_start)
    )
    scale = max(ds, dt, abs(offset), np.finfo(float).tiny)
    tolerance = 128.0 * np.finfo(float).eps * scale
    return _clip_polygon_halfspace(
        full_parameter_polygon(),
        lambda parameter: parameter[1] * dt - parameter[0] * ds - offset,
        tolerance=tolerance,
    )


def _validate_parameter_polygon(polygon: Array | None) -> Array:
    domain = full_parameter_polygon() if polygon is None else np.asarray(polygon, dtype=float)
    if domain.ndim != 2 or domain.shape[1] != 2 or domain.shape[0] < 1:
        raise ValueError("parameter_polygon must have shape (m,2) with m >= 1.")
    if not np.all(np.isfinite(domain)):
        raise ValueError("parameter_polygon must be finite.")
    tolerance = 1.0e-12
    if np.any(domain < -tolerance) or np.any(domain > 1.0 + tolerance):
        raise ValueError("parameter_polygon must lie in the unit square.")
    domain = _deduplicate_polygon(domain, tolerance=1.0e-14)
    if domain.shape[0] < 1:
        raise ValueError("parameter_polygon contains no admissible parameter.")
    if domain.shape[0] >= 3:
        edge = np.roll(domain, -1, axis=0) - domain
        following_edge = np.roll(edge, -1, axis=0)
        cross = (
            edge[:, 0] * following_edge[:, 1]
            - edge[:, 1] * following_edge[:, 0]
        )
        if np.any(cross < -1.0e-12):
            raise ValueError("parameter_polygon must be convex and counter-clockwise.")
    return domain


def _inside_convex_polygon(point: Array, polygon: Array, tolerance: float) -> bool:
    edge = np.roll(polygon, -1, axis=0) - polygon
    relative = np.asarray(point, dtype=float)[None, :] - polygon
    cross = edge[:, 0] * relative[:, 1] - edge[:, 1] * relative[:, 0]
    return bool(np.all(cross >= -tolerance))



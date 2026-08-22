"""Exact fixed-knot upper geometry and local torus frame utilities."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

Array = npt.NDArray[np.float64]


@dataclass(frozen=True)
class UpperGeometry:
    support_a: Array
    support_b: Array
    axis: Array
    distance: float
    center: Array
    a_a: float
    a_b: float
    h: float
    radial_down: Array
    azimuth: Array


def unit(vector: Array, *, name: str = "vector") -> Array:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-15 or not np.isfinite(norm):
        raise ValueError(f"Cannot normalise degenerate {name}.")
    return np.asarray(vector, dtype=float) / norm


def fixed_knot_upper_geometry(
    support_a: Array,
    support_b: Array,
    length_a: float,
    length_b: float,
    gravity: Array,
) -> UpperGeometry:
    """Intersection-circle geometry for two independently fixed upper lengths.

    ``radial_down`` is the point on the intersection circle furthest in the
    direction of gravity, providing the suspended branch used for initialisation.
    """

    A = np.asarray(support_a, dtype=float)
    B = np.asarray(support_b, dtype=float)
    g = np.asarray(gravity, dtype=float)
    axis_vec = B - A
    d = float(np.linalg.norm(axis_vec))
    if not abs(length_a - length_b) < d < length_a + length_b:
        raise ValueError("Upper lengths do not have a non-degenerate sphere intersection.")
    ex = axis_vec / d
    a_a = (length_a**2 - length_b**2 + d**2) / (2.0 * d)
    a_b = d - a_a
    h2 = length_a**2 - a_a**2
    if h2 <= 0:
        raise ValueError("Upper intersection circle has non-positive radius.")
    h = float(np.sqrt(h2))
    center = A + a_a * ex
    g_perp = g - float(np.dot(g, ex)) * ex
    if np.linalg.norm(g_perp) < 1e-12 * max(np.linalg.norm(g), 1.0):
        # Deterministic fallback when gravity is accidentally parallel to the support axis.
        trial = np.array([0.0, 0.0, 1.0])
        if abs(np.dot(trial, ex)) > 0.9:
            trial = np.array([0.0, 1.0, 0.0])
        g_perp = trial - np.dot(trial, ex) * ex
    er = unit(g_perp, name="gravity component perpendicular to support axis")
    eaz = unit(np.cross(ex, er), name="torus azimuth")
    return UpperGeometry(A, B, ex, d, center, float(a_a), float(a_b), h, er, eaz)


def torus_point(
    geometry: UpperGeometry,
    lower_length: float,
    phi: float,
    theta: float,
) -> tuple[Array, Array]:
    """Return ideal junction and bob positions for fast angle ``phi`` and slow angle ``theta``."""

    er = np.cos(theta) * geometry.radial_down + np.sin(theta) * geometry.azimuth
    junction = geometry.center + geometry.h * er
    lower_direction = np.sin(phi) * geometry.axis + np.cos(phi) * er
    bob = junction + lower_length * lower_direction
    return junction, bob


def torus_velocity(
    geometry: UpperGeometry,
    lower_length: float,
    phi: float,
    theta: float,
    phi_dot: float,
    theta_dot: float,
) -> tuple[Array, Array]:
    er = np.cos(theta) * geometry.radial_down + np.sin(theta) * geometry.azimuth
    etheta = -np.sin(theta) * geometry.radial_down + np.cos(theta) * geometry.azimuth
    junction_v = geometry.h * theta_dot * etheta
    lower_v = lower_length * (
        phi_dot * (np.cos(phi) * geometry.axis - np.sin(phi) * er)
        + np.cos(phi) * theta_dot * etheta
    )
    return junction_v, junction_v + lower_v


def reduced_geometry_from_loaded_state(
    support_a: Array, support_b: Array, junction: Array, gravity: Array
) -> UpperGeometry:
    A = np.asarray(support_a, dtype=float)
    B = np.asarray(support_b, dtype=float)
    J = np.asarray(junction, dtype=float)
    axis = unit(B - A, name="support axis")
    d = float(np.linalg.norm(B - A))
    a_a = float(np.dot(J - A, axis))
    center = A + a_a * axis
    radial = J - center
    h = float(np.linalg.norm(radial))
    if h <= 1e-14:
        # Use gravity to define the limiting radial direction.
        radial = gravity - np.dot(gravity, axis) * axis
    er = unit(radial, name="loaded junction radial direction")
    eaz = unit(np.cross(axis, er), name="loaded torus azimuth")
    return UpperGeometry(A, B, axis, d, center, a_a, d - a_a, h, er, eaz)

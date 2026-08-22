"""Local Newton model for discrete bending rods and a finite rigid bob.

This backend is intentionally not assembled from the FWD-CABLE weak form.
Each cable is represented by material beads joined by a registered passive
unilateral/bilateral Kelvin-Voigt blend and three-point bending interactions.
The bob has finite radius,
rotational inertia and an eccentric material attachment point.  Those local
degrees of freedom do not exist in the frozen forward model and therefore
provide an independent comparison path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from scipy import sparse

from ypendulum.config.models import SimulationConfig
from ypendulum.config.units import as_vector3, to_si
from ypendulum.geometry.supports import SupportMotion

BRANCH_NAMES = ("upper_A", "upper_B", "lower")


@dataclass(frozen=True)
class RodBranch:
    name: str
    bead_indices: np.ndarray
    segment_rest_length: np.ndarray
    bead_mass: float
    cell_length: float
    ea: float
    eta_a: float
    ei: float
    diameter: float
    drag_cd_normal: float
    drag_cd_tangent: float
    drag_linear_normal_per_length: float
    drag_linear_tangent_per_length: float
    drag_enabled: bool
    start_kind: Literal["support_A", "support_B", "junction"]
    end_kind: Literal["junction", "bob_attachment"]


@dataclass(frozen=True)
class MaterialSocketRegistration:
    side: Literal["start", "end"]
    socket_length: float
    total_length: float
    cut_left_index: int
    cut_right_index: int
    cut_fraction: float
    active_node_indices: np.ndarray
    breakpoints: np.ndarray
    breakpoint_left_indices: np.ndarray
    breakpoint_right_indices: np.ndarray
    breakpoint_fractions: np.ndarray


@dataclass(frozen=True)
class SameBranchContactRegistration:
    full_pairs: np.ndarray
    partial_pairs: tuple[tuple[int, int, float, float, float, float], ...]
    minimum_material_separation: float


@dataclass(frozen=True)
class JunctionContactRegistration:
    first_name: str
    second_name: str
    first_socket: MaterialSocketRegistration
    second_socket: MaterialSocketRegistration
    required_center_separation: float
    registered_projective_opening_squared: float


@dataclass
class HighFidelityEvaluation:
    particle_force: np.ndarray
    bob_force: np.ndarray
    bob_torque: np.ndarray
    support_force: dict[str, np.ndarray]
    branch_positions: dict[str, np.ndarray]
    branch_velocities: dict[str, np.ndarray]
    branch_axial_force: dict[str, np.ndarray]
    branch_tension: dict[str, np.ndarray]
    axial_energy: float
    bending_energy: float
    axial_dissipation_rate: float
    aero_dissipation_rate: float
    air_work_rate: float
    support_work_rate: float
    minimum_segment_length: float
    minimum_bending_turn_clearance: float
    minimum_aerodynamic_chord_length: float
    bob_contact_margin: float
    bob_socket_material_extent: float
    bob_socket_radial_monotonicity: float
    bob_socket_cut_clearance: float
    rod_self_contact_margin: float
    junction_socket_material_extent: float
    junction_socket_projective_opening: float
    junction_socket_cut_clearance: float
    contact_margin: float


def quaternion_multiply(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Hamilton product for scalar-first quaternions."""

    w1, x1, y1, z1 = np.asarray(left, dtype=float)
    w2, x2, y2, z2 = np.asarray(right, dtype=float)
    return np.array(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ],
        dtype=float,
    )


def normalize_quaternion(quaternion: np.ndarray) -> np.ndarray:
    q = np.asarray(quaternion, dtype=float)
    norm = float(np.linalg.norm(q))
    if not np.isfinite(norm) or norm <= 1.0e-14:
        raise FloatingPointError("Rigid-bob quaternion lost a finite non-zero norm.")
    return q / norm


def rotate_body_vector(quaternion: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """Rotate one body-frame vector into the world frame."""

    q = normalize_quaternion(quaternion)
    v = np.asarray(vector, dtype=float)
    qv = q[1:]
    return v + 2.0 * np.cross(qv, np.cross(qv, v) + q[0] * v)


def _point_segment_distance(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    segment = end - start
    norm2 = float(np.dot(segment, segment))
    if norm2 <= 1.0e-30:
        return float(np.linalg.norm(point - start))
    alpha = float(np.dot(point - start, segment) / norm2)
    alpha = min(max(alpha, 0.0), 1.0)
    return float(np.linalg.norm(point - (start + alpha * segment)))


def _batched_point_segment_distance(
    point: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
) -> np.ndarray:
    """Vectorized counterpart of :func:`_point_segment_distance`."""

    points, starts, ends = np.broadcast_arrays(
        np.asarray(point, dtype=float),
        np.asarray(start, dtype=float),
        np.asarray(end, dtype=float),
    )
    segment = ends - starts
    norm2 = np.einsum("...i,...i->...", segment, segment)
    numerator = np.einsum("...i,...i->...", points - starts, segment)
    alpha = np.zeros_like(norm2)
    np.divide(numerator, norm2, out=alpha, where=norm2 > 1.0e-30)
    alpha = np.clip(alpha, 0.0, 1.0)
    projected = starts + alpha[..., None] * segment
    distance = np.linalg.norm(points - projected, axis=-1)
    degenerate = norm2 <= 1.0e-30
    if np.any(degenerate):
        distance = np.where(
            degenerate,
            np.linalg.norm(points - starts, axis=-1),
            distance,
        )
    return np.asarray(distance, dtype=float)


def _segment_segment_distance(
    first_start: np.ndarray,
    first_end: np.ndarray,
    second_start: np.ndarray,
    second_end: np.ndarray,
) -> float:
    """Shortest distance between two closed 3-D line segments."""

    p0 = np.asarray(first_start, dtype=float)
    p1 = np.asarray(first_end, dtype=float)
    q0 = np.asarray(second_start, dtype=float)
    q1 = np.asarray(second_end, dtype=float)
    u = p1 - p0
    v = q1 - q0
    w = p0 - q0
    a = float(np.dot(u, u))
    c = float(np.dot(v, v))
    tiny = np.finfo(float).tiny
    if a <= tiny and c <= tiny:
        return float(np.linalg.norm(p0 - q0))
    if a <= tiny:
        return _point_segment_distance(p0, q0, q1)
    if c <= tiny:
        return _point_segment_distance(q0, p0, p1)

    # The four endpoint-to-closed-segment candidates make the calculation
    # exactly symmetric in its arguments and cover every boundary optimum,
    # including collinear parallel overlap.  A non-parallel pair can also have
    # one interior/interior closest point, which is added explicitly below.
    candidates = [
        _point_segment_distance(p0, q0, q1),
        _point_segment_distance(p1, q0, q1),
        _point_segment_distance(q0, p0, p1),
        _point_segment_distance(q1, p0, p1),
    ]
    normal = np.cross(u, v)
    cross_denominator = float(np.dot(normal, normal))
    if cross_denominator > 0.0:
        # Cross-product parameters avoid the catastrophic cancellation in
        # ``a*c-b*b`` for analytically resolvable, nearly parallel crossings.
        offset = q0 - p0
        s = float(np.dot(np.cross(offset, v), normal) / cross_denominator)
        t = float(np.dot(np.cross(offset, u), normal) / cross_denominator)
        parameter_tolerance = 64.0 * np.finfo(float).eps
        if (
            -parameter_tolerance <= s <= 1.0 + parameter_tolerance
            and -parameter_tolerance <= t <= 1.0 + parameter_tolerance
        ):
            s = min(max(s, 0.0), 1.0)
            t = min(max(t, 0.0), 1.0)
            candidates.append(float(np.linalg.norm(w + s * u - t * v)))
    return float(min(candidates))


def _batched_segment_segment_distance(
    first_start: np.ndarray,
    first_end: np.ndarray,
    second_start: np.ndarray,
    second_end: np.ndarray,
) -> np.ndarray:
    """Vectorized symmetric closed-segment distance for independent pairs."""

    p0, p1, q0, q1 = np.broadcast_arrays(
        np.asarray(first_start, dtype=float),
        np.asarray(first_end, dtype=float),
        np.asarray(second_start, dtype=float),
        np.asarray(second_end, dtype=float),
    )
    u = p1 - p0
    v = q1 - q0
    w = p0 - q0
    candidates = np.stack(
        [
            _batched_point_segment_distance(p0, q0, q1),
            _batched_point_segment_distance(p1, q0, q1),
            _batched_point_segment_distance(q0, p0, p1),
            _batched_point_segment_distance(q1, p0, p1),
        ],
        axis=-1,
    )
    normal = np.cross(u, v)
    denominator = np.einsum("...i,...i->...", normal, normal)
    offset = q0 - p0
    s = np.zeros_like(denominator)
    t = np.zeros_like(denominator)
    np.divide(
        np.einsum("...i,...i->...", np.cross(offset, v), normal),
        denominator,
        out=s,
        where=denominator > 0.0,
    )
    np.divide(
        np.einsum("...i,...i->...", np.cross(offset, u), normal),
        denominator,
        out=t,
        where=denominator > 0.0,
    )
    parameter_tolerance = 64.0 * np.finfo(float).eps
    interior = (
        (denominator > 0.0)
        & (s >= -parameter_tolerance)
        & (s <= 1.0 + parameter_tolerance)
        & (t >= -parameter_tolerance)
        & (t <= 1.0 + parameter_tolerance)
    )
    s = np.clip(s, 0.0, 1.0)
    t = np.clip(t, 0.0, 1.0)
    interior_distance = np.linalg.norm(
        w + s[..., None] * u - t[..., None] * v,
        axis=-1,
    )
    interior_distance = np.where(interior, interior_distance, np.inf)
    return np.minimum(np.min(candidates, axis=-1), interior_distance)


def _minimum_cartesian_segment_distance(
    first_segments: np.ndarray,
    second_segments: np.ndarray,
) -> float:
    """Minimum distance over the Cartesian product of two segment arrays."""

    first = np.asarray(first_segments, dtype=float)
    second = np.asarray(second_segments, dtype=float)
    if first.size == 0 or second.size == 0:
        return float("inf")
    if first.ndim != 3 or first.shape[1:] != (2, 3):
        raise ValueError("first_segments must have shape (n,2,3).")
    if second.ndim != 3 or second.shape[1:] != (2, 3):
        raise ValueError("second_segments must have shape (n,2,3).")
    first_index = np.repeat(np.arange(first.shape[0]), second.shape[0])
    second_index = np.tile(np.arange(second.shape[0]), first.shape[0])
    distances = _batched_segment_segment_distance(
        first[first_index, 0],
        first[first_index, 1],
        second[second_index, 0],
        second[second_index, 1],
    )
    return float(np.min(distances))


def _passive_axial_kelvin_voigt_response(
    extension: np.ndarray,
    extension_rate: np.ndarray,
    stiffness: np.ndarray,
    viscosity: np.ndarray,
    compression_regularization_scale: float,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Return signed force, tensile part, stored energy and passive loss rate."""

    x = np.asarray(extension, dtype=float)
    rate = np.asarray(extension_rate, dtype=float)
    k = np.asarray(stiffness, dtype=float)
    c = np.asarray(viscosity, dtype=float)
    alpha = float(compression_regularization_scale)
    if not (x.shape == rate.shape == k.shape == c.shape):
        raise ValueError("Axial constitutive arrays must have identical shapes.")
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("compression_regularization_scale must lie in [0,1].")
    if (
        not np.all(np.isfinite(x))
        or not np.all(np.isfinite(rate))
        or not np.all(np.isfinite(k))
        or not np.all(np.isfinite(c))
        or np.any(k <= 0.0)
        or np.any(c < 0.0)
    ):
        raise ValueError("Axial Kelvin-Voigt inputs must be finite and passive.")

    bilateral_force = k * x + c * rate
    unilateral_active = (x > 0.0) & (bilateral_force > 0.0)
    unilateral_force = np.where(unilateral_active, bilateral_force, 0.0)
    signed_force = (1.0 - alpha) * unilateral_force + alpha * bilateral_force

    unilateral_energy = 0.5 * float(np.sum(k * np.maximum(x, 0.0) ** 2))
    bilateral_energy = 0.5 * float(np.sum(k * x**2))
    stored_energy = (1.0 - alpha) * unilateral_energy + alpha * bilateral_energy

    unilateral_dissipation = float(
        np.sum(c[unilateral_active] * rate[unilateral_active] ** 2)
    )
    release = (x > 0.0) & ~unilateral_active & (rate < 0.0)
    unilateral_dissipation += float(np.sum(-k[release] * x[release] * rate[release]))
    bilateral_dissipation = float(np.sum(c * rate**2))
    dissipation = (
        (1.0 - alpha) * unilateral_dissipation
        + alpha * bilateral_dissipation
    )
    return (
        signed_force,
        np.maximum(signed_force, 0.0),
        float(stored_energy),
        float(dissipation),
    )


def _materially_separated_segment_distance(
    first_start: np.ndarray,
    first_end: np.ndarray,
    second_start: np.ndarray,
    second_end: np.ndarray,
    *,
    first_material_start: float,
    first_material_end: float,
    second_material_start: float,
    second_material_end: float,
    minimum_material_separation: float,
) -> float:
    """Closest spatial distance outside a fixed same-rod material neighbourhood."""

    ds = float(first_material_end - first_material_start)
    dt = float(second_material_end - second_material_start)
    offset = float(
        minimum_material_separation
        - (second_material_start - first_material_start)
    )

    polygon = [
        np.array([0.0, 0.0]),
        np.array([1.0, 0.0]),
        np.array([1.0, 1.0]),
        np.array([0.0, 1.0]),
    ]

    def feasible_value(parameter: np.ndarray) -> float:
        xi, eta = parameter
        return eta * dt - xi * ds - offset

    clipped: list[np.ndarray] = []
    tolerance = 128.0 * np.finfo(float).eps * max(ds, dt, abs(offset), 1.0e-300)
    for current, following in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        current_value = feasible_value(current)
        following_value = feasible_value(following)
        current_inside = current_value >= -tolerance
        following_inside = following_value >= -tolerance
        if current_inside:
            clipped.append(current)
        if current_inside != following_inside:
            fraction = current_value / (current_value - following_value)
            clipped.append(current + fraction * (following - current))
    if not clipped:
        return float("inf")

    p0 = np.asarray(first_start, dtype=float)
    q0 = np.asarray(second_start, dtype=float)
    u = np.asarray(first_end, dtype=float) - p0
    v = np.asarray(second_end, dtype=float) - q0

    def spatial_delta(parameter: np.ndarray) -> np.ndarray:
        return p0 + parameter[0] * u - q0 - parameter[1] * v

    candidates = [float(np.linalg.norm(spatial_delta(vertex))) for vertex in clipped]
    for current, following in zip(clipped, clipped[1:] + clipped[:1], strict=True):
        parameter_delta = following - current
        spatial_start = spatial_delta(current)
        spatial_direction = (
            parameter_delta[0] * u - parameter_delta[1] * v
        )
        denominator = float(np.dot(spatial_direction, spatial_direction))
        if denominator > 0.0:
            fraction = float(
                np.clip(
                    -np.dot(spatial_start, spatial_direction) / denominator,
                    0.0,
                    1.0,
                )
            )
            candidates.append(
                float(np.linalg.norm(spatial_start + fraction * spatial_direction))
            )

    normal = np.cross(u, v)
    cross_denominator = float(np.dot(normal, normal))
    if cross_denominator > 0.0:
        spatial_offset = q0 - p0
        xi = float(np.dot(np.cross(spatial_offset, v), normal) / cross_denominator)
        eta = float(np.dot(np.cross(spatial_offset, u), normal) / cross_denominator)
        interior = np.array([xi, eta])
        if (
            -tolerance <= xi <= 1.0 + tolerance
            and -tolerance <= eta <= 1.0 + tolerance
            and feasible_value(interior) >= -tolerance
        ):
            candidates.append(float(np.linalg.norm(spatial_delta(interior))))
    return float(min(candidates))


def _material_position_from_joint(
    points: np.ndarray,
    segment_rest_length: np.ndarray,
    side: Literal["start", "end"],
    material_distance: float,
) -> np.ndarray:
    coordinates = np.asarray(points, dtype=float)
    rest = np.asarray(segment_rest_length, dtype=float)
    if side == "end":
        coordinates = coordinates[::-1]
        rest = rest[::-1]
    distance = float(np.clip(material_distance, 0.0, np.sum(rest)))
    cumulative = np.concatenate([[0.0], np.cumsum(rest)])
    segment_index = min(int(np.searchsorted(cumulative, distance, side="right") - 1), rest.size - 1)
    fraction = (distance - cumulative[segment_index]) / rest[segment_index]
    return (
        (1.0 - fraction) * coordinates[segment_index]
        + fraction * coordinates[segment_index + 1]
    )


def _material_segments_outside_joint_socket(
    points: np.ndarray,
    segment_rest_length: np.ndarray,
    side: Literal["start", "end"],
    socket_length: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    coordinates = np.asarray(points, dtype=float)
    rest = np.asarray(segment_rest_length, dtype=float)
    reverse = side == "end"
    if reverse:
        coordinates = coordinates[::-1]
        rest = rest[::-1]
    total = float(np.sum(rest))
    if not 0.0 <= socket_length < total:
        return []
    cumulative = np.concatenate([[0.0], np.cumsum(rest)])
    index = min(int(np.searchsorted(cumulative, socket_length, side="right") - 1), rest.size - 1)
    fraction = (socket_length - cumulative[index]) / rest[index]
    cut = (1.0 - fraction) * coordinates[index] + fraction * coordinates[index + 1]
    active_points = np.vstack([cut, coordinates[index + 1 :]])
    segments = [
        (active_points[item], active_points[item + 1])
        for item in range(active_points.shape[0] - 1)
        if np.linalg.norm(active_points[item + 1] - active_points[item]) > 0.0
    ]
    if reverse:
        segments = [(end, start) for start, end in segments[::-1]]
    return segments


def _socket_material_breakpoints(
    segment_rest_length: np.ndarray,
    side: Literal["start", "end"],
    socket_length: float,
) -> np.ndarray:
    rest = np.asarray(segment_rest_length, dtype=float)
    if side == "end":
        rest = rest[::-1]
    cumulative = np.concatenate([[0.0], np.cumsum(rest)])
    internal = cumulative[(cumulative > 0.0) & (cumulative < socket_length)]
    return np.concatenate([[0.0], internal, [socket_length]])


def _material_point_registration(
    segment_rest_length: np.ndarray,
    side: Literal["start", "end"],
    material_distance: float,
) -> tuple[int, int, float]:
    rest = np.asarray(segment_rest_length, dtype=float)
    oriented_rest = rest[::-1] if side == "end" else rest
    cumulative = np.concatenate([[0.0], np.cumsum(oriented_rest)])
    distance = float(np.clip(material_distance, 0.0, cumulative[-1]))
    index = min(
        int(np.searchsorted(cumulative, distance, side="right") - 1),
        oriented_rest.size - 1,
    )
    fraction = float(
        (distance - cumulative[index]) / oriented_rest[index]
    )
    if side == "start":
        return index, index + 1, fraction
    point_count = rest.size + 1
    return point_count - 1 - index, point_count - 2 - index, fraction


def _register_material_socket(
    segment_rest_length: np.ndarray,
    side: Literal["start", "end"],
    socket_length: float,
) -> MaterialSocketRegistration:
    rest = np.asarray(segment_rest_length, dtype=float)
    total = float(np.sum(rest))
    left, right, fraction = _material_point_registration(
        rest, side, socket_length
    )
    oriented_rest = rest[::-1] if side == "end" else rest
    cumulative = np.concatenate([[0.0], np.cumsum(oriented_rest)])
    oriented_index = min(
        int(np.searchsorted(cumulative, socket_length, side="right") - 1),
        oriented_rest.size - 1,
    )
    if side == "start":
        active_nodes = np.arange(oriented_index + 1, rest.size + 1, dtype=np.int64)
    else:
        active_nodes = np.arange(
            rest.size - 1 - oriented_index,
            -1,
            -1,
            dtype=np.int64,
        )
    breakpoints = _socket_material_breakpoints(rest, side, socket_length)
    point_map = [
        _material_point_registration(rest, side, float(distance))
        for distance in breakpoints
    ]
    return MaterialSocketRegistration(
        side=side,
        socket_length=float(socket_length),
        total_length=total,
        cut_left_index=left,
        cut_right_index=right,
        cut_fraction=fraction,
        active_node_indices=active_nodes,
        breakpoints=breakpoints,
        breakpoint_left_indices=np.asarray(
            [item[0] for item in point_map], dtype=np.int64
        ),
        breakpoint_right_indices=np.asarray(
            [item[1] for item in point_map], dtype=np.int64
        ),
        breakpoint_fractions=np.asarray([item[2] for item in point_map], dtype=float),
    )


def _registered_material_points(
    points: np.ndarray,
    registration: MaterialSocketRegistration,
) -> np.ndarray:
    fractions = registration.breakpoint_fractions[:, None]
    return (
        (1.0 - fractions) * points[registration.breakpoint_left_indices]
        + fractions * points[registration.breakpoint_right_indices]
    )


def _registered_socket_cut(
    points: np.ndarray,
    registration: MaterialSocketRegistration,
) -> np.ndarray:
    return (
        (1.0 - registration.cut_fraction) * points[registration.cut_left_index]
        + registration.cut_fraction * points[registration.cut_right_index]
    )


def _registered_active_segments(
    points: np.ndarray,
    registration: MaterialSocketRegistration,
) -> np.ndarray:
    if registration.socket_length >= registration.total_length:
        return np.empty((0, 2, 3), dtype=float)
    active_points = np.vstack(
        [
            _registered_socket_cut(points, registration),
            points[registration.active_node_indices],
        ]
    )
    if active_points.shape[0] < 2:
        return np.empty((0, 2, 3), dtype=float)
    length = np.linalg.norm(active_points[1:] - active_points[:-1], axis=1)
    keep = length > 0.0
    return np.stack(
        [active_points[:-1][keep], active_points[1:][keep]], axis=1
    )


def _registered_projective_opening_squared(
    first_points: np.ndarray,
    first_registration: MaterialSocketRegistration,
    second_points: np.ndarray,
    second_registration: MaterialSocketRegistration,
) -> float:
    first_registered = _registered_material_points(
        first_points, first_registration
    )
    second_registered = _registered_material_points(
        second_points, second_registration
    )
    minimum = float("inf")
    for first_index in range(first_registered.shape[0] - 1):
        for second_index in range(second_registered.shape[0] - 1):
            minimum = min(
                minimum,
                _minimum_projective_opening_squared_on_material_cell(
                    first_registered[first_index],
                    first_registered[first_index + 1],
                    second_registered[second_index],
                    second_registered[second_index + 1],
                    first_material_start=float(
                        first_registration.breakpoints[first_index]
                    ),
                    first_material_end=float(
                        first_registration.breakpoints[first_index + 1]
                    ),
                    second_material_start=float(
                        second_registration.breakpoints[second_index]
                    ),
                    second_material_end=float(
                        second_registration.breakpoints[second_index + 1]
                    ),
                ),
            )
    return float(minimum)


def _minimum_projective_opening_squared_on_material_cell(
    first_start: np.ndarray,
    first_end: np.ndarray,
    second_start: np.ndarray,
    second_end: np.ndarray,
    *,
    first_material_start: float,
    first_material_end: float,
    second_material_start: float,
    second_material_end: float,
) -> float:
    """Minimise ``|p(s)-q(t)|^2/(s+t)^2`` on one material cell.

    The projective coordinates ``u=1/(s+t)`` and ``x=s/(s+t)`` turn both the
    objective and the image of the material rectangle into a convex quadratic
    over a convex polygon.  The cell touching ``(s,t)=(0,0)`` is handled by
    its finite projective closure, so two healthy rays sharing exactly the
    junction are not rejected merely because their Euclidean distance tends
    to zero there.
    """

    s0 = float(first_material_start)
    s1 = float(first_material_end)
    t0 = float(second_material_start)
    t1 = float(second_material_end)
    if not (0.0 <= s0 < s1 and 0.0 <= t0 < t1):
        raise ValueError("Projective material cells must have positive extent.")

    p0 = np.asarray(first_start, dtype=float)
    p1 = np.asarray(first_end, dtype=float)
    q0 = np.asarray(second_start, dtype=float)
    q1 = np.asarray(second_end, dtype=float)
    first_slope = (p1 - p0) / (s1 - s0)
    second_slope = (q1 - q0) / (t1 - t0)
    # Cancel the common world-coordinate origin before the material affine
    # terms are applied; this preserves the guard numerically under large
    # rigid translations as well as algebraically.
    affine_offset = (
        (p0 - q0)
        - first_slope * s0
        + second_slope * t0
    )
    first_coefficient = first_slope
    second_coefficient = -second_slope

    if s0 == 0.0 and t0 == 0.0:
        # Both material traces start at the same registered junction.  In the
        # projective closure x=s/(s+t), the ratio is the squared norm of one
        # affine vector on x in [0,1].
        endpoint_scale = max(
            float(np.linalg.norm(p1 - p0)),
            float(np.linalg.norm(q1 - q0)),
            s1,
            t1,
            np.finfo(float).tiny,
        )
        if float(np.linalg.norm(p0 - q0)) > (
            256.0 * np.finfo(float).eps * endpoint_scale
        ):
            return 0.0
        direction = first_coefficient - second_coefficient
        denominator = float(np.dot(direction, direction))
        fraction = 0.0
        if denominator > 0.0:
            fraction = float(
                np.clip(
                    -np.dot(second_coefficient, direction) / denominator,
                    0.0,
                    1.0,
                )
            )
        vector = second_coefficient + fraction * direction
        return max(float(np.dot(vector, vector)), 0.0)

    # z/(s+t) = a*u + c + (b-c)*x, with u=1/(s+t).
    matrix = np.column_stack(
        [affine_offset, first_coefficient - second_coefficient]
    )
    constant = second_coefficient
    material_corners = (
        (s0, t0),
        (s1, t0),
        (s1, t1),
        (s0, t1),
    )
    polygon = [
        np.array([1.0 / (s + t), s / (s + t)], dtype=float)
        for s, t in material_corners
    ]

    def squared_value(parameter: np.ndarray) -> float:
        vector = constant + matrix @ parameter
        return float(np.dot(vector, vector))

    def feasible(parameter: np.ndarray) -> bool:
        u, x = (float(parameter[0]), float(parameter[1]))
        tolerance = 256.0 * np.finfo(float).eps * max(
            abs(x),
            abs(s0 * u),
            abs(s1 * u),
            abs(1.0 - x),
            abs(t0 * u),
            abs(t1 * u),
            np.finfo(float).tiny,
        )
        return (
            u > 0.0
            and s0 * u - tolerance <= x <= s1 * u + tolerance
            and t0 * u - tolerance <= 1.0 - x <= t1 * u + tolerance
        )

    candidates = [squared_value(vertex) for vertex in polygon]
    for current, following in zip(
        polygon, polygon[1:] + polygon[:1], strict=True
    ):
        parameter_direction = following - current
        spatial_start = constant + matrix @ current
        spatial_direction = matrix @ parameter_direction
        denominator = float(np.dot(spatial_direction, spatial_direction))
        fraction = 0.0
        if denominator > 0.0:
            fraction = float(
                np.clip(
                    -np.dot(spatial_start, spatial_direction) / denominator,
                    0.0,
                    1.0,
                )
            )
        candidates.append(
            squared_value(current + fraction * parameter_direction)
        )

    stationary = -np.linalg.lstsq(matrix, constant, rcond=None)[0]
    if feasible(stationary):
        candidates.append(squared_value(stationary))
    return max(float(min(candidates)), 0.0)


def _junction_socket_projective_opening_squared(
    first_points: np.ndarray,
    first_rest_length: np.ndarray,
    first_side: Literal["start", "end"],
    second_points: np.ndarray,
    second_rest_length: np.ndarray,
    second_side: Literal["start", "end"],
    socket_length: float,
) -> float:
    """Return the mesh-objective projective opening of two junction traces."""

    first_breakpoints = _socket_material_breakpoints(
        first_rest_length, first_side, socket_length
    )
    second_breakpoints = _socket_material_breakpoints(
        second_rest_length, second_side, socket_length
    )
    minimum = float("inf")
    for first_left, first_right in zip(
        first_breakpoints[:-1], first_breakpoints[1:], strict=True
    ):
        first_start = _material_position_from_joint(
            first_points,
            first_rest_length,
            first_side,
            float(first_left),
        )
        first_end = _material_position_from_joint(
            first_points,
            first_rest_length,
            first_side,
            float(first_right),
        )
        for second_left, second_right in zip(
            second_breakpoints[:-1], second_breakpoints[1:], strict=True
        ):
            second_start = _material_position_from_joint(
                second_points,
                second_rest_length,
                second_side,
                float(second_left),
            )
            second_end = _material_position_from_joint(
                second_points,
                second_rest_length,
                second_side,
                float(second_right),
            )
            minimum = min(
                minimum,
                _minimum_projective_opening_squared_on_material_cell(
                    first_start,
                    first_end,
                    second_start,
                    second_end,
                    first_material_start=float(first_left),
                    first_material_end=float(first_right),
                    second_material_start=float(second_left),
                    second_material_end=float(second_right),
                ),
            )
    return float(minimum)


def discrete_bending_energy_forces(
    points: np.ndarray,
    segment_rest_length: np.ndarray,
    bending_stiffness: float,
) -> tuple[float, np.ndarray]:
    """Return three-point rod bending energy and its conservative nodal force.

    The local interaction is intentionally expressed directly in bead
    coordinates rather than through the forward cable weak form.  For
    consecutive unit tangents ``t_-`` and ``t_+`` it uses

    ``U_i = 0.5 * EI / lbar * ||t_+ - t_-||^2``.

    The returned force is exactly ``-dU/dx``.  Keeping this operation as a
    small pure function makes the decisive HF-only interaction independently
    differentiable and testable.
    """

    coordinates = np.asarray(points, dtype=float)
    rest = np.asarray(segment_rest_length, dtype=float)
    if coordinates.ndim != 2 or coordinates.shape[1] != 3:
        raise ValueError("Discrete-rod points must have shape (n, 3).")
    if coordinates.shape[0] < 3:
        raise ValueError("A bending interaction requires at least three points.")
    if rest.shape != (coordinates.shape[0] - 1,):
        raise ValueError("segment_rest_length must contain one value per segment.")
    if not np.all(np.isfinite(coordinates)) or not np.all(np.isfinite(rest)):
        raise FloatingPointError("Discrete-rod bending input is non-finite.")
    if np.any(rest <= 0.0) or not np.isfinite(bending_stiffness) or bending_stiffness < 0.0:
        raise ValueError("Bending stiffness must be finite/non-negative and rest lengths positive.")

    segment = coordinates[1:] - coordinates[:-1]
    length = np.linalg.norm(segment, axis=1)
    if np.any(length <= 0.0):
        raise FloatingPointError("Collapsed segment in discrete bending interaction.")
    tangent = segment / length[:, None]
    force = np.zeros_like(coordinates)
    energy = 0.0
    identity = np.eye(3)
    for center in range(1, coordinates.shape[0] - 1):
        left_tangent = tangent[center - 1]
        right_tangent = tangent[center]
        delta_tangent = right_tangent - left_tangent
        dual_length = 0.5 * (rest[center - 1] + rest[center])
        coefficient = bending_stiffness / dual_length
        energy += 0.5 * coefficient * float(np.dot(delta_tangent, delta_tangent))

        # Gradients with respect to the two segment vectors.  Converting those
        # gradients to nodal forces preserves equal-and-opposite resultants.
        grad_left_segment = (
            -coefficient
            * ((identity - np.outer(left_tangent, left_tangent)) @ delta_tangent)
            / length[center - 1]
        )
        grad_right_segment = (
            coefficient
            * ((identity - np.outer(right_tangent, right_tangent)) @ delta_tangent)
            / length[center]
        )
        force[center - 1] += grad_left_segment
        force[center] += -grad_left_segment + grad_right_segment
        force[center + 1] += -grad_right_segment
    return float(energy), force


class HighFidelityModel:
    """Independent local discrete-rod / finite-rigid-bob Newton model."""

    model_id = "HF-DISCRETE-ROD-RIGID-BOB-1.0"

    def __init__(self, cfg: SimulationConfig):
        if cfg.run.mode != "high_fidelity":
            raise ValueError("HighFidelityModel requires run.mode='high_fidelity'.")
        self.cfg = cfg
        self.gravity = as_vector3(cfg.environment.gravity, default_unit="m/s^2")
        gravity_norm = float(np.linalg.norm(self.gravity))
        if gravity_norm <= 0.0:
            raise ValueError("The high-fidelity gravitational pendulum requires non-zero gravity.")
        self.gravity_direction = self.gravity / gravity_norm
        self.air_density = float(to_si(cfg.environment.air_density, default_unit="kg/m^3"))
        self.air_velocity = as_vector3(cfg.environment.air_velocity, default_unit="m/s")
        self.support_motion = {
            "support_A": SupportMotion.from_config(
                cfg.supports.A,
                base_directory=None if cfg.source_path is None else cfg.source_path.parent,
            ),
            "support_B": SupportMotion.from_config(
                cfg.supports.B,
                base_directory=None if cfg.source_path is None else cfg.source_path.parent,
            ),
        }
        self.junction_mass = float(to_si(cfg.junction.mass, default_unit="kg"))
        self.junction_drag_linear = float(
            to_si(cfg.junction.drag_linear, default_unit="N*s/m")
        )
        self.bob_mass = float(to_si(cfg.bob.mass, default_unit="kg"))
        self.bob_radius = float(to_si(cfg.bob.radius, default_unit="m"))
        self.bob_cd = float(to_si(cfg.bob.drag.cd, default_unit="dimensionless"))
        self.bob_linear_drag = float(
            to_si(cfg.bob.drag.linear_coefficient, default_unit="N*s/m")
        )
        if cfg.bob.drag.model == "linear":
            self.bob_cd = 0.0
        elif cfg.bob.drag.model == "quadratic":
            self.bob_linear_drag = 0.0
        attachment_radius = (
            cfg.high_fidelity.bob_attachment_radius_fraction * self.bob_radius
        )
        self.bob_contact_radius = (
            cfg.high_fidelity.bob_contact_radius_fraction * self.bob_radius
        )
        # The body frame is initially aligned with the world frame.  The
        # attachment is on the surface opposite gravity (the top of the bob).
        self.attachment_body = -self.gravity_direction * attachment_radius
        self.bob_inertia = (
            cfg.high_fidelity.bob_inertia_factor
            * self.bob_mass
            * self.bob_radius**2
        )
        self.quaternion_stabilization_rate = (
            float(
                to_si(
                    cfg.high_fidelity.quaternion_stabilization_rate,
                    default_unit="1/s",
                )
            )
        )
        self.compression_regularization_scale = float(
            cfg.high_fidelity.compression_regularization_scale
        )
        self.minimum_clearance = float(
            to_si(cfg.high_fidelity.minimum_clearance, default_unit="m")
        )
        self.contact_guard_enabled = cfg.high_fidelity.contact_guard_enabled
        self.bob_buoyancy = (
            -self.air_density
            * (4.0 * np.pi * self.bob_radius**3 / 3.0)
            * self.gravity
            if cfg.bob.buoyancy
            else np.zeros(3, dtype=float)
        )

        support_a, _, _ = self.support_motion["support_A"].state(0.0)
        support_b, _, _ = self.support_motion["support_B"].state(0.0)
        junction_guess, bob_guess = self._initial_body_geometry(support_a, support_b)

        particle_positions: list[np.ndarray] = []
        particle_labels: list[str] = []
        particle_masses: list[float] = []
        branches: dict[str, RodBranch] = {}
        for name, start, end, start_kind, end_kind in (
            (
                "upper_A",
                support_a,
                junction_guess,
                "support_A",
                "junction",
            ),
            (
                "upper_B",
                support_b,
                junction_guess,
                "support_B",
                "junction",
            ),
            (
                "lower",
                junction_guess,
                bob_guess + self.attachment_body,
                "junction",
                "bob_attachment",
            ),
        ):
            cable = getattr(cfg.cables, name)
            bead_count = int(cable.elements)
            length = float(to_si(cable.rest_length, default_unit="m"))
            diameter = float(to_si(cable.diameter, default_unit="m"))
            density = float(to_si(cable.density, default_unit="kg/m^3"))
            young = float(to_si(cable.young_modulus, default_unit="Pa"))
            viscosity = float(to_si(cable.axial_viscosity, default_unit="Pa*s"))
            area = np.pi * diameter**2 / 4.0
            second_moment = np.pi * diameter**4 / 64.0
            indices: list[int] = []
            for bead in range(bead_count):
                alpha = (bead + 0.5) / bead_count
                indices.append(len(particle_positions))
                particle_positions.append((1.0 - alpha) * start + alpha * end)
                particle_labels.append(f"{name}_material_bead_{bead}")
                particle_masses.append(density * area * length / bead_count)
            segment_rest = np.full(bead_count + 1, length / bead_count)
            segment_rest[0] *= 0.5
            segment_rest[-1] *= 0.5
            branches[name] = RodBranch(
                name=name,
                bead_indices=np.asarray(indices, dtype=np.int64),
                segment_rest_length=segment_rest,
                bead_mass=density * area * length / bead_count,
                cell_length=length / bead_count,
                ea=young * area,
                eta_a=viscosity * area,
                ei=(
                    cfg.high_fidelity.bending_stiffness_scale
                    * young
                    * second_moment
                ),
                diameter=diameter,
                drag_cd_normal=float(cable.drag_cd_normal),
                drag_cd_tangent=float(cable.drag_cd_tangent),
                drag_linear_normal_per_length=float(
                    to_si(
                        cable.drag_linear_normal_per_length,
                        default_unit="N*s/m^2",
                    )
                ),
                drag_linear_tangent_per_length=float(
                    to_si(
                        cable.drag_linear_tangent_per_length,
                        default_unit="N*s/m^2",
                    )
                ),
                drag_enabled=bool(cable.drag_enabled),
                start_kind=start_kind,
                end_kind=end_kind,
            )

        self.junction_index = len(particle_positions)
        particle_positions.append(junction_guess.copy())
        particle_labels.append("finite_mass_junction")
        particle_masses.append(self.junction_mass)
        self.reference_particle_positions = np.asarray(particle_positions, dtype=float)
        self.reference_bob_position = bob_guess
        self.particle_labels = tuple(particle_labels)
        self.particle_mass = np.asarray(particle_masses, dtype=float)
        self.branches = branches
        self.particle_count = len(particle_positions)
        self.position_size = 3 * self.particle_count
        self.state_size = 2 * self.position_size + 13
        length_scale = max(
            float(np.linalg.norm(support_b - support_a)),
            *(float(to_si(getattr(cfg.cables, name).rest_length, default_unit="m")) for name in BRANCH_NAMES),
        )
        self.characteristic_length = length_scale
        self.geometry_singularity_floor = max(1.0e-15 * length_scale, 1.0e-16)
        self.length_guard = max(1.0e-12 * length_scale, 1.0e-14)
        if not self.geometry_singularity_floor < self.length_guard:
            raise AssertionError("Geometry singularity floor must lie below the length guard.")
        self.bending_turn_clearance_floor = 1.0e-8
        self.aerodynamic_chord_guard = max(
            1.0e-14 * length_scale, 1.0e-15
        )
        physical_force_scale = (
            self.bob_mass + self.junction_mass + float(np.sum(self.particle_mass))
        ) * gravity_norm
        self.force_scale = max(physical_force_scale, np.finfo(float).tiny)
        self.tension_zero_tolerance = 1024.0 * np.finfo(float).eps * self.force_scale
        self._build_contact_registrations()

    def _build_contact_registrations(self) -> None:
        """Freeze topology, material sockets and static contact pair classes."""

        self.same_branch_contact_registration: dict[
            str, SameBranchContactRegistration
        ] = {}
        for name, branch in self.branches.items():
            material_nodes = np.concatenate(
                [[0.0], np.cumsum(branch.segment_rest_length)]
            )
            neighbourhood = self._same_branch_registration_length(branch)
            full_pairs: list[tuple[int, int]] = []
            partial_pairs: list[
                tuple[int, int, float, float, float, float]
            ] = []
            for first in range(branch.segment_rest_length.size):
                for second in range(first + 1, branch.segment_rest_length.size):
                    first_start = float(material_nodes[first])
                    first_end = float(material_nodes[first + 1])
                    second_start = float(material_nodes[second])
                    second_end = float(material_nodes[second + 1])
                    tolerance = (
                        128.0
                        * np.finfo(float).eps
                        * max(
                            first_end - first_start,
                            second_end - second_start,
                            abs(
                                neighbourhood
                                - (second_start - first_start)
                            ),
                            1.0e-300,
                        )
                    )
                    if second_start - first_end >= neighbourhood - tolerance:
                        full_pairs.append((first, second))
                    elif second_end - first_start >= neighbourhood - tolerance:
                        partial_pairs.append(
                            (
                                first,
                                second,
                                first_start,
                                first_end,
                                second_start,
                                second_end,
                            )
                        )
            self.same_branch_contact_registration[name] = (
                SameBranchContactRegistration(
                    full_pairs=np.asarray(full_pairs, dtype=np.int64).reshape(-1, 2),
                    partial_pairs=tuple(partial_pairs),
                    minimum_material_separation=neighbourhood,
                )
            )

        lower = self.branches["lower"]
        self.bob_socket_registration = _register_material_socket(
            lower.segment_rest_length,
            "end",
            self._bob_socket_length(lower),
        )
        junction_pairs: list[JunctionContactRegistration] = []
        for first_index, first_name in enumerate(BRANCH_NAMES):
            first = self.branches[first_name]
            first_side: Literal["start", "end"] = (
                "start" if first.start_kind == "junction" else "end"
            )
            for second_name in BRANCH_NAMES[first_index + 1 :]:
                second = self.branches[second_name]
                second_side: Literal["start", "end"] = (
                    "start" if second.start_kind == "junction" else "end"
                )
                required = (
                    0.5 * (first.diameter + second.diameter)
                    + self.minimum_clearance
                )
                socket_length = self._junction_socket_length(first, second)
                junction_pairs.append(
                    JunctionContactRegistration(
                        first_name=first_name,
                        second_name=second_name,
                        first_socket=_register_material_socket(
                            first.segment_rest_length,
                            first_side,
                            socket_length,
                        ),
                        second_socket=_register_material_socket(
                            second.segment_rest_length,
                            second_side,
                            socket_length,
                        ),
                        required_center_separation=required,
                        registered_projective_opening_squared=(
                            required / (2.0 * socket_length)
                        )
                        ** 2,
                    )
                )
        self.junction_contact_registration = tuple(junction_pairs)

    def _initial_body_geometry(
        self, support_a: np.ndarray, support_b: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        la = float(to_si(self.cfg.cables.upper_A.rest_length, default_unit="m"))
        lb = float(to_si(self.cfg.cables.upper_B.rest_length, default_unit="m"))
        lower = float(to_si(self.cfg.cables.lower.rest_length, default_unit="m"))
        axis = support_b - support_a
        spacing = float(np.linalg.norm(axis))
        ex = axis / spacing
        scale = max(1.005, 1.005 * spacing / max(la + lb, 1.0e-15))
        loaded_a = scale * la
        loaded_b = scale * lb
        along = (loaded_a**2 - loaded_b**2 + spacing**2) / (2.0 * spacing)
        height = np.sqrt(max(loaded_a**2 - along**2, (1.0e-4 * spacing) ** 2))
        down = self.gravity_direction - np.dot(self.gravity_direction, ex) * ex
        down_norm = float(np.linalg.norm(down))
        if down_norm <= 1.0e-12:
            trial = np.array([0.0, 0.0, 1.0])
            if abs(float(np.dot(trial, ex))) > 0.9:
                trial = np.array([0.0, 1.0, 0.0])
            down = trial - np.dot(trial, ex) * ex
            down_norm = float(np.linalg.norm(down))
        down /= down_norm
        junction = support_a + along * ex + height * down
        bob = junction + self.gravity_direction * (lower + np.linalg.norm(self.attachment_body))
        return junction, bob

    def pack_state(
        self,
        particle_positions: np.ndarray,
        bob_position: np.ndarray,
        quaternion: np.ndarray,
        particle_velocities: np.ndarray,
        bob_velocity: np.ndarray,
        angular_velocity: np.ndarray,
    ) -> np.ndarray:
        return np.concatenate(
            [
                np.asarray(particle_positions, dtype=float).reshape(-1),
                np.asarray(bob_position, dtype=float),
                np.asarray(quaternion, dtype=float),
                np.asarray(particle_velocities, dtype=float).reshape(-1),
                np.asarray(bob_velocity, dtype=float),
                np.asarray(angular_velocity, dtype=float),
            ]
        )

    def unpack_state(
        self, state: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        y = np.asarray(state, dtype=float)
        if y.shape != (self.state_size,):
            raise ValueError(f"Expected HF state shape {(self.state_size,)}, got {y.shape}.")
        n = self.position_size
        particle_positions = y[:n].reshape(self.particle_count, 3)
        bob_position = y[n : n + 3]
        quaternion = y[n + 3 : n + 7]
        offset = n + 7
        particle_velocities = y[offset : offset + n].reshape(self.particle_count, 3)
        bob_velocity = y[offset + n : offset + n + 3]
        angular_velocity = y[offset + n + 3 : offset + n + 6]
        return (
            particle_positions,
            bob_position,
            quaternion,
            particle_velocities,
            bob_velocity,
            angular_velocity,
        )

    def _endpoint_state(
        self,
        kind: str,
        t: float,
        particle_positions: np.ndarray,
        particle_velocities: np.ndarray,
        bob_position: np.ndarray,
        bob_velocity: np.ndarray,
        quaternion: np.ndarray,
        angular_velocity: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        if kind in self.support_motion:
            position, velocity, _ = self.support_motion[kind].state(t)
            return position, velocity, None
        if kind == "junction":
            return (
                particle_positions[self.junction_index],
                particle_velocities[self.junction_index],
                None,
            )
        if kind == "bob_attachment":
            arm = rotate_body_vector(quaternion, self.attachment_body)
            return bob_position + arm, bob_velocity + np.cross(angular_velocity, arm), arm
        raise KeyError(kind)

    @staticmethod
    def _accumulate_local_force(
        kind: str,
        force: np.ndarray,
        *,
        particle_force: np.ndarray,
        junction_index: int,
        bob_force: np.ndarray,
        bob_torque: np.ndarray,
        support_force: dict[str, np.ndarray],
        bob_arm: np.ndarray | None,
    ) -> None:
        if kind in support_force:
            support_force[kind] += force
        elif kind == "junction":
            particle_force[junction_index] += force
        elif kind == "bob_attachment":
            bob_force += force
            assert bob_arm is not None
            bob_torque += np.cross(bob_arm, force)
        else:
            raise KeyError(kind)

    def evaluate(
        self,
        t: float,
        particle_positions: np.ndarray,
        particle_velocities: np.ndarray,
        bob_position: np.ndarray,
        bob_velocity: np.ndarray,
        quaternion: np.ndarray,
        angular_velocity: np.ndarray,
        *,
        include_aero: bool = True,
        compute_contact: bool = True,
    ) -> HighFidelityEvaluation:
        positions = np.asarray(particle_positions, dtype=float)
        velocities = np.asarray(particle_velocities, dtype=float)
        particle_force = self.particle_mass[:, None] * self.gravity[None, :]
        bob_force = self.bob_mass * self.gravity + self.bob_buoyancy
        bob_torque = np.zeros(3, dtype=float)
        support_force = {
            "support_A": np.zeros(3, dtype=float),
            "support_B": np.zeros(3, dtype=float),
        }
        branch_positions: dict[str, np.ndarray] = {}
        branch_velocities: dict[str, np.ndarray] = {}
        branch_axial_force: dict[str, np.ndarray] = {}
        branch_tension: dict[str, np.ndarray] = {}
        axial_energy = 0.0
        bending_energy = 0.0
        axial_dissipation = 0.0
        aero_dissipation = 0.0
        air_work = 0.0
        minimum_segment_length = float("inf")
        minimum_bending_turn_clearance = float("inf")
        minimum_aerodynamic_chord_length = float("inf")

        for branch in self.branches.values():
            start_p, start_v, start_arm = self._endpoint_state(
                branch.start_kind,
                t,
                positions,
                velocities,
                bob_position,
                bob_velocity,
                quaternion,
                angular_velocity,
            )
            end_p, end_v, end_arm = self._endpoint_state(
                branch.end_kind,
                t,
                positions,
                velocities,
                bob_position,
                bob_velocity,
                quaternion,
                angular_velocity,
            )
            points = np.vstack([start_p, positions[branch.bead_indices], end_p])
            point_velocities = np.vstack(
                [start_v, velocities[branch.bead_indices], end_v]
            )
            local_force = np.zeros_like(points)
            segment = points[1:] - points[:-1]
            segment_length = np.linalg.norm(segment, axis=1)
            minimum_segment_length = min(
                minimum_segment_length, float(np.min(segment_length))
            )
            if np.any(segment_length <= self.geometry_singularity_floor):
                raise FloatingPointError(
                    f"{branch.name} contains a collapsed discrete-rod segment."
                )
            tangent = segment / segment_length[:, None]
            turn_clearance = 1.0 + np.einsum(
                "ij,ij->i", tangent[:-1], tangent[1:]
            )
            minimum_bending_turn_clearance = min(
                minimum_bending_turn_clearance,
                float(np.min(turn_clearance)),
            )
            chord_length = np.linalg.norm(points[2:] - points[:-2], axis=1)
            minimum_aerodynamic_chord_length = min(
                minimum_aerodynamic_chord_length,
                float(np.min(chord_length)),
            )
            relative_velocity = point_velocities[1:] - point_velocities[:-1]
            extension_rate = np.einsum("ij,ij->i", relative_velocity, tangent)
            extension = segment_length - branch.segment_rest_length
            stiffness = branch.ea / branch.segment_rest_length
            viscosity = branch.eta_a / branch.segment_rest_length
            (
                axial_force,
                tensile_force,
                branch_axial_energy,
                branch_axial_dissipation,
            ) = _passive_axial_kelvin_voigt_response(
                extension,
                extension_rate,
                stiffness,
                viscosity,
                self.compression_regularization_scale,
            )
            for index, scalar in enumerate(axial_force):
                force = scalar * tangent[index]
                local_force[index] += force
                local_force[index + 1] -= force
            axial_energy += branch_axial_energy
            axial_dissipation += branch_axial_dissipation

            bend_energy, bend_force = discrete_bending_energy_forces(
                points, branch.segment_rest_length, branch.ei
            )
            bending_energy += bend_energy
            local_force += bend_force

            particle_force[branch.bead_indices] += local_force[1:-1]
            self._accumulate_local_force(
                branch.start_kind,
                local_force[0],
                particle_force=particle_force,
                junction_index=self.junction_index,
                bob_force=bob_force,
                bob_torque=bob_torque,
                support_force=support_force,
                bob_arm=start_arm,
            )
            self._accumulate_local_force(
                branch.end_kind,
                local_force[-1],
                particle_force=particle_force,
                junction_index=self.junction_index,
                bob_force=bob_force,
                bob_torque=bob_torque,
                support_force=support_force,
                bob_arm=end_arm,
            )

            if include_aero and branch.drag_enabled:
                for local_bead, particle_index in enumerate(branch.bead_indices, start=1):
                    local_tangent = points[local_bead + 1] - points[local_bead - 1]
                    chord_length = float(np.linalg.norm(local_tangent))
                    if chord_length <= self.geometry_singularity_floor:
                        raise FloatingPointError(
                            f"{branch.name} has a degenerate aerodynamic bead chord."
                        )
                    local_tangent /= chord_length
                    relative = velocities[particle_index] - self.air_velocity
                    tangential = np.dot(relative, local_tangent) * local_tangent
                    normal = relative - tangential
                    normal_speed = float(np.linalg.norm(normal))
                    tangential_speed = float(np.linalg.norm(tangential))
                    normal_quadratic = (
                        0.5
                        * self.air_density
                        * branch.drag_cd_normal
                        * branch.diameter
                        * branch.cell_length
                    )
                    tangential_quadratic = (
                        0.5
                        * self.air_density
                        * branch.drag_cd_tangent
                        * branch.diameter
                        * branch.cell_length
                    )
                    normal_linear = (
                        branch.drag_linear_normal_per_length * branch.cell_length
                    )
                    tangential_linear = (
                        branch.drag_linear_tangent_per_length * branch.cell_length
                    )
                    drag = (
                        -normal_quadratic * normal_speed * normal
                        - tangential_quadratic * tangential_speed * tangential
                        - normal_linear * normal
                        - tangential_linear * tangential
                    )
                    particle_force[particle_index] += drag
                    aero_dissipation += (
                        normal_quadratic * normal_speed**3
                        + tangential_quadratic * tangential_speed**3
                        + normal_linear * normal_speed**2
                        + tangential_linear * tangential_speed**2
                    )
                    air_work += float(np.dot(drag, self.air_velocity))

            branch_positions[branch.name] = points
            branch_velocities[branch.name] = point_velocities
            branch_axial_force[branch.name] = axial_force
            branch_tension[branch.name] = tensile_force

        if include_aero and self.junction_drag_linear > 0.0:
            relative = velocities[self.junction_index] - self.air_velocity
            drag = -self.junction_drag_linear * relative
            particle_force[self.junction_index] += drag
            aero_dissipation += self.junction_drag_linear * float(
                np.dot(relative, relative)
            )
            air_work += float(np.dot(drag, self.air_velocity))

        if include_aero and self.cfg.bob.drag.enabled:
            relative = bob_velocity - self.air_velocity
            speed = float(np.linalg.norm(relative))
            quadratic = 0.5 * self.air_density * self.bob_cd * np.pi * self.bob_radius**2
            drag = -quadratic * speed * relative - self.bob_linear_drag * relative
            bob_force += drag
            aero_dissipation += quadratic * speed**3 + self.bob_linear_drag * speed**2
            air_work += float(np.dot(drag, self.air_velocity))

        support_work = 0.0
        for name, reaction_on_support in support_force.items():
            _, support_velocity, _ = self.support_motion[name].state(t)
            # reaction_on_support is the rod force on the kinematic support;
            # its negative is the force supplied to the simulated system.
            support_work -= float(np.dot(reaction_on_support, support_velocity))

        if compute_contact:
            (
                bob_contact_margin,
                bob_socket_material_extent,
                bob_socket_radial_monotonicity,
                bob_socket_cut_clearance,
            ) = self._bob_contact_margin(branch_positions, bob_position)
            (
                rod_self_contact_margin,
                junction_socket_material_extent,
                junction_socket_projective_opening,
                junction_socket_cut_clearance,
            ) = self._rod_self_contact_margin(branch_positions)
        else:
            bob_contact_margin = float("inf")
            bob_socket_material_extent = float("inf")
            bob_socket_radial_monotonicity = float("inf")
            bob_socket_cut_clearance = float("inf")
            rod_self_contact_margin = float("inf")
            junction_socket_material_extent = float("inf")
            junction_socket_projective_opening = float("inf")
            junction_socket_cut_clearance = float("inf")
        # Retain the public contact-margin field as a spatial surface margin
        # in metres.  Socket-domain validity is exposed by the six signed
        # subguards below rather than mixing metre and square-metre quantities.
        contact_margin = min(bob_contact_margin, rod_self_contact_margin)
        return HighFidelityEvaluation(
            particle_force=particle_force,
            bob_force=bob_force,
            bob_torque=bob_torque,
            support_force=support_force,
            branch_positions=branch_positions,
            branch_velocities=branch_velocities,
            branch_axial_force=branch_axial_force,
            branch_tension=branch_tension,
            axial_energy=axial_energy,
            bending_energy=bending_energy,
            # Preserve the raw constitutive/aerodynamic rates so validation can
            # actually falsify passivity instead of observing a clipped value.
            axial_dissipation_rate=float(axial_dissipation),
            aero_dissipation_rate=float(aero_dissipation),
            air_work_rate=air_work,
            support_work_rate=support_work,
            minimum_segment_length=minimum_segment_length,
            minimum_bending_turn_clearance=minimum_bending_turn_clearance,
            minimum_aerodynamic_chord_length=minimum_aerodynamic_chord_length,
            bob_contact_margin=bob_contact_margin,
            bob_socket_material_extent=bob_socket_material_extent,
            bob_socket_radial_monotonicity=bob_socket_radial_monotonicity,
            bob_socket_cut_clearance=bob_socket_cut_clearance,
            rod_self_contact_margin=rod_self_contact_margin,
            junction_socket_material_extent=junction_socket_material_extent,
            junction_socket_projective_opening=(
                junction_socket_projective_opening
            ),
            junction_socket_cut_clearance=junction_socket_cut_clearance,
            contact_margin=contact_margin,
        )

    def _bob_contact_margin(
        self, branch_positions: dict[str, np.ndarray], bob_position: np.ndarray
    ) -> tuple[float, float, float, float]:
        if not self.contact_guard_enabled:
            return (float("inf"),) * 4
        margins: list[float] = []
        socket_material_extent = float("inf")
        socket_radial_monotonicity = float("inf")
        socket_cut_clearance = float("inf")
        for name, points in branch_positions.items():
            branch = self.branches[name]
            diameter = branch.diameter
            if name == "lower":
                registration = self.bob_socket_registration
                required_center_distance = registration.socket_length
                # A fixed rest-material socket is part of the registered model
                # identity.  Its cut point is consequently an affine material
                # point independent of the instantaneous mesh geometry.
                socket_length = required_center_distance
                total_material_length = registration.total_length
                socket_material_extent = min(
                    socket_material_extent,
                    total_material_length - socket_length,
                )
                if socket_length >= total_material_length:
                    # The extent guard is non-positive and therefore rejects
                    # the state.  Do not construct a clipped pseudo-socket.
                    continue
                checked_segments = _registered_active_segments(
                    points, registration
                )
                socket_points = _registered_material_points(points, registration)
                radial = socket_points[:-1] - bob_position
                radial_increment = socket_points[1:] - socket_points[:-1]
                socket_radial_monotonicity = min(
                    socket_radial_monotonicity,
                    float(np.min(np.einsum("ij,ij->i", radial, radial_increment))),
                )
                socket_boundary = _registered_socket_cut(points, registration)
                socket_cut_clearance = min(
                    socket_cut_clearance,
                    float(np.linalg.norm(socket_boundary - bob_position))
                    - required_center_distance,
                )
            else:
                checked_segments = np.stack(
                    [points[:-1], points[1:]], axis=1
                )
            if checked_segments.size:
                distances = _batched_point_segment_distance(
                    bob_position,
                    checked_segments[:, 0],
                    checked_segments[:, 1],
                )
                margins.append(
                    float(np.min(distances))
                    - self.bob_contact_radius
                    - 0.5 * diameter
                )
        return (
            min(margins) if margins else float("inf"),
            socket_material_extent,
            socket_radial_monotonicity,
            socket_cut_clearance,
        )

    def _same_branch_registration_length(self, branch: RodBranch) -> float:
        """Fixed rest-material geodesic excluded from nonlocal self contact."""

        return 1.01 * (branch.diameter + self.minimum_clearance)

    def _bob_socket_length(self, branch: RodBranch) -> float:
        """Fixed lower-rod rest-material distance occupied by the bob socket."""

        return (
            self.bob_contact_radius
            + 0.5 * branch.diameter
            + self.minimum_clearance
        )

    def _junction_socket_length(
        self, first: RodBranch, second: RodBranch
    ) -> float:
        """Fixed rest-material crop on each incident branch of a pair."""

        required_center_separation = (
            0.5 * (first.diameter + second.diameter)
            + self.minimum_clearance
        )
        return 2.0 * required_center_separation

    def _rod_self_contact_margin(
        self, branch_positions: dict[str, np.ndarray]
    ) -> tuple[float, float, float, float]:
        """Return clearance outside fixed rest-material connection neighbourhoods."""

        minimum = float("inf")
        junction_material_extent = float("inf")
        junction_projective_opening = float("inf")
        junction_cut_clearance = float("inf")
        for name, points in branch_positions.items():
            branch = self.branches[name]
            registration = self.same_branch_contact_registration[name]
            pairs = registration.full_pairs
            if pairs.size:
                distances = _batched_segment_segment_distance(
                    points[pairs[:, 0]],
                    points[pairs[:, 0] + 1],
                    points[pairs[:, 1]],
                    points[pairs[:, 1] + 1],
                )
                minimum = min(
                    minimum,
                    float(np.min(distances)) - branch.diameter,
                )
            for (
                first,
                second,
                first_material_start,
                first_material_end,
                second_material_start,
                second_material_end,
            ) in registration.partial_pairs:
                distance = _materially_separated_segment_distance(
                    points[first],
                    points[first + 1],
                    points[second],
                    points[second + 1],
                    first_material_start=first_material_start,
                    first_material_end=first_material_end,
                    second_material_start=second_material_start,
                    second_material_end=second_material_end,
                    minimum_material_separation=(
                        registration.minimum_material_separation
                    ),
                )
                minimum = min(minimum, distance - branch.diameter)

        for registration in self.junction_contact_registration:
            points_a = branch_positions[registration.first_name]
            points_b = branch_positions[registration.second_name]
            branch_a = self.branches[registration.first_name]
            branch_b = self.branches[registration.second_name]
            active_a = _registered_active_segments(
                points_a, registration.first_socket
            )
            active_b = _registered_active_segments(
                points_b, registration.second_socket
            )
            junction_material_extent = min(
                junction_material_extent,
                registration.first_socket.total_length
                - registration.first_socket.socket_length,
                registration.second_socket.total_length
                - registration.second_socket.socket_length,
            )
            if active_a.size == 0 or active_b.size == 0:
                continue
            opening_squared = _registered_projective_opening_squared(
                points_a,
                registration.first_socket,
                points_b,
                registration.second_socket,
            )
            junction_projective_opening = min(
                junction_projective_opening,
                opening_squared
                - registration.registered_projective_opening_squared,
            )
            boundary_separation = np.linalg.norm(
                _registered_socket_cut(points_a, registration.first_socket)
                - _registered_socket_cut(points_b, registration.second_socket)
            )
            junction_cut_clearance = min(
                junction_cut_clearance,
                float(
                    boundary_separation
                    - registration.required_center_separation
                ),
            )
            all_a = np.stack([points_a[:-1], points_a[1:]], axis=1)
            all_b = np.stack([points_b[:-1], points_b[1:]], axis=1)
            # The registered connector domain is the product of the two fixed
            # socket intervals.  Its complement is the union below.  Keeping
            # the two Cartesian products (including their harmless overlap)
            # preserves the scalar algorithm while evaluating them in NumPy.
            spatial_distance = min(
                _minimum_cartesian_segment_distance(active_a, all_b),
                _minimum_cartesian_segment_distance(all_a, active_b),
            )
            minimum = min(
                minimum,
                spatial_distance
                - 0.5 * (branch_a.diameter + branch_b.diameter),
            )
        return (
            minimum,
            junction_material_extent,
            junction_projective_opening,
            junction_cut_clearance,
        )

    def rhs(self, t: float, state: np.ndarray) -> np.ndarray:
        (
            particle_positions,
            bob_position,
            quaternion,
            particle_velocities,
            bob_velocity,
            angular_velocity,
        ) = self.unpack_state(state)
        evaluation = self.evaluate(
            t,
            particle_positions,
            particle_velocities,
            bob_position,
            bob_velocity,
            quaternion,
            angular_velocity,
            compute_contact=False,
        )
        particle_acceleration = evaluation.particle_force / self.particle_mass[:, None]
        bob_acceleration = evaluation.bob_force / self.bob_mass
        angular_acceleration = evaluation.bob_torque / self.bob_inertia
        raw_quaternion = np.asarray(quaternion, dtype=float)
        quaternion_rate = 0.5 * quaternion_multiply(
            np.concatenate([[0.0], angular_velocity]), raw_quaternion
        )
        quaternion_rate += (
            self.quaternion_stabilization_rate
            * (1.0 - float(np.dot(raw_quaternion, raw_quaternion)))
            * raw_quaternion
        )
        return self.pack_state(
            particle_velocities,
            bob_velocity,
            quaternion_rate,
            particle_acceleration,
            bob_acceleration,
            angular_acceleration,
        )

    def energy_snapshot(
        self,
        t: float,
        particle_positions: np.ndarray,
        particle_velocities: np.ndarray,
        bob_position: np.ndarray,
        bob_velocity: np.ndarray,
        quaternion: np.ndarray,
        angular_velocity: np.ndarray,
        evaluation: HighFidelityEvaluation | None = None,
    ) -> dict[str, float]:
        ev = evaluation or self.evaluate(
            t,
            particle_positions,
            particle_velocities,
            bob_position,
            bob_velocity,
            quaternion,
            angular_velocity,
        )
        kinetic_particles = 0.5 * float(
            np.sum(self.particle_mass[:, None] * particle_velocities**2)
        )
        kinetic_bob_translation = 0.5 * self.bob_mass * float(
            np.dot(bob_velocity, bob_velocity)
        )
        kinetic_bob_rotation = 0.5 * self.bob_inertia * float(
            np.dot(angular_velocity, angular_velocity)
        )
        gravitational = -float(
            np.sum(self.particle_mass[:, None] * particle_positions * self.gravity[None, :])
        ) - self.bob_mass * float(np.dot(bob_position, self.gravity))
        buoyancy_potential = -float(np.dot(bob_position, self.bob_buoyancy))
        kinetic = kinetic_particles + kinetic_bob_translation + kinetic_bob_rotation
        mechanical = (
            kinetic
            + gravitational
            + buoyancy_potential
            + ev.axial_energy
            + ev.bending_energy
        )
        return {
            "kinetic": kinetic,
            "kinetic_particles": kinetic_particles,
            "kinetic_bob_translation": kinetic_bob_translation,
            "kinetic_bob_rotation": kinetic_bob_rotation,
            "gravitational": gravitational + buoyancy_potential,
            "elastic_axial": ev.axial_energy,
            "elastic_bending": ev.bending_energy,
            "mechanical": mechanical,
            "axial_dissipation_rate": ev.axial_dissipation_rate,
            "aero_dissipation_rate": ev.aero_dissipation_rate,
            "air_work_rate": ev.air_work_rate,
            "support_work_rate": ev.support_work_rate,
        }

    def guard_value(self, t: float, state: np.ndarray) -> float:
        components = self.guard_components(t, state)
        metadata = self.guard_component_metadata()
        return float(
            min(
                value / float(metadata[name]["scale"])
                for name, value in components.items()
            )
        )

    def guard_component_metadata(self) -> dict[str, dict[str, float | str]]:
        """Return frozen units, normalization scales and raw tolerances."""

        length_scale = self.characteristic_length
        square_length_scale = length_scale**2
        definitions: dict[str, tuple[str, float]] = {
            "MINIMUM_SEGMENT_LENGTH": ("m", length_scale),
            "BENDING_TURN_CLEARANCE": ("dimensionless", 1.0),
            "AERODYNAMIC_CHORD_LENGTH": ("m", length_scale),
        }
        if self.contact_guard_enabled:
            definitions.update(
                {
                    "BOB_ROD_CLEARANCE": ("m", length_scale),
                    "ROD_SELF_CLEARANCE": ("m", length_scale),
                    "BOB_SOCKET_MATERIAL_EXTENT": ("m", length_scale),
                    "BOB_SOCKET_RADIAL_MONOTONICITY": (
                        "m^2",
                        square_length_scale,
                    ),
                    "BOB_SOCKET_CUT_CLEARANCE": ("m", length_scale),
                    "JUNCTION_SOCKET_MATERIAL_EXTENT": ("m", length_scale),
                    "JUNCTION_SOCKET_PROJECTIVE_OPENING": (
                        "dimensionless",
                        1.0,
                    ),
                    "JUNCTION_SOCKET_CUT_CLEARANCE": ("m", length_scale),
                }
            )
        machine_factor = 1024.0 * np.finfo(float).eps
        return {
            name: {
                "unit": unit,
                "scale": scale,
                "tolerance": machine_factor * scale,
            }
            for name, (unit, scale) in definitions.items()
        }

    def guard_components(self, t: float, state: np.ndarray) -> dict[str, float]:
        (
            particle_positions,
            bob_position,
            quaternion,
            particle_velocities,
            bob_velocity,
            angular_velocity,
        ) = self.unpack_state(state)
        evaluation = self.evaluate(
            t,
            particle_positions,
            particle_velocities,
            bob_position,
            bob_velocity,
            quaternion,
            angular_velocity,
            # Guard evaluation must remain defined beyond the registered
            # aerodynamic-chord root.  The physical RHS still fails closed on
            # a singular drag direction, but root finding never asks that
            # invalid aerodynamic law to produce a force.
            include_aero=False,
        )
        return self.guard_components_from_evaluation(evaluation)

    def guard_components_from_evaluation(
        self,
        evaluation: HighFidelityEvaluation,
    ) -> dict[str, float]:
        """Build every registered guard from one already-computed evaluation.

        Presentation post-processing needs forces, energy inputs, contact
        distances and guards at the same state.  Keeping this conversion pure
        avoids evaluating the expensive contact geometry twice while retaining
        exactly the same guard definitions used by root finding.
        """

        margins = {
            "MINIMUM_SEGMENT_LENGTH": evaluation.minimum_segment_length
            - self.length_guard,
            "BENDING_TURN_CLEARANCE": evaluation.minimum_bending_turn_clearance
            - self.bending_turn_clearance_floor,
            "AERODYNAMIC_CHORD_LENGTH": evaluation.minimum_aerodynamic_chord_length
            - self.aerodynamic_chord_guard,
        }
        if self.contact_guard_enabled:
            margins["BOB_ROD_CLEARANCE"] = (
                evaluation.bob_contact_margin - self.minimum_clearance
            )
            margins["ROD_SELF_CLEARANCE"] = (
                evaluation.rod_self_contact_margin - self.minimum_clearance
            )
            margins["BOB_SOCKET_MATERIAL_EXTENT"] = (
                evaluation.bob_socket_material_extent
            )
            margins["BOB_SOCKET_RADIAL_MONOTONICITY"] = (
                evaluation.bob_socket_radial_monotonicity
            )
            margins["BOB_SOCKET_CUT_CLEARANCE"] = (
                evaluation.bob_socket_cut_clearance
            )
            margins["JUNCTION_SOCKET_MATERIAL_EXTENT"] = (
                evaluation.junction_socket_material_extent
            )
            margins["JUNCTION_SOCKET_PROJECTIVE_OPENING"] = (
                evaluation.junction_socket_projective_opening
            )
            margins["JUNCTION_SOCKET_CUT_CLEARANCE"] = (
                evaluation.junction_socket_cut_clearance
            )
        return margins

    def diagnostics(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "physics_path": "local material beads + passive unilateral/bilateral KV blend + three-point bending + finite rigid bob",
            "particle_count": self.particle_count,
            "state_size": self.state_size,
            "junction_index": self.junction_index,
            "bob_inertia_kg_m2": self.bob_inertia,
            "bob_attachment_body_m": self.attachment_body.tolist(),
            "bob_contact_radius_m": self.bob_contact_radius,
            "physical_force_scale_N": self.force_scale,
            "tension_zero_tolerance_N": self.tension_zero_tolerance,
            "axial_material_model": self.cfg.high_fidelity.axial_material_model,
            "cable_material_field_semantics": (
                "E, eta, area parameter source only; HF axial_material_model owns "
                "the constitutive branch"
            ),
            "compression_regularization_scale": self.compression_regularization_scale,
            "geometry_singularity_floor_m": self.geometry_singularity_floor,
            "length_guard_m": self.length_guard,
            "bending_turn_clearance_floor": self.bending_turn_clearance_floor,
            "aerodynamic_chord_guard_m": self.aerodynamic_chord_guard,
            "quaternion_stabilization_rate_s_inv": self.quaternion_stabilization_rate,
            "contact_registration_id": (
                "FIXED_REST_MATERIAL_SOCKETS_PROJECTIVE_V2"
            ),
            "same_branch_minimum_material_separation_m": {
                name: self._same_branch_registration_length(branch)
                for name, branch in self.branches.items()
            },
            "same_branch_full_contact_pair_count": {
                name: int(registration.full_pairs.shape[0])
                for name, registration in self.same_branch_contact_registration.items()
            },
            "same_branch_partial_contact_pair_count": {
                name: len(registration.partial_pairs)
                for name, registration in self.same_branch_contact_registration.items()
            },
            "junction_contact_pair_count": len(self.junction_contact_registration),
            "contact_topology_precomputed": True,
            "bob_socket_rest_material_length_m": self._bob_socket_length(
                self.branches["lower"]
            ),
            "junction_pair_socket_rest_material_length_m": {
                f"{first_name}__{second_name}": self._junction_socket_length(
                    self.branches[first_name], self.branches[second_name]
                )
                for index, first_name in enumerate(BRANCH_NAMES)
                for second_name in BRANCH_NAMES[index + 1 :]
            },
            "junction_socket_projective_opening_definition": (
                "inf_{s,t>=0,s+t>0} ||p_i(s)-p_j(t)||^2/(s+t)^2 "
                "minus (required_center_separation/(2*socket_length))^2"
            ),
            "branch_beads": {
                name: int(branch.bead_indices.size)
                for name, branch in self.branches.items()
            },
            "branch_bending_stiffness_N_m2": {
                name: branch.ei for name, branch in self.branches.items()
            },
            "contact_scope": (
                "bob-vs-rod and rod-vs-rod root guards; friction, compliant contact, "
                "fracture, ground contact and knot sliding excluded"
            ),
        }

    def jacobian_sparsity(self) -> sparse.csr_matrix:
        """Conservative dependency graph for colored finite differences.

        This is not an imported FWD matrix or analytic FWD Jacobian.  It is the
        graph of the local bead/rod and rigid-body Newton interactions above.
        Every true derivative is covered; marking a few extra entries only
        reduces coloring efficiency and cannot change the equations.
        """

        size = self.state_size
        n = self.position_size
        velocity_offset = n + 7
        pattern = sparse.lil_matrix((size, size), dtype=np.int8)

        particle_q = np.arange(n)
        bob_q = np.arange(n, n + 3)
        quaternion_q = np.arange(n + 3, n + 7)
        particle_v = np.arange(velocity_offset, velocity_offset + n)
        bob_v = np.arange(velocity_offset + n, velocity_offset + n + 3)
        omega = np.arange(velocity_offset + n + 3, velocity_offset + n + 6)

        pattern[particle_q, particle_v] = 1
        pattern[bob_q, bob_v] = 1
        pattern[np.ix_(quaternion_q, quaternion_q)] = 1
        pattern[np.ix_(quaternion_q, omega)] = 1

        def particle_coordinates(indices: np.ndarray, *, velocity: bool) -> np.ndarray:
            base = velocity_offset if velocity else 0
            blocks = [
                np.arange(base + 3 * int(index), base + 3 * int(index) + 3)
                for index in np.asarray(indices, dtype=np.int64)
            ]
            return np.concatenate(blocks) if blocks else np.asarray([], dtype=np.int64)

        def point_dependencies(branch: RodBranch, point_indices: range) -> np.ndarray:
            columns: list[np.ndarray] = []
            point_count = int(branch.bead_indices.size) + 2
            for local_point in point_indices:
                if not 0 <= local_point < point_count:
                    continue
                if 1 <= local_point <= branch.bead_indices.size:
                    particle = np.asarray(
                        [branch.bead_indices[local_point - 1]], dtype=np.int64
                    )
                    columns.extend(
                        [
                            particle_coordinates(particle, velocity=False),
                            particle_coordinates(particle, velocity=True),
                        ]
                    )
                    continue
                kind = branch.start_kind if local_point == 0 else branch.end_kind
                if kind == "junction":
                    junction = np.asarray([self.junction_index], dtype=np.int64)
                    columns.extend(
                        [
                            particle_coordinates(junction, velocity=False),
                            particle_coordinates(junction, velocity=True),
                        ]
                    )
                elif kind == "bob_attachment":
                    columns.extend([bob_q, quaternion_q, bob_v, omega])
                # Prescribed supports depend only on time, not on state.
            return (
                np.unique(np.concatenate(columns))
                if columns
                else np.asarray([], dtype=np.int64)
            )

        for branch in self.branches.values():
            for local_bead, particle_index in enumerate(branch.bead_indices):
                # Axial and aerodynamic interactions are nearest-neighbour;
                # a three-point bending force reaches at most two material
                # points to either side of the affected bead.
                local_point = local_bead + 1
                dependency = point_dependencies(
                    branch, range(local_point - 2, local_point + 3)
                )
                rows = particle_coordinates(
                    np.asarray([particle_index], dtype=np.int64), velocity=True
                )
                pattern[np.ix_(rows, dependency)] = 1

        junction_rows = np.arange(
            velocity_offset + 3 * self.junction_index,
            velocity_offset + 3 * self.junction_index + 3,
        )
        junction_dependencies = [
            particle_coordinates(
                np.asarray([self.junction_index], dtype=np.int64), velocity=False
            ),
            particle_coordinates(
                np.asarray([self.junction_index], dtype=np.int64), velocity=True
            ),
        ]
        for branch in self.branches.values():
            if branch.start_kind == "junction":
                junction_dependencies.append(point_dependencies(branch, range(0, 3)))
            if branch.end_kind == "junction":
                end = int(branch.bead_indices.size) + 1
                junction_dependencies.append(
                    point_dependencies(branch, range(end - 2, end + 1))
                )
        pattern[
            np.ix_(junction_rows, np.unique(np.concatenate(junction_dependencies)))
        ] = 1

        bob_acceleration_rows = np.arange(
            velocity_offset + n, velocity_offset + n + 3
        )
        angular_acceleration_rows = np.arange(
            velocity_offset + n + 3, velocity_offset + n + 6
        )
        lower = self.branches["lower"]
        lower_end = int(lower.bead_indices.size) + 1
        rigid_dependencies = np.unique(
            np.concatenate(
                [
                    point_dependencies(
                        lower, range(lower_end - 2, lower_end + 1)
                    ),
                    bob_q,
                    quaternion_q,
                    bob_v,
                    omega,
                ]
            )
        )
        pattern[np.ix_(bob_acceleration_rows, rigid_dependencies)] = 1
        pattern[np.ix_(angular_acceleration_rows, rigid_dependencies)] = 1
        return pattern.tocsr()

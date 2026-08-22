"""Independent reference kernel for HF qualification.

This module intentionally does not import or call :meth:`HighFidelityModel.evaluate`.
It consumes the frozen, read-only geometry/material data carried by a model instance
and rebuilds the local rod, rigid-bob, aerodynamic, support-work and validity-guard
quantities from the public state.  The duplication is deliberate: validation must
not certify a derived production field with the same routine that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pragma: no cover - imports are only for static type checking
    from .model import HighFidelityModel, RodBranch


@dataclass(frozen=True)
class ReferenceSnapshot:
    """All independently reconstructed instantaneous HF observables."""

    particle_force: np.ndarray
    bob_force: np.ndarray
    bob_torque: np.ndarray
    support_force: dict[str, np.ndarray]
    branch_positions: dict[str, np.ndarray]
    branch_velocities: dict[str, np.ndarray]
    branch_axial_force: dict[str, np.ndarray]
    branch_tension: dict[str, np.ndarray]
    kinetic_particles: float
    kinetic_bob_translation: float
    kinetic_bob_rotation: float
    gravitational: float
    axial_energy: float
    bending_energy: float
    mechanical_energy: float
    axial_dissipation_rate: float
    aero_dissipation_rate: float
    axial_power_roundoff_scale: float
    aero_power_roundoff_scale: float
    air_work_rate: float
    support_work_rate: float
    guard_margins: dict[str, float]


def normalize_quaternion_reference(quaternion: np.ndarray) -> np.ndarray:
    """Normalize a scalar-first quaternion without using the production helper."""

    value = np.asarray(quaternion, dtype=float)
    norm = float(np.sqrt(np.dot(value, value)))
    if value.shape != (4,) or not np.isfinite(norm) or norm <= 1.0e-14:
        raise FloatingPointError("Reference quaternion is not finite/non-zero.")
    return value / norm


def rotate_body_vector_reference(
    quaternion: np.ndarray, vector: np.ndarray
) -> np.ndarray:
    """Apply the unit-quaternion rotation using its explicit rotation matrix."""

    w, x, y, z = normalize_quaternion_reference(quaternion)
    rotation = np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - w * z), 2.0 * (x * z + w * y)],
            [2.0 * (x * y + w * z), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - w * x)],
            [2.0 * (x * z - w * y), 2.0 * (y * z + w * x), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=float,
    )
    return rotation @ np.asarray(vector, dtype=float)


def unpack_reference_state(
    model: HighFidelityModel, state: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Decode the registered public HF state without calling ``model.unpack_state``."""

    value = np.asarray(state, dtype=float)
    if value.shape != (model.state_size,) or not np.all(np.isfinite(value)):
        raise ValueError("Reference kernel received an invalid HF state vector.")
    n = int(model.position_size)
    velocity_offset = n + 7
    return (
        value[:n].reshape(model.particle_count, 3),
        value[n : n + 3],
        value[n + 3 : n + 7],
        value[velocity_offset : velocity_offset + n].reshape(model.particle_count, 3),
        value[velocity_offset + n : velocity_offset + n + 3],
        value[velocity_offset + n + 3 : velocity_offset + n + 6],
    )


def pack_reference_state(
    particle_positions: np.ndarray,
    bob_position: np.ndarray,
    quaternion: np.ndarray,
    particle_velocities: np.ndarray,
    bob_velocity: np.ndarray,
    angular_velocity: np.ndarray,
) -> np.ndarray:
    """Encode an HF state without delegating to the production model."""

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


def _endpoint_state_reference(
    model: HighFidelityModel,
    kind: str,
    time: float,
    particle_positions: np.ndarray,
    particle_velocities: np.ndarray,
    bob_position: np.ndarray,
    bob_velocity: np.ndarray,
    quaternion: np.ndarray,
    angular_velocity: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    if kind in model.support_motion:
        position, velocity, _ = model.support_motion[kind].state(float(time))
        return np.asarray(position), np.asarray(velocity), None
    if kind == "junction":
        return (
            particle_positions[model.junction_index],
            particle_velocities[model.junction_index],
            None,
        )
    if kind == "bob_attachment":
        arm = rotate_body_vector_reference(quaternion, model.attachment_body)
        return (
            bob_position + arm,
            bob_velocity + np.cross(angular_velocity, arm),
            arm,
        )
    raise KeyError(kind)


def _apply_endpoint_force(
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
        if bob_arm is None:
            raise AssertionError("Bob endpoint force is missing its moment arm.")
        bob_force += force
        bob_torque += np.cross(bob_arm, force)
    else:  # pragma: no cover - model construction freezes the endpoint vocabulary
        raise KeyError(kind)


def bending_energy_forces_reference(
    points: np.ndarray,
    segment_rest_length: np.ndarray,
    bending_stiffness: float,
) -> tuple[float, np.ndarray]:
    """Independently differentiate the registered three-point bending energy."""

    coordinates = np.asarray(points, dtype=float)
    rest = np.asarray(segment_rest_length, dtype=float)
    if (
        coordinates.ndim != 2
        or coordinates.shape[1] != 3
        or coordinates.shape[0] < 3
        or rest.shape != (coordinates.shape[0] - 1,)
        or not np.all(np.isfinite(coordinates))
        or not np.all(np.isfinite(rest))
        or np.any(rest <= 0.0)
        or not np.isfinite(bending_stiffness)
        or bending_stiffness < 0.0
    ):
        raise ValueError("Invalid input to the independent bending kernel.")

    edges = np.diff(coordinates, axis=0)
    edge_length = np.sqrt(np.einsum("ij,ij->i", edges, edges))
    if np.any(edge_length <= 0.0):
        raise FloatingPointError("Collapsed segment in reference bending kernel.")
    tangent = edges / edge_length[:, None]
    nodal_gradient = np.zeros_like(coordinates)
    total_energy = 0.0
    identity = np.eye(3)
    for vertex in range(1, coordinates.shape[0] - 1):
        left = tangent[vertex - 1]
        right = tangent[vertex]
        curvature_jump = right - left
        dual_length = 0.5 * (rest[vertex - 1] + rest[vertex])
        modulus = bending_stiffness / dual_length
        total_energy += 0.5 * modulus * float(curvature_jump @ curvature_jump)

        # dU/de for each adjacent edge, followed by the edge-to-node incidence
        # transpose.  This is kept separate from the production force assembly.
        d_u_d_left_edge = (
            -modulus
            * (identity - np.outer(left, left))
            @ curvature_jump
            / edge_length[vertex - 1]
        )
        d_u_d_right_edge = (
            modulus
            * (identity - np.outer(right, right))
            @ curvature_jump
            / edge_length[vertex]
        )
        nodal_gradient[vertex - 1] -= d_u_d_left_edge
        nodal_gradient[vertex] += d_u_d_left_edge - d_u_d_right_edge
        nodal_gradient[vertex + 1] += d_u_d_right_edge
    return float(total_energy), -nodal_gradient


def point_segment_distance_reference(
    point: np.ndarray, start: np.ndarray, end: np.ndarray
) -> float:
    direction = np.asarray(end) - np.asarray(start)
    squared = float(direction @ direction)
    if squared <= 1.0e-30:
        return float(np.linalg.norm(np.asarray(point) - np.asarray(start)))
    parameter = float((np.asarray(point) - np.asarray(start)) @ direction / squared)
    parameter = float(np.clip(parameter, 0.0, 1.0))
    closest = np.asarray(start) + parameter * direction
    return float(np.linalg.norm(np.asarray(point) - closest))


def segment_segment_distance_reference(
    first_start: np.ndarray,
    first_end: np.ndarray,
    second_start: np.ndarray,
    second_end: np.ndarray,
) -> float:
    """Distance between closed 3-D segments via the constrained two-line solve."""

    p0 = np.asarray(first_start, dtype=float)
    p1 = np.asarray(first_end, dtype=float)
    q0 = np.asarray(second_start, dtype=float)
    q1 = np.asarray(second_end, dtype=float)
    u = p1 - p0
    v = q1 - q0
    w = p0 - q0
    a = float(u @ u)
    c = float(v @ v)
    tiny = np.finfo(float).tiny
    if a <= tiny and c <= tiny:
        return float(np.linalg.norm(w))
    if a <= tiny:
        return point_segment_distance_reference(p0, q0, q1)
    if c <= tiny:
        return point_segment_distance_reference(q0, p0, p1)
    # Every boundary optimum is one endpoint against the opposite closed
    # segment.  These candidates also make parallel/collinear overlap robust.
    candidates = [
        point_segment_distance_reference(p0, q0, q1),
        point_segment_distance_reference(p1, q0, q1),
        point_segment_distance_reference(q0, p0, p1),
        point_segment_distance_reference(q1, p0, p1),
    ]
    normal = np.cross(u, v)
    normal_squared = float(normal @ normal)
    if normal_squared > 0.0:
        offset = q0 - p0
        first_parameter = float(np.cross(offset, v) @ normal / normal_squared)
        second_parameter = float(np.cross(offset, u) @ normal / normal_squared)
        parameter_tolerance = 64.0 * np.finfo(float).eps
        if (
            -parameter_tolerance <= first_parameter <= 1.0 + parameter_tolerance
            and -parameter_tolerance
            <= second_parameter
            <= 1.0 + parameter_tolerance
        ):
            first_parameter = float(np.clip(first_parameter, 0.0, 1.0))
            second_parameter = float(np.clip(second_parameter, 0.0, 1.0))
            candidates.append(
                float(
                    np.linalg.norm(
                        w + first_parameter * u - second_parameter * v
                    )
                )
            )
    return float(min(candidates))


def materially_separated_segment_distance_reference(
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
    """Minimise segment distance on a fixed rest-material separation domain."""

    first_span = float(first_material_end - first_material_start)
    second_span = float(second_material_end - second_material_start)
    offset = float(
        minimum_material_separation
        - (second_material_start - first_material_start)
    )

    def feasible(parameter: np.ndarray) -> float:
        first_parameter, second_parameter = parameter
        return second_parameter * second_span - first_parameter * first_span - offset

    polygon = [
        np.array([0.0, 0.0]),
        np.array([1.0, 0.0]),
        np.array([1.0, 1.0]),
        np.array([0.0, 1.0]),
    ]
    tolerance = 128.0 * np.finfo(float).eps * max(
        first_span, second_span, abs(offset), np.finfo(float).tiny
    )
    clipped: list[np.ndarray] = []
    for start, end in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        start_value = feasible(start)
        end_value = feasible(end)
        start_inside = start_value >= -tolerance
        end_inside = end_value >= -tolerance
        if start_inside:
            clipped.append(start)
        if start_inside != end_inside:
            fraction = start_value / (start_value - end_value)
            clipped.append(start + fraction * (end - start))
    if not clipped:
        return float("inf")

    p0 = np.asarray(first_start, dtype=float)
    q0 = np.asarray(second_start, dtype=float)
    first_direction = np.asarray(first_end, dtype=float) - p0
    second_direction = np.asarray(second_end, dtype=float) - q0

    def delta(parameter: np.ndarray) -> np.ndarray:
        return (
            p0
            + parameter[0] * first_direction
            - q0
            - parameter[1] * second_direction
        )

    candidates = [float(np.linalg.norm(delta(vertex))) for vertex in clipped]
    for start, end in zip(clipped, clipped[1:] + clipped[:1], strict=True):
        parameter_direction = end - start
        spatial_start = delta(start)
        spatial_direction = (
            parameter_direction[0] * first_direction
            - parameter_direction[1] * second_direction
        )
        denominator = float(spatial_direction @ spatial_direction)
        if denominator > 0.0:
            fraction = float(
                np.clip(
                    -(spatial_start @ spatial_direction) / denominator,
                    0.0,
                    1.0,
                )
            )
            candidates.append(
                float(np.linalg.norm(spatial_start + fraction * spatial_direction))
            )

    normal = np.cross(first_direction, second_direction)
    normal_squared = float(normal @ normal)
    if normal_squared > 0.0:
        offset_vector = q0 - p0
        first_parameter = float(
            np.cross(offset_vector, second_direction) @ normal / normal_squared
        )
        second_parameter = float(
            np.cross(offset_vector, first_direction) @ normal / normal_squared
        )
        parameter = np.array([first_parameter, second_parameter])
        if (
            -tolerance <= first_parameter <= 1.0 + tolerance
            and -tolerance <= second_parameter <= 1.0 + tolerance
            and feasible(parameter) >= -tolerance
        ):
            candidates.append(float(np.linalg.norm(delta(parameter))))
    return float(min(candidates))


def material_point_from_joint_reference(
    points: np.ndarray,
    segment_rest_length: np.ndarray,
    side: str,
    material_distance: float,
) -> tuple[np.ndarray, tuple[int, int, float]]:
    """Return a fixed rest-material cut point and its affine node weights."""

    coordinates = np.asarray(points, dtype=float)
    rest = np.asarray(segment_rest_length, dtype=float)
    if side not in {"start", "end"}:
        raise ValueError("Material socket side must be 'start' or 'end'.")
    indices = np.arange(coordinates.shape[0], dtype=int)
    if side == "end":
        coordinates = coordinates[::-1]
        rest = rest[::-1]
        indices = indices[::-1]
    total = float(np.sum(rest))
    distance = float(np.clip(material_distance, 0.0, total))
    cumulative = np.concatenate([[0.0], np.cumsum(rest)])
    segment = min(
        int(np.searchsorted(cumulative, distance, side="right") - 1),
        rest.size - 1,
    )
    fraction = float((distance - cumulative[segment]) / rest[segment])
    left = int(indices[segment])
    right = int(indices[segment + 1])
    point = (1.0 - fraction) * coordinates[segment] + fraction * coordinates[segment + 1]
    return point, (left, right, fraction)


def material_segments_outside_socket_reference(
    points: np.ndarray,
    segment_rest_length: np.ndarray,
    side: str,
    socket_length: float,
) -> list[
    tuple[
        np.ndarray,
        np.ndarray,
        tuple[int, int, float],
        tuple[int, int, float],
    ]
]:
    """Return collision-active segments beyond a fixed rest-material socket."""

    coordinates = np.asarray(points, dtype=float)
    total = float(np.sum(segment_rest_length))
    if not 0.0 <= socket_length < total:
        return []
    cut, cut_reference = material_point_from_joint_reference(
        coordinates, segment_rest_length, side, socket_length
    )
    oriented_indices = np.arange(coordinates.shape[0], dtype=int)
    rest = np.asarray(segment_rest_length, dtype=float)
    if side == "end":
        oriented_indices = oriented_indices[::-1]
        rest = rest[::-1]
    cumulative = np.concatenate([[0.0], np.cumsum(rest)])
    segment = min(
        int(np.searchsorted(cumulative, socket_length, side="right") - 1),
        rest.size - 1,
    )
    active_points = [cut]
    active_references = [cut_reference]
    for index in oriented_indices[segment + 1 :]:
        node = int(index)
        active_points.append(coordinates[node])
        active_references.append((node, node, 0.0))
    return [
        (start, end, start_reference, end_reference)
        for start, end, start_reference, end_reference in zip(
            active_points[:-1],
            active_points[1:],
            active_references[:-1],
            active_references[1:],
            strict=True,
        )
        if float(np.linalg.norm(end - start)) > 0.0
    ]


def material_points_inside_socket_reference(
    points: np.ndarray,
    segment_rest_length: np.ndarray,
    side: str,
    socket_length: float,
) -> list[tuple[np.ndarray, tuple[int, int, float]]]:
    """Return fixed material breakpoints from a joint through its socket cut."""

    coordinates = np.asarray(points, dtype=float)
    cut, cut_reference = material_point_from_joint_reference(
        coordinates, segment_rest_length, side, socket_length
    )
    indices = np.arange(coordinates.shape[0], dtype=int)
    rest = np.asarray(segment_rest_length, dtype=float)
    if side == "end":
        indices = indices[::-1]
        rest = rest[::-1]
    cumulative = np.concatenate([[0.0], np.cumsum(rest)])
    inside = [(coordinates[int(indices[0])], (int(indices[0]), int(indices[0]), 0.0))]
    for edge_index in range(1, indices.size - 1):
        if cumulative[edge_index] >= socket_length:
            break
        node = int(indices[edge_index])
        inside.append((coordinates[node], (node, node, 0.0)))
    inside.append((cut, cut_reference))
    return inside


def socket_material_breakpoints_reference(
    segment_rest_length: np.ndarray, side: str, socket_length: float
) -> np.ndarray:
    """Return fixed rest-material breakpoints inside a registered socket."""

    rest = np.asarray(segment_rest_length, dtype=float)
    if side == "end":
        rest = rest[::-1]
    elif side != "start":
        raise ValueError("Material socket side must be 'start' or 'end'.")
    cumulative = np.concatenate([[0.0], np.cumsum(rest)])
    internal = cumulative[(cumulative > 0.0) & (cumulative < socket_length)]
    return np.concatenate([[0.0], internal, [float(socket_length)]])


def minimum_projective_opening_squared_on_material_cell_reference(
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
    """Independently minimise ``|p(s)-q(t)|^2/(s+t)^2`` on one cell."""

    s0 = float(first_material_start)
    s1 = float(first_material_end)
    t0 = float(second_material_start)
    t1 = float(second_material_end)
    if not (0.0 <= s0 < s1 and 0.0 <= t0 < t1):
        raise ValueError("Projective reference cells must have positive extent.")

    p0 = np.asarray(first_start, dtype=float)
    p1 = np.asarray(first_end, dtype=float)
    q0 = np.asarray(second_start, dtype=float)
    q1 = np.asarray(second_end, dtype=float)
    p_slope = (p1 - p0) / (s1 - s0)
    q_slope = (q1 - q0) / (t1 - t0)
    origin_offset = p0 - q0 - p_slope * s0 + q_slope * t0

    if s0 == 0.0 and t0 == 0.0:
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
        # On the projective closure x=s/(s+t), the normalized separation is
        # -q_slope + x*(p_slope+q_slope).  Minimise this affine vector on [0,1].
        base = -q_slope
        direction = p_slope + q_slope
        denominator = float(direction @ direction)
        fraction = 0.0
        if denominator > 0.0:
            fraction = float(np.clip(-(base @ direction) / denominator, 0.0, 1.0))
        vector = base + fraction * direction
        return max(float(vector @ vector), 0.0)

    # With u=1/(s+t), x=s/(s+t), the normalized separation is affine in
    # (u,x).  The material rectangle maps to a convex quadrilateral.  A convex
    # quadratic reaches its minimum at the unconstrained stationary point (if
    # feasible) or on one of the four closed edges, all enumerated below.
    linear = np.column_stack([origin_offset, p_slope + q_slope])
    constant = -q_slope
    material_corners = ((s0, t0), (s1, t0), (s1, t1), (s0, t1))
    polygon = [
        np.array([1.0 / (s + t), s / (s + t)], dtype=float)
        for s, t in material_corners
    ]

    def squared(parameter: np.ndarray) -> float:
        vector = constant + linear @ parameter
        return float(vector @ vector)

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

    candidates = [squared(vertex) for vertex in polygon]
    for start, end in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        parameter_direction = end - start
        spatial_start = constant + linear @ start
        spatial_direction = linear @ parameter_direction
        denominator = float(spatial_direction @ spatial_direction)
        fraction = 0.0
        if denominator > 0.0:
            fraction = float(
                np.clip(
                    -(spatial_start @ spatial_direction) / denominator,
                    0.0,
                    1.0,
                )
            )
        candidates.append(squared(start + fraction * parameter_direction))

    stationary = -np.linalg.lstsq(linear, constant, rcond=None)[0]
    if feasible(stationary):
        candidates.append(squared(stationary))
    return max(float(min(candidates)), 0.0)


def junction_socket_projective_opening_squared_reference(
    first_points: np.ndarray,
    first_rest_length: np.ndarray,
    first_side: str,
    second_points: np.ndarray,
    second_rest_length: np.ndarray,
    second_side: str,
    socket_length: float,
) -> float:
    """Reference projective opening over every fixed material cell pair."""

    first_breakpoints = socket_material_breakpoints_reference(
        first_rest_length, first_side, socket_length
    )
    second_breakpoints = socket_material_breakpoints_reference(
        second_rest_length, second_side, socket_length
    )
    minimum = float("inf")
    for first_left, first_right in zip(
        first_breakpoints[:-1], first_breakpoints[1:], strict=True
    ):
        first_start, _ = material_point_from_joint_reference(
            first_points, first_rest_length, first_side, float(first_left)
        )
        first_end, _ = material_point_from_joint_reference(
            first_points, first_rest_length, first_side, float(first_right)
        )
        for second_left, second_right in zip(
            second_breakpoints[:-1], second_breakpoints[1:], strict=True
        ):
            second_start, _ = material_point_from_joint_reference(
                second_points, second_rest_length, second_side, float(second_left)
            )
            second_end, _ = material_point_from_joint_reference(
                second_points, second_rest_length, second_side, float(second_right)
            )
            minimum = min(
                minimum,
                minimum_projective_opening_squared_on_material_cell_reference(
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


def _bob_rod_margins_reference(
    model: HighFidelityModel,
    branch_positions: dict[str, np.ndarray],
    bob_position: np.ndarray,
) -> tuple[float, float, float, float]:
    margins: list[float] = []
    material_extent = float("inf")
    radial_monotonicity = float("inf")
    cut_clearance = float("inf")
    for name, points in branch_positions.items():
        branch = model.branches[name]
        diameter = branch.diameter
        if name == "lower":
            required_radius = (
                model.bob_contact_radius
                + 0.5 * diameter
                + model.minimum_clearance
            )
            socket_length = required_radius
            total_material_length = float(np.sum(branch.segment_rest_length))
            material_extent = min(
                material_extent, total_material_length - socket_length
            )
            if socket_length >= total_material_length:
                continue
            checked = material_segments_outside_socket_reference(
                points, branch.segment_rest_length, "end", socket_length
            )
            breakpoints = socket_material_breakpoints_reference(
                branch.segment_rest_length, "end", socket_length
            )
            for left, right in zip(
                breakpoints[:-1], breakpoints[1:], strict=True
            ):
                start, _ = material_point_from_joint_reference(
                    points, branch.segment_rest_length, "end", float(left)
                )
                end, _ = material_point_from_joint_reference(
                    points, branch.segment_rest_length, "end", float(right)
                )
                radial = start - bob_position
                increment = end - start
                radial_monotonicity = min(
                    radial_monotonicity, float(radial @ increment)
                )
            boundary, _ = material_point_from_joint_reference(
                points, branch.segment_rest_length, "end", socket_length
            )
            cut_clearance = min(
                cut_clearance,
                float(np.linalg.norm(boundary - bob_position)) - required_radius,
            )
        else:
            checked = [
                (
                    points[index],
                    points[index + 1],
                    (index, index, 0.0),
                    (index + 1, index + 1, 0.0),
                )
                for index in range(points.shape[0] - 1)
            ]
        for start, end, _, _ in checked:
            distance = point_segment_distance_reference(
                bob_position, start, end
            )
            margins.append(distance - model.bob_contact_radius - 0.5 * diameter)
    return (
        min(margins) if margins else float("inf"),
        material_extent,
        radial_monotonicity,
        cut_clearance,
    )


def _rod_rod_margins_reference(
    model: HighFidelityModel, branch_positions: dict[str, np.ndarray]
) -> tuple[float, float, float, float]:
    minimum = float("inf")
    junction_material_extent = float("inf")
    junction_projective_opening = float("inf")
    junction_cut_clearance = float("inf")
    for name, points in branch_positions.items():
        branch = model.branches[name]
        material_nodes = np.concatenate(
            [[0.0], np.cumsum(branch.segment_rest_length)]
        )
        local_neighbourhood = 1.01 * (
            branch.diameter + model.minimum_clearance
        )
        segment_count = points.shape[0] - 1
        for first in range(segment_count):
            for second in range(first + 1, segment_count):
                distance = materially_separated_segment_distance_reference(
                    points[first],
                    points[first + 1],
                    points[second],
                    points[second + 1],
                    first_material_start=float(material_nodes[first]),
                    first_material_end=float(material_nodes[first + 1]),
                    second_material_start=float(material_nodes[second]),
                    second_material_end=float(material_nodes[second + 1]),
                    minimum_material_separation=local_neighbourhood,
                )
                minimum = min(minimum, distance - branch.diameter)

    branch_items = list(branch_positions.items())
    for first_branch_index, (name_a, points_a) in enumerate(branch_items):
        branch_a = model.branches[name_a]
        side_a = "start" if branch_a.start_kind == "junction" else "end"
        for name_b, points_b in branch_items[first_branch_index + 1 :]:
            branch_b = model.branches[name_b]
            side_b = "start" if branch_b.start_kind == "junction" else "end"
            required_separation = (
                0.5 * (branch_a.diameter + branch_b.diameter)
                + model.minimum_clearance
            )
            socket_length = 2.0 * required_separation
            active_a = material_segments_outside_socket_reference(
                points_a, branch_a.segment_rest_length, side_a, socket_length
            )
            active_b = material_segments_outside_socket_reference(
                points_b, branch_b.segment_rest_length, side_b, socket_length
            )
            junction_material_extent = min(
                junction_material_extent,
                float(np.sum(branch_a.segment_rest_length)) - socket_length,
                float(np.sum(branch_b.segment_rest_length)) - socket_length,
            )
            if not active_a or not active_b:
                continue
            opening_squared = junction_socket_projective_opening_squared_reference(
                points_a,
                branch_a.segment_rest_length,
                side_a,
                points_b,
                branch_b.segment_rest_length,
                side_b,
                socket_length,
            )
            registered_opening_squared = (
                required_separation / (2.0 * socket_length)
            ) ** 2
            junction_projective_opening = min(
                junction_projective_opening,
                opening_squared - registered_opening_squared,
            )
            boundary_a, _ = material_point_from_joint_reference(
                points_a, branch_a.segment_rest_length, side_a, socket_length
            )
            boundary_b, _ = material_point_from_joint_reference(
                points_b, branch_b.segment_rest_length, side_b, socket_length
            )
            junction_cut_clearance = min(
                junction_cut_clearance,
                float(np.linalg.norm(boundary_a - boundary_b))
                - required_separation,
            )
            all_a = [
                (
                    points_a[index],
                    points_a[index + 1],
                    (index, index, 0.0),
                    (index + 1, index + 1, 0.0),
                )
                for index in range(points_a.shape[0] - 1)
            ]
            all_b = [
                (
                    points_b[index],
                    points_b[index + 1],
                    (index, index, 0.0),
                    (index + 1, index + 1, 0.0),
                )
                for index in range(points_b.shape[0] - 1)
            ]
            for first_segments, second_segments in (
                (active_a, all_b),
                (all_a, active_b),
            ):
                for start_a, end_a, _, _ in first_segments:
                    for start_b, end_b, _, _ in second_segments:
                        minimum = min(
                            minimum,
                            segment_segment_distance_reference(
                                start_a, end_a, start_b, end_b
                            )
                            - 0.5 * (branch_a.diameter + branch_b.diameter),
                        )
    return (
        minimum,
        junction_material_extent,
        junction_projective_opening,
        junction_cut_clearance,
    )


def _branch_aerodynamics_reference(
    model: HighFidelityModel,
    branch: RodBranch,
    points: np.ndarray,
    particle_velocities: np.ndarray,
    particle_force: np.ndarray,
) -> tuple[float, float, float]:
    dissipation = 0.0
    air_work = 0.0
    power_roundoff_scale = 0.0
    if not branch.drag_enabled:
        return dissipation, air_work, power_roundoff_scale
    for local_bead, particle_index in enumerate(branch.bead_indices, start=1):
        material_tangent = points[local_bead + 1] - points[local_bead - 1]
        chord_length = float(np.linalg.norm(material_tangent))
        if chord_length <= model.geometry_singularity_floor:
            raise FloatingPointError("Degenerate aerodynamic chord in reference kernel.")
        material_tangent /= chord_length
        relative = particle_velocities[particle_index] - model.air_velocity
        tangential = float(relative @ material_tangent) * material_tangent
        normal = relative - tangential
        normal_speed = float(np.linalg.norm(normal))
        tangential_speed = float(np.linalg.norm(tangential))
        normal_quadratic = (
            0.5
            * model.air_density
            * branch.drag_cd_normal
            * branch.diameter
            * branch.cell_length
        )
        tangential_quadratic = (
            0.5
            * model.air_density
            * branch.drag_cd_tangent
            * branch.diameter
            * branch.cell_length
        )
        normal_linear = branch.drag_linear_normal_per_length * branch.cell_length
        tangential_linear = branch.drag_linear_tangent_per_length * branch.cell_length
        force = (
            -normal_quadratic * normal_speed * normal
            - tangential_quadratic * tangential_speed * tangential
            - normal_linear * normal
            - tangential_linear * tangential
        )
        particle_force[particle_index] += force
        relative_power = float(force @ relative)
        dissipation -= relative_power
        power_roundoff_scale += float(
            np.sum(np.abs(force * relative))
        )
        air_work += float(force @ model.air_velocity)
    return float(dissipation), float(air_work), float(power_roundoff_scale)


def evaluate_reference(
    model: HighFidelityModel,
    time: float,
    particle_positions: np.ndarray,
    particle_velocities: np.ndarray,
    bob_position: np.ndarray,
    bob_velocity: np.ndarray,
    quaternion: np.ndarray,
    angular_velocity: np.ndarray,
    *,
    include_aero: bool = True,
    compute_contact: bool = True,
) -> ReferenceSnapshot:
    """Rebuild one HF state without invoking a production dynamics oracle."""

    positions = np.asarray(particle_positions, dtype=float)
    velocities = np.asarray(particle_velocities, dtype=float)
    bob = np.asarray(bob_position, dtype=float)
    bob_v = np.asarray(bob_velocity, dtype=float)
    omega = np.asarray(angular_velocity, dtype=float)
    unit_quaternion = normalize_quaternion_reference(quaternion)
    particle_force = model.particle_mass[:, None] * model.gravity[None, :]
    bob_force = model.bob_mass * model.gravity + model.bob_buoyancy
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
    axial_power_roundoff_scale = 0.0
    aero_power_roundoff_scale = 0.0
    air_work = 0.0
    minimum_segment_length = float("inf")
    minimum_bending_turn_clearance = float("inf")
    minimum_aerodynamic_chord_length = float("inf")

    for branch in model.branches.values():
        start_p, start_v, start_arm = _endpoint_state_reference(
            model,
            branch.start_kind,
            float(time),
            positions,
            velocities,
            bob,
            bob_v,
            unit_quaternion,
            omega,
        )
        end_p, end_v, end_arm = _endpoint_state_reference(
            model,
            branch.end_kind,
            float(time),
            positions,
            velocities,
            bob,
            bob_v,
            unit_quaternion,
            omega,
        )
        points = np.vstack([start_p, positions[branch.bead_indices], end_p])
        point_velocities = np.vstack([start_v, velocities[branch.bead_indices], end_v])
        local_force = np.zeros_like(points)
        segment = np.diff(points, axis=0)
        segment_length = np.sqrt(np.einsum("ij,ij->i", segment, segment))
        minimum_segment_length = min(minimum_segment_length, float(np.min(segment_length)))
        if np.any(segment_length <= model.geometry_singularity_floor):
            raise FloatingPointError("Collapsed segment in independent HF reference kernel.")
        tangent = segment / segment_length[:, None]
        minimum_bending_turn_clearance = min(
            minimum_bending_turn_clearance,
            float(np.min(1.0 + np.einsum("ij,ij->i", tangent[:-1], tangent[1:]))),
        )
        minimum_aerodynamic_chord_length = min(
            minimum_aerodynamic_chord_length,
            float(np.min(np.linalg.norm(points[2:] - points[:-2], axis=1))),
        )
        extension_rate = np.einsum(
            "ij,ij->i", np.diff(point_velocities, axis=0), tangent
        )
        extension = segment_length - branch.segment_rest_length
        stiffness = branch.ea / branch.segment_rest_length
        viscosity = branch.eta_a / branch.segment_rest_length
        trial_tension = stiffness * extension + viscosity * extension_rate
        unilateral_active = (extension > 0.0) & (trial_tension > 0.0)
        unilateral_tension = np.where(unilateral_active, trial_tension, 0.0)
        compression_alpha = float(model.compression_regularization_scale)
        # Registered production law: alpha=1 is the two-sided KV rod; alpha=0
        # is the exact tension-only limit.  Intermediate alpha is used only by
        # the explicitly OUT_OF_SCOPE controlled-limit study.
        signed_axial_force = (
            (1.0 - compression_alpha) * unilateral_tension
            + compression_alpha * trial_tension
        )
        tension = np.maximum(signed_axial_force, 0.0)
        axial_force = signed_axial_force[:, None] * tangent
        local_force[:-1] += axial_force
        local_force[1:] -= axial_force

        positive_extension = np.maximum(extension, 0.0)
        unilateral_energy = 0.5 * stiffness * positive_extension**2
        bilateral_energy = 0.5 * stiffness * extension**2
        axial_energy += float(
            np.sum(
                (1.0 - compression_alpha) * unilateral_energy
                + compression_alpha * bilateral_energy
            )
        )
        unilateral_storage_rate = np.where(
            extension > 0.0,
            stiffness * extension * extension_rate,
            0.0,
        )
        bilateral_storage_rate = stiffness * extension * extension_rate
        storage_rate = (
            (1.0 - compression_alpha) * unilateral_storage_rate
            + compression_alpha * bilateral_storage_rate
        )
        axial_power = signed_axial_force * extension_rate
        axial_dissipation += float(np.sum(axial_power - storage_rate))
        axial_power_roundoff_scale += float(
            np.sum(np.abs(axial_power) + np.abs(storage_rate))
        )

        bend_energy, bend_force = bending_energy_forces_reference(
            points, branch.segment_rest_length, branch.ei
        )
        bending_energy += bend_energy
        local_force += bend_force
        particle_force[branch.bead_indices] += local_force[1:-1]
        _apply_endpoint_force(
            branch.start_kind,
            local_force[0],
            particle_force=particle_force,
            junction_index=model.junction_index,
            bob_force=bob_force,
            bob_torque=bob_torque,
            support_force=support_force,
            bob_arm=start_arm,
        )
        _apply_endpoint_force(
            branch.end_kind,
            local_force[-1],
            particle_force=particle_force,
            junction_index=model.junction_index,
            bob_force=bob_force,
            bob_torque=bob_torque,
            support_force=support_force,
            bob_arm=end_arm,
        )
        if include_aero:
            (
                branch_dissipation,
                branch_air_work,
                branch_power_scale,
            ) = _branch_aerodynamics_reference(
                model, branch, points, velocities, particle_force
            )
            aero_dissipation += branch_dissipation
            air_work += branch_air_work
            aero_power_roundoff_scale += branch_power_scale
        branch_positions[branch.name] = points
        branch_velocities[branch.name] = point_velocities
        branch_axial_force[branch.name] = signed_axial_force
        branch_tension[branch.name] = tension

    if include_aero and model.junction_drag_linear > 0.0:
        relative = velocities[model.junction_index] - model.air_velocity
        force = -model.junction_drag_linear * relative
        particle_force[model.junction_index] += force
        aero_dissipation -= float(force @ relative)
        aero_power_roundoff_scale += float(np.sum(np.abs(force * relative)))
        air_work += float(force @ model.air_velocity)

    if include_aero and model.cfg.bob.drag.enabled:
        relative = bob_v - model.air_velocity
        speed = float(np.linalg.norm(relative))
        quadratic = (
            0.5 * model.air_density * model.bob_cd * np.pi * model.bob_radius**2
        )
        force = -quadratic * speed * relative - model.bob_linear_drag * relative
        bob_force += force
        aero_dissipation -= float(force @ relative)
        aero_power_roundoff_scale += float(np.sum(np.abs(force * relative)))
        air_work += float(force @ model.air_velocity)

    support_work = 0.0
    for name, force_on_support in support_force.items():
        _, support_velocity, _ = model.support_motion[name].state(float(time))
        support_work -= float(force_on_support @ support_velocity)

    guard_margins = {
        "MINIMUM_SEGMENT_LENGTH": minimum_segment_length - model.length_guard,
        "BENDING_TURN_CLEARANCE": (
            minimum_bending_turn_clearance - model.bending_turn_clearance_floor
        ),
        "AERODYNAMIC_CHORD_LENGTH": (
            minimum_aerodynamic_chord_length - model.aerodynamic_chord_guard
        ),
    }
    if model.contact_guard_enabled and compute_contact:
        (
            bob_rod,
            bob_socket_material_extent,
            bob_socket_radial_monotonicity,
            bob_socket_cut_clearance,
        ) = _bob_rod_margins_reference(
            model, branch_positions, bob
        )
        (
            rod_rod,
            junction_socket_material_extent,
            junction_socket_projective_opening,
            junction_socket_cut_clearance,
        ) = _rod_rod_margins_reference(
            model, branch_positions
        )
        guard_margins.update(
            {
                "BOB_ROD_CLEARANCE": bob_rod - model.minimum_clearance,
                "ROD_SELF_CLEARANCE": rod_rod - model.minimum_clearance,
                "BOB_SOCKET_MATERIAL_EXTENT": bob_socket_material_extent,
                "BOB_SOCKET_RADIAL_MONOTONICITY": (
                    bob_socket_radial_monotonicity
                ),
                "BOB_SOCKET_CUT_CLEARANCE": bob_socket_cut_clearance,
                "JUNCTION_SOCKET_MATERIAL_EXTENT": (
                    junction_socket_material_extent
                ),
                "JUNCTION_SOCKET_PROJECTIVE_OPENING": (
                    junction_socket_projective_opening
                ),
                "JUNCTION_SOCKET_CUT_CLEARANCE": (
                    junction_socket_cut_clearance
                ),
            }
        )
    elif compute_contact:
        # The guard vocabulary is frozen by ``contact_guard_enabled``.  Do not
        # manufacture infinite public components when the guard is disabled.
        pass

    kinetic_particles = 0.5 * float(
        np.sum(model.particle_mass[:, None] * velocities**2)
    )
    kinetic_bob_translation = 0.5 * model.bob_mass * float(bob_v @ bob_v)
    kinetic_bob_rotation = 0.5 * model.bob_inertia * float(omega @ omega)
    gravitational = -float(
        np.sum(model.particle_mass[:, None] * positions * model.gravity[None, :])
    ) - model.bob_mass * float(bob @ model.gravity)
    gravitational -= float(bob @ model.bob_buoyancy)
    mechanical = (
        kinetic_particles
        + kinetic_bob_translation
        + kinetic_bob_rotation
        + gravitational
        + axial_energy
        + bending_energy
    )
    return ReferenceSnapshot(
        particle_force=particle_force,
        bob_force=bob_force,
        bob_torque=bob_torque,
        support_force=support_force,
        branch_positions=branch_positions,
        branch_velocities=branch_velocities,
        branch_axial_force=branch_axial_force,
        branch_tension=branch_tension,
        kinetic_particles=kinetic_particles,
        kinetic_bob_translation=kinetic_bob_translation,
        kinetic_bob_rotation=kinetic_bob_rotation,
        gravitational=gravitational,
        axial_energy=float(axial_energy),
        bending_energy=float(bending_energy),
        mechanical_energy=float(mechanical),
        axial_dissipation_rate=float(axial_dissipation),
        aero_dissipation_rate=float(aero_dissipation),
        axial_power_roundoff_scale=float(axial_power_roundoff_scale),
        aero_power_roundoff_scale=float(aero_power_roundoff_scale),
        air_work_rate=float(air_work),
        support_work_rate=float(support_work),
        guard_margins=guard_margins,
    )


def reference_rhs(model: HighFidelityModel, time: float, state: np.ndarray) -> np.ndarray:
    """Independent first-order dynamics used by accepted-step reconstruction."""

    particles, bob, quaternion, velocities, bob_v, omega = unpack_reference_state(
        model, state
    )
    snapshot = evaluate_reference(
        model,
        float(time),
        particles,
        velocities,
        bob,
        bob_v,
        quaternion,
        omega,
        compute_contact=False,
    )
    q = np.asarray(quaternion, dtype=float)
    q0 = float(q[0])
    qv = q[1:]
    quaternion_rate = 0.5 * np.concatenate(
        [[-float(omega @ qv)], q0 * omega + np.cross(omega, qv)]
    )
    quaternion_rate += (
        model.quaternion_stabilization_rate
        * (1.0 - float(q @ q))
        * q
    )
    return pack_reference_state(
        velocities,
        bob_v,
        quaternion_rate,
        snapshot.particle_force / model.particle_mass[:, None],
        snapshot.bob_force / model.bob_mass,
        snapshot.bob_torque / model.bob_inertia,
    )


def reference_snapshot_from_state(
    model: HighFidelityModel,
    time: float,
    state: np.ndarray,
    *,
    include_aero: bool = True,
    compute_contact: bool = True,
) -> ReferenceSnapshot:
    particles, bob, quaternion, velocities, bob_v, omega = unpack_reference_state(
        model, state
    )
    return evaluate_reference(
        model,
        time,
        particles,
        velocities,
        bob,
        bob_v,
        quaternion,
        omega,
        include_aero=include_aero,
        compute_contact=compute_contact,
    )


def cumulative_trapezoid_reference(time: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Cumulative trapezoid implemented locally for ledger independence."""

    t = np.asarray(time, dtype=float)
    y = np.asarray(values, dtype=float)
    if t.ndim != 1 or y.shape != t.shape or t.size < 1 or np.any(np.diff(t) <= 0.0):
        raise ValueError("Invalid time series for reference cumulative integral.")
    if t.size == 1:
        return np.zeros(1, dtype=float)
    increments = 0.5 * (y[:-1] + y[1:]) * np.diff(t)
    return np.concatenate([np.zeros(1, dtype=float), np.cumsum(increments)])


def origin_invariant_energy_scale(model: HighFidelityModel) -> float:
    """Return a physical energy scale unaffected by coordinate-origin shifts."""

    return max(
        float(model.force_scale) * float(model.characteristic_length),
        np.finfo(float).tiny,
    )

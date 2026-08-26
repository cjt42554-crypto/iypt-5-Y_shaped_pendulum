"""Post-solve-only material-domain clearance audit for P2."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ypendulum_hfv2.statics.assembly import StaticAssembly, StaticEvaluation
from ypendulum_hfv2.topology import MaterialSegment


@dataclass(frozen=True)
class ClearanceAudit:
    rod_rod_centerline_distance_m: float
    rod_rod_net_clearance_m: float
    bob_rod_centerline_distance_m: float
    bob_rod_net_clearance_m: float
    minimum_net_clearance_m: float
    evaluated_rod_pair_domains: int
    evaluated_bob_segment_domains: int


def point_segment_distance(
    point: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
) -> float:
    direction = np.asarray(end, dtype=float) - np.asarray(start, dtype=float)
    squared = float(direction @ direction)
    if squared <= np.finfo(float).tiny:
        return float(np.linalg.norm(np.asarray(point, dtype=float) - start))
    parameter = float((np.asarray(point, dtype=float) - start) @ direction / squared)
    parameter = float(np.clip(parameter, 0.0, 1.0))
    closest = np.asarray(start, dtype=float) + parameter * direction
    return float(np.linalg.norm(np.asarray(point, dtype=float) - closest))


def segment_segment_distance(
    first_start: np.ndarray,
    first_end: np.ndarray,
    second_start: np.ndarray,
    second_end: np.ndarray,
) -> float:
    p0 = np.asarray(first_start, dtype=float)
    p1 = np.asarray(first_end, dtype=float)
    q0 = np.asarray(second_start, dtype=float)
    q1 = np.asarray(second_end, dtype=float)
    u = p1 - p0
    v = q1 - q0
    candidates = [
        point_segment_distance(p0, q0, q1),
        point_segment_distance(p1, q0, q1),
        point_segment_distance(q0, p0, p1),
        point_segment_distance(q1, p0, p1),
    ]
    normal = np.cross(u, v)
    normal_squared = float(normal @ normal)
    if normal_squared > 0.0:
        offset = q0 - p0
        first_parameter = float(np.cross(offset, v) @ normal / normal_squared)
        second_parameter = float(np.cross(offset, u) @ normal / normal_squared)
        tolerance = 64.0 * np.finfo(float).eps
        if (
            -tolerance <= first_parameter <= 1.0 + tolerance
            and -tolerance <= second_parameter <= 1.0 + tolerance
        ):
            candidates.append(
                float(
                    np.linalg.norm(
                        p0
                        + np.clip(first_parameter, 0.0, 1.0) * u
                        - q0
                        - np.clip(second_parameter, 0.0, 1.0) * v
                    )
                )
            )
    return float(min(candidates))


def materially_separated_segment_distance(
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
    first_span = float(first_material_end - first_material_start)
    second_span = float(second_material_end - second_material_start)
    offset = float(
        minimum_material_separation - (second_material_start - first_material_start)
    )

    def feasible(parameter: np.ndarray) -> float:
        return float(
            parameter[1] * second_span - parameter[0] * first_span - offset
        )

    polygon = [
        np.array([0.0, 0.0]),
        np.array([1.0, 0.0]),
        np.array([1.0, 1.0]),
        np.array([0.0, 1.0]),
    ]
    tolerance = 128.0 * np.finfo(float).eps * max(
        first_span,
        second_span,
        abs(offset),
        np.finfo(float).tiny,
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
                np.clip(-(spatial_start @ spatial_direction) / denominator, 0.0, 1.0)
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


def _segment_points(
    assembly: StaticAssembly,
    evaluation: StaticEvaluation,
    segment: MaterialSegment,
) -> tuple[np.ndarray, np.ndarray]:
    return (
        evaluation.node_positions[assembly.topology.node_index(segment.start_node)],
        evaluation.node_positions[assembly.topology.node_index(segment.end_node)],
    )


def _crop_away_from_endpoint(
    assembly: StaticAssembly,
    evaluation: StaticEvaluation,
    segment: MaterialSegment,
    endpoint_node: str,
    material_exclusion: float,
) -> tuple[np.ndarray, np.ndarray] | None:
    branch = assembly.topology.branch_segments(segment.branch_id)
    branch_start = branch[0].material_start
    branch_end = branch[-1].material_end
    branch_start_node = branch[0].start_node
    branch_end_node = branch[-1].end_node
    allowed_start = segment.material_start
    allowed_end = segment.material_end
    if endpoint_node == branch_start_node:
        allowed_start = max(allowed_start, branch_start + material_exclusion)
    elif endpoint_node == branch_end_node:
        allowed_end = min(allowed_end, branch_end - material_exclusion)
    else:
        raise ValueError("Clearance socket node must be a branch endpoint.")
    if allowed_end <= allowed_start:
        return None
    start, end = _segment_points(assembly, evaluation, segment)
    span = segment.material_end - segment.material_start
    first_fraction = (allowed_start - segment.material_start) / span
    second_fraction = (allowed_end - segment.material_start) / span
    direction = end - start
    return start + first_fraction * direction, start + second_fraction * direction


def audit_clearance(
    assembly: StaticAssembly,
    evaluation: StaticEvaluation,
    *,
    cable_radius_m: float,
    bob_radius_m: float,
    same_branch_material_exclusion_m: float,
    junction_socket_material_exclusion_m: float,
    bob_socket_material_exclusion_m: float,
) -> ClearanceAudit:
    segments = assembly.topology.segments
    rod_distances: list[float] = []
    for first_index, first in enumerate(segments):
        first_points = _segment_points(assembly, evaluation, first)
        for second in segments[first_index:]:
            second_points = _segment_points(assembly, evaluation, second)
            if first.branch_id == second.branch_id:
                if first.material_start <= second.material_start:
                    distance = materially_separated_segment_distance(
                        *first_points,
                        *second_points,
                        first_material_start=first.material_start,
                        first_material_end=first.material_end,
                        second_material_start=second.material_start,
                        second_material_end=second.material_end,
                        minimum_material_separation=same_branch_material_exclusion_m,
                    )
                else:
                    distance = materially_separated_segment_distance(
                        *second_points,
                        *first_points,
                        first_material_start=second.material_start,
                        first_material_end=second.material_end,
                        second_material_start=first.material_start,
                        second_material_end=first.material_end,
                        minimum_material_separation=same_branch_material_exclusion_m,
                    )
            else:
                first_nodes = set(assembly.branch_node_ids(first.branch_id))
                second_nodes = set(assembly.branch_node_ids(second.branch_id))
                shared = first_nodes & second_nodes
                if len(shared) > 1:
                    raise ValueError("P2 clearance audit does not accept multiply shared branches.")
                if shared:
                    junction = next(iter(shared))
                    first_cropped = _crop_away_from_endpoint(
                        assembly,
                        evaluation,
                        first,
                        junction,
                        junction_socket_material_exclusion_m,
                    )
                    second_cropped = _crop_away_from_endpoint(
                        assembly,
                        evaluation,
                        second,
                        junction,
                        junction_socket_material_exclusion_m,
                    )
                    if first_cropped is None or second_cropped is None:
                        continue
                    distance = segment_segment_distance(*first_cropped, *second_cropped)
                else:
                    distance = segment_segment_distance(*first_points, *second_points)
            if np.isfinite(distance):
                rod_distances.append(float(distance))

    attachment_id = next(
        node.node_id for node in assembly.topology.nodes if node.kind == "bob_attachment"
    )
    bob_distances: list[float] = []
    for segment in segments:
        branch_nodes = assembly.branch_node_ids(segment.branch_id)
        if attachment_id in branch_nodes:
            cropped = _crop_away_from_endpoint(
                assembly,
                evaluation,
                segment,
                attachment_id,
                bob_socket_material_exclusion_m,
            )
            if cropped is None:
                continue
            points = cropped
        else:
            points = _segment_points(assembly, evaluation, segment)
        bob_distances.append(point_segment_distance(evaluation.bob_position, *points))
    if not rod_distances or not bob_distances:
        raise ValueError("Clearance audit found no nonlocal rod or bob domains.")
    rod_distance = float(min(rod_distances))
    bob_distance = float(min(bob_distances))
    rod_net = rod_distance - 2.0 * cable_radius_m
    bob_net = bob_distance - bob_radius_m - cable_radius_m
    return ClearanceAudit(
        rod_rod_centerline_distance_m=rod_distance,
        rod_rod_net_clearance_m=rod_net,
        bob_rod_centerline_distance_m=bob_distance,
        bob_rod_net_clearance_m=bob_net,
        minimum_net_clearance_m=min(rod_net, bob_net),
        evaluated_rod_pair_domains=len(rod_distances),
        evaluated_bob_segment_domains=len(bob_distances),
    )

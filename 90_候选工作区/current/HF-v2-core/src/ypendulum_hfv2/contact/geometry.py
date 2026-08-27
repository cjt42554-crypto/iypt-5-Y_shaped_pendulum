"""Closest-point witnesses on frozen material parameter domains."""

from __future__ import annotations

import numpy as np

from .contracts import (
    BobSegmentConstraint,
    ContactWitness,
    ConvexParameterPolygon,
    DegenerateContactGeometry,
    GeometryTolerances,
    SegmentPairConstraint,
)


def _signed_area(vertices: np.ndarray) -> float:
    return 0.5 * float(
        np.sum(
            vertices[:, 0] * np.roll(vertices[:, 1], -1)
            - vertices[:, 1] * np.roll(vertices[:, 0], -1)
        )
    )


def _canonical_vertices(vertices: list[np.ndarray], tolerances: GeometryTolerances) -> np.ndarray | None:
    if not vertices:
        return None
    merged: list[np.ndarray] = []
    for vertex in vertices:
        point = np.asarray(vertex, dtype=float)
        if not merged or float(np.linalg.norm(point - merged[-1], ord=np.inf)) > tolerances.parameter_merge_absolute:
            merged.append(point)
    if len(merged) > 1 and float(np.linalg.norm(merged[0] - merged[-1], ord=np.inf)) <= tolerances.parameter_merge_absolute:
        merged.pop()
    if len(merged) < 3:
        return None
    array = np.vstack(merged)
    area = _signed_area(array)
    if abs(area) <= tolerances.polygon_area_absolute:
        return None
    if area < 0.0:
        array = array[::-1]
    first = min(range(array.shape[0]), key=lambda index: (float(array[index, 0]), float(array[index, 1])))
    return np.roll(array, -first, axis=0)


def full_parameter_polygon() -> ConvexParameterPolygon:
    return ConvexParameterPolygon(
        np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    )


def clip_parameter_polygon(
    polygon: ConvexParameterPolygon,
    *,
    first_coefficient: float,
    second_coefficient: float,
    constant: float,
    tolerances: GeometryTolerances,
) -> ConvexParameterPolygon | None:
    """Clip by ``a*xi+b*eta+c >= 0`` with deterministic vertex ordering."""

    vertices = [np.array(vertex, copy=True) for vertex in polygon.vertices]

    def value(point: np.ndarray) -> float:
        return float(first_coefficient * point[0] + second_coefficient * point[1] + constant)

    clipped: list[np.ndarray] = []
    for current, following in zip(vertices, vertices[1:] + vertices[:1], strict=True):
        current_value = value(current)
        following_value = value(following)
        current_inside = current_value >= -tolerances.polygon_halfspace_absolute
        following_inside = following_value >= -tolerances.polygon_halfspace_absolute
        if current_inside:
            clipped.append(current)
        if current_inside != following_inside:
            denominator = current_value - following_value
            if denominator == 0.0:
                raise DegenerateContactGeometry("Half-space clipping encountered an unresolved edge.")
            fraction = current_value / denominator
            clipped.append(current + fraction * (following - current))
    canonical = _canonical_vertices(clipped, tolerances)
    return None if canonical is None else ConvexParameterPolygon(canonical)


def _point_in_convex_polygon(
    point: np.ndarray,
    polygon: ConvexParameterPolygon,
    tolerance: float,
) -> bool:
    vertices = polygon.vertices
    edges = np.roll(vertices, -1, axis=0) - vertices
    offsets = point - vertices
    cross = edges[:, 0] * offsets[:, 1] - edges[:, 1] * offsets[:, 0]
    return bool(np.all(cross >= -tolerance))


def _candidate_clusters(
    candidates: list[tuple[np.ndarray, float, str]],
    tolerances: GeometryTolerances,
) -> tuple[np.ndarray, float, str, int]:
    minimum = min(value for _, value, _ in candidates)
    tie = max(
        tolerances.zero_witness_distance_m**2,
        abs(minimum) * tolerances.squared_distance_tie_relative,
    )
    tied = [(parameter, value, feature) for parameter, value, feature in candidates if value <= minimum + tie]
    clusters: list[list[tuple[np.ndarray, float, str]]] = []
    for candidate in tied:
        for cluster in clusters:
            if float(np.linalg.norm(candidate[0] - cluster[0][0], ord=np.inf)) <= tolerances.parameter_merge_absolute:
                cluster.append(candidate)
                break
        else:
            clusters.append([candidate])
    if len(clusters) != 1:
        raise DegenerateContactGeometry(
            f"Closest-point parameter is non-unique across {len(clusters)} separated minimizer clusters."
        )
    selected = min(clusters[0], key=lambda item: (item[1], float(item[0][0]), float(item[0][1])))
    return selected[0], selected[1], selected[2], len(clusters)


def closest_segment_pair_witness(
    first_start: np.ndarray,
    first_end: np.ndarray,
    second_start: np.ndarray,
    second_end: np.ndarray,
    constraint: SegmentPairConstraint,
    tolerances: GeometryTolerances,
) -> ContactWitness:
    p0 = np.asarray(first_start, dtype=float)
    p1 = np.asarray(first_end, dtype=float)
    q0 = np.asarray(second_start, dtype=float)
    q1 = np.asarray(second_end, dtype=float)
    if any(value.shape != (3,) or not np.all(np.isfinite(value)) for value in (p0, p1, q0, q1)):
        raise ValueError("Segment endpoints must be finite three-vectors.")
    first_direction = p1 - p0
    second_direction = q1 - q0
    if float(np.linalg.norm(first_direction)) <= tolerances.collapsed_segment_length_m:
        raise DegenerateContactGeometry("First registered contact segment is collapsed.")
    if float(np.linalg.norm(second_direction)) <= tolerances.collapsed_segment_length_m:
        raise DegenerateContactGeometry("Second registered contact segment is collapsed.")
    offset = p0 - q0
    matrix = np.column_stack([first_direction, -second_direction])

    def squared(parameter: np.ndarray) -> float:
        delta = offset + matrix @ parameter
        return float(delta @ delta)

    candidates: list[tuple[np.ndarray, float, str]] = []
    for domain_index, domain in enumerate(constraint.parameter_domains):
        for vertex_index, vertex in enumerate(domain.vertices):
            candidates.append((np.array(vertex, copy=True), squared(vertex), f"domain_{domain_index}:vertex_{vertex_index}"))
        for edge_index, (start, end) in enumerate(
            zip(domain.vertices, np.roll(domain.vertices, -1, axis=0), strict=True)
        ):
            parameter_direction = end - start
            spatial_start = offset + matrix @ start
            spatial_direction = matrix @ parameter_direction
            denominator = float(spatial_direction @ spatial_direction)
            fraction = 0.0
            if denominator > 0.0:
                fraction = float(np.clip(-(spatial_start @ spatial_direction) / denominator, 0.0, 1.0))
            parameter = start + fraction * parameter_direction
            candidates.append((parameter, squared(parameter), f"domain_{domain_index}:edge_{edge_index}"))
        stationary = -np.linalg.lstsq(matrix, offset, rcond=None)[0]
        if _point_in_convex_polygon(stationary, domain, tolerances.polygon_halfspace_absolute):
            candidates.append((stationary, squared(stationary), f"domain_{domain_index}:interior"))
    parameter, squared_distance, feature, cluster_count = _candidate_clusters(candidates, tolerances)
    first_parameter = float(parameter[0])
    second_parameter = float(parameter[1])
    first_point = p0 + first_parameter * first_direction
    second_point = q0 + second_parameter * second_direction
    delta = first_point - second_point
    distance = float(np.sqrt(max(squared_distance, 0.0)))
    if distance <= tolerances.zero_witness_distance_m:
        raise DegenerateContactGeometry("Registered segment-pair witness has no resolvable normal.")
    normal = delta / distance
    gradients = np.vstack(
        [
            (1.0 - first_parameter) * normal,
            first_parameter * normal,
            -(1.0 - second_parameter) * normal,
            -second_parameter * normal,
        ]
    )
    margin = min(first_parameter, 1.0 - first_parameter, second_parameter, 1.0 - second_parameter)
    return ContactWitness(
        constraint_id=constraint.constraint_id,
        category=constraint.category,
        first_parameter=first_parameter,
        second_parameter=second_parameter,
        first_point_m=first_point,
        second_point_m=second_point,
        distance_m=distance,
        required_center_distance_m=constraint.required_center_distance_m,
        gap_m=distance - constraint.required_center_distance_m,
        normal_second_to_first=normal,
        object_ids=constraint.endpoint_node_ids,
        object_gap_gradients=gradients,
        active_feature=feature,
        competing_minimizer_count=cluster_count,
        unit_interval_parameter_margin=float(margin),
    )


def closest_bob_segment_witness(
    bob_center: np.ndarray,
    segment_start: np.ndarray,
    segment_end: np.ndarray,
    constraint: BobSegmentConstraint,
    tolerances: GeometryTolerances,
) -> ContactWitness:
    point = np.asarray(bob_center, dtype=float)
    start = np.asarray(segment_start, dtype=float)
    end = np.asarray(segment_end, dtype=float)
    if any(value.shape != (3,) or not np.all(np.isfinite(value)) for value in (point, start, end)):
        raise ValueError("Bob and segment geometry must contain finite three-vectors.")
    direction = end - start
    squared_length = float(direction @ direction)
    if float(np.sqrt(squared_length)) <= tolerances.collapsed_segment_length_m:
        raise DegenerateContactGeometry("Registered bob-contact segment is collapsed.")
    raw_parameter = float((point - start) @ direction / squared_length)
    parameter = float(np.clip(raw_parameter, constraint.parameter_min, constraint.parameter_max))
    closest = start + parameter * direction
    delta = point - closest
    distance = float(np.linalg.norm(delta))
    if distance <= tolerances.zero_witness_distance_m:
        raise DegenerateContactGeometry("Registered bob-segment witness has no resolvable normal.")
    normal = delta / distance
    gradients = np.vstack([normal, -(1.0 - parameter) * normal, -parameter * normal])
    if parameter == constraint.parameter_min:
        feature = "interval_min"
    elif parameter == constraint.parameter_max:
        feature = "interval_max"
    else:
        feature = "interval_interior"
    margin = min(parameter, 1.0 - parameter)
    return ContactWitness(
        constraint_id=constraint.constraint_id,
        category="bob_segment",
        first_parameter=None,
        second_parameter=parameter,
        first_point_m=point,
        second_point_m=closest,
        distance_m=distance,
        required_center_distance_m=constraint.required_center_distance_m,
        gap_m=distance - constraint.required_center_distance_m,
        normal_second_to_first=normal,
        object_ids=("__bob_center__", constraint.start_node, constraint.end_node),
        object_gap_gradients=gradients,
        active_feature=feature,
        competing_minimizer_count=1,
        unit_interval_parameter_margin=float(margin),
    )

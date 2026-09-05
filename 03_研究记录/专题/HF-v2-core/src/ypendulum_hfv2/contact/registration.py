"""Read-only mapping of the formal material registration to HF-v2 constraints."""

from __future__ import annotations

import numpy as np

from ypendulum_hfv2.topology import HFV2Topology, MaterialSegment

from .contracts import (
    BobSegmentConstraint,
    BobSocketRegistration,
    ContactGeometryError,
    ContactRegistry,
    ContactSurfaceSpec,
    GeometryTolerances,
    JunctionSocketRegistration,
    MaterialSocketRegistration,
    SegmentPairConstraint,
)
from .geometry import clip_parameter_polygon, full_parameter_polygon


def _branch_ids(topology: HFV2Topology) -> tuple[str, ...]:
    return tuple(dict.fromkeys(segment.branch_id for segment in topology.segments))


def _branch_endpoints(topology: HFV2Topology, branch_id: str) -> tuple[str, str]:
    segments = topology.branch_segments(branch_id)
    return segments[0].start_node, segments[-1].end_node


def _socket_side(topology: HFV2Topology, branch_id: str, endpoint_node_id: str) -> str:
    start, end = _branch_endpoints(topology, branch_id)
    if endpoint_node_id == start:
        return "start"
    if endpoint_node_id == end:
        return "end"
    raise ContactGeometryError("A material socket endpoint must be a branch endpoint.")


def _joint_distance_affine(
    topology: HFV2Topology,
    segment: MaterialSegment,
    endpoint_node_id: str,
) -> tuple[float, float]:
    branch = topology.branch_segments(segment.branch_id)
    branch_start = branch[0].material_start
    branch_end = branch[-1].material_end
    side = _socket_side(topology, segment.branch_id, endpoint_node_id)
    if side == "start":
        return segment.material_start - branch_start, segment.rest_length
    return branch_end - segment.material_start, -segment.rest_length


def _clip_joint_condition(
    polygon,
    *,
    affine: tuple[float, float],
    socket_length: float,
    coordinate: int,
    outside: bool,
    tolerances: GeometryTolerances,
):
    offset, slope = affine
    sign = 1.0 if outside else -1.0
    first = sign * slope if coordinate == 0 else 0.0
    second = sign * slope if coordinate == 1 else 0.0
    constant = sign * (offset - socket_length)
    return clip_parameter_polygon(
        polygon,
        first_coefficient=first,
        second_coefficient=second,
        constant=constant,
        tolerances=tolerances,
    )


def _same_branch_constraints(
    topology: HFV2Topology,
    surface: ContactSurfaceSpec,
    tolerances: GeometryTolerances,
) -> list[SegmentPairConstraint]:
    constraints: list[SegmentPairConstraint] = []
    for branch_id in _branch_ids(topology):
        segments = topology.branch_segments(branch_id)
        radius = surface.radius(branch_id)
        required = 2.0 * radius + surface.minimum_clearance_m
        minimum_separation = 1.01 * required
        for first_index, first in enumerate(segments):
            for second in segments[first_index + 1 :]:
                polygon = clip_parameter_polygon(
                    full_parameter_polygon(),
                    first_coefficient=-first.rest_length,
                    second_coefficient=second.rest_length,
                    constant=second.material_start - first.material_start - minimum_separation,
                    tolerances=tolerances,
                )
                if polygon is None:
                    continue
                full = polygon.vertices.shape == (4, 2) and np.allclose(
                    polygon.vertices,
                    full_parameter_polygon().vertices,
                    rtol=0.0,
                    atol=tolerances.parameter_merge_absolute,
                )
                category = "same_branch_full" if full else "same_branch_partial"
                constraints.append(
                    SegmentPairConstraint(
                        constraint_id=f"same:{branch_id}:{first.segment_id}|{second.segment_id}",
                        category=category,
                        first_branch_id=branch_id,
                        first_segment_id=first.segment_id,
                        first_start_node=first.start_node,
                        first_end_node=first.end_node,
                        second_branch_id=branch_id,
                        second_segment_id=second.segment_id,
                        second_start_node=second.start_node,
                        second_end_node=second.end_node,
                        required_center_distance_m=required,
                        parameter_domains=(polygon,),
                    )
                )
    return constraints


def _junction_constraints(
    topology: HFV2Topology,
    surface: ContactSurfaceSpec,
    tolerances: GeometryTolerances,
) -> tuple[list[SegmentPairConstraint], list[JunctionSocketRegistration]]:
    constraints: list[SegmentPairConstraint] = []
    registrations: list[JunctionSocketRegistration] = []
    branches = _branch_ids(topology)
    for first_index, first_branch in enumerate(branches):
        first_endpoints = set(_branch_endpoints(topology, first_branch))
        for second_branch in branches[first_index + 1 :]:
            shared = first_endpoints & set(_branch_endpoints(topology, second_branch))
            if len(shared) != 1:
                raise ContactGeometryError(
                    "Formal junction registration requires each branch pair to share exactly one endpoint."
                )
            shared_node = next(iter(shared))
            if topology.nodes[topology.node_index(shared_node)].kind == "bob_attachment":
                raise ContactGeometryError("A bob attachment cannot also define a junction socket.")
            required = (
                surface.radius(first_branch)
                + surface.radius(second_branch)
                + surface.minimum_clearance_m
            )
            socket_length = 2.0 * required
            first_socket = MaterialSocketRegistration(
                branch_id=first_branch,
                endpoint_node_id=shared_node,
                side=_socket_side(topology, first_branch, shared_node),
                socket_length_m=socket_length,
                total_material_length_m=topology.branch_rest_length(first_branch),
            )
            second_socket = MaterialSocketRegistration(
                branch_id=second_branch,
                endpoint_node_id=shared_node,
                side=_socket_side(topology, second_branch, shared_node),
                socket_length_m=socket_length,
                total_material_length_m=topology.branch_rest_length(second_branch),
            )
            registration_id = f"junction:{shared_node}:{first_branch}|{second_branch}"
            registrations.append(
                JunctionSocketRegistration(
                    registration_id=registration_id,
                    shared_node_id=shared_node,
                    first=first_socket,
                    second=second_socket,
                    required_center_distance_m=required,
                    registered_projective_opening_squared=(required / (2.0 * socket_length)) ** 2,
                )
            )
            for first_segment in topology.branch_segments(first_branch):
                first_affine = _joint_distance_affine(topology, first_segment, shared_node)
                for second_segment in topology.branch_segments(second_branch):
                    second_affine = _joint_distance_affine(topology, second_segment, shared_node)
                    domains = []
                    first_outside = _clip_joint_condition(
                        full_parameter_polygon(),
                        affine=first_affine,
                        socket_length=socket_length,
                        coordinate=0,
                        outside=True,
                        tolerances=tolerances,
                    )
                    if first_outside is not None:
                        domains.append(("first_outside", first_outside))
                    first_inside = _clip_joint_condition(
                        full_parameter_polygon(),
                        affine=first_affine,
                        socket_length=socket_length,
                        coordinate=0,
                        outside=False,
                        tolerances=tolerances,
                    )
                    if first_inside is not None:
                        second_outside = _clip_joint_condition(
                            first_inside,
                            affine=second_affine,
                            socket_length=socket_length,
                            coordinate=1,
                            outside=True,
                            tolerances=tolerances,
                        )
                        if second_outside is not None:
                            domains.append(("second_outside_first_inside", second_outside))
                    if not domains:
                        continue
                    for role, domain in domains:
                        constraints.append(
                            SegmentPairConstraint(
                                constraint_id=(
                                    f"junction:{shared_node}:{first_branch}:{first_segment.segment_id}"
                                    f"|{second_branch}:{second_segment.segment_id}:{role}"
                                ),
                                category="junction_socket",
                                first_branch_id=first_branch,
                                first_segment_id=first_segment.segment_id,
                                first_start_node=first_segment.start_node,
                                first_end_node=first_segment.end_node,
                                second_branch_id=second_branch,
                                second_segment_id=second_segment.segment_id,
                                second_start_node=second_segment.start_node,
                                second_end_node=second_segment.end_node,
                                required_center_distance_m=required,
                                parameter_domains=(domain,),
                                shared_node_id=shared_node,
                            )
                        )
    return constraints, registrations


def _active_interval_from_socket(
    topology: HFV2Topology,
    segment: MaterialSegment,
    attachment_node: str,
    socket_length: float,
) -> tuple[float, float] | None:
    offset, slope = _joint_distance_affine(topology, segment, attachment_node)
    endpoint_values = np.array([offset, offset + slope])
    if np.all(endpoint_values < socket_length):
        return None
    if np.all(endpoint_values >= socket_length):
        return 0.0, 1.0
    threshold = float((socket_length - offset) / slope)
    if slope > 0.0:
        return threshold, 1.0
    return 0.0, threshold


def _bob_constraints(
    topology: HFV2Topology,
    surface: ContactSurfaceSpec,
) -> tuple[list[BobSegmentConstraint], BobSocketRegistration]:
    attachment_node = next(node.node_id for node in topology.nodes if node.kind == "bob_attachment")
    attachment_branches = [
        branch_id
        for branch_id in _branch_ids(topology)
        if attachment_node in _branch_endpoints(topology, branch_id)
    ]
    if len(attachment_branches) != 1:
        raise ContactGeometryError("Exactly one material branch must terminate at the bob attachment.")
    attachment_branch = attachment_branches[0]
    bob_required = (
        surface.bob_contact_radius_m
        + surface.radius(attachment_branch)
        + surface.minimum_clearance_m
    )
    socket = MaterialSocketRegistration(
        branch_id=attachment_branch,
        endpoint_node_id=attachment_node,
        side=_socket_side(topology, attachment_branch, attachment_node),
        socket_length_m=bob_required,
        total_material_length_m=topology.branch_rest_length(attachment_branch),
    )
    registration = BobSocketRegistration(
        registration_id=f"bob_socket:{attachment_branch}:{attachment_node}",
        socket=socket,
        required_center_distance_m=bob_required,
    )
    constraints: list[BobSegmentConstraint] = []
    for branch_id in _branch_ids(topology):
        required = (
            surface.bob_contact_radius_m
            + surface.radius(branch_id)
            + surface.minimum_clearance_m
        )
        for segment in topology.branch_segments(branch_id):
            interval = (0.0, 1.0)
            if branch_id == attachment_branch:
                interval = _active_interval_from_socket(
                    topology,
                    segment,
                    attachment_node,
                    socket.socket_length_m,
                )
                if interval is None:
                    continue
            constraints.append(
                BobSegmentConstraint(
                    constraint_id=f"bob:{branch_id}:{segment.segment_id}",
                    branch_id=branch_id,
                    segment_id=segment.segment_id,
                    start_node=segment.start_node,
                    end_node=segment.end_node,
                    parameter_min=interval[0],
                    parameter_max=interval[1],
                    required_center_distance_m=required,
                )
            )
    return constraints, registration


def build_contact_registry(
    topology: HFV2Topology,
    surface: ContactSurfaceSpec,
    tolerances: GeometryTolerances,
) -> ContactRegistry:
    branches = _branch_ids(topology)
    if surface.branch_ids != branches:
        raise ValueError("Contact surface branch order must exactly match topology first appearance.")
    same = _same_branch_constraints(topology, surface, tolerances)
    junction, junction_sockets = _junction_constraints(topology, surface, tolerances)
    bob, bob_socket = _bob_constraints(topology, surface)
    return ContactRegistry(
        formal_registration_id=surface.formal_registration_id,
        surface=surface,
        segment_pair_constraints=tuple(same + junction),
        bob_segment_constraints=tuple(bob),
        junction_sockets=tuple(junction_sockets),
        bob_socket=bob_socket,
    )

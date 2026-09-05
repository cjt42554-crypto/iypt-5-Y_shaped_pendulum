"""Contact-identity-bound gaps and generalized Jacobian over the frozen P2 assembly."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

import numpy as np

from ypendulum_hfv2.contact.contracts import (
    ContactRegistry,
    ContactSurfaceSpec,
    ContactWitness,
    DegenerateContactGeometry,
    GeometryTolerances,
    JunctionSocketRegistration,
    MaterialSocketRegistration,
)
from ypendulum_hfv2.contact.geometry import (
    closest_bob_segment_witness,
    closest_segment_pair_witness,
)
from ypendulum_hfv2.contact.registration import build_contact_registry
from ypendulum_hfv2.rigid.rotation import hat
from ypendulum_hfv2.statics.assembly import StaticAssembly, StaticEvaluation
from ypendulum_hfv2.statics.contracts import StaticSeed

CONTACT_MODEL_ID = "HFV2-DISCRETE-CORD-RIGID-BOB-0.3-CONTACT-CANDIDATE"


def _readonly(value: np.ndarray, ndim: int, name: str) -> np.ndarray:
    array = np.array(value, dtype=float, copy=True)
    if array.ndim != ndim or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be a finite {ndim}-dimensional array.")
    array.setflags(write=False)
    return array


def _right_jacobian_so3(rotation_vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(rotation_vector, dtype=float)
    squared = float(vector @ vector)
    angle = float(np.sqrt(squared))
    generator = hat(vector)
    if angle < 1.0e-6:
        angle_fourth = squared**2
        first = 0.5 - squared / 24.0 + angle_fourth / 720.0
        second = 1.0 / 6.0 - squared / 120.0 + angle_fourth / 5040.0
    else:
        first = float((1.0 - np.cos(angle)) / squared)
        second = float((angle - np.sin(angle)) / (squared * angle))
    return np.eye(3) - first * generator + second * (generator @ generator)


@dataclass(frozen=True)
class ContactCoordinates:
    contact_assembly_token: str
    values: np.ndarray

    def __post_init__(self) -> None:
        if len(self.contact_assembly_token) != 64:
            raise ValueError("contact_assembly_token must be one SHA-256 hexadecimal identity.")
        int(self.contact_assembly_token, 16)
        object.__setattr__(self, "values", _readonly(self.values, 1, "values"))


@dataclass(frozen=True)
class ContactValidityMetrics:
    bob_socket_material_extent_m: float
    bob_socket_radial_monotonicity_m2: float
    bob_socket_cut_gap_m: float
    junction_socket_metrics: tuple[tuple[str, float, float, float], ...]


@dataclass(frozen=True)
class ContactStaticEvaluation:
    coordinates: ContactCoordinates
    base_evaluation: StaticEvaluation
    constraint_ids: tuple[str, ...]
    gaps_m: np.ndarray
    gap_jacobian: np.ndarray
    witnesses: tuple[ContactWitness, ...]
    validity: ContactValidityMetrics

    def __post_init__(self) -> None:
        gaps = _readonly(self.gaps_m, 1, "gaps_m")
        jacobian = _readonly(self.gap_jacobian, 2, "gap_jacobian")
        if gaps.shape != (len(self.constraint_ids),):
            raise ValueError("gaps_m must contain one value per constraint identity.")
        if jacobian.shape[0] != gaps.size:
            raise ValueError("gap_jacobian must contain one row per gap.")
        if len(self.witnesses) != gaps.size:
            raise ValueError("witnesses must contain one entry per gap.")
        if tuple(witness.constraint_id for witness in self.witnesses) != self.constraint_ids:
            raise ValueError("Witness order must exactly match the frozen constraint identities.")
        object.__setattr__(self, "gaps_m", gaps)
        object.__setattr__(self, "gap_jacobian", jacobian)

    @property
    def total_potential(self) -> float:
        return self.base_evaluation.total_potential

    @property
    def generalized_force(self) -> np.ndarray:
        return self.base_evaluation.generalized_force


def _branch_points(
    assembly: StaticAssembly,
    evaluation: StaticEvaluation,
    branch_id: str,
) -> np.ndarray:
    return np.vstack(
        [
            evaluation.node_positions[assembly.topology.node_index(node_id)]
            for node_id in assembly.branch_node_ids(branch_id)
        ]
    )


def _socket_breakpoints(
    assembly: StaticAssembly,
    socket: MaterialSocketRegistration,
) -> np.ndarray:
    rest = np.array(
        [segment.rest_length for segment in assembly.topology.branch_segments(socket.branch_id)]
    )
    if socket.side == "end":
        rest = rest[::-1]
    cumulative = np.concatenate([[0.0], np.cumsum(rest)])
    internal = cumulative[(cumulative > 0.0) & (cumulative < socket.socket_length_m)]
    return np.concatenate([[0.0], internal, [socket.socket_length_m]])


def _material_point_from_socket_endpoint(
    assembly: StaticAssembly,
    evaluation: StaticEvaluation,
    socket: MaterialSocketRegistration,
    material_distance: float,
) -> np.ndarray:
    segments = assembly.topology.branch_segments(socket.branch_id)
    points = _branch_points(assembly, evaluation, socket.branch_id)
    rest = np.array([segment.rest_length for segment in segments])
    if socket.side == "end":
        points = points[::-1]
        rest = rest[::-1]
    cumulative = np.concatenate([[0.0], np.cumsum(rest)])
    distance = float(material_distance)
    if distance < 0.0 or distance > cumulative[-1]:
        raise DegenerateContactGeometry("Material socket query left its registered branch.")
    index = min(int(np.searchsorted(cumulative, distance, side="right") - 1), rest.size - 1)
    fraction = (distance - cumulative[index]) / rest[index]
    return (1.0 - fraction) * points[index] + fraction * points[index + 1]


def _minimum_projective_opening_squared_cell(
    first_start: np.ndarray,
    first_end: np.ndarray,
    second_start: np.ndarray,
    second_end: np.ndarray,
    first_interval: tuple[float, float],
    second_interval: tuple[float, float],
) -> float:
    s0, s1 = first_interval
    t0, t1 = second_interval
    first_slope = (first_end - first_start) / (s1 - s0)
    second_slope = (second_end - second_start) / (t1 - t0)
    offset = first_start - second_start - first_slope * s0 + second_slope * t0
    if s0 == 0.0 and t0 == 0.0:
        scale = max(
            float(np.linalg.norm(first_end - first_start)),
            float(np.linalg.norm(second_end - second_start)),
            s1,
            t1,
            np.finfo(float).tiny,
        )
        if float(np.linalg.norm(first_start - second_start)) > 256.0 * np.finfo(float).eps * scale:
            return 0.0
        base = -second_slope
        direction = first_slope + second_slope
        denominator = float(direction @ direction)
        fraction = 0.0 if denominator == 0.0 else float(np.clip(-(base @ direction) / denominator, 0.0, 1.0))
        vector = base + fraction * direction
        return max(float(vector @ vector), 0.0)

    matrix = np.column_stack([offset, first_slope + second_slope])
    constant = -second_slope
    material_corners = ((s0, t0), (s1, t0), (s1, t1), (s0, t1))
    polygon = [np.array([1.0 / (s + t), s / (s + t)]) for s, t in material_corners]

    def squared(parameter: np.ndarray) -> float:
        vector = constant + matrix @ parameter
        return float(vector @ vector)

    candidates = [squared(vertex) for vertex in polygon]
    for start, end in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        parameter_direction = end - start
        spatial_start = constant + matrix @ start
        spatial_direction = matrix @ parameter_direction
        denominator = float(spatial_direction @ spatial_direction)
        fraction = 0.0 if denominator == 0.0 else float(
            np.clip(-(spatial_start @ spatial_direction) / denominator, 0.0, 1.0)
        )
        candidates.append(squared(start + fraction * parameter_direction))
    stationary = -np.linalg.lstsq(matrix, constant, rcond=None)[0]
    u, x = (float(stationary[0]), float(stationary[1]))
    scale = max(abs(x), abs(s0 * u), abs(s1 * u), abs(1.0 - x), abs(t0 * u), abs(t1 * u), np.finfo(float).tiny)
    tolerance = 256.0 * np.finfo(float).eps * scale
    feasible = (
        u > 0.0
        and s0 * u - tolerance <= x <= s1 * u + tolerance
        and t0 * u - tolerance <= 1.0 - x <= t1 * u + tolerance
    )
    if feasible:
        candidates.append(squared(stationary))
    return max(float(min(candidates)), 0.0)


def _junction_validity(
    assembly: StaticAssembly,
    evaluation: StaticEvaluation,
    registration: JunctionSocketRegistration,
) -> tuple[float, float, float]:
    first_breaks = _socket_breakpoints(assembly, registration.first)
    second_breaks = _socket_breakpoints(assembly, registration.second)
    projective = float("inf")
    for first_start_s, first_end_s in zip(first_breaks[:-1], first_breaks[1:], strict=True):
        first_start = _material_point_from_socket_endpoint(
            assembly, evaluation, registration.first, float(first_start_s)
        )
        first_end = _material_point_from_socket_endpoint(
            assembly, evaluation, registration.first, float(first_end_s)
        )
        for second_start_s, second_end_s in zip(second_breaks[:-1], second_breaks[1:], strict=True):
            second_start = _material_point_from_socket_endpoint(
                assembly, evaluation, registration.second, float(second_start_s)
            )
            second_end = _material_point_from_socket_endpoint(
                assembly, evaluation, registration.second, float(second_end_s)
            )
            projective = min(
                projective,
                _minimum_projective_opening_squared_cell(
                    first_start,
                    first_end,
                    second_start,
                    second_end,
                    (float(first_start_s), float(first_end_s)),
                    (float(second_start_s), float(second_end_s)),
                ),
            )
    first_cut = _material_point_from_socket_endpoint(
        assembly, evaluation, registration.first, registration.first.socket_length_m
    )
    second_cut = _material_point_from_socket_endpoint(
        assembly, evaluation, registration.second, registration.second.socket_length_m
    )
    cut_gap = float(np.linalg.norm(first_cut - second_cut)) - registration.required_center_distance_m
    return (
        min(
            registration.first.total_material_length_m - registration.first.socket_length_m,
            registration.second.total_material_length_m - registration.second.socket_length_m,
        ),
        float(projective - registration.registered_projective_opening_squared),
        cut_gap,
    )


class ContactStaticAssembly:
    """Add registered inequality geometry without changing the P2 potential."""

    def __init__(
        self,
        *,
        base_assembly: StaticAssembly,
        surface: ContactSurfaceSpec,
        tolerances: GeometryTolerances,
        formal_registration_contract_sha256: str,
        protocol_amendment_sha256: str,
    ) -> None:
        if len(formal_registration_contract_sha256) != 64:
            raise ValueError("formal_registration_contract_sha256 must be one SHA-256 identity.")
        int(formal_registration_contract_sha256, 16)
        if len(protocol_amendment_sha256) != 64:
            raise ValueError("protocol_amendment_sha256 must be one SHA-256 identity.")
        int(protocol_amendment_sha256, 16)
        registry = build_contact_registry(base_assembly.topology, surface, tolerances)
        binding = {
            "identity_schema": "YPS-HFV2-CONTACT-ASSEMBLY-IDENTITY-1.0",
            "contact_model_id": CONTACT_MODEL_ID,
            "base_static_assembly_token": base_assembly.layout.layout_token,
            "formal_registration_contract_sha256": formal_registration_contract_sha256,
            "protocol_amendment_sha256": protocol_amendment_sha256,
            "geometry_tolerances": asdict(tolerances),
            "contact_registry": registry.serializable(),
        }
        token = hashlib.sha256(
            json.dumps(binding, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        self.base_assembly = base_assembly
        self.surface = surface
        self.tolerances = tolerances
        self.registry: ContactRegistry = registry
        self.formal_registration_contract_sha256 = formal_registration_contract_sha256
        self.protocol_amendment_sha256 = protocol_amendment_sha256
        self.contact_assembly_token = token

    def coordinates_from_seed(self, seed: StaticSeed) -> ContactCoordinates:
        base = self.base_assembly.coordinates_from_seed(seed)
        return ContactCoordinates(self.contact_assembly_token, base.values)

    def coordinates_from_values(self, values: np.ndarray) -> ContactCoordinates:
        base = self.base_assembly.coordinates_from_values(values)
        return ContactCoordinates(self.contact_assembly_token, base.values)

    def _validate_coordinates(self, coordinates: ContactCoordinates) -> np.ndarray:
        if coordinates.contact_assembly_token != self.contact_assembly_token:
            raise ValueError("ContactCoordinates belong to a different contact assembly identity.")
        base = self.base_assembly.coordinates_from_values(coordinates.values)
        return base.values

    def _node_position_jacobians(
        self,
        coordinates: ContactCoordinates,
        evaluation: StaticEvaluation,
    ) -> dict[str, np.ndarray]:
        size = self.base_assembly.layout.generalized_size
        result: dict[str, np.ndarray] = {}
        for node in self.base_assembly.topology.nodes:
            jacobian = np.zeros((3, size))
            if node.kind == "free":
                jacobian[:, self.base_assembly.layout.free_slice(node.node_id)] = np.eye(3)
            elif node.kind == "bob_attachment":
                jacobian[:, self.base_assembly.layout.bob_position_slice.slice] = np.eye(3)
                rotation_vector = coordinates.values[
                    self.base_assembly.layout.bob_rotation_slice.slice
                ]
                jacobian[:, self.base_assembly.layout.bob_rotation_slice.slice] = (
                    -evaluation.bob_rotation
                    @ hat(self.base_assembly.bob.attachment_arm_body)
                    @ _right_jacobian_so3(rotation_vector)
                )
            result[node.node_id] = jacobian
        return result

    def _validity_metrics(self, evaluation: StaticEvaluation) -> ContactValidityMetrics:
        bob_socket = self.registry.bob_socket
        breakpoints = _socket_breakpoints(self.base_assembly, bob_socket.socket)
        points = [
            _material_point_from_socket_endpoint(
                self.base_assembly, evaluation, bob_socket.socket, float(distance)
            )
            for distance in breakpoints
        ]
        radial = min(
            float((start - evaluation.bob_position) @ (end - start))
            for start, end in zip(points[:-1], points[1:], strict=True)
        )
        cut_gap = float(np.linalg.norm(points[-1] - evaluation.bob_position)) - bob_socket.required_center_distance_m
        extent = bob_socket.socket.total_material_length_m - bob_socket.socket.socket_length_m
        if radial < self.tolerances.socket_radial_monotonicity_min_m2:
            raise DegenerateContactGeometry("Bob socket radial monotonicity left its frozen valid domain.")
        if cut_gap < self.tolerances.socket_cut_gap_min_m:
            raise DegenerateContactGeometry("Bob socket cut entered the registered inflated surface.")
        junction_metrics = []
        for registration in self.registry.junction_sockets:
            material_extent, projective_margin, junction_cut_gap = _junction_validity(
                self.base_assembly,
                evaluation,
                registration,
            )
            if projective_margin < self.tolerances.socket_projective_opening_margin_min:
                raise DegenerateContactGeometry("Junction socket projective opening is invalid.")
            if junction_cut_gap < self.tolerances.socket_cut_gap_min_m:
                raise DegenerateContactGeometry("Junction socket cut violates its required separation.")
            junction_metrics.append(
                (
                    registration.registration_id,
                    material_extent,
                    projective_margin,
                    junction_cut_gap,
                )
            )
        return ContactValidityMetrics(
            bob_socket_material_extent_m=extent,
            bob_socket_radial_monotonicity_m2=radial,
            bob_socket_cut_gap_m=cut_gap,
            junction_socket_metrics=tuple(junction_metrics),
        )

    def evaluate(self, coordinates: ContactCoordinates) -> ContactStaticEvaluation:
        values = self._validate_coordinates(coordinates)
        base_coordinates = self.base_assembly.coordinates_from_values(values)
        base_evaluation = self.base_assembly.evaluate(base_coordinates)
        validity = self._validity_metrics(base_evaluation)
        witnesses: list[ContactWitness] = []
        positions = base_evaluation.node_positions
        topology = self.base_assembly.topology
        for constraint in self.registry.segment_pair_constraints:
            indices = [topology.node_index(node_id) for node_id in constraint.endpoint_node_ids]
            witnesses.append(
                closest_segment_pair_witness(
                    positions[indices[0]],
                    positions[indices[1]],
                    positions[indices[2]],
                    positions[indices[3]],
                    constraint,
                    self.tolerances,
                )
            )
        for constraint in self.registry.bob_segment_constraints:
            witnesses.append(
                closest_bob_segment_witness(
                    base_evaluation.bob_position,
                    positions[topology.node_index(constraint.start_node)],
                    positions[topology.node_index(constraint.end_node)],
                    constraint,
                    self.tolerances,
                )
            )
        node_jacobians = self._node_position_jacobians(coordinates, base_evaluation)
        bob_jacobian = np.zeros((3, self.base_assembly.layout.generalized_size))
        bob_jacobian[:, self.base_assembly.layout.bob_position_slice.slice] = np.eye(3)
        gap_jacobian = np.zeros(
            (len(witnesses), self.base_assembly.layout.generalized_size),
            dtype=float,
        )
        for row, witness in enumerate(witnesses):
            for object_id, gradient in zip(
                witness.object_ids,
                witness.object_gap_gradients,
                strict=True,
            ):
                object_jacobian = bob_jacobian if object_id == "__bob_center__" else node_jacobians[object_id]
                gap_jacobian[row] += gradient @ object_jacobian
        return ContactStaticEvaluation(
            coordinates=coordinates,
            base_evaluation=base_evaluation,
            constraint_ids=self.registry.constraint_ids,
            gaps_m=np.array([witness.gap_m for witness in witnesses]),
            gap_jacobian=gap_jacobian,
            witnesses=tuple(witnesses),
            validity=validity,
        )

"""Immutable contracts for registered static rigid contact."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

ContactCategory = Literal["same_branch_full", "same_branch_partial", "junction_socket", "bob_segment"]


class ContactGeometryError(ValueError):
    """Base error for invalid registered contact geometry."""


class DegenerateContactGeometry(ContactGeometryError):
    """Raised when a unique differentiable closest-point witness is unavailable."""


def _positive_finite(value: float, name: str) -> float:
    scalar = float(value)
    if not np.isfinite(scalar) or scalar <= 0.0:
        raise ValueError(f"{name} must be finite and strictly positive.")
    return scalar


def _nonnegative_finite(value: float, name: str) -> float:
    scalar = float(value)
    if not np.isfinite(scalar) or scalar < 0.0:
        raise ValueError(f"{name} must be finite and non-negative.")
    return scalar


def _identifier(value: str, name: str) -> str:
    if not value or value.strip() != value:
        raise ValueError(f"{name} must be a non-empty, stripped string.")
    return value


def _readonly(value: np.ndarray, shape_tail: tuple[int, ...], name: str) -> np.ndarray:
    array = np.array(value, dtype=float, copy=True)
    if array.ndim < len(shape_tail) or array.shape[-len(shape_tail) :] != shape_tail:
        raise ValueError(f"{name} must end with shape {shape_tail}.")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite.")
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class GeometryTolerances:
    collapsed_segment_length_m: float
    zero_witness_distance_m: float
    parameter_merge_absolute: float
    squared_distance_tie_relative: float
    polygon_halfspace_absolute: float
    polygon_area_absolute: float
    socket_radial_monotonicity_min_m2: float
    socket_projective_opening_margin_min: float
    socket_cut_gap_min_m: float

    def __post_init__(self) -> None:
        positive = (
            "collapsed_segment_length_m",
            "zero_witness_distance_m",
            "parameter_merge_absolute",
            "squared_distance_tie_relative",
            "polygon_halfspace_absolute",
            "polygon_area_absolute",
        )
        for name in positive:
            object.__setattr__(self, name, _positive_finite(getattr(self, name), name))
        object.__setattr__(
            self,
            "socket_radial_monotonicity_min_m2",
            _nonnegative_finite(
                self.socket_radial_monotonicity_min_m2,
                "socket_radial_monotonicity_min_m2",
            ),
        )
        for name in ("socket_projective_opening_margin_min", "socket_cut_gap_min_m"):
            scalar = float(getattr(self, name))
            if not np.isfinite(scalar):
                raise ValueError(f"{name} must be finite.")
            object.__setattr__(self, name, scalar)


@dataclass(frozen=True)
class ContactSurfaceSpec:
    branch_contact_radii_m: tuple[tuple[str, float], ...]
    bob_contact_radius_m: float
    minimum_clearance_m: float
    formal_registration_id: str = "FIXED_REST_MATERIAL_SOCKETS_PROJECTIVE_V2"

    def __post_init__(self) -> None:
        entries = tuple((str(branch), float(radius)) for branch, radius in self.branch_contact_radii_m)
        identifiers = tuple(branch for branch, _ in entries)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Branch contact radii must have unique branch identities.")
        for branch, radius in entries:
            _identifier(branch, "branch_id")
            _positive_finite(radius, f"branch_contact_radius[{branch!r}]")
        object.__setattr__(self, "branch_contact_radii_m", entries)
        object.__setattr__(
            self,
            "bob_contact_radius_m",
            _positive_finite(self.bob_contact_radius_m, "bob_contact_radius_m"),
        )
        object.__setattr__(
            self,
            "minimum_clearance_m",
            _nonnegative_finite(self.minimum_clearance_m, "minimum_clearance_m"),
        )
        _identifier(self.formal_registration_id, "formal_registration_id")

    @property
    def branch_ids(self) -> tuple[str, ...]:
        return tuple(branch for branch, _ in self.branch_contact_radii_m)

    def radius(self, branch_id: str) -> float:
        for branch, radius in self.branch_contact_radii_m:
            if branch == branch_id:
                return radius
        raise KeyError(branch_id)


@dataclass(frozen=True)
class ConvexParameterPolygon:
    vertices: np.ndarray

    def __post_init__(self) -> None:
        vertices = _readonly(self.vertices, (2,), "vertices")
        if vertices.ndim != 2 or vertices.shape[0] < 3:
            raise ValueError("A convex parameter polygon requires at least three vertices.")
        area = 0.5 * float(
            np.sum(
                vertices[:, 0] * np.roll(vertices[:, 1], -1)
                - vertices[:, 1] * np.roll(vertices[:, 0], -1)
            )
        )
        if area <= 0.0:
            raise ValueError("Parameter polygon vertices must be counter-clockwise with positive area.")
        object.__setattr__(self, "vertices", vertices)

    def serializable(self) -> list[list[float]]:
        return self.vertices.tolist()


@dataclass(frozen=True)
class SegmentPairConstraint:
    constraint_id: str
    category: Literal["same_branch_full", "same_branch_partial", "junction_socket"]
    first_branch_id: str
    first_segment_id: str
    first_start_node: str
    first_end_node: str
    second_branch_id: str
    second_segment_id: str
    second_start_node: str
    second_end_node: str
    required_center_distance_m: float
    parameter_domains: tuple[ConvexParameterPolygon, ...]
    shared_node_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "constraint_id",
            "first_branch_id",
            "first_segment_id",
            "first_start_node",
            "first_end_node",
            "second_branch_id",
            "second_segment_id",
            "second_start_node",
            "second_end_node",
        ):
            _identifier(str(getattr(self, name)), name)
        if self.category not in {"same_branch_full", "same_branch_partial", "junction_socket"}:
            raise ValueError("Unsupported segment-pair contact category.")
        if self.shared_node_id is not None:
            _identifier(self.shared_node_id, "shared_node_id")
        domains = tuple(self.parameter_domains)
        if not domains:
            raise ValueError("A segment-pair constraint requires a non-empty parameter domain.")
        serialized_domains = tuple(
            tuple(tuple(vertex) for vertex in domain.serializable()) for domain in domains
        )
        if len(serialized_domains) != len(set(serialized_domains)):
            raise ContactGeometryError("Duplicate convex pieces inside one contact domain are forbidden.")
        object.__setattr__(self, "parameter_domains", domains)
        object.__setattr__(
            self,
            "required_center_distance_m",
            _positive_finite(self.required_center_distance_m, "required_center_distance_m"),
        )

    @property
    def endpoint_node_ids(self) -> tuple[str, str, str, str]:
        return (
            self.first_start_node,
            self.first_end_node,
            self.second_start_node,
            self.second_end_node,
        )

    def serializable(self) -> dict[str, object]:
        return {
            "constraint_id": self.constraint_id,
            "category": self.category,
            "first": [
                self.first_branch_id,
                self.first_segment_id,
                self.first_start_node,
                self.first_end_node,
            ],
            "second": [
                self.second_branch_id,
                self.second_segment_id,
                self.second_start_node,
                self.second_end_node,
            ],
            "required_center_distance_m": self.required_center_distance_m,
            "parameter_domains": [domain.serializable() for domain in self.parameter_domains],
            "shared_node_id": self.shared_node_id,
        }


@dataclass(frozen=True)
class BobSegmentConstraint:
    constraint_id: str
    branch_id: str
    segment_id: str
    start_node: str
    end_node: str
    parameter_min: float
    parameter_max: float
    required_center_distance_m: float

    def __post_init__(self) -> None:
        for name in ("constraint_id", "branch_id", "segment_id", "start_node", "end_node"):
            _identifier(str(getattr(self, name)), name)
        lower = float(self.parameter_min)
        upper = float(self.parameter_max)
        if not np.isfinite(lower) or not np.isfinite(upper) or lower < 0.0 or upper > 1.0:
            raise ValueError("Bob-segment parameter interval must lie in [0,1].")
        if upper <= lower:
            raise ValueError("Bob-segment parameter interval must have positive extent.")
        object.__setattr__(self, "parameter_min", lower)
        object.__setattr__(self, "parameter_max", upper)
        object.__setattr__(
            self,
            "required_center_distance_m",
            _positive_finite(self.required_center_distance_m, "required_center_distance_m"),
        )

    def serializable(self) -> dict[str, object]:
        return {
            "constraint_id": self.constraint_id,
            "category": "bob_segment",
            "branch_id": self.branch_id,
            "segment_id": self.segment_id,
            "start_node": self.start_node,
            "end_node": self.end_node,
            "parameter_interval": [self.parameter_min, self.parameter_max],
            "required_center_distance_m": self.required_center_distance_m,
        }


@dataclass(frozen=True)
class MaterialSocketRegistration:
    branch_id: str
    endpoint_node_id: str
    side: Literal["start", "end"]
    socket_length_m: float
    total_material_length_m: float

    def __post_init__(self) -> None:
        _identifier(self.branch_id, "branch_id")
        _identifier(self.endpoint_node_id, "endpoint_node_id")
        if self.side not in {"start", "end"}:
            raise ValueError("Material socket side must be 'start' or 'end'.")
        length = _positive_finite(self.socket_length_m, "socket_length_m")
        total = _positive_finite(self.total_material_length_m, "total_material_length_m")
        if length >= total:
            raise ContactGeometryError("Material socket must leave positive active material extent.")
        object.__setattr__(self, "socket_length_m", length)
        object.__setattr__(self, "total_material_length_m", total)

    def serializable(self) -> dict[str, object]:
        return {
            "branch_id": self.branch_id,
            "endpoint_node_id": self.endpoint_node_id,
            "side": self.side,
            "socket_length_m": self.socket_length_m,
            "total_material_length_m": self.total_material_length_m,
        }


@dataclass(frozen=True)
class JunctionSocketRegistration:
    registration_id: str
    shared_node_id: str
    first: MaterialSocketRegistration
    second: MaterialSocketRegistration
    required_center_distance_m: float
    registered_projective_opening_squared: float

    def __post_init__(self) -> None:
        _identifier(self.registration_id, "registration_id")
        _identifier(self.shared_node_id, "shared_node_id")
        if self.first.endpoint_node_id != self.shared_node_id or self.second.endpoint_node_id != self.shared_node_id:
            raise ValueError("Junction sockets must terminate at their declared shared node.")
        object.__setattr__(
            self,
            "required_center_distance_m",
            _positive_finite(self.required_center_distance_m, "required_center_distance_m"),
        )
        opening = _positive_finite(
            self.registered_projective_opening_squared,
            "registered_projective_opening_squared",
        )
        object.__setattr__(self, "registered_projective_opening_squared", opening)

    def serializable(self) -> dict[str, object]:
        return {
            "registration_id": self.registration_id,
            "shared_node_id": self.shared_node_id,
            "first": self.first.serializable(),
            "second": self.second.serializable(),
            "required_center_distance_m": self.required_center_distance_m,
            "registered_projective_opening_squared": self.registered_projective_opening_squared,
        }


@dataclass(frozen=True)
class BobSocketRegistration:
    registration_id: str
    socket: MaterialSocketRegistration
    required_center_distance_m: float

    def __post_init__(self) -> None:
        _identifier(self.registration_id, "registration_id")
        object.__setattr__(
            self,
            "required_center_distance_m",
            _positive_finite(self.required_center_distance_m, "required_center_distance_m"),
        )

    def serializable(self) -> dict[str, object]:
        return {
            "registration_id": self.registration_id,
            "socket": self.socket.serializable(),
            "required_center_distance_m": self.required_center_distance_m,
        }


@dataclass(frozen=True)
class ContactRegistry:
    formal_registration_id: str
    surface: ContactSurfaceSpec
    segment_pair_constraints: tuple[SegmentPairConstraint, ...]
    bob_segment_constraints: tuple[BobSegmentConstraint, ...]
    junction_sockets: tuple[JunctionSocketRegistration, ...]
    bob_socket: BobSocketRegistration

    def __post_init__(self) -> None:
        _identifier(self.formal_registration_id, "formal_registration_id")
        segment_pairs = tuple(self.segment_pair_constraints)
        bob_segments = tuple(self.bob_segment_constraints)
        junctions = tuple(self.junction_sockets)
        identifiers = tuple(item.constraint_id for item in segment_pairs) + tuple(
            item.constraint_id for item in bob_segments
        )
        if len(identifiers) != len(set(identifiers)):
            raise ContactGeometryError("Contact constraint identities must be unique.")
        canonical_domains = []
        for item in segment_pairs:
            canonical_domains.append(
                (
                    "segment_pair",
                    item.endpoint_node_ids,
                    tuple(tuple(tuple(vertex) for vertex in domain.serializable()) for domain in item.parameter_domains),
                    item.required_center_distance_m,
                )
            )
        for item in bob_segments:
            canonical_domains.append(
                (
                    "bob_segment",
                    item.start_node,
                    item.end_node,
                    item.parameter_min,
                    item.parameter_max,
                    item.required_center_distance_m,
                )
            )
        if len(canonical_domains) != len(set(canonical_domains)):
            raise ContactGeometryError("Duplicate canonical contact domains are forbidden.")
        object.__setattr__(self, "segment_pair_constraints", segment_pairs)
        object.__setattr__(self, "bob_segment_constraints", bob_segments)
        object.__setattr__(self, "junction_sockets", junctions)

    @property
    def constraint_ids(self) -> tuple[str, ...]:
        return tuple(item.constraint_id for item in self.segment_pair_constraints) + tuple(
            item.constraint_id for item in self.bob_segment_constraints
        )

    def serializable(self) -> dict[str, object]:
        return {
            "formal_registration_id": self.formal_registration_id,
            "surface": {
                "branch_contact_radii_m": [list(item) for item in self.surface.branch_contact_radii_m],
                "bob_contact_radius_m": self.surface.bob_contact_radius_m,
                "minimum_clearance_m": self.surface.minimum_clearance_m,
            },
            "segment_pair_constraints": [item.serializable() for item in self.segment_pair_constraints],
            "bob_segment_constraints": [item.serializable() for item in self.bob_segment_constraints],
            "junction_sockets": [item.serializable() for item in self.junction_sockets],
            "bob_socket": self.bob_socket.serializable(),
        }


@dataclass(frozen=True)
class ContactWitness:
    constraint_id: str
    category: ContactCategory
    first_parameter: float | None
    second_parameter: float
    first_point_m: np.ndarray
    second_point_m: np.ndarray
    distance_m: float
    required_center_distance_m: float
    gap_m: float
    normal_second_to_first: np.ndarray
    object_ids: tuple[str, ...]
    object_gap_gradients: np.ndarray
    active_feature: str
    competing_minimizer_count: int
    unit_interval_parameter_margin: float

    def __post_init__(self) -> None:
        _identifier(self.constraint_id, "constraint_id")
        if self.category not in {"same_branch_full", "same_branch_partial", "junction_socket", "bob_segment"}:
            raise ValueError("Unsupported contact witness category.")
        if self.first_parameter is not None and not np.isfinite(self.first_parameter):
            raise ValueError("first_parameter must be finite when present.")
        if not np.isfinite(self.second_parameter):
            raise ValueError("second_parameter must be finite.")
        first = _readonly(self.first_point_m, (3,), "first_point_m")
        second = _readonly(self.second_point_m, (3,), "second_point_m")
        normal = _readonly(self.normal_second_to_first, (3,), "normal_second_to_first")
        gradients = _readonly(self.object_gap_gradients, (3,), "object_gap_gradients")
        if gradients.ndim != 2 or gradients.shape[0] != len(self.object_ids):
            raise ValueError("object_gap_gradients must have one row per object identity.")
        if not np.isclose(np.linalg.norm(normal), 1.0, rtol=0.0, atol=2.0e-12):
            raise ValueError("Contact normal must have unit length.")
        for name in ("distance_m", "required_center_distance_m", "gap_m", "unit_interval_parameter_margin"):
            if not np.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite.")
        if self.distance_m <= 0.0 or self.required_center_distance_m <= 0.0:
            raise ValueError("Witness and required center distances must be positive.")
        if self.competing_minimizer_count != 1:
            raise ValueError("Accepted contact witnesses must have exactly one minimizer cluster.")
        object.__setattr__(self, "first_point_m", first)
        object.__setattr__(self, "second_point_m", second)
        object.__setattr__(self, "normal_second_to_first", normal)
        object.__setattr__(self, "object_gap_gradients", gradients)

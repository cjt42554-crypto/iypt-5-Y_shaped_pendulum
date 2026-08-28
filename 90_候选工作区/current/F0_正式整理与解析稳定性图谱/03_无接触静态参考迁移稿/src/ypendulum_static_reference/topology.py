"""Explicit material-node topology and tangent-space degree-of-freedom mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

NodeKind = Literal["free", "prescribed", "bob_attachment"]


@dataclass(frozen=True)
class MaterialNode:
    """One registered material node.

    Shared nodes, such as the Y junction, appear once and are referenced by
    every incident segment.  Coincident coordinates therefore never imply a
    topological connection.
    """

    node_id: str
    kind: NodeKind

    def __post_init__(self) -> None:
        if not self.node_id or self.node_id.strip() != self.node_id:
            raise ValueError("node_id must be a non-empty, stripped string.")
        if self.kind not in {"free", "prescribed", "bob_attachment"}:
            raise ValueError(f"Unsupported material-node kind {self.kind!r}.")


@dataclass(frozen=True)
class MaterialSegment:
    """One oriented material segment on a named reference-arc branch.

    Material coordinates are SI reference arc lengths.  ``rest_length`` is
    consequently derived from the coordinate interval and cannot diverge from
    it as a second source of truth.
    """

    segment_id: str
    branch_id: str
    start_node: str
    end_node: str
    material_start: float
    material_end: float

    def __post_init__(self) -> None:
        identifiers = (self.segment_id, self.branch_id, self.start_node, self.end_node)
        if any(not value or value.strip() != value for value in identifiers):
            raise ValueError("Segment and node identifiers must be non-empty and stripped.")
        if self.start_node == self.end_node:
            raise ValueError("A material segment cannot connect a node to itself.")
        scalars = np.asarray([self.material_start, self.material_end], dtype=float)
        if not np.all(np.isfinite(scalars)):
            raise ValueError("Material coordinates must be finite.")
        if self.material_end <= self.material_start:
            raise ValueError("material_end must be strictly greater than material_start.")

    @property
    def rest_length(self) -> float:
        """Reference length derived from the SI material-arc coordinates."""

        return float(self.material_end - self.material_start)


@dataclass(frozen=True)
class StaticReferenceTopology:
    """Immutable node/segment registration with an explicit free-DOF map."""

    nodes: tuple[MaterialNode, ...]
    segments: tuple[MaterialSegment, ...]

    def __post_init__(self) -> None:
        nodes = tuple(self.nodes)
        segments = tuple(self.segments)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "segments", segments)
        if not nodes:
            raise ValueError("StaticReferenceTopology requires at least one material node.")
        node_ids = [node.node_id for node in nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Material-node identities must be unique.")
        segment_ids = [segment.segment_id for segment in segments]
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("Material-segment identities must be unique.")
        known = set(node_ids)
        used_nodes: set[str] = set()
        for segment in segments:
            missing = {segment.start_node, segment.end_node} - known
            if missing:
                raise ValueError(
                    f"Segment {segment.segment_id!r} references unknown nodes {sorted(missing)}."
                )
            used_nodes.update((segment.start_node, segment.end_node))
        if not segments:
            raise ValueError("StaticReferenceTopology requires at least one material segment.")
        unreferenced = known - used_nodes
        if unreferenced:
            raise ValueError(
                f"Unreferenced material nodes are not allowed: {sorted(unreferenced)}."
            )
        attachment_count = sum(node.kind == "bob_attachment" for node in nodes)
        if attachment_count != 1:
            raise ValueError(
                "StaticReferenceTopology requires exactly one bob_attachment node."
            )
        for branch_id in {segment.branch_id for segment in segments}:
            branch = sorted(
                (segment for segment in segments if segment.branch_id == branch_id),
                key=lambda segment: segment.material_start,
            )
            for left, right in zip(branch[:-1], branch[1:], strict=True):
                scale = max(
                    abs(left.material_end),
                    abs(right.material_start),
                    left.rest_length,
                    right.rest_length,
                )
                coordinate_tolerance = 64.0 * np.finfo(float).eps * scale
                if abs(left.material_end - right.material_start) > coordinate_tolerance:
                    raise ValueError(
                        f"Branch {branch_id!r} has a material-coordinate gap or overlap."
                    )
                if left.end_node != right.start_node:
                    raise ValueError(
                        f"Branch {branch_id!r} is not a connected oriented material chain."
                    )

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(node.node_id for node in self.nodes)

    @property
    def free_node_ids(self) -> tuple[str, ...]:
        return tuple(node.node_id for node in self.nodes if node.kind == "free")

    @property
    def free_node_count(self) -> int:
        return len(self.free_node_ids)

    @property
    def generalized_position_tangent_size(self) -> int:
        """Free nodes, bob translation and three-dimensional rotation tangent."""

        return 3 * self.free_node_count + 6

    def node_index(self, node_id: str) -> int:
        if node_id not in self.node_ids:
            raise KeyError(node_id)
        return self.node_ids.index(node_id)

    def free_node_index(self, node_id: str) -> int:
        if node_id not in self.free_node_ids:
            raise KeyError(f"Node {node_id!r} is absent or is not free.")
        return self.free_node_ids.index(node_id)

    def free_position_slice(self, node_id: str) -> slice:
        start = 3 * self.free_node_index(node_id)
        return slice(start, start + 3)

    @property
    def bob_position_slice(self) -> slice:
        start = 3 * self.free_node_count
        return slice(start, start + 3)

    @property
    def bob_rotation_tangent_slice(self) -> slice:
        start = 3 * self.free_node_count + 3
        return slice(start, start + 3)

    def branch_segments(self, branch_id: str) -> tuple[MaterialSegment, ...]:
        selected = tuple(segment for segment in self.segments if segment.branch_id == branch_id)
        if not selected:
            raise KeyError(branch_id)
        return tuple(sorted(selected, key=lambda segment: segment.material_start))

    def branch_rest_length(self, branch_id: str) -> float:
        """Return the reference-arc span of one connected branch."""

        branch = self.branch_segments(branch_id)
        return float(branch[-1].material_end - branch[0].material_start)

    def incidence_matrix(self) -> np.ndarray:
        """Return the oriented segment-by-node incidence matrix."""

        matrix = np.zeros((len(self.segments), len(self.nodes)), dtype=float)
        for row, segment in enumerate(self.segments):
            matrix[row, self.node_index(segment.start_node)] = -1.0
            matrix[row, self.node_index(segment.end_node)] = 1.0
        return matrix

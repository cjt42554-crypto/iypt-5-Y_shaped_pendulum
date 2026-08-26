"""Assembly of individual contact gaps and nodal Jacobians."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .types import Array, ContactConstraint, ContactWitness, DegenerateContactGeometry
from .witness import closest_segment_pair_witness


def assemble_gap_system(
    node_positions_m: Array,
    constraints: Sequence[ContactConstraint],
    *,
    require_differentiable: bool = True,
) -> tuple[Array, Array, tuple[ContactWitness, ...]]:
    positions = np.asarray(node_positions_m, dtype=float)
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError("node_positions_m must have shape (n,3).")
    if not np.all(np.isfinite(positions)):
        raise ValueError("node_positions_m must be finite.")
    rows: list[Array] = []
    gaps: list[float] = []
    witnesses: list[ContactWitness] = []
    for constraint in constraints:
        nodes = constraint.endpoint_nodes()
        if any(node < 0 or node >= positions.shape[0] for node in nodes):
            raise IndexError(f"Contact {constraint.label!r} references an invalid node.")
        witness = closest_segment_pair_witness(
            positions[nodes[0]],
            positions[nodes[1]],
            positions[nodes[2]],
            positions[nodes[3]],
            required_center_distance_m=constraint.required_center_distance_m,
            parameter_polygon=constraint.parameter_polygon,
        )
        if require_differentiable and not witness.differentiable:
            raise DegenerateContactGeometry(
                f"Contact {constraint.label!r} has "
                f"{witness.competing_minimizer_count} closest-point minimizers "
                "or a zero-distance witness."
            )
        row = np.zeros(positions.size, dtype=float)
        for node, local_gradient in zip(
            nodes, witness.endpoint_gap_gradient, strict=True
        ):
            row[3 * node : 3 * node + 3] += local_gradient
        gaps.append(witness.gap_m)
        rows.append(row)
        witnesses.append(witness)
    jacobian = np.vstack(rows) if rows else np.empty((0, positions.size), dtype=float)
    return np.asarray(gaps, dtype=float), jacobian, tuple(witnesses)

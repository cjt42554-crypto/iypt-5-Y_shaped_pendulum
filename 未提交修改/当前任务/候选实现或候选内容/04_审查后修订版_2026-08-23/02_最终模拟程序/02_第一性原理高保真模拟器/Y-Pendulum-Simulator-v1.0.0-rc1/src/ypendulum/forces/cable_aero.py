"""Distributed normal drag on cable elements."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse

from ypendulum.elements.cable3d import CableElementBatch, CableKinematics


@dataclass(frozen=True)
class CableAeroResponse:
    nodal_forces: np.ndarray
    velocity_tangent: sparse.csr_matrix
    dissipation_rate: float


def cable_normal_drag(
    positions: np.ndarray,
    velocities: np.ndarray,
    kin: CableKinematics,
    elements: CableElementBatch,
    *,
    air_velocity: np.ndarray,
    air_density: float,
    enabled_mask: np.ndarray,
    node_count: int,
) -> CableAeroResponse:
    forces = np.zeros((node_count, 3), dtype=float)
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    dissipation = 0.0
    air = np.asarray(air_velocity, dtype=float)
    eye = np.eye(3)

    for e, (i, j) in enumerate(zip(elements.node_i, elements.node_j, strict=True)):
        if not enabled_mask[e]:
            continue
        midpoint_v = 0.5 * (velocities[i] + velocities[j])
        rel = midpoint_v - air
        n = kin.direction[e]
        projector = eye - np.outer(n, n)
        w = projector @ rel
        speed = float(np.linalg.norm(w))
        if speed <= 1e-15:
            continue
        coeff = 0.5 * air_density * elements.drag_cd_normal[e] * elements.diameter[e]
        total = -coeff * kin.length[e] * speed * w
        forces[i] += 0.5 * total
        forces[j] += 0.5 * total
        dissipation += coeff * kin.length[e] * speed**3

        dwdv = projector
        dtotal_dmid = -coeff * kin.length[e] * (
            speed * eye + np.outer(w, w) / speed
        ) @ dwdv
        # Each nodal force is half the total; midpoint velocity has half weight per endpoint.
        block = 0.25 * dtotal_dmid
        for out_node in (int(i), int(j)):
            for in_node in (int(i), int(j)):
                for a in range(3):
                    for b in range(3):
                        val = float(block[a, b])
                        if val:
                            rows.append(3 * out_node + a)
                            cols.append(3 * in_node + b)
                            data.append(val)

    tangent = sparse.coo_matrix(
        (data, (rows, cols)), shape=(3 * node_count, 3 * node_count)
    ).tocsr()
    tangent.sum_duplicates()
    return CableAeroResponse(forces, tangent, float(dissipation))

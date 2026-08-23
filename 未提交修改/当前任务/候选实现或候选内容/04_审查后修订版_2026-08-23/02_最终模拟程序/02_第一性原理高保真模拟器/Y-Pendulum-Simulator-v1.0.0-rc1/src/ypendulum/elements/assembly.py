"""Sparse nodal force and tangent assembly."""

from __future__ import annotations

import numpy as np
from scipy import sparse

from .cable3d import CableElementBatch, CableResponse


def assemble_element_forces(
    node_count: int, elements: CableElementBatch, response: CableResponse
) -> np.ndarray:
    forces = np.zeros((node_count, 3), dtype=float)
    np.add.at(forces, elements.node_i, response.force_i)
    np.add.at(forces, elements.node_j, response.force_j)
    return forces


def assemble_element_tangent(
    node_count: int,
    elements: CableElementBatch,
    local: np.ndarray,
) -> sparse.csr_matrix:
    """Assemble derivative of nodal forces from local ``df_i/dd`` matrices."""

    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    # f_i = f(d), f_j=-f(d), d=x_j-x_i
    # blocks: ii=-K, ij=K, ji=K, jj=-K.
    for e, (i, j) in enumerate(zip(elements.node_i, elements.node_j, strict=True)):
        K = local[e]
        for a in range(3):
            for b in range(3):
                val = float(K[a, b])
                if val == 0.0:
                    continue
                ia, ja = 3 * int(i) + a, 3 * int(j) + a
                ib, jb = 3 * int(i) + b, 3 * int(j) + b
                rows.extend((ia, ia, ja, ja))
                cols.extend((ib, jb, ib, jb))
                data.extend((-val, val, val, -val))
    mat = sparse.coo_matrix((data, (rows, cols)), shape=(3 * node_count, 3 * node_count))
    mat.sum_duplicates()
    return mat.tocsr()

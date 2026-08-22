"""Consistent and lumped translational mass assembly."""

from __future__ import annotations

import numpy as np
from scipy import sparse

from .cable3d import CableElementBatch


def assemble_mass_matrix(
    node_count: int,
    elements: CableElementBatch,
    point_masses: dict[int, float],
    *,
    kind: str = "consistent",
) -> sparse.csr_matrix:
    ndof = 3 * node_count
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []

    if kind not in {"consistent", "lumped"}:
        raise ValueError(f"Unknown mass matrix kind {kind!r}.")

    for i, j, mass in zip(elements.node_i, elements.node_j, elements.element_mass, strict=True):
        if kind == "consistent":
            coeffs = ((i, i, mass / 3), (i, j, mass / 6), (j, i, mass / 6), (j, j, mass / 3))
        else:
            coeffs = ((i, i, mass / 2), (j, j, mass / 2))
        for na, nb, coefficient in coeffs:
            for axis in range(3):
                rows.append(3 * int(na) + axis)
                cols.append(3 * int(nb) + axis)
                data.append(float(coefficient))

    for node, mass in point_masses.items():
        if mass <= 0:
            raise ValueError("Point masses must be positive.")
        for axis in range(3):
            rows.append(3 * int(node) + axis)
            cols.append(3 * int(node) + axis)
            data.append(float(mass))

    matrix = sparse.coo_matrix((data, (rows, cols)), shape=(ndof, ndof)).tocsr()
    matrix.sum_duplicates()
    if (matrix - matrix.T).nnz and np.max(np.abs((matrix - matrix.T).data)) > 1e-13:
        raise RuntimeError("Assembled mass matrix is not symmetric.")
    return matrix

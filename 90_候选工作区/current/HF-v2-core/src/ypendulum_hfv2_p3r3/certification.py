"""P3R3 inherited scales plus deterministic tangent-space construction."""

from __future__ import annotations

import numpy as np

from ypendulum_hfv2_p3r2.certification import (
    COORDINATE_IDS,
    COORDINATE_UNITS,
    STATIONARITY_UNITS,
    CharacteristicScales,
    RestorationActivity,
    characteristic_scales,
    gauge_coordinate,
    gauge_coordinate_row,
    gauge_direction_and_projection,
    scaled_canonical_multipliers,
    select_restoration_activity,
    stationarity_vector,
)

from .assembly import P3R3ContactAssembly


def deterministic_nullspace_basis(
    rows: np.ndarray,
    *,
    rank_relative_tolerance: float,
) -> np.ndarray:
    """Project fixed coordinate axes, then apply deterministic Gram--Schmidt."""

    matrix = np.asarray(rows, dtype=float)
    if matrix.ndim != 2 or not np.all(np.isfinite(matrix)):
        raise ValueError("Tangent exclusions must be one finite matrix.")
    if rank_relative_tolerance <= 0.0:
        raise ValueError("The tangent rank tolerance must be strictly positive.")
    coordinate_count = matrix.shape[1]
    if matrix.shape[0] == 0:
        rank = 0
        projector = np.eye(coordinate_count)
    else:
        _, singular, right = np.linalg.svd(matrix, full_matrices=True)
        rank = 0
        if singular.size and singular[0] > 0.0:
            rank = int(np.count_nonzero(singular > rank_relative_tolerance * singular[0]))
        row_basis = right[:rank]
        projector = np.eye(coordinate_count) - row_basis.T @ row_basis
    required = coordinate_count - rank
    vectors: list[np.ndarray] = []
    threshold = 64.0 * np.finfo(float).eps * max(1, coordinate_count)
    for index in range(coordinate_count):
        candidate = np.array(projector[:, index], copy=True)
        for existing in vectors:
            candidate -= float(existing @ candidate) * existing
        norm = float(np.linalg.norm(candidate))
        if norm <= threshold:
            continue
        candidate /= norm
        pivot = int(np.argmax(np.abs(candidate)))
        if candidate[pivot] < 0.0:
            candidate *= -1.0
        vectors.append(candidate)
        if len(vectors) == required:
            break
    if len(vectors) != required:
        raise np.linalg.LinAlgError(
            "Deterministic coordinate-axis projection did not span the tangent space."
        )
    basis = np.column_stack(vectors) if vectors else np.empty((coordinate_count, 0))
    orthogonality = basis.T @ basis - np.eye(required)
    if required and float(np.linalg.norm(orthogonality, ord=np.inf)) > 1.0e-10:
        raise np.linalg.LinAlgError("Deterministic tangent basis lost orthogonality.")
    return basis


def deterministic_tangent_basis(
    assembly: P3R3ContactAssembly,
    evaluation: object,
    supported_indices: np.ndarray,
    scales: CharacteristicScales,
    *,
    rank_relative_tolerance: float,
) -> np.ndarray:
    """Return the dimensionless support-and-gauge tangent basis."""

    indices = np.asarray(supported_indices, dtype=int)
    jacobian = np.asarray(evaluation.contact.gap_jacobian, dtype=float)
    if indices.ndim != 1 or indices.size == 0:
        raise ValueError("P3R3 tangent construction requires supported contacts.")
    support_rows = jacobian[indices] * scales.coordinate_scales[None, :]
    gauge_row = (gauge_coordinate_row(assembly) * scales.coordinate_scales)[None, :]
    return deterministic_nullspace_basis(
        np.vstack([support_rows, gauge_row]),
        rank_relative_tolerance=rank_relative_tolerance,
    )


__all__ = [
    "COORDINATE_IDS",
    "COORDINATE_UNITS",
    "STATIONARITY_UNITS",
    "CharacteristicScales",
    "RestorationActivity",
    "characteristic_scales",
    "deterministic_nullspace_basis",
    "deterministic_tangent_basis",
    "gauge_coordinate",
    "gauge_coordinate_row",
    "gauge_direction_and_projection",
    "scaled_canonical_multipliers",
    "select_restoration_activity",
    "stationarity_vector",
]

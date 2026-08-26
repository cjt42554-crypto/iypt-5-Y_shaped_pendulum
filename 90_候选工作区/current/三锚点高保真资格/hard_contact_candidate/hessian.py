from __future__ import annotations

import numpy as np

from .types import Array, ProjectedHessianAudit

def audit_projected_hessian(hessian_N_per_m: Array, active_gap_jacobian: Array, *, tolerance_N_per_m: float, rank_tolerance: float | None=None) -> ProjectedHessianAudit:
    """Check PSD on the nullspace of all selected active contact gradients.

    This is a conservative sufficient check.  For weakly active constraints
    with zero multiplier the exact critical cone is larger than a nullspace;
    promotion must therefore retain a separate critical-cone analysis rather
    than relabel this helper as a complete second-order KKT theorem.
    """
    hessian = np.asarray(hessian_N_per_m, dtype=float)
    jacobian = np.asarray(active_gap_jacobian, dtype=float)
    if hessian.ndim != 2 or hessian.shape[0] != hessian.shape[1]:
        raise ValueError('hessian_N_per_m must be square.')
    if jacobian.ndim != 2 or jacobian.shape[1] != hessian.shape[0]:
        raise ValueError('active_gap_jacobian has an incompatible shape.')
    if not np.isfinite(tolerance_N_per_m) or tolerance_N_per_m < 0.0:
        raise ValueError('tolerance_N_per_m must be finite and non-negative.')
    finite = np.all(np.isfinite(hessian)) and np.all(np.isfinite(jacobian))
    if not finite:
        return ProjectedHessianAudit(passed=False, finite=False, tangent_dimension=0, active_constraint_rank=0, minimum_projected_eigenvalue_N_per_m=None, tolerance_N_per_m=float(tolerance_N_per_m), interpretation='NONFINITE_INPUT')
    symmetric = 0.5 * (hessian + hessian.T)
    if jacobian.shape[0] == 0:
        eigenvalues = np.linalg.eigvalsh(symmetric)
        minimum = float(eigenvalues[0]) if eigenvalues.size else float('inf')
        return ProjectedHessianAudit(passed=minimum >= -tolerance_N_per_m, finite=True, tangent_dimension=hessian.shape[0], active_constraint_rank=0, minimum_projected_eigenvalue_N_per_m=minimum, tolerance_N_per_m=float(tolerance_N_per_m), interpretation='UNCONSTRAINED_PSD')
    _, singular_values, right_vectors = np.linalg.svd(jacobian, full_matrices=True)
    threshold = rank_tolerance if rank_tolerance is not None else max(jacobian.shape) * np.finfo(float).eps * max(float(singular_values[0]) if singular_values.size else 0.0, 1.0)
    rank = int(np.count_nonzero(singular_values > threshold))
    tangent = right_vectors[rank:].T
    if tangent.shape[1] == 0:
        minimum: float | None = None
        passed = True
    else:
        projected = tangent.T @ symmetric @ tangent
        projected = 0.5 * (projected + projected.T)
        minimum = float(np.linalg.eigvalsh(projected)[0])
        passed = minimum >= -tolerance_N_per_m
    return ProjectedHessianAudit(passed=passed, finite=True, tangent_dimension=int(tangent.shape[1]), active_constraint_rank=rank, minimum_projected_eigenvalue_N_per_m=minimum, tolerance_N_per_m=float(tolerance_N_per_m), interpretation='SUFFICIENT_NULLSPACE_PSD_NOT_FULL_WEAK_ACTIVE_CRITICAL_CONE')

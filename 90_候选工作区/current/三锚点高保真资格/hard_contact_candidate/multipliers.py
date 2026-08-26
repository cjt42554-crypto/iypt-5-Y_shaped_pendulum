from __future__ import annotations

import numpy as np
from scipy.optimize import lsq_linear

from .types import Array

def estimate_nonnegative_multipliers(energy_gradient_N: Array, gaps_m: Array, gap_jacobian: Array, *, active_gap_m: float) -> Array:
    """Reconstruct non-negative normal reactions on the selected active set."""
    gradient = np.asarray(energy_gradient_N, dtype=float).reshape(-1)
    gaps = np.asarray(gaps_m, dtype=float).reshape(-1)
    jacobian = np.asarray(gap_jacobian, dtype=float)
    if jacobian.shape != (gaps.size, gradient.size):
        raise ValueError('gap_jacobian shape is inconsistent with gaps and gradient.')
    if not np.isfinite(active_gap_m) or active_gap_m < 0.0:
        raise ValueError('active_gap_m must be finite and non-negative.')
    active = np.flatnonzero(gaps <= active_gap_m)
    multipliers = np.zeros(gaps.size, dtype=float)
    if active.size == 0:
        return multipliers
    system = jacobian[active].T
    solution = lsq_linear(system, gradient, bounds=(0.0, np.inf), method='trf', lsmr_tol='auto', max_iter=max(100, 10 * active.size))
    if not solution.success or not np.all(np.isfinite(solution.x)):
        raise RuntimeError(f'Could not reconstruct finite non-negative contact multipliers: {solution.message}')
    multipliers[active] = solution.x
    return multipliers

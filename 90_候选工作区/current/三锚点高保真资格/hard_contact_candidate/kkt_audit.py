from __future__ import annotations

import numpy as np

from .types import Array, KKTAudit, KKTThresholds

def audit_static_kkt(energy_gradient_N: Array, gaps_m: Array, gap_jacobian: Array, multipliers_N: Array, *, thresholds: KKTThresholds=KKTThresholds()) -> KKTAudit:
    """Audit ``grad(E) - J_g.T @ lambda = 0`` and unilateral complementarity."""
    gradient = np.asarray(energy_gradient_N, dtype=float).reshape(-1)
    gaps = np.asarray(gaps_m, dtype=float).reshape(-1)
    jacobian = np.asarray(gap_jacobian, dtype=float)
    multipliers = np.asarray(multipliers_N, dtype=float).reshape(-1)
    if jacobian.shape != (gaps.size, gradient.size):
        raise ValueError('gap_jacobian shape is inconsistent with gaps and gradient.')
    if multipliers.shape != gaps.shape:
        raise ValueError('multipliers_N must have one value per gap.')
    arrays = (gradient, gaps, jacobian, multipliers)
    finite = all((np.all(np.isfinite(values)) for values in arrays))
    if not finite:
        stationarity = np.full_like(gradient, np.nan)
        return KKTAudit(passed=False, finite=False, primal_violation_m=float('inf'), stationarity_residual_N=float('inf'), dual_violation_N=float('inf'), complementarity_residual_Nm=float('inf'), minimum_gap_m=float('-inf'), minimum_multiplier_N=float('-inf'), active_contact_count=0, multiplier_supported_contact_count=0, stationarity_vector_N=stationarity)
    stationarity = gradient - jacobian.T @ multipliers
    primal_violation = float(max(0.0, -float(np.min(gaps)))) if gaps.size else 0.0
    dual_violation = float(max(0.0, -float(np.min(multipliers)))) if multipliers.size else 0.0
    complementarity = float(np.max(np.abs(multipliers * gaps))) if gaps.size else 0.0
    stationarity_residual = float(np.max(np.abs(stationarity))) if stationarity.size else 0.0
    passed = primal_violation <= thresholds.primal_gap_m and stationarity_residual <= thresholds.stationarity_N and (dual_violation <= thresholds.dual_force_N) and (complementarity <= thresholds.complementarity_Nm)
    return KKTAudit(passed=passed, finite=True, primal_violation_m=primal_violation, stationarity_residual_N=stationarity_residual, dual_violation_N=dual_violation, complementarity_residual_Nm=complementarity, minimum_gap_m=float(np.min(gaps)) if gaps.size else float('inf'), minimum_multiplier_N=float(np.min(multipliers)) if multipliers.size else float('inf'), active_contact_count=int(np.count_nonzero(gaps <= thresholds.active_gap_m)), multiplier_supported_contact_count=int(np.count_nonzero(multipliers > thresholds.dual_force_N)), stationarity_vector_N=stationarity)

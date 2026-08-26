from __future__ import annotations
from typing import Any
import numpy as np
from scipy.optimize import NonlinearConstraint, minimize
from .kkt import audit_static_kkt, estimate_nonnegative_multipliers
from .types import Array, EnergyWithGradient, GapsWithJacobian, KKTThresholds, StaticContactResult

def solve_static_contact_problem(objective: EnergyWithGradient, gaps: GapsWithJacobian, initial_state: Array, *, thresholds: KKTThresholds=KKTThresholds(), max_iterations: int=1000, ftol_J: float=1e-14, optimizer_options: dict[str, Any] | None=None) -> StaticContactResult:
    x0 = np.asarray(initial_state, dtype=float).reshape(-1)
    if not np.all(np.isfinite(x0)):
        raise ValueError('initial_state must be finite.')
    if max_iterations < 1 or not np.isfinite(ftol_J) or ftol_J < 0.0:
        raise ValueError('Invalid static-contact optimizer controls.')

    def fun(state: Array) -> float:
        energy, gradient = objective(np.asarray(state, dtype=float))
        if not np.isfinite(energy) or not np.all(np.isfinite(gradient)):
            raise FloatingPointError('Objective returned non-finite values.')
        return float(energy)

    def jac(state: Array) -> Array:
        _, gradient = objective(np.asarray(state, dtype=float))
        return np.asarray(gradient, dtype=float).reshape(-1)

    def gap_values(state: Array) -> Array:
        values, jacobian = gaps(np.asarray(state, dtype=float))
        values_array = np.asarray(values, dtype=float).reshape(-1)
        jacobian_array = np.asarray(jacobian, dtype=float)
        if jacobian_array.shape != (values_array.size, x0.size):
            raise ValueError('Gap callback returned an incompatible Jacobian.')
        return values_array

    def gap_jacobian(state: Array) -> Array:
        values, jacobian = gaps(np.asarray(state, dtype=float))
        values_array = np.asarray(values, dtype=float).reshape(-1)
        jacobian_array = np.asarray(jacobian, dtype=float)
        if jacobian_array.shape != (values_array.size, x0.size):
            raise ValueError('Gap callback returned an incompatible Jacobian.')
        return jacobian_array
    initial_gaps = gap_values(x0)
    constraint = NonlinearConstraint(gap_values, lb=np.zeros(initial_gaps.size), ub=np.full(initial_gaps.size, np.inf), jac=gap_jacobian)
    options: dict[str, Any] = {'maxiter': int(max_iterations), 'ftol': float(ftol_J), 'disp': False}
    if optimizer_options:
        options.update(optimizer_options)
    result = minimize(fun, x0, method='SLSQP', jac=jac, constraints=[constraint], options=options)
    state = np.asarray(result.x, dtype=float)
    energy, gradient = objective(state)
    gap_values_final, gap_jacobian_final = gaps(state)
    gradient_array = np.asarray(gradient, dtype=float).reshape(-1)
    gap_values_array = np.asarray(gap_values_final, dtype=float).reshape(-1)
    gap_jacobian_array = np.asarray(gap_jacobian_final, dtype=float)
    multipliers = estimate_nonnegative_multipliers(gradient_array, gap_values_array, gap_jacobian_array, active_gap_m=thresholds.active_gap_m)
    kkt = audit_static_kkt(gradient_array, gap_values_array, gap_jacobian_array, multipliers, thresholds=thresholds)
    return StaticContactResult(state=state, energy_J=float(energy), gradient_N=gradient_array, gaps_m=gap_values_array, gap_jacobian=gap_jacobian_array, multipliers_N=multipliers, optimizer_success=bool(result.success), optimizer_status=int(result.status), optimizer_message=str(result.message), optimizer_iterations=int(getattr(result, 'nit', 0)), kkt=kkt, raw_result=result)

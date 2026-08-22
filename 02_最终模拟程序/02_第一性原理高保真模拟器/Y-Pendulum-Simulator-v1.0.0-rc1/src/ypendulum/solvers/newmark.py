"""Implicit second-order Newmark integration for the H1 cable system.

This solver is an additional, auditable integration path. It does not replace
Radau as the frozen default. Its main purpose is to preserve the sparse
second-order mechanical structure ``M q_ddot = F(q, q_dot, t)`` instead of
forming the generally dense first-order Jacobian ``M^{-1} dF/dq``.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
import warnings

import numpy as np
from scipy.sparse.linalg import MatrixRankWarning, spsolve

from ypendulum.config.models import SimulationConfig
from ypendulum.config.units import to_si
from ypendulum.models.full_cable import FullCableModel


@dataclass(frozen=True)
class NewmarkIntegration:
    time: np.ndarray
    state: np.ndarray
    runtime_seconds: float
    metadata: dict[str, float | int | str]


def _residual_and_tangent(
    model: FullCableModel,
    t: float,
    q: np.ndarray,
    q_predictor: np.ndarray,
    v_predictor: np.ndarray,
    *,
    beta: float,
    gamma: float,
    dt: float,
    tangent: bool,
):
    a = (q - q_predictor) / (beta * dt * dt)
    v = v_predictor + gamma * dt * a
    ev = model.evaluate(t, q, v, compute_tangent=tangent)
    residual = np.asarray(model.mass_ff @ a).reshape(-1) - ev.free_force
    if not tangent:
        return residual, None, v, a, ev
    assert ev.tangent_position is not None and ev.tangent_velocity is not None
    fd = model.topology.free_dofs
    kff = ev.tangent_position[fd][:, fd].tocsr()
    cff = ev.tangent_velocity[fd][:, fd].tocsr()
    effective = (
        model.mass_ff * (1.0 / (beta * dt * dt))
        - kff
        - cff * (gamma / (beta * dt))
    ).tocsr()
    return residual, effective, v, a, ev


def integrate_newmark(
    cfg: SimulationConfig,
    model: FullCableModel,
    y0: np.ndarray,
    t_eval: np.ndarray,
    *,
    max_step: float,
) -> NewmarkIntegration:
    """Integrate H1 on requested output times using implicit Newmark substeps."""

    if t_eval.ndim != 1 or t_eval.size < 2 or np.any(np.diff(t_eval) <= 0):
        raise ValueError("Newmark t_eval must be strictly increasing with at least two points.")
    beta = float(cfg.solver.newmark_beta)
    gamma = float(cfg.solver.newmark_gamma)
    max_iterations = int(cfg.solver.newmark_max_iterations)
    force_tolerance = float(to_si(cfg.solver.newmark_force_tolerance, default_unit="N"))
    line_min = float(cfg.solver.newmark_line_search_min)
    if force_tolerance <= 0:
        raise ValueError("newmark_force_tolerance must be positive.")

    q, v = model.split_state(np.asarray(y0, dtype=float))
    q = q.copy()
    v = v.copy()
    a = model.acceleration(float(t_eval[0]), q, v)
    n = model.position_dof_count
    state = np.empty((t_eval.size, 2 * n), dtype=float)
    state[0] = np.concatenate([q, v])

    total_substeps = 0
    total_newton = 0
    maximum_newton = 0
    maximum_residual = 0.0
    minimum_dt = np.inf
    maximum_dt = 0.0
    start_clock = perf_counter()

    t = float(t_eval[0])
    for out_index in range(1, t_eval.size):
        target = float(t_eval[out_index])
        while t < target - 10.0 * np.finfo(float).eps * max(1.0, abs(target)):
            dt = min(float(max_step), target - t)
            if dt <= 0.0:
                raise FloatingPointError("Newmark produced a non-positive substep.")
            t_next = t + dt
            minimum_dt = min(minimum_dt, dt)
            maximum_dt = max(maximum_dt, dt)

            q_predictor = q + dt * v + dt * dt * (0.5 - beta) * a
            v_predictor = v + dt * (1.0 - gamma) * a
            q_trial = q_predictor + beta * dt * dt * a

            converged = False
            accepted_v = v
            accepted_a = a
            for iteration in range(1, max_iterations + 1):
                residual, tangent, trial_v, trial_a, _ev = _residual_and_tangent(
                    model,
                    t_next,
                    q_trial,
                    q_predictor,
                    v_predictor,
                    beta=beta,
                    gamma=gamma,
                    dt=dt,
                    tangent=True,
                )
                norm_inf = float(np.max(np.abs(residual)))
                maximum_residual = max(maximum_residual, norm_inf)
                force_scale = max(
                    model.bob_mass * float(np.linalg.norm(model.gravity)),
                    float(np.max(np.abs(model.gravity_force_full))),
                    1.0,
                )
                target_tol = max(force_tolerance, float(cfg.solver.rtol or 0.0) * force_scale)
                if norm_inf <= target_tol:
                    converged = True
                    accepted_v = trial_v
                    accepted_a = trial_a
                    total_newton += iteration
                    maximum_newton = max(maximum_newton, iteration)
                    break
                assert tangent is not None
                with warnings.catch_warnings():
                    warnings.simplefilter("error", MatrixRankWarning)
                    try:
                        increment = np.asarray(spsolve(tangent.tocsc(), -residual), dtype=float)
                    except (MatrixRankWarning, RuntimeError, ValueError) as exc:
                        raise RuntimeError(
                            f"Newmark effective tangent solve failed at t={t_next:.12g} s."
                        ) from exc
                if not np.all(np.isfinite(increment)):
                    raise RuntimeError(
                        f"Newmark effective tangent returned a non-finite increment at t={t_next:.12g} s."
                    )

                alpha = 1.0
                accepted = False
                while alpha >= line_min:
                    candidate = q_trial + alpha * increment
                    candidate_residual, _tan, candidate_v, candidate_a, _ = _residual_and_tangent(
                        model,
                        t_next,
                        candidate,
                        q_predictor,
                        v_predictor,
                        beta=beta,
                        gamma=gamma,
                        dt=dt,
                        tangent=False,
                    )
                    candidate_norm = float(np.max(np.abs(candidate_residual)))
                    if candidate_norm < norm_inf or candidate_norm <= target_tol:
                        q_trial = candidate
                        accepted_v = candidate_v
                        accepted_a = candidate_a
                        accepted = True
                        break
                    alpha *= 0.5
                if not accepted:
                    q_trial = q_trial + increment

            if not converged:
                residual, _tan, _v, _a, ev = _residual_and_tangent(
                    model,
                    t_next,
                    q_trial,
                    q_predictor,
                    v_predictor,
                    beta=beta,
                    gamma=gamma,
                    dt=dt,
                    tangent=False,
                )
                raise RuntimeError(
                    "Implicit Newmark failed to converge: "
                    f"t={t_next:.12g} s, dt={dt:.6g} s, "
                    f"residual_inf={np.max(np.abs(residual)):.6g} N, "
                    f"active_elements={int(np.sum(ev.active))}/{ev.active.size}, "
                    f"iterations={max_iterations}. Reduce max_step/output_dt or "
                    "increase independently calibrated physical damping."
                )

            q = q_trial
            v = accepted_v
            a = accepted_a
            t = t_next
            total_substeps += 1

        state[out_index] = np.concatenate([q, v])

    runtime = perf_counter() - start_clock
    metadata: dict[str, float | int | str] = {
        "solver_method": "Newmark",
        "newmark_beta": beta,
        "newmark_gamma": gamma,
        "newmark_force_tolerance_N": force_tolerance,
        "newmark_substeps": total_substeps,
        "newmark_total_iterations": total_newton,
        "newmark_max_iterations_used": maximum_newton,
        "newmark_max_residual_encountered_N": maximum_residual,
        "newmark_minimum_substep_s": float(minimum_dt),
        "newmark_maximum_substep_s": float(maximum_dt),
        "jacobian_kind": "sparse_effective_second_order_exact_piecewise",
        "nfev": 0,
        "njev": total_newton,
        "nlu": total_newton,
    }
    return NewmarkIntegration(np.asarray(t_eval), state, runtime, metadata)

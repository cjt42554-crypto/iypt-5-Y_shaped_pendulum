"""Radau/BDF integration and post-processing for the H1 model."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import numpy as np
from scipy import sparse
from scipy.integrate import cumulative_trapezoid, solve_ivp

from ypendulum.analysis.tension_events import detect_tension_events
from ypendulum.config.models import SimulationConfig
from ypendulum.config.units import to_si
from ypendulum.models.full_cable import FullCableModel
from ypendulum.models.state import SimulationResult, StaticEquilibrium

from .static import build_initial_state
from .newmark import integrate_newmark


@dataclass(frozen=True)
class SolverSettings:
    rtol: float
    position_atol: float
    velocity_atol: float
    max_step: float


def solver_settings(cfg: SimulationConfig, model: FullCableModel) -> SolverSettings:
    defaults = {
        "quick": (1e-6, 1e-8, 1e-8),
        "production": (1e-8, 1e-10, 1e-10),
        "reference": (1e-10, 1e-12, 1e-12),
    }
    rtol, patol, vatol = defaults[cfg.solver.profile]
    if cfg.solver.rtol is not None:
        rtol = float(cfg.solver.rtol)
    if cfg.solver.position_atol is not None:
        patol = float(to_si(cfg.solver.position_atol, default_unit="m"))
    if cfg.solver.velocity_atol is not None:
        vatol = float(to_si(cfg.solver.velocity_atol, default_unit="m/s"))
    times = model.characteristic_times()
    max_step = times["pendulum_period_estimate"] / 200.0
    if cfg.solver.resolve_longitudinal_waves:
        max_step = min(max_step, times["minimum_element_wave_crossing"] / 20.0)
    if cfg.solver.max_step != "auto":
        max_step = float(to_si(cfg.solver.max_step, default_unit="s"))
    output_dt = float(to_si(cfg.solver.output_dt, default_unit="s"))
    max_step = min(max_step, output_dt)
    return SolverSettings(rtol, patol, vatol, max_step)


def _sparse_preconditioner_jacobian(model: FullCableModel, t: float, y: np.ndarray):
    """Sparse mass-lumped Jacobian used only as a Newton preconditioner.

    The RHS still uses the configured consistent mass matrix.  For large meshes,
    an exact elimination would make the first-order Jacobian dense; this local
    approximation preserves cable sparsity and materially reduces Radau factorisation
    cost.  Its use is recorded in diagnostics.
    """

    qf, vf = model.split_state(y)
    ev = model.evaluate(t, qf, vf, compute_tangent=True)
    assert ev.tangent_position is not None and ev.tangent_velocity is not None
    fd = model.topology.free_dofs
    kff = ev.tangent_position[fd][:, fd].tocsr()
    cff = ev.tangent_velocity[fd][:, fd].tocsr()
    lumped = np.asarray(model.mass_ff.sum(axis=1)).reshape(-1)
    if np.any(lumped <= 0):
        lumped = model.mass_ff.diagonal()
    inv = sparse.diags(1.0 / lumped)
    n = model.position_dof_count
    return sparse.bmat(
        [
            [sparse.csr_matrix((n, n)), sparse.eye(n, format="csr")],
            [inv @ kff, inv @ cff],
        ],
        format="csr",
    )


def _postprocess(
    model: FullCableModel,
    time: np.ndarray,
    state: np.ndarray,
    *,
    runtime_s: float,
    solver_meta: dict[str, Any],
) -> SimulationResult:
    nt = time.size
    nnode = model.topology.node_count
    nelem = model.topology.elements.count
    positions = np.empty((nt, nnode, 3), dtype=float)
    velocities = np.empty_like(positions)
    tension = np.empty((nt, nelem), dtype=float)
    stretch = np.empty_like(tension)
    active = np.empty((nt, nelem), dtype=bool)
    reaction_a = np.empty((nt, 3), dtype=float)
    reaction_b = np.empty((nt, 3), dtype=float)
    energy_keys = [
        "kinetic",
        "gravitational",
        "elastic",
        "mechanical",
        "material_dissipation_rate",
        "aero_relative_dissipation_rate",
        "aero_work_rate",
        "support_work_rate",
    ]
    snapshots = {key: np.empty(nt, dtype=float) for key in energy_keys}

    n = model.position_dof_count
    for k, t in enumerate(time):
        qf = state[k, :n]
        vf = state[k, n:]
        ev = model.evaluate(float(t), qf, vf, compute_tangent=False)
        positions[k] = ev.full_positions
        velocities[k] = ev.full_velocities
        tension[k] = ev.tension
        stretch[k] = ev.stretch
        active[k] = ev.active
        reaction_a[k], reaction_b[k] = model.support_reactions(float(t), qf, vf, ev)
        snapshot = model.energy_snapshot(float(t), qf, vf, ev)
        for key in energy_keys:
            snapshots[key][k] = snapshot[key]

    dmat = np.concatenate(
        [[0.0], cumulative_trapezoid(snapshots["material_dissipation_rate"], time)]
    )
    daero = np.concatenate(
        [[0.0], cumulative_trapezoid(snapshots["aero_relative_dissipation_rate"], time)]
    )
    waero = np.concatenate([[0.0], cumulative_trapezoid(snapshots["aero_work_rate"], time)])
    wsupport = np.concatenate(
        [[0.0], cumulative_trapezoid(snapshots["support_work_rate"], time)]
    )
    mech = snapshots["mechanical"]
    scale = max(
        model.bob_mass * float(np.linalg.norm(model.gravity)) * model.topology.characteristic_length,
        abs(float(mech[0])),
        1e-12,
    )
    # E(t)-E(0) + D_material + D_aero-relative
    #              - W_air - W_support = 0.
    residual = (mech - mech[0] + dmat + daero - waero - wsupport) / scale
    energy = {
        **snapshots,
        "dissipation_material": dmat,
        "dissipation_aero_relative": daero,
        "aero_work": waero,
        "support_work": wsupport,
        "balance_residual": residual,
    }
    events = detect_tension_events(
        time, tension, active, model.topology.cable_slices
    )
    rest = model.topology.elements.rest_length
    strain = stretch / rest[None, :]
    per_cable: dict[str, dict[str, float]] = {}
    for name, sl in model.topology.cable_slices.items():
        branch_active = np.all(active[:, sl] & (tension[:, sl] > 0.0), axis=1)
        per_cable[name] = {
            "minimum_tension_N": float(np.min(tension[:, sl])),
            "maximum_tension_N": float(np.max(tension[:, sl])),
            "maximum_tensile_strain": float(np.max(np.maximum(strain[:, sl], 0.0))),
            "minimum_engineering_strain": float(np.min(strain[:, sl])),
            "element_active_fraction": float(np.mean(active[:, sl])),
            "branch_transmitting_fraction": float(np.mean(branch_active)),
        }
    output_dt = float(np.median(np.diff(time))) if time.size > 1 else float("nan")
    times = model.characteristic_times()
    warnings_list: list[str] = []
    if np.isfinite(output_dt) and output_dt > 0.5 * times["minimum_element_wave_crossing"]:
        warnings_list.append(
            "Stored output does not resolve the fastest element wave-crossing time; "
            "use internal-step/convergence data for retension peaks."
        )
    if not model.cfg.solver.resolve_longitudinal_waves:
        warnings_list.append(
            "resolve_longitudinal_waves=false: the run is intended primarily for low-frequency motion, "
            "not a converged cable-wave or peak-tension prediction."
        )
    max_energy_residual = float(np.max(np.abs(residual)))
    if max_energy_residual > 1.0e-4:
        warnings_list.append(
            f"Energy-balance residual {max_energy_residual:.3e} exceeds the production acceptance target."
        )
    if model.material_extrapolation_seen:
        warnings_list.append(
            "One or more tabulated material curves were extrapolated beyond independent calibration data."
        )

    diagnostics = {
        **model.diagnostics(),
        **solver_meta,
        "runtime_seconds": runtime_s,
        "max_abs_energy_balance_residual": max_energy_residual,
        "minimum_tension": float(np.min(tension)),
        "maximum_tension": float(np.max(tension)),
        "active_fraction": float(np.mean(active)),
        "maximum_tensile_strain": float(np.max(np.maximum(strain, 0.0))),
        "minimum_engineering_strain": float(np.min(strain)),
        "maximum_support_reaction_N": float(
            max(np.max(np.linalg.norm(reaction_a, axis=1)), np.max(np.linalg.norm(reaction_b, axis=1)))
        ),
        "stored_output_dt_s": output_dt,
        "stored_samples_per_fastest_wave_crossing": float(
            times["minimum_element_wave_crossing"] / output_dt
        ) if np.isfinite(output_dt) and output_dt > 0 else None,
        "per_cable": per_cable,
        "scientific_warnings": warnings_list,
    }
    return SimulationResult(
        time=time,
        positions=positions,
        velocities=velocities,
        tension=tension,
        stretch=stretch,
        active=active,
        energy=energy,
        reactions={"support_A": reaction_a, "support_B": reaction_b},
        events=events,
        diagnostics=diagnostics,
        model_name="H1",
        claim_level=model.cfg.run.claim_level,
    )


def simulate_full(
    cfg: SimulationConfig,
    *,
    model: FullCableModel | None = None,
    equilibrium: StaticEquilibrium | None = None,
) -> SimulationResult:
    model = FullCableModel(cfg) if model is None else model
    y0, t0, equilibrium_used = build_initial_state(cfg, model, equilibrium)
    t_end_rel = float(to_si(cfg.solver.t_end, default_unit="s"))
    t_end = t0 + t_end_rel
    output_dt = float(to_si(cfg.solver.output_dt, default_unit="s"))
    count = int(np.floor(t_end_rel / output_dt + 1e-12))
    t_eval = t0 + np.arange(count + 1) * output_dt
    if t_eval[-1] < t_end - 1e-12:
        t_eval = np.append(t_eval, t_end)
    settings = solver_settings(cfg, model)
    atol = np.concatenate(
        [
            np.full(model.position_dof_count, settings.position_atol),
            np.full(model.position_dof_count, settings.velocity_atol),
        ]
    )

    jac = None
    jacobian_kind = "finite_difference"
    if cfg.solver.analytic_jacobian:
        if model._mass_is_diagonal or model.state_size <= 900:
            jac = model.jacobian
            jacobian_kind = (
                "analytic_internal_and_velocity_aero_partial"
                if np.any(model._cable_drag_enabled)
                else "exact_analytic"
            )
        else:
            jac = lambda t, y: _sparse_preconditioner_jacobian(model, t, y)
            jacobian_kind = "sparse_mass_lumped_preconditioner"

    if cfg.solver.method == "Newmark":
        nm = integrate_newmark(cfg, model, y0, t_eval, max_step=settings.max_step)
        state = nm.state
        metadata = {
            **nm.metadata,
            "solver_profile": cfg.solver.profile,
            "rtol": settings.rtol,
            "position_atol": settings.position_atol,
            "velocity_atol": settings.velocity_atol,
            "max_step": settings.max_step,
            "static_force_residual": None
            if equilibrium_used is None
            else equilibrium_used.force_residual_max,
            "static_iterations": None if equilibrium_used is None else equilibrium_used.iterations,
            "static_metadata": None if equilibrium_used is None else equilibrium_used.metadata,
        }
        return _postprocess(
            model,
            nm.time,
            state,
            runtime_s=nm.runtime_seconds,
            solver_meta=metadata,
        )

    start = perf_counter()
    sol = solve_ivp(
        model.rhs,
        (t0, t_end),
        y0,
        method=cfg.solver.method,
        t_eval=t_eval,
        rtol=settings.rtol,
        atol=atol,
        max_step=settings.max_step,
        jac=jac,
        vectorized=False,
    )
    runtime = perf_counter() - start
    if not sol.success:
        raise RuntimeError(
            f"H1 {cfg.solver.method} integration failed at t={sol.t[-1] if sol.t.size else t0}: "
            f"{sol.message}"
        )
    state = sol.y.T
    metadata = {
        "solver_method": cfg.solver.method,
        "solver_profile": cfg.solver.profile,
        "rtol": settings.rtol,
        "position_atol": settings.position_atol,
        "velocity_atol": settings.velocity_atol,
        "max_step": settings.max_step,
        "jacobian_kind": jacobian_kind,
        "nfev": int(sol.nfev),
        "njev": int(sol.njev),
        "nlu": int(sol.nlu),
        "static_force_residual": None
        if equilibrium_used is None
        else equilibrium_used.force_residual_max,
        "static_iterations": None if equilibrium_used is None else equilibrium_used.iterations,
        "static_metadata": None if equilibrium_used is None else equilibrium_used.metadata,
    }
    return _postprocess(model, sol.t, state, runtime_s=runtime, solver_meta=metadata)

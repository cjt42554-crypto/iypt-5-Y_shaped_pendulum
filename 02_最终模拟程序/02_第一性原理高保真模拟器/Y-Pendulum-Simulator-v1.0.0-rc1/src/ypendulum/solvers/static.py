"""Static equilibrium and physically consistent release-state construction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import h5py
import numpy as np
from scipy import sparse
from scipy.linalg import eigvalsh
from scipy.optimize import minimize
from scipy.sparse.linalg import MatrixRankWarning, lsmr, spsolve
import warnings

from ypendulum.config.models import SimulationConfig
from ypendulum.config.units import as_vector3, to_si
from ypendulum.elements import evaluate_cable_elements
from ypendulum.geometry import reduced_geometry_from_loaded_state, torus_point, torus_velocity
from ypendulum.models.full_cable import FullCableModel
from ypendulum.models.state import StaticEquilibrium


class StaticEquilibriumError(RuntimeError):
    """Static equilibrium could not be established to the configured force tolerance."""


def _node_free_indices(model: FullCableModel, nodes: Iterable[int]) -> np.ndarray:
    node_to_offset = {
        int(node): 3 * idx for idx, node in enumerate(model.topology.free_nodes.tolist())
    }
    out: list[int] = []
    for node in nodes:
        if int(node) not in node_to_offset:
            continue
        base = node_to_offset[int(node)]
        out.extend((base, base + 1, base + 2))
    return np.asarray(out, dtype=np.int64)


def _redistribute_chain_positions(model: FullCableModel, full_positions: np.ndarray) -> None:
    for path in model.topology.cable_node_paths.values():
        start = full_positions[path[0]].copy()
        end = full_positions[path[-1]].copy()
        count = len(path) - 1
        for k, node in enumerate(path[1:-1], start=1):
            alpha = k / count
            full_positions[node] = (1.0 - alpha) * start + alpha * end


def _energy_minimise(
    model: FullCableModel,
    q_free: np.ndarray,
    variable_indices: np.ndarray,
    gravity_scale: float,
    fixed_values: dict[int, np.ndarray],
    max_iterations: int,
) -> np.ndarray:
    x0 = q_free[variable_indices].copy()
    scale_length = model.topology.characteristic_length
    energy_scale = max(model.bob_mass * np.linalg.norm(model.gravity) * scale_length, 1e-12)

    def unpack(x: np.ndarray) -> np.ndarray:
        q = q_free.copy()
        q[variable_indices] = x
        for node, value in fixed_values.items():
            idx = _node_free_indices(model, [node])
            q[idx] = value
        return q

    def objective(x: np.ndarray) -> tuple[float, np.ndarray]:
        q = unpack(x)
        ev = model.evaluate(
            0.0,
            q,
            np.zeros_like(q),
            compute_tangent=False,
            gravity_scale=gravity_scale,
            include_aero=False,
        )
        full = ev.full_positions.reshape(-1)
        potential_g = -gravity_scale * float(full @ model.gravity_force_full.reshape(-1))
        potential_b = -gravity_scale * float(
            np.dot(ev.full_positions[model.topology.bob_node], model.buoyancy)
        )
        value = (ev.elastic_energy + potential_g + potential_b) / energy_scale
        grad = -ev.free_force[variable_indices] / energy_scale
        return value, grad

    res = minimize(
        fun=lambda x: objective(x)[0],
        x0=x0,
        jac=lambda x: objective(x)[1],
        method="L-BFGS-B",
        options={"maxiter": max_iterations, "ftol": 1e-14, "gtol": 1e-10, "maxls": 50},
    )
    q = unpack(res.x)
    return q


def _newton_refine(
    model: FullCableModel,
    q_free: np.ndarray,
    variable_indices: np.ndarray,
    gravity_scale: float,
    fixed_values: dict[int, np.ndarray],
    force_tolerance: float,
    max_iterations: int,
    line_search_min: float,
) -> tuple[np.ndarray, int, float, bool]:
    q = q_free.copy()
    velocity = np.zeros_like(q)
    for iteration in range(1, max_iterations + 1):
        for node, value in fixed_values.items():
            idx = _node_free_indices(model, [node])
            q[idx] = value
        ev = model.evaluate(
            0.0,
            q,
            velocity,
            compute_tangent=True,
            gravity_scale=gravity_scale,
            include_aero=False,
        )
        residual = ev.free_force[variable_indices]
        norm_inf = float(np.max(np.abs(residual))) if residual.size else 0.0
        if norm_inf <= force_tolerance:
            return q, iteration, norm_inf, True
        assert ev.tangent_position is not None
        fd = model.topology.free_dofs
        K = ev.tangent_position[fd][:, fd].tocsr()[variable_indices][:, variable_indices]
        # A tiny scale-aware regularisation protects near-slack transverse modes without
        # changing a well-conditioned taut equilibrium.
        diag_scale = max(float(np.max(np.abs(K.diagonal()))) if K.shape[0] else 1.0, 1.0)
        Kreg = K - sparse.eye(K.shape[0], format="csr") * (1e-12 * diag_scale)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", MatrixRankWarning)
            step = spsolve(Kreg.tocsc(), -residual)
        if not np.all(np.isfinite(step)):
            step = lsmr(Kreg, -residual, atol=1e-12, btol=1e-12, maxiter=5 * K.shape[0])[0]
        step_norm = float(np.linalg.norm(step))
        max_step = 0.2 * model.topology.characteristic_length * np.sqrt(max(K.shape[0], 1))
        if step_norm > max_step:
            step *= max_step / step_norm

        alpha = 1.0
        accepted = False
        while alpha >= line_search_min:
            trial = q.copy()
            trial[variable_indices] += alpha * step
            for node, value in fixed_values.items():
                idx = _node_free_indices(model, [node])
                trial[idx] = value
            try:
                trial_ev = model.evaluate(
                    0.0,
                    trial,
                    velocity,
                    compute_tangent=False,
                    gravity_scale=gravity_scale,
                    include_aero=False,
                )
            except FloatingPointError:
                alpha *= 0.5
                continue
            trial_norm = float(np.max(np.abs(trial_ev.free_force[variable_indices])))
            if trial_norm < norm_inf * (1.0 - 1e-4 * alpha) or trial_norm < force_tolerance:
                q = trial
                accepted = True
                break
            alpha *= 0.5
        if not accepted:
            return q, iteration, norm_inf, False
    ev = model.evaluate(
        0.0,
        q,
        velocity,
        compute_tangent=False,
        gravity_scale=gravity_scale,
        include_aero=False,
    )
    final = float(np.max(np.abs(ev.free_force[variable_indices])))
    return q, max_iterations, final, final <= force_tolerance



def _static_stability_audit(
    model: FullCableModel,
    q_free: np.ndarray,
    variable_indices: np.ndarray,
) -> dict[str, float | int | bool]:
    """Audit local energetic stability of the active tensile equilibrium.

    The audit uses the same force tangent and mass matrix as the nonlinear H1
    equations.  A materially negative generalized stiffness eigenvalue denotes
    an unstable equilibrium branch.  Near-zero values are reported separately
    because unilateral slack modes can be neutrally constrained rather than
    conventionally stable.
    """

    velocity = np.zeros_like(q_free)
    evaluation = model.evaluate(
        0.0,
        q_free,
        velocity,
        compute_tangent=True,
        gravity_scale=1.0,
        include_aero=False,
    )
    assert evaluation.tangent_position is not None
    free_dofs = model.topology.free_dofs
    stiffness = -evaluation.tangent_position[free_dofs][:, free_dofs]
    stiffness = stiffness[variable_indices][:, variable_indices].toarray()
    mass = model.mass_ff[variable_indices][:, variable_indices].toarray()
    stiffness = 0.5 * (stiffness + stiffness.T)
    mass = 0.5 * (mass + mass.T)
    if stiffness.size == 0:
        return {
            "stable": True,
            "minimum_generalized_eigenvalue_s-2": float("inf"),
            "negative_mode_count": 0,
            "near_zero_mode_count": 0,
        }
    count = min(12, stiffness.shape[0])
    values = eigvalsh(
        stiffness,
        mass,
        subset_by_index=(0, count - 1),
        check_finite=True,
    )
    scale = max(float(np.max(np.abs(values))), 1.0)
    tolerance = max(1.0e-8, 1.0e-8 * scale)
    negative = int(np.count_nonzero(values < -tolerance))
    near_zero = int(np.count_nonzero(np.abs(values) <= tolerance))
    return {
        "stable": negative == 0,
        "minimum_generalized_eigenvalue_s-2": float(values[0]),
        "negative_mode_count": negative,
        "near_zero_mode_count": near_zero,
        "stability_eigenvalue_tolerance_s-2": tolerance,
        "audited_lowest_mode_count": int(count),
    }

def _solve_conditioned_equilibrium(
    model: FullCableModel,
    initial_positions: np.ndarray,
    *,
    fixed_nodes: dict[int, np.ndarray] | None = None,
) -> StaticEquilibrium:
    fixed_nodes = {} if fixed_nodes is None else dict(fixed_nodes)
    q0 = model.topology.pack_free(initial_positions)
    fixed_indices = _node_free_indices(model, fixed_nodes.keys())
    all_indices = np.arange(model.position_dof_count, dtype=np.int64)
    variable = np.setdiff1d(all_indices, fixed_indices, assume_unique=False)
    fixed_flat = {node: np.asarray(value, dtype=float).reshape(3) for node, value in fixed_nodes.items()}
    force_tol = float(to_si(model.cfg.solver.static.force_tolerance, default_unit="N"))
    max_iter = model.cfg.solver.static.max_iterations
    continuation_steps = max(model.cfg.solver.static.continuation_steps, 1)
    line_min = model.cfg.solver.static.line_search_min

    q = q0.copy()
    total_iterations = 0
    converged = False
    residual = np.inf
    # The first small load step activates geometric stiffness; starting at exactly zero gravity
    # would leave transverse cable directions singular.
    scales = np.linspace(1.0 / continuation_steps, 1.0, continuation_steps)
    for scale in scales:
        q, it, residual, converged = _newton_refine(
            model,
            q,
            variable,
            float(scale),
            fixed_flat,
            max(force_tol * max(float(scale), 0.1), force_tol),
            max_iter,
            line_min,
        )
        total_iterations += it
        if not converged:
            q = _energy_minimise(
                model,
                q,
                variable,
                float(scale),
                fixed_flat,
                max_iterations=max_iter * 4,
            )
            q, it2, residual, converged = _newton_refine(
                model,
                q,
                variable,
                float(scale),
                fixed_flat,
                max(force_tol * max(float(scale), 0.1), force_tol),
                max_iter,
                line_min,
            )
            total_iterations += it2
        if not converged and scale < 1.0:
            # Continue cautiously: the next load step can regularise a near-slack configuration.
            continue

    full, vel, _ = model.topology.expand_free(0.0, q, np.zeros_like(q))
    final_ev = model.evaluate(
        0.0,
        q,
        np.zeros_like(q),
        compute_tangent=False,
        gravity_scale=1.0,
        include_aero=False,
    )
    residual = float(np.max(np.abs(final_ev.free_force[variable]))) if variable.size else 0.0
    converged = residual <= force_tol
    if not converged:
        raise StaticEquilibriumError(
            f"Static equilibrium residual {residual:.3e} N exceeds tolerance {force_tol:.3e} N."
        )
    stability = _static_stability_audit(model, q, variable)
    if not bool(stability["stable"]):
        raise StaticEquilibriumError(
            "Static force balance converged but the active tensile equilibrium is locally unstable: "
            f"minimum generalized eigenvalue={stability['minimum_generalized_eigenvalue_s-2']:.6g} s^-2."
        )
    return StaticEquilibrium(
        positions=full,
        velocities=vel,
        force_residual_max=residual,
        iterations=total_iterations,
        converged=True,
        fixed_nodes=tuple(sorted(fixed_nodes)),
        metadata={
            "continuation_steps": continuation_steps,
            "variable_dofs": int(variable.size),
            "stability": stability,
        },
    )


def solve_static_equilibrium(
    cfg: SimulationConfig, model: FullCableModel | None = None
) -> StaticEquilibrium:
    model = FullCableModel(cfg) if model is None else model
    initial = model.topology.reference_positions.copy()
    return _solve_conditioned_equilibrium(model, initial)


def _resolve_input_path(cfg: SimulationConfig, value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() and cfg.source_path is not None:
        path = cfg.source_path.parent / path
    return path.resolve()


def _load_restart_state(
    path: str | Path, model: FullCableModel
) -> tuple[np.ndarray, np.ndarray, float]:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Restart HDF5 file not found: {target}")
    with h5py.File(target, "r") as h5:
        if str(h5.attrs.get("model", "")) != "H1":
            raise ValueError("Restart file must contain an H1 high-fidelity result.")
        positions = np.asarray(h5["/state/positions"][-1], dtype=float)
        velocities = np.asarray(h5["/state/velocities"][-1], dtype=float)
        t = float(h5["/time"][-1])
        if "/mesh/node_labels" not in h5 or "/mesh/elements/node_i" not in h5:
            raise ValueError("Restart file lacks the mesh metadata required for compatibility checks.")
        labels = tuple(
            value.decode("utf-8") if isinstance(value, bytes) else str(value)
            for value in np.asarray(h5["/mesh/node_labels"])
        )
        node_i = np.asarray(h5["/mesh/elements/node_i"], dtype=np.int64)
        node_j = np.asarray(h5["/mesh/elements/node_j"], dtype=np.int64)
        rest = np.asarray(h5["/mesh/elements/rest_length"], dtype=float)
    expected = model.topology
    if positions.shape != (expected.node_count, 3) or velocities.shape != positions.shape:
        raise ValueError("Restart state shape is incompatible with the current mesh.")
    if labels != expected.node_labels:
        raise ValueError("Restart node labels/topology differ from the current configuration.")
    if not (
        np.array_equal(node_i, expected.elements.node_i)
        and np.array_equal(node_j, expected.elements.node_j)
        and np.allclose(rest, expected.elements.rest_length, rtol=1e-12, atol=1e-14)
    ):
        raise ValueError("Restart element connectivity or rest lengths differ from the current configuration.")
    if not np.all(np.isfinite(positions)) or not np.all(np.isfinite(velocities)) or not np.isfinite(t):
        raise ValueError("Restart file contains non-finite state values.")
    return positions, velocities, t



def _project_velocity_to_taut_compatibility(
    model: FullCableModel,
    positions: np.ndarray,
    preliminary_velocities: np.ndarray,
    *,
    time: float,
    target_bob_velocity: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, float | int | bool]]:
    """Mass-project a constructed release velocity onto the taut cable tangent space.

    The H1 state is elastic, so arbitrary velocities are mathematically valid.
    For a release intended to represent a low-frequency Y-pendulum motion,
    however, a naive node-by-node interpolation can inject a large longitudinal
    wave at ``t=0``.  This routine finds the velocity field closest in the
    assembled kinetic-energy norm to the preliminary field while enforcing zero
    instantaneous extension rate on every initially tensile element.  The bob
    velocity, when explicitly supplied by the user/reduced release map, is kept
    exactly.  Prescribed support velocities enter the compatibility right-hand
    side and are never silently set to zero.
    """

    full_positions = np.asarray(positions, dtype=float)
    full_preliminary = np.asarray(preliminary_velocities, dtype=float).copy()
    if full_positions.shape != (model.topology.node_count, 3):
        raise ValueError("Velocity projection positions do not match the H1 mesh.")
    if full_preliminary.shape != full_positions.shape:
        raise ValueError("Velocity projection field does not match the H1 mesh.")

    # Obtain the actual prescribed support velocities at the release instant.
    q_free = model.topology.pack_free(full_positions)
    zero_free = np.zeros(model.position_dof_count, dtype=float)
    _q, boundary_velocity_field, _a = model.topology.expand_free(time, q_free, zero_free)
    for node in model.topology.support_nodes:
        full_preliminary[node] = boundary_velocity_field[node]

    # Determine the initial tensile active set from geometry and elastic
    # material response only.  Setting all velocities to zero avoids a damping
    # term changing the definition of which geometric path is initially taut.
    element_response = evaluate_cable_elements(
        full_positions,
        np.zeros_like(full_positions),
        model.topology.elements,
        length_guard=model.length_guard,
        compute_tangent=False,
        material_overrides=model.material_overrides,
    )
    active_indices = np.flatnonzero(element_response.active & (element_response.tension > 0.0))

    free_nodes = model.topology.free_nodes
    node_to_free = {int(node): 3 * idx for idx, node in enumerate(free_nodes.tolist())}
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    rhs: list[float] = []
    row_index = 0

    for element_index in active_indices:
        i = int(model.topology.elements.node_i[element_index])
        j = int(model.topology.elements.node_j[element_index])
        displacement = full_positions[j] - full_positions[i]
        length = float(np.linalg.norm(displacement))
        if length <= model.length_guard:
            raise FloatingPointError("Cannot project velocity on a degenerate cable element.")
        direction = displacement / length
        boundary_contribution = 0.0
        for node, sign in ((i, -1.0), (j, 1.0)):
            if node in node_to_free:
                base = node_to_free[node]
                for axis in range(3):
                    rows.append(row_index)
                    cols.append(base + axis)
                    data.append(sign * float(direction[axis]))
            else:
                boundary_contribution += sign * float(np.dot(direction, full_preliminary[node]))
        rhs.append(-boundary_contribution)
        row_index += 1

    if target_bob_velocity is not None:
        target = np.asarray(target_bob_velocity, dtype=float)
        if target.shape != (3,) or not np.all(np.isfinite(target)):
            raise ValueError("target_bob_velocity must be a finite three-vector.")
        bob = int(model.topology.bob_node)
        if bob not in node_to_free:
            raise RuntimeError("The H1 bob node is unexpectedly constrained.")
        base = node_to_free[bob]
        for axis in range(3):
            rows.append(row_index)
            cols.append(base + axis)
            data.append(1.0)
            rhs.append(float(target[axis]))
            row_index += 1

    preliminary_free = model.topology.pack_free(full_preliminary)
    if row_index == 0:
        return full_preliminary, {
            "applied": False,
            "active_taut_constraints": 0,
            "hard_bob_velocity_constraints": 0,
            "maximum_axial_rate_residual_m_s": 0.0,
            "mass_norm_velocity_change": 0.0,
        }

    constraint = sparse.coo_matrix(
        (data, (rows, cols)),
        shape=(row_index, model.position_dof_count),
    ).tocsr()
    rhs_array = np.asarray(rhs, dtype=float)
    zero = sparse.csr_matrix((row_index, row_index))
    kkt = sparse.bmat(
        [[model.mass_ff, constraint.T], [constraint, zero]],
        format="csc",
    )
    system_rhs = np.concatenate(
        [np.asarray(model.mass_ff @ preliminary_free).reshape(-1), rhs_array]
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", MatrixRankWarning)
        solution = spsolve(kkt, system_rhs)
    if not np.all(np.isfinite(solution)):
        solution = lsmr(
            kkt,
            system_rhs,
            atol=1e-13,
            btol=1e-13,
            maxiter=max(10 * kkt.shape[0], 1000),
        )[0]
    projected_free = np.asarray(solution[: model.position_dof_count], dtype=float)
    residual = np.asarray(constraint @ projected_free - rhs_array).reshape(-1)
    tolerance = 1e-9 * max(
        1.0,
        float(np.max(np.abs(preliminary_free))) if preliminary_free.size else 1.0,
    )
    max_residual = float(np.max(np.abs(residual))) if residual.size else 0.0
    if not np.all(np.isfinite(projected_free)) or max_residual > tolerance:
        raise RuntimeError(
            "Could not construct a kinematically compatible initial velocity field: "
            f"constraint residual={max_residual:.3e} m/s."
        )

    projected_full = full_preliminary.copy()
    projected_full[free_nodes] = projected_free.reshape(-1, 3)
    delta = projected_free - preliminary_free
    mass_change = float(np.sqrt(max(delta @ (model.mass_ff @ delta), 0.0)))
    return projected_full, {
        "applied": True,
        "active_taut_constraints": int(active_indices.size),
        "hard_bob_velocity_constraints": 3 if target_bob_velocity is not None else 0,
        "maximum_axial_rate_residual_m_s": max_residual,
        "mass_norm_velocity_change": mass_change,
    }

def build_initial_state(
    cfg: SimulationConfig,
    model: FullCableModel,
    equilibrium: StaticEquilibrium | None = None,
) -> tuple[np.ndarray, float, StaticEquilibrium | None]:
    ic = cfg.initial_condition
    if ic.type == "restart":
        assert ic.state_file is not None
        restart_path = _resolve_input_path(cfg, ic.state_file)
        positions, velocities, t0 = _load_restart_state(restart_path, model)
        if positions.shape != (model.topology.node_count, 3):
            raise ValueError("Restart mesh is incompatible with the current configuration.")
        return model.pack_state(positions, velocities), t0, None

    if ic.type == "direct_state":
        assert ic.positions_file is not None
        positions_path = _resolve_input_path(cfg, ic.positions_file)
        positions = np.load(positions_path)
        velocities = (
            np.zeros_like(positions)
            if ic.velocities_file is None
            else np.load(_resolve_input_path(cfg, ic.velocities_file))
        )
        if positions.shape != (model.topology.node_count, 3) or velocities.shape != positions.shape:
            raise ValueError("Direct-state arrays do not match the current mesh.")
        return model.pack_state(positions, velocities), 0.0, None

    base = solve_static_equilibrium(cfg, model) if equilibrium is None else equilibrium
    if ic.type == "static_equilibrium":
        compatible, projection = _project_velocity_to_taut_compatibility(
            model,
            base.positions,
            base.velocities,
            time=0.0,
        )
        base.metadata["initial_velocity_projection"] = projection
        return model.pack_state(base.positions, compatible), 0.0, base

    positions = base.positions.copy()
    velocities = np.zeros_like(positions)
    if ic.type == "cartesian_release":
        assert ic.bob_position is not None
        target = as_vector3(ic.bob_position, default_unit="m")
        positions[model.topology.bob_node] = target
        _redistribute_chain_positions(model, positions)
        conditioned = _solve_conditioned_equilibrium(
            model, positions, fixed_nodes={model.topology.bob_node: target}
        )
        velocities = conditioned.velocities.copy()
        target_bob_velocity = as_vector3(ic.bob_velocity, default_unit="m/s")
        velocities[model.topology.bob_node] = target_bob_velocity
        velocities, projection = _project_velocity_to_taut_compatibility(
            model,
            conditioned.positions,
            velocities,
            time=0.0,
            target_bob_velocity=target_bob_velocity,
        )
        conditioned.metadata["initial_velocity_projection"] = projection
        return model.pack_state(conditioned.positions, velocities), 0.0, conditioned

    if ic.type != "reduced_angles_release":
        raise ValueError(f"Unsupported initial condition type {ic.type!r}.")

    phi = float(to_si(ic.phi, default_unit="rad"))
    theta = float(to_si(ic.theta, default_unit="rad"))
    phi_dot = float(to_si(ic.phi_dot, default_unit="rad/s"))
    theta_dot = float(to_si(ic.theta_dot, default_unit="rad/s"))
    A = base.positions[0]
    B = base.positions[1]
    J0 = base.positions[model.topology.junction_node]
    P0 = base.positions[model.topology.bob_node]
    geom = reduced_geometry_from_loaded_state(A, B, J0, model.gravity)
    loaded_lower = float(np.linalg.norm(P0 - J0))
    target_j, target_p = torus_point(geom, loaded_lower, phi, theta)
    positions[model.topology.junction_node] = target_j
    positions[model.topology.bob_node] = target_p
    _redistribute_chain_positions(model, positions)
    conditioned = _solve_conditioned_equilibrium(
        model, positions, fixed_nodes={model.topology.bob_node: target_p}
    )

    jv, pv = torus_velocity(geom, loaded_lower, phi, theta, phi_dot, theta_dot)
    velocities = np.zeros_like(conditioned.positions)
    velocities[model.topology.junction_node] = jv
    velocities[model.topology.bob_node] = pv
    for name, path in model.topology.cable_node_paths.items():
        v_start = velocities[path[0]].copy()
        v_end = velocities[path[-1]].copy()
        count = len(path) - 1
        for k, node in enumerate(path[1:-1], start=1):
            alpha = k / count
            velocities[node] = (1.0 - alpha) * v_start + alpha * v_end
    velocities, projection = _project_velocity_to_taut_compatibility(
        model,
        conditioned.positions,
        velocities,
        time=0.0,
        target_bob_velocity=pv,
    )
    conditioned.metadata["initial_velocity_projection"] = projection
    return model.pack_state(conditioned.positions, velocities), 0.0, conditioned

"""Finite-mass junction backend for the ``YP-FWD-J3-v1`` model.

The integrated coordinates are ``[theta, nu, n_x, n_y, n_z,
eta_x, eta_y, eta_z]``.  Both ``n`` and ``eta`` use the global Cartesian
frame.  The exact vector field preserves ``|n| = 1`` and ``n dot eta = 0``;
the numerical backend deliberately applies no projection, so the reported
constraint and energy residuals expose the actual integration error.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable
import warnings

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import minimize_scalar

from .contracts import (
    MAX_UNIFORM_SAMPLES,
    MIN_SOLVER_RTOL,
    SimulationResult,
    ValidationIssue,
    as_vector3,
    base_validation,
    is_finite_number,
    numerical_time_resource_issues,
    reject_unknown_keys,
    require_number,
    safe_uniform_sample_count,
    strict_finite_array,
)
from .observations import evaluate_observations


JUNCTION_MODEL_ID = "YP-FWD-J3-v1"
JUNCTION_NUMERICAL_FIELDS = {
    "method",
    "rtol",
    "atol",
    "atol_angle",
    "atol_rate",
    "max_step",
    "output_dt",
    "event_cluster_tolerance",
}
_OBSTACLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_OBSTACLES = 64
_MAX_FAST_MODE_PHASE_STEP = 0.25
_CONSTRAINT_TOLERANCE = 1.0e-8
_RELATIVE_ENERGY_TOLERANCE = 1.0e-6


@dataclass(frozen=True)
class JunctionObstacle:
    """A signed-clearance contact guard.

    A sphere admits points outside its surface.  A plane admits the half-space
    ``allowed_side * normal dot (position - point) > 0``.
    """

    id: str
    kind: str
    target: str
    center: np.ndarray | None = None
    radius: float | None = None
    point: np.ndarray | None = None
    normal: np.ndarray | None = None
    allowed_side: float = 1.0


@dataclass(frozen=True)
class JunctionParameters:
    """Validated J3 parameters, using the TorusParameters geometry names."""

    A: np.ndarray
    B: np.ndarray
    e_z: np.ndarray
    g: float
    mass: float
    junction_mass: float
    s_A: float
    s_B: float
    lower_length: float
    T: float
    initial_state: np.ndarray
    O: np.ndarray
    e_x: np.ndarray
    e_y: np.ndarray
    d: float
    x_C: float
    a_A: float
    a_B: float
    h: float
    obstacles: tuple[JunctionObstacle, ...] = ()


def validate_junction_config(
    config: dict[str, Any],
) -> tuple[list[ValidationIssue], JunctionParameters | None]:
    """Validate J.1, the support-circle geometry, and the initial guards."""

    issues = base_validation(config, JUNCTION_MODEL_ID)
    reject_unknown_keys(
        config,
        {
            "schema_version",
            "model_id",
            "theory_sha256",
            "units",
            "physical",
            "numerics",
            "observation",
            "validation",
            "metadata",
        },
        "",
        issues,
    )
    if config.get("units") != "SI":
        issues.append(ValidationIssue("UNITS", "units", config.get("units"), "SI"))

    physical = config.get("physical")
    if not isinstance(physical, dict):
        issues.append(ValidationIssue("TYPE", "physical", physical, "object"))
        physical = {}
    reject_unknown_keys(
        physical,
        {
            "A",
            "B",
            "e_z",
            "g",
            "mass",
            "junction_mass",
            "s_A",
            "s_B",
            "lower_length",
            "initial_state",
            "T",
            "obstacles",
        },
        "physical",
        issues,
    )
    A = as_vector3(physical.get("A"), "physical.A", issues)
    B = as_vector3(physical.get("B"), "physical.B", issues)
    e_z = as_vector3(physical.get("e_z"), "physical.e_z", issues)
    g = require_number(physical, "g", "physical", issues, positive=True)
    mass = require_number(physical, "mass", "physical", issues, positive=True)
    junction_mass = require_number(
        physical, "junction_mass", "physical", issues, positive=True
    )
    s_A = require_number(physical, "s_A", "physical", issues, positive=True)
    s_B = require_number(physical, "s_B", "physical", issues, positive=True)
    lower_length = require_number(
        physical, "lower_length", "physical", issues, positive=True
    )
    T = require_number(physical, "T", "physical", issues, positive=True)

    initial_raw = physical.get("initial_state")
    initial_state = strict_finite_array(initial_raw)
    if initial_state is None or initial_state.shape != (8,):
        issues.append(
            ValidationIssue(
                "TYPE",
                "physical.initial_state",
                initial_raw,
                (
                    "eight finite reals [theta,nu,nx,ny,nz,"
                    "etax,etay,etaz]"
                ),
            )
        )
        initial_state = np.zeros(8)

    geometry_ok = True
    d_vector = B - A
    d = float(np.linalg.norm(d_vector))
    if not d > 0.0:
        issues.append(
            ValidationIssue(
                "JUNCTION_GEOMETRY",
                "physical.A,B",
                [A, B],
                "distinct support points",
            )
        )
        geometry_ok = False
        e_x = np.array([1.0, 0.0, 0.0])
    else:
        e_x = d_vector / d
    e_z_norm = float(np.linalg.norm(e_z))
    if abs(e_z_norm - 1.0) > 1.0e-10:
        issues.append(
            ValidationIssue(
                "JUNCTION_GEOMETRY", "physical.e_z", e_z, "unit vector"
            )
        )
        geometry_ok = False
    support_vertical_cosine = (
        abs(float(d_vector @ e_z)) / (d * e_z_norm)
        if d > 0.0 and e_z_norm > 0.0
        else np.inf
    )
    if support_vertical_cosine > 1.0e-10:
        issues.append(
            ValidationIssue(
                "JUNCTION_GEOMETRY",
                "physical.A,B,e_z",
                support_vertical_cosine,
                "dimensionless support-axis vertical cosine <= 1e-10",
            )
        )
        geometry_ok = False
    e_y = np.cross(e_z, e_x)
    if not (abs(s_A - s_B) < d < s_A + s_B):
        issues.append(
            ValidationIssue(
                "JUNCTION_GEOMETRY",
                "physical.s_A,s_B,A,B",
                [s_A, s_B, d],
                "strict sphere-intersection inequalities",
            )
        )
        geometry_ok = False
    x_C = (s_A * s_A - s_B * s_B) / (2.0 * d) if d > 0.0 else 0.0
    a_A = x_C + d / 2.0
    a_B = d / 2.0 - x_C
    h2 = s_A * s_A - a_A * a_A
    if not (a_A > 0.0 and a_B > 0.0):
        issues.append(
            ValidationIssue(
                "JUNCTION_WORKING_BAND",
                "derived.a_A,a_B",
                [a_A, a_B],
                "both > 0",
            )
        )
        geometry_ok = False
    if not h2 > 0.0:
        issues.append(
            ValidationIssue(
                "JUNCTION_GEOMETRY", "derived.h2", h2, "> 0"
            )
        )
        geometry_ok = False
    h = float(np.sqrt(max(h2, 0.0)))
    O = (A + B) / 2.0
    obstacles = _validate_obstacles(physical.get("obstacles", []), issues)

    if initial_state.shape == (8,):
        n0 = initial_state[2:5]
        eta0 = initial_state[5:8]
        n_error = abs(float(np.linalg.norm(n0)) - 1.0)
        tangent_error = abs(float(n0 @ eta0))
        tangent_scale = max(1.0, float(np.linalg.norm(eta0)))
        if n_error > 1.0e-10:
            issues.append(
                ValidationIssue(
                    "JUNCTION_INITIAL_CONSTRAINT",
                    "physical.initial_state.n",
                    float(np.linalg.norm(n0)),
                    "unit norm within 1e-10; no projection is applied",
                )
            )
        if tangent_error > 1.0e-10 * tangent_scale:
            issues.append(
                ValidationIssue(
                    "JUNCTION_INITIAL_CONSTRAINT",
                    "physical.initial_state.n_dot_eta",
                    float(n0 @ eta0),
                    "absolute value <= 1e-10 max(1, |eta|)",
                )
            )

    params: JunctionParameters | None = None
    if geometry_ok and not any(
        issue.path.startswith("physical.initial_state")
        or issue.path.startswith("physical.obstacles")
        or issue.path
        in {
            "physical.g",
            "physical.mass",
            "physical.junction_mass",
            "physical.s_A",
            "physical.s_B",
            "physical.lower_length",
            "physical.T",
        }
        for issue in issues
    ):
        params = JunctionParameters(
            A=A,
            B=B,
            e_z=e_z,
            g=g,
            mass=mass,
            junction_mass=junction_mass,
            s_A=s_A,
            s_B=s_B,
            lower_length=lower_length,
            T=T,
            initial_state=initial_state,
            O=O,
            e_x=e_x,
            e_y=e_y,
            d=d,
            x_C=x_C,
            a_A=a_A,
            a_B=a_B,
            h=h,
            obstacles=obstacles,
        )
        derived0 = junction_derived(params, initial_state[None, :])
        initial_tensions = [
            float(derived0[name][0])
            for name in ("T_A", "T_B", "T_lower")
        ]
        if not min(initial_tensions) > 0.0:
            issues.append(
                ValidationIssue(
                    "JUNCTION_INITIAL_TENSION",
                    "physical.initial_state.tensions",
                    initial_tensions,
                    "all three initial tensions strictly positive",
                )
            )
        initial_clearance = {
            obstacle.id: float(derived0["obstacle_clearance"][obstacle.id][0])
            for obstacle in obstacles
        }
        for obstacle_id, clearance in initial_clearance.items():
            if not clearance > 0.0:
                issues.append(
                    ValidationIssue(
                        "JUNCTION_INITIAL_CONTACT",
                        f"physical.obstacles.{obstacle_id}",
                        clearance,
                        "strictly positive initial signed clearance",
                    )
                )
    return issues, params


def junction_rhs(
    params: JunctionParameters, _t: float, state: np.ndarray
) -> np.ndarray:
    """Evaluate the projection-free J.3 vector field."""

    state = np.asarray(state, dtype=float)
    if state.shape != (8,) or not np.all(np.isfinite(state)):
        raise ValueError("junction state must contain eight finite reals")
    theta, nu = state[:2]
    n = state[2:5]
    eta = state[5:8]
    e_r, e_theta = _frame(params, np.asarray([theta]))
    e_r = e_r[0]
    e_theta = e_theta[0]
    n_theta = float(n @ e_theta)
    n_r = float(n @ e_r)
    n_z = float(n @ params.e_z)
    eta2 = float(eta @ eta)
    denominator = params.h * (
        params.junction_mass + params.mass * n_theta * n_theta
    )
    if not np.isfinite(denominator) or denominator <= 0.0:
        raise FloatingPointError("J3 acceleration denominator left its positive domain")
    nu_dot = (
        -params.junction_mass * params.g * np.sin(theta)
        + params.mass
        * n_theta
        * (params.g * n_z + params.h * nu * nu * n_r + params.lower_length * eta2)
    ) / denominator
    a_J = params.h * (nu_dot * e_theta - nu * nu * e_r)
    eta_dot = (
        (np.eye(3) - np.outer(n, n))
        @ (params.g * params.e_z - a_J)
        / params.lower_length
        - eta2 * n
    )
    result = np.concatenate(([nu, nu_dot], eta, eta_dot))
    if not np.all(np.isfinite(result)):
        raise FloatingPointError("J3 right-hand side became non-finite")
    return result


def junction_derived(
    params: JunctionParameters, states: np.ndarray
) -> dict[str, Any]:
    """Return J.2 positions/velocities, J.4--J.6 forces, and J.7 energy."""

    states = np.asarray(states, dtype=float)
    if states.ndim == 1:
        states = states[None, :]
    if states.ndim != 2 or states.shape[1] != 8:
        raise ValueError("junction states must have shape (sample_count, 8)")
    if not np.all(np.isfinite(states)):
        raise ValueError("junction states must be finite")
    theta = states[:, 0]
    nu = states[:, 1]
    n = states[:, 2:5]
    eta = states[:, 5:8]
    e_r, e_theta = _frame(params, theta)
    n_theta = np.einsum("ij,ij->i", n, e_theta)
    n_r = np.einsum("ij,ij->i", n, e_r)
    n_z = n @ params.e_z
    eta2 = np.einsum("ij,ij->i", eta, eta)
    denominator = params.h * (
        params.junction_mass + params.mass * n_theta * n_theta
    )
    nu_dot = (
        -params.junction_mass * params.g * np.sin(theta)
        + params.mass
        * n_theta
        * (
            params.g * n_z
            + params.h * nu * nu * n_r
            + params.lower_length * eta2
        )
    ) / denominator
    a_J = params.h * (
        nu_dot[:, None] * e_theta - (nu * nu)[:, None] * e_r
    )
    projector_force = params.g * params.e_z[None, :] - a_J
    n_dot_force = np.einsum("ij,ij->i", n, projector_force)
    eta_dot = (
        (projector_force - n * n_dot_force[:, None])
        / params.lower_length
        - eta2[:, None] * n
    )
    a_m = a_J + params.lower_length * eta_dot

    J = (
        params.O
        + params.x_C * params.e_x
        + params.h * e_r
    )
    r_m = J + params.lower_length * n
    v_J = params.h * nu[:, None] * e_theta
    v_m = v_J + params.lower_length * eta
    T_lower = params.mass * (
        n_dot_force + params.lower_length * eta2
    )
    W = (
        params.junction_mass * projector_force
        + T_lower[:, None] * n
    )
    W_x = W @ params.e_x
    W_r = np.einsum("ij,ij->i", W, e_r)
    T_A = params.s_A / params.d * (
        W_x + params.a_B / params.h * W_r
    )
    T_B = params.s_B / params.d * (
        params.a_A / params.h * W_r - W_x
    )
    energy = (
        0.5 * params.junction_mass * params.h**2 * nu**2
        + 0.5 * params.mass * np.einsum("ij,ij->i", v_m, v_m)
        + (params.junction_mass + params.mass)
        * params.g
        * params.h
        * (1.0 - np.cos(theta))
        + params.mass
        * params.g
        * params.lower_length
        * (1.0 - n_z)
    )
    n_norm = np.linalg.norm(n, axis=1)
    n_dot_eta = np.einsum("ij,ij->i", n, eta)
    obstacle_clearance = {
        obstacle.id: _obstacle_clearance(obstacle, J, r_m)
        for obstacle in params.obstacles
    }
    upper_A_error = np.linalg.norm(J - params.A, axis=1) - params.s_A
    upper_B_error = np.linalg.norm(J - params.B, axis=1) - params.s_B
    lower_error = np.linalg.norm(r_m - J, axis=1) - params.lower_length
    junction_force_residual = (
        params.junction_mass * a_J
        - params.junction_mass * params.g * params.e_z
        - T_lower[:, None] * n
        - T_A[:, None] * (params.A - J) / params.s_A
        - T_B[:, None] * (params.B - J) / params.s_B
    )
    bob_force_residual = (
        params.mass * a_m
        - params.mass * params.g * params.e_z
        + T_lower[:, None] * n
    )
    return {
        "J": J,
        "r_m": r_m,
        "v_J": v_J,
        "v_m": v_m,
        "a_J": a_J,
        "a_m": a_m,
        "nu_dot": nu_dot,
        "eta_dot": eta_dot,
        "T_A": T_A,
        "T_B": T_B,
        "T_lower": T_lower,
        "E_junction": energy,
        "n_norm_error": n_norm - 1.0,
        "n_norm_squared_minus_one": np.einsum("ij,ij->i", n, n) - 1.0,
        "n_dot_eta": n_dot_eta,
        "constraint_position_error": n_norm - 1.0,
        "constraint_velocity_error": n_dot_eta,
        "upper_A_length_error": upper_A_error,
        "upper_B_length_error": upper_B_error,
        "lower_length_error": lower_error,
        "junction_force_residual": junction_force_residual,
        "bob_force_residual": bob_force_residual,
        "W_theta_residual": np.einsum("ij,ij->i", W, e_theta),
        "obstacle_clearance": obstacle_clearance,
    }


def run_junction(
    config: dict[str, Any], *, identity: dict[str, Any]
) -> SimulationResult:
    """Validate, integrate, guard, diagnose, and observe one J3 input."""

    issues, params = validate_junction_config(config)
    if issues or params is None:
        return SimulationResult(
            model_id=JUNCTION_MODEL_ID,
            contract_status=["INVALID_INPUT"],
            numerical_status="INPUT_REJECTED",
            tau=0.0,
            returned_interval="empty",
            time=np.empty(0),
            events=[
                {
                    "kind": "input",
                    "failures": [issue.as_dict() for issue in issues],
                }
            ],
            metadata=identity,
        )

    numerics = config.get("numerics", {})
    if not isinstance(numerics, dict):
        return _invalid_numerical(
            identity,
            [ValidationIssue("NUMERICAL_CONFIG", "numerics", numerics, "object")],
        )
    numerical_issues = _validate_junction_numerics(numerics)
    method = numerics.get("method", "DOP853")
    rtol = _positive_value(numerics.get("rtol", 1.0e-10), 1.0e-10)
    atol = _positive_value(numerics.get("atol", 1.0e-12), 1.0e-12)
    atol_angle = _positive_value(numerics.get("atol_angle", atol), atol)
    atol_rate = _positive_value(numerics.get("atol_rate", atol), atol)
    omega_plus = _omega_plus(params)
    default_max_step = min(
        params.T / 200.0,
        _MAX_FAST_MODE_PHASE_STEP / omega_plus,
    )
    max_step = _positive_value(
        numerics.get("max_step", default_max_step), default_max_step
    )
    output_dt = _positive_value(
        numerics.get("output_dt", params.T / 1000.0), params.T / 1000.0
    )
    event_tolerance = _positive_value(
        numerics.get("event_cluster_tolerance", 1.0e-9), 1.0e-9
    )
    numerical_issues.extend(
        numerical_time_resource_issues(params.T, max_step, output_dt)
    )
    if max_step * omega_plus > _MAX_FAST_MODE_PHASE_STEP * (1.0 + 1.0e-14):
        numerical_issues.append(
            ValidationIssue(
                "JUNCTION_FAST_MODE_RESOLUTION",
                "numerics.max_step",
                max_step,
                (
                    "max_step * Omega_plus <= "
                    f"{_MAX_FAST_MODE_PHASE_STEP}; Omega_plus={omega_plus:.17g}"
                ),
            )
        )
    if numerical_issues:
        return _invalid_numerical(identity, numerical_issues)

    atol_vector = np.array(
        [atol_angle, atol_rate, atol_angle, atol_angle, atol_angle,
         atol_rate, atol_rate, atol_rate],
        dtype=float,
    )
    guard_names = ["T_A_ZERO", "T_B_ZERO", "T_LOWER_ZERO"] + [
        f"CONTACT_{obstacle.id}" for obstacle in params.obstacles
    ]
    guards = [
        _make_guard(params, index)
        for index in range(len(guard_names))
    ]
    effective_max_step = max_step
    integration_retry = None

    def integrate(step_bound):
        return solve_ivp(
            lambda t, state: junction_rhs(params, t, state),
            (0.0, params.T),
            params.initial_state,
            method=str(method),
            rtol=rtol,
            atol=atol_vector,
            max_step=step_bound,
            dense_output=True,
            events=guards,
        )

    try:
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always")
            try:
                sol = integrate(max_step)
            except ValueError as exc:
                # SciPy 1.11 can append a terminal root equal to an accepted
                # mesh point twice, then reject its own OdeSolution mesh.
                # One explicitly recorded, finer-mesh retry avoids that mesh
                # coincidence without changing the physical input or tolerances.
                if str(exc) != "`ts` must be strictly increasing or decreasing.":
                    raise
                effective_max_step = 0.9 * max_step
                integration_retry = {
                    "reason": "scipy_duplicate_terminal_dense_time",
                    "original_exception": str(exc),
                    "requested_max_step": max_step,
                    "retry_max_step": effective_max_step,
                }
                sol = integrate(effective_max_step)
    except Exception as exc:
        return SimulationResult(
            model_id=JUNCTION_MODEL_ID,
            contract_status=[],
            numerical_status="SOLVER_FAILURE",
            tau=0.0,
            returned_interval="unresolved",
            time=np.empty(0),
            events=[{"kind": "numerical_failure", "message": repr(exc)}],
            metadata={
                **identity,
                "integrator": method,
                "omega_plus": omega_plus,
                "constraint_projection_applied": False,
            },
        )

    solver_warnings = [
        {"category": warning.category.__name__, "message": str(warning.message)}
        for warning in caught_warnings
    ]
    event_times = [float(times[0]) for times in sol.t_events if len(times)]
    event_tau = min(event_times) if event_times else np.inf
    event_root_bracket = (
        _root_bracket(np.asarray(sol.t), event_tau)
        if np.isfinite(event_tau)
        else None
    )
    known_triggers: list[str] = []
    if np.isfinite(event_tau):
        known_triggers = [
            name
            for name, times in zip(guard_names, sol.t_events)
            if len(times) and abs(float(times[0]) - event_tau) <= event_tolerance
        ]
        # A small positive value is still inside the physical domain.  Do not
        # relabel it as a simultaneous root merely because it falls below a
        # numerical audit tolerance.  Only roots actually located by the
        # integrator establish trigger identity; an unlocated nonpositive
        # guard is handled conservatively by ``_audit_dense_guards`` below.
        known_triggers = sorted(set(known_triggers))

    dense_guard_issue = None
    invariant_issue = None
    if sol.t.size and sol.sol is not None:
        dense_guard_issue = _audit_dense_guards(
            params,
            sol,
            guard_names,
            known_event_tau=event_tau,
            known_triggers=set(known_triggers),
            event_tolerance=event_tolerance,
            rtol=rtol,
        )
        invariant_issue = _accepted_invariant_issue(params, sol)

    if solver_warnings:
        tau = float(sol.t[-1]) if sol.t.size else 0.0
        completed = False
        contract_status: list[str] = []
        numerical_status = "SOLVER_WARNING"
        returned_interval = f"[0,{tau}] candidate only; warning made status unresolved"
        events = [{"kind": "numerical_warning", "warnings": solver_warnings}]
    elif not sol.success:
        tau = float(sol.t[-1]) if sol.t.size else 0.0
        completed = False
        contract_status = []
        numerical_status = "SOLVER_FAILURE"
        returned_interval = f"[0,{tau}] last accepted; physical status unresolved"
        events = [{"kind": "numerical_failure", "message": sol.message}]
    elif dense_guard_issue is not None:
        tau = float(dense_guard_issue["root_bracket"][0])
        completed = False
        contract_status = []
        numerical_status = "EVENT_UNRESOLVED"
        returned_interval = f"[0,{tau}] last interval boundary before unresolved guard"
        events = [dense_guard_issue]
        event_root_bracket = dense_guard_issue["root_bracket"]
    elif invariant_issue is not None:
        tau = float(invariant_issue["last_certified_time"])
        completed = False
        contract_status = []
        numerical_status = str(invariant_issue["numerical_status"])
        returned_interval = f"[0,{tau}] candidate only; invariant qualification failed"
        events = [invariant_issue]
    elif np.isfinite(event_tau) and event_tau <= params.T + event_tolerance:
        tau = min(event_tau, params.T)
        completed = False
        contract_status = ["OUT_OF_SCOPE"]
        numerical_status = "SUCCESS_EVENT"
        returned_interval = f"[0,{tau})"
        event_state = np.asarray(sol.sol(tau), dtype=float)
        event_derived = junction_derived(params, event_state)
        guard_values = _guard_values(params, event_state)
        tolerances = _guard_zero_tolerances(params, rtol)
        events = [
            {
                "kind": "physical_exit",
                "time": tau,
                "triggers": known_triggers,
                "state_left": event_state,
                "derived_left": _first_sample(event_derived),
                "guard_values": dict(zip(guard_names, guard_values)),
                "guard_zero_tolerances": dict(zip(guard_names, tolerances)),
                "root_bracket": event_root_bracket,
                "root_bracket_basis": (
                    "adjacent accepted solver times; not an independent "
                    "event-time error bound"
                ),
            }
        ]
    else:
        tau = params.T
        completed = True
        contract_status = ["COMPLETED"]
        numerical_status = "SUCCESS_SINGLE_RUN"
        returned_interval = f"[0,{params.T}]"
        events = []

    include_end = completed or not contract_status
    time = _output_times(tau, output_dt, include_end=include_end)
    states = (
        np.asarray(sol.sol(time), dtype=float).T
        if time.size
        else np.empty((0, 8))
    )
    derived = junction_derived(params, states) if time.size else {}
    diagnostics = _run_diagnostics(
        params,
        sol,
        derived,
        omega_plus=omega_plus,
        solver_warnings=solver_warnings,
        event_root_bracket=event_root_bracket,
    )

    def position_at(times: np.ndarray) -> np.ndarray:
        query = np.atleast_1d(np.asarray(times, dtype=float))
        query_states = np.asarray(sol.sol(query), dtype=float).T
        return junction_derived(params, query_states)["r_m"]

    numerically_resolved = numerical_status in {
        "SUCCESS_SINGLE_RUN",
        "SUCCESS_EVENT",
    }
    observations = (
        evaluate_observations(
            config.get("observation"),
            position_at=position_at,
            interval_end=tau,
            completed=completed,
            e_z=params.e_z,
            event_time_tolerance=event_tolerance,
        )
        if numerically_resolved
        else _unresolved_observations(config.get("observation"), numerical_status, tau)
    )
    state_payload: dict[str, Any] = {"X_junction": states}
    if time.size:
        state_payload.update(
            {
                "theta": states[:, 0],
                "nu": states[:, 1],
                "n": states[:, 2:5],
                "eta": states[:, 5:8],
                "r_J": derived["J"],
                "r_m": derived["r_m"],
                "v_J": derived["v_J"],
                "v_m": derived["v_m"],
            }
        )
    return SimulationResult(
        model_id=JUNCTION_MODEL_ID,
        contract_status=contract_status,
        numerical_status=numerical_status,
        tau=tau,
        returned_interval=returned_interval,
        time=time,
        state=state_payload,
        derived=derived,
        events=events,
        diagnostics=diagnostics,
        observations=observations,
        metadata={
            **identity,
            "integrator": method,
            "rtol": rtol,
            "effective_rtol": rtol,
            "atol": atol,
            "atol_angle": atol_angle,
            "atol_rate": atol_rate,
            "effective_atol_vector": atol_vector,
            "max_step": max_step,
            "effective_max_step": effective_max_step,
            "integration_retry": integration_retry,
            "fast_mode_max_phase_step": float(max_step * omega_plus),
            "omega_plus": omega_plus,
            "event_cluster_tolerance": event_tolerance,
            "constraint_projection_applied": False,
            "coordinate_note": (
                "theta is an unwrapped real representative; n and eta are global "
                "Cartesian coordinates; no constraint projection is applied"
            ),
        },
    )


def _frame(
    params: JunctionParameters, theta: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    theta = np.asarray(theta, dtype=float)
    e_r = (
        np.sin(theta)[:, None] * params.e_y
        + np.cos(theta)[:, None] * params.e_z
    )
    e_theta = (
        np.cos(theta)[:, None] * params.e_y
        - np.sin(theta)[:, None] * params.e_z
    )
    return e_r, e_theta


def _validate_obstacles(
    raw: Any, issues: list[ValidationIssue]
) -> tuple[JunctionObstacle, ...]:
    if not isinstance(raw, list):
        issues.append(
            ValidationIssue("TYPE", "physical.obstacles", raw, "array of obstacle objects")
        )
        return ()
    if len(raw) > _MAX_OBSTACLES:
        issues.append(
            ValidationIssue(
                "JUNCTION_OBSTACLE_COUNT",
                "physical.obstacles",
                len(raw),
                f"at most {_MAX_OBSTACLES} obstacles",
            )
        )
    result: list[JunctionObstacle] = []
    ids: set[str] = set()
    for index, item in enumerate(raw[:_MAX_OBSTACLES]):
        path = f"physical.obstacles[{index}]"
        if not isinstance(item, dict):
            issues.append(ValidationIssue("TYPE", path, item, "obstacle object"))
            continue
        obstacle_id = item.get("id")
        kind = item.get("kind")
        target = item.get("target")
        if not isinstance(obstacle_id, str) or not _OBSTACLE_ID.fullmatch(obstacle_id):
            issues.append(
                ValidationIssue(
                    "JUNCTION_OBSTACLE_ID",
                    f"{path}.id",
                    obstacle_id,
                    "unique 1--64 character ASCII identifier",
                )
            )
            obstacle_id = f"invalid_{index}"
        elif obstacle_id in ids:
            issues.append(
                ValidationIssue(
                    "JUNCTION_OBSTACLE_ID",
                    f"{path}.id",
                    obstacle_id,
                    "unique obstacle identifier",
                )
            )
        ids.add(obstacle_id)
        if target not in {"junction", "bob"}:
            issues.append(
                ValidationIssue(
                    "JUNCTION_OBSTACLE_TARGET",
                    f"{path}.target",
                    target,
                    "junction or bob",
                )
            )
            target = "bob"
        if kind == "sphere":
            reject_unknown_keys(
                item, {"id", "kind", "target", "center", "radius"}, path, issues
            )
            center = as_vector3(item.get("center"), f"{path}.center", issues)
            radius = require_number(item, "radius", path, issues, positive=True)
            result.append(
                JunctionObstacle(
                    id=obstacle_id,
                    kind="sphere",
                    target=str(target),
                    center=center,
                    radius=radius,
                )
            )
        elif kind == "plane":
            reject_unknown_keys(
                item,
                {"id", "kind", "target", "point", "normal", "allowed_side"},
                path,
                issues,
            )
            point = as_vector3(item.get("point"), f"{path}.point", issues)
            normal = as_vector3(item.get("normal"), f"{path}.normal", issues)
            if abs(float(np.linalg.norm(normal)) - 1.0) > 1.0e-10:
                issues.append(
                    ValidationIssue(
                        "JUNCTION_OBSTACLE_GEOMETRY",
                        f"{path}.normal",
                        normal,
                        "unit vector",
                    )
                )
            side_raw = item.get("allowed_side", 1)
            if not is_finite_number(side_raw) or float(side_raw) not in {-1.0, 1.0}:
                issues.append(
                    ValidationIssue(
                        "JUNCTION_OBSTACLE_GEOMETRY",
                        f"{path}.allowed_side",
                        side_raw,
                        "+1 or -1",
                    )
                )
                side = 1.0
            else:
                side = float(side_raw)
            result.append(
                JunctionObstacle(
                    id=obstacle_id,
                    kind="plane",
                    target=str(target),
                    point=point,
                    normal=normal,
                    allowed_side=side,
                )
            )
        else:
            reject_unknown_keys(item, {"id", "kind", "target"}, path, issues)
            issues.append(
                ValidationIssue(
                    "JUNCTION_OBSTACLE_KIND",
                    f"{path}.kind",
                    kind,
                    "sphere or plane",
                )
            )
    return tuple(result)


def _obstacle_clearance(
    obstacle: JunctionObstacle, J: np.ndarray, r_m: np.ndarray
) -> np.ndarray:
    position = J if obstacle.target == "junction" else r_m
    if obstacle.kind == "sphere":
        assert obstacle.center is not None and obstacle.radius is not None
        return np.linalg.norm(position - obstacle.center, axis=1) - obstacle.radius
    assert obstacle.point is not None and obstacle.normal is not None
    return obstacle.allowed_side * ((position - obstacle.point) @ obstacle.normal)


def _omega_plus(params: JunctionParameters) -> float:
    eta_J = params.junction_mass / (params.junction_mass + params.mass)
    h = params.h
    ell = params.lower_length
    D_J = np.sqrt((h + ell) ** 2 - 4.0 * eta_J * h * ell)
    return float(
        np.sqrt(params.g * (h + ell + D_J) / (2.0 * eta_J * h * ell))
    )


def _validate_junction_numerics(
    numerics: dict[str, Any]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    reject_unknown_keys(
        numerics, JUNCTION_NUMERICAL_FIELDS, "numerics", issues
    )
    method = numerics.get("method", "DOP853")
    if method not in {"DOP853", "Radau"}:
        issues.append(
            ValidationIssue(
                "INTEGRATOR", "numerics.method", method, "DOP853 or Radau"
            )
        )
    for field, default in {
        "rtol": 1.0e-10,
        "atol": 1.0e-12,
        "atol_angle": numerics.get("atol", 1.0e-12),
        "atol_rate": numerics.get("atol", 1.0e-12),
        "max_step": None,
        "output_dt": None,
        "event_cluster_tolerance": 1.0e-9,
    }.items():
        value = numerics.get(field, default)
        if value is None:
            continue
        if not is_finite_number(value) or float(value) <= 0.0:
            issues.append(
                ValidationIssue(
                    "NUMERICAL_CONFIG",
                    f"numerics.{field}",
                    value,
                    "positive finite real",
                )
            )
    rtol = numerics.get("rtol", 1.0e-10)
    if is_finite_number(rtol) and 0.0 < float(rtol) < MIN_SOLVER_RTOL:
        issues.append(
            ValidationIssue(
                "NUMERICAL_CONFIG",
                "numerics.rtol",
                rtol,
                f">= SciPy machine floor {MIN_SOLVER_RTOL:.17g}",
            )
        )
    return issues


def _positive_value(value: Any, fallback: float) -> float:
    return float(value) if is_finite_number(value) and float(value) > 0.0 else fallback


def _invalid_numerical(
    identity: dict[str, Any], issues: list[ValidationIssue]
) -> SimulationResult:
    return SimulationResult(
        model_id=JUNCTION_MODEL_ID,
        contract_status=[],
        numerical_status="INVALID_NUMERICAL_CONFIG",
        tau=0.0,
        returned_interval="empty",
        time=np.empty(0),
        events=[
            {
                "kind": "numerical_input",
                "failures": [issue.as_dict() for issue in issues],
            }
        ],
        metadata=identity,
    )


def _guard_values(params: JunctionParameters, state: np.ndarray) -> np.ndarray:
    derived = junction_derived(params, np.asarray(state)[None, :])
    values = [
        float(derived["T_A"][0]),
        float(derived["T_B"][0]),
        float(derived["T_lower"][0]),
    ]
    values.extend(
        float(derived["obstacle_clearance"][obstacle.id][0])
        for obstacle in params.obstacles
    )
    return np.asarray(values, dtype=float)


def _make_guard(
    params: JunctionParameters, index: int
) -> Callable[[float, np.ndarray], float]:
    def event(_time: float, state: np.ndarray) -> float:
        return float(_guard_values(params, state)[index])

    event.terminal = True  # type: ignore[attr-defined]
    event.direction = -1.0  # type: ignore[attr-defined]
    return event


def _guard_zero_tolerances(
    params: JunctionParameters, rtol: float
) -> np.ndarray:
    eps_factor = max(4096.0 * np.finfo(float).eps, 32.0 * rtol)
    force_scale = max(
        (params.mass + params.junction_mass) * params.g,
        np.finfo(float).tiny,
    )
    length_scale = max(
        params.s_A,
        params.s_B,
        params.lower_length,
        params.d,
        params.h,
        np.finfo(float).tiny,
    )
    return np.asarray(
        [eps_factor * force_scale] * 3
        + [eps_factor * length_scale] * len(params.obstacles),
        dtype=float,
    )


def _root_bracket(times: np.ndarray, root: float) -> list[float]:
    if times.size == 0:
        return [0.0, float(root)]
    index = int(np.searchsorted(times, root, side="left"))
    upper_index = min(index, times.size - 1)
    lower_index = max(0, upper_index - 1)
    return [float(times[lower_index]), float(times[upper_index])]


def _audit_dense_guards(
    params: JunctionParameters,
    sol: Any,
    guard_names: list[str],
    *,
    known_event_tau: float,
    known_triggers: set[str],
    event_tolerance: float,
    rtol: float,
) -> dict[str, Any] | None:
    """Find non-sign-changing touches that ``solve_ivp`` events can miss."""

    times = np.asarray(sol.t, dtype=float)
    if times.size < 2:
        return None
    zero_tolerances = _guard_zero_tolerances(params, rtol)
    for interval in range(times.size - 1):
        left = float(times[interval])
        right = float(times[interval + 1])
        if not right > left:
            continue
        left_values = _guard_values(params, np.asarray(sol.sol(left), dtype=float))
        right_values = _guard_values(params, np.asarray(sol.sol(right), dtype=float))
        for guard_index, (name, tolerance) in enumerate(
            zip(guard_names, zero_tolerances)
        ):
            objective = lambda query: float(
                _guard_values(
                    params, np.asarray(sol.sol(float(query)), dtype=float)
                )[guard_index]
            )
            optimum = minimize_scalar(
                objective,
                bounds=(left, right),
                method="bounded",
                options={
                    "xatol": max(
                        event_tolerance / 4.0,
                        32.0 * np.finfo(float).eps * max(1.0, abs(right)),
                    ),
                    "maxiter": 48,
                },
            )
            if (
                not bool(getattr(optimum, "success", False))
                or not np.isfinite(float(getattr(optimum, "x", np.nan)))
                or not np.isfinite(float(getattr(optimum, "fun", np.nan)))
            ):
                return {
                    "kind": "numerical_event_unresolved",
                    "numerical_status": "EVENT_UNRESOLVED",
                    "reason": "guard minimum search failed",
                    "trigger": name,
                    "optimizer_message": str(
                        getattr(optimum, "message", "no optimizer status")
                    ),
                    "root_bracket": [left, right],
                    "root_bracket_basis": (
                        "accepted solver interval containing the failed guard audit"
                    ),
                }
            candidates = [
                (left, float(left_values[guard_index])),
                (right, float(right_values[guard_index])),
                (float(optimum.x), float(optimum.fun)),
            ]
            minimum_time, minimum_value = min(candidates, key=lambda item: item[1])
            if minimum_value > tolerance:
                continue
            ends_at_known_exit = (
                np.isfinite(known_event_tau)
                and abs(right - known_event_tau) <= event_tolerance
                and abs(minimum_time - right)
                <= max(event_tolerance, 1.0e-6 * (right - left))
            )
            if ends_at_known_exit and minimum_value > 0.0:
                # The trajectory is no longer interpreted after the already
                # located physical exit at ``right``.  Another guard that is
                # still strictly positive there cannot have triggered first,
                # even when its margin is below the audit uncertainty scale.
                continue
            matches_known_root = (
                np.isfinite(known_event_tau)
                and name in known_triggers
                and right >= known_event_tau - event_tolerance
                and abs(minimum_time - known_event_tau)
                <= max(event_tolerance, 1.0e-6 * (right - left))
            )
            if matches_known_root:
                continue
            return {
                "kind": "numerical_event_unresolved",
                "numerical_status": "EVENT_UNRESOLVED",
                "reason": "grazing or unbracketed guard minimum",
                "trigger": name,
                "suspected_time": minimum_time,
                "minimum_guard_value": minimum_value,
                "guard_zero_tolerance": float(tolerance),
                "root_bracket": [left, right],
                "root_bracket_basis": (
                    "accepted solver interval; grazing screen, not an "
                    "independent event-time error bound"
                ),
            }
    return None


def _accepted_invariant_issue(
    params: JunctionParameters, sol: Any
) -> dict[str, Any] | None:
    states = np.asarray(sol.y, dtype=float).T
    times = np.asarray(sol.t, dtype=float)
    if states.shape != (times.size, 8) or not np.all(np.isfinite(states)):
        return {
            "kind": "numerical_nonfinite_state",
            "numerical_status": "NONFINITE_STATE",
            "time": float(times[-1]) if times.size else 0.0,
            "last_certified_time": float(times[-2]) if times.size > 1 else 0.0,
        }
    derived = junction_derived(params, states)
    position_error = np.abs(derived["n_norm_error"])
    velocity_error = np.abs(derived["n_dot_eta"])
    invalid = (position_error > _CONSTRAINT_TOLERANCE) | (
        velocity_error > _CONSTRAINT_TOLERANCE
    )
    indices = np.flatnonzero(invalid)
    if indices.size:
        index = int(indices[0])
        return {
            "kind": "numerical_invariant_failure",
            "numerical_status": "INVARIANT_FAILURE",
            "time": float(times[index]),
            "last_certified_time": float(times[max(0, index - 1)]),
            "max_abs_n_norm_error_at_detection": float(position_error[index]),
            "max_abs_n_dot_eta_at_detection": float(velocity_error[index]),
            "constraint_tolerance": _CONSTRAINT_TOLERANCE,
        }
    energy = np.asarray(derived["E_junction"], dtype=float)
    if energy.size:
        drift = np.abs(energy - energy[0])
        gravitational_scale = (
            (params.mass + params.junction_mass) * params.g * params.h
            + params.mass * params.g * params.lower_length
        )
        excitation_floor = 4096.0 * np.finfo(float).eps * gravitational_scale
        if abs(float(energy[0])) > excitation_floor:
            invalid_energy = drift > _RELATIVE_ENERGY_TOLERANCE * abs(float(energy[0]))
        else:
            invalid_energy = drift > 1.0e-10 * gravitational_scale
        indices = np.flatnonzero(invalid_energy)
        if indices.size:
            index = int(indices[0])
            return {
                "kind": "numerical_energy_failure",
                "numerical_status": "ENERGY_INVARIANT_FAILURE",
                "time": float(times[index]),
                "last_certified_time": float(times[max(0, index - 1)]),
                "absolute_energy_drift_at_detection": float(drift[index]),
                "initial_excitation_energy": float(energy[0]),
                "relative_tolerance": _RELATIVE_ENERGY_TOLERANCE,
            }
    return None


def _run_diagnostics(
    params: JunctionParameters,
    sol: Any,
    derived: dict[str, Any],
    *,
    omega_plus: float,
    solver_warnings: list[dict[str, str]],
    event_root_bracket: list[float] | None,
) -> dict[str, Any]:
    accepted_states = np.asarray(sol.y, dtype=float).T
    accepted = junction_derived(params, accepted_states) if accepted_states.size else {}
    energy = np.asarray(accepted.get("E_junction", np.empty(0)), dtype=float)
    energy_drift = (
        np.abs(energy - energy[0]) if energy.size else np.empty(0)
    )
    energy_scale = abs(float(energy[0])) if energy.size else 0.0
    gravitational_scale = (
        (params.mass + params.junction_mass) * params.g * params.h
        + params.mass * params.g * params.lower_length
    )
    relative_energy_drift = (
        float(np.max(energy_drift) / energy_scale)
        if energy.size and energy_scale > 4096.0 * np.finfo(float).eps * gravitational_scale
        else None
    )
    sampled_guards: dict[str, Any] = {}
    if derived:
        sampled_guards = {
            "T_A_ZERO": np.asarray(derived["T_A"], dtype=float),
            "T_B_ZERO": np.asarray(derived["T_B"], dtype=float),
            "T_LOWER_ZERO": np.asarray(derived["T_lower"], dtype=float),
        }
        sampled_guards.update(
            {
                f"CONTACT_{obstacle.id}": np.asarray(
                    derived["obstacle_clearance"][obstacle.id], dtype=float
                )
                for obstacle in params.obstacles
            }
        )
    accepted_differences = np.diff(np.asarray(sol.t, dtype=float))
    min_tensions = {
        name: (
            float(np.min(accepted[name]))
            if accepted and np.asarray(accepted[name]).size
            else None
        )
        for name in ("T_A", "T_B", "T_lower")
    }
    force_residual = np.asarray(
        accepted.get("junction_force_residual", np.empty((0, 3))), dtype=float
    )
    bob_residual = np.asarray(
        accepted.get("bob_force_residual", np.empty((0, 3))), dtype=float
    )
    return {
        "solver_message": sol.message,
        "nfev": int(sol.nfev),
        "njev": int(getattr(sol, "njev", 0)),
        "nlu": int(getattr(sol, "nlu", 0)),
        "accepted_steps": max(0, int(np.asarray(sol.t).size) - 1),
        "max_actual_step": (
            float(np.max(accepted_differences)) if accepted_differences.size else 0.0
        ),
        "omega_plus": omega_plus,
        "max_actual_fast_mode_phase_step": (
            float(np.max(accepted_differences) * omega_plus)
            if accepted_differences.size
            else 0.0
        ),
        "initial_energy": float(energy[0]) if energy.size else None,
        "energy_scale": energy_scale if energy.size else None,
        "energy_scale_basis": "absolute initial J.7 excitation energy",
        "max_absolute_energy_drift": (
            float(np.max(energy_drift)) if energy_drift.size else None
        ),
        "max_relative_energy_drift": relative_energy_drift,
        "max_abs_n_norm_error": (
            float(np.max(np.abs(accepted["n_norm_error"]))) if accepted else None
        ),
        "max_abs_n_dot_eta": (
            float(np.max(np.abs(accepted["n_dot_eta"]))) if accepted else None
        ),
        "max_abs_upper_length_error": (
            max(
                float(np.max(np.abs(accepted["upper_A_length_error"]))),
                float(np.max(np.abs(accepted["upper_B_length_error"]))),
            )
            if accepted
            else None
        ),
        "max_abs_lower_length_error": (
            float(np.max(np.abs(accepted["lower_length_error"])))
            if accepted
            else None
        ),
        "max_junction_force_residual": (
            float(np.max(np.linalg.norm(force_residual, axis=1)))
            if force_residual.size
            else None
        ),
        "max_bob_force_residual": (
            float(np.max(np.linalg.norm(bob_residual, axis=1)))
            if bob_residual.size
            else None
        ),
        "min_tensions": min_tensions,
        "event_root_bracket": event_root_bracket,
        "event_root_bracket_basis": (
            "adjacent accepted solver times; not an independent event-time error bound"
            if event_root_bracket is not None
            else None
        ),
        "dense_guard_audit": (
            "bounded scalar minimization plus endpoints on every accepted step"
        ),
        "dense_guard_audit_scope": (
            "conservative screen for missed sign changes and grazing minima under "
            "the configured step/fast-mode bound; not a proof for arbitrary "
            "continuous guards"
        ),
        "sampled_guard_component_series": sampled_guards,
        "constraint_projection_applied": False,
        "projection_energy_correction_J": None,
        "refinement_qualification": "SINGLE_RUN_CANDIDATE",
        "solver_warnings": solver_warnings,
    }


def _first_sample(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _first_sample(child) for key, child in value.items()}
    array = np.asarray(value)
    return array[0] if array.ndim else array


def _output_times(end: float, step: float, *, include_end: bool) -> np.ndarray:
    if end < 0.0:
        return np.empty(0)
    count = safe_uniform_sample_count(
        end, step, maximum_samples=MAX_UNIFORM_SAMPLES
    )
    if count is None:
        raise ValueError("unsafe uniform output grid")
    values = step * np.arange(count)
    if include_end and (
        not values.size
        or values[-1] < end - 1.0e-13 * max(1.0, abs(end))
    ):
        values = np.append(values, end)
    if not include_end:
        values = values[values < end]
    return values


def _unresolved_observations(
    spec: Any, numerical_status: str, time: float
) -> dict[str, Any]:
    if spec is None:
        return {}
    return {
        "status": ["OBSERVATION_UNRESOLVED_DUE_TO_NUMERICS"],
        "operator": None,
        "time": np.empty(0),
        "values": np.empty((0, 2)),
        "valid_mask": np.empty(0, dtype=bool),
        "errors": [
            {"code": numerical_status, "detected_at_sample": float(time)}
        ],
    }

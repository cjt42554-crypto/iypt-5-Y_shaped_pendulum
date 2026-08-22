"""Independent numerical backend for the frozen FWD-TORUS-1.0 model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import warnings

import numpy as np
from scipy.integrate import solve_ivp

from .contracts import (
    SimulationResult,
    MIN_SOLVER_RTOL,
    MAX_UNIFORM_SAMPLES,
    ValidationIssue,
    as_vector3,
    base_validation,
    is_finite_number,
    numerical_time_resource_issues,
    reject_unknown_keys,
    require_number,
    strict_finite_array,
    safe_uniform_sample_count,
)
from .observations import evaluate_observations


TORUS_NUMERICAL_FIELDS = {
    "method",
    "rtol",
    "atol",
    "atol_angle",
    "atol_rate",
    "max_step",
    "output_dt",
    "event_cluster_tolerance",
}


@dataclass(frozen=True)
class TorusParameters:
    A: np.ndarray
    B: np.ndarray
    e_z: np.ndarray
    g: float
    mass: float
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


def validate_torus_config(config: dict[str, Any]) -> tuple[list[ValidationIssue], TorusParameters | None]:
    issues = base_validation(config, "FWD-TORUS-1.0")
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
            "s_A",
            "s_B",
            "lower_length",
            "initial_state",
            "T",
        },
        "physical",
        issues,
    )
    A = as_vector3(physical.get("A"), "physical.A", issues)
    B = as_vector3(physical.get("B"), "physical.B", issues)
    e_z = as_vector3(physical.get("e_z"), "physical.e_z", issues)
    g = require_number(physical, "g", "physical", issues, positive=True)
    mass = require_number(physical, "mass", "physical", issues, positive=True)
    s_A = require_number(physical, "s_A", "physical", issues, positive=True)
    s_B = require_number(physical, "s_B", "physical", issues, positive=True)
    ell = require_number(physical, "lower_length", "physical", issues, positive=True)
    T = require_number(physical, "T", "physical", issues, positive=True)
    initial_raw = physical.get("initial_state")
    initial = strict_finite_array(initial_raw)
    if initial is None or initial.shape != (4,):
        issues.append(ValidationIssue("TYPE", "physical.initial_state", initial_raw, "four finite reals"))
        initial = np.zeros(4)
    d_vector = B - A
    d = float(np.linalg.norm(d_vector))
    geometry_ok = True
    if not d > 0.0:
        issues.append(ValidationIssue("TORUS_GEOMETRY", "physical.A,B", [A, B], "distinct support points"))
        geometry_ok = False
        e_x = np.array([1.0, 0.0, 0.0])
    else:
        e_x = d_vector / d
    if abs(np.linalg.norm(e_z) - 1.0) > 1e-10:
        issues.append(ValidationIssue("TORUS_GEOMETRY", "physical.e_z", e_z, "unit vector"))
        geometry_ok = False
    e_z_norm = float(np.linalg.norm(e_z))
    support_vertical_cosine = (
        abs(float(d_vector @ e_z)) / (d * e_z_norm)
        if d > 0.0 and e_z_norm > 0.0
        else np.inf
    )
    if d > 0 and support_vertical_cosine > 1e-10:
        issues.append(
            ValidationIssue(
                "TORUS_GEOMETRY",
                "physical.A,B,e_z",
                support_vertical_cosine,
                "dimensionless |(B-A) dot e_z|/(|B-A| |e_z|) <= 1e-10",
            )
        )
        geometry_ok = False
    e_y = np.cross(e_z, e_x)
    if not (abs(s_A - s_B) < d < s_A + s_B):
        issues.append(ValidationIssue("TORUS_GEOMETRY", "physical.s_A,s_B,A,B", [s_A, s_B, d], "strict sphere-intersection inequalities"))
        geometry_ok = False
    x_C = (s_A * s_A - s_B * s_B) / (2 * d) if d > 0 else 0.0
    a_A = x_C + d / 2
    a_B = d / 2 - x_C
    h2 = s_A * s_A - a_A * a_A
    if not (a_A > 0 and a_B > 0):
        issues.append(ValidationIssue("TORUS_WORKING_BAND", "derived.a_A,a_B", [a_A, a_B], "both > 0"))
        geometry_ok = False
    if not h2 > 0:
        issues.append(ValidationIssue("TORUS_GEOMETRY", "derived.h2", h2, "> 0"))
        geometry_ok = False
    h = float(np.sqrt(max(h2, 0.0)))
    O = (A + B) / 2
    if geometry_ok:
        params = TorusParameters(A, B, e_z, g, mass, s_A, s_B, ell, T, initial, O, e_x, e_y, d, x_C, a_A, a_B, h)
        R0 = h + ell * np.cos(initial[0])
        derived0 = torus_derived(params, initial[None, :])
        initial_tensions = [float(derived0[key][0]) for key in ("T_A", "T_B", "T_lower")]
        if not R0 > 0:
            issues.append(ValidationIssue("TORUS_INITIAL", "physical.initial_state.R", R0, "> 0"))
        if not min(initial_tensions) > 0:
            issues.append(ValidationIssue("TORUS_INITIAL", "physical.initial_state.tensions", initial_tensions, "all > 0"))
    else:
        params = None
    return issues, params


def torus_rhs(params: TorusParameters, _t: float, state: np.ndarray) -> np.ndarray:
    phi, theta, phi_dot, theta_dot = state
    R = params.h + params.lower_length * np.cos(phi)
    if not R > 0.0:
        raise FloatingPointError("torus R left its positive domain")
    phi_ddot = -(
        R * np.sin(phi) * theta_dot * theta_dot
        + params.g * np.sin(phi) * np.cos(theta)
    ) / params.lower_length
    theta_ddot = (
        2 * params.lower_length * np.sin(phi) * phi_dot * theta_dot
        - params.g * np.sin(theta)
    ) / R
    return np.array([phi_dot, theta_dot, phi_ddot, theta_ddot])


def torus_derived(params: TorusParameters, states: np.ndarray) -> dict[str, np.ndarray]:
    states = np.asarray(states, dtype=float)
    phi, theta, phi_dot, theta_dot = states.T
    ell = params.lower_length
    R = params.h + ell * np.cos(phi)
    e_r = np.sin(theta)[:, None] * params.e_y + np.cos(theta)[:, None] * params.e_z
    junction = params.O + params.x_C * params.e_x + params.h * e_r
    bob = (
        params.O
        + (params.x_C + ell * np.sin(phi))[:, None] * params.e_x
        + R[:, None] * e_r
    )
    T_lower = params.mass * (
        ell * phi_dot**2
        + R * np.cos(phi) * theta_dot**2
        + params.g * np.cos(phi) * np.cos(theta)
    )
    T_A = params.s_A * T_lower / params.d * (
        np.sin(phi) + params.a_B / params.h * np.cos(phi)
    )
    T_B = params.s_B * T_lower / params.d * (
        params.a_A / params.h * np.cos(phi) - np.sin(phi)
    )
    energy = (
        0.5 * params.mass * (ell * ell * phi_dot**2 + R * R * theta_dot**2)
        + params.mass * params.g * ((params.h + ell) - R * np.cos(theta))
    )
    relative = bob - params.O
    x = relative @ params.e_x
    y = relative @ params.e_y
    z = relative @ params.e_z
    r_perp = np.sqrt(y * y + z * z)
    Q_T = (x - params.x_C) ** 2 + r_perp**2 + params.h**2 - ell**2
    torus_residual = (x - params.x_C) ** 2 + (r_perp - params.h) ** 2 - ell**2
    return {
        "J": junction,
        "r_m": bob,
        "R": R,
        "T_A": T_A,
        "T_B": T_B,
        "T_lower": T_lower,
        "E_torus": energy,
        "r_perp": r_perp,
        "Q_T": Q_T,
        "torus_unsquared_residual": torus_residual,
        "physical_branch_residual": Q_T - 2 * params.h * r_perp,
    }


def run_torus(
    config: dict[str, Any], *, identity: dict[str, Any]
) -> SimulationResult:
    issues, params = validate_torus_config(config)
    if issues or params is None:
        return SimulationResult(
            model_id="FWD-TORUS-1.0",
            contract_status=["INVALID_INPUT"],
            numerical_status="INPUT_REJECTED",
            tau=0.0,
            returned_interval="empty",
            time=np.empty(0),
            events=[{"kind": "input", "failures": [issue.as_dict() for issue in issues]}],
            metadata=identity,
        )
    numerics = config.get("numerics", {})
    if not isinstance(numerics, dict):
        return _invalid_numerics(config, "numerics", numerics, "object", identity)
    numerical_issues = _validate_torus_numerics(numerics)
    if numerical_issues:
        return _invalid_numerical_issues(config, numerical_issues, identity)
    method = str(numerics.get("method", "DOP853"))
    rtol = float(numerics.get("rtol", 1e-9))
    atol = float(numerics.get("atol", 1e-11))
    atol_angle = float(numerics.get("atol_angle", atol))
    atol_rate = float(numerics.get("atol_rate", atol))
    max_step = float(numerics.get("max_step", params.T / 200.0))
    output_dt = float(numerics.get("output_dt", params.T / 1000))
    if not (np.isfinite(rtol) and rtol > 0 and np.isfinite(atol) and atol > 0 and np.isfinite(atol_angle) and atol_angle > 0 and np.isfinite(atol_rate) and atol_rate > 0 and max_step > 0 and np.isfinite(output_dt) and output_dt > 0):
        return _invalid_numerics(
            config,
            "numerics",
            numerics,
            "positive finite rtol, atol/atol_angle/atol_rate, output_dt; max_step > 0",
            identity,
        )
    resource_issues = numerical_time_resource_issues(
        params.T, max_step, output_dt
    )
    if resource_issues:
        return _invalid_numerical_issues(config, resource_issues, identity)
    atol_vector = np.array([atol_angle, atol_angle, atol_rate, atol_rate])

    event_names = ["R_ZERO", "T_A_ZERO", "T_B_ZERO", "T_LOWER_ZERO"]

    def guard_component(index):
        def event(_t, state):
            values = torus_derived(params, np.asarray(state)[None, :])
            return float([values["R"][0], values["T_A"][0], values["T_B"][0], values["T_lower"][0]][index])

        event.terminal = True
        event.direction = 0
        return event

    guards = [guard_component(index) for index in range(4)]
    try:
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always")
            sol = solve_ivp(
                lambda t, y: torus_rhs(params, t, y),
                (0.0, params.T),
                params.initial_state,
                method=method,
                rtol=rtol,
                atol=atol_vector,
                max_step=max_step,
                dense_output=True,
                events=guards,
            )
    except Exception as exc:  # numerical backend must return, not counterfeit physics
        return SimulationResult(
            model_id="FWD-TORUS-1.0",
            contract_status=[],
            numerical_status="SOLVER_FAILURE",
            tau=0.0,
            returned_interval="unresolved",
            time=np.empty(0),
            events=[{"kind": "numerical_failure", "message": repr(exc)}],
            metadata=identity,
        )
    solver_warnings = [
        {"category": item.category.__name__, "message": str(item.message)}
        for item in caught_warnings
    ]
    event_times = [float(times[0]) for times in sol.t_events if len(times)]
    event_tau = min(event_times) if event_times else np.inf
    event_tol = float(numerics.get("event_cluster_tolerance", 1e-9))
    if solver_warnings:
        tau = float(sol.t[-1]) if sol.t.size else 0.0
        completed = False
        contract_status = []
        numerical_status = "SOLVER_WARNING"
        returned_interval = f"[0,{tau}] candidate only; warning made status unresolved"
        events = [{"kind": "numerical_warning", "warnings": solver_warnings}]
    elif not sol.success:
        tau = float(sol.t[-1]) if sol.t.size else 0.0
        completed = False
        contract_status: list[str] = []
        numerical_status = "SOLVER_FAILURE"
        returned_interval = f"[0,{tau}] last accepted; physical status unresolved"
        events = [{"kind": "numerical_failure", "message": sol.message}]
    elif np.isfinite(event_tau) and event_tau <= params.T + event_tol:
        tau = min(event_tau, params.T)
        completed = False
        contract_status = ["OUT_OF_SCOPE"]
        numerical_status = "SUCCESS_EVENT"
        returned_interval = f"[0,{tau})"
        event_state = np.asarray(sol.sol(tau), dtype=float)
        guard_values = torus_derived(params, event_state[None, :])
        triggered = [
            name
            for name, times in zip(event_names, sol.t_events)
            if len(times) and abs(float(times[0]) - event_tau) <= event_tol
        ]
        tension_values = np.asarray(
            [
                guard_values["T_A"][0],
                guard_values["T_B"][0],
                guard_values["T_lower"][0],
            ],
            dtype=float,
        )
        # The zero certificate uses a run-input-derived force scale.  It must
        # not expand with the candidate root values themselves, otherwise a
        # nonzero tension could manufacture its own permissive tolerance.
        tension_scale = max(
            params.mass * params.g,
            np.finfo(float).tiny,
        )
        tension_zero_tolerance = 1024.0 * np.finfo(float).eps * tension_scale
        for name, value in zip(event_names[1:], tension_values):
            if abs(float(value)) <= tension_zero_tolerance:
                triggered.append(name)
        length_scale = max(
            params.s_A,
            params.s_B,
            params.lower_length,
            params.d,
            params.h,
            np.finfo(float).tiny,
        )
        if abs(float(guard_values["R"][0])) <= (
            1024.0 * np.finfo(float).eps * length_scale
        ):
            triggered.append("R_ZERO")
        # In the frozen torus equations both upper tensions are exact finite
        # multipliers of T_lower.  This is a model identity, unlike a generic
        # mixed-unit absolute-value threshold.
        if "T_LOWER_ZERO" in triggered:
            triggered.extend(("T_A_ZERO", "T_B_ZERO"))
        triggered = sorted(set(triggered))
        events = [{
            "kind": "physical_exit",
            "time": tau,
            "triggers": triggered,
            "state_left": event_state,
            "derived_left": {
                name: np.asarray(value)[0]
                for name, value in guard_values.items()
            },
            "guard_values": {name: float(value) for name, value in zip(event_names, [guard_values["R"][0], guard_values["T_A"][0], guard_values["T_B"][0], guard_values["T_lower"][0]])},
            "guard_zero_tolerances": {
                name: (
                    1024.0 * np.finfo(float).eps * length_scale
                    if name == "R_ZERO"
                    else tension_zero_tolerance
                )
                for name in triggered
            },
        }]
    else:
        tau = params.T
        completed = True
        contract_status = ["COMPLETED"]
        numerical_status = "SUCCESS_SINGLE_RUN"
        returned_interval = f"[0,{params.T}]"
        events = []

    time = _output_times(tau, output_dt, include_end=completed or not contract_status)
    states = np.asarray(sol.sol(time), dtype=float).T if time.size else np.empty((0, 4))
    derived = torus_derived(params, states) if time.size else {}
    diagnostics = _torus_run_diagnostics(
        params, time, derived, sol, solver_warnings
    )

    postrun_failure = (
        _torus_completed_sample_failure(params, time, states, derived)
        if completed
        else None
    )
    if postrun_failure is not None:
        candidate_diagnostics = diagnostics
        completed = False
        contract_status = []
        numerical_status = postrun_failure["numerical_status"]
        tau = float(postrun_failure["time"])
        returned_interval = (
            "candidate samples only; completed physical contract could not be "
            f"certified at or before {tau}"
        )
        events = [postrun_failure]
        failure_index = int(postrun_failure.get("sample_index", 0))
        time = time[:failure_index]
        states = states[:failure_index]
        derived = {
            name: np.asarray(value)[:failure_index]
            for name, value in derived.items()
        }
        diagnostics = _torus_run_diagnostics(
            params, time, derived, sol, solver_warnings
        )
        diagnostics["postrun_failure"] = postrun_failure
        diagnostics["candidate_full_diagnostics_at_detection"] = (
            candidate_diagnostics
        )

    def position_at(times):
        query_states = np.asarray(sol.sol(times), dtype=float).T
        return torus_derived(params, query_states)["r_m"]

    observations = (
        {
            "status": ["OBSERVATION_UNRESOLVED_DUE_TO_NUMERICS"],
            "errors": [
                {
                    "code": numerical_status,
                    "detected_at_sample": tau,
                }
            ],
        }
        if postrun_failure is not None and config.get("observation") is not None
        else evaluate_observations(
            config.get("observation"),
            position_at=position_at,
            interval_end=tau,
            completed=completed,
            e_z=params.e_z,
            event_time_tolerance=event_tol,
        )
    )
    return SimulationResult(
        model_id="FWD-TORUS-1.0",
        contract_status=contract_status,
        numerical_status=numerical_status,
        tau=tau,
        returned_interval=returned_interval,
        time=time,
        state={"X_torus": states},
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
            "effective_atol_vector": {
                "angle": atol_angle,
                "rate": atol_rate,
            },
            "max_step": max_step,
            "event_cluster_tolerance": event_tol,
            "coordinate_note": "angles integrated on real representatives; no modulo during integration",
        },
    )


def _torus_run_diagnostics(
    params: TorusParameters,
    time: np.ndarray,
    derived: dict[str, Any],
    sol: Any,
    solver_warnings: list[dict[str, str]],
) -> dict[str, Any]:
    energy = np.asarray(derived.get("E_torus", np.empty(0)), dtype=float)
    energy_variation = (
        float(np.max(np.abs(energy - energy[0]))) if energy.size else 0.0
    )
    gravitational_scale = params.mass * params.g * params.lower_length
    energy_scale = max(
        gravitational_scale,
        energy_variation,
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
    tension_scale = max(
        params.mass * params.g,
        np.finfo(float).tiny,
    )
    guard_component_series = {
        "R_ZERO": np.asarray(derived.get("R", np.empty(0)), dtype=float),
        "T_A_ZERO": np.asarray(
            derived.get("T_A", np.empty(0)), dtype=float
        ),
        "T_B_ZERO": np.asarray(
            derived.get("T_B", np.empty(0)), dtype=float
        ),
        "T_LOWER_ZERO": np.asarray(
            derived.get("T_lower", np.empty(0)), dtype=float
        ),
    }
    return {
        "solver_message": sol.message,
        "nfev": int(sol.nfev),
        "njev": int(getattr(sol, "njev", 0)),
        "nlu": int(getattr(sol, "nlu", 0)),
        "energy_scale": float(energy_scale),
        "energy_scale_components": {
            "gravitational": float(gravitational_scale),
            "energy_variation": float(energy_variation),
        },
        "max_absolute_energy_drift": energy_variation if energy.size else None,
        "max_relative_energy_drift": (
            float(energy_variation / energy_scale) if energy.size else None
        ),
        "max_abs_torus_unsquared_residual": (
            float(np.max(np.abs(derived["torus_unsquared_residual"])))
            if time.size
            else None
        ),
        "max_abs_physical_branch_residual": (
            float(np.max(np.abs(derived["physical_branch_residual"])))
            if time.size
            else None
        ),
        "min_Q_T": float(np.min(derived["Q_T"])) if time.size else None,
        "sampled_guard_component_series": guard_component_series,
        "guard_component_scales": {
            "R_ZERO": float(length_scale),
            "T_A_ZERO": float(tension_scale),
            "T_B_ZERO": float(tension_scale),
            "T_LOWER_ZERO": float(tension_scale),
        },
        "refinement_qualification": "SINGLE_RUN_CANDIDATE",
        "solver_warnings": solver_warnings,
    }
def _torus_completed_sample_failure(
    params: TorusParameters,
    time: np.ndarray,
    states: np.ndarray,
    derived: dict[str, Any],
) -> dict[str, Any] | None:
    """Fail closed on sampled evidence that a nominal completion is invalid.

    ``solve_ivp`` locates sign-changing roots, but a tangential contact can
    touch a zero guard without changing sign.  A completion is therefore
    certified only if every returned sample is finite, remains strictly away
    from the four physical guards at its own machine-scaled tolerance, and
    satisfies both unsquared torus identities to roundoff scale.
    """

    if not time.size or states.shape != (time.size, 4):
        return {
            "kind": "numerical_invariant_failure",
            "numerical_status": "INVARIANT_FAILURE",
            "time": 0.0,
            "reason": "missing or malformed completed state samples",
        }
    if not np.all(np.isfinite(states)):
        bad_rows = np.flatnonzero(~np.all(np.isfinite(states), axis=1))
        index = int(bad_rows[0]) if bad_rows.size else 0
        return {
            "kind": "numerical_nonfinite_state",
            "numerical_status": "NONFINITE_STATE",
            "time": float(time[index]),
            "sample_index": index,
        }
    required = {
        "R",
        "T_A",
        "T_B",
        "T_lower",
        "Q_T",
        "torus_unsquared_residual",
        "physical_branch_residual",
    }
    if not required.issubset(derived):
        return {
            "kind": "numerical_invariant_failure",
            "numerical_status": "INVARIANT_FAILURE",
            "time": 0.0,
            "reason": f"missing derived fields: {sorted(required - set(derived))}",
        }
    for name, value in derived.items():
        array = np.asarray(value)
        if array.dtype == object or not np.all(np.isfinite(array)):
            index = 0
            if array.ndim and array.shape[0] == time.size:
                rows = np.reshape(np.isfinite(array), (time.size, -1)).all(axis=1)
                bad_rows = np.flatnonzero(~rows)
                if bad_rows.size:
                    index = int(bad_rows[0])
            return {
                "kind": "numerical_nonfinite_state",
                "numerical_status": "NONFINITE_STATE",
                "time": float(time[index]),
                "sample_index": index,
                "field": name,
            }

    length_scale = max(
        params.s_A,
        params.s_B,
        params.lower_length,
        params.d,
        params.h,
    )
    eps = np.finfo(float).eps
    R = np.asarray(derived["R"], dtype=float)
    tensions = {
        name: np.asarray(derived[name], dtype=float)
        for name in ("T_A", "T_B", "T_lower")
    }
    guard_hits: list[tuple[int, str, float, float]] = []
    R_tolerance = 1024.0 * eps * length_scale
    for index in np.flatnonzero(R <= R_tolerance):
        guard_hits.append(
            (int(index), "R_ZERO", float(R[index]), float(R_tolerance))
        )
    force_reference = params.mass * params.g
    for name, values in tensions.items():
        tolerances = 1024.0 * eps * np.maximum(force_reference, np.abs(values))
        for index in np.flatnonzero(values <= tolerances):
            guard_hits.append(
                (
                    int(index),
                    f"{name.upper()}_ZERO",
                    float(values[index]),
                    float(tolerances[index]),
                )
            )
    if guard_hits:
        first_index = min(item[0] for item in guard_hits)
        hits = [item for item in guard_hits if item[0] == first_index]
        return {
            "kind": "numerical_event_unresolved",
            "numerical_status": "EVENT_UNRESOLVED",
            "time": float(time[first_index]),
            "sample_index": first_index,
            "triggers": sorted({item[1] for item in hits}),
            "sampled_guard_values": {item[1]: item[2] for item in hits},
            "guard_zero_tolerances": {item[1]: item[3] for item in hits},
        }

    squared_scale = max(length_scale * length_scale, np.finfo(float).tiny)
    residual_tolerance = 8192.0 * eps * squared_scale
    unsquared = np.abs(
        np.asarray(derived["torus_unsquared_residual"], dtype=float)
    )
    branch = np.abs(
        np.asarray(derived["physical_branch_residual"], dtype=float)
    )
    Q_T = np.asarray(derived["Q_T"], dtype=float)
    invalid = (
        (unsquared > residual_tolerance)
        | (branch > residual_tolerance)
        | (Q_T < -residual_tolerance)
    )
    indices = np.flatnonzero(invalid)
    if indices.size:
        index = int(indices[0])
        return {
            "kind": "numerical_invariant_failure",
            "numerical_status": "INVARIANT_FAILURE",
            "time": float(time[index]),
            "sample_index": index,
            "torus_unsquared_residual": float(unsquared[index]),
            "physical_branch_residual": float(branch[index]),
            "Q_T": float(Q_T[index]),
            "absolute_residual_tolerance": float(residual_tolerance),
        }
    return None


def _output_times(end: float, step: float, *, include_end: bool) -> np.ndarray:
    if end < 0:
        return np.empty(0)
    count = safe_uniform_sample_count(
        end,
        step,
        maximum_samples=MAX_UNIFORM_SAMPLES,
    )
    if count is None:
        raise ValueError("unsafe uniform output grid")
    values = step * np.arange(count)
    if include_end and (not values.size or values[-1] < end - 1e-13 * max(1.0, end)):
        values = np.append(values, end)
    if not include_end:
        values = values[values < end]
    return values


def _invalid_numerics(config, path, actual, expected, identity):
    return SimulationResult(
        model_id="FWD-TORUS-1.0",
        contract_status=[],
        numerical_status="INVALID_NUMERICAL_CONFIG",
        tau=0.0,
        returned_interval="empty",
        time=np.empty(0),
        events=[{"kind": "numerical_input", "failures": [ValidationIssue("NUMERICAL_CONFIG", path, actual, expected).as_dict()]}],
        metadata=identity,
    )


def _validate_torus_numerics(
    numerics: dict[str, Any]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    reject_unknown_keys(
        numerics, TORUS_NUMERICAL_FIELDS, "numerics", issues
    )
    method = numerics.get("method", "DOP853")
    if method not in ("DOP853", "Radau"):
        issues.append(
            ValidationIssue(
                "INTEGRATOR", "numerics.method", method, "DOP853 or Radau"
            )
        )
    defaults = {
        "rtol": 1e-9,
        "atol": 1e-11,
        "atol_angle": numerics.get("atol", 1e-11),
        "atol_rate": numerics.get("atol", 1e-11),
        "max_step": None,
        "output_dt": None,
        "event_cluster_tolerance": 1e-9,
    }
    for field, default in defaults.items():
        value = numerics.get(field, default)
        # T-dependent defaults are injected after physical validation.
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
    rtol = numerics.get("rtol", 1e-9)
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


def _invalid_numerical_issues(
    config: dict[str, Any],
    issues: list[ValidationIssue],
    identity: dict[str, Any],
) -> SimulationResult:
    return SimulationResult(
        model_id="FWD-TORUS-1.0",
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

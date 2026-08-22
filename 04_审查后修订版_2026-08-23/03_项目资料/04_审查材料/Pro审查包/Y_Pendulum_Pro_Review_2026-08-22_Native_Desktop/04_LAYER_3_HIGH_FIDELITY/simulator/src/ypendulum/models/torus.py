"""A1 exact all-taut torus model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.integrate import solve_ivp

from ypendulum.config.models import SimulationConfig
from ypendulum.config.units import as_vector3, to_si
from ypendulum.geometry import UpperGeometry, fixed_knot_upper_geometry
from ypendulum.models.state import TorusResult


@dataclass(frozen=True)
class TorusParameters:
    geometry: UpperGeometry
    upper_length_a: float
    upper_length_b: float
    lower_length: float
    bob_mass: float
    gravity_magnitude: float

    @classmethod
    def from_config(cls, cfg: SimulationConfig) -> "TorusParameters":
        A = as_vector3(cfg.supports.A.position, default_unit="m")
        B = as_vector3(cfg.supports.B.position, default_unit="m")
        gvec = as_vector3(cfg.environment.gravity, default_unit="m/s^2")
        axis = (B - A) / np.linalg.norm(B - A)
        if abs(float(np.dot(axis, gvec))) > 1e-8 * np.linalg.norm(gvec):
            raise ValueError("A1 torus model requires the support axis to be horizontal.")
        sa = float(to_si(cfg.cables.upper_A.rest_length, default_unit="m"))
        sb = float(to_si(cfg.cables.upper_B.rest_length, default_unit="m"))
        lower = float(to_si(cfg.cables.lower.rest_length, default_unit="m"))
        geom = fixed_knot_upper_geometry(A, B, sa, sb, gvec)
        return cls(
            geom,
            sa,
            sb,
            lower,
            float(to_si(cfg.bob.mass, default_unit="kg")),
            float(np.linalg.norm(gvec)),
        )


def torus_rhs(_t: float, state: np.ndarray, p: TorusParameters) -> np.ndarray:
    phi, theta, phi_dot, theta_dot = map(float, state)
    radius = p.geometry.h + p.lower_length * np.cos(phi)
    if radius <= 0:
        raise FloatingPointError("A1 torus coordinate radius became non-positive.")
    phi_ddot = -(
        radius * np.sin(phi) * theta_dot**2
        + p.gravity_magnitude * np.sin(phi) * np.cos(theta)
    ) / p.lower_length
    theta_ddot = (
        2.0 * p.lower_length * np.sin(phi) * phi_dot * theta_dot
        - p.gravity_magnitude * np.sin(theta)
    ) / radius
    return np.array([phi_dot, theta_dot, phi_ddot, theta_ddot], dtype=float)


def torus_coordinates(state: np.ndarray, p: TorusParameters) -> np.ndarray:
    y = np.asarray(state, dtype=float)
    phi = y[..., 0]
    theta = y[..., 1]
    er = (
        np.cos(theta)[..., None] * p.geometry.radial_down
        + np.sin(theta)[..., None] * p.geometry.azimuth
    )
    radius = p.geometry.h + p.lower_length * np.cos(phi)
    return (
        p.geometry.center
        + (p.lower_length * np.sin(phi))[..., None] * p.geometry.axis
        + radius[..., None] * er
    )


def torus_tensions(state: np.ndarray, p: TorusParameters) -> np.ndarray:
    y = np.asarray(state, dtype=float)
    phi = y[..., 0]
    theta = y[..., 1]
    phi_dot = y[..., 2]
    theta_dot = y[..., 3]
    radius = p.geometry.h + p.lower_length * np.cos(phi)
    tl = p.bob_mass * (
        p.lower_length * phi_dot**2
        + radius * np.cos(phi) * theta_dot**2
        + p.gravity_magnitude * np.cos(phi) * np.cos(theta)
    )
    d = p.geometry.distance
    ta = (p.upper_length_a * tl / d) * (
        np.sin(phi) + (p.geometry.a_b / p.geometry.h) * np.cos(phi)
    )
    tb = (p.upper_length_b * tl / d) * (
        (p.geometry.a_a / p.geometry.h) * np.cos(phi) - np.sin(phi)
    )
    return np.stack([ta, tb, tl], axis=-1)


def torus_energy(state: np.ndarray, p: TorusParameters) -> np.ndarray:
    y = np.asarray(state, dtype=float)
    phi = y[..., 0]
    theta = y[..., 1]
    phi_dot = y[..., 2]
    theta_dot = y[..., 3]
    radius = p.geometry.h + p.lower_length * np.cos(phi)
    slow = p.geometry.h + p.lower_length
    kinetic = 0.5 * p.bob_mass * (
        p.lower_length**2 * phi_dot**2 + radius**2 * theta_dot**2
    )
    potential = p.bob_mass * p.gravity_magnitude * (slow - radius * np.cos(theta))
    return kinetic + potential


def simulate_torus(cfg: SimulationConfig) -> TorusResult:
    p = TorusParameters.from_config(cfg)
    ic = cfg.initial_condition
    y0 = np.array(
        [
            float(to_si(ic.phi, default_unit="rad")),
            float(to_si(ic.theta, default_unit="rad")),
            float(to_si(ic.phi_dot, default_unit="rad/s")),
            float(to_si(ic.theta_dot, default_unit="rad/s")),
        ],
        dtype=float,
    )
    t_end = float(to_si(cfg.solver.t_end, default_unit="s"))
    output_dt = float(to_si(cfg.solver.output_dt, default_unit="s"))
    t_eval = np.arange(0.0, t_end + 0.5 * output_dt, output_dt)
    t_eval = t_eval[t_eval <= t_end + 1e-14]
    max_step = min(output_dt, 0.01)
    if cfg.solver.max_step != "auto":
        max_step = float(to_si(cfg.solver.max_step, default_unit="s"))

    initial_t = torus_tensions(y0, p)
    if np.min(initial_t) <= 0:
        raise ValueError(f"A1 initial state lies outside the all-taut regime: {initial_t}.")

    events: list[Callable[[float, np.ndarray], float]] = []
    for index in range(3):
        def event(_t: float, y: np.ndarray, idx: int = index) -> float:
            return float(torus_tensions(y, p)[idx])

        event.terminal = True  # type: ignore[attr-defined]
        event.direction = -1.0  # type: ignore[attr-defined]
        events.append(event)

    sol = solve_ivp(
        lambda t, y: torus_rhs(t, y, p),
        (0.0, t_end),
        y0,
        method="DOP853",
        t_eval=t_eval,
        rtol=1e-10,
        atol=1e-12,
        max_step=max_step,
        events=events,
    )
    if not sol.success:
        raise RuntimeError(f"A1 integration failed: {sol.message}")
    states = sol.y.T
    event_info = None
    names = ["upper_A_slack", "upper_B_slack", "lower_slack"]
    for name, times in zip(names, sol.t_events, strict=True):
        if times.size:
            event_info = {"type": name, "time": float(times[0])}
            break
    return TorusResult(
        time=sol.t,
        state=states,
        position=torus_coordinates(states, p),
        tensions=torus_tensions(states, p),
        energy=torus_energy(states, p),
        event=event_info,
    )

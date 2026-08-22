"""A0 analytic small-amplitude model."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from ypendulum.config.models import SimulationConfig
from ypendulum.config.units import as_vector3, to_si
from ypendulum.geometry import fixed_knot_upper_geometry


@dataclass(frozen=True)
class AnalyticPrediction:
    lower_length: float
    upper_drop: float
    slow_length: float
    omega_fast: float
    omega_slow: float
    frequency_ratio: float
    target_ratio: tuple[int, int]
    detuning: float
    drift_time: float
    nominal_close_time: float
    h_over_l: float


def predict_analytic(cfg: SimulationConfig) -> AnalyticPrediction:
    A = as_vector3(cfg.supports.A.position, default_unit="m")
    B = as_vector3(cfg.supports.B.position, default_unit="m")
    gvec = as_vector3(cfg.environment.gravity, default_unit="m/s^2")
    g = float(np.linalg.norm(gvec))
    la = float(to_si(cfg.cables.upper_A.rest_length, default_unit="m"))
    lb = float(to_si(cfg.cables.upper_B.rest_length, default_unit="m"))
    lower = float(to_si(cfg.cables.lower.rest_length, default_unit="m"))
    geom = fixed_knot_upper_geometry(A, B, la, lb, gvec)
    slow_length = lower + geom.h
    wf = math.sqrt(g / lower)
    ws = math.sqrt(g / slow_length)
    ratio = wf / ws
    p, q = cfg.analysis.target_ratio
    detuning = q * wf - p * ws
    drift = math.inf if abs(detuning) < 1e-15 else 2.0 * math.pi / abs(detuning)
    close = 2.0 * math.pi * p / wf
    return AnalyticPrediction(
        lower,
        geom.h,
        slow_length,
        wf,
        ws,
        ratio,
        (p, q),
        detuning,
        drift,
        close,
        geom.h / lower,
    )


def required_h_over_l(p: int, q: int) -> float:
    if p <= q or q <= 0:
        raise ValueError("A fixed-knot Y pendulum requires p/q > 1 for the fast:slow ratio.")
    return (p / q) ** 2 - 1.0

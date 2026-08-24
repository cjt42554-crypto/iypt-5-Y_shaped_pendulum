#!/usr/bin/env python3
"""Reproducible no-experiment parameter-to-pattern atlas for the Y-shaped pendulum.

Scope: ideal, symmetric, massless, inextensible, always-taut torus branch.
Run from this directory. Outputs are written to results/, figures/, and
MANIFEST.sha256. No experimental data are read or fitted.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["svg.fonttype"] = "none"
import matplotlib.pyplot as plt
import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq
from scipy.special import ellipk

SLOW_CYCLES = 18
AMPS = ((0.05, 0.04), (0.10, 0.08), (0.15, 0.10), (0.20, 0.12))
PHASE_TOL = 0.10
ELL_REF_M = 0.300
UPPER_SLOPE = 0.4

@dataclass(frozen=True)
class Target:
    p: int
    q: int

    @property
    def label(self) -> str:
        return f"{self.p}:{self.q}"

    @property
    def ratio(self) -> float:
        return self.p / self.q

    @property
    def eta0(self) -> float:
        return self.ratio**2 - 1.0

TARGETS = (Target(4, 3), Target(3, 2), Target(5, 3), Target(2, 1))

def rhs(_t: float, y: np.ndarray, eta: float) -> np.ndarray:
    phi, theta, u, v = y
    radius = eta + math.cos(phi)
    if radius <= 0:
        raise FloatingPointError("left positive-radius torus branch")
    return np.array((
        u,
        v,
        -radius * math.sin(phi) * v * v - math.sin(phi) * math.cos(theta),
        (2.0 * math.sin(phi) * u * v - math.sin(theta)) / radius,
    ))

def initial(eta: float, aphi: float, atheta: float,
            phase_phi: float = 0.0, phase_theta: float = 0.0) -> np.ndarray:
    wtheta = 1.0 / math.sqrt(1.0 + eta)
    return np.array((
        aphi * math.cos(phase_phi),
        atheta * math.cos(phase_theta),
        -aphi * math.sin(phase_phi),
        -atheta * wtheta * math.sin(phase_theta),
    ))

def integrate(eta: float, y0: np.ndarray, end: float, max_step: float,
              dense: bool = False, t_eval: np.ndarray | None = None):
    sol = solve_ivp(
        lambda t, y: rhs(t, y, eta), (0.0, end), y0, method="DOP853",
        rtol=3e-11, atol=3e-13, max_step=max_step,
        dense_output=dense, t_eval=t_eval,
    )
    if not sol.success:
        raise RuntimeError(sol.message)
    return sol

def fit_phase(t: np.ndarray, x: np.ndarray, v: np.ndarray, wref: float):
    phase = np.unwrap(np.arctan2(-v / wref, x))
    slope, intercept = np.polyfit(t, phase, 1)
    resid = phase - (slope * t + intercept)
    return phase, float(slope), float(np.sqrt(np.mean(resid * resid)))

def energy(states: np.ndarray, eta: float) -> np.ndarray:
    phi, theta, u, v = states.T
    radius = eta + np.cos(phi)
    return 0.5 * u*u + 0.5 * radius*radius * v*v + (1.0 + eta) - radius*np.cos(theta)

def guard_minima(states: np.ndarray, eta: float) -> dict[str, float]:
    phi, theta, u, v = states.T
    radius = eta + np.cos(phi)
    lower = u*u + radius*np.cos(phi)*v*v + np.cos(phi)*np.cos(theta)
    return {
        "R_over_ell": float(radius.min()),
        "T_A_sign_factor": float((np.sin(phi) + UPPER_SLOPE*np.cos(phi)).min()),
        "T_B_sign_factor": float((UPPER_SLOPE*np.cos(phi) - np.sin(phi)).min()),
        "T_lower_over_mg": float(lower.min()),
    }

def analyze(target: Target, eta: float, aphi: float, atheta: float,
            max_step: float = 0.16) -> dict[str, Any]:
    kappa = 1.0 + eta
    nominal_slow_period = 2.0 * math.pi * math.sqrt(kappa)
    end = (SLOW_CYCLES + 0.8) * nominal_slow_period
    sol = integrate(eta, initial(eta, aphi, atheta), end, max_step, dense=True)
    dt = min(0.025, nominal_slow_period / 600.0)
    t = np.arange(0.0, end, dt)
    if t[-1] < end:
        t = np.append(t, end)
    states = np.asarray(sol.sol(t)).T
    pphi, wphi, rms_phi = fit_phase(t, states[:, 0], states[:, 2], 1.0)
    ptheta, wtheta, rms_theta = fit_phase(
        t, states[:, 1], states[:, 3], 1.0 / math.sqrt(kappa))
    target_theta_phase = 2.0 * math.pi * SLOW_CYCLES
    if np.any(np.diff(ptheta) <= -1e-5) or ptheta[-1] <= target_theta_phase:
        raise RuntimeError("phase interpolation guard failed")
    close_t = float(np.interp(target_theta_phase, ptheta, t))
    close = np.asarray(sol.sol(close_t))
    phi_at_close = float(np.interp(close_t, t, pphi))
    psi = target.q * phi_at_close - target.p * target_theta_phase
    norm_terms = np.array((
        (close[0] - aphi) / aphi,
        close[2] / aphi,
        (close[1] - atheta) / atheta,
        close[3] / (atheta / math.sqrt(kappa)),
    ))
    e = energy(states, eta)
    drift = float(np.max(np.abs(e - e[0])) / max(abs(float(e[0])), 1e-12))
    guards = guard_minima(states, eta)
    if min(guards.values()) <= 0.0:
        raise AssertionError("trajectory left sampled taut branch")
    return {
        "target": target.label,
        "p": target.p,
        "q": target.q,
        "A_phi_rad": aphi,
        "A_theta_rad": atheta,
        "eta": eta,
        "omega_phi": wphi,
        "omega_theta": wtheta,
        "frequency_ratio": wphi / wtheta,
        "ratio_error": wphi / wtheta - target.ratio,
        "resonant_phase_error_rad": psi,
        "normalized_state_closure_error": float(np.linalg.norm(norm_terms)),
        "relative_energy_drift_max": drift,
        "phase_fit_rms_phi_rad": rms_phi,
        "phase_fit_rms_theta_rad": rms_theta,
        "closure_time_dimensionless": close_t,
        "minimum_guards": guards,
    }

def quartic_eta(target: Target, aphi: float, atheta: float) -> float:
    k = target.ratio**2
    return target.eta0 + (k/8.0 + 1.0/4.0)*aphi*aphi - 3.0*k*atheta*atheta/8.0

def measured_ratio(target: Target, eta: float, aphi: float, atheta: float) -> float:
    kappa = 1.0 + eta
    period = 2.0 * math.pi * math.sqrt(kappa)
    end = (SLOW_CYCLES + 0.8) * period
    t = np.linspace(0.0, end, int((SLOW_CYCLES + 0.8) * 180) + 1)
    sol = integrate(eta, initial(eta, aphi, atheta), end, 0.25, t_eval=t)
    states = sol.y.T
    _, wphi, _ = fit_phase(t, states[:, 0], states[:, 2], 1.0)
    _, wtheta, _ = fit_phase(t, states[:, 1], states[:, 3], 1.0 / math.sqrt(kappa))
    return wphi / wtheta

def tune_eta(target: Target, aphi: float, atheta: float) -> float:
    guess = quartic_eta(target, aphi, atheta)
    cache: dict[float, float] = {}

    def objective(eta: float) -> float:
        key = round(float(eta), 13)
        if key not in cache:
            cache[key] = measured_ratio(target, eta, aphi, atheta) - target.ratio
        return cache[key]

    half = 0.012
    floor = -math.cos(aphi) + 0.002
    left, right = max(guess-half, floor), guess+half
    for _ in range(9):
        if objective(left) * objective(right) <= 0.0:
            break
        half *= 1.7
        left, right = max(guess-half, floor), guess+half
    else:
        raise RuntimeError(f"could not bracket eta for {target.label}")
    return float(brentq(objective, left, right, xtol=3e-10, rtol=2e-11))

def pure_mode_period_check() -> list[dict[str, float | str]]:
    eta = 1.25
    rows = []
    for name, idx, scale in (("phi_fast", 0, 1.0), ("theta_slow", 1, 1.0+eta)):
        for amp in (0.05, 0.20):
            y0 = np.zeros(4)
            y0[idx] = amp

            def event(_t, y):
                return float(y[idx])

            event.direction = -1
            event.terminal = True
            sol = solve_ivp(
                lambda t, y: rhs(t, y, eta),
                (0, 3*math.pi*math.sqrt(scale)),
                y0,
                method="DOP853",
                rtol=1e-12,
                atol=1e-14,
                max_step=0.01,
                events=event,
            )
            numerical = 4.0 * float(sol.t_events[0][0])
            exact = 4.0 * math.sqrt(scale) * float(ellipk(math.sin(amp/2.0)**2))
            rel = (numerical-exact)/exact
            if abs(rel) > 5e-10:
                raise AssertionError("pure-mode check failed")
            rows.append({
                "coordinate": name,
                "amplitude_rad": amp,
                "period_exact": exact,
                "period_numeric": numerical,
                "relative_difference": rel,
            })
    return rows

def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

def plot_compensation(path: Path, rows: list[dict[str, Any]]) -> None:
    fig, axis = plt.subplots(figsize=(6.4, 5.2))
    for target in TARGETS:
        part = [row for row in rows if row["target"] == target.label]
        axis.scatter(
            [row["delta_eta_quartic"] for row in part],
            [row["delta_eta_numeric"] for row in part],
            label=target.label,
        )
    all_values = [row[key] for row in rows for key in ("delta_eta_quartic", "delta_eta_numeric")]
    low, high = min(all_values), max(all_values)
    pad = 0.08 * max(high-low, 1e-5)
    axis.plot([low-pad, high+pad], [low-pad, high+pad], "--", label="quartic = numerical")
    axis.set(
        xlabel="quartic Delta(h/ell)",
        ylabel="numerically tuned Delta(h/ell)",
        title="Finite-amplitude geometry compensation",
    )
    axis.grid(alpha=.25)
    axis.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)

def plot_phase_atlas(path: Path, eta: float) -> None:
    target = Target(3, 2)
    aphi, atheta = 0.10, 0.08
    end = 2.1 * target.q * 2*math.pi*math.sqrt(1+eta)
    phases = (0.0, math.pi/4, math.pi/2, 3*math.pi/4)
    fig, axes = plt.subplots(2, 2, figsize=(8.4, 8.0), sharex=True, sharey=True)
    for axis, psi0 in zip(axes.flat, phases):
        state0 = initial(eta, aphi, atheta, phase_phi=psi0/target.q)
        sol = integrate(eta, state0, end, 0.025, dense=True)
        states = np.asarray(sol.sol(np.linspace(0, end, 420))).T
        x = np.sin(states[:, 0])
        y = (eta + np.cos(states[:, 0])) * np.sin(states[:, 1])
        axis.plot(x, y, lw=1)
        axis.scatter([x[0]], [y[0]], s=18)
        axis.set_aspect("equal", adjustable="box")
        axis.grid(alpha=.2)
        axis.set_title(rf"$\Psi={psi0/math.pi:.2g}\pi$")
    fig.suptitle("Nonlinear 3:2 phase atlas")
    fig.tight_layout(rect=(0, 0, 1, .96))
    fig.savefig(path)
    plt.close(fig)

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()

def main(smoke: bool = False) -> None:
    root = Path(__file__).resolve().parent
    results = root / "results"
    figures = root / "figures"
    results.mkdir(exist_ok=True)
    figures.mkdir(exist_ok=True)

    pure = pure_mode_period_check()
    targets = TARGETS[:1] if smoke else TARGETS
    amps = AMPS[:1] if smoke else AMPS
    summary: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    tuned_map: dict[tuple[str, float, float], float] = {}

    for target in targets:
        for aphi, atheta in amps:
            eta0 = target.eta0
            eta4 = quartic_eta(target, aphi, atheta)
            etan = tune_eta(target, aphi, atheta)
            tuned_map[(target.label, aphi, atheta)] = etan
            c0, c4, cn = (
                analyze(target, eta, aphi, atheta)
                for eta in (eta0, eta4, etan)
            )
            cases.append({
                "target": target.label,
                "A_phi_rad": aphi,
                "A_theta_rad": atheta,
                "zero": c0,
                "quartic": c4,
                "numeric": cn,
            })
            summary.append({
                "target": target.label,
                "p": target.p,
                "q": target.q,
                "A_phi_rad": aphi,
                "A_theta_rad": atheta,
                "eta_zero": eta0,
                "eta_quartic": eta4,
                "eta_numeric": etan,
                "delta_eta_quartic": eta4-eta0,
                "delta_eta_numeric": etan-eta0,
                "quartic_minus_numeric_eta": eta4-etan,
                "phase_error_zero_rad": c0["resonant_phase_error_rad"],
                "phase_error_quartic_rad": c4["resonant_phase_error_rad"],
                "phase_error_numeric_rad": cn["resonant_phase_error_rad"],
                "closure_zero": c0["normalized_state_closure_error"],
                "closure_quartic": c4["normalized_state_closure_error"],
                "closure_numeric": cn["normalized_state_closure_error"],
                "energy_drift_numeric": cn["relative_energy_drift_max"],
                "minimum_guard_numeric": min(cn["minimum_guards"].values()),
            })

    write_csv(results / "atlas_summary.csv", summary)
    tolerances = []
    for target in targets:
        deta = PHASE_TOL * target.p / (math.pi * target.q**2 * SLOW_CYCLES)
        tolerances.append({
            "target": target.label,
            "p": target.p,
            "q": target.q,
            "slow_cycles": SLOW_CYCLES,
            "phase_tolerance_rad": PHASE_TOL,
            "delta_eta_tolerance": deta,
            "delta_h_tolerance_mm_at_ell_0p300m": deta * ELL_REF_M * 1000,
        })
    write_csv(results / "geometry_tolerance.csv", tolerances)

    validation: dict[str, Any] = {"pure_mode_period_checks": pure}
    if not smoke:
        step_checks = []
        for target in TARGETS:
            eta = tuned_map[(target.label, 0.20, 0.12)]
            coarse = next(
                case["numeric"] for case in cases
                if case["target"] == target.label and case["A_phi_rad"] == 0.20
            )
            fine = analyze(target, eta, 0.20, 0.12, max_step=0.08)
            step_checks.append({
                "target": target.label,
                "ratio_abs_difference": abs(coarse["frequency_ratio"]-fine["frequency_ratio"]),
                "phase_abs_difference_rad": abs(
                    coarse["resonant_phase_error_rad"]-fine["resonant_phase_error_rad"]),
                "closure_abs_difference": abs(
                    coarse["normalized_state_closure_error"]-
                    fine["normalized_state_closure_error"]),
            })
        validation["step_halving_checks"] = step_checks
        plot_compensation(figures / "compensation_accuracy.svg", summary)
        plot_phase_atlas(
            figures / "phase_atlas_3to2.svg",
            tuned_map[("3:2", 0.10, 0.08)],
        )

    payload = {
        "schema": "YPS-NO-EXPERIMENT-ATLAS-1.1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "ideal symmetric taut torus; no experimental data",
        "settings": {
            "targets": [target.label for target in targets],
            "amplitudes_rad": amps,
            "slow_cycles": SLOW_CYCLES,
        },
        "validation": validation,
        "cases": cases,
    }
    result_json = results / "atlas_results.json"
    with result_json.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    generated = [
        Path(__file__).resolve(),
        root / "README.md",
        results / "atlas_summary.csv",
        results / "geometry_tolerance.csv",
        result_json,
    ]
    if not smoke:
        generated += list(figures.glob("*.svg"))
    with (root / "MANIFEST.sha256").open("w", encoding="utf-8") as handle:
        for path in sorted(generated):
            if path.exists():
                handle.write(f"{sha256(path)}  {path.relative_to(root)}\n")

    print(json.dumps({
        "cases": len(summary),
        "smoke": smoke,
        "max_abs_phase_error_zero": max(
            abs(row["phase_error_zero_rad"]) for row in summary),
        "max_energy_drift_numeric": max(
            row["energy_drift_numeric"] for row in summary),
    }, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="run one target-amplitude case")
    main(parser.parse_args().smoke)

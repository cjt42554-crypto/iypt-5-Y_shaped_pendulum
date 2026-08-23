"""Time, mesh and cross-integrator convergence studies for H1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ypendulum.analysis.modes import linearised_modes
from ypendulum.config.models import SimulationConfig
from ypendulum.io.provenance import write_json
from ypendulum.models.full_cable import FullCableModel
from ypendulum.models.state import SimulationResult
from ypendulum.solvers.dynamic import simulate_full
from ypendulum.solvers.static import solve_static_equilibrium


@dataclass(frozen=True)
class PairMetrics:
    trajectory_normalized_rms: float
    maximum_position_difference_m: float
    low_frequency_relative_difference: float
    maximum_tension_relative_difference: float
    minimum_tension_relative_difference: float
    energy_residual_max_difference: float
    event_time_relative_difference: float | None
    retension_peak_relative_difference: float | None
    retension_impulse_relative_difference: float | None


def _bob_positions(result: SimulationResult) -> np.ndarray:
    # The topology contract deliberately stores the bob as the last node.
    return result.positions[:, -1]


def _first_structural_event(result: SimulationResult) -> float | None:
    times = [
        float(event["time"])
        for event in result.events
        if event.get("type") in {"cable_slack", "cable_retension", "upper_branch_switch"}
        and "time" in event
    ]
    return None if not times else min(times)



def _first_retension_metrics(result: SimulationResult) -> tuple[float, float] | None:
    events = [
        event
        for event in result.events
        if event.get("type") == "cable_retension"
        and "peak_tension_near_event" in event
        and "tension_impulse_window_Ns" in event
    ]
    if not events:
        return None
    event = min(events, key=lambda item: float(item.get("time", 0.0)))
    return float(event["peak_tension_near_event"]), float(event["tension_impulse_window_Ns"])

def compare_pair(
    reference: SimulationResult,
    candidate: SimulationResult,
    reference_frequencies: np.ndarray,
    candidate_frequencies: np.ndarray,
) -> PairMetrics:
    time = reference.time
    candidate_bob = np.column_stack(
        [
            np.interp(time, candidate.time, _bob_positions(candidate)[:, component])
            for component in range(3)
        ]
    )
    reference_bob = _bob_positions(reference)
    scale = max(
        float(np.sqrt(np.mean((reference_bob - np.mean(reference_bob, axis=0)) ** 2))),
        1.0e-12,
    )
    difference = candidate_bob - reference_bob
    trajectory = float(np.sqrt(np.mean(difference**2)) / scale)
    max_position = float(np.max(np.linalg.norm(difference, axis=1)))
    frequency = float(
        np.max(
            np.abs(np.asarray(candidate_frequencies) - np.asarray(reference_frequencies))
            / np.maximum(np.abs(reference_frequencies), 1.0e-15)
        )
    )
    max_tension = float(
        abs(float(np.max(candidate.tension)) - float(np.max(reference.tension)))
        / max(abs(float(np.max(reference.tension))), 1.0e-12)
    )
    reference_min = float(np.min(reference.tension))
    candidate_min = float(np.min(candidate.tension))
    minimum_scale = max(abs(reference_min), float(np.max(reference.tension)) * 1.0e-6, 1.0e-12)
    min_tension = float(abs(candidate_min - reference_min) / minimum_scale)
    energy = float(
        abs(
            float(np.max(np.abs(candidate.energy["balance_residual"])))
            - float(np.max(np.abs(reference.energy["balance_residual"])))
        )
    )
    tr = _first_structural_event(reference)
    tc = _first_structural_event(candidate)
    event_difference: float | None
    if tr is None and tc is None:
        event_difference = None
    elif tr is None or tc is None:
        event_difference = float("inf")
    else:
        period_scale = max(float(reference.time[-1] - reference.time[0]), abs(tr), 1.0e-12)
        event_difference = abs(tc - tr) / period_scale
    retension_reference = _first_retension_metrics(reference)
    retension_candidate = _first_retension_metrics(candidate)
    if retension_reference is None and retension_candidate is None:
        retension_peak_difference = None
        retension_impulse_difference = None
    elif retension_reference is None or retension_candidate is None:
        retension_peak_difference = float("inf")
        retension_impulse_difference = float("inf")
    else:
        retension_peak_difference = abs(retension_candidate[0] - retension_reference[0]) / max(
            abs(retension_reference[0]), 1.0e-12
        )
        retension_impulse_difference = abs(retension_candidate[1] - retension_reference[1]) / max(
            abs(retension_reference[1]), 1.0e-12
        )
    return PairMetrics(
        trajectory_normalized_rms=trajectory,
        maximum_position_difference_m=max_position,
        low_frequency_relative_difference=frequency,
        maximum_tension_relative_difference=max_tension,
        minimum_tension_relative_difference=min_tension,
        energy_residual_max_difference=energy,
        event_time_relative_difference=event_difference,
        retension_peak_relative_difference=retension_peak_difference,
        retension_impulse_relative_difference=retension_impulse_difference,
    )


def _run(cfg: SimulationConfig) -> tuple[FullCableModel, SimulationResult, np.ndarray]:
    model = FullCableModel(cfg)
    equilibrium = solve_static_equilibrium(cfg, model)
    frequencies = np.asarray(
        linearised_modes(model, equilibrium.positions, count=2)["frequency_hz"], dtype=float
    )
    result = simulate_full(cfg, model=model, equilibrium=equilibrium)
    return model, result, frequencies


def _spatial_pass(metrics: PairMetrics) -> bool:
    event_ok = metrics.event_time_relative_difference in {None} or (
        metrics.event_time_relative_difference is not None
        and metrics.event_time_relative_difference < 2.0e-3
    )
    retension_ok = (
        metrics.retension_peak_relative_difference is None
        or (
            metrics.retension_peak_relative_difference < 2.0e-2
            and metrics.retension_impulse_relative_difference is not None
            and metrics.retension_impulse_relative_difference < 2.0e-2
        )
    )
    return bool(
        metrics.low_frequency_relative_difference < 1.0e-4
        and metrics.trajectory_normalized_rms < 2.0e-3
        and metrics.maximum_tension_relative_difference < 1.0e-2
        and metrics.energy_residual_max_difference < 1.0e-4
        and event_ok
        and retension_ok
    )


def _time_pass(metrics: PairMetrics) -> bool:
    event_ok = metrics.event_time_relative_difference in {None} or (
        metrics.event_time_relative_difference is not None
        and metrics.event_time_relative_difference < 1.0e-3
    )
    retension_ok = (
        metrics.retension_peak_relative_difference is None
        or (
            metrics.retension_peak_relative_difference < 2.0e-2
            and metrics.retension_impulse_relative_difference is not None
            and metrics.retension_impulse_relative_difference < 2.0e-2
        )
    )
    return bool(
        metrics.low_frequency_relative_difference < 1.0e-4
        and metrics.trajectory_normalized_rms < 1.0e-3
        and metrics.energy_residual_max_difference < 1.0e-4
        and event_ok
        and retension_ok
    )


def run_convergence_matrix(
    cfg: SimulationConfig,
    *,
    include_time: bool = True,
    include_cross_solver: bool = True,
    output_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Run the frozen N/2N, production/reference and Radau/BDF checks."""

    coarse = cfg.model_copy(deep=True)
    fine = cfg.model_copy(deep=True)
    fine.run.name = f"{coarse.run.name}_2N"
    for name in ("upper_A", "upper_B", "lower"):
        getattr(fine.cables, name).elements *= 2

    _mc, rc, fc = _run(coarse)
    _mf, rf, ff = _run(fine)
    spatial_metrics = compare_pair(rf, rc, ff, fc)
    report: dict[str, Any] = {
        "spatial": {
            "passed": _spatial_pass(spatial_metrics),
            "coarse_elements": int(rc.tension.shape[1]),
            "fine_elements": int(rf.tension.shape[1]),
            "metrics": asdict(spatial_metrics),
        }
    }

    if include_time:
        production = cfg.model_copy(deep=True)
        reference = cfg.model_copy(deep=True)
        production.solver.profile = "production"
        reference.solver.profile = "reference"
        production.solver.method = "Radau"
        reference.solver.method = "Radau"
        _mp, rp, fp = _run(production)
        _mr, rr, fr = _run(reference)
        time_metrics = compare_pair(rr, rp, fr, fp)
        report["time"] = {"passed": _time_pass(time_metrics), "metrics": asdict(time_metrics)}

    if include_cross_solver:
        radau = cfg.model_copy(deep=True)
        bdf = cfg.model_copy(deep=True)
        radau.solver.profile = "production"
        bdf.solver.profile = "production"
        radau.solver.method = "Radau"
        bdf.solver.method = "BDF"
        _mrad, rrad, frad = _run(radau)
        _mbdf, rbdf, fbdf = _run(bdf)
        solver_metrics = compare_pair(rrad, rbdf, frad, fbdf)
        report["cross_solver"] = {
            "passed": _time_pass(solver_metrics),
            "metrics": asdict(solver_metrics),
        }

    report["passed"] = bool(all(section["passed"] for section in report.values() if isinstance(section, dict) and "passed" in section))

    if output_directory is not None:
        out = Path(output_directory)
        out.mkdir(parents=True, exist_ok=True)
        write_json(out / "convergence_report.json", report)
        lines = [
            "# YP-FPSim 收敛与跨求解器报告",
            "",
            f"- 总体：`{'PASS' if report['passed'] else 'FAIL'}`",
            "",
            "| 检查 | 状态 | 轨迹 RMS | 低频差 | 最大张力差 | 能量残差差 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for name in ("spatial", "time", "cross_solver"):
            if name not in report:
                continue
            section = report[name]
            metrics = section["metrics"]
            lines.append(
                f"| {name} | {'PASS' if section['passed'] else 'FAIL'} | "
                f"{metrics['trajectory_normalized_rms']:.6g} | "
                f"{metrics['low_frequency_relative_difference']:.6g} | "
                f"{metrics['maximum_tension_relative_difference']:.6g} | "
                f"{metrics['energy_residual_max_difference']:.6g} |"
            )
        lines += [
            "",
            "该矩阵检查数值收敛和求解器一致性；没有实验数据时，不构成实验验证。",
        ]
        (out / "convergence_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report

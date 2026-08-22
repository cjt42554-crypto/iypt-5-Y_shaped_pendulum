#!/usr/bin/env python3
"""Run the minimum representative HF time-step and mesh sensitivity study.

This is a personal-research utility, not the formal six-candidate qualification
matrix.  It prepares the finest held state once, forks two independent time
integrations from that identical state, and concurrently prepares/runs one
coarser mesh.  Raw differences are reported without post-result threshold
tuning.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import queue
import sys
import traceback
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from ypendulum.config import (
    SimulationConfig,
    load_config,
    resolved_config_sha256,
    validate_physical_config,
)
from ypendulum.config.units import to_si
from ypendulum.hf.model import HighFidelityModel
from ypendulum.hf.solver import (
    PreparationResult,
    prepare_initial_state,
    simulate_high_fidelity,
)
from ypendulum.hf.state import HighFidelityResult
from ypendulum.io.provenance import source_hash

_BRANCHES = ("upper_A", "upper_B", "lower")


def _quantity(value: float, unit: str) -> dict[str, Any]:
    return {"value": float(value), "unit": unit}


def _candidate(
    base: SimulationConfig,
    *,
    label: str,
    window_s: float,
    output_dt_s: float,
    max_step_s: float,
    elements: tuple[int, int, int] | None = None,
) -> SimulationConfig:
    cfg = base.model_copy(deep=True)
    cfg.run.name = f"representative_{label}"
    cfg.solver.t_end = _quantity(window_s, "s")
    cfg.solver.output_dt = _quantity(output_dt_s, "s")
    cfg.solver.max_step = _quantity(max_step_s, "s")
    if elements is not None:
        cfg.cables.upper_A.elements = int(elements[0])
        cfg.cables.upper_B.elements = int(elements[1])
        cfg.cables.lower.elements = int(elements[2])
    validate_physical_config(cfg)
    return cfg


def _preparation_summary(preparation: PreparationResult) -> dict[str, Any]:
    audit = preparation.audit
    return {
        "mode": preparation.preparation_mode,
        "residual_inf_N": float(preparation.residual_inf_N),
        "iterations": int(preparation.iterations),
        "bob_held": bool(preparation.bob_held),
        "selected_seed": audit.get("selected_seed"),
        "selected_hessian_min_eigenvalue_N_m": audit.get("selected_hessian_min_eigenvalue_N_m"),
        "hessian_workers": audit.get("hessian_workers"),
    }


def _worker(
    label: str,
    cfg: SimulationConfig,
    inherited_model: HighFidelityModel | None,
    inherited_preparation: PreparationResult | None,
    output: Any,
) -> None:
    """Run one independent candidate and return it through a process queue."""

    started = perf_counter()
    try:
        model = inherited_model
        preparation = inherited_preparation
        preparation_wall = 0.0
        if model is None or preparation is None:
            model = HighFidelityModel(cfg)
            prep_started = perf_counter()
            preparation = prepare_initial_state(cfg, model)
            preparation_wall = perf_counter() - prep_started
        integration_started = perf_counter()
        result = simulate_high_fidelity(
            cfg,
            model=model,
            preparation=preparation,
        )
        integration_wall = perf_counter() - integration_started
        output.put(
            {
                "label": label,
                "ok": True,
                "result": result,
                "preparation": _preparation_summary(preparation),
                "preparation_wall_seconds": preparation_wall,
                "integration_wall_seconds": integration_wall,
                "worker_wall_seconds": perf_counter() - started,
            }
        )
    except BaseException as exc:  # fail closed and preserve the other members
        output.put(
            {
                "label": label,
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "worker_wall_seconds": perf_counter() - started,
            }
        )


def _rms_max(prefix: str, difference: np.ndarray) -> dict[str, float]:
    values = np.asarray(difference, dtype=float)
    return {
        f"rms_{prefix}": float(np.sqrt(np.mean(values * values))),
        f"max_{prefix}": float(np.max(np.abs(values))),
    }


def _rest_lengths(cfg: SimulationConfig, branch: str) -> np.ndarray:
    branch_cfg = getattr(cfg.cables, branch)
    length = float(to_si(branch_cfg.rest_length, default_unit="m"))
    elements = int(branch_cfg.elements)
    values = np.full(elements + 1, length / elements, dtype=float)
    values[0] = length / (2.0 * elements)
    values[-1] = length / (2.0 * elements)
    return values


def _material_path(
    values: np.ndarray,
    rest_lengths: np.ndarray,
    common_s: np.ndarray,
) -> np.ndarray:
    source_s = np.concatenate([[0.0], np.cumsum(rest_lengths)])
    source_s /= source_s[-1]
    if source_s.size != values.shape[1]:
        raise ValueError("Material path and rest-length topology disagree.")
    out = np.empty((values.shape[0], common_s.size, values.shape[2]))
    for index in range(values.shape[0]):
        for component in range(values.shape[2]):
            out[index, :, component] = np.interp(
                common_s,
                source_s,
                values[index, :, component],
            )
    return out


def _segment_field(
    values: np.ndarray,
    rest_lengths: np.ndarray,
    common_s: np.ndarray,
) -> np.ndarray:
    edges = np.concatenate([[0.0], np.cumsum(rest_lengths)])
    edges /= edges[-1]
    cell = np.searchsorted(edges, common_s, side="right") - 1
    cell = np.clip(cell, 0, values.shape[1] - 1)
    return np.asarray(values)[:, cell]


def _normalized_guards(
    result: HighFidelityResult,
) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    metadata = result.diagnostics["guard_component_metadata"]
    normalized: dict[str, np.ndarray] = {}
    minima: dict[str, float] = {}
    if set(metadata) != set(result.guard_margins):
        raise ValueError("Guard metadata and series vocabularies differ.")
    for name, values in result.guard_margins.items():
        scale = float(metadata[name]["scale"])
        if not np.isfinite(scale) or scale <= 0.0:
            raise ValueError(f"Invalid guard scale for {name}: {scale}")
        series = np.asarray(values, dtype=float) / scale
        normalized[name] = series
        minima[name] = float(np.min(series))
    return normalized, minima


def _compare(
    left_cfg: SimulationConfig,
    left: HighFidelityResult,
    right_cfg: SimulationConfig,
    right: HighFidelityResult,
    *,
    material_points: int,
) -> dict[str, Any]:
    if not np.array_equal(left.time, right.time):
        raise ValueError("Representative candidates must share an exact output grid.")
    metrics: dict[str, float] = {}
    metrics.update(_rms_max("bob_position_m", left.bob_position - right.bob_position))
    metrics.update(_rms_max("bob_velocity_m_s", left.bob_velocity - right.bob_velocity))
    metrics.update(
        _rms_max(
            "junction_position_m",
            left.junction_position - right.junction_position,
        )
    )
    metrics.update(
        _rms_max(
            "junction_velocity_m_s",
            left.junction_velocity - right.junction_velocity,
        )
    )
    metrics.update(
        _rms_max(
            "bob_attachment_position_m",
            left.bob_attachment_position - right.bob_attachment_position,
        )
    )
    quaternion_dot = np.abs(np.sum(left.bob_quaternion * right.bob_quaternion, axis=1))
    orientation_angle = 2.0 * np.arccos(np.clip(quaternion_dot, 0.0, 1.0))
    metrics.update(_rms_max("bob_orientation_angle_rad", orientation_angle))
    metrics.update(
        _rms_max(
            "bob_angular_velocity_rad_s",
            left.bob_angular_velocity - right.bob_angular_velocity,
        )
    )

    common_s = np.linspace(0.0, 1.0, material_points)
    position_difference: list[np.ndarray] = []
    velocity_difference: list[np.ndarray] = []
    tension_difference: list[np.ndarray] = []
    signed_difference: list[np.ndarray] = []
    for branch in _BRANCHES:
        left_rest = _rest_lengths(left_cfg, branch)
        right_rest = _rest_lengths(right_cfg, branch)
        position_difference.append(
            _material_path(left.cable_positions[branch], left_rest, common_s)
            - _material_path(right.cable_positions[branch], right_rest, common_s)
        )
        velocity_difference.append(
            _material_path(left.cable_velocities[branch], left_rest, common_s)
            - _material_path(right.cable_velocities[branch], right_rest, common_s)
        )
        tension_difference.append(
            _segment_field(left.cable_tension[branch], left_rest, common_s)
            - _segment_field(right.cable_tension[branch], right_rest, common_s)
        )
        signed_difference.append(
            _segment_field(left.cable_axial_force[branch], left_rest, common_s)
            - _segment_field(right.cable_axial_force[branch], right_rest, common_s)
        )
    metrics.update(
        _rms_max(
            "rod_position_m",
            np.concatenate(position_difference, axis=1),
        )
    )
    metrics.update(
        _rms_max(
            "rod_velocity_m_s",
            np.concatenate(velocity_difference, axis=1),
        )
    )
    metrics.update(
        _rms_max(
            "rod_tension_N",
            np.concatenate(tension_difference, axis=1),
        )
    )
    metrics.update(
        _rms_max(
            "rod_signed_axial_force_N",
            np.concatenate(signed_difference, axis=1),
        )
    )
    metrics.update(
        _rms_max(
            "mechanical_energy_J",
            left.energy["mechanical"] - right.energy["mechanical"],
        )
    )
    metrics.update(
        _rms_max(
            "support_reaction_N",
            np.concatenate(
                [
                    left.reactions["support_A"] - right.reactions["support_A"],
                    left.reactions["support_B"] - right.reactions["support_B"],
                ],
                axis=1,
            ),
        )
    )

    left_guards, left_minima = _normalized_guards(left)
    right_guards, right_minima = _normalized_guards(right)
    if set(left_guards) != set(right_guards):
        raise ValueError("Compared candidates have different guard vocabularies.")
    per_guard = {}
    all_guard_difference = []
    for name in sorted(left_guards):
        difference = left_guards[name] - right_guards[name]
        all_guard_difference.append(difference)
        per_guard[name] = {
            "left_minimum_normalized": left_minima[name],
            "right_minimum_normalized": right_minima[name],
            **_rms_max("normalized_difference", difference),
        }
    metrics.update(
        _rms_max(
            "normalized_guard_margin",
            np.concatenate(all_guard_difference),
        )
    )
    return {
        "metrics": metrics,
        "per_guard": per_guard,
        "left_minimum_normalized_guard": min(left_minima.values()),
        "right_minimum_normalized_guard": min(right_minima.values()),
    }


def _finite_result(result: HighFidelityResult) -> bool:
    arrays: list[np.ndarray] = [
        result.time,
        result.integration_time,
        result.particle_positions,
        result.particle_velocities,
        result.bob_position,
        result.bob_velocity,
        result.bob_quaternion,
        result.bob_angular_velocity,
        result.junction_position,
        result.junction_velocity,
    ]
    arrays.extend(result.cable_positions.values())
    arrays.extend(result.cable_velocities.values())
    arrays.extend(result.cable_axial_force.values())
    arrays.extend(result.cable_tension.values())
    arrays.extend(result.energy.values())
    arrays.extend(result.reactions.values())
    arrays.extend(result.guard_margins.values())
    return all(bool(np.all(np.isfinite(np.asarray(values)))) for values in arrays)


def _result_summary(
    label: str,
    cfg: SimulationConfig,
    result: HighFidelityResult,
    worker: dict[str, Any],
) -> dict[str, Any]:
    _, guard_minima = _normalized_guards(result)
    signed = np.concatenate(list(result.cable_axial_force.values()), axis=1)
    tension = np.concatenate(list(result.cable_tension.values()), axis=1)
    return {
        "label": label,
        "config_sha256": resolved_config_sha256(cfg),
        "mesh": {branch: int(getattr(cfg.cables, branch).elements) for branch in _BRANCHES},
        "t_end_s": float(to_si(cfg.solver.t_end, default_unit="s")),
        "output_dt_s": float(to_si(cfg.solver.output_dt, default_unit="s")),
        "max_step_s": float(to_si(cfg.solver.max_step, default_unit="s")),
        "physical_status": result.physical_status,
        "numerical_status": result.numerical_status,
        "valid_interval_s": [float(item) for item in result.valid_interval],
        "output_sample_count": int(result.time.size),
        "accepted_time_count": int(result.integration_time.size),
        "all_scientific_arrays_finite": _finite_result(result),
        "minimum_normalized_guard_margin": min(guard_minima.values()),
        "minimum_normalized_guard_by_component": guard_minima,
        "minimum_signed_axial_force_N": float(np.min(signed)),
        "maximum_signed_axial_force_N": float(np.max(signed)),
        "minimum_tension_N": float(np.min(tension)),
        "maximum_tension_N": float(np.max(tension)),
        "maximum_abs_energy_balance_residual": float(
            np.max(np.abs(result.energy["balance_residual"]))
        ),
        "minimum_axial_dissipation_rate_W": float(np.min(result.energy["axial_dissipation_rate"])),
        "minimum_aero_dissipation_rate_W": float(np.min(result.energy["aero_dissipation_rate"])),
        "maximum_quaternion_norm_error": float(result.diagnostics["maximum_quaternion_norm_error"]),
        "event_count": len(result.events),
        "solver_runtime_seconds": float(result.diagnostics["runtime_seconds"]),
        "worker_integration_wall_seconds": float(worker["integration_wall_seconds"]),
        "worker_preparation_wall_seconds": float(worker["preparation_wall_seconds"]),
        "worker_wall_seconds": float(worker["worker_wall_seconds"]),
        "preparation": worker["preparation"],
    }


def _series_payload(
    results: dict[str, HighFidelityResult],
) -> dict[str, np.ndarray]:
    payload: dict[str, np.ndarray] = {}
    for label, result in results.items():
        prefix = label + "__"
        signed = np.concatenate(list(result.cable_axial_force.values()), axis=1)
        tension = np.concatenate(list(result.cable_tension.values()), axis=1)
        normalized_guards, _ = _normalized_guards(result)
        guard_stack = np.column_stack(
            [normalized_guards[name] for name in sorted(normalized_guards)]
        )
        payload[prefix + "time_s"] = result.time
        payload[prefix + "bob_position_m"] = result.bob_position
        payload[prefix + "bob_velocity_m_s"] = result.bob_velocity
        payload[prefix + "junction_position_m"] = result.junction_position
        payload[prefix + "junction_velocity_m_s"] = result.junction_velocity
        payload[prefix + "mechanical_energy_J"] = result.energy["mechanical"]
        payload[prefix + "signed_axial_force_min_N"] = np.min(signed, axis=1)
        payload[prefix + "signed_axial_force_max_N"] = np.max(signed, axis=1)
        payload[prefix + "tension_max_N"] = np.max(tension, axis=1)
        payload[prefix + "normalized_guard_min"] = np.min(guard_stack, axis=1)
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/examples/high_fidelity_shared_forward_window.yaml"),
    )
    parser.add_argument("--window-s", type=float, default=0.01)
    parser.add_argument("--material-points", type=int, default=129)
    parser.add_argument(
        "--coarse-mesh",
        type=int,
        nargs=3,
        metavar=("UPPER_A", "UPPER_B", "LOWER"),
        default=(20, 20, 30),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("validation/representative_hf_sensitivity.json"),
    )
    parser.add_argument(
        "--series-output",
        type=Path,
        default=Path("validation/representative_hf_sensitivity_series.npz"),
    )
    parser.add_argument("--worker-timeout-s", type=float, default=7200.0)
    args = parser.parse_args()

    if os.name != "posix" or "fork" not in mp.get_all_start_methods():
        raise RuntimeError("This CPU-parallel research utility requires POSIX fork.")
    if not np.isfinite(args.window_s) or args.window_s <= 0.0:
        raise ValueError("--window-s must be finite and positive.")
    if args.material_points < 3:
        raise ValueError("--material-points must be at least three.")

    started = perf_counter()
    config_path = args.config.expanduser().resolve()
    base = load_config(config_path)
    fine_step = float(to_si(base.solver.max_step, default_unit="s"))
    output_dt = float(to_si(base.solver.output_dt, default_unit="s"))
    if output_dt > fine_step:
        raise ValueError("The production output_dt must not exceed max_step.")

    fine_cfg = _candidate(
        base,
        label="fine",
        window_s=args.window_s,
        output_dt_s=output_dt,
        max_step_s=fine_step,
    )
    time_coarse_cfg = _candidate(
        base,
        label="time_2h",
        window_s=args.window_s,
        output_dt_s=output_dt,
        max_step_s=2.0 * fine_step,
    )
    space_coarse_cfg = _candidate(
        base,
        label="mesh_coarse",
        window_s=args.window_s,
        output_dt_s=output_dt,
        max_step_s=fine_step,
        elements=tuple(args.coarse_mesh),
    )
    configs = {
        "fine": fine_cfg,
        "time_2h": time_coarse_cfg,
        "mesh_coarse": space_coarse_cfg,
    }

    source_root = Path(__file__).resolve().parents[1] / "src" / "ypendulum"
    source_start = source_hash(source_root)
    fine_model = HighFidelityModel(fine_cfg)
    preparation_started = perf_counter()
    fine_preparation = prepare_initial_state(fine_cfg, fine_model)
    shared_preparation_wall = perf_counter() - preparation_started

    context = mp.get_context("fork")
    output_queue = context.Queue(maxsize=3)
    processes = [
        context.Process(
            name="yps-hf-fine",
            target=_worker,
            args=("fine", fine_cfg, fine_model, fine_preparation, output_queue),
        ),
        context.Process(
            name="yps-hf-time-2h",
            target=_worker,
            args=(
                "time_2h",
                time_coarse_cfg,
                fine_model,
                fine_preparation,
                output_queue,
            ),
        ),
        context.Process(
            name="yps-hf-mesh-coarse",
            target=_worker,
            args=("mesh_coarse", space_coarse_cfg, None, None, output_queue),
        ),
    ]
    for process in processes:
        process.start()

    records: dict[str, dict[str, Any]] = {}
    try:
        for _ in processes:
            record = output_queue.get(timeout=args.worker_timeout_s)
            records[str(record["label"])] = record
    except queue.Empty as exc:
        for process in processes:
            if process.is_alive():
                process.terminate()
        raise TimeoutError("Representative HF sensitivity worker timed out.") from exc
    finally:
        for process in processes:
            process.join(timeout=30.0)

    failed = {label: record for label, record in records.items() if not bool(record.get("ok"))}
    abnormal_exit = {
        process.name: process.exitcode for process in processes if process.exitcode not in (0, None)
    }
    if failed or abnormal_exit or set(records) != set(configs):
        failure = {
            "failed_workers": failed,
            "abnormal_exit_codes": abnormal_exit,
            "received_labels": sorted(records),
        }
        print(json.dumps(failure, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2

    results = {label: records[label]["result"] for label in configs}
    expected_pair = (
        "UNDETERMINED",
        "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED",
    )
    incomplete = {
        label: (
            result.physical_status,
            result.numerical_status,
            result.valid_interval,
        )
        for label, result in results.items()
        if (
            result.physical_status,
            result.numerical_status,
        )
        != expected_pair
        or result.valid_interval != (0.0, args.window_s)
    }
    if incomplete:
        print(
            json.dumps(
                {"candidate_did_not_cover_representative_window": incomplete},
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            file=sys.stderr,
        )
        return 3

    time_comparison = _compare(
        fine_cfg,
        results["fine"],
        time_coarse_cfg,
        results["time_2h"],
        material_points=args.material_points,
    )
    space_comparison = _compare(
        fine_cfg,
        results["fine"],
        space_coarse_cfg,
        results["mesh_coarse"],
        material_points=args.material_points,
    )

    args.series_output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.series_output, **_series_payload(results))
    source_end = source_hash(source_root)
    report = {
        "schema_version": "YPS-HF-REPRESENTATIVE-SENSITIVITY-1.0",
        "scope": (
            "personal_research_representative_short_window_not_formal_six_candidate_qualification"
        ),
        "model_id": results["fine"].model_id,
        "source_hash_start_sha256": source_start,
        "source_hash_end_sha256": source_end,
        "source_stable_during_study": source_start == source_end,
        "base_config_path": str(config_path),
        "base_config_file_sha256": _sha256_file(config_path),
        "base_config_resolved_sha256": resolved_config_sha256(base),
        "representative_window_s": float(args.window_s),
        "material_comparison_points": int(args.material_points),
        "parallel_execution": {
            "method": "POSIX_fork_three_independent_processes",
            "shared_fine_preparation": True,
            "shared_fine_preparation_wall_seconds": shared_preparation_wall,
            "blas_threads_per_worker": {
                "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS"),
                "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS"),
            },
        },
        "runs": {
            label: _result_summary(
                label,
                configs[label],
                results[label],
                records[label],
            )
            for label in configs
        },
        "time_step_comparison": {
            "definition": "same_24_24_32_mesh_same_preparation_h_vs_2h",
            "left": "fine",
            "right": "time_2h",
            **time_comparison,
        },
        "mesh_comparison": {
            "definition": "same_window_24_24_32_vs_20_20_30",
            "left": "fine",
            "right": "mesh_coarse",
            **space_comparison,
        },
        "series_npz_path": str(args.series_output.resolve()),
        "series_npz_sha256": _sha256_file(args.series_output),
        "study_wall_seconds": perf_counter() - started,
        "interpretation": {
            "raw_metrics_are_primary": True,
            "thresholds_relaxed_after_results": False,
            "formal_full_window_qualification_claimed": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "REPRESENTATIVE_SENSITIVITY_COMPLETED",
                "output": str(args.output.resolve()),
                "output_sha256": _sha256_file(args.output),
                "series_output": str(args.series_output.resolve()),
                "source_stable": source_start == source_end,
                "wall_seconds": report["study_wall_seconds"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

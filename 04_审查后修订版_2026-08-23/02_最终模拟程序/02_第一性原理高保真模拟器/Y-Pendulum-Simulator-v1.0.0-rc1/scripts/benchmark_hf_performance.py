#!/usr/bin/env python3
"""Benchmark and compare the HF integration/presentation pipeline.

This utility is intentionally aimed at the personal research workflow.  It
reuses the held initial state from a completed HF result, shortens only the
time window in memory, and records enough canonical arrays to compare a
pre-optimization run with a post-optimization run.  The physical model and
the production configuration file are never rewritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import subprocess
import time
from pathlib import Path
from typing import Any

import h5py
import numpy as np
from scipy.integrate import cumulative_trapezoid

from ypendulum.config import (
    load_config,
    resolved_config_sha256,
    validate_physical_config,
)
from ypendulum.hf.model import HighFidelityModel
from ypendulum.hf.solver import (
    PreparationResult,
    _presentation_samples,
    _sampled_axial_events,
    simulate_high_fidelity,
)
from ypendulum.io.provenance import source_hash

_BRANCHES = ("upper_A", "upper_B", "lower")


def _quantity(value: float, unit: str) -> dict[str, Any]:
    return {"value": float(value), "unit": unit}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cpu_seconds() -> float:
    self_usage = resource.getrusage(resource.RUSAGE_SELF)
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(
        self_usage.ru_utime
        + self_usage.ru_stime
        + child_usage.ru_utime
        + child_usage.ru_stime
    )


def _process_tree(root: int) -> set[int]:
    pending = [root]
    found: set[int] = set()
    while pending:
        pid = pending.pop()
        if pid in found:
            continue
        found.add(pid)
        children_path = Path(f"/proc/{pid}/task/{pid}/children")
        try:
            pending.extend(int(item) for item in children_path.read_text().split())
        except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError):
            continue
    return found


def _rss_bytes(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError):
        pass
    return 0


def _gpu_sample() -> tuple[float, float] | None:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        first = completed.stdout.strip().splitlines()[0]
        utilization, memory_mib = (float(item.strip()) for item in first.split(","))
        return utilization, memory_mib
    except (FileNotFoundError, IndexError, subprocess.SubprocessError, ValueError):
        return None


class _ResourceMonitor:
    def __init__(self, interval_s: float = 5.0) -> None:
        self.interval_s = interval_s
        self.peak_tree_rss_bytes = 0
        self.gpu_utilization_percent: list[float] = []
        self.gpu_memory_mib: list[float] = []

    def __enter__(self) -> _ResourceMonitor:
        self.peak_tree_rss_bytes = sum(
            _rss_bytes(pid) for pid in _process_tree(os.getpid())
        )
        gpu = _gpu_sample()
        if gpu is not None:
            self.gpu_utilization_percent.append(gpu[0])
            self.gpu_memory_mib.append(gpu[1])
        return self

    def __exit__(self, *_: object) -> None:
        # Do not keep a monitoring thread alive while the solver forks its
        # deterministic post-process workers.  GNU time supplies the external
        # peak-RSS cross-check; these two samples record the process-local view.
        self.peak_tree_rss_bytes = max(
            self.peak_tree_rss_bytes,
            sum(_rss_bytes(pid) for pid in _process_tree(os.getpid())),
        )
        self.peak_tree_rss_bytes = max(
            self.peak_tree_rss_bytes,
            int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
            int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss) * 1024,
        )
        gpu = _gpu_sample()
        if gpu is not None:
            self.gpu_utilization_percent.append(gpu[0])
            self.gpu_memory_mib.append(gpu[1])


def _initial_preparation(
    model: HighFidelityModel,
    result_path: Path,
) -> PreparationResult:
    with h5py.File(result_path, "r") as handle:
        particles = np.asarray(
            handle["numerical_certificate/material_particles/position"][0],
            dtype=float,
        )
        velocities = np.asarray(
            handle["numerical_certificate/material_particles/velocity"][0],
            dtype=float,
        )
        bob = np.asarray(handle["numerical_certificate/bob/com_position"][0], dtype=float)
        bob_velocity = np.asarray(
            handle["numerical_certificate/bob/com_velocity"][0], dtype=float
        )
        quaternion = np.asarray(
            handle["numerical_certificate/bob/quaternion_body_to_world"][0],
            dtype=float,
        )
        angular_velocity = np.asarray(
            handle["numerical_certificate/bob/angular_velocity_world"][0],
            dtype=float,
        )
    state = model.pack_state(
        particles,
        bob,
        quaternion,
        velocities,
        bob_velocity,
        angular_velocity,
    )
    return PreparationResult(
        state=state,
        residual_inf_N=float("nan"),
        iterations=0,
        bob_held=True,
        preparation_mode="reused_completed_target_initial_state",
        audit={
            "source_result_h5": str(result_path.resolve()),
            "source_result_sha256": _sha256(result_path),
        },
    )


def _result_arrays(result: Any) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {
        "time": np.asarray(result.time),
        "integration_time": np.asarray(result.integration_time),
        "integration_particle_positions": np.asarray(result.integration_particle_positions),
        "integration_particle_velocities": np.asarray(result.integration_particle_velocities),
        "integration_bob_position": np.asarray(result.integration_bob_position),
        "integration_bob_velocity": np.asarray(result.integration_bob_velocity),
        "integration_bob_quaternion": np.asarray(result.integration_bob_quaternion),
        "integration_bob_angular_velocity": np.asarray(
            result.integration_bob_angular_velocity
        ),
        "particle_positions": np.asarray(result.particle_positions),
        "particle_velocities": np.asarray(result.particle_velocities),
        "junction_position": np.asarray(result.junction_position),
        "junction_velocity": np.asarray(result.junction_velocity),
        "bob_position": np.asarray(result.bob_position),
        "bob_velocity": np.asarray(result.bob_velocity),
        "bob_quaternion": np.asarray(result.bob_quaternion),
        "bob_angular_velocity": np.asarray(result.bob_angular_velocity),
        "bob_attachment_position": np.asarray(result.bob_attachment_position),
    }
    for branch in _BRANCHES:
        arrays[f"cable_positions__{branch}"] = np.asarray(result.cable_positions[branch])
        arrays[f"cable_velocities__{branch}"] = np.asarray(result.cable_velocities[branch])
        arrays[f"signed_axial_force__{branch}"] = np.asarray(
            result.cable_axial_force[branch]
        )
        arrays[f"tension__{branch}"] = np.asarray(result.cable_tension[branch])
    for name, values in sorted(result.energy.items()):
        arrays[f"energy__{name}"] = np.asarray(values)
    for name, values in sorted(result.guard_margins.items()):
        arrays[f"guard__{name}"] = np.asarray(values)
    for name, values in sorted(result.reactions.items()):
        arrays[f"reaction__{name}"] = np.asarray(values)
    return arrays


def _canonical_events(events: list[dict[str, Any]]) -> str:
    return json.dumps(events, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _array_error(
    candidate: np.ndarray,
    reference: np.ndarray,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> dict[str, Any]:
    left = np.asarray(candidate)
    right = np.asarray(reference)
    if left.shape != right.shape:
        return {
            "passed": False,
            "shape_equal": False,
            "candidate_shape": list(left.shape),
            "reference_shape": list(right.shape),
        }
    difference = np.abs(left - right)
    maximum = float(np.max(difference)) if difference.size else 0.0
    rms = (
        float(np.sqrt(np.mean(difference * difference)))
        if difference.size
        else 0.0
    )
    scale = max(
        float(np.max(np.abs(left))) if left.size else 0.0,
        float(np.max(np.abs(right))) if right.size else 0.0,
        np.finfo(float).tiny,
    )
    tolerance = absolute_tolerance + relative_tolerance * scale
    return {
        "passed": bool(maximum <= tolerance),
        "shape_equal": True,
        "exactly_equal": bool(np.array_equal(left, right, equal_nan=True)),
        "rms_absolute_difference": rms,
        "max_absolute_difference": maximum,
        "scale": scale,
        "tolerance": tolerance,
    }


def _presentation_state_from_hdf5(
    handle: h5py.File,
) -> tuple[np.ndarray, np.ndarray]:
    time_values = np.asarray(handle["time"], dtype=float)
    particle_positions = np.asarray(
        handle["state/material_particles/position"], dtype=float
    )
    particle_velocities = np.asarray(
        handle["state/material_particles/velocity"], dtype=float
    )
    state = np.concatenate(
        [
            particle_positions.reshape(time_values.size, -1),
            np.asarray(handle["bodies/bob/com_position"], dtype=float),
            np.asarray(
                handle["bodies/bob/quaternion_body_to_world"], dtype=float
            ),
            particle_velocities.reshape(time_values.size, -1),
            np.asarray(handle["bodies/bob/com_velocity"], dtype=float),
            np.asarray(
                handle["bodies/bob/angular_velocity_world"], dtype=float
            ),
        ],
        axis=1,
    )
    return time_values, state


def _postprocess_existing(args: argparse.Namespace) -> int:
    """Benchmark the whole saved target trajectory without reintegration."""

    config_path = Path(args.config).resolve()
    result_path = Path(args.result).resolve()
    report_path = Path(args.report).resolve()
    cfg = load_config(config_path)
    validate_physical_config(cfg)
    model = HighFidelityModel(cfg)
    with h5py.File(result_path, "r") as handle:
        time_values, state = _presentation_state_from_hdf5(handle)
    if state.shape != (time_values.size, model.state_size):
        raise ValueError(
            "Saved HF result state does not match the requested model topology."
        )

    cpu_started = _cpu_seconds()
    wall_started = time.perf_counter()
    with _ResourceMonitor() as monitor:
        presentation, unresolved, worker_count = _presentation_samples(
            model,
            time_values,
            state,
            model.guard_component_metadata(),
            check_guards=True,
        )
        if unresolved is not None:
            raise RuntimeError(
                "Optimized post-processing found an unresolved sampled guard: "
                f"{unresolved}"
            )
        energy = presentation["energy"]
        energy["dissipation_axial"] = np.concatenate(
            [
                [0.0],
                cumulative_trapezoid(
                    energy["axial_dissipation_rate"], time_values
                ),
            ]
        )
        energy["dissipation_aero"] = np.concatenate(
            [
                [0.0],
                cumulative_trapezoid(
                    energy["aero_dissipation_rate"], time_values
                ),
            ]
        )
        energy["work_air"] = np.concatenate(
            [[0.0], cumulative_trapezoid(energy["air_work_rate"], time_values)]
        )
        energy["work_support"] = np.concatenate(
            [
                [0.0],
                cumulative_trapezoid(energy["support_work_rate"], time_values),
            ]
        )
        energy["balance_residual"] = (
            energy["mechanical"]
            - energy["mechanical"][0]
            + energy["dissipation_axial"]
            + energy["dissipation_aero"]
            - energy["work_air"]
            - energy["work_support"]
        ) / max(
            model.force_scale * model.characteristic_length,
            1.0e-12,
        )
        geometry = presentation["geometry"]
        guard_margins = {
            "MINIMUM_SEGMENT_LENGTH": (
                geometry["minimum_segment"] - model.length_guard
            ),
            "BENDING_TURN_CLEARANCE": (
                geometry["minimum_bending_turn_clearance"]
                - model.bending_turn_clearance_floor
            ),
            "AERODYNAMIC_CHORD_LENGTH": (
                geometry["minimum_aerodynamic_chord_length"]
                - model.aerodynamic_chord_guard
            ),
        }
        if model.contact_guard_enabled:
            guard_margins.update(
                {
                    "BOB_ROD_CLEARANCE": (
                        geometry["bob_contact_margin"]
                        - model.minimum_clearance
                    ),
                    "ROD_SELF_CLEARANCE": (
                        geometry["rod_self_contact_margin"]
                        - model.minimum_clearance
                    ),
                    "BOB_SOCKET_MATERIAL_EXTENT": geometry[
                        "bob_socket_material_extent"
                    ],
                    "BOB_SOCKET_RADIAL_MONOTONICITY": geometry[
                        "bob_socket_radial_monotonicity"
                    ],
                    "BOB_SOCKET_CUT_CLEARANCE": geometry[
                        "bob_socket_cut_clearance"
                    ],
                    "JUNCTION_SOCKET_MATERIAL_EXTENT": geometry[
                        "junction_socket_material_extent"
                    ],
                    "JUNCTION_SOCKET_PROJECTIVE_OPENING": geometry[
                        "junction_socket_projective_opening"
                    ],
                    "JUNCTION_SOCKET_CUT_CLEARANCE": geometry[
                        "junction_socket_cut_clearance"
                    ],
                }
            )
        events = _sampled_axial_events(
            time_values,
            presentation["cable_tension"],
            presentation["cable_axial_force"],
            zero_tolerance=model.tension_zero_tolerance,
            compression_regularization_scale=(
                model.compression_regularization_scale
            ),
        )
    wall_seconds = time.perf_counter() - wall_started
    cpu_seconds = _cpu_seconds() - cpu_started

    comparisons: dict[str, dict[str, Any]] = {}
    with h5py.File(result_path, "r") as handle:
        def compare(name: str, candidate: np.ndarray, reference_path: str) -> None:
            comparisons[name] = _array_error(
                candidate,
                np.asarray(handle[reference_path]),
                absolute_tolerance=args.absolute_tolerance,
                relative_tolerance=args.relative_tolerance,
            )

        compare(
            "bob_quaternion",
            presentation["bob_quaternion"],
            "bodies/bob/quaternion_body_to_world",
        )
        compare(
            "bob_attachment_position",
            presentation["bob_attachment"],
            "bodies/bob/attachment_position",
        )
        for branch in _BRANCHES:
            compare(
                f"cable_position__{branch}",
                presentation["cable_positions"][branch],
                f"cables/{branch}/material_path/position",
            )
            compare(
                f"cable_velocity__{branch}",
                presentation["cable_velocities"][branch],
                f"cables/{branch}/material_path/velocity",
            )
            compare(
                f"signed_axial_force__{branch}",
                presentation["cable_axial_force"][branch],
                f"cables/{branch}/segments/signed_axial_force",
            )
            compare(
                f"tension__{branch}",
                presentation["cable_tension"][branch],
                f"cables/{branch}/segments/tension",
            )
        compare("reaction__support_A", presentation["reaction_a"], "reactions/support_A")
        compare("reaction__support_B", presentation["reaction_b"], "reactions/support_B")
        for name, values in energy.items():
            compare(f"energy__{name}", values, f"energy/{name}")
        for name, values in guard_margins.items():
            compare(f"guard__{name}", values, f"validity/guard_margin/{name}")

    reference_events = json.loads(
        (result_path.parent / "events.json").read_text(encoding="utf-8")
    )
    event_identity = [
        (
            event.get("type"),
            event.get("branch"),
            event.get("material_segment"),
            event.get("time"),
            event.get("axial_regime"),
            event.get("axial_regime_before"),
            event.get("axial_regime_after"),
        )
        for event in events
    ]
    reference_event_identity = [
        (
            event.get("type"),
            event.get("branch"),
            event.get("material_segment"),
            event.get("time"),
            event.get("axial_regime"),
            event.get("axial_regime_before"),
            event.get("axial_regime_after"),
        )
        for event in reference_events
    ]
    passed = all(item["passed"] for item in comparisons.values()) and (
        event_identity == reference_event_identity
    )
    report = {
        "schema": "YPS-HF-FULL-POSTPROCESS-BENCHMARK-1.0",
        "config": str(config_path),
        "config_sha256": _sha256(config_path),
        "source_result": str(result_path),
        "source_result_sha256": _sha256(result_path),
        "samples": int(time_values.size),
        "workers": worker_count,
        "wall_seconds": wall_seconds,
        "process_tree_cpu_seconds": cpu_seconds,
        "average_equivalent_cpu_cores": (
            cpu_seconds / max(wall_seconds, np.finfo(float).tiny)
        ),
        "average_cpu_utilization_percent": (
            100.0 * cpu_seconds / max(wall_seconds, np.finfo(float).tiny)
        ),
        "peak_process_tree_rss_bytes": int(monitor.peak_tree_rss_bytes),
        "simulation_gpu_backend": "NOT_USED_CPU_ONLY",
        "system_gpu_utilization_percent_mean": (
            float(np.mean(monitor.gpu_utilization_percent))
            if monitor.gpu_utilization_percent
            else None
        ),
        "system_gpu_utilization_percent_max": (
            float(np.max(monitor.gpu_utilization_percent))
            if monitor.gpu_utilization_percent
            else None
        ),
        "system_gpu_memory_mib_max": (
            float(np.max(monitor.gpu_memory_mib))
            if monitor.gpu_memory_mib
            else None
        ),
        "events_identity_equal": event_identity == reference_event_identity,
        "event_count": len(events),
        "comparisons": comparisons,
        "passed": passed,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if passed else 1


def _run(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    source_result = Path(args.initial_result).resolve()
    output_prefix = Path(args.output_prefix).resolve()
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    cfg = load_config(config_path).model_copy(deep=True)
    cfg.run.name = f"hf_performance_{args.label}"
    cfg.run.output_directory = str(output_prefix.parent / f"unused_{args.label}")
    cfg.solver.t_end = _quantity(args.window_ms * 1.0e-3, "s")
    if args.output_dt_us is not None:
        cfg.solver.output_dt = _quantity(args.output_dt_us * 1.0e-6, "s")
        cfg.solver.max_step = _quantity(args.output_dt_us * 1.0e-6, "s")
    validate_physical_config(cfg)

    model_started = time.perf_counter()
    model = HighFidelityModel(cfg)
    model_wall = time.perf_counter() - model_started
    preparation = _initial_preparation(model, source_result)

    cpu_started = _cpu_seconds()
    wall_started = time.perf_counter()
    with _ResourceMonitor() as monitor:
        solver_started = time.perf_counter()
        result = simulate_high_fidelity(
            cfg,
            model=model,
            preparation=None if args.resume_checkpoint else preparation,
            checkpoint_path=args.checkpoint,
            resume_from_checkpoint=args.resume_checkpoint,
        )
        solver_wall = time.perf_counter() - solver_started
    total_wall = time.perf_counter() - wall_started
    cpu_seconds = _cpu_seconds() - cpu_started
    integration_wall = float(result.diagnostics["runtime_seconds"])
    nonintegration_wall = solver_wall - integration_wall

    arrays = _result_arrays(result)
    np.savez(output_prefix.with_suffix(".npz"), **arrays)
    metrics = {
        "schema": "YPS-HF-PERFORMANCE-BENCHMARK-1.0",
        "label": args.label,
        "config_path": str(config_path),
        "config_file_sha256": _sha256(config_path),
        "resolved_short_config_sha256": resolved_config_sha256(cfg),
        "source_tree_hash": source_hash(
            Path(__file__).resolve().parents[1] / "src" / "ypendulum"
        ),
        "source_result_h5": str(source_result),
        "source_result_sha256": _sha256(source_result),
        "window_seconds": args.window_ms * 1.0e-3,
        "output_dt_seconds": float(result.time[1] - result.time[0]),
        "presentation_samples": int(result.time.size),
        "accepted_samples": int(result.integration_time.size),
        "model_construction_wall_seconds": model_wall,
        "solver_total_wall_seconds": solver_wall,
        "integration_wall_seconds": integration_wall,
        "postprocess_and_solver_overhead_wall_seconds": nonintegration_wall,
        "measured_total_wall_seconds": total_wall,
        "process_tree_cpu_seconds": cpu_seconds,
        "average_equivalent_cpu_cores": cpu_seconds / max(total_wall, np.finfo(float).tiny),
        "average_process_cpu_utilization_percent": 100.0
        * cpu_seconds
        / max(total_wall, np.finfo(float).tiny),
        "peak_process_tree_rss_bytes": int(monitor.peak_tree_rss_bytes),
        "system_gpu_utilization_percent_mean": (
            float(np.mean(monitor.gpu_utilization_percent))
            if monitor.gpu_utilization_percent
            else None
        ),
        "system_gpu_utilization_percent_max": (
            float(np.max(monitor.gpu_utilization_percent))
            if monitor.gpu_utilization_percent
            else None
        ),
        "system_gpu_memory_mib_max": (
            float(np.max(monitor.gpu_memory_mib)) if monitor.gpu_memory_mib else None
        ),
        "simulation_gpu_backend": "NOT_USED_CPU_ONLY",
        "integration_checkpoint_path": (
            str(Path(args.checkpoint).resolve()) if args.checkpoint else None
        ),
        "integration_checkpoint_reused": bool(args.resume_checkpoint),
        "physical_status": result.physical_status,
        "numerical_status": result.numerical_status,
        "valid_interval": list(result.valid_interval),
        "events_canonical_json": _canonical_events(result.events),
        "scientific_array_keys": sorted(arrays),
        "diagnostics": {
            "nfev": int(result.diagnostics["nfev"]),
            "njev": int(result.diagnostics["njev"]),
            "nlu": int(result.diagnostics["nlu"]),
            "postprocess_worker_count": int(
                result.diagnostics["postprocess_worker_count"]
            ),
            "postprocess_physical_core_count": int(
                result.diagnostics["postprocess_physical_core_count"]
            ),
            "postprocess_process_tree_cpu_seconds": float(
                result.diagnostics["postprocess_process_tree_cpu_seconds"]
            ),
            "postprocess_average_equivalent_cpu_cores": float(
                result.diagnostics["postprocess_average_equivalent_cpu_cores"]
            ),
            "postprocess_average_cpu_utilization_percent": float(
                result.diagnostics["postprocess_average_cpu_utilization_percent"]
            ),
            "maximum_energy_balance_residual": float(
                np.max(np.abs(result.energy["balance_residual"]))
            ),
            "minimum_guard_margins": {
                name: float(np.min(values))
                for name, values in sorted(result.guard_margins.items())
            },
            "guard_component_metadata": result.diagnostics["guard_component_metadata"],
        },
    }
    output_prefix.with_suffix(".json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _compare(args: argparse.Namespace) -> int:
    baseline_prefix = Path(args.baseline_prefix).resolve()
    candidate_prefix = Path(args.candidate_prefix).resolve()
    report_path = Path(args.report).resolve()
    left_meta = json.loads(baseline_prefix.with_suffix(".json").read_text())
    right_meta = json.loads(candidate_prefix.with_suffix(".json").read_text())
    per_array: dict[str, Any] = {}
    failures: list[str] = []
    with np.load(baseline_prefix.with_suffix(".npz")) as left, np.load(
        candidate_prefix.with_suffix(".npz")
    ) as right:
        if set(left.files) != set(right.files):
            failures.append("scientific array key sets differ")
        for key in sorted(set(left.files) & set(right.files)):
            a = np.asarray(left[key])
            b = np.asarray(right[key])
            if a.shape != b.shape:
                per_array[key] = {"shape_equal": False, "left": a.shape, "right": b.shape}
                failures.append(f"{key}: shape mismatch")
                continue
            difference = np.abs(a - b)
            maximum = float(np.max(difference)) if difference.size else 0.0
            rms = float(np.sqrt(np.mean(difference * difference))) if difference.size else 0.0
            scale = max(
                float(np.max(np.abs(a))) if a.size else 0.0,
                float(np.max(np.abs(b))) if b.size else 0.0,
                1.0,
            )
            tolerance = args.absolute_tolerance + args.relative_tolerance * scale
            exact = bool(np.array_equal(a, b, equal_nan=True))
            passed = bool(maximum <= tolerance)
            per_array[key] = {
                "shape_equal": True,
                "exactly_equal": exact,
                "rms_absolute_difference": rms,
                "max_absolute_difference": maximum,
                "tolerance": tolerance,
                "passed": passed,
            }
            if not passed:
                failures.append(f"{key}: max {maximum:.17g} > {tolerance:.17g}")
    for name in ("physical_status", "numerical_status", "valid_interval", "events_canonical_json"):
        if left_meta[name] != right_meta[name]:
            failures.append(f"metadata mismatch: {name}")
    report = {
        "schema": "YPS-HF-PERFORMANCE-COMPARISON-1.0",
        "baseline": str(baseline_prefix),
        "candidate": str(candidate_prefix),
        "absolute_tolerance": args.absolute_tolerance,
        "relative_tolerance": args.relative_tolerance,
        "passed": not failures,
        "failures": failures,
        "per_array": per_array,
        "wall_speedup": left_meta["solver_total_wall_seconds"]
        / right_meta["solver_total_wall_seconds"],
        "postprocess_speedup": left_meta[
            "postprocess_and_solver_overhead_wall_seconds"
        ]
        / right_meta["postprocess_and_solver_overhead_wall_seconds"],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--config", required=True)
    run_parser.add_argument("--initial-result", required=True)
    run_parser.add_argument("--output-prefix", required=True)
    run_parser.add_argument("--label", required=True)
    run_parser.add_argument("--window-ms", type=float, default=1.0)
    run_parser.add_argument("--output-dt-us", type=float)
    run_parser.add_argument("--checkpoint")
    run_parser.add_argument("--resume-checkpoint", action="store_true")
    run_parser.set_defaults(func=_run)

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--baseline-prefix", required=True)
    compare_parser.add_argument("--candidate-prefix", required=True)
    compare_parser.add_argument("--report", required=True)
    compare_parser.add_argument("--absolute-tolerance", type=float, default=5.0e-13)
    compare_parser.add_argument("--relative-tolerance", type=float, default=5.0e-13)
    compare_parser.set_defaults(func=_compare)

    postprocess_parser = subparsers.add_parser("postprocess-existing")
    postprocess_parser.add_argument("--config", required=True)
    postprocess_parser.add_argument("--result", required=True)
    postprocess_parser.add_argument("--report", required=True)
    postprocess_parser.add_argument(
        "--absolute-tolerance", type=float, default=5.0e-13
    )
    postprocess_parser.add_argument(
        "--relative-tolerance", type=float, default=5.0e-13
    )
    postprocess_parser.set_defaults(func=_postprocess_existing)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

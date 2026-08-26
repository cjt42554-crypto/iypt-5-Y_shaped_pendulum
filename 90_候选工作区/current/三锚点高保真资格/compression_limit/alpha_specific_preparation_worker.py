#!/usr/bin/env python3
"""Prepare and qualify one isolated alpha-specific held equilibrium."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import numpy as np


SCRIPT_PATH = Path(__file__).resolve()
CANDIDATE_ROOT = SCRIPT_PATH.parents[1]
if str(CANDIDATE_ROOT) not in sys.path:
    sys.path.insert(0, str(CANDIDATE_ROOT))

import guard_contract_v2_full as guard_v2


def _classification(value: float, tolerance: float) -> str:
    if value < -tolerance:
        return "NEGATIVE_BEYOND_TOLERANCE"
    if value > tolerance:
        return "POSITIVE_RESOLVED"
    return "MARGINAL_WITHIN_TOLERANCE"


def _raw_sign(value: float) -> str:
    if value < 0.0:
        return "NEGATIVE"
    if value > 0.0:
        return "POSITIVE"
    return "ZERO"


def _dense_hessian_spectrum(
    gradient: Callable[[np.ndarray], np.ndarray],
    candidate: np.ndarray,
    step_m: float,
    worker_count: int,
) -> tuple[np.ndarray, np.ndarray, float]:
    dimension = candidate.size

    def column(index: int) -> np.ndarray:
        basis = np.zeros(dimension, dtype=float)
        basis[index] = 1.0
        plus = gradient(candidate + step_m * basis)
        minus = gradient(candidate - step_m * basis)
        return (plus - minus) / (2.0 * step_m)

    started = time.monotonic()
    if worker_count == 1:
        columns = [column(index) for index in range(dimension)]
    else:
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="alpha-specific-hessian",
        ) as executor:
            columns = list(executor.map(column, range(dimension)))
    hessian = np.column_stack(columns)
    hessian = 0.5 * (hessian + hessian.T)
    eigenvalues, eigenvectors = np.linalg.eigh(hessian)
    elapsed = time.monotonic() - started
    if not np.all(np.isfinite(hessian)) or not np.all(np.isfinite(eigenvalues)):
        raise FloatingPointError("Non-finite held-endpoint Hessian spectrum.")
    return eigenvalues, eigenvectors, elapsed


def _energy_directional_curvature(
    energy: Callable[[np.ndarray], float],
    candidate: np.ndarray,
    direction: np.ndarray,
    step_m: float,
) -> float:
    center = energy(candidate)
    plus = energy(candidate + step_m * direction)
    minus = energy(candidate - step_m * direction)
    return float((plus - 2.0 * center + minus) / step_m**2)


def hessian_crosscheck(
    model: Any,
    preparation: Any,
    spec: dict[str, Any],
) -> dict[str, Any]:
    multipliers = [
        float(value) for value in spec["finite_difference_step_multipliers"]
    ]
    if multipliers != [0.5, 1.0, 2.0]:
        raise ValueError("Unexpected pre-frozen Hessian step multipliers.")
    (
        particles,
        bob,
        quaternion,
        _particle_velocity,
        _bob_velocity,
        _angular_velocity,
    ) = model.unpack_state(preparation.state)
    free_indices = np.concatenate(
        [branch.bead_indices for branch in model.branches.values()]
    )
    template = particles.copy()
    candidate = particles[free_indices].reshape(-1).copy()
    zero_particle_velocity = np.zeros_like(particles)
    zero3 = np.zeros(3, dtype=float)

    def evaluate(trial: np.ndarray) -> tuple[float, np.ndarray]:
        trial_particles = template.copy()
        trial_particles[free_indices] = trial.reshape(free_indices.size, 3)
        snapshot = model.evaluate(
            0.0,
            trial_particles,
            zero_particle_velocity,
            bob,
            zero3,
            quaternion,
            zero3,
            include_aero=False,
            compute_contact=False,
        )
        gravitational = -float(
            np.sum(
                model.particle_mass[free_indices, None]
                * trial_particles[free_indices]
                * model.gravity[None, :]
            )
        )
        energy = snapshot.axial_energy + snapshot.bending_energy + gravitational
        gradient = -snapshot.particle_force[free_indices].reshape(-1)
        if not math.isfinite(energy) or not np.all(np.isfinite(gradient)):
            raise FloatingPointError("Non-finite conservative objective probe.")
        return float(energy), gradient

    def energy(trial: np.ndarray) -> float:
        return evaluate(trial)[0]

    def gradient(trial: np.ndarray) -> np.ndarray:
        return evaluate(trial)[1]

    base_step = max(
        1.0e-6 * model.characteristic_length,
        256.0 * np.finfo(float).eps * model.characteristic_length,
    )
    tolerance = float(preparation.audit["hessian_tolerance_N_per_m"])
    worker_count = max(1, min(8, os.cpu_count() or 1))
    spectra: list[dict[str, Any]] = []
    base_eigenvector: np.ndarray | None = None
    base_minimum: float | None = None
    for multiplier in multipliers:
        step = multiplier * base_step
        eigenvalues, eigenvectors, elapsed = _dense_hessian_spectrum(
            gradient, candidate, step, worker_count
        )
        minimum = float(eigenvalues[0])
        maximum_abs = float(np.max(np.abs(eigenvalues)))
        resolved = np.abs(eigenvalues) > tolerance
        minimum_resolved_abs = (
            float(np.min(np.abs(eigenvalues[resolved])))
            if np.any(resolved)
            else None
        )
        condition = (
            maximum_abs / minimum_resolved_abs
            if minimum_resolved_abs is not None
            else None
        )
        record = {
            "step_multiplier": multiplier,
            "step_m": step,
            "minimum_eigenvalue_N_per_m": minimum,
            "maximum_absolute_eigenvalue_N_per_m": maximum_abs,
            "minimum_resolved_absolute_eigenvalue_N_per_m": (
                minimum_resolved_abs
            ),
            "resolved_condition_number": condition,
            "negative_beyond_tolerance_count": int(
                np.count_nonzero(eigenvalues < -tolerance)
            ),
            "marginal_within_tolerance_count": int(
                np.count_nonzero(np.abs(eigenvalues) <= tolerance)
            ),
            "classification": _classification(minimum, tolerance),
            "raw_sign": _raw_sign(minimum),
            "elapsed_wall_s": elapsed,
        }
        spectra.append(record)
        print(
            json.dumps(
                {
                    "phase": "HESSIAN_GRADIENT_SPECTRUM",
                    "compression_regularization_scale": float(
                        model.compression_regularization_scale
                    ),
                    "step_multiplier": multiplier,
                    "minimum_eigenvalue_N_per_m": minimum,
                    "classification": record["classification"],
                    "resolved_condition_number": condition,
                    "elapsed_wall_s": elapsed,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        if multiplier == 1.0:
            base_eigenvector = eigenvectors[:, 0].copy()
            base_minimum = minimum
    if base_eigenvector is None or base_minimum is None:
        raise RuntimeError("The pre-frozen base Hessian step was not evaluated.")
    base_eigenvector /= np.linalg.norm(base_eigenvector)
    directional: list[dict[str, Any]] = []
    for multiplier in multipliers:
        step = multiplier * base_step
        curvature = _energy_directional_curvature(
            energy, candidate, base_eigenvector, step
        )
        directional.append(
            {
                "step_multiplier": multiplier,
                "displacement_m": step,
                "curvature_N_per_m": curvature,
                "classification": _classification(curvature, tolerance),
                "raw_sign": _raw_sign(curvature),
            }
        )

    gradient_classes = {item["classification"] for item in spectra}
    gradient_signs = {item["raw_sign"] for item in spectra}
    directional_classes = {item["classification"] for item in directional}
    directional_signs = {item["raw_sign"] for item in directional}
    audit_minimum = float(
        preparation.audit["minimum_hessian_eigenvalue_N_per_m"]
    )
    base_agreement_error = abs(base_minimum - audit_minimum)
    checks = {
        "gradient_spectra_finite": all(
            math.isfinite(float(item["minimum_eigenvalue_N_per_m"]))
            and math.isfinite(
                float(item["maximum_absolute_eigenvalue_N_per_m"])
            )
            for item in spectra
        ),
        "gradient_psd_at_unchanged_tolerance": all(
            float(item["minimum_eigenvalue_N_per_m"]) >= -tolerance
            for item in spectra
        ),
        "gradient_tolerance_class_stable": len(gradient_classes) == 1,
        "gradient_raw_sign_stable": len(gradient_signs) == 1,
        "base_step_matches_preparation_audit": (
            base_agreement_error <= 10.0 * tolerance
        ),
        "resolved_stiffness_exists": all(
            item["resolved_condition_number"] is not None
            and math.isfinite(float(item["resolved_condition_number"]))
            for item in spectra
        ),
        "directional_curvatures_finite": all(
            math.isfinite(float(item["curvature_N_per_m"]))
            for item in directional
        ),
        "directional_psd_at_unchanged_tolerance": all(
            float(item["curvature_N_per_m"]) >= -tolerance
            for item in directional
        ),
        "directional_tolerance_class_stable": len(directional_classes) == 1,
        "directional_raw_sign_stable": len(directional_signs) == 1,
    }
    return {
        "schema_version": "YPS-ALPHA-SPECIFIC-HESSIAN-CROSSCHECK-RESULT-1.0",
        "passed": all(checks.values()),
        "dimension": int(candidate.size),
        "worker_count": worker_count,
        "base_step_m": base_step,
        "hessian_tolerance_N_per_m": tolerance,
        "preparation_audit_minimum_eigenvalue_N_per_m": audit_minimum,
        "base_step_agreement_error_N_per_m": base_agreement_error,
        "checks": checks,
        "gradient_hessian_spectra": spectra,
        "independent_energy_directional_curvatures": directional,
        "condition_number_acceptance_threshold": None,
        "condition_number_role": "diagnostic_only",
        "spec_schema_version": spec["schema_version"],
        "spec_canonical_sha256": guard_v2.canonical_sha256(spec),
    }


def _lowest_energy_selection_check(audit: dict[str, Any]) -> dict[str, Any]:
    accepted = [
        item
        for item in audit["candidate_records"]
        if item["accepted_stable_candidate"]
    ]
    if not accepted:
        return {
            "passed": False,
            "accepted_stable_candidate_count": 0,
            "selected_seed": audit.get("selected_seed"),
            "minimum_accepted_energy_J": None,
            "selected_energy_J": None,
        }
    selected_seed = audit["selected_seed"]
    selected = next(
        (item for item in accepted if item["seed"] == selected_seed), None
    )
    minimum = min(float(item["energy_J"]) for item in accepted)
    selected_energy = None if selected is None else float(selected["energy_J"])
    tolerance = 1.0e-12 * max(abs(minimum), 1.0)
    return {
        "passed": (
            selected_energy is not None
            and selected_energy <= minimum + tolerance
        ),
        "accepted_stable_candidate_count": len(accepted),
        "selected_seed": selected_seed,
        "minimum_accepted_energy_J": minimum,
        "selected_energy_J": selected_energy,
        "energy_comparison_tolerance_J": tolerance,
    }


def run(
    config_path: Path,
    output_directory: Path,
    guard_spec_path: Path,
    hessian_spec_path: Path,
) -> dict[str, Any]:
    from ypendulum.config import (
        load_config,
        resolved_config_sha256,
        validate_physical_config,
    )
    from ypendulum.config.units import to_si
    from ypendulum.hf import HighFidelityModel
    from ypendulum.hf.solver import prepare_initial_state

    output_directory.mkdir(parents=True, exist_ok=True)
    guard_spec = json.loads(guard_spec_path.read_text(encoding="utf-8"))
    hessian_spec = json.loads(hessian_spec_path.read_text(encoding="utf-8"))
    guard_v2.validate_spec(guard_spec)
    started = time.monotonic()
    cfg = load_config(config_path)
    validate_physical_config(cfg)
    model = HighFidelityModel(cfg)
    try:
        preparation = prepare_initial_state(cfg, model)
        print(
            json.dumps(
                {
                    "phase": "PREPARATION_SOLVED",
                    "compression_regularization_scale": float(
                        model.compression_regularization_scale
                    ),
                    "residual_inf_N": float(preparation.residual_inf_N),
                    "minimum_hessian_eigenvalue_N_per_m": (
                        preparation.audit.get(
                            "minimum_hessian_eigenvalue_N_per_m"
                        )
                    ),
                    "selected_seed": preparation.audit.get("selected_seed"),
                    "iterations": int(preparation.iterations),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        guard = guard_v2.evaluate_prepared_state(
            model, preparation.state, guard_spec
        )
        hessian = hessian_crosscheck(model, preparation, hessian_spec)
        lowest_energy = _lowest_energy_selection_check(preparation.audit)
        requested_force_tolerance = float(
            to_si(cfg.solver.static.force_tolerance, default_unit="N")
        )
        scale = float(model.compression_regularization_scale)
        expected_protocol = (
            "HELD_ENDPOINT_STABLE_ALPHA_SPECIFIC_EQUILIBRIUM_V2_CANDIDATE"
        )
        expected_mode = "held_endpoint_alpha_specific_stable_equilibrium_candidate"
        checks = {
            "positive_target_scale": 0.0 < scale < 1.0,
            "controlled_limit_study": bool(
                cfg.high_fidelity.controlled_limit_study
            ),
            "claim_level_out_of_scope": cfg.run.claim_level == "OUT_OF_SCOPE",
            "preparation_protocol_versioned": (
                preparation.audit.get("protocol") == expected_protocol
            ),
            "preparation_mode_versioned": (
                preparation.preparation_mode == expected_mode
            ),
            "preparation_scale_bound": (
                float(
                    preparation.audit.get(
                        "compression_regularization_scale", float("nan")
                    )
                )
                == scale
            ),
            "free_material_residual_passed": (
                math.isfinite(float(preparation.residual_inf_N))
                and float(preparation.residual_inf_N)
                <= requested_force_tolerance
            ),
            "lowest_energy_stable_candidate_selected": lowest_energy["passed"],
            "formal_raw_guards_positive": all(
                item["raw_gate_passed"]
                for item in guard["components"].values()
            ),
            "full_candidate_guard_passed": guard["passed"],
            "hessian_crosscheck_passed": hessian["passed"],
            "state_finite": bool(np.all(np.isfinite(preparation.state))),
        }
        passed = all(checks.values())
        state_path = output_directory / "prepared_state.npz"
        np.savez_compressed(
            state_path,
            state=np.asarray(preparation.state, dtype=float),
            compression_regularization_scale=np.array([scale], dtype=float),
        )
        report = {
            "schema_version": "YPS-ALPHA-SPECIFIC-PREPARATION-RESULT-1.0",
            "status": (
                "ALPHA_SPECIFIC_PREPARATION_QUALIFIED_FOR_DYNAMIC_GATE"
                if passed
                else "ALPHA_SPECIFIC_PREPARATION_NO_GO"
            ),
            "passed": passed,
            "checks": checks,
            "config_path": str(config_path),
            "config_sha256": guard_v2.sha256_file(config_path),
            "resolved_config_sha256": resolved_config_sha256(cfg),
            "compression_regularization_scale": scale,
            "requested_force_tolerance_N": requested_force_tolerance,
            "preparation": {
                "mode": preparation.preparation_mode,
                "protocol": preparation.audit.get("protocol"),
                "residual_inf_N": float(preparation.residual_inf_N),
                "iterations": int(preparation.iterations),
                "selected_seed": preparation.audit.get("selected_seed"),
                "seed_candidate_count": preparation.audit.get(
                    "seed_candidate_count"
                ),
                "minimum_hessian_eigenvalue_N_per_m": preparation.audit.get(
                    "minimum_hessian_eigenvalue_N_per_m"
                ),
                "hessian_tolerance_N_per_m": preparation.audit.get(
                    "hessian_tolerance_N_per_m"
                ),
                "candidate_records": preparation.audit.get(
                    "candidate_records"
                ),
            },
            "lowest_energy_selection": lowest_energy,
            "hessian_crosscheck": hessian,
            "guard_v2_full": guard,
            "prepared_state_path": str(state_path),
            "prepared_state_sha256": guard_v2.sha256_file(state_path),
            "elapsed_wall_s": time.monotonic() - started,
            "dynamic_run_count": 0,
            "formal_change_authorized": False,
            "claim_boundary": (
                "A passing result admits only this prepared candidate state to "
                "the next dynamic gate. It is not a trajectory, convergence, "
                "unilateral-limit, physical or experimental result."
            ),
        }
    except Exception as exc:  # fail-closed worker record; orchestrator continues
        report = {
            "schema_version": "YPS-ALPHA-SPECIFIC-PREPARATION-RESULT-1.0",
            "status": "ALPHA_SPECIFIC_PREPARATION_EXECUTION_FAILED",
            "passed": False,
            "config_path": str(config_path),
            "config_sha256": guard_v2.sha256_file(config_path),
            "compression_regularization_scale": float(
                model.compression_regularization_scale
            ),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "elapsed_wall_s": time.monotonic() - started,
            "dynamic_run_count": 0,
            "formal_change_authorized": False,
        }
    guard_v2.write_json(output_directory / "preparation_result.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument(
        "--guard-spec",
        type=Path,
        default=CANDIDATE_ROOT / "guard_contract_v2" / "full_spec.json",
    )
    parser.add_argument(
        "--hessian-spec",
        type=Path,
        default=SCRIPT_PATH.parent / "hessian_crosscheck_spec.json",
    )
    args = parser.parse_args()
    report = run(
        args.config.expanduser().resolve(),
        args.output_directory.expanduser().resolve(),
        args.guard_spec.expanduser().resolve(),
        args.hessian_spec.expanduser().resolve(),
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "passed": report["passed"],
                "compression_regularization_scale": report[
                    "compression_regularization_scale"
                ],
                "elapsed_wall_s": report["elapsed_wall_s"],
                "output": str(
                    args.output_directory.expanduser().resolve()
                    / "preparation_result.json"
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

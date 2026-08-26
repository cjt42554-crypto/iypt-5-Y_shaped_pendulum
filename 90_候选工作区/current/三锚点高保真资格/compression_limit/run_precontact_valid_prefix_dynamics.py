#!/usr/bin/env python3
"""Run one frozen contact-free trajectory only over its valid prefix."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

SCRIPT_PATH = Path(__file__).resolve()
COMPRESSION_ROOT = SCRIPT_PATH.parent
CANDIDATE_ROOT = COMPRESSION_ROOT.parent
BUILDER_PATH = COMPRESSION_ROOT / "build_alpha_specific_candidate.py"
FREEZE_SCRIPT_PATH = COMPRESSION_ROOT / "freeze_precontact_valid_prefix_dynamics.py"
PLAN_PATH = COMPRESSION_ROOT / "precontact_valid_prefix_dynamic_plan.json"
UPPER_PLAN_PATH = COMPRESSION_ROOT / "precontact_upper_gate_plan.json"
UPPER_RESULT_PATH = COMPRESSION_ROOT / "precontact_upper_gate" / "preparation_result.json"
STATE_PATH = COMPRESSION_ROOT / "precontact_upper_gate" / "prepared_state.npz"
BOUNDARY_RESULTS_PATH = COMPRESSION_ROOT / "precontact_boundary_results.json"
GUARD_SPEC_PATH = CANDIDATE_ROOT / "guard_contract_v2" / "full_spec.json"
GUARD_IMPLEMENTATION_PATH = CANDIDATE_ROOT / "guard_contract_v2_full.py"
RESULT_PATH = COMPRESSION_ROOT / "precontact_valid_prefix_dynamic_results.json"
DEFAULT_OUTPUT_ROOT = CANDIDATE_ROOT / "generated" / "precontact_valid_prefix_dynamic"
OVERLAY_SOURCE = (
    CANDIDATE_ROOT
    / "generated"
    / "precontact_alpha_boundary"
    / "alpha_specific_overlay"
    / "overlay"
    / "src"
)


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = _load_module(BUILDER_PATH, "precontact_valid_prefix_builder")
full_v2 = _load_module(GUARD_IMPLEMENTATION_PATH, "precontact_valid_prefix_guard_v2")


def _sha256(path: Path) -> str:
    return builder.sha256_file(path)


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        relative = str(path.relative_to(root)).encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def first_failed_sample(records: list[dict[str, Any]]) -> int | None:
    """Return the first failed sample index; unresolved records fail closed."""

    for index, record in enumerate(records):
        if record.get("passed") is not True:
            return index
    return None


def _verify_bindings(plan: dict[str, Any]) -> dict[str, bool]:
    config_path = (CANDIDATE_ROOT / plan["config_path"]).resolve()
    file_paths = {
        "upper_gate_plan_sha256": UPPER_PLAN_PATH,
        "upper_gate_result_sha256": UPPER_RESULT_PATH,
        "prepared_state_archive_sha256": STATE_PATH,
        "boundary_results_sha256": BOUNDARY_RESULTS_PATH,
        "config_sha256": config_path,
        "guard_spec_sha256": GUARD_SPEC_PATH,
        "guard_implementation_sha256": GUARD_IMPLEMENTATION_PATH,
        "runner_sha256": SCRIPT_PATH,
        "freeze_script_sha256": FREEZE_SCRIPT_PATH,
    }
    bindings = plan["bindings"]
    checks = {
        key: _sha256(path) == bindings[key] for key, path in file_paths.items()
    }
    checks["formal_python_tree_sha256"] = (
        _tree_sha256(builder.FORMAL_SOURCE_ROOT)
        == bindings["formal_python_tree_sha256"]
    )
    checks["overlay_python_tree_sha256"] = (
        _tree_sha256(OVERLAY_SOURCE) == bindings["overlay_python_tree_sha256"]
    )
    if not all(checks.values()):
        raise RuntimeError(f"Frozen valid-prefix inputs drifted: {checks}")
    return checks


def _compact_candidate(report: dict[str, Any], index: int, time_s: float) -> dict[str, Any]:
    minimum_name = report["minimum_component"]
    minimum = report["components"][minimum_name]
    winner = minimum["normalized_winner"]
    return {
        "sample_index": index,
        "time_s": float(time_s),
        "passed": bool(report["passed"]),
        "status": report["status"],
        "minimum_component": minimum_name,
        "minimum_normalized_margin": float(report["minimum_normalized_margin"]),
        "minimum_normalized_margin_required": float(
            report["minimum_normalized_margin_required"]
        ),
        "winner_label": winner["label"],
        "winner_raw_margin": float(winner["raw_margin"]),
        "winner_local_scale": float(winner["local_scale"]),
        "failed_components": list(report["failed_components"]),
    }


def _state_at_presentation_sample(model: Any, result: Any, index: int) -> np.ndarray:
    return model.pack_state(
        result.particle_positions[index],
        result.bob_position[index],
        result.bob_quaternion[index],
        result.particle_velocities[index],
        result.bob_velocity[index],
        result.bob_angular_velocity[index],
    )


def _sample_candidate_prefix(
    model: Any,
    result: Any,
    guard_spec: dict[str, Any],
    initial_report: dict[str, Any],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    minima: dict[str, dict[str, Any]] = {}
    first_failure: dict[str, Any] | None = None
    last_pass: dict[str, Any] | None = None
    evaluated_reports: list[dict[str, Any]] = []
    for index, sample_time in enumerate(result.time):
        if index == 0:
            report = initial_report
        else:
            state = _state_at_presentation_sample(model, result, index)
            report = full_v2.evaluate_prepared_state(
                model,
                state,
                guard_spec,
                time_s=float(sample_time),
            )
        compact = _compact_candidate(report, index, float(sample_time))
        records.append(compact)
        evaluated_reports.append({"passed": report.get("passed")})
        for component, component_report in report["components"].items():
            value = float(component_report["normalized_minimum"])
            current = minima.get(component)
            if current is None or value < current["normalized_margin"]:
                winner = component_report["normalized_winner"]
                minima[component] = {
                    "sample_index": index,
                    "time_s": float(sample_time),
                    "normalized_margin": value,
                    "raw_margin": float(winner["raw_margin"]),
                    "local_scale": float(winner["local_scale"]),
                    "winner_label": winner["label"],
                }
        if first_failed_sample(evaluated_reports) is not None:
            first_failure = compact
            break
        last_pass = compact

    if first_failure is None:
        status = "SAMPLED_CANDIDATE_GUARD_PASS_AT_ALL_PRESENTATION_SAMPLES"
        bracket = None
    else:
        status = "SAMPLED_CANDIDATE_GUARD_FIRST_FAILURE_BRACKETED"
        bracket = {
            "last_passing_sample": last_pass,
            "first_failing_sample": first_failure,
            "width_s": (
                None
                if last_pass is None
                else float(first_failure["time_s"] - last_pass["time_s"])
            ),
            "continuous_crossing_time_resolved": False,
        }
    return {
        "status": status,
        "sampling_identity": "presentation grid from t=0 until first failure",
        "continuous_certificate": False,
        "evaluated_sample_count": len(records),
        "total_presentation_sample_count": int(result.time.size),
        "last_passing_sample": last_pass,
        "first_failing_sample": first_failure,
        "first_failure_bracket": bracket,
        "component_minima_over_evaluated_prefix": minima,
    }


def _raw_guard_minima(result: Any) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for name, values in result.guard_margins.items():
        array = np.asarray(values, dtype=float)
        index = int(np.argmin(array))
        summary[name] = {
            "sample_index": index,
            "time_s": float(result.time[index]),
            "raw_margin": float(array[index]),
        }
    return summary


def _event_summary(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for event in events:
        item: dict[str, Any] = {
            "type": event.get("type"),
            "time_s": None if event.get("time") is None else float(event["time"]),
        }
        for key in ("reasons", "bracketed_guard_names", "branch"):
            if key in event:
                item[key] = event[key]
        if "guard_components" in event:
            item["guard_components"] = {
                name: float(value)
                for name, value in event["guard_components"].items()
            }
        summary.append(item)
    return summary


def run(*, resume_from_checkpoint: bool = False) -> dict[str, Any]:
    if RESULT_PATH.exists():
        raise RuntimeError("The frozen valid-prefix result already exists.")
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if plan.get("status") != "EXACT_PRECONTACT_VALID_PREFIX_RUN_FROZEN_BEFORE_DYNAMICS":
        raise RuntimeError("The valid-prefix plan is not frozen.")
    if plan.get("dynamic_run_count_at_freeze") != 0:
        raise RuntimeError("The plan was not frozen before dynamics.")
    binding_checks_before = _verify_bindings(plan)
    preparation_report = json.loads(UPPER_RESULT_PATH.read_text(encoding="utf-8"))
    if preparation_report.get("passed") is not True:
        raise RuntimeError("The prepared state is not admitted to dynamics.")

    from ypendulum.config import load_config, resolved_config_sha256
    from ypendulum.config.validation import validate_physical_config
    from ypendulum.hf import (
        HighFidelityModel,
        PreparationResult,
        simulate_high_fidelity,
    )
    from ypendulum.io import write_hf_result

    config_path = (CANDIDATE_ROOT / plan["config_path"]).resolve()
    cfg = load_config(config_path)
    validate_physical_config(cfg)
    model = HighFidelityModel(cfg)
    if model.model_id != plan["model_id"]:
        raise RuntimeError("The runtime model identity drifted.")
    if not math.isclose(
        float(model.compression_regularization_scale),
        float(plan["alpha"]),
        rel_tol=0.0,
        abs_tol=0.0,
    ):
        raise RuntimeError("The runtime alpha drifted.")

    with np.load(STATE_PATH, allow_pickle=False) as archive:
        state = np.asarray(archive["state"], dtype=float)
        archived_alpha = float(
            np.asarray(archive["compression_regularization_scale"], dtype=float)[0]
        )
    if state.shape != (model.state_size,) or not np.all(np.isfinite(state)):
        raise RuntimeError("The exact prepared state is invalid for the runtime model.")
    if archived_alpha != float(plan["alpha"]):
        raise RuntimeError("The state archive alpha drifted.")
    guard_spec = json.loads(GUARD_SPEC_PATH.read_text(encoding="utf-8"))
    initial_candidate = full_v2.evaluate_prepared_state(model, state, guard_spec)
    if initial_candidate["passed"] is not True:
        raise RuntimeError("The exact initial state no longer passes guard v2.")

    preparation = PreparationResult(
        state=state,
        residual_inf_N=float(preparation_report["preparation"]["residual_inf_N"]),
        iterations=int(preparation_report["preparation"]["iterations"]),
        bob_held=True,
        preparation_mode=str(preparation_report["preparation"]["mode"]),
        audit={
            "protocol": preparation_report["preparation"]["protocol"],
            "selected_seed": preparation_report["preparation"]["selected_seed"],
            "prepared_state_archive_sha256": _sha256(STATE_PATH),
            "admission_result_sha256": _sha256(UPPER_RESULT_PATH),
            "dynamic_plan_sha256": _sha256(PLAN_PATH),
        },
    )

    output_root = (CANDIDATE_ROOT / plan["output_root"]).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_root / "integration_checkpoint.npz"
    h5_path = output_root / "valid_prefix_result.h5"
    if h5_path.exists():
        raise RuntimeError("The valid-prefix HDF5 result already exists.")
    if resume_from_checkpoint and not checkpoint_path.exists():
        raise RuntimeError("No integration checkpoint exists to resume.")
    if not resume_from_checkpoint and checkpoint_path.exists():
        raise RuntimeError("A checkpoint exists; use --resume-from-checkpoint.")

    started = time.monotonic()
    result = simulate_high_fidelity(
        cfg,
        model=model,
        preparation=preparation,
        checkpoint_path=checkpoint_path,
        resume_from_checkpoint=resume_from_checkpoint,
    )
    write_hf_result(h5_path, result, model)
    candidate_prefix = _sample_candidate_prefix(
        model,
        result,
        guard_spec,
        initial_candidate,
    )
    elapsed = time.monotonic() - started
    binding_checks_after = _verify_bindings(plan)

    formal_event = any(event.get("type") == "HF_VALIDITY_GUARD" for event in result.events)
    candidate_failed = candidate_prefix["first_failing_sample"] is not None
    if candidate_failed:
        status = "CANDIDATE_QUALIFIED_PREFIX_ENDED__NO_POSTCONTACT_MODEL"
    elif formal_event:
        status = "FORMAL_RAW_VALID_PREFIX_ENDED__NO_POSTCONTACT_MODEL"
    else:
        status = "VALID_PREFIX_WINDOW_COMPLETED__SINGLE_RUN_UNCERTIFIED"

    diagnostics = result.diagnostics
    report = {
        "schema_version": "YPS-PRECONTACT-VALID-PREFIX-DYNAMIC-RESULT-1.0",
        "status": status,
        "research_identity": plan["research_identity"],
        "model_id": result.model_id,
        "alpha": float(plan["alpha"]),
        "passed_exact_preparation_gate": True,
        "resolved_config_sha256": resolved_config_sha256(cfg),
        "prepared_state_archive_sha256": _sha256(STATE_PATH),
        "dynamic_plan_sha256": _sha256(PLAN_PATH),
        "binding_checks_before": binding_checks_before,
        "binding_checks_after": binding_checks_after,
        "run": {
            "requested_t_end_s": float(plan["integration_contract"]["t_end_s"]),
            "returned_valid_interval_s": [
                float(result.valid_interval[0]),
                float(result.valid_interval[1]),
            ],
            "last_presentation_time_s": float(result.time[-1]),
            "presentation_sample_count": int(result.time.size),
            "accepted_state_count": int(result.integration_time.size),
            "physical_status": result.physical_status,
            "numerical_status": result.numerical_status,
            "formal_raw_guard_event_present": formal_event,
            "resumed_from_checkpoint": bool(resume_from_checkpoint),
            "elapsed_wall_s": elapsed,
        },
        "candidate_v2_sampled_prefix": candidate_prefix,
        "formal_raw_guard_minima_on_returned_samples": _raw_guard_minima(result),
        "events": _event_summary(result.events),
        "numerical_diagnostics": {
            "integration_wall_seconds": float(diagnostics["integration_wall_seconds"]),
            "nfev": int(diagnostics["nfev"]),
            "njev": int(diagnostics["njev"]),
            "nlu": int(diagnostics["nlu"]),
            "accepted_integration_step_count": int(
                diagnostics["accepted_integration_step_count"]
            ),
            "minimum_accepted_integration_step_s": diagnostics[
                "minimum_accepted_integration_step_s"
            ],
            "maximum_accepted_integration_step_s": diagnostics[
                "maximum_accepted_integration_step_s"
            ],
            "max_abs_energy_balance_residual": float(
                diagnostics["max_abs_energy_balance_residual"]
            ),
            "raw_guard_certification_status": diagnostics[
                "raw_guard_certification_status"
            ],
            "maximum_quaternion_norm_error": float(
                diagnostics["maximum_quaternion_norm_error"]
            ),
        },
        "artifacts": {
            "hdf5_path": str(h5_path.relative_to(CANDIDATE_ROOT)),
            "hdf5_sha256": _sha256(h5_path),
            "integration_checkpoint_path": str(
                checkpoint_path.relative_to(CANDIDATE_ROOT)
            ),
            "integration_checkpoint_sha256": _sha256(checkpoint_path),
        },
        "dynamic_run_count": 1,
        "postcontact_run_count": 0,
        "formal_change_authorized": False,
        "claim_boundary": (
            "This is one single-run, contact-free valid-prefix result from an "
            "exact admitted state. The formal solver stops at a raw guard event; "
            "candidate-v2 timing is only presentation-grid bracket evidence. "
            "No continuation, convergence, physical prediction or experimental "
            "validation is claimed."
        ),
    }
    full_v2.write_json(RESULT_PATH, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-from-checkpoint", action="store_true")
    args = parser.parse_args()
    report = run(resume_from_checkpoint=args.resume_from_checkpoint)
    print(
        json.dumps(
            {
                "status": report["status"],
                "valid_interval_s": report["run"]["returned_valid_interval_s"],
                "candidate_sampled_status": report[
                    "candidate_v2_sampled_prefix"
                ]["status"],
                "result": str(RESULT_PATH),
            },
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

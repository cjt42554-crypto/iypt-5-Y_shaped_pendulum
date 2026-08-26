#!/usr/bin/env python3
"""Freeze one contact-free valid-prefix dynamic run before execution."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import yaml

SCRIPT_PATH = Path(__file__).resolve()
COMPRESSION_ROOT = SCRIPT_PATH.parent
CANDIDATE_ROOT = COMPRESSION_ROOT.parent
REPOSITORY_ROOT = CANDIDATE_ROOT.parents[2]
BUILDER_PATH = COMPRESSION_ROOT / "build_alpha_specific_candidate.py"
RUNNER_PATH = COMPRESSION_ROOT / "run_precontact_valid_prefix_dynamics.py"
UPPER_PLAN_PATH = COMPRESSION_ROOT / "precontact_upper_gate_plan.json"
UPPER_RESULT_PATH = COMPRESSION_ROOT / "precontact_upper_gate" / "preparation_result.json"
STATE_PATH = COMPRESSION_ROOT / "precontact_upper_gate" / "prepared_state.npz"
BOUNDARY_RESULTS_PATH = COMPRESSION_ROOT / "precontact_boundary_results.json"
GUARD_SPEC_PATH = CANDIDATE_ROOT / "guard_contract_v2" / "full_spec.json"
GUARD_IMPLEMENTATION_PATH = CANDIDATE_ROOT / "guard_contract_v2_full.py"
PLAN_PATH = COMPRESSION_ROOT / "precontact_valid_prefix_dynamic_plan.json"
RESULT_PATH = COMPRESSION_ROOT / "precontact_valid_prefix_dynamic_results.json"
OUTPUT_ROOT = CANDIDATE_ROOT / "generated" / "precontact_valid_prefix_dynamic"
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


builder = _load_module(BUILDER_PATH, "precontact_dynamic_builder")


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


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def freeze() -> dict[str, Any]:
    if PLAN_PATH.exists():
        raise RuntimeError("The valid-prefix dynamic plan is already frozen.")
    if RESULT_PATH.exists():
        raise RuntimeError("The valid-prefix dynamic result already exists.")
    if OUTPUT_ROOT.exists():
        raise RuntimeError("The valid-prefix dynamic output already exists.")
    if not RUNNER_PATH.is_file():
        raise RuntimeError("The valid-prefix runner must exist before freezing.")
    if not OVERLAY_SOURCE.is_dir():
        raise RuntimeError("The frozen alpha-specific overlay is absent.")

    upper_plan = json.loads(UPPER_PLAN_PATH.read_text(encoding="utf-8"))
    preparation = json.loads(UPPER_RESULT_PATH.read_text(encoding="utf-8"))
    boundary = json.loads(BOUNDARY_RESULTS_PATH.read_text(encoding="utf-8"))
    if preparation.get("status") != (
        "ALPHA_SPECIFIC_PREPARATION_QUALIFIED_FOR_DYNAMIC_GATE"
    ) or preparation.get("passed") is not True:
        raise RuntimeError("The exact upper-gate preparation did not pass.")
    if not all(preparation["checks"].values()):
        raise RuntimeError("The upper-gate preparation has a failed check.")
    if boundary.get("status") != (
        "PRECONTACT_QUALIFICATION_BOUNDARY_BRACKET_RESOLVED__NO_POSTCONTACT_MODEL"
    ):
        raise RuntimeError("A resolved precontact boundary is required.")

    alpha = float(upper_plan["alpha"])
    if alpha != float(preparation["compression_regularization_scale"]):
        raise RuntimeError("The upper plan and prepared state disagree on alpha.")
    if alpha != float(boundary["final_primary_bracket"]["upper_alpha_primary_pass"]):
        raise RuntimeError("The selected alpha is not the mapped upper gate.")
    if _sha256(STATE_PATH) != preparation["prepared_state_sha256"]:
        raise RuntimeError("The prepared-state archive drifted.")
    with np.load(STATE_PATH, allow_pickle=False) as archive:
        state = np.asarray(archive["state"], dtype=float)
        state_alpha = float(np.asarray(archive["compression_regularization_scale"])[0])
    if state.ndim != 1 or state.size == 0 or not np.all(np.isfinite(state)):
        raise RuntimeError("The frozen prepared state must be a finite nonempty vector.")
    if state_alpha != alpha:
        raise RuntimeError("The state archive carries the wrong alpha.")

    config_path = (CANDIDATE_ROOT / upper_plan["config_path"]).resolve()
    if _sha256(config_path) != preparation["config_sha256"]:
        raise RuntimeError("The admitted dynamic configuration drifted.")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    solver = config["solver"]
    hf = config["high_fidelity"]
    if float(hf["compression_regularization_scale"]) != alpha:
        raise RuntimeError("The dynamic configuration carries the wrong alpha.")
    if hf["contact_guard_enabled"] is not True:
        raise RuntimeError("Raw contact guards must remain enabled.")
    if config["run"]["claim_level"] != "OUT_OF_SCOPE":
        raise RuntimeError("The dynamic configuration must remain OUT_OF_SCOPE.")

    report = {
        "schema_version": "YPS-PRECONTACT-VALID-PREFIX-DYNAMIC-PLAN-1.0",
        "status": "EXACT_PRECONTACT_VALID_PREFIX_RUN_FROZEN_BEFORE_DYNAMICS",
        "git_head_at_freeze": _git_head(),
        "research_identity": "ALPHA_SPECIFIC_CONTACT_FREE_VALID_PREFIX_DYNAMIC",
        "model_id": hf["model_id"],
        "alpha": alpha,
        "prepared_state_archive_path": str(STATE_PATH.relative_to(CANDIDATE_ROOT)),
        "prepared_state_dimension": int(state.size),
        "config_path": str(config_path.relative_to(CANDIDATE_ROOT)),
        "output_root": str(OUTPUT_ROOT.relative_to(CANDIDATE_ROOT)),
        "result_path": str(RESULT_PATH.relative_to(CANDIDATE_ROOT)),
        "integration_contract": {
            "t_end_s": float(solver["t_end"]),
            "output_dt_s": float(solver["output_dt"]),
            "max_step_s": float(solver["max_step"]),
            "method": solver["method"],
            "rtol": float(solver["rtol"]),
            "raw_formal_guard_action": "terminate at first bracketed zero event",
            "postcontact_continuation": False,
            "contact_force_model": None,
            "impact_model": None,
            "friction_model": None,
        },
        "candidate_guard_diagnostic": {
            "contract": "complete frozen 11-component guard v2",
            "sampling": "presentation grid from t=0 until first sampled failure",
            "continuous_certificate": False,
            "failure_action": "stop candidate qualification interpretation",
        },
        "bindings": {
            "upper_gate_plan_sha256": _sha256(UPPER_PLAN_PATH),
            "upper_gate_result_sha256": _sha256(UPPER_RESULT_PATH),
            "prepared_state_archive_sha256": _sha256(STATE_PATH),
            "boundary_results_sha256": _sha256(BOUNDARY_RESULTS_PATH),
            "config_sha256": _sha256(config_path),
            "guard_spec_sha256": _sha256(GUARD_SPEC_PATH),
            "guard_implementation_sha256": _sha256(GUARD_IMPLEMENTATION_PATH),
            "runner_sha256": _sha256(RUNNER_PATH),
            "freeze_script_sha256": _sha256(SCRIPT_PATH),
            "formal_python_tree_sha256": _tree_sha256(builder.FORMAL_SOURCE_ROOT),
            "overlay_python_tree_sha256": _tree_sha256(OVERLAY_SOURCE),
        },
        "declared_command": (
            "PYTHONPATH=<frozen-overlay>/src .venv/bin/python "
            "compression_limit/run_precontact_valid_prefix_dynamics.py"
        ),
        "dynamic_run_count_at_freeze": 0,
        "formal_change_authorized": False,
        "claim_boundary": (
            "This plan admits one exact prepared state to one contact-free raw "
            "valid-prefix run. A raw event terminates the model; candidate-v2 "
            "checks on the presentation grid are discrete diagnostics, not a "
            "continuous guard certificate or a post-contact model."
        ),
    }
    builder.write_json(PLAN_PATH, report)
    return report


def main() -> int:
    report = freeze()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

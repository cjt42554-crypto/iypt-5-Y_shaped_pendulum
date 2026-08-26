#!/usr/bin/env python3
"""Freeze the lowest sampled qualified precontact preparation cross-check."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

SCRIPT_PATH = Path(__file__).resolve()
COMPRESSION_ROOT = SCRIPT_PATH.parent
CANDIDATE_ROOT = COMPRESSION_ROOT.parent
REPOSITORY_ROOT = CANDIDATE_ROOT.parents[2]
BOUNDARY_RESULTS_PATH = COMPRESSION_ROOT / "precontact_boundary_results.json"
BOUNDARY_SPEC_PATH = COMPRESSION_ROOT / "precontact_boundary_spec.json"
BOUNDARY_PREFREEZE_PATH = COMPRESSION_ROOT / "precontact_boundary_prefreeze.json"
WORKER_PATH = COMPRESSION_ROOT / "alpha_specific_preparation_worker.py"
HESSIAN_SPEC_PATH = COMPRESSION_ROOT / "hessian_crosscheck_spec.json"
GUARD_SPEC_PATH = CANDIDATE_ROOT / "guard_contract_v2" / "full_spec.json"
GUARD_IMPLEMENTATION_PATH = CANDIDATE_ROOT / "guard_contract_v2_full.py"
BUILDER_PATH = COMPRESSION_ROOT / "build_alpha_specific_candidate.py"
PLAN_PATH = COMPRESSION_ROOT / "precontact_upper_gate_plan.json"
OUTPUT_DIRECTORY = COMPRESSION_ROOT / "precontact_upper_gate"
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


builder = _load_module(BUILDER_PATH, "precontact_upper_gate_builder")


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
        raise RuntimeError("The precontact upper-gate plan is already frozen.")
    if OUTPUT_DIRECTORY.exists():
        raise RuntimeError("The precontact upper-gate output already exists.")
    boundary = json.loads(BOUNDARY_RESULTS_PATH.read_text(encoding="utf-8"))
    if boundary["status"] != (
        "PRECONTACT_QUALIFICATION_BOUNDARY_BRACKET_RESOLVED__NO_POSTCONTACT_MODEL"
    ):
        raise RuntimeError("A resolved precontact boundary is required.")
    alpha = float(
        boundary["final_primary_bracket"]["upper_alpha_primary_pass"]
    )
    matches = [
        sample for sample in boundary["samples"] if float(sample["alpha"]) == alpha
    ]
    if len(matches) != 1:
        raise RuntimeError("The upper qualified boundary sample is not unique.")
    sample = matches[0]
    if sample["primary_pass"] is not True or sample["qualified_candidate_count"] < 1:
        raise RuntimeError("The selected upper boundary sample is not qualified.")
    config_path = Path(sample["config"]["path"]).resolve()
    if _sha256(config_path) != sample["config"]["sha256"]:
        raise RuntimeError("The generated upper-boundary config drifted.")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if float(config["high_fidelity"]["compression_regularization_scale"]) != alpha:
        raise RuntimeError("The upper-boundary config carries the wrong alpha.")
    if not OVERLAY_SOURCE.is_dir():
        raise RuntimeError("The frozen precontact alpha overlay is absent.")
    report = {
        "schema_version": "YPS-PRECONTACT-UPPER-GATE-PLAN-1.0",
        "status": "LOWEST_SAMPLED_QUALIFIED_PREPARATION_FROZEN_BEFORE_CROSSCHECK",
        "git_head_at_freeze": _git_head(),
        "research_identity": "ALPHA_SPECIFIC_HELD_EQUILIBRIUM_PRECONTACT_UPPER_GATE",
        "alpha": alpha,
        "selection_identity": (
            "lowest sampled alpha passing the frozen complete candidate guard in "
            "the completed precontact boundary map"
        ),
        "config_path": str(config_path.relative_to(CANDIDATE_ROOT)),
        "output_directory": str(OUTPUT_DIRECTORY.relative_to(CANDIDATE_ROOT)),
        "bindings": {
            "boundary_results_sha256": _sha256(BOUNDARY_RESULTS_PATH),
            "boundary_spec_sha256": _sha256(BOUNDARY_SPEC_PATH),
            "boundary_prefreeze_sha256": _sha256(BOUNDARY_PREFREEZE_PATH),
            "config_sha256": _sha256(config_path),
            "worker_sha256": _sha256(WORKER_PATH),
            "hessian_spec_sha256": _sha256(HESSIAN_SPEC_PATH),
            "guard_spec_sha256": _sha256(GUARD_SPEC_PATH),
            "guard_implementation_sha256": _sha256(GUARD_IMPLEMENTATION_PATH),
            "freeze_script_sha256": _sha256(SCRIPT_PATH),
            "formal_python_tree_sha256": _tree_sha256(builder.FORMAL_SOURCE_ROOT),
            "overlay_python_tree_sha256": _tree_sha256(OVERLAY_SOURCE),
        },
        "declared_command": (
            "PYTHONPATH=<frozen-overlay>/src .venv/bin/python "
            "compression_limit/alpha_specific_preparation_worker.py "
            "--config <frozen-generated-config> --output-directory "
            "compression_limit/precontact_upper_gate"
        ),
        "required_checks": [
            "configured force residual",
            "lowest-energy stable candidate selection",
            "all formal raw guards positive",
            "complete frozen candidate guard v2",
            "three-step 240-dimensional gradient Hessian spectra",
            "independent energy directional curvatures",
            "finite prepared state"
        ],
        "dynamic_run_count_at_freeze": 0,
        "formal_change_authorized": False,
        "next_gate": (
            "Only a passing cross-check may admit this exact prepared-state hash "
            "to a separately frozen valid-prefix dynamic run."
        ),
        "claim_boundary": (
            "This gate qualifies at most one prepared state for a later dynamic "
            "gate. It is not a trajectory, post-contact model or compression limit."
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

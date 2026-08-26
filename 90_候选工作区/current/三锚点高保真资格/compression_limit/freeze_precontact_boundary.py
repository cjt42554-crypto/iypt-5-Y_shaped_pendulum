#!/usr/bin/env python3
"""Freeze the precontact alpha-boundary map before intermediate samples exist."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
COMPRESSION_ROOT = SCRIPT_PATH.parent
CANDIDATE_ROOT = COMPRESSION_ROOT.parent
REPOSITORY_ROOT = CANDIDATE_ROOT.parents[2]
RUNNER_PATH = COMPRESSION_ROOT / "run_precontact_boundary_map.py"
BUILDER_PATH = COMPRESSION_ROOT / "build_alpha_specific_candidate.py"
MAP_SPEC_PATH = COMPRESSION_ROOT / "precontact_boundary_spec.json"
GUARD_IMPLEMENTATION_PATH = CANDIDATE_ROOT / "guard_contract_v2_full.py"
GUARD_SPEC_PATH = CANDIDATE_ROOT / "guard_contract_v2" / "full_spec.json"
TEST_PATH = CANDIDATE_ROOT / "tests" / "test_precontact_boundary_map.py"
OUTPUT_PATH = COMPRESSION_ROOT / "precontact_boundary_prefreeze.json"
RESULTS_PATH = COMPRESSION_ROOT / "precontact_boundary_results.json"
GENERATED_ROOT = CANDIDATE_ROOT / "generated" / "precontact_alpha_boundary"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_module(RUNNER_PATH, "precontact_boundary_runner_for_freeze")
builder = _load_module(BUILDER_PATH, "precontact_boundary_builder_for_freeze")


def _sha256(path: Path) -> str:
    return builder.sha256_file(path)


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
    if OUTPUT_PATH.exists():
        raise RuntimeError("Precontact-boundary inputs are already frozen.")
    if RESULTS_PATH.exists():
        raise RuntimeError("Cannot freeze after precontact-boundary results exist.")
    if GENERATED_ROOT.exists():
        raise RuntimeError("Cannot freeze after generated precontact samples exist.")
    spec = json.loads(MAP_SPEC_PATH.read_text(encoding="utf-8"))
    runner.validate_map_spec(spec)
    builder.audit_formal_source()
    base_config = CANDIDATE_ROOT / spec["base_configuration"]
    paths = {
        "map_spec_sha256": MAP_SPEC_PATH,
        "run_script_sha256": RUNNER_PATH,
        "builder_sha256": BUILDER_PATH,
        "guard_implementation_sha256": GUARD_IMPLEMENTATION_PATH,
        "guard_spec_sha256": GUARD_SPEC_PATH,
        "base_config_sha256": base_config,
        "test_sha256": TEST_PATH,
        "freeze_script_sha256": SCRIPT_PATH,
    }
    report = {
        "schema_version": "YPS-PRECONTACT-ALPHA-BOUNDARY-PREFREEZE-1.0",
        "status": "PRECONTACT_BOUNDARY_INPUTS_FROZEN_BEFORE_INTERMEDIATE_ALPHA_RESULTS",
        "git_head_at_freeze": _git_head(),
        "research_identity": spec["research_identity"],
        "bindings": {name: _sha256(path) for name, path in paths.items()},
        "formal_python_tree_sha256": runner._tree_sha256(builder.FORMAL_SOURCE_ROOT),
        "expected_formal_git_blobs": dict(builder.EXPECTED_FORMAL_GIT_BLOBS),
        "alpha_bracket": spec["alpha_bracket"],
        "sampling": spec["sampling"],
        "declared_test_command": (
            ".venv/bin/python -m pytest -q tests/test_precontact_boundary_map.py"
        ),
        "new_boundary_alpha_sample_count_at_freeze": 0,
        "dynamic_run_count_at_freeze": 0,
        "formal_change_authorized": False,
        "next_gate": (
            "Run only the frozen independent alpha preparations and geometric-mean "
            "bisection. Stop without dynamics or a post-contact model."
        ),
        "claim_boundary": spec["claim_boundary"],
    }
    builder.write_json(OUTPUT_PATH, report)
    return report


def main() -> int:
    report = freeze()
    print(
        json.dumps(
            {
                "status": report["status"],
                "git_head_at_freeze": report["git_head_at_freeze"],
                "new_boundary_alpha_sample_count_at_freeze": report[
                    "new_boundary_alpha_sample_count_at_freeze"
                ],
                "dynamic_run_count_at_freeze": report[
                    "dynamic_run_count_at_freeze"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

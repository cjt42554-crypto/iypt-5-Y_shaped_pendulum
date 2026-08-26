#!/usr/bin/env python3
"""Freeze the complete candidate guard-v2 inputs before live preparations."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import build_qualification_configs as builder
import guard_contract_v2_full as full_v2


SCRIPT_PATH = Path(__file__).resolve()
ROOT = SCRIPT_PATH.parent
SPEC_PATH = ROOT / "guard_contract_v2" / "full_spec.json"
IMPLEMENTATION_PATH = ROOT / "guard_contract_v2_full.py"
TEST_PATH = ROOT / "tests" / "test_guard_contract_v2_full.py"
OUTPUT_PATH = ROOT / "guard_contract_v2" / "prefreeze.json"


def git_head() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=builder.REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def freeze() -> dict[str, Any]:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    threshold = full_v2.validate_spec(spec)
    source_paths = {
        "formal_model_py_sha256": (
            builder.HF_SOURCE_ROOT / "ypendulum" / "hf" / "model.py"
        ),
        "formal_reference_py_sha256": (
            builder.HF_SOURCE_ROOT / "ypendulum" / "hf" / "reference.py"
        ),
        "formal_solver_py_sha256": (
            builder.HF_SOURCE_ROOT / "ypendulum" / "hf" / "solver.py"
        ),
        "formal_config_validation_py_sha256": (
            builder.HF_SOURCE_ROOT
            / "ypendulum"
            / "config"
            / "validation.py"
        ),
    }
    source_checks = {
        key: full_v2.sha256_file(path) == spec["source_binding"][key]
        for key, path in source_paths.items()
    }
    if not all(source_checks.values()):
        raise RuntimeError(f"Formal source drift before guard-v2 freeze: {source_checks}")
    report = {
        "schema_version": "YPS-HF-GUARD-FULL-CANDIDATE-PREFREEZE-1.0",
        "status": "FULL_COMPONENT_CONTRACT_AND_TESTS_FROZEN_BEFORE_LIVE_RESULTS",
        "git_head_at_freeze": git_head(),
        "minimum_normalized_margin": threshold,
        "strict_comparison": True,
        "component_count": len(full_v2.COMPONENT_NAMES),
        "component_names": list(full_v2.COMPONENT_NAMES),
        "spec_path": str(SPEC_PATH.relative_to(ROOT)),
        "spec_sha256": full_v2.sha256_file(SPEC_PATH),
        "spec_canonical_sha256": full_v2.canonical_sha256(spec),
        "implementation_path": str(IMPLEMENTATION_PATH.relative_to(ROOT)),
        "implementation_sha256": full_v2.sha256_file(IMPLEMENTATION_PATH),
        "test_path": str(TEST_PATH.relative_to(ROOT)),
        "test_sha256": full_v2.sha256_file(TEST_PATH),
        "freeze_script_sha256": full_v2.sha256_file(SCRIPT_PATH),
        "formal_source_identity_checks": source_checks,
        "declared_test_command": (
            ".venv/bin/python -m pytest -q tests/test_guard_contract_v2_full.py"
        ),
        "new_alpha_preparation_count_at_freeze": 0,
        "historical_alpha1_mesh_reevaluation_count_at_freeze": 0,
        "physical_guard_domains_changed": False,
        "raw_zero_crossing_semantics_changed": False,
        "formal_change_authorized": False,
        "next_gate": (
            "Re-evaluate the already frozen alpha=1 three-level meshes under "
            "this exact contract, then run alpha-specific preparations without "
            "changing these frozen inputs."
        ),
        "claim_boundary": (
            "Freezing a complete candidate normalization and its tests is not "
            "a formal qualification result and does not authorize dynamics."
        ),
    }
    full_v2.write_json(OUTPUT_PATH, report)
    return report


def main() -> int:
    report = freeze()
    print(
        json.dumps(
            {
                "status": report["status"],
                "component_count": report["component_count"],
                "spec_sha256": report["spec_sha256"],
                "implementation_sha256": report["implementation_sha256"],
                "output": str(OUTPUT_PATH),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

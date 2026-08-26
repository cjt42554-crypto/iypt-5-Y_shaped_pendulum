#!/usr/bin/env python3
"""Build the isolated overlay and run the three alpha-specific preparations."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
COMPRESSION_ROOT = SCRIPT_PATH.parent
CANDIDATE_ROOT = COMPRESSION_ROOT.parent
REPOSITORY_ROOT = CANDIDATE_ROOT.parents[2]
BUILDER_PATH = COMPRESSION_ROOT / "build_alpha_specific_candidate.py"
WORKER_PATH = COMPRESSION_ROOT / "alpha_specific_preparation_worker.py"
HESSIAN_SPEC_PATH = COMPRESSION_ROOT / "hessian_crosscheck_spec.json"
RUNNER_TEST_PATH = (
    CANDIDATE_ROOT / "tests" / "test_alpha_specific_preparation_runner.py"
)
GUARD_SPEC_PATH = CANDIDATE_ROOT / "guard_contract_v2" / "full_spec.json"
GUARD_PREFREEZE_PATH = CANDIDATE_ROOT / "guard_contract_v2" / "prefreeze.json"
DEFAULT_OUTPUT_ROOT = (
    CANDIDATE_ROOT / "generated" / "alpha_specific_candidate"
)
PLAN_PATH = COMPRESSION_ROOT / "alpha_specific_preparation_run_plan.json"
SUMMARY_PATH = COMPRESSION_ROOT / "alpha_specific_preparation_results.json"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


alpha_builder = _load_module(BUILDER_PATH, "alpha_specific_overlay_builder")


def _sha256(path: Path) -> str:
    return alpha_builder.sha256_file(path)


def _python_source_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): _sha256(path)
        for path in sorted(root.rglob("*.py"))
        if path.is_file()
    }


def _formal_source_hashes() -> dict[str, str]:
    return _python_source_hashes(alpha_builder.FORMAL_SOURCE_ROOT)


def _frozen_candidate_hashes() -> dict[str, Any]:
    prefreeze = json.loads(GUARD_PREFREEZE_PATH.read_text(encoding="utf-8"))
    config_hashes = {
        path.name: _sha256(path)
        for path in sorted(
            (COMPRESSION_ROOT / "alpha_specific_configs").glob("*.yaml")
        )
    }
    return {
        "builder_sha256": _sha256(BUILDER_PATH),
        "worker_sha256": _sha256(WORKER_PATH),
        "orchestrator_sha256": _sha256(SCRIPT_PATH),
        "hessian_crosscheck_spec_sha256": _sha256(HESSIAN_SPEC_PATH),
        "preparation_runner_test_sha256": _sha256(RUNNER_TEST_PATH),
        "alpha_specific_protocol_sha256": _sha256(
            COMPRESSION_ROOT / "alpha_specific_protocol.json"
        ),
        "alpha_specific_prefreeze_plan_sha256": _sha256(
            COMPRESSION_ROOT / "alpha_specific_plan.json"
        ),
        "guard_full_spec_sha256": _sha256(GUARD_SPEC_PATH),
        "guard_full_implementation_sha256": _sha256(
            CANDIDATE_ROOT / "guard_contract_v2_full.py"
        ),
        "guard_full_test_sha256": _sha256(
            CANDIDATE_ROOT / "tests" / "test_guard_contract_v2_full.py"
        ),
        "guard_prefreeze_sha256": _sha256(GUARD_PREFREEZE_PATH),
        "guard_prefreeze_bindings_match": {
            "spec": _sha256(GUARD_SPEC_PATH) == prefreeze["spec_sha256"],
            "implementation": _sha256(
                CANDIDATE_ROOT / "guard_contract_v2_full.py"
            )
            == prefreeze["implementation_sha256"],
            "test": _sha256(
                CANDIDATE_ROOT / "tests" / "test_guard_contract_v2_full.py"
            )
            == prefreeze["test_sha256"],
        },
        "prefrozen_config_sha256": config_hashes,
    }


def _write_run_plan(
    output_root: Path,
    overlay_plan: dict[str, Any],
    frozen_hashes: dict[str, Any],
    formal_hashes: dict[str, str],
    overlay_hashes: dict[str, str],
) -> dict[str, Any]:
    bindings = frozen_hashes["guard_prefreeze_bindings_match"]
    if not all(bindings.values()):
        raise RuntimeError(f"Guard full-contract prefreeze drift: {bindings}")
    planned = [
        {
            "slug": record["slug"],
            "scale": record["scale"],
            "config_path": str(output_root / record["path"]),
            "config_sha256": record["sha256"],
            "output_directory": str(
                output_root / "preparations" / record["slug"]
            ),
        }
        for record in overlay_plan["configs"]
    ]
    plan = {
        "schema_version": "YPS-ALPHA-SPECIFIC-PREPARATION-RUN-PLAN-1.0",
        "status": "FROZEN_BEFORE_ALPHA_SPECIFIC_PREPARATIONS",
        "primary_preparation_identity": "ALPHA_SPECIFIC_HELD_EQUILIBRIUM",
        "cross_alpha_warm_start": False,
        "target_order": [item["scale"] for item in planned],
        "planned_preparation_count": len(planned),
        "completed_preparation_count_at_freeze": 0,
        "dynamic_run_count_at_freeze": 0,
        "frozen_candidate_hashes": frozen_hashes,
        "formal_python_source_hashes": formal_hashes,
        "overlay_python_source_hashes": overlay_hashes,
        "overlay_plan_sha256": _sha256(output_root / "plan.json"),
        "overlay_source_patch_audit": overlay_plan["source_patch_audit"],
        "targets": planned,
        "acceptance": [
            "isolated candidate config remains OUT_OF_SCOPE and validates",
            "versioned alpha-specific preparation protocol and mode are emitted",
            "free-material residual is no greater than the unchanged configured tolerance",
            "the lowest-energy accepted multi-seed stable candidate is selected",
            "all formal raw guards are strictly positive",
            "the frozen complete guard-v2 contract passes",
            "the frozen multi-step gradient-Hessian and independent energy-directional cross-check passes",
            "formal and overlay Python sources remain byte-stable"
        ],
        "formal_change_authorized": False,
        "claim_boundary": (
            "The plan authorizes only three isolated held preparations. No "
            "release trajectory may run unless every preparation passes."
        ),
    }
    alpha_builder.write_json(PLAN_PATH, plan)
    return plan


def run(output_root: Path) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    overlay_plan = alpha_builder.build(output_root)
    overlay_source = output_root / "overlay" / "src"
    formal_start = _formal_source_hashes()
    overlay_start = _python_source_hashes(overlay_source)
    frozen_start = _frozen_candidate_hashes()
    plan = _write_run_plan(
        output_root,
        overlay_plan,
        frozen_start,
        formal_start,
        overlay_start,
    )
    run_plan_hash_start = _sha256(PLAN_PATH)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(overlay_source),
            str(CANDIDATE_ROOT),
            environment.get("PYTHONPATH", ""),
        ]
    ).rstrip(os.pathsep)
    records: list[dict[str, Any]] = []
    for target in plan["targets"]:
        print(
            json.dumps(
                {
                    "phase": "START_ALPHA_SPECIFIC_PREPARATION",
                    "slug": target["slug"],
                    "scale": target["scale"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        output_directory = Path(target["output_directory"])
        completed = subprocess.run(
            [
                sys.executable,
                str(WORKER_PATH),
                "--config",
                target["config_path"],
                "--output-directory",
                str(output_directory),
                "--guard-spec",
                str(GUARD_SPEC_PATH),
                "--hessian-spec",
                str(HESSIAN_SPEC_PATH),
            ],
            check=False,
            cwd=CANDIDATE_ROOT,
            env=environment,
        )
        result_path = output_directory / "preparation_result.json"
        if result_path.exists():
            record = json.loads(result_path.read_text(encoding="utf-8"))
        else:
            record = {
                "schema_version": "YPS-ALPHA-SPECIFIC-PREPARATION-RESULT-1.0",
                "status": "ALPHA_SPECIFIC_WORKER_DID_NOT_EMIT_RESULT",
                "passed": False,
                "compression_regularization_scale": target["scale"],
                "worker_returncode": completed.returncode,
            }
        record["worker_returncode"] = completed.returncode
        record["slug"] = target["slug"]
        records.append(record)

    formal_end = _formal_source_hashes()
    overlay_end = _python_source_hashes(overlay_source)
    frozen_end = _frozen_candidate_hashes()
    identity_checks = {
        "formal_python_sources_stable": formal_start == formal_end,
        "overlay_python_sources_stable": overlay_start == overlay_end,
        "frozen_candidate_inputs_stable": frozen_start == frozen_end,
        "run_plan_stable": run_plan_hash_start == _sha256(PLAN_PATH),
    }
    all_passed = (
        len(records) == len(plan["targets"])
        and all(bool(record.get("passed")) for record in records)
        and all(identity_checks.values())
    )
    summary = {
        "schema_version": "YPS-ALPHA-SPECIFIC-PREPARATION-SUMMARY-1.0",
        "status": (
            "ALL_ALPHA_SPECIFIC_PREPARATIONS_PASS__DYNAMIC_GATE_OPEN_CANDIDATE_ONLY"
            if all_passed
            else "ALPHA_SPECIFIC_PREPARATION_NO_GO__DYNAMIC_GATE_CLOSED"
        ),
        "run_plan_sha256": _sha256(PLAN_PATH),
        "overlay_plan_sha256": _sha256(output_root / "plan.json"),
        "planned_preparation_count": len(plan["targets"]),
        "completed_preparation_count": len(records),
        "passed_preparation_count": sum(
            bool(record.get("passed")) for record in records
        ),
        "all_preparations_passed": all_passed,
        "dynamic_gate_open": all_passed,
        "dynamic_run_count": 0,
        "identity_checks": identity_checks,
        "formal_python_sources_start": formal_start,
        "formal_python_sources_end": formal_end,
        "overlay_python_sources_start": overlay_start,
        "overlay_python_sources_end": overlay_end,
        "frozen_candidate_hashes_start": frozen_start,
        "frozen_candidate_hashes_end": frozen_end,
        "preparations": records,
        "formal_change_authorized": False,
        "claim_boundary": (
            "Even if all preparations pass, the result only opens the isolated "
            "candidate dynamic gate. It does not establish a compression-limit "
            "trend, formal numerical qualification or physical validity."
        ),
    }
    alpha_builder.write_json(SUMMARY_PATH, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    summary = run(args.output_root)
    print(
        json.dumps(
            {
                "status": summary["status"],
                "completed_preparation_count": summary[
                    "completed_preparation_count"
                ],
                "passed_preparation_count": summary[
                    "passed_preparation_count"
                ],
                "dynamic_gate_open": summary["dynamic_gate_open"],
                "output": str(SUMMARY_PATH),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if summary["all_preparations_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

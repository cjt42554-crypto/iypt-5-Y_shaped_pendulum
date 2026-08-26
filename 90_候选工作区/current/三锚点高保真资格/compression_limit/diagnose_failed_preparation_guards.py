#!/usr/bin/env python3
"""Resolve raw guard components for rejected alpha-specific seed candidates."""

from __future__ import annotations

import argparse
import ast
import hashlib
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
BUILDER_PATH = COMPRESSION_ROOT / "build_alpha_specific_candidate.py"
PRIMARY_RESULTS_PATH = (
    COMPRESSION_ROOT / "alpha_specific_preparation_results.json"
)
PLAN_PATH = COMPRESSION_ROOT / "failed_preparation_guard_diagnostic_plan.json"
OUTPUT_PATH = COMPRESSION_ROOT / "failed_preparation_guard_diagnostic.json"
DEFAULT_OVERLAY_ROOT = (
    CANDIDATE_ROOT / "generated" / "failed_preparation_guard_diagnostic"
)

AUDIT_NEEDLE = '''            "guards_valid": guards_valid,
            "minimum_normalized_guard_margin": (
'''
AUDIT_REPLACEMENT = '''            "guards_valid": guards_valid,
            "guard_components_raw": {
                name: float(value)
                for name, value in sorted(guard_components.items())
            },
            "minimum_normalized_guard_margin": (
'''


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = _load_module(BUILDER_PATH, "failed_guard_diagnostic_builder")


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


def _parse_candidate_records(error: str) -> list[dict[str, Any]]:
    marker = "conservative minimum: "
    if marker not in error:
        raise RuntimeError("Preparation error does not contain candidate records.")
    value = ast.literal_eval(error.split(marker, 1)[1])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeError("Preparation candidate record payload is malformed.")
    return value


def _core_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "seed",
            "iterations",
            "energy_J",
            "free_material_residual_inf_N",
            "minimum_hessian_eigenvalue_N_per_m",
            "stability_audit_skipped_reason",
            "escaped_negative_curvature",
            "guards_valid",
            "minimum_normalized_guard_margin",
            "optimizer_messages",
            "accepted_stable_candidate",
        )
    }


def _diagnose_record(
    record: dict[str, Any], metadata: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    guards = record["guard_components_raw"]
    normalized = {
        name: float(value) / float(metadata[name]["scale"])
        for name, value in guards.items()
    }
    minimum_name = min(normalized, key=normalized.get)
    raw_nonpositive = {
        name: float(value)
        for name, value in guards.items()
        if not float(value) > 0.0
    }
    tolerance_failures = {
        name: {
            "raw_margin": float(value),
            "raw_tolerance": float(metadata[name]["tolerance"]),
        }
        for name, value in guards.items()
        if not float(value) > float(metadata[name]["tolerance"])
    }
    return {
        **_core_record(record),
        "minimum_v1_component": minimum_name,
        "minimum_v1_normalized_margin": normalized[minimum_name],
        "raw_nonpositive_components": raw_nonpositive,
        "formal_raw_tolerance_failures": tolerance_failures,
        "all_guard_components_raw": {
            name: float(value) for name, value in sorted(guards.items())
        },
    }


CHILD_CODE = r'''
import json
import sys
from pathlib import Path
from ypendulum.config import load_config, validate_physical_config
from ypendulum.hf import HighFidelityModel
from ypendulum.hf.solver import prepare_initial_state
path = Path(sys.argv[1]).resolve()
cfg = load_config(path)
validate_physical_config(cfg)
model = HighFidelityModel(cfg)
try:
    preparation = prepare_initial_state(cfg, model)
    result = {
        "unexpected_success": True,
        "preparation_mode": preparation.preparation_mode,
    }
except Exception as exc:
    result = {
        "unexpected_success": False,
        "error_type": type(exc).__name__,
        "error": str(exc),
        "guard_metadata": model.guard_component_metadata(),
    }
print(json.dumps(result, sort_keys=True, allow_nan=False))
'''


def run(output_root: Path) -> dict[str, Any]:
    primary = json.loads(PRIMARY_RESULTS_PATH.read_text(encoding="utf-8"))
    if primary["dynamic_gate_open"] is not False:
        raise RuntimeError("This diagnostic is only valid after a closed preparation gate.")
    output_root = output_root.expanduser().resolve()
    overlay_plan = builder.build(output_root)
    overlay_source = output_root / "overlay" / "src"
    solver_path = overlay_source / "ypendulum" / "hf" / "solver.py"
    text = solver_path.read_text(encoding="utf-8")
    if text.count(AUDIT_NEEDLE) != 1:
        raise RuntimeError("Diagnostic audit insertion is not an exact single match.")
    base_solver_sha256 = _sha256(solver_path)
    solver_path.write_text(
        text.replace(AUDIT_NEEDLE, AUDIT_REPLACEMENT, 1),
        encoding="utf-8",
    )
    compile(solver_path.read_text(encoding="utf-8"), str(solver_path), "exec")
    diagnostic_solver_sha256 = _sha256(solver_path)
    formal_tree_start = _tree_sha256(builder.FORMAL_SOURCE_ROOT)
    overlay_tree_start = _tree_sha256(overlay_source)
    targets = [
        {
            "slug": record["slug"],
            "scale": record["scale"],
            "config": str(output_root / record["path"]),
            "config_sha256": record["sha256"],
        }
        for record in overlay_plan["configs"]
    ]
    plan = {
        "schema_version": "YPS-FAILED-PREPARATION-GUARD-DIAGNOSTIC-PLAN-1.0",
        "status": "FROZEN_OBSERVATIONAL_AUDIT_BEFORE_DIAGNOSTIC_RERUN",
        "primary_results_sha256": _sha256(PRIMARY_RESULTS_PATH),
        "builder_sha256": _sha256(BUILDER_PATH),
        "diagnostic_script_sha256": _sha256(SCRIPT_PATH),
        "base_overlay_solver_sha256": base_solver_sha256,
        "diagnostic_overlay_solver_sha256": diagnostic_solver_sha256,
        "exact_single_insertion": True,
        "insertion_semantics": (
            "Add the already computed public raw guard dictionary to each rejected "
            "candidate record; do not alter objective, optimizer, residual, Hessian, "
            "guard decision, selection or exception behavior."
        ),
        "targets": targets,
        "planned_diagnostic_preparation_count": len(targets),
        "dynamic_run_count": 0,
        "formal_change_authorized": False,
    }
    builder.write_json(PLAN_PATH, plan)
    plan_sha256 = _sha256(PLAN_PATH)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(overlay_source), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    primary_by_slug = {
        item["slug"]: item for item in primary["preparations"]
    }
    results: list[dict[str, Any]] = []
    for target in targets:
        print(
            json.dumps(
                {
                    "phase": "START_FAILED_GUARD_DIAGNOSTIC",
                    "slug": target["slug"],
                    "scale": target["scale"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        completed = subprocess.run(
            [sys.executable, "-c", CHILD_CODE, target["config"]],
            check=False,
            capture_output=True,
            text=True,
            cwd=CANDIDATE_ROOT,
            env=environment,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Diagnostic child failed for {target['slug']}: {completed.stderr}"
            )
        payload = json.loads(completed.stdout)
        if payload["unexpected_success"]:
            raise RuntimeError(
                f"Diagnostic audit unexpectedly changed acceptance for {target['slug']}."
            )
        observed = _parse_candidate_records(payload["error"])
        original = _parse_candidate_records(primary_by_slug[target["slug"]]["error"])
        core_stable = [_core_record(item) for item in observed] == [
            _core_record(item) for item in original
        ]
        diagnosed = [
            _diagnose_record(item, payload["guard_metadata"])
            for item in observed
        ]
        result = {
            "slug": target["slug"],
            "compression_regularization_scale": target["scale"],
            "error_type": payload["error_type"],
            "candidate_core_records_match_primary_run": core_stable,
            "seed_candidate_count": len(diagnosed),
            "seeds": diagnosed,
            "raw_nonpositive_component_union": sorted(
                {
                    name
                    for item in diagnosed
                    for name in item["raw_nonpositive_components"]
                }
            ),
            "force_balanced_seed_count": sum(
                float(item["free_material_residual_inf_N"]) <= 1.0e-8
                for item in diagnosed
            ),
        }
        results.append(result)
        print(
            json.dumps(
                {
                    "slug": result["slug"],
                    "candidate_core_records_match_primary_run": core_stable,
                    "raw_nonpositive_component_union": result[
                        "raw_nonpositive_component_union"
                    ],
                    "force_balanced_seed_count": result[
                        "force_balanced_seed_count"
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
    identity_checks = {
        "formal_python_tree_stable": (
            formal_tree_start == _tree_sha256(builder.FORMAL_SOURCE_ROOT)
        ),
        "diagnostic_overlay_python_tree_stable": (
            overlay_tree_start == _tree_sha256(overlay_source)
        ),
        "diagnostic_plan_stable": plan_sha256 == _sha256(PLAN_PATH),
        "all_candidate_core_records_match_primary_run": all(
            item["candidate_core_records_match_primary_run"]
            for item in results
        ),
    }
    report = {
        "schema_version": "YPS-FAILED-PREPARATION-GUARD-DIAGNOSTIC-1.0",
        "status": (
            "FAILED_PREPARATION_RAW_GUARD_COMPONENTS_RESOLVED__DYNAMIC_GATE_REMAINS_CLOSED"
            if all(identity_checks.values())
            else "FAILED_PREPARATION_DIAGNOSTIC_IDENTITY_NO_GO"
        ),
        "plan_sha256": plan_sha256,
        "identity_checks": identity_checks,
        "results": results,
        "dynamic_gate_open": False,
        "dynamic_run_count": 0,
        "formal_change_authorized": False,
        "claim_boundary": (
            "This observational rerun only adds raw guard values to rejected seed "
            "records. It does not create an accepted preparation or relax any gate."
        ),
    }
    builder.write_json(OUTPUT_PATH, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OVERLAY_ROOT)
    args = parser.parse_args()
    report = run(args.output_root)
    print(
        json.dumps(
            {
                "status": report["status"],
                "identity_checks": report["identity_checks"],
                "output": str(OUTPUT_PATH),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if all(report["identity_checks"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())

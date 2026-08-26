#!/usr/bin/env python3
"""Re-evaluate the frozen alpha=1 three-anchor meshes under full guard v2."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import build_qualification_configs as builder
import guard_contract_v2_full as full_v2

from ypendulum.config import load_config, resolved_config_sha256
from ypendulum.hf import HighFidelityModel
from ypendulum.hf.solver import prepare_initial_state
from ypendulum.hf.validation import _space_configs
from ypendulum.io.provenance import source_hash


SCRIPT_PATH = Path(__file__).resolve()
ROOT = SCRIPT_PATH.parent
SPEC_PATH = ROOT / "guard_contract_v2" / "full_spec.json"
PREFREEZE_PATH = ROOT / "guard_contract_v2" / "prefreeze.json"
PLAN_PATH = ROOT / "guard_contract_v2" / "full_mesh_audit_plan.json"
DEFAULT_OUTPUT = ROOT / "guard_contract_v2" / "full_mesh_audit.json"
PACKAGE_ROOT = builder.HF_SOURCE_ROOT / "ypendulum"


def _frozen_identity() -> dict[str, str]:
    return {
        "full_spec_sha256": full_v2.sha256_file(SPEC_PATH),
        "full_implementation_sha256": full_v2.sha256_file(
            ROOT / "guard_contract_v2_full.py"
        ),
        "full_test_sha256": full_v2.sha256_file(
            ROOT / "tests" / "test_guard_contract_v2_full.py"
        ),
        "prefreeze_sha256": full_v2.sha256_file(PREFREEZE_PATH),
        "runner_sha256": full_v2.sha256_file(SCRIPT_PATH),
        "qualification_plan_sha256": full_v2.sha256_file(
            ROOT / "qualification_plan.json"
        ),
        "formal_source_sha256": source_hash(PACKAGE_ROOT),
    }


def _write_plan(identity: dict[str, str]) -> dict[str, Any]:
    plan = {
        "schema_version": "YPS-HF-GUARD-FULL-MESH-AUDIT-PLAN-1.0",
        "status": "FROZEN_BEFORE_ALPHA1_MESH_REEVALUATION",
        "contract_identity": identity,
        "anchor_order": ["4:3", "3:2", "2:1"],
        "level_meshes": [
            {"upper_A": 6, "upper_B": 6, "lower": 8},
            {"upper_A": 12, "upper_B": 12, "lower": 16},
            {"upper_A": 24, "upper_B": 24, "lower": 32},
        ],
        "planned_preparation_count": 9,
        "completed_preparation_count_at_freeze": 0,
        "compression_regularization_scale": 1.0,
        "dynamic_run_count": 0,
        "formal_change_authorized": False,
        "claim_boundary": (
            "The audit re-prepares the already frozen alpha=1 states and checks "
            "only prepared-state guard normalization. It cannot alter historical "
            "trajectory or spatial-Cauchy status."
        ),
    }
    full_v2.write_json(PLAN_PATH, plan)
    return plan


def _level_record(
    cfg: Any,
    anchor: str,
    level_index: int,
    spec: dict[str, Any],
) -> dict[str, Any]:
    start = time.monotonic()
    model = HighFidelityModel(cfg)
    preparation = prepare_initial_state(cfg, model)
    guard = full_v2.evaluate_prepared_state(model, preparation.state, spec)
    elapsed = time.monotonic() - start
    record = {
        "anchor": anchor,
        "level_index": level_index,
        "role": "finest_production" if level_index == 2 else "formal_coarse_trend",
        "mesh": {
            name: int(getattr(cfg.cables, name).elements)
            for name in ("upper_A", "upper_B", "lower")
        },
        "resolved_config_sha256": resolved_config_sha256(cfg),
        "compression_regularization_scale": float(
            model.compression_regularization_scale
        ),
        "preparation": {
            "mode": preparation.preparation_mode,
            "protocol": preparation.audit.get("protocol"),
            "force_residual_inf_N": float(preparation.residual_inf_N),
            "minimum_hessian_eigenvalue_N_per_m": preparation.audit.get(
                "minimum_hessian_eigenvalue_N_per_m"
            ),
            "hessian_tolerance_N_per_m": preparation.audit.get(
                "hessian_tolerance_N_per_m"
            ),
            "selected_seed": preparation.audit.get("selected_seed"),
            "seed_candidate_count": preparation.audit.get(
                "seed_candidate_count"
            ),
            "iterations": int(preparation.iterations),
        },
        "guard_v2_full": guard,
        "elapsed_wall_s": elapsed,
    }
    print(
        json.dumps(
            {
                "anchor": anchor,
                "level_index": level_index,
                "mesh": record["mesh"],
                "guard_status": guard["status"],
                "minimum_component": guard["minimum_component"],
                "minimum_normalized_margin": guard[
                    "minimum_normalized_margin"
                ],
                "elapsed_wall_s": elapsed,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return record


def run(output_path: Path) -> dict[str, Any]:
    prefreeze = json.loads(PREFREEZE_PATH.read_text(encoding="utf-8"))
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    full_v2.validate_spec(spec)
    identity_start = _frozen_identity()
    expected = {
        "full_spec_sha256": prefreeze["spec_sha256"],
        "full_implementation_sha256": prefreeze["implementation_sha256"],
        "full_test_sha256": prefreeze["test_sha256"],
    }
    checks = {
        name: identity_start[name] == digest
        for name, digest in expected.items()
    }
    if not all(checks.values()):
        raise RuntimeError(f"Guard-v2 prefreeze identity drift: {checks}")
    plan = _write_plan(identity_start)
    qualification = json.loads(
        (ROOT / "qualification_plan.json").read_text(encoding="utf-8")
    )
    records: list[dict[str, Any]] = []
    for anchor in qualification["anchors"]:
        base = load_config(ROOT / anchor["config"])
        for level_index, cfg in enumerate(_space_configs(base)):
            records.append(
                _level_record(cfg, anchor["anchor"], level_index, spec)
            )
    identity_end = _frozen_identity()
    stable = identity_start == identity_end
    if not stable:
        raise RuntimeError("Full guard-v2 mesh-audit identity changed during run.")
    all_passed = all(item["guard_v2_full"]["passed"] for item in records)
    minimum_record = min(
        records,
        key=lambda item: item["guard_v2_full"][
            "minimum_normalized_margin"
        ],
    )
    report = {
        "schema_version": "YPS-HF-GUARD-FULL-MESH-AUDIT-1.0",
        "status": (
            "FULL_CANDIDATE_GUARD_ALPHA1_PREPARED_MESH_AUDIT_PASS__HISTORICAL_HF_NO_GO_UNCHANGED"
            if all_passed
            else "FULL_CANDIDATE_GUARD_ALPHA1_PREPARED_MESH_AUDIT_FAIL__HISTORICAL_HF_NO_GO_UNCHANGED"
        ),
        "plan_sha256": full_v2.sha256_file(PLAN_PATH),
        "contract_identity_start": identity_start,
        "contract_identity_end": identity_end,
        "contract_identity_stable": stable,
        "planned_preparation_count": plan["planned_preparation_count"],
        "completed_preparation_count": len(records),
        "all_prepared_states_passed_full_candidate_guard": all_passed,
        "minimum_observed": {
            "anchor": minimum_record["anchor"],
            "level_index": minimum_record["level_index"],
            "mesh": minimum_record["mesh"],
            "component": minimum_record["guard_v2_full"][
                "minimum_component"
            ],
            "normalized_margin": minimum_record["guard_v2_full"][
                "minimum_normalized_margin"
            ],
        },
        "records": records,
        "historical_v1_status_preserved": (
            "ROOT_CAUSE_DIAGNOSTIC_COMPLETE__FORMAL_CHANGE_NOT_AUTHORIZED"
        ),
        "historical_dynamic_qualification": (
            "HF_NUMERICAL_QUALIFICATION_NO_GO_UNCHANGED"
        ),
        "historical_space_cauchy_status": (
            "SPACE_CAUCHY_DIAGNOSTIC_NOT_DEMONSTRATED_UNCHANGED"
        ),
        "source_endpoint_probe_status": (
            "SOURCE_ENDPOINT_PROBE_INVALID_UNCHANGED"
        ),
        "dynamic_run_count": 0,
        "formal_change_authorized": False,
        "claim_boundary": (
            "This is a prepared-state audit of the complete candidate local-scale "
            "contract. It does not re-certify historical trajectories, repair the "
            "source endpoint probe, overturn spatial failures, establish numerical "
            "convergence, or validate the physical apparatus."
        ),
    }
    full_v2.write_json(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run(args.output.expanduser().resolve())
    print(
        json.dumps(
            {
                "status": report["status"],
                "completed_preparation_count": report[
                    "completed_preparation_count"
                ],
                "all_passed": report[
                    "all_prepared_states_passed_full_candidate_guard"
                ],
                "minimum_observed": report["minimum_observed"],
                "output": str(args.output),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

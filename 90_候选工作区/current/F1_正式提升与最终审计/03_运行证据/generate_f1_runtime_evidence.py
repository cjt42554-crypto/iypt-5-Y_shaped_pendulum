#!/usr/bin/env python3
"""Build the F1 candidate audit summaries from already-generated run evidence.

This program never launches a numerical calculation.  It only reads the three
formal-A repeat directories and the two formal-S runtime evidence documents,
checks their closed-world invariants, and writes stable, sorted JSON summaries
beside this file (or to an explicitly selected output directory).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

EXPECTED_ATLAS_VERIFICATION_SHA256 = (
    "28683aa78759be4f5628f5e618de5fa17eff6dc37510dfa0d9e1f7a07eb2db08"
)
ATLAS_VERIFY_SCHEMA = "YPS-FORMAL-PATTERN-ATLAS-FULL-REPEAT-VERIFICATION-1.0"
STATIC_EVIDENCE_SCHEMA = "YPS-NO-CONTACT-STATIC-RUN-EVIDENCE-1.1"
ATLAS_AUDIT_SCHEMA = "YPS-F1-FORMAL-A-RUNTIME-AUDIT-1.0"
STATIC_MATRIX_SCHEMA = "YPS-F1-FORMAL-S-RUNTIME-MATRIX-1.0"
MASTER_SCHEMA = "YPS-F1-RUNTIME-EVIDENCE-STATUS-1.0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise TypeError(f"JSON root must be an object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def resolve_atlas_root(args: argparse.Namespace) -> Path:
    if args.atlas_root is not None:
        return args.atlas_root.resolve()
    root_file = args.atlas_root_file.resolve()
    require(root_file.is_file(), f"atlas root file is missing: {root_file}")
    lines = [line.strip() for line in root_file.read_text(encoding="utf-8").splitlines()]
    lines = [line for line in lines if line]
    require(len(lines) == 1, f"atlas root file must contain exactly one path: {root_file}")
    return Path(lines[0]).resolve()


def build_atlas_audit(
    atlas_root: Path,
    expected_verification_sha256: str,
) -> dict[str, Any]:
    verification_path = atlas_root / "full_repeat_verification.json"
    require(verification_path.is_file(), f"missing atlas verification: {verification_path}")
    verification_sha256 = sha256_file(verification_path)
    require(
        verification_sha256 == expected_verification_sha256,
        "atlas verification hash does not match the frozen accepted evidence",
    )
    verification = load_json(verification_path)
    require(verification.get("schema") == ATLAS_VERIFY_SCHEMA, "unexpected atlas schema")
    require(verification.get("repeat_count") == 3, "atlas must contain three repeats")
    require(
        verification.get("run_kind") == "FULL_16_CASE_48_PRIMARY_TRAJECTORY_MATRIX",
        "atlas run kind is not the frozen full matrix",
    )
    require(
        verification.get("byte_identical_across_all_repeats") is True,
        "atlas repeats are not declared byte-identical",
    )
    semantic = verification.get("semantic_checks", {})
    require(semantic.get("atlas_case_count") == 16, "atlas case count is not 16")
    require(
        semantic.get("primary_result_trajectory_count") == 48,
        "atlas primary trajectory count is not 48",
    )
    require(semantic.get("result_case_count") == 16, "atlas result case count is not 16")
    require(semantic.get("all_numerical_gates_passed") is True, "atlas gates did not pass")
    require(semantic.get("all_optimizer_states_converged") is True, "atlas optimizer state failed")

    reference_entries = verification.get("reference_artifact_hashes")
    require(isinstance(reference_entries, list), "atlas reference artifacts must be a list")
    require(len(reference_entries) == 9, "atlas reference artifact count is not 9")
    reference_hashes = {
        entry["path"]: entry["sha256"] for entry in reference_entries
    }
    require(len(reference_hashes) == 9, "atlas reference artifact paths are not unique")

    repeat_records: list[dict[str, Any]] = []
    for repeat_id in (1, 2, 3):
        repeat_dir = atlas_root / f"repeat-{repeat_id}"
        require(repeat_dir.is_dir(), f"missing atlas repeat directory: {repeat_dir}")
        actual_paths = sorted(
            str(path.relative_to(repeat_dir))
            for path in repeat_dir.rglob("*")
            if path.is_file()
        )
        require(actual_paths == sorted(reference_hashes), f"repeat {repeat_id} artifact set drift")
        artifacts: list[dict[str, Any]] = []
        for relative_path in sorted(reference_hashes):
            artifact = repeat_dir / relative_path
            actual_sha256 = sha256_file(artifact)
            require(
                actual_sha256 == reference_hashes[relative_path],
                f"repeat {repeat_id} hash drift: {relative_path}",
            )
            artifacts.append(
                {
                    "bytes": artifact.stat().st_size,
                    "path": relative_path,
                    "sha256": actual_sha256,
                }
            )

        run_evidence = load_json(repeat_dir / "atlas_run_evidence.json")
        require(
            run_evidence.get("run_kind")
            == "FULL_16_CASE_48_PRIMARY_TRAJECTORY_MATRIX",
            f"repeat {repeat_id} run kind drift",
        )
        execution = run_evidence.get("execution", {})
        require(execution.get("atlas_case_count") == 16, f"repeat {repeat_id} case count drift")
        require(
            execution.get("primary_result_trajectory_count") == 48,
            f"repeat {repeat_id} trajectory count drift",
        )
        require(
            run_evidence.get("diagnostics", {}).get("all_numerical_gates_passed") is True,
            f"repeat {repeat_id} numerical gates failed",
        )
        repeat_records.append(
            {
                "artifact_count": 9,
                "artifacts": artifacts,
                "atlas_case_count": 16,
                "byte_identity_against_repeat_1": "PASS",
                "primary_result_trajectory_count": 48,
                "repeat_id": repeat_id,
            }
        )

    first_run_evidence = load_json(atlas_root / "repeat-1" / "atlas_run_evidence.json")
    source_manifest = first_run_evidence["source_manifest"]
    tool = verification["verification_tool"]
    return {
        "accepted_evidence": {
            "byte_identical_across_all_repeats": True,
            "full_repeat_verification": {
                "bytes": verification_path.stat().st_size,
                "sha256": verification_sha256,
            },
            "repeat_count": 3,
            "repeat_matrix": repeat_records,
            "run_kind": verification["run_kind"],
            "semantic_checks": semantic,
        },
        "claim_limit": verification["conclusion_limit"],
        "formal_package_output_policy": {
            "candidate_audit_contains_summaries_only": True,
            "formal_pattern_atlas_contains_result_outputs": False,
            "repeat_output_directories_are_external_ephemeral_inputs": True,
        },
        "provenance": {
            "runtime_identity": source_manifest["runtime_identity"],
            "runtime_identity_sha256": source_manifest["runtime_identity_sha256"],
            "source_manifest_sha256": first_run_evidence["source_manifest_sha256"],
            "source_manifest_lock": first_run_evidence["source_manifest_lock"],
            "verification_tool": tool,
        },
        "schema": ATLAS_AUDIT_SCHEMA,
        "status": "PASS_IMPLEMENTATION_LEVEL_DETERMINISM_AND_IDEAL_MODEL_NUMERICAL_VALIDATION_ONLY",
    }


def comparable_static_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    comparable = copy.deepcopy(evidence)
    comparable.pop("runtime", None)
    comparable.pop("runtime_identity_sha256", None)
    return comparable


def build_static_matrix(current_path: Path, lower_path: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for runtime_id, path in (("current", current_path), ("lower_bound", lower_path)):
        path = path.resolve()
        require(path.is_file(), f"missing static evidence: {path}")
        evidence = load_json(path)
        require(evidence.get("schema") == STATIC_EVIDENCE_SCHEMA, "unexpected static schema")
        evidence_by_id[runtime_id] = evidence
        diagnostics = evidence.get("diagnostics", {})
        independent_checks = diagnostics.get("independent_checks", {})
        require(len(independent_checks) == 5, "static evidence must carry five diagnostics")
        require(all(value is True for value in independent_checks.values()), "static diagnostic failed")
        require(diagnostics.get("implementation_diagnostics_passed") is True, "static gates failed")
        optimizer = evidence.get("optimizer_state", {})
        require(optimizer.get("status_record_only") == 2, "static raw optimizer status drift")
        require(optimizer.get("success_record_only") is False, "static raw optimizer success drift")
        records.append(
            {
                "assembly_token": evidence["case_binding"]["assembly_token"],
                "complete_evidence": {
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                },
                "five_independent_checks": independent_checks,
                "implementation_diagnostics_passed": True,
                "raw_optimizer_state": {
                    "message_record_only": optimizer["message_record_only"],
                    "status_record_only": 2,
                    "success_record_only": False,
                },
                "runtime": evidence["runtime"],
                "runtime_id": runtime_id,
                "runtime_identity_sha256": evidence["runtime_identity_sha256"],
                "seed_id": evidence["case_binding"]["seed_id"],
                "seed_sha256": evidence["case_binding"]["seed_sha256"],
                "source_manifest_sha256": evidence["source_manifest_sha256"],
            }
        )

    current = evidence_by_id["current"]
    lower = evidence_by_id["lower_bound"]
    comparable_current = comparable_static_evidence(current)
    comparable_lower = comparable_static_evidence(lower)
    require(
        comparable_current == comparable_lower,
        "static evidence differs outside runtime and runtime_identity_sha256",
    )
    require(
        current["source_manifest_sha256"] == lower["source_manifest_sha256"],
        "static source manifests differ",
    )
    require(
        current["case_binding"]["assembly_token"]
        == lower["case_binding"]["assembly_token"],
        "static assembly tokens differ",
    )
    require(
        current["case_binding"]["seed_sha256"] == lower["case_binding"]["seed_sha256"],
        "static seeds differ",
    )

    return {
        "claim_limit": current["claim_limit"],
        "cross_runtime_invariants": {
            "assembly_token_identical": True,
            "evidence_identical_after_removing_runtime_and_runtime_identity_sha256": True,
            "five_independent_diagnostics_identical_and_passed": True,
            "raw_optimizer_state_identical": True,
            "raw_optimizer_status_record_only": 2,
            "raw_optimizer_success_record_only": False,
            "seed_identical": True,
            "source_manifest_identical": True,
            "source_manifest_sha256": current["source_manifest_sha256"],
        },
        "formal_package_output_policy": {
            "candidate_audit_contains_summaries_only": True,
            "formal_static_package_contains_runtime_evidence": False,
            "runtime_evidence_documents_are_external_ephemeral_inputs": True,
        },
        "model_identity": current["model_identity"],
        "runtime_count": 2,
        "runtimes": records,
        "schema": STATIC_MATRIX_SCHEMA,
        "status": "PASS_FORMAL_STATIC_REFERENCE_IMPLEMENTATION_AND_TWO_RUNTIME_EVIDENCE_ONLY",
    }


def build_master(
    generator_path: Path,
    atlas_path: Path,
    static_path: Path,
) -> dict[str, Any]:
    return {
        "accepted_evidence": {
            "formal_a_runtime_audit": {
                "path": atlas_path.name,
                "sha256": sha256_file(atlas_path),
            },
            "formal_s_runtime_matrix": {
                "path": static_path.name,
                "sha256": sha256_file(static_path),
            },
        },
        "discarded_pre_result_attempts": [
            {
                "admissible_for_pass_evidence": False,
                "attempt": "formal-A clean installation with matplotlib 3.6.3 on CPython 3.12",
                "failure": "source build stopped before any result-bearing run because Python.h was unavailable",
                "included_in_accepted_inputs": False,
                "resolution": "freeze the installable formal runtime at matplotlib 3.8.4 before executing the accepted matrix",
                "stage": "environment_preflight_before_results",
            },
            {
                "admissible_for_pass_evidence": False,
                "attempt": "first formal-A complete pytest run while implementation was still being finalized",
                "failure": "3 failed and 14 passed: four schemas changed after the source lock was generated, so two smoke tests correctly reported hash_drift; one negative runtime test used schema-invalid 0.0.0 while expecting a later runtime-identity-drift rejection",
                "included_in_accepted_inputs": False,
                "resolution": "freeze the files, regenerate the source lock, change the negative runtime value to schema-valid but drifting 3.12.999, obtain 19 passed, then run three serialized full matrices in isolated directories",
                "stage": "source_lock_and_file_finalization_timing_race_before_results",
            },
        ],
        "generator": {
            "launches_numerical_calculations": False,
            "path": generator_path.name,
            "sha256": sha256_file(generator_path),
        },
        "overall_claim_limit": "HF_NUMERICAL_QUALIFICATION_NO_GO",
        "schema": MASTER_SCHEMA,
        "self_check": "PASS",
        "status": "F1_RUNTIME_EVIDENCE_CLOSED__STOP_AT_F1_FINAL_PRO_REVIEW",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    atlas_group = parser.add_mutually_exclusive_group()
    atlas_group.add_argument("--atlas-root", type=Path)
    atlas_group.add_argument(
        "--atlas-root-file",
        type=Path,
        default=Path("/tmp/yps-f1-atlas-full-root.txt"),
    )
    parser.add_argument(
        "--expected-atlas-verification-sha256",
        default=EXPECTED_ATLAS_VERIFICATION_SHA256,
    )
    parser.add_argument(
        "--static-current",
        type=Path,
        default=Path("/tmp/yps-f1-static-current-evidence.json"),
    )
    parser.add_argument(
        "--static-lower",
        type=Path,
        default=Path("/tmp/yps-f1-static-lower-evidence.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    atlas_root = resolve_atlas_root(args)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    atlas_audit = build_atlas_audit(
        atlas_root,
        args.expected_atlas_verification_sha256,
    )
    static_matrix = build_static_matrix(args.static_current, args.static_lower)
    atlas_path = output_dir / "formal_a_full_repeat_audit.json"
    static_path = output_dir / "formal_s_runtime_matrix.json"
    master_path = output_dir / "f1_runtime_evidence_status.json"
    write_json(atlas_path, atlas_audit)
    write_json(static_path, static_matrix)
    write_json(
        master_path,
        build_master(Path(__file__).resolve(), atlas_path, static_path),
    )

    require(load_json(atlas_path) == atlas_audit, "atlas output reload check failed")
    require(load_json(static_path) == static_matrix, "static output reload check failed")
    master = load_json(master_path)
    require(master.get("self_check") == "PASS", "master output reload check failed")
    require(
        master["accepted_evidence"]["formal_a_runtime_audit"]["sha256"]
        == sha256_file(atlas_path),
        "master atlas hash check failed",
    )
    require(
        master["accepted_evidence"]["formal_s_runtime_matrix"]["sha256"]
        == sha256_file(static_path),
        "master static hash check failed",
    )
    print(
        json.dumps(
            {
                "formal_a_full_repeat_audit_sha256": sha256_file(atlas_path),
                "formal_s_runtime_matrix_sha256": sha256_file(static_path),
                "f1_runtime_evidence_status_sha256": sha256_file(master_path),
                "self_check": "PASS",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build a compact, re-verifying summary of HF qualification diagnostics."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import build_qualification_configs as builder

from ypendulum.hf.certificate_io import read_hf_certificate_sidecar
from ypendulum.io.provenance import source_hash


SCRIPT_PATH = Path(__file__).resolve()
CANDIDATE_ROOT = SCRIPT_PATH.parent
PACKAGE_ROOT = builder.HF_SOURCE_ROOT / "ypendulum"
EMPTY_PYTHON_SOURCE_TREE_SHA256 = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)


def compact_continuous_guard(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    steps = value.get("step_certificates")
    if not isinstance(steps, list):
        return {
            "passed": value.get("passed"),
            "status": value.get("status"),
            "accepted_step_count": value.get("accepted_step_count"),
            "step_records_available": False,
        }
    status_counts = Counter(str(step.get("status")) for step in steps)
    first_failure = next(
        (step for step in steps if step.get("passed") is not True),
        None,
    )
    return {
        "passed": value.get("passed"),
        "status": value.get("status"),
        "minimum_normalized_guard_margin": value.get(
            "minimum_normalized_guard_margin"
        ),
        "accepted_step_count": value.get("accepted_step_count"),
        "serialized_step_record_count": len(steps),
        "step_status_counts": dict(sorted(status_counts.items())),
        "first_failure": first_failure,
    }


def summarize_direct_run(run_directory: Path) -> dict[str, Any]:
    sidecar = read_hf_certificate_sidecar(run_directory, require_full=False)
    certificate = sidecar["certificate"]
    summary = json.loads((run_directory / "summary.json").read_text(encoding="utf-8"))
    diagnostics = json.loads(
        (run_directory / "diagnostics.json").read_text(encoding="utf-8")
    )
    checks = certificate.get("checks") or {}
    identity_checks = certificate.get("identity_checks") or {}
    return {
        "evidence_state": "CERTIFICATE_RETURNED",
        "run_directory": str(run_directory.relative_to(CANDIDATE_ROOT)),
        "sidecar_sha256": builder.sha256_file(
            run_directory / "hf_single_bundle_certificate.json"
        ),
        "artifact_set_sha256": sidecar["artifact_set_sha256"],
        "bound_artifact_count": len(sidecar["artifacts"]),
        "bound_artifact_bytes": sum(item["bytes"] for item in sidecar["artifacts"]),
        "certificate_sha256": certificate["certificate_sha256"],
        "passed": certificate["passed"],
        "guard_domain_certified": certificate["guard_domain_certified"],
        "certification_level": certificate["certification_level"],
        "full_accuracy_spec_bound": certificate["full_accuracy_spec_bound"],
        "certified_status_pair": certificate["certified_status_pair"],
        "false_contract_checks": sorted(
            name for name, passed in checks.items() if passed is False
        ),
        "false_identity_checks": sorted(
            name for name, passed in identity_checks.items() if passed is False
        ),
        "contract_evaluation_error": certificate.get("contract_evaluation_error"),
        "continuous_guard_certificate": compact_continuous_guard(
            certificate.get("continuous_guard_certificate")
        ),
        "raw_summary": {
            key: summary.get(key)
            for key in (
                "physical_status",
                "numerical_status",
                "valid_interval_s",
                "minimum_signed_axial_force_N",
                "maximum_signed_axial_force_N",
                "max_abs_energy_balance_residual",
                "maximum_quaternion_norm_error",
                "accepted_integration_step_count",
                "event_count",
            )
        },
        "runtime": {
            "integration_runtime_seconds": diagnostics.get("runtime_seconds"),
            "postprocess_wall_seconds": diagnostics.get("postprocess_wall_seconds"),
            "preparation_force_residual_inf_N": diagnostics.get(
                "preparation_force_residual_inf_N"
            ),
            "preparation_iterations": diagnostics.get("preparation_iterations"),
        },
    }


def summarize_incomplete_certificate_attempt(
    attempt_path: Path,
    candidate_root: Path = CANDIDATE_ROOT,
) -> dict[str, Any]:
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    publication = attempt["publication"]
    target = candidate_root / publication["atomic_target"]
    staging = candidate_root / publication["staging_directory"]
    checkpoint = candidate_root / publication["integration_checkpoint"]
    if target.exists() or (staging / "hf_single_bundle_certificate.json").exists():
        raise ValueError("Incomplete certificate attempt publication state drifted.")
    verified_bytes = 0
    verified_files = 0
    for name, record in attempt["preserved_artifacts"].items():
        path = checkpoint if name == "integration_checkpoint" else staging / name
        if (
            path.stat().st_size != record["bytes"]
            or builder.sha256_file(path) != record["sha256"]
        ):
            raise ValueError(f"Incomplete certificate artifact drifted: {path}")
        verified_bytes += record["bytes"]
        verified_files += 1
    return {
        **attempt,
        "evidence_state": "CERTIFICATE_INCOMPLETE_EXTERNAL_SIGTERM",
        "attempt_record_path": str(attempt_path.relative_to(candidate_root)),
        "attempt_record_sha256": builder.sha256_file(attempt_path),
        "artifact_verification": {
            "passed": True,
            "verified_file_count": verified_files,
            "verified_file_bytes": verified_bytes,
        },
    }


def verify_spatial_artifacts(
    report: dict[str, Any],
    candidate_root: Path = CANDIDATE_ROOT,
) -> dict[str, Any]:
    relative_root = Path(report["artifact_directory"])
    if relative_root.is_absolute() or ".." in relative_root.parts:
        raise ValueError("Spatial artifact root is not a safe relative path.")
    artifact_root = (candidate_root / relative_root).resolve()
    if not artifact_root.is_relative_to(candidate_root.resolve()):
        raise ValueError("Spatial artifact root escapes the candidate directory.")
    records = report["candidate_artifacts"]
    expected_hashes = {level["config_sha256"] for level in report["levels"]}
    if set(records) != expected_hashes:
        raise ValueError("Spatial artifact config identities do not match report levels.")
    verified_files = 0
    verified_bytes = 0
    manifests: dict[str, Any] = {}
    for config_hash, record in sorted(records.items()):
        relative_candidate = Path(record["relative_directory"])
        if relative_candidate.is_absolute() or ".." in relative_candidate.parts:
            raise ValueError("Spatial candidate directory is not a safe relative path.")
        candidate = (artifact_root / relative_candidate).resolve()
        if not candidate.is_relative_to(artifact_root):
            raise ValueError("Spatial candidate directory escapes its artifact root.")
        manifest_path = candidate / "candidate_manifest.json"
        if (
            manifest_path.stat().st_size != record["candidate_manifest_bytes"]
            or builder.sha256_file(manifest_path)
            != record["candidate_manifest_sha256"]
        ):
            raise ValueError(f"Spatial candidate manifest drifted: {config_hash}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["config_sha256"] != config_hash:
            raise ValueError(f"Spatial candidate config identity drifted: {config_hash}")
        for item in manifest["files"]:
            relative_file = Path(item["path"])
            if relative_file.is_absolute() or ".." in relative_file.parts:
                raise ValueError("Spatial artifact file path is unsafe.")
            path = (candidate / relative_file).resolve()
            if not path.is_relative_to(candidate):
                raise ValueError("Spatial artifact file escapes its candidate directory.")
            if (
                path.stat().st_size != item["bytes"]
                or builder.sha256_file(path) != item["sha256"]
            ):
                raise ValueError(f"Spatial candidate artifact drifted: {path}")
            verified_files += 1
            verified_bytes += item["bytes"]
        manifests[config_hash] = {
            "relative_directory": record["relative_directory"],
            "candidate_manifest_sha256": record["candidate_manifest_sha256"],
            "candidate_manifest_bytes": record["candidate_manifest_bytes"],
        }
    return {
        "passed": True,
        "artifact_directory": str(relative_root),
        "verified_candidate_count": len(records),
        "verified_file_count": verified_files,
        "verified_file_bytes": verified_bytes,
        "candidate_manifests": manifests,
    }


def assess_spatial_source_provenance(
    report: dict[str, Any],
    frozen_source_sha256: str,
) -> dict[str, Any]:
    """Fail closed when a historical run hashed an empty source-tree path.

    The raw spatial reports are retained unchanged.  This assessment makes the
    defective outer probe explicit and records only what can still be checked
    now; a current matching hash cannot retroactively prove both run endpoints.
    """

    raw_hashes = [str(report["formal_hf_source_sha256"])]
    for level in report["levels"]:
        identity = level["identity"]
        raw_hashes.extend(
            (
                str(identity["source_sha256_start"]),
                str(identity["source_sha256_end"]),
            )
        )
    unique_raw_hashes = sorted(set(raw_hashes))
    direct_endpoint_verified = bool(raw_hashes) and all(
        value == frozen_source_sha256 for value in raw_hashes
    )
    empty_tree_probe_detected = bool(raw_hashes) and all(
        value == EMPTY_PYTHON_SOURCE_TREE_SHA256 for value in raw_hashes
    )
    current_source_sha256 = source_hash(PACKAGE_ROOT)
    if direct_endpoint_verified:
        status = "DIRECT_ENDPOINT_SOURCE_HASH_VERIFIED"
        temporal_stability: bool | None = True
    elif empty_tree_probe_detected:
        status = "RUN_ENDPOINT_SOURCE_HASH_NOT_DIRECTLY_VERIFIED__EMPTY_TREE_PROBE"
        temporal_stability = None
    else:
        status = "RUN_ENDPOINT_SOURCE_HASH_NOT_DIRECTLY_VERIFIED__UNEXPECTED_HASH"
        temporal_stability = None
    return {
        "status": status,
        "raw_probe_hashes": unique_raw_hashes,
        "raw_probe_detected_empty_python_tree": empty_tree_probe_detected,
        "raw_probe_matches_frozen_source": direct_endpoint_verified,
        "direct_run_endpoint_source_hash_verified": direct_endpoint_verified,
        "temporal_source_stability_during_spatial_run": temporal_stability,
        "current_formal_source_sha256_at_summary": current_source_sha256,
        "frozen_formal_source_sha256": frozen_source_sha256,
        "current_source_matches_frozen_plan": (
            current_source_sha256 == frozen_source_sha256
        ),
        "interpretation": (
            "The current formal source matches the frozen plan, but this does not "
            "retroactively establish both historical run endpoint hashes."
            if not direct_endpoint_verified
            else "Both historical run endpoint probes match the frozen source."
        ),
    }


def compact_spatial_report(
    report: dict[str, Any],
    frozen_source_sha256: str,
) -> dict[str, Any]:
    failed_metrics = sorted(
        metric
        for metric, check in report["formal_space_cauchy_gate"]["metrics"].items()
        if not (
            check["finest_threshold_passed"]
            and check["decreasing_or_at_floor"]
        )
    )
    source_provenance = assess_spatial_source_provenance(
        report, frozen_source_sha256
    )
    effective_identity_checks = dict(report["identity_checks"])
    if not source_provenance["direct_run_endpoint_source_hash_verified"]:
        effective_identity_checks["formal_source_stable"] = None
        effective_identity_checks["bundle_internal_identities_stable"] = None
    return {
        "anchor": report["anchor"],
        "qualification": report["qualification"],
        "passed": report["passed"],
        "identity_checks_as_recorded": report["identity_checks"],
        "effective_identity_checks": effective_identity_checks,
        "source_provenance_assessment": source_provenance,
        "levels": report["levels"],
        "coarse_to_middle": report["comparisons"]["coarse_to_middle"],
        "middle_to_fine": report["comparisons"]["middle_to_fine"],
        "formal_space_cauchy_gate_passed": report["formal_space_cauchy_gate"][
            "passed"
        ],
        "formal_event_stability_gate_passed": report[
            "formal_event_stability_gate"
        ]["passed"],
        "failed_cauchy_metrics": failed_metrics,
        "apparent_norm_tail_diagnostics": report[
            "apparent_norm_tail_diagnostics"
        ],
        "candidate_artifacts": report["candidate_artifacts"],
        "artifact_verification": verify_spatial_artifacts(report),
    }


def build(output_path: Path) -> dict[str, Any]:
    plan_path = CANDIDATE_ROOT / "qualification_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    frozen_source_sha256 = str(plan["formal_hf_source_sha256"])
    initial_path = CANDIDATE_ROOT / "results" / "initial_level_diagnostics.json"
    initial = json.loads(initial_path.read_text(encoding="utf-8"))
    direct_directory = CANDIDATE_ROOT / "generated" / "direct_runs" / "3to2"
    attempt_path = CANDIDATE_ROOT / "results" / "certificate_attempt.json"
    if direct_directory.is_dir():
        certificate_evidence = summarize_direct_run(direct_directory)
    elif attempt_path.is_file():
        certificate_evidence = summarize_incomplete_certificate_attempt(attempt_path)
    else:
        raise FileNotFoundError("Neither a returned certificate nor an attempt record exists.")
    spatial_reports: dict[str, Any] = {}
    missing_spatial: list[str] = []
    for slug in ("4to3", "3to2", "2to1"):
        path = CANDIDATE_ROOT / "results" / "spatial" / f"{slug}.json"
        if not path.is_file():
            missing_spatial.append(slug)
            continue
        spatial_reports[slug] = compact_spatial_report(
            json.loads(path.read_text(encoding="utf-8")),
            frozen_source_sha256,
        )
    complete = not missing_spatial
    certificate_complete = (
        certificate_evidence["evidence_state"] == "CERTIFICATE_RETURNED"
    )
    source_endpoint_probe_complete = complete and all(
        item["source_provenance_assessment"][
            "direct_run_endpoint_source_hash_verified"
        ]
        for item in spatial_reports.values()
    )
    status = "PARTIAL"
    if complete:
        status = "COMPLETE_DIAGNOSTIC_RETURN_SET"
        if not certificate_complete:
            status += "__CERTIFICATE_INCOMPLETE"
        if not source_endpoint_probe_complete:
            status += "__SOURCE_ENDPOINT_PROBE_INVALID"
    report = {
        "schema_version": "YPS-THREE-ANCHOR-HF-QUALIFICATION-SUMMARY-1.0",
        "status": status,
        "qualification": "HF_NUMERICAL_QUALIFICATION_NO_GO",
        "scope": (
            "three-anchor prepared-state audit, one 0.12 s single-bundle "
            "certificate attempt, and three-level 0.12 s spatial Cauchy diagnostics"
        ),
        "qualification_plan_sha256": builder.sha256_file(plan_path),
        "initial_level_diagnostics": {
            "path": str(initial_path.relative_to(CANDIDATE_ROOT)),
            "sha256": builder.sha256_file(initial_path),
            "formal_hf_source_stable": initial["formal_hf_source_stable"],
            "anchors": initial["anchors"],
        },
        "representative_certificate_evidence": certificate_evidence,
        "spatial_diagnostics": spatial_reports,
        "missing_spatial_diagnostics": missing_spatial,
        "spatial_source_endpoint_probe_complete": source_endpoint_probe_complete,
        "claim_boundary": (
            "NO-GO applies to HF numerical qualification. The 0.12 s diagnostics "
            "cannot establish long-window modal convergence, apparatus-level "
            "physical prediction, calibration, uncertainty propagation, or experiment."
        ),
    }
    builder.write_json(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=CANDIDATE_ROOT / "results" / "run_summary.json",
    )
    args = parser.parse_args()
    report = build(args.output.expanduser().resolve())
    print(
        json.dumps(
            {
                "status": report["status"],
                "qualification": report["qualification"],
                "spatial_anchor_count": len(report["spatial_diagnostics"]),
                "output": str(args.output.expanduser().resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["status"].startswith("COMPLETE_DIAGNOSTIC_RETURN_SET") else 2


if __name__ == "__main__":
    raise SystemExit(main())

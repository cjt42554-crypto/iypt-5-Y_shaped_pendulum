from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import build_qualification_configs as builder
import build_compression_limit_configs as compression
import guard_root_cause as guard
import initial_level_diagnostics as initial
import run_spatial_diagnostic as spatial
import summarize_qualification as summarizer

from ypendulum.config import load_config, validate_physical_config
from ypendulum.io.provenance import source_hash


def test_source_probe_targets_real_formal_package() -> None:
    expected = builder.HF_SOURCE_ROOT / "ypendulum"
    assert expected.is_dir()
    assert initial.PACKAGE_ROOT == expected
    assert spatial.PACKAGE_ROOT == expected
    assert summarizer.PACKAGE_ROOT == expected
    assert guard.PACKAGE_ROOT == expected
    assert compression.PACKAGE_ROOT == expected
    plan = __import__("json").loads(
        (ROOT / "qualification_plan.json").read_text(encoding="utf-8")
    )
    assert source_hash(expected) == plan["formal_hf_source_sha256"]


def test_materially_separated_argmin_resolves_active_constraint() -> None:
    result = guard.materially_separated_argmin(
        np.array([0.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
        np.array([0.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
        first_material_start=0.0,
        first_material_end=1.0,
        second_material_start=1.0,
        second_material_end=2.0,
        minimum_material_separation=1.25,
    )
    assert result["distance_m"] == pytest.approx(0.25, abs=1.0e-14)
    assert result["material_separation_m"] == pytest.approx(1.25, abs=1.0e-14)
    assert result["material_constraint_slack_m"] == pytest.approx(0.0, abs=1.0e-14)


def test_saved_guard_root_cause_is_local_and_fail_closed() -> None:
    import json

    report = json.loads(
        (ROOT / "results" / "guard_root_cause.json").read_text(encoding="utf-8")
    )
    assert report["status"] == (
        "ROOT_CAUSE_DIAGNOSTIC_COMPLETE__FORMAL_CHANGE_NOT_AUTHORIZED"
    )
    assert all(report["identity_checks"].values())
    assert report["required_normalized_guard_margin"] == pytest.approx(3.0e-4)
    for anchor in report["anchors"]:
        for level in anchor["levels"]:
            rod = level["rod_self_clearance"]
            winner = rod["same_branch"]["overall"]
            assert rod["winning_category"] == "SAME_BRANCH"
            assert winner["branch"] == "lower"
            assert winner["raw_guard_margin_m"] > 0.0
            assert rod["public_raw_guard_margin_m"] > 0.0
            assert rod["normalized_guard_margin"] < 3.0e-4
            assert winner["argmin"]["material_constraint_slack_m"] == pytest.approx(
                0.0, abs=2.0e-14
            )
            assert rod["cross_branch"]["overall"]["raw_guard_margin_m"] > (
                rod["public_raw_guard_margin_m"]
            )


def test_two_to_one_has_additional_positive_radial_guard_failure() -> None:
    import json

    report = json.loads(
        (ROOT / "results" / "guard_root_cause.json").read_text(encoding="utf-8")
    )
    two_to_one = next(item for item in report["anchors"] if item["slug"] == "2to1")
    for level in two_to_one["levels"]:
        failures = {item["guard"] for item in level["failed_guard_components"]}
        assert failures == {
            "BOB_SOCKET_RADIAL_MONOTONICITY",
            "ROD_SELF_CLEARANCE",
        }
        radial = level["bob_socket_radial_monotonicity"]
        assert radial["raw_guard_margin_m2"] > 0.0
        assert radial["threshold_passed"] is False
        assert radial["minimum_cell"]["radial_increment_cosine"] > 0.0


def test_compression_preflight_preserves_formal_preparation_boundary() -> None:
    import json

    report = json.loads(
        (ROOT / "compression_limit" / "preflight.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["status"] == "BLOCKED_PENDING_PREPARATION_PROTOCOL_DECISION"
    assert report["runnable_candidate_count"] == 0
    assert report["dynamic_run_count"] == 0
    assert all(report["identity_checks"].values())
    controlled = [
        item
        for item in report["config_preflight"]
        if 0.0 < item["scale"] < 1.0
    ]
    assert [item["scale"] for item in controlled] == [1.0e-2, 1.0e-4, 1.0e-6]
    assert all(
        item["rejection_code"] == "HF_HELD_PREPARATION_REQUIRES_BILATERAL_ROD"
        for item in controlled
    )
    chord = report["fixed_endpoint_chord_audit"]
    assert chord["branches_with_chord_shorter_than_rest_length"] == ["lower"]
    assert chord["geometric_direct_release_can_preserve_all_endpoints"] is False
    fixed = report["fixed_state_constitutive_audit"]
    assert fixed["all_instantaneous_kernel_crosschecks_passed"] is True
    snapshots = {item["scale"]: item for item in fixed["snapshots"]}
    assert snapshots[1.0]["branches"]["lower"]["negative_segment_count"] == 5
    assert snapshots[0.0]["branches"]["lower"]["negative_segment_count"] == 0
    assert snapshots[0.0]["branches"]["lower"]["nonpositive_segment_count"] == 5
    assert snapshots[0.0]["role"] == "mathematical_fixed_state_endpoint"


def test_empty_source_probe_is_fail_closed() -> None:
    report = {
        "formal_hf_source_sha256": summarizer.EMPTY_PYTHON_SOURCE_TREE_SHA256,
        "levels": [
            {
                "identity": {
                    "source_sha256_start": summarizer.EMPTY_PYTHON_SOURCE_TREE_SHA256,
                    "source_sha256_end": summarizer.EMPTY_PYTHON_SOURCE_TREE_SHA256,
                }
            }
        ],
    }
    frozen = source_hash(summarizer.PACKAGE_ROOT)
    assessment = summarizer.assess_spatial_source_provenance(report, frozen)
    assert assessment["raw_probe_detected_empty_python_tree"] is True
    assert assessment["direct_run_endpoint_source_hash_verified"] is False
    assert assessment["temporal_source_stability_during_spatial_run"] is None
    assert assessment["current_source_matches_frozen_plan"] is True


def test_frozen_configs_match_formal_target_and_space_levels(tmp_path: Path) -> None:
    plan = builder.build_all(tmp_path)
    assert plan["target_window_s"] == pytest.approx(0.12)
    assert plan["finest_mesh"] == {
        "upper_A": 24,
        "upper_B": 24,
        "lower": 32,
    }
    assert [item["anchor"] for item in plan["anchors"]] == ["4:3", "3:2", "2:1"]
    expected_levels = [
        {"upper_A": 6, "upper_B": 6, "lower": 8},
        {"upper_A": 12, "upper_B": 12, "lower": 16},
        {"upper_A": 24, "upper_B": 24, "lower": 32},
    ]
    for record in plan["anchors"]:
        assert record["space_mesh_levels"] == expected_levels
        assert record["formal_target"]["passed"] is True
        assert record["resource_estimate"]["estimated_peak_memory_bytes"] < 8 * 1024**3
        config = load_config(tmp_path / record["config"])
        validate_physical_config(config)
        assert config.solver.allow_subminimum_mesh is False
        assert config.solver.resolve_longitudinal_waves is True
        assert config.run.claim_level == "DERIVED"


def test_shared_input_audits_remain_complete(tmp_path: Path) -> None:
    builder.build_all(tmp_path)
    import json

    audits = json.loads((tmp_path / "shared_input_audits.json").read_text(encoding="utf-8"))
    for anchor in ("4:3", "3:2", "2:1"):
        assert audits[anchor]["passed"] is True
        assert audits[anchor]["check_count"] == 53


def test_apparent_tail_diagnostics_fail_closed_for_noncontraction() -> None:
    report = spatial.apparent_tail_diagnostics(
        {"contracting": 4.0, "growing": 1.0, "zero": 2.0},
        {"contracting": 2.0, "growing": 1.1, "zero": 0.0},
    )
    assert report["contracting"]["status"] == "CONTRACTING"
    assert report["contracting"]["apparent_order_base2"] == pytest.approx(1.0)
    assert report["contracting"]["estimated_remaining_fine_error_norm"] == pytest.approx(2.0)
    assert report["contracting"]["signed_field_extrapolation"] is None
    assert report["growing"]["status"] == "NONCONTRACTING"
    assert report["growing"]["estimated_remaining_fine_error_norm"] is None
    assert report["zero"]["status"] == "FINE_DIFFERENCE_ZERO"
    assert report["zero"]["estimated_remaining_fine_error_norm"] == 0.0


def test_continuous_guard_summary_keeps_first_failure_and_counts() -> None:
    compact = summarizer.compact_continuous_guard(
        {
            "passed": False,
            "status": "GUARD_VIOLATION",
            "minimum_normalized_guard_margin": 3.0e-4,
            "accepted_step_count": 3,
            "step_certificates": [
                {"passed": True, "status": "CERTIFIED_POSITIVE"},
                {
                    "passed": False,
                    "status": "GUARD_CROSSING_OR_TANGENCY_DETECTED",
                    "time_bracket_s": [0.1, 0.2],
                },
                {"passed": False, "status": "EVENT_UNRESOLVED"},
            ],
        }
    )
    assert compact is not None
    assert compact["serialized_step_record_count"] == 3
    assert compact["step_status_counts"] == {
        "CERTIFIED_POSITIVE": 1,
        "EVENT_UNRESOLVED": 1,
        "GUARD_CROSSING_OR_TANGENCY_DETECTED": 1,
    }
    assert compact["first_failure"]["time_bracket_s"] == [0.1, 0.2]


def test_spatial_report_numpy_scalars_convert_to_strict_json() -> None:
    import json
    import numpy as np

    converted = spatial.json_ready(
        {
            "passed": np.bool_(False),
            "count": np.int64(3),
            "values": (np.float64(1.25),),
        }
    )
    assert converted == {"passed": False, "count": 3, "values": [1.25]}
    assert json.loads(json.dumps(converted, allow_nan=False)) == converted


def test_spatial_artifact_verification_rehashes_manifest_files(tmp_path: Path) -> None:
    import json

    candidate = tmp_path / "generated" / "spatial" / "case" / "candidate_a"
    candidate.mkdir(parents=True)
    payload = candidate / "result.h5"
    payload.write_bytes(b"result")
    manifest = {
        "config_sha256": "a" * 64,
        "files": [
            {
                "path": "result.h5",
                "bytes": payload.stat().st_size,
                "sha256": builder.sha256_file(payload),
            }
        ],
    }
    manifest_path = candidate / "candidate_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = {
        "artifact_directory": "generated/spatial/case",
        "levels": [{"config_sha256": "a" * 64}],
        "candidate_artifacts": {
            "a" * 64: {
                "relative_directory": "candidate_a",
                "candidate_manifest_sha256": builder.sha256_file(manifest_path),
                "candidate_manifest_bytes": manifest_path.stat().st_size,
            }
        },
    }
    verified = summarizer.verify_spatial_artifacts(report, tmp_path)
    assert verified["passed"] is True
    assert verified["verified_candidate_count"] == 1
    assert verified["verified_file_count"] == 1
    payload.write_bytes(b"drift")
    with pytest.raises(ValueError, match="artifact drifted"):
        summarizer.verify_spatial_artifacts(report, tmp_path)


def test_incomplete_certificate_attempt_rehashes_preserved_files(
    tmp_path: Path,
) -> None:
    import json

    staging = tmp_path / "generated" / "direct_runs" / ".case.staging"
    staging.mkdir(parents=True)
    result = staging / "result.h5"
    result.write_bytes(b"raw")
    checkpoint = tmp_path / "generated" / "direct_runs" / ".case.checkpoint.npz"
    checkpoint.write_bytes(b"checkpoint")
    attempt = {
        "publication": {
            "atomic_target": "generated/direct_runs/case",
            "staging_directory": "generated/direct_runs/.case.staging",
            "integration_checkpoint": "generated/direct_runs/.case.checkpoint.npz",
        },
        "preserved_artifacts": {
            "integration_checkpoint": {
                "bytes": checkpoint.stat().st_size,
                "sha256": builder.sha256_file(checkpoint),
            },
            "result.h5": {
                "bytes": result.stat().st_size,
                "sha256": builder.sha256_file(result),
            },
        },
    }
    attempt_path = tmp_path / "attempt.json"
    attempt_path.write_text(json.dumps(attempt), encoding="utf-8")
    compact = summarizer.summarize_incomplete_certificate_attempt(
        attempt_path, tmp_path
    )
    assert compact["artifact_verification"] == {
        "passed": True,
        "verified_file_count": 2,
        "verified_file_bytes": len(b"raw") + len(b"checkpoint"),
    }
    result.write_bytes(b"drift")
    with pytest.raises(ValueError, match="artifact drifted"):
        summarizer.summarize_incomplete_certificate_attempt(attempt_path, tmp_path)

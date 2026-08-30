"""Fail-closed E0 file, contract, provenance and Git-scope checker."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

STAGE_RELATIVE = Path("90_候选工作区/current/E0_实验准备与数据合同")
ALLOWED_GOVERNANCE = {
    Path("90_候选工作区/交接说明_current.md"),
    Path("90_候选工作区/交接说明_history.md"),
}

EXPECTED_FILES = {
    Path(name)
    for name in (
        "README.md",
        "00_EXISTING_GATE_REUSE_MATRIX.md",
        "01_MEASUREMENT_REGISTER_PROTOCOL.md",
        "02_FIRST_ROUND_PREREGISTRATION.md",
        "03_CAMERA_TRAJECTORY_DATA_CONTRACT.md",
        "04_GEOMETRY_AND_PILOT_PROTOCOL.md",
        "05_ACCEPTANCE_MATRIX.md",
        "pyproject.toml",
        "schemas/apparatus_measurements.schema.json",
        "schemas/acquisition_attempts.schema.json",
        "schemas/material_test_manifest.schema.json",
        "schemas/camera_rig.schema.json",
        "schemas/experiment_run.schema.json",
        "schemas/detection_2d_bundle.schema.json",
        "schemas/trajectory_bundle.schema.json",
        "schemas/processed_observables.schema.json",
        "schemas/model_input_binding.schema.json",
        "schemas/comparison_result.schema.json",
        "templates/apparatus_measurements.template.json",
        "templates/material_test_manifest.template.json",
        "templates/camera_rig.template.json",
        "templates/first_round_plan.template.json",
        "templates/pilot_attempts.template.json",
        "templates/uncertainty_budget.template.csv",
        "templates/pilot_run_sheet.template.csv",
        "src/yps_experiment_pipeline/__init__.py",
        "src/yps_experiment_pipeline/__main__.py",
        "src/yps_experiment_pipeline/contracts.py",
        "src/yps_experiment_pipeline/camera.py",
        "src/yps_experiment_pipeline/detections.py",
        "src/yps_experiment_pipeline/synchronization.py",
        "src/yps_experiment_pipeline/trajectory.py",
        "src/yps_experiment_pipeline/observables.py",
        "src/yps_experiment_pipeline/forward_adapter.py",
        "src/yps_experiment_pipeline/comparison.py",
        "src/yps_experiment_pipeline/cli.py",
        "tests/fixtures/synthetic_stereo_session/fixture_manifest.json",
        "tests/fixtures/synthetic_real_shape_session/fixture_manifest.json",
        "tests/real_shape_fixture.py",
        "tests/test_contracts.py",
        "tests/test_camera_and_sync.py",
        "tests/test_trajectory_reconstruction.py",
        "tests/test_observables.py",
        "tests/test_forward_adapter.py",
        "tests/test_comparison.py",
        "tests/test_no_fake_measurements.py",
        "tests/test_real_shape_end_to_end.py",
        "tools/check_stage.py",
    )
}


def fail(message: str) -> None:
    raise RuntimeError(message)


def tracked_stage_files(stage_root: Path) -> set[Path]:
    ignored_parts = {"__pycache__", ".pytest_cache", ".ruff_cache", "build", "dist"}
    result = set()
    for path in stage_root.rglob("*"):
        if (
            not path.is_file()
            or any(part in ignored_parts for part in path.parts)
            or any(part.endswith(".egg-info") for part in path.parts)
        ):
            continue
        if path.suffix == ".pyc":
            continue
        result.add(path.relative_to(stage_root))
    return result


def git_changed_paths(repository_root: Path) -> list[Path]:
    commands = (
        ["git", "diff", "--name-only", "-z"],
        ["git", "diff", "--cached", "--name-only", "-z"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    )
    paths: set[Path] = set()
    for command in commands:
        output = subprocess.check_output(command, cwd=repository_root)
        paths.update(Path(raw.decode("utf-8")) for raw in output.split(b"\0") if raw)
    return sorted(paths, key=lambda path: path.as_posix())


def check_csv_templates(template_root: Path) -> None:
    with (template_root / "uncertainty_budget.template.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 8 or any(row["status"] != "NOT_MEASURED" for row in rows):
        fail("uncertainty budget must contain eight unmeasured source rows")
    if any(row["standard_uncertainty_si"] for row in rows):
        fail("uncertainty template contains fabricated numeric uncertainty")
    with (template_root / "pilot_run_sheet.template.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        pilot = list(csv.DictReader(handle))
    expected_slots = [
        "P00",
        "P01",
        "P01",
        "P02",
        "P02",
        "P03",
        "P03",
        "P04",
        "P04",
        "P05",
        "P05",
        "P06",
    ]
    if [row["slot_id"] for row in pilot] != expected_slots:
        fail("pilot CSV must contain every preregistered repeat in execution order")
    if len({row["attempt_id"] for row in pilot}) != len(pilot):
        fail("pilot CSV attempt IDs must be unique")
    if any(row["status"] != "NOT_RUN" for row in pilot):
        fail("pilot template contains an executed run")
    if any(row["apparatus_revision"] != "UNSET_REQUIRES_HUMAN" for row in pilot):
        fail("pilot template contains an apparatus claim")
    completion_fields = {
        "started_at",
        "ended_at",
        "operator_id",
        "failure_stage",
        "reason_code",
        "operator_note",
        "raw_file_hashes",
        "retry_parent_id",
        "corrective_action",
        "camera_rig_sha256",
    }
    if any(row[field] for row in pilot for field in completion_fields):
        fail("unexecuted pilot CSV contains completion or retry evidence")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    stage_root = repository_root / STAGE_RELATIVE
    sys.path.insert(0, str(stage_root / "src"))
    from yps_experiment_pipeline.contracts import (
        SCHEMA_ROOT,
        TEMPLATE_ROOT,
        assert_templates_are_human_unset,
        load_json,
        load_schema,
        validate_all_templates,
    )
    from yps_experiment_pipeline.forward_adapter import formal_identity

    actual = tracked_stage_files(stage_root)
    if actual != EXPECTED_FILES:
        fail(
            "E0 file closure mismatch; missing="
            f"{sorted(EXPECTED_FILES - actual, key=str)} extra={sorted(actual - EXPECTED_FILES, key=str)}"
        )

    for schema_path in sorted(SCHEMA_ROOT.glob("*.schema.json")):
        load_schema(schema_path.name)
    validate_all_templates()
    assert_templates_are_human_unset()
    check_csv_templates(TEMPLATE_ROOT)

    first_round = load_json(TEMPLATE_ROOT / "first_round_plan.template.json")
    if sum(item["planned_runs"] for item in first_round["run_families"]) != 70:
        fail("first-round plan does not close to 70 result runs")
    registry = first_round["run_registry"]
    if len(registry) != 70:
        fail("first-round run registry does not contain exactly 70 entries")
    if len({item["run_id"] for item in registry}) != 70:
        fail("first-round run IDs are not unique")
    if len({item["attempt_id"] for item in registry}) != 70:
        fail("first-round attempt IDs are not unique")
    family_counts = {
        family["family_id"]: family["planned_runs"] for family in first_round["run_families"]
    }
    registry_counts = {
        family_id: sum(item["family_id"] == family_id for item in registry)
        for family_id in family_counts
    }
    if registry_counts != family_counts:
        fail("first-round run registry does not match family totals")
    level_counts = {
        family["family_id"]: family["amplitude_level_count"]
        for family in first_round["run_families"]
    }
    expected_amplitudes = {
        "F01": [(0.05, 0.0)],
        "F02": [(0.0, 0.04)],
        "F03": [(0.05, 0.0)],
        "F04": [(0.0, 0.04)],
        "F05": [(0.05, 0.0)],
        "F06": [(0.0, 0.04)],
        "F07": [(0.05, 0.04), (0.10, 0.08), (0.15, 0.10), (0.20, 0.12)],
        "F08": [(0.05, 0.04), (0.10, 0.08)],
        "F09": [(0.05, 0.04), (0.10, 0.08)],
    }
    for family in first_round["run_families"]:
        family_id = family["family_id"]
        levels = family["amplitude_levels"]
        if len(levels) != family["amplitude_level_count"]:
            fail(f"{family_id} amplitude level count does not match its frozen definitions")
        if [level["level_index"] for level in levels] != list(range(1, len(levels) + 1)):
            fail(f"{family_id} amplitude level indices are not contiguous")
        if [level["release_target_id"] for level in levels] != [
            f"{family_id}_L{index:02d}" for index in range(1, len(levels) + 1)
        ]:
            fail(f"{family_id} release target IDs are not deterministic")
        actual = [(level["target_fast_rad"], level["target_slow_rad"]) for level in levels]
        if actual != expected_amplitudes[family_id]:
            fail(f"{family_id} release amplitudes differ from the frozen first-round matrix")
        if family["actual_initial_amplitude_source"] != "TRAJECTORY_RECONSTRUCTION_REQUIRED":
            fail(f"{family_id} does not require trajectory-reconstructed initial amplitudes")
    expected_slots = {
        (family_id, level, repeat)
        for family_id, level_count in level_counts.items()
        for level in range(1, level_count + 1)
        for repeat in range(1, 6)
    }
    actual_slots = {
        (item["family_id"], item["amplitude_level_index"], item["repeat_index"])
        for item in registry
    }
    if actual_slots != expected_slots:
        fail("first-round run registry does not cover the preregistered slot matrix exactly once")
    for item in registry:
        family_id = item["family_id"]
        level = item["amplitude_level_index"]
        repeat = item["repeat_index"]
        expected_run = f"E0R-{family_id}-L{level:02d}-R{repeat:02d}"
        expected_attempt = f"E0A-{family_id}-L{level:02d}-R{repeat:02d}-A00"
        if item["run_id"] != expected_run or item["attempt_id"] != expected_attempt:
            fail("first-round run or attempt ID does not match its preregistered slot")
    forbidden_design_fields = {"eta_numeric", "tuned_eta", "numerically_tuned_geometry"}
    template_text = "\n".join(path.read_text(encoding="utf-8") for path in TEMPLATE_ROOT.iterdir())
    if any(field in template_text for field in forbidden_design_fields):
        fail("template contains forbidden numerically tuned manufacturing field")

    fixture = load_json(
        stage_root / "tests/fixtures/synthetic_stereo_session/fixture_manifest.json"
    )
    if (
        fixture.get("data_origin") != "SYNTHETIC"
        or fixture.get("contains_measured_values") is not False
    ):
        fail("synthetic fixture identity is not fail-closed")
    real_shape_fixture = load_json(
        stage_root / "tests/fixtures/synthetic_real_shape_session/fixture_manifest.json"
    )
    if (
        real_shape_fixture.get("data_origin") != "SYNTHETIC_REAL_SHAPE_FIXTURE"
        or real_shape_fixture.get("contains_measured_values") is not False
        or real_shape_fixture.get("attempt_lineage", {}).get("logical_repeats") != 2
        or real_shape_fixture.get("attempt_lineage", {}).get("retry_attempt") != "P02-R02-A01"
    ):
        fail("synthetic real-shape fixture identity or retry lineage is not fail-closed")

    source_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((stage_root / "src").rglob("*.py"))
    )
    for forbidden in ("solve_ivp", "odeint", "scipy.integrate"):
        if forbidden in source_text:
            fail(f"E0 contains a forbidden second integrator token: {forbidden}")
    adapter_text = (stage_root / "src/yps_experiment_pipeline/forward_adapter.py").read_text(
        encoding="utf-8"
    )
    for required in ("FORMAL_FORWARD_RELATIVE", "run_config", "run_ensemble"):
        if required not in adapter_text:
            fail(f"formal adapter lacks required binding token: {required}")
    detection_text = (stage_root / "src/yps_experiment_pipeline/detections.py").read_text(
        encoding="utf-8"
    )
    for required in (
        "pixel_covariance_px2",
        "triangulate_markers_with_covariance",
        "positive semidefinite",
    ):
        if required not in detection_text:
            fail(f"2D-to-3D covariance pipeline lacks required token: {required}")
    formal = formal_identity(repository_root)
    if len(formal["formal_source_sha256"]) != 64:
        fail("formal source hash is invalid")

    prohibited_claims = re.compile(
        r"\b(EXPERIMENT_PASS|PHYSICAL_VALIDATION_PASS|HF_NUMERICAL_QUALIFICATION_PASS)\b"
    )
    for document in sorted(stage_root.glob("*.md")):
        if prohibited_claims.search(document.read_text(encoding="utf-8")):
            fail(f"document contains prohibited claim: {document.name}")

    changed = git_changed_paths(repository_root)
    for path in changed:
        if path == STAGE_RELATIVE or STAGE_RELATIVE in path.parents or path in ALLOWED_GOVERNANCE:
            continue
        fail(f"Git change outside E0 allowlist: {path}")

    result = {
        "status": "E0R_REAL_DATA_CONTRACT_CORRECTIONS_COMPLETE__SYNTHETIC_REAL_SHAPE_FIXTURE_PASS__STOP_AT_E0R_PRO_REVIEW",
        "expected_file_count": len(EXPECTED_FILES),
        "schema_count": len(list(SCHEMA_ROOT.glob("*.schema.json"))),
        "template_count": len(list(TEMPLATE_ROOT.iterdir())),
        "formal_identity": formal,
        "git_changed_paths": [path.as_posix() for path in changed],
        "claim_ceiling": "IMPLEMENTATION_AND_SYNTHETIC_REAL_SHAPE_FIXTURE_ONLY",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "E0_STAGE_CHECK_FAIL", "error": str(exc)}, ensure_ascii=False))
        raise

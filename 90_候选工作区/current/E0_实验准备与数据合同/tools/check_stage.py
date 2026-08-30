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
        "schemas/material_test_manifest.schema.json",
        "schemas/camera_rig.schema.json",
        "schemas/experiment_run.schema.json",
        "schemas/trajectory_bundle.schema.json",
        "schemas/processed_observables.schema.json",
        "schemas/model_input_binding.schema.json",
        "schemas/comparison_result.schema.json",
        "templates/apparatus_measurements.template.json",
        "templates/material_test_manifest.template.json",
        "templates/camera_rig.template.json",
        "templates/first_round_plan.template.json",
        "templates/uncertainty_budget.template.csv",
        "templates/pilot_run_sheet.template.csv",
        "src/yps_experiment_pipeline/__init__.py",
        "src/yps_experiment_pipeline/__main__.py",
        "src/yps_experiment_pipeline/contracts.py",
        "src/yps_experiment_pipeline/camera.py",
        "src/yps_experiment_pipeline/synchronization.py",
        "src/yps_experiment_pipeline/trajectory.py",
        "src/yps_experiment_pipeline/observables.py",
        "src/yps_experiment_pipeline/forward_adapter.py",
        "src/yps_experiment_pipeline/comparison.py",
        "src/yps_experiment_pipeline/cli.py",
        "tests/fixtures/synthetic_stereo_session/fixture_manifest.json",
        "tests/test_contracts.py",
        "tests/test_camera_and_sync.py",
        "tests/test_trajectory_reconstruction.py",
        "tests/test_observables.py",
        "tests/test_forward_adapter.py",
        "tests/test_comparison.py",
        "tests/test_no_fake_measurements.py",
        "tools/check_stage.py",
    )
}


def fail(message: str) -> None:
    raise RuntimeError(message)


def tracked_stage_files(stage_root: Path) -> set[Path]:
    ignored_parts = {"__pycache__", ".pytest_cache", "build", "dist"}
    result = set()
    for path in stage_root.rglob("*"):
        if not path.is_file() or any(part in ignored_parts for part in path.parts):
            continue
        if path.suffix == ".pyc" or path.name.endswith(".egg-info"):
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
    if [row["pilot_id"] for row in pilot] != [f"P0{index}" for index in range(7)]:
        fail("pilot IDs must be P00 through P06")
    if any(row["status"] != "NOT_RUN" for row in pilot):
        fail("pilot template contains an executed run")


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
        "status": "E0_STAGE_CHECK_PASS__SYNTHETIC_ONLY",
        "expected_file_count": len(EXPECTED_FILES),
        "schema_count": len(list(SCHEMA_ROOT.glob("*.schema.json"))),
        "template_count": len(list(TEMPLATE_ROOT.iterdir())),
        "formal_identity": formal,
        "git_changed_paths": [path.as_posix() for path in changed],
        "claim_ceiling": "IMPLEMENTATION_AND_SYNTHETIC_FIXTURE_ONLY",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "E0_STAGE_CHECK_FAIL", "error": str(exc)}, ensure_ascii=False))
        raise

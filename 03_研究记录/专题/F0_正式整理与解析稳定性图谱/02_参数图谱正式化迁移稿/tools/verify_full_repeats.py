"""Verify byte-identical full atlas repeats and emit deterministic evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

EXPECTED_FILES = (
    "artifact_manifest.json",
    "atlas_results.json",
    "atlas_run_evidence.json",
    "atlas_summary.csv",
    "figures/compensation_accuracy.png",
    "figures/compensation_accuracy.svg",
    "figures/phase_atlas_3to2.png",
    "figures/phase_atlas_3to2.svg",
    "geometry_tolerance.csv",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_json(instance_path: Path, schema_path: Path) -> None:
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(load_json(instance_path))


def collect_run(run_dir: Path) -> dict[str, Any]:
    files = tuple(
        sorted(
            path.relative_to(run_dir).as_posix()
            for path in run_dir.rglob("*")
            if path.is_file()
        )
    )
    if files != EXPECTED_FILES:
        raise RuntimeError(
            f"unexpected full-run file set in {run_dir}: {files!r}"
        )

    artifact_manifest = load_json(run_dir / "artifact_manifest.json")
    manifest_entries = {
        entry["path"]: (entry["bytes"], entry["sha256"])
        for entry in artifact_manifest["artifacts"]
    }
    expected_manifest_paths = set(EXPECTED_FILES) - {"artifact_manifest.json"}
    if set(manifest_entries) != expected_manifest_paths:
        raise RuntimeError(f"artifact manifest is incomplete in {run_dir}")

    hashes: dict[str, str] = {}
    for relative_path in EXPECTED_FILES:
        path = run_dir / relative_path
        file_hash = sha256(path)
        hashes[relative_path] = file_hash
        if relative_path != "artifact_manifest.json":
            expected_size, expected_hash = manifest_entries[relative_path]
            if path.stat().st_size != expected_size or file_hash != expected_hash:
                raise RuntimeError(
                    f"artifact manifest mismatch for {run_dir / relative_path}"
                )

    return {
        "artifact_manifest_self_check": "PASS",
        "file_count": len(files),
        "files": [
            {"path": relative_path, "sha256": hashes[relative_path]}
            for relative_path in EXPECTED_FILES
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if len(args.run_dirs) < 2:
        raise RuntimeError("at least two full-run directories are required")

    project_root = args.project_root.resolve()
    run_dirs = [path.resolve() for path in args.run_dirs]
    runs = [collect_run(path) for path in run_dirs]
    reference_files = runs[0]["files"]
    byte_identical = all(run["files"] == reference_files for run in runs[1:])
    if not byte_identical:
        raise RuntimeError("full atlas runs are not byte-identical")

    for run_dir in run_dirs:
        validate_json(
            run_dir / "atlas_results.json",
            project_root / "schemas/atlas_output.schema.json",
        )
        validate_json(
            run_dir / "atlas_run_evidence.json",
            project_root / "schemas/atlas_run_evidence.schema.json",
        )

    result = load_json(run_dirs[0] / "atlas_results.json")
    evidence = load_json(run_dirs[0] / "atlas_run_evidence.json")
    semantic_checks = {
        "all_numerical_gates_passed": evidence["diagnostics"][
            "all_numerical_gates_passed"
        ],
        "all_optimizer_states_converged": evidence["optimizer"]["all_states"]
        == "CONVERGED",
        "atlas_case_count": evidence["execution"]["atlas_case_count"],
        "primary_result_trajectory_count": evidence["execution"][
            "primary_result_trajectory_count"
        ],
        "result_case_count": len(result["cases"]),
    }
    expected_semantics = {
        "all_numerical_gates_passed": True,
        "all_optimizer_states_converged": True,
        "atlas_case_count": 16,
        "primary_result_trajectory_count": 48,
        "result_case_count": 16,
    }
    if semantic_checks != expected_semantics:
        raise RuntimeError(f"full-run semantic checks failed: {semantic_checks!r}")

    report = {
        "schema": "YPS-FORMAL-PATTERN-ATLAS-FULL-REPEAT-VERIFICATION-1.0",
        "run_kind": "FULL_16_CASE_48_PRIMARY_TRAJECTORY_MATRIX",
        "verification_tool": {
            "path": "tools/verify_full_repeats.py",
            "sha256": sha256(Path(__file__).resolve()),
        },
        "repeat_count": len(runs),
        "byte_identical_across_all_repeats": True,
        "schemas_validated": [
            "schemas/atlas_output.schema.json",
            "schemas/atlas_run_evidence.schema.json",
        ],
        "semantic_checks": semantic_checks,
        "reference_artifact_hashes": reference_files,
        "per_repeat_checks": [
            {
                "repeat_id": index,
                "artifact_manifest_self_check": run[
                    "artifact_manifest_self_check"
                ],
                "file_count": run["file_count"],
                "byte_identity_against_repeat_1": "PASS",
            }
            for index, run in enumerate(runs, start=1)
        ],
        "conclusion_limit": (
            "IMPLEMENTATION_LEVEL_DETERMINISM_AND_IDEAL_MODEL_NUMERICAL_"
            "VALIDATION_ONLY"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

"""Runtime, architecture, hash and six-stage commit support for P3R4."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ypendulum_hfv2_p3r3.evidence_support import (
    architecture_metrics,
    jsonable,
    load_json,
    runtime_metrics,
    sha256,
)


def commit_for_path(repository_root: Path, path: Path) -> str:
    relative = path.relative_to(repository_root)
    return subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", str(relative)],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def commit_exists(repository_root: Path, commit: str) -> bool:
    return bool(
        commit
        and subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )


def is_ancestor(repository_root: Path, older: str, newer: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )


def commit_distance(repository_root: Path, older: str, newer: str) -> int:
    output = subprocess.run(
        ["git", "rev-list", "--count", f"{older}..{newer}"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return int(output)


def git_head(repository_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _hash_records(
    root: Path,
    expected_hashes: dict[str, str],
) -> dict[str, dict[str, str]]:
    records = {}
    for relative, expected in expected_hashes.items():
        actual = sha256(root / relative)
        records[relative] = {
            "expected_sha256": expected,
            "actual_sha256": actual,
            "status": "PASS" if actual == expected else "FAIL",
        }
    return records


def _formal_records(
    root: Path,
    manifest: dict[str, Any],
) -> dict[str, dict[str, str]]:
    repository_root = root.parents[2]
    adapter = load_json(root / "contracts" / manifest["adapter_contract"])
    records = {}
    for identity, contract in adapter["formal_sources"].items():
        path = repository_root / contract["path"]
        actual_sha = sha256(path)
        actual_blob = subprocess.run(
            ["git", "hash-object", str(path)],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        passed = actual_sha == contract["sha256"] and actual_blob == contract["git_blob"]
        records[identity] = {
            "path": contract["path"],
            "expected_sha256": contract["sha256"],
            "actual_sha256": actual_sha,
            "expected_git_blob": contract["git_blob"],
            "actual_git_blob": actual_blob,
            "status": "PASS" if passed else "FAIL",
        }
    return records


def contract_binding(
    root: Path,
    manifest: dict[str, Any],
    *,
    required_stage: str,
) -> dict[str, Any]:
    """Verify prefreeze, implementation, admissibility and target boundaries."""

    if required_stage not in {"implementation", "admissibility", "target"}:
        raise ValueError("Unknown P3R4 binding stage.")
    repository_root = root.parents[2]
    formal = _formal_records(root, manifest)
    prefreeze_records = _hash_records(root, manifest["prefreeze_source_sha256"])
    historical_records = _hash_records(root, manifest["historical_artifact_sha256"])
    implementation_path = root / "contracts" / manifest["implementation_binding"]
    implementation = load_json(implementation_path)
    implementation_records = _hash_records(root, implementation["source_sha256"])

    source_parent = str(manifest["prefreeze_source_commit"])
    prefreeze_commit = commit_for_path(
        repository_root,
        root / "contracts" / manifest["frozen_protocol"],
    )
    implementation_commit = commit_for_path(repository_root, implementation_path)
    base_order = bool(
        commit_exists(repository_root, source_parent)
        and commit_exists(repository_root, prefreeze_commit)
        and commit_exists(repository_root, implementation_commit)
        and len({source_parent, prefreeze_commit, implementation_commit}) == 3
        and is_ancestor(repository_root, source_parent, prefreeze_commit)
        and is_ancestor(repository_root, prefreeze_commit, implementation_commit)
        and commit_distance(repository_root, source_parent, prefreeze_commit) == 1
        and commit_distance(repository_root, prefreeze_commit, implementation_commit) == 1
    )

    admissibility_record: dict[str, Any] | None = None
    admissibility_commit = ""
    admissibility_pass = required_stage == "implementation"
    if required_stage in {"admissibility", "target"}:
        paths = [root / relative for relative in manifest["planned_admissibility_paths"]]
        commits = {commit_for_path(repository_root, path) for path in paths}
        admissibility_commit = next(iter(commits)) if len(commits) == 1 else ""
        metrics = load_json(root / "reports/p3r4_admissibility_metrics.json")
        selection = load_json(root / "contracts/p3r4_admissibility_selection.json")
        zero_qualification = bool(
            metrics["qualification_seed_run_count"] == 0
            and metrics["target_freeze_run_count"] == 0
            and selection["qualification_seed_results_observed_before_separate_target_freeze"] == 0
            and selection["qualification_seed_execution_counts_before_separate_target_freeze"] == {}
            and selection["target_freeze_generated"] is False
        )
        admissibility_pass = bool(
            admissibility_commit
            and commit_exists(repository_root, admissibility_commit)
            and is_ancestor(repository_root, implementation_commit, admissibility_commit)
            and commit_distance(repository_root, implementation_commit, admissibility_commit) == 1
            and metrics["reference_discovery_run_count"] == 8
            and zero_qualification
        )
        admissibility_record = {
            "paths": [str(path.relative_to(root)) for path in paths],
            "commit": admissibility_commit,
            "metrics_sha256": sha256(root / "reports/p3r4_admissibility_metrics.json"),
            "selection_sha256": sha256(root / "contracts/p3r4_admissibility_selection.json"),
            "zero_target_or_qualification_results": zero_qualification,
        }

    target_record: dict[str, Any] | None = None
    target_commit = ""
    target_pass = required_stage != "target"
    if required_stage == "target":
        target_path = root / "contracts" / manifest["target_freeze"]
        target = load_json(target_path)
        target_commit = commit_for_path(repository_root, target_path)
        counts = target["qualification_seed_execution_counts_before_target_freeze"]
        zero_qualification = bool(
            target["qualification_seed_results_observed_before_target_freeze"] == 0
            and counts
            and all(value == 0 for value in counts.values())
            and target["qualification_targets"]
        )
        target_pass = bool(
            target["status"] == "TARGETS_AND_SOLVER_INITIAL_GUESSES_FROZEN"
            and target["admissibility_commit"] == admissibility_commit
            and target["admissibility_metrics_sha256"]
            == sha256(root / "reports/p3r4_admissibility_metrics.json")
            and target["admissibility_selection_sha256"]
            == sha256(root / "contracts/p3r4_admissibility_selection.json")
            and zero_qualification
            and commit_exists(repository_root, target_commit)
            and is_ancestor(repository_root, admissibility_commit, target_commit)
            and commit_distance(repository_root, admissibility_commit, target_commit) == 1
        )
        target_record = {
            "path": f"contracts/{manifest['target_freeze']}",
            "sha256": sha256(target_path),
            "commit": target_commit,
            "zero_qualification_seed_results": zero_qualification,
        }

    records_pass = all(
        item["status"] == "PASS"
        for records in (formal, prefreeze_records, historical_records, implementation_records)
        for item in records.values()
    )
    passed = base_order and admissibility_pass and target_pass and records_pass
    return {
        "required_stage": required_stage,
        "prefreeze_source_commit": source_parent,
        "prefreeze_commit": prefreeze_commit,
        "implementation_commit": implementation_commit,
        "admissibility_commit": admissibility_commit or None,
        "target_freeze_commit": target_commit or None,
        "commit_order_passed": base_order and admissibility_pass and target_pass,
        "adapter_contract": {
            "path": manifest["adapter_contract"],
            "sha256": sha256(root / "contracts" / manifest["adapter_contract"]),
        },
        "frozen_protocol": {
            "path": manifest["frozen_protocol"],
            "sha256": sha256(root / "contracts" / manifest["frozen_protocol"]),
        },
        "model_identity": {
            "path": manifest["model_identity"],
            "sha256": sha256(root / "contracts" / manifest["model_identity"]),
        },
        "formal_sources": formal,
        "prefreeze_source_records": prefreeze_records,
        "historical_artifact_records": historical_records,
        "implementation_source_records": implementation_records,
        "admissibility": admissibility_record,
        "target_freeze": target_record,
        "status": "PASS" if passed else "FAIL",
    }


def evidence_hash_binding(
    root: Path,
    manifest: dict[str, Any],
) -> dict[str, str]:
    implementation = load_json(root / "contracts" / manifest["implementation_binding"])
    paths = set(manifest["prefreeze_source_sha256"])
    paths.update(manifest["historical_artifact_sha256"])
    paths.update(implementation["source_sha256"])
    paths.update(
        {
            f"contracts/{manifest['implementation_binding']}",
            f"contracts/{manifest['admissibility_selection']}",
            f"contracts/{manifest['target_freeze']}",
            "reports/p3r4_admissibility_metrics.json",
            "reports/P3R4_ADMISSIBILITY_REPORT.md",
        }
    )
    return {relative: sha256(root / relative) for relative in sorted(paths)}


__all__ = [
    "architecture_metrics",
    "commit_distance",
    "commit_exists",
    "commit_for_path",
    "contract_binding",
    "evidence_hash_binding",
    "git_head",
    "is_ancestor",
    "jsonable",
    "load_json",
    "runtime_metrics",
    "sha256",
]

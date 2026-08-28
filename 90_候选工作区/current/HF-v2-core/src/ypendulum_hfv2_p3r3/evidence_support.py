"""Runtime, source, commit, architecture and hash support for P3R3."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ypendulum_hfv2.audit.dependency import audit_g2_dependencies
from ypendulum_hfv2_p3r.evidence_support import (
    jsonable,
    load_json,
    run_bound_benchmarks,
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
    return (
        subprocess.run(
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


def git_head(repository_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def architecture_metrics(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    architecture = manifest["architecture"]
    package_name = str(manifest["package_name"])
    source_root = root / "src" / package_name
    audit = audit_g2_dependencies(
        source_root,
        root / "contracts" / architecture["module_manifest"],
        package_name=package_name,
    )
    line_limit = int(architecture["source_lines_per_module_max_exclusive"])
    line_counts = {
        relative: len((source_root / relative).read_text(encoding="utf-8").splitlines())
        for relative in audit.discovered_files
    }
    oversized = {path: count for path, count in line_counts.items() if count >= line_limit}
    passed = audit.passed and not oversized
    return {
        "module_manifest": architecture["module_manifest"],
        "discovered_file_count": len(audit.discovered_files),
        "unclassified_files": list(audit.unclassified_files),
        "missing_manifest_files": list(audit.missing_manifest_files),
        "dependency_violations": [item.__dict__ for item in audit.dependency_violations],
        "path_classification_violations": list(audit.path_classification_violations),
        "production_try_statement_count": audit.production_try_statement_count,
        "production_random_call_count": audit.production_random_call_count,
        "line_counts": line_counts,
        "line_limit_exclusive": line_limit,
        "oversized_modules": oversized,
        "status": "PASS" if passed else "FAIL",
    }


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


def contract_binding(
    root: Path,
    manifest: dict[str, Any],
    *,
    require_target_freeze: bool,
) -> dict[str, Any]:
    repository_root = root.parents[2]
    adapter_path = root / "contracts" / manifest["adapter_contract"]
    adapter = load_json(adapter_path)
    formal_sources = {}
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
        formal_sources[identity] = {
            "path": contract["path"],
            "expected_sha256": contract["sha256"],
            "actual_sha256": actual_sha,
            "expected_git_blob": contract["git_blob"],
            "actual_git_blob": actual_blob,
            "status": "PASS" if passed else "FAIL",
        }
    prefreeze_records = _hash_records(root, manifest["prefreeze_source_sha256"])
    historical_records = _hash_records(
        root,
        manifest["historical_artifact_sha256"],
    )
    implementation_path = root / "contracts" / manifest["implementation_binding"]
    implementation = load_json(implementation_path)
    implementation_records = _hash_records(root, implementation["source_sha256"])
    protocol_path = root / "contracts" / manifest["frozen_protocol"]
    prefreeze_commit = commit_for_path(repository_root, protocol_path)
    implementation_commit = commit_for_path(repository_root, implementation_path)
    source_parent = str(manifest["prefreeze_source_commit"])
    base_commits_pass = bool(
        commit_exists(repository_root, source_parent)
        and commit_exists(repository_root, prefreeze_commit)
        and commit_exists(repository_root, implementation_commit)
        and is_ancestor(repository_root, source_parent, prefreeze_commit)
        and is_ancestor(repository_root, prefreeze_commit, implementation_commit)
        and len({source_parent, prefreeze_commit, implementation_commit}) == 3
    )
    target_record: dict[str, Any] | None = None
    target_commit = ""
    target_pass = not require_target_freeze
    if require_target_freeze:
        target_path = root / "contracts" / manifest["target_freeze"]
        target = load_json(target_path)
        target_commit = commit_for_path(repository_root, target_path)
        counts = target["qualification_seed_execution_counts_before_target_freeze"]
        target_zero = bool(
            target["qualification_seed_results_observed_before_target_freeze"] == 0
            and counts
            and all(value == 0 for value in counts.values())
        )
        target_pass = bool(
            target_zero
            and commit_exists(repository_root, target_commit)
            and is_ancestor(repository_root, implementation_commit, target_commit)
            and target_commit != implementation_commit
        )
        target_record = {
            "path": f"contracts/{manifest['target_freeze']}",
            "sha256": sha256(target_path),
            "commit": target_commit,
            "zero_qualification_seed_results": target_zero,
        }
    records_pass = all(
        item["status"] == "PASS"
        for records in (
            formal_sources,
            prefreeze_records,
            historical_records,
            implementation_records,
        )
        for item in records.values()
    )
    passed = base_commits_pass and target_pass and records_pass
    return {
        "prefreeze_source_commit": source_parent,
        "prefreeze_commit": prefreeze_commit,
        "implementation_commit": implementation_commit,
        "target_freeze_commit": target_commit or None,
        "commit_order_passed": base_commits_pass and target_pass,
        "adapter_contract": {
            "path": manifest["adapter_contract"],
            "sha256": sha256(adapter_path),
        },
        "frozen_protocol": {
            "path": manifest["frozen_protocol"],
            "sha256": sha256(protocol_path),
        },
        "model_identity": {
            "path": manifest["model_identity"],
            "sha256": sha256(root / "contracts" / manifest["model_identity"]),
        },
        "formal_sources": formal_sources,
        "prefreeze_source_records": prefreeze_records,
        "historical_artifact_records": historical_records,
        "implementation_source_records": implementation_records,
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
            f"contracts/{manifest['target_freeze']}",
            "reports/p3r3_admissibility_metrics.json",
        }
    )
    return {relative: sha256(root / relative) for relative in sorted(paths)}


__all__ = [
    "architecture_metrics",
    "commit_exists",
    "commit_for_path",
    "contract_binding",
    "evidence_hash_binding",
    "git_head",
    "is_ancestor",
    "jsonable",
    "load_json",
    "run_bound_benchmarks",
    "runtime_metrics",
    "sha256",
]

"""Runtime, source, commit, architecture and benchmark support for G3R2."""

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


def _commit_for_path(repository_root: Path, path: Path) -> str:
    relative = path.relative_to(repository_root)
    return subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", str(relative)],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _commit_exists(repository_root: Path, commit: str) -> bool:
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


def _is_ancestor(repository_root: Path, older: str, newer: str) -> bool:
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
        relative: len(
            (source_root / relative).read_text(encoding="utf-8").splitlines()
        )
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


def contract_binding(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
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
    prefreeze_records = {}
    for relative, expected in manifest["prefreeze_source_sha256"].items():
        actual = sha256(root / relative)
        prefreeze_records[relative] = {
            "expected_sha256": expected,
            "actual_sha256": actual,
            "status": "PASS" if actual == expected else "FAIL",
        }
    historical_records = {}
    for relative, expected in manifest["historical_artifact_sha256"].items():
        actual = sha256(root / relative)
        historical_records[relative] = {
            "expected_sha256": expected,
            "actual_sha256": actual,
            "status": "PASS" if actual == expected else "FAIL",
        }
    implementation_path = root / "contracts" / manifest["implementation_binding"]
    implementation = load_json(implementation_path)
    implementation_records = {}
    for relative, expected in implementation["source_sha256"].items():
        actual = sha256(root / relative)
        implementation_records[relative] = {
            "expected_sha256": expected,
            "actual_sha256": actual,
            "status": "PASS" if actual == expected else "FAIL",
        }
    protocol_path = root / "contracts" / manifest["frozen_protocol"]
    prefreeze_commit = _commit_for_path(repository_root, protocol_path)
    implementation_commit = _commit_for_path(repository_root, implementation_path)
    source_parent = str(manifest["prefreeze_source_commit"])
    commits_pass = bool(
        _commit_exists(repository_root, source_parent)
        and _commit_exists(repository_root, prefreeze_commit)
        and _commit_exists(repository_root, implementation_commit)
        and _is_ancestor(repository_root, source_parent, prefreeze_commit)
        and _is_ancestor(repository_root, prefreeze_commit, implementation_commit)
        and source_parent != prefreeze_commit
        and prefreeze_commit != implementation_commit
    )
    target_zero = bool(
        manifest["qualification_target_results_observed_before_freeze"] == 0
        and all(
            value == 0
            for value in manifest[
                "qualification_target_execution_counts_before_freeze"
            ].values()
        )
        and all(
            target["qualification_results_observed_before_freeze"] == 0
            for target in manifest["qualification_targets"]
        )
    )
    passed = bool(
        commits_pass
        and target_zero
        and all(item["status"] == "PASS" for item in formal_sources.values())
        and all(item["status"] == "PASS" for item in prefreeze_records.values())
        and all(item["status"] == "PASS" for item in historical_records.values())
        and all(item["status"] == "PASS" for item in implementation_records.values())
    )
    return {
        "prefreeze_source_commit": source_parent,
        "prefreeze_commit": prefreeze_commit,
        "implementation_commit": implementation_commit,
        "commit_order_passed": commits_pass,
        "qualification_target_results_observed_before_freeze": 0,
        "qualification_target_execution_counts_before_freeze": manifest[
            "qualification_target_execution_counts_before_freeze"
        ],
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
        "status": "PASS" if passed else "FAIL",
    }


def evidence_hash_binding(root: Path, manifest: dict[str, Any]) -> dict[str, str]:
    implementation = load_json(root / "contracts" / manifest["implementation_binding"])
    paths = set(manifest["prefreeze_source_sha256"])
    paths.update(implementation["source_sha256"])
    paths.update(
        {
            "contracts/p3r2_acceptance_manifest.json",
            f"contracts/{manifest['implementation_binding']}",
            "reports/g3_metrics.json",
            "reports/g3r_metrics.json",
        }
    )
    return {relative: sha256(root / relative) for relative in sorted(paths)}


__all__ = [
    "architecture_metrics",
    "contract_binding",
    "evidence_hash_binding",
    "jsonable",
    "load_json",
    "run_bound_benchmarks",
    "runtime_metrics",
    "sha256",
]

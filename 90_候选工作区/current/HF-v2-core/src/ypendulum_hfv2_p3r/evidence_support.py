"""Runtime, contract, architecture and exact-test-node evidence support for G3R."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import scipy

from ypendulum_hfv2.audit.dependency import audit_g2_dependencies


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return [jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return jsonable(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        if np.isnan(value):
            return "NOT_A_NUMBER"
        return "POSITIVE_INFINITY" if value > 0.0 else "NEGATIVE_INFINITY"
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    return value


def runtime_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    expected = manifest["runtime"]
    pytest_output = subprocess.run(
        [sys.executable, "-m", "pytest", "--version"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    ruff_output = subprocess.run(
        ["ruff", "--version"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    pytest_version = re.search(r"pytest\s+([0-9.]+)", pytest_output)
    ruff_version = re.search(r"ruff\s+([0-9.]+)", ruff_output)
    if pytest_version is None or ruff_version is None:
        raise ValueError("P3R validation-tool versions could not be parsed.")
    actual = {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "pytest_version": pytest_version.group(1),
        "ruff_version": ruff_version.group(1),
    }
    checks = {
        key: actual[key] == expected[key]
        for key in (
            "python_implementation",
            "python_version",
            "numpy_version",
            "scipy_version",
            "ruff_version",
        )
    }
    checks["pytest_minimum"] = tuple(
        int(item) for item in actual["pytest_version"].split(".")[:2]
    ) >= tuple(int(item) for item in str(expected["pytest_minimum"]).split(".")[:2])
    return {
        "expected": expected,
        "actual": actual,
        "checks": checks,
        "platform": platform.platform(),
        "byteorder": sys.byteorder,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def run_bound_benchmarks(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    mapping = manifest["small_benchmarks"]["benchmark_id_to_test_node"]
    records = []
    for benchmark_id, node in mapping.items():
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(node)],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        records.append(
            {
                "benchmark_id": benchmark_id,
                "test_node": node,
                "return_code": result.returncode,
                "status": "PASS" if result.returncode == 0 else "FAIL",
                "failure_output": "" if result.returncode == 0 else result.stdout + result.stderr,
            }
        )
    passed = bool(records) and all(item["status"] == "PASS" for item in records)
    return {
        "mapping_count": len(mapping),
        "unique_test_node_count": len(set(mapping.values())),
        "records": records,
        "executed_before_qualification_target": True,
        "status": "PASS" if passed else "FAIL",
    }


def architecture_metrics(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    architecture = manifest["architecture"]
    audit = audit_g2_dependencies(
        root / "src" / "ypendulum_hfv2_p3r",
        root / "contracts" / architecture["module_manifest"],
        package_name="ypendulum_hfv2_p3r",
    )
    line_limit = int(architecture["source_lines_per_module_max_exclusive"])
    line_counts = {
        relative: len(
            (root / "src" / "ypendulum_hfv2_p3r" / relative)
            .read_text(encoding="utf-8")
            .splitlines()
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
    source_records = {}
    for relative, expected_sha in manifest["prefreeze_source_sha256"].items():
        actual_sha = sha256(root / relative)
        source_records[relative] = {
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
            "status": "PASS" if actual_sha == expected_sha else "FAIL",
        }
    prefreeze = str(manifest["prefreeze_source_commit"])
    commit_exists = subprocess.run(
        ["git", "cat-file", "-e", f"{prefreeze}^{{commit}}"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    ).returncode == 0
    old_metrics = root / "reports" / "g3_metrics.json"
    old_hash = sha256(old_metrics)
    old_immutable = old_hash == manifest["historical_g3_metrics_sha256"]
    passed = bool(
        commit_exists
        and all(item["status"] == "PASS" for item in formal_sources.values())
        and all(item["status"] == "PASS" for item in source_records.values())
        and old_immutable
        and manifest["qualification_target_results_observed_before_freeze"] == 0
    )
    return {
        "prefreeze_source_commit": prefreeze,
        "prefreeze_commit_exists": commit_exists,
        "qualification_target_results_observed_before_freeze": manifest[
            "qualification_target_results_observed_before_freeze"
        ],
        "adapter_contract": {
            "path": manifest["adapter_contract"],
            "sha256": sha256(adapter_path),
        },
        "frozen_protocol": {
            "path": manifest["frozen_protocol"],
            "sha256": sha256(root / "contracts" / manifest["frozen_protocol"]),
        },
        "model_identity": {
            "path": manifest["model_identity"],
            "sha256": sha256(root / "contracts" / manifest["model_identity"]),
        },
        "formal_sources": formal_sources,
        "source_records": source_records,
        "historical_g3_metrics": {
            "expected_sha256": manifest["historical_g3_metrics_sha256"],
            "actual_sha256": old_hash,
            "status": "PASS" if old_immutable else "FAIL",
        },
        "status": "PASS" if passed else "FAIL",
    }


def evidence_hash_binding(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    paths = tuple(manifest["evidence_named_paths"])
    return {relative: sha256(root / relative) for relative in paths}

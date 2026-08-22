"""Transactional adapters around the frozen FWD tree and independent HF tree."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

import h5py
import yaml

from ypendulum.api import simulate
from ypendulum.config import resolved_config_dict
from ypendulum.hf import read_hf_certificate_sidecar
from ypendulum.io.provenance import source_hash

from .comparison import compare_backend_directories
from .contracts import (
    ResolvedUnifiedCase,
    load_unified_case,
    verify_unified_case_identities,
)

BackendSelection = Literal["forward", "high_fidelity", "both"]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _materialize_forward_dispatch(case: ResolvedUnifiedCase, target: Path) -> Path:
    """Write only bytes authenticated by the Stage-2 delivery into a private tree."""

    for relative, payload in case.forward_chain["dispatch_files"]:
        path = (target / relative).resolve()
        if not path.is_relative_to(target.resolve()):
            raise RuntimeError("Frozen forward dispatch path escaped its private root.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    config = (target / case.forward_chain["config_relative_path"]).resolve()
    if not config.is_relative_to(target.resolve()):
        raise RuntimeError("Frozen forward config path escaped its private root.")
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_bytes(case.forward_chain["config_bytes"])
    return config


def _forward_outcome(case: ResolvedUnifiedCase, output: Path) -> dict[str, Any]:
    result_path = output / "result.json"
    snapshot_path = output / "config.snapshot.json"
    if not result_path.is_file() or not snapshot_path.is_file():
        raise RuntimeError("Forward backend did not return its canonical result/config snapshot.")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        raise RuntimeError("Forward result lacks identity metadata.")
    expected = case.forward_chain
    identity_checks = {
        "model_id": result.get("model_id") == "FWD-CABLE-1.0",
        "config_snapshot": _canonical_hash(snapshot)
        == expected["config_canonical_sha256"],
        "config_metadata": metadata.get("config_sha256")
        == expected["config_canonical_sha256"],
        "source_start": metadata.get("source_tree_sha256")
        == expected["source_tree_sha256"],
        "source_end": metadata.get("source_tree_sha256_at_end")
        == expected["source_tree_sha256"],
        "source_stable": metadata.get("source_tree_stable_during_run") is True,
        "theory_top_level": result.get("theory_sha256")
        == expected["frozen_theory_sha256"],
        "theory_metadata": metadata.get("theory_sha256")
        == expected["frozen_theory_sha256"],
        "units": result.get("units") == "SI" and metadata.get("units") == "SI",
        "runtime_identity": isinstance(metadata.get("runtime_versions"), dict)
        and bool(metadata["runtime_versions"])
        and all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in metadata["runtime_versions"].items()
        ),
        "numerical_model": isinstance(result.get("numerical_model_id"), str)
        and "UNRESOLVED" not in result["numerical_model_id"],
    }
    failed = [name for name, passed in identity_checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Frozen forward result identity contract failed: {failed}")
    contract = result.get("contract_status")
    numerical = result.get("numerical_status")
    if contract == ["COMPLETED"] and numerical == "SUCCESS_SINGLE_RUN":
        scientific_status = "COMPLETED"
    elif contract == ["OUT_OF_SCOPE"] and numerical == "SUCCESS_EVENT":
        scientific_status = "OUT_OF_SCOPE_PREFIX"
    else:
        raise RuntimeError(
            "Forward backend returned neither a completed trajectory nor a certified "
            f"physical prefix: contract={contract}, numerical={numerical}."
        )
    return {
        "model_id": result["model_id"],
        "scientific_status": scientific_status,
        "physical_status": contract[0],
        "numerical_status": numerical,
        "tau": result.get("tau"),
        "identity_checks": identity_checks,
        "runtime_versions": metadata["runtime_versions"],
    }


def _run_forward(
    case: ResolvedUnifiedCase, output: Path, log: Path
) -> dict[str, Any]:
    dispatch = Path(
        tempfile.mkdtemp(prefix=".fwd-dispatch-", dir=output.parent)
    ).resolve()
    try:
        config = _materialize_forward_dispatch(case, dispatch)
        command = [
            sys.executable,
            str(dispatch / "run.py"),
            "run",
            str(config),
            "--output",
            str(output),
            "--no-plots",
        ]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(dispatch)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        with log.open("wb") as stream:
            completed = subprocess.run(
                command,
                cwd=dispatch,
                env=environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if completed.returncode != 0:
            raise RuntimeError(
                "Frozen forward backend failed with exit code "
                f"{completed.returncode}; see {log}."
            )
        return _forward_outcome(case, output)
    finally:
        shutil.rmtree(dispatch, ignore_errors=True)


def _run_high_fidelity(
    case: ResolvedUnifiedCase, output: Path, log: Path
) -> dict[str, Any]:
    config = case.high_fidelity_config.model_copy(deep=True)
    config.run.output_directory = str(output)
    expected_resolved = resolved_config_dict(config)
    package_root = Path(__file__).resolve().parents[1]
    source_start = source_hash(package_root)
    try:
        result = simulate(
            config,
            hf_validation_spec=case.high_fidelity_validation_spec_path,
        )
        source_end = source_hash(package_root)
        if source_start != source_end:
            raise RuntimeError("HF executable source drifted during the backend run.")
        supported_raw_status = (
            (
                result.physical_status == "UNDETERMINED"
                and result.numerical_status
                == "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"
            )
            or (
                result.physical_status == "OUT_OF_SCOPE"
                and result.numerical_status == "SUCCESS_EVENT"
            )
        )
        if not supported_raw_status:
            raise RuntimeError(
                "HF backend is numerically/physically unresolved: "
                f"{result.physical_status}/{result.numerical_status}."
            )
        sidecar = read_hf_certificate_sidecar(output, require_full=False)
        certificate = sidecar["certificate"]
        if (
            result.physical_status == "UNDETERMINED"
            and result.numerical_status
            == "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"
        ):
            sidecar = read_hf_certificate_sidecar(output, require_full=True)
            certificate = sidecar["certificate"]
            certified_status = certificate["certified_status_pair"]
            scientific_status = "COMPLETED"
        elif (
            result.physical_status == "OUT_OF_SCOPE"
            and result.numerical_status == "SUCCESS_EVENT"
        ):
            scientific_status = "OUT_OF_SCOPE_PREFIX"
            certified_status = {
                "physical_status": result.physical_status,
                "numerical_status": result.numerical_status,
            }
        else:  # guarded by ``supported_raw_status`` above
            raise AssertionError("Unreachable HF raw-status branch.")
        resolved_path = output / "config_resolved.yaml"
        provenance_path = output / "provenance.json"
        summary_path = output / "summary.json"
        h5_path = output / "result.h5"
        if not all(
            path.is_file()
            for path in (resolved_path, provenance_path, summary_path, h5_path)
        ):
            raise RuntimeError("HF backend omitted a canonical identity/result artifact.")
        resolved_output = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        with h5py.File(h5_path, "r") as h5:
            h5_identity = {
                "model": str(h5.attrs.get("model", "")),
                "units": str(h5.attrs.get("units", "")),
                "physical_status": str(h5.attrs.get("physical_status", "")),
                "numerical_status": str(h5.attrs.get("numerical_status", "")),
            }
        identity_checks = {
            "resolved_config": _canonical_hash(resolved_output)
            == _canonical_hash(expected_resolved),
            "provenance_config": provenance.get("config_hash_sha256")
            == _canonical_hash(resolved_output),
            "provenance_source": provenance.get("source_hash_sha256") == source_start,
            "summary_model": summary.get("model") == result.model_id,
            "summary_status": summary.get("physical_status")
            == result.physical_status
            and summary.get("numerical_status") == result.numerical_status,
            "hdf5_model": h5_identity["model"] == result.model_id,
            "hdf5_units": h5_identity["units"] == "SI",
            "hdf5_status": h5_identity["physical_status"]
            == result.physical_status
            and h5_identity["numerical_status"] == result.numerical_status,
            "certificate_status_appropriate": (
                certificate["passed"] is True
                if scientific_status == "COMPLETED"
                else certificate["passed"] is False
            ),
            "certificate_config": certificate["identity"][
                "canonical_resolved_config_sha256_start"
            ]
            == _canonical_hash(expected_resolved),
            "certificate_source": certificate["identity"][
                "source_hash_start_sha256"
            ]
            == source_start,
            "certificate_validation_spec": certificate["identity"][
                "validation_spec_file_sha256_start"
            ]
            == case.high_fidelity_validation_spec_file_sha256,
        }
        failed_identity = [
            name for name, passed in identity_checks.items() if not passed
        ]
        if failed_identity:
            raise RuntimeError(f"HF result identity contract failed: {failed_identity}")
        payload = {
            "status": scientific_status,
            "model_id": result.model_id,
            "physical_status": result.physical_status,
            "numerical_status": result.numerical_status,
            "certified_physical_status": certified_status["physical_status"],
            "certified_numerical_status": certified_status["numerical_status"],
            "certificate_sha256": certificate["certificate_sha256"],
            "valid_interval": list(result.valid_interval),
            "identity_checks": identity_checks,
            "source_hash_start_sha256": source_start,
            "source_hash_end_sha256": source_end,
        }
        _write_json(
            log,
            payload,
        )
        return {
            "model_id": result.model_id,
            "scientific_status": scientific_status,
            "physical_status": result.physical_status,
            "numerical_status": result.numerical_status,
            "certified_physical_status": certified_status["physical_status"],
            "certified_numerical_status": certified_status["numerical_status"],
            "certificate_sha256": certificate["certificate_sha256"],
            "valid_interval": list(result.valid_interval),
            "identity_checks": identity_checks,
            "source_hash_start_sha256": source_start,
            "source_hash_end_sha256": source_end,
        }
    except Exception as exc:
        _write_json(
            log,
            {
                "status": "error",
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
        )
        raise


def _manifest(directory: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.relative_to(directory)),
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    ]


def run_unified_case(
    case: ResolvedUnifiedCase | str | Path,
    *,
    backend: BackendSelection,
    output_directory: str | Path,
) -> dict[str, Any]:
    if backend not in {"forward", "high_fidelity", "both"}:
        raise ValueError("backend must be forward, high_fidelity or both.")
    resolved = case if isinstance(case, ResolvedUnifiedCase) else load_unified_case(case)
    target = Path(output_directory).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"Unified output directory already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
    package_root = Path(__file__).resolve().parents[1]
    source_start = source_hash(package_root)
    identities_start = verify_unified_case_identities(resolved)
    try:
        _write_json(staging / "case.snapshot.json", resolved.payload)
        _write_json(staging / "shared_input_audit.json", resolved.shared_input_audit)
        outcomes: dict[str, Any] = {}
        if backend in {"forward", "both"}:
            outcomes["forward"] = _run_forward(
                resolved, staging / "forward", staging / "forward.log"
            ) or {
                "scientific_status": "COMPLETED",
                "physical_status": "COMPLETED",
                "numerical_status": "SUCCESS_SINGLE_RUN",
            }
        if backend in {"high_fidelity", "both"}:
            outcomes["high_fidelity"] = _run_high_fidelity(
                resolved, staging / "high_fidelity", staging / "high_fidelity.log.json"
            ) or {
                "scientific_status": "COMPLETED",
                "physical_status": "UNDETERMINED",
                "numerical_status": "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED",
                "certified_physical_status": (
                    "COMPLETED_INDEPENDENTLY_CERTIFIED"
                ),
                "certified_numerical_status": (
                    "SUCCESS_SINGLE_RUN_GUARDS_CERTIFIED_BY_VALIDATION"
                ),
            }
        all_completed = all(
            outcome.get("scientific_status") == "COMPLETED"
            for outcome in outcomes.values()
        )
        comparison = None
        if backend == "both" and all_completed:
            comparison = compare_backend_directories(
                staging / "forward",
                staging / "high_fidelity",
                output_directory=staging / "comparison",
            )
        source_end = source_hash(package_root)
        identities_end = verify_unified_case_identities(resolved)
        if source_start != source_end or identities_start != identities_end:
            raise RuntimeError(
                "Executable, input, or frozen forward delivery identity drifted during the run."
            )
        manifest_path = staging / "artifact_manifest.json"
        _write_json(
            manifest_path,
            {
                "schema_version": "YPS-UNIFIED-ARTIFACT-MANIFEST-1.0",
                "files": _manifest(staging),
            },
        )
        root = {
            "schema_version": "YPS-UNIFIED-DELIVERY-ROOT-1.0",
            "status": "COMPLETE" if all_completed else "OUT_OF_SCOPE_PREFIX",
            "backend_selection": backend,
            "problem_id": resolved.payload["problem_id"],
            "units": "SI",
            "case_sha256": resolved.case_hash_sha256,
            "source_hash_start_sha256": source_start,
            "source_hash_end_sha256": source_end,
            "source_stable_during_run": True,
            "input_identity_start": identities_start,
            "input_identity_end": identities_end,
            "input_identity_stable_during_run": True,
            "shared_input_audit_passed": resolved.shared_input_audit["passed"],
            "backend_outcomes": outcomes,
            "comparison_status": (
                "NOT_REQUESTED"
                if backend != "both"
                else (
                    "NOT_RUN_BACKEND_NOT_COMPLETED"
                    if comparison is None
                    else comparison["status"]
                )
            ),
            "artifact_manifest_sha256": _sha256_file(manifest_path),
        }
        _write_json(staging / "delivery_root.json", root)
        os.replace(staging, target)
        return {**root, "output_directory": str(target)}
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise

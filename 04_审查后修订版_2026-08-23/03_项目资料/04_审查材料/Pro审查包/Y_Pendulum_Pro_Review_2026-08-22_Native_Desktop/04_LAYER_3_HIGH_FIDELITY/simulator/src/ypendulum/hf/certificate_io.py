"""Artifact binding for independently certified HF single-run results.

The numerical/physical certificate deliberately hashes the in-memory result
and contains no file-system paths.  This module wraps that certificate in a
non-self-referential sidecar which binds every artifact already present in the
staged run directory.  Consumers re-check both layers before treating the raw
provisional HDF5 trajectory as independently certified.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

import h5py

from ypendulum.io.provenance import sha256_file, write_json

HF_CERTIFICATE_SIDECAR = "hf_single_bundle_certificate.json"
_SIDECAR_SCHEMA = "YPS-HF-CERTIFIED-RUN-SIDECAR-1.0"
_MODEL_ID = "HF-DISCRETE-ROD-RIGID-BOB-1.0"
_RAW_STATUS = {
    "physical_status": "UNDETERMINED",
    "numerical_status": "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED",
}
_CERTIFIED_STATUS = {
    "physical_status": "COMPLETED_INDEPENDENTLY_CERTIFIED",
    "numerical_status": "SUCCESS_SINGLE_RUN_GUARDS_CERTIFIED_BY_VALIDATION",
}
_REQUIRED_ARTIFACTS = {
    "config_resolved.yaml",
    "diagnostics.json",
    "events.csv",
    "events.json",
    "execution_identity.json",
    "observer_output.npz",
    "observer_summary.json",
    "provenance.json",
    "result.h5",
    "summary.json",
}


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _certificate_digest_valid(certificate: Any) -> bool:
    # Local import keeps the artifact reader independent of package import
    # order while still using the validation layer's canonical algorithm.
    from .validation import verify_single_hf_certificate_digest

    return verify_single_hf_certificate_digest(certificate)


def _strict_json(path: Path) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in items:
            if not isinstance(key, str) or key in output:
                raise ValueError(f"Duplicate or non-string JSON key in {path}.")
            output[key] = value
        return output

    def constant(value: str) -> Any:
        raise ValueError(f"Non-finite JSON constant {value!r} in {path}.")

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=pairs,
        parse_constant=constant,
    )


def _validated_relative_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ValueError("Certificate artifact paths must be non-empty strings.")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"Unsafe certificate artifact path: {value!r}.")
    if relative.as_posix() == HF_CERTIFICATE_SIDECAR:
        raise ValueError("The certificate sidecar must not hash itself.")
    return relative


def _artifact_records(directory: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name == HF_CERTIFICATE_SIDECAR:
            continue
        if path.is_symlink():
            raise ValueError(f"Certified run artifacts may not be symlinks: {path}.")
        relative = path.relative_to(directory).as_posix()
        records.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    records.sort(key=lambda item: item["path"])
    names = {item["path"] for item in records}
    missing = sorted(_REQUIRED_ARTIFACTS - names)
    if missing:
        raise ValueError(f"Certified HF run is missing canonical artifacts: {missing}.")
    return records


def write_hf_certificate_sidecar(
    directory: str | Path,
    certificate: dict[str, Any],
) -> dict[str, Any]:
    """Bind a verified in-memory certificate to every staged run artifact."""

    root = Path(directory).expanduser().resolve()
    target = root / HF_CERTIFICATE_SIDECAR
    if target.exists():
        raise FileExistsError(f"HF certificate sidecar already exists: {target}.")
    if not _certificate_digest_valid(certificate):
        raise ValueError("HF single-run certificate digest or schema is invalid.")
    artifacts = _artifact_records(root)
    payload = {
        "schema_version": _SIDECAR_SCHEMA,
        "model_id": _MODEL_ID,
        "units": "SI",
        "certificate": certificate,
        "artifacts": artifacts,
        "artifact_set_sha256": _canonical_sha256(artifacts),
    }
    write_json(target, payload)
    return payload


def read_hf_certificate_sidecar(
    directory: str | Path,
    *,
    require_full: bool = False,
) -> dict[str, Any]:
    """Read and re-verify a certificate sidecar and every bound artifact."""

    root = Path(directory).expanduser().resolve()
    target = root / HF_CERTIFICATE_SIDECAR
    if not target.is_file() or target.is_symlink():
        raise FileNotFoundError(f"HF certificate sidecar is absent: {target}.")
    payload = _strict_json(target)
    expected_fields = {
        "schema_version",
        "model_id",
        "units",
        "certificate",
        "artifacts",
        "artifact_set_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        raise ValueError("HF certificate sidecar schema fields are not exact.")
    if (
        payload["schema_version"] != _SIDECAR_SCHEMA
        or payload["model_id"] != _MODEL_ID
        or payload["units"] != "SI"
    ):
        raise ValueError("HF certificate sidecar identity is invalid.")
    certificate = payload["certificate"]
    if not _certificate_digest_valid(certificate):
        raise ValueError("HF certificate payload digest or schema is invalid.")
    artifacts = payload["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("HF certificate artifact list is empty or invalid.")
    if payload["artifact_set_sha256"] != _canonical_sha256(artifacts):
        raise ValueError("HF certificate artifact-set digest does not match.")
    seen: set[str] = set()
    artifact_by_name: dict[str, dict[str, Any]] = {}
    prior = ""
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}:
            raise ValueError("HF certificate artifact record schema is invalid.")
        relative = _validated_relative_path(item["path"])
        name = relative.as_posix()
        if name in seen or (prior and name <= prior):
            raise ValueError("HF certificate artifact paths are duplicate or unsorted.")
        seen.add(name)
        artifact_by_name[name] = item
        prior = name
        size = item["bytes"]
        digest = item["sha256"]
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError(f"Invalid artifact identity for {name}.")
        path = root.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Bound HF artifact is absent or unsafe: {name}.")
        if path.stat().st_size != size or sha256_file(path) != digest:
            raise ValueError(f"Bound HF artifact identity drifted: {name}.")
    missing = sorted(_REQUIRED_ARTIFACTS - seen)
    if missing:
        raise ValueError(f"HF certificate omits canonical artifacts: {missing}.")

    if require_full:
        if not isinstance(certificate, dict):
            raise ValueError("HF certificate payload must be an object.")
        identity = certificate.get("identity")
        checks = certificate.get("identity_checks")
        if not (
            certificate.get("model_id") == _MODEL_ID
            and certificate.get("passed") is True
            and certificate.get("full_accuracy_spec_bound") is True
            and certificate.get("certification_level")
            == "FULL_NUMERICAL_AND_GUARD_DOMAIN_CERTIFIED"
            and certificate.get("raw_result_status_pair") == _RAW_STATUS
            and certificate.get("certified_status_pair") == _CERTIFIED_STATUS
            and isinstance(checks, dict)
            and checks
            and all(value is True for value in checks.values())
            and isinstance(identity, dict)
        ):
            raise ValueError("HF run does not carry a complete independent certificate.")
        stable_pairs = (
            ("canonical_resolved_config_sha256_start", "canonical_resolved_config_sha256_end"),
            ("canonical_result_sha256_start", "canonical_result_sha256_end"),
            ("source_hash_start_sha256", "source_hash_end_sha256"),
            ("runtime_identity_start", "runtime_identity_end"),
            ("auxiliary_input_identity_start", "auxiliary_input_identity_end"),
            ("validation_spec_file_sha256_start", "validation_spec_file_sha256_end"),
        )
        for start, end in stable_pairs:
            if identity.get(start) is None or identity.get(start) != identity.get(end):
                raise ValueError(f"HF certificate identity is not stable: {start}.")
        if not isinstance(certificate.get("validation_spec_sha256"), str):
            raise ValueError("HF certificate does not bind a frozen validation spec.")
        if "hf_validation_spec.yaml" not in seen:
            raise ValueError(
                "A complete HF certificate must bind its frozen validation-spec copy."
            )
        if artifact_by_name["hf_validation_spec.yaml"]["sha256"] != identity.get(
            "validation_spec_file_sha256_start"
        ):
            raise ValueError(
                "The certified validation-spec identity does not match its bound file."
            )

        summary = _strict_json(root / "summary.json")
        execution = _strict_json(root / "execution_identity.json")
        with h5py.File(root / "result.h5", "r") as h5:
            h5_identity = {
                "model_id": str(h5.attrs.get("model", "")),
                "units": str(h5.attrs.get("units", "")),
                "physical_status": str(h5.attrs.get("physical_status", "")),
                "numerical_status": str(h5.attrs.get("numerical_status", "")),
            }
        if (
            h5_identity
            != {"model_id": _MODEL_ID, "units": "SI", **_RAW_STATUS}
            or summary.get("model") != _MODEL_ID
            or {
                "physical_status": summary.get("physical_status"),
                "numerical_status": summary.get("numerical_status"),
            }
            != _RAW_STATUS
            or execution.get("model") != _MODEL_ID
            or execution.get("source_stable_during_run") is not True
            or execution.get("config_stable_during_run") is not True
            or execution.get("auxiliary_inputs_stable_during_run") is not True
            or execution.get("source_hash_start_sha256")
            != identity.get("source_hash_start_sha256")
            or execution.get("source_hash_end_sha256")
            != identity.get("source_hash_end_sha256")
            or execution.get("config_resolved_sha256")
            != identity.get("canonical_resolved_config_sha256_start")
            or execution.get("auxiliary_inputs_start")
            != identity.get("auxiliary_input_identity_start")
            or execution.get("auxiliary_inputs_end")
            != identity.get("auxiliary_input_identity_end")
        ):
            raise ValueError("HF raw artifacts and independent certificate disagree.")
    return payload


__all__ = [
    "HF_CERTIFICATE_SIDECAR",
    "read_hf_certificate_sidecar",
    "write_hf_certificate_sidecar",
]

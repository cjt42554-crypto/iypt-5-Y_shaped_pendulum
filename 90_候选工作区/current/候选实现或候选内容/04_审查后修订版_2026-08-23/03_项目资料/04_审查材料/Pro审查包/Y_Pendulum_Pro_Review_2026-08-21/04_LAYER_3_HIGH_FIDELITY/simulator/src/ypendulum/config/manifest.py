"""Frozen experimental-validation manifest contract."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


_CLAIM_RANK = {"VALIDATED": 0, "PREDICTIVE": 1}


class _UniqueManifestLoader(yaml.SafeLoader):
    """YAML loader that refuses last-key-wins claim ambiguity."""


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ValueError("Validation-manifest mapping keys must be scalar.") from exc
        if duplicate:
            raise ValueError(f"Duplicate validation-manifest key: {key!r}.")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueManifestLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _current_model_definition_hash() -> str:
    """Hash the complete importable Python model definition, path plus bytes."""

    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _sealed_file(
    payload: dict[str, Any],
    *,
    path_field: str,
    hash_field: str,
    manifest_path: Path,
    label: str,
) -> Path:
    raw_path = payload.get(path_field)
    expected_hash = payload.get(hash_field)
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError(f"{label}.{path_field} must be a non-empty path string.")
    if not _is_sha256(expected_hash):
        raise ValueError(f"{label}.{hash_field} must be a lowercase SHA-256 digest.")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = manifest_path.parent / path
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"{label}.{path_field} does not identify a sealed file: {path}")
    actual_hash = _sha256_file(path)
    if actual_hash != expected_hash:
        raise ValueError(
            f"{label}.{path_field} hash mismatch: expected {expected_hash}, "
            f"got {actual_hash}."
        )
    return path


def _validate_run_record(
    record: Any,
    *,
    manifest_path: Path,
    model_hash: str,
    label: str,
) -> str:
    if not isinstance(record, dict):
        raise ValueError(f"{label} must be a mapping.")
    run_id = record.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError(f"{label}.run_id must be a non-empty string.")
    if record.get("sealed") is not True:
        raise ValueError(f"{label} must explicitly set sealed: true.")
    if record.get("model_definition_hash_sha256") != model_hash:
        raise ValueError(f"{label} is not bound to the manifest model definition hash.")
    _sealed_file(
        record,
        path_field="data_path",
        hash_field="data_sha256",
        manifest_path=manifest_path,
        label=label,
    )
    _sealed_file(
        record,
        path_field="result_manifest_path",
        hash_field="result_manifest_sha256",
        manifest_path=manifest_path,
        label=label,
    )
    return run_id


def _validate_metric(name: Any, metric: Any) -> None:
    if not isinstance(name, str) or not name.strip() or not isinstance(metric, dict):
        raise ValueError("Every validation metric must be a named mapping.")
    value = metric.get("value")
    threshold = metric.get("threshold")
    comparison = metric.get("comparison")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(float(threshold))
    ):
        raise ValueError(f"Metric {name!r} requires finite numeric value and threshold.")
    if comparison == "less_than_or_equal":
        recomputed = float(value) <= float(threshold)
    elif comparison == "greater_than_or_equal":
        recomputed = float(value) >= float(threshold)
    else:
        raise ValueError(
            f"Metric {name!r} comparison must be less_than_or_equal or "
            "greater_than_or_equal."
        )
    if metric.get("passed") is not True or not recomputed:
        raise ValueError(f"Metric {name!r} did not pass its frozen threshold.")


@dataclass(frozen=True)
class ValidationManifestAudit:
    path: Path
    claim_level: str
    frozen: bool
    passed: bool
    calibration_run_count: int
    validation_run_count: int
    metric_count: int
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "claim_level": self.claim_level,
            "frozen": self.frozen,
            "passed": self.passed,
            "calibration_run_count": self.calibration_run_count,
            "validation_run_count": self.validation_run_count,
            "metric_count": self.metric_count,
        }


def resolve_validation_manifest_path(value: str, *, config_source: Path | None) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() and config_source is not None:
        path = config_source.parent / path
    return path.resolve()


def load_validation_manifest(
    value: str,
    *,
    config_source: Path | None = None,
    requested_claim: str | None = None,
) -> ValidationManifestAudit:
    path = resolve_validation_manifest_path(value, config_source=config_source)
    if not path.is_file():
        raise ValueError(f"Validation manifest does not exist: {path}")
    payload = yaml.load(
        path.read_text(encoding="utf-8"), Loader=_UniqueManifestLoader
    )
    if not isinstance(payload, dict):
        raise ValueError("Validation manifest root must be a mapping.")
    required = {
        "schema_version",
        "frozen",
        "passed",
        "claim_level",
        "frozen_at_utc",
        "model_definition_hash_sha256",
        "calibration_runs",
        "validation_runs",
        "metrics",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ValueError(f"Validation manifest is missing required fields: {missing}")
    if str(payload["schema_version"]) != "1.1":
        raise ValueError("Unsupported validation manifest schema_version.")
    claim = str(payload["claim_level"])
    if claim not in _CLAIM_RANK:
        raise ValueError("Validation manifest claim_level must be VALIDATED or PREDICTIVE.")
    if payload["frozen"] is not True:
        raise ValueError("Validation manifest must explicitly set frozen: true.")
    if payload["passed"] is not True:
        raise ValueError("Validation manifest does not record a passed validation campaign.")
    frozen_at = payload["frozen_at_utc"]
    if not isinstance(frozen_at, str):
        raise ValueError("frozen_at_utc must be an ISO-8601 string.")
    try:
        parsed_frozen_at = datetime.fromisoformat(frozen_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("frozen_at_utc must be a valid ISO-8601 timestamp.") from exc
    if parsed_frozen_at.tzinfo is None:
        raise ValueError("frozen_at_utc must include an explicit timezone.")
    for name in ("calibration_runs", "validation_runs"):
        if not isinstance(payload[name], list):
            raise ValueError(f"Validation manifest {name} must be a list.")
    if not payload["validation_runs"]:
        raise ValueError("Validation manifest must contain at least one sealed validation run.")
    if not isinstance(payload["metrics"], dict) or not payload["metrics"]:
        raise ValueError("Validation manifest must contain quantitative metrics.")
    digest = payload["model_definition_hash_sha256"]
    if not _is_sha256(digest):
        raise ValueError(
            "model_definition_hash_sha256 must be a lowercase SHA-256 digest."
        )
    current_model_hash = _current_model_definition_hash()
    if digest != current_model_hash:
        raise ValueError(
            "Validation manifest model_definition_hash_sha256 does not match the "
            f"currently executing model definition ({current_model_hash})."
        )
    run_ids: set[str] = set()
    for collection_name in ("calibration_runs", "validation_runs"):
        for index, record in enumerate(payload[collection_name]):
            label = f"{collection_name}[{index}]"
            run_id = _validate_run_record(
                record,
                manifest_path=path,
                model_hash=digest,
                label=label,
            )
            if run_id in run_ids:
                raise ValueError(f"Duplicate sealed campaign run_id: {run_id!r}.")
            run_ids.add(run_id)
    for metric_name, metric in payload["metrics"].items():
        _validate_metric(metric_name, metric)
    if requested_claim in _CLAIM_RANK and _CLAIM_RANK[claim] < _CLAIM_RANK[requested_claim]:
        raise ValueError(
            f"Manifest supports {claim}, which is below requested {requested_claim}."
        )
    if requested_claim == "PREDICTIVE":
        pressure = payload.get("predictive_scope")
        if not isinstance(pressure, dict) or not pressure.get("unseen_conditions_passed", False):
            raise ValueError(
                "PREDICTIVE claim requires predictive_scope.unseen_conditions_passed: true."
            )
        if not any(
            record.get("geometry_was_unseen") is True
            for record in payload["validation_runs"]
        ):
            raise ValueError(
                "PREDICTIVE claim requires at least one sealed validation run with "
                "geometry_was_unseen: true."
            )
    return ValidationManifestAudit(
        path=path,
        claim_level=claim,
        frozen=True,
        passed=True,
        calibration_run_count=len(payload["calibration_runs"]),
        validation_run_count=len(payload["validation_runs"]),
        metric_count=len(payload["metrics"]),
        payload=payload,
    )

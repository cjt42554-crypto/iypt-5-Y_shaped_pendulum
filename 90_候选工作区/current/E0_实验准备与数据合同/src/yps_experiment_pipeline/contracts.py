"""Strict JSON contracts and provenance helpers for E0."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

STAGE_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = STAGE_ROOT / "schemas"
TEMPLATE_ROOT = STAGE_ROOT / "templates"
STAGE_RELATIVE = Path("90_候选工作区/current/E0_实验准备与数据合同")

TEMPLATE_SCHEMA_MAP = {
    "apparatus_measurements.template.json": "apparatus_measurements.schema.json",
    "material_test_manifest.template.json": "material_test_manifest.schema.json",
    "camera_rig.template.json": "camera_rig.schema.json",
    "first_round_plan.template.json": "experiment_run.schema.json",
    "pilot_attempts.template.json": "acquisition_attempts.schema.json",
}


class ContractError(ValueError):
    """Raised when an E0 machine contract fails closed."""


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_document(value: Any) -> str:
    """Hash a JSON-compatible value in the repository's canonical form."""

    return sha256(canonical_json_bytes(value)).hexdigest()


def load_schema(name: str, *, schema_root: Path = SCHEMA_ROOT) -> dict[str, Any]:
    path = schema_root / name
    if not path.is_file():
        raise ContractError(f"schema not found: {name}")
    schema = load_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validation_errors(
    schema_name: str,
    document: Any,
    *,
    schema_root: Path = SCHEMA_ROOT,
) -> list[str]:
    validator = Draft202012Validator(load_schema(schema_name, schema_root=schema_root))
    errors = []
    for error in sorted(validator.iter_errors(document), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"{location}: {error.message}")
    return errors


def validate_document(
    schema_name: str,
    document: Any,
    *,
    schema_root: Path = SCHEMA_ROOT,
) -> None:
    errors = validation_errors(schema_name, document, schema_root=schema_root)
    if errors:
        raise ContractError("; ".join(errors))
    if schema_name == "apparatus_measurements.schema.json":
        _validate_apparatus_shapes(document)
    if schema_name == "acquisition_attempts.schema.json":
        _validate_attempt_lineage(document)
    if schema_name == "model_input_binding.schema.json":
        _validate_model_input_provenance(document)
    if document.get("data_origin") in {
        "MEASURED_BUNDLE",
        "MEASURED_CALIBRATION",
        "MEASURED_ACQUISITION",
    }:
        assert_no_unset_tokens(document)


def validate_all_templates(
    *,
    schema_root: Path = SCHEMA_ROOT,
    template_root: Path = TEMPLATE_ROOT,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for template_name, schema_name in sorted(TEMPLATE_SCHEMA_MAP.items()):
        document = load_json(template_root / template_name)
        validate_document(schema_name, document, schema_root=schema_root)
        result[template_name] = "VALID"
    return result


def iter_source_types(value: Any):
    if isinstance(value, dict):
        if "source_type" in value:
            yield value
        for child in value.values():
            yield from iter_source_types(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_source_types(child)


def iter_values(value: Any):
    if isinstance(value, dict):
        for child in value.values():
            yield from iter_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_values(child)
    else:
        yield value


def assert_no_unset_tokens(document: Any) -> None:
    """A document claiming real acquisition may not retain template sentinels."""

    if any(value == "UNSET_REQUIRES_HUMAN" for value in iter_values(document)):
        raise ContractError("completed measured document retains UNSET_REQUIRES_HUMAN")


def _validate_apparatus_shapes(document: Any) -> None:
    """Enforce vector dimensions that JSON Schema cannot relate to label counts."""

    for record in document.get("measurements", []):
        measurement_id = record.get("measurement_id", "<unknown>")
        kind = record.get("value_kind")
        labels = record.get("component_labels", [])
        if kind == "SCALAR":
            if labels:
                raise ContractError(f"{measurement_id}: scalar measurement has component labels")
            scalar_values = [record.get("value_si"), *record.get("raw_repeats", [])]
            scalar_values.extend(
                record.get(key)
                for key in (
                    "type_a_standard_uncertainty",
                    "type_b_standard_uncertainty",
                    "combined_standard_uncertainty",
                )
            )
            if any(value is not None and not np.isfinite(value) for value in scalar_values):
                raise ContractError(
                    f"{measurement_id}: scalar measurement contains non-finite data"
                )
            if any(
                record.get(key) is not None and record[key] < 0
                for key in (
                    "type_a_standard_uncertainty",
                    "type_b_standard_uncertainty",
                    "combined_standard_uncertainty",
                )
            ):
                raise ContractError(f"{measurement_id}: uncertainty must be non-negative")
            continue
        if kind != "VECTOR":
            continue
        dimension = len(labels)
        if dimension < 2:
            raise ContractError(f"{measurement_id}: vector measurement needs component labels")
        for key in (
            "value_si",
            "type_a_standard_uncertainty",
            "type_b_standard_uncertainty",
            "combined_standard_uncertainty",
        ):
            value = record.get(key)
            if value is not None and (not isinstance(value, list) or len(value) != dimension):
                raise ContractError(f"{measurement_id}: {key} dimension does not match labels")
            if value is not None and not np.all(np.isfinite(np.asarray(value, dtype=float))):
                raise ContractError(f"{measurement_id}: {key} contains non-finite data")
            if key != "value_si" and value is not None and np.any(np.asarray(value) < 0):
                raise ContractError(f"{measurement_id}: uncertainty must be non-negative")
        for repeat in record.get("raw_repeats", []):
            if not isinstance(repeat, list) or len(repeat) != dimension:
                raise ContractError(f"{measurement_id}: repeat dimension does not match labels")
            if not np.all(np.isfinite(np.asarray(repeat, dtype=float))):
                raise ContractError(f"{measurement_id}: repeat contains non-finite data")
        covariance = record.get("covariance_si")
        if covariance is not None:
            if len(covariance) != dimension or any(
                not isinstance(row, list) or len(row) != dimension for row in covariance
            ):
                raise ContractError(f"{measurement_id}: covariance shape does not match labels")
            matrix = np.asarray(covariance, dtype=float)
            if not np.all(np.isfinite(matrix)):
                raise ContractError(f"{measurement_id}: covariance contains non-finite data")
            if np.max(np.abs(matrix - matrix.T)) > 1e-12:
                raise ContractError(f"{measurement_id}: covariance must be symmetric")
            if float(np.min(np.linalg.eigvalsh(matrix))) < -1e-12:
                raise ContractError(f"{measurement_id}: covariance must be positive semidefinite")


def _validate_attempt_lineage(document: Any) -> None:
    """Require unique attempts and an explicit failed parent for every retry."""

    attempts = document.get("attempts", [])
    by_id = {attempt.get("attempt_id"): attempt for attempt in attempts}
    if len(by_id) != len(attempts):
        raise ContractError("attempt_id values must be unique")
    for attempt in attempts:
        parent_id = attempt.get("retry_parent_id")
        if parent_id is None:
            continue
        parent = by_id.get(parent_id)
        if parent is None:
            raise ContractError(f"retry parent is absent from ledger: {parent_id}")
        if parent.get("status") not in {"FAILED", "ABORTED"}:
            raise ContractError(f"retry parent is not a failed attempt: {parent_id}")
        if parent.get("slot_id") != attempt.get("slot_id"):
            raise ContractError(f"retry changes acquisition slot: {parent_id}")
        if parent.get("repeat_index") != attempt.get("repeat_index"):
            raise ContractError(f"retry changes repeat index: {parent_id}")


def _validate_model_input_provenance(document: Any) -> None:
    evidence = document.get("compatibility_evidence")
    if sha256_document(evidence) != document.get("compatibility_evidence_sha256"):
        raise ContractError("compatibility evidence hash does not match its content")
    bundle_hash = document.get("measurement_bundle_sha256")
    bindings = document.get("parameter_bindings", [])
    names = [record.get("parameter_name") for record in bindings]
    if len(names) != len(set(names)):
        raise ContractError("parameter bindings contain duplicate names")
    if any(record.get("measurement_bundle_sha256") != bundle_hash for record in bindings):
        raise ContractError("parameter binding points to a different measurement bundle")
    if document.get("compatibility_status") == "READY_FOR_FORMAL_RUN" and document.get(
        "missing_fields"
    ):
        raise ContractError("ready model input binding still contains missing fields")


def assert_no_fake_measurements(document: Any) -> None:
    """Reject measured claims without a real raw-data binding."""

    for record in iter_source_types(document):
        source_type = record.get("source_type")
        if source_type == "MEASURED":
            digest = record.get("raw_data_sha256")
            repeats = record.get("raw_repeats")
            if not isinstance(digest, str) or len(digest) != 64:
                raise ContractError("MEASURED record lacks raw_data_sha256")
            if not isinstance(repeats, list) or not repeats:
                raise ContractError("MEASURED record lacks raw_repeats")
        if source_type == "UNSET_REQUIRES_HUMAN" and record.get("value_si") is not None:
            raise ContractError("UNSET_REQUIRES_HUMAN record contains value_si")


def assert_templates_are_human_unset(*, template_root: Path = TEMPLATE_ROOT) -> None:
    for template_name in TEMPLATE_SCHEMA_MAP:
        document = load_json(template_root / template_name)
        assert_no_fake_measurements(document)
        encoded = canonical_json_bytes(document)
        if b'"source_type":"MEASURED"' in encoded:
            raise ContractError(f"template contains MEASURED claim: {template_name}")

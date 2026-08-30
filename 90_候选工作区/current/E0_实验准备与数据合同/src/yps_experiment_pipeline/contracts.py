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


def assert_array_manifest_matches(
    arrays: dict[str, np.ndarray],
    fields: dict[str, Any],
    *,
    label: str,
) -> None:
    """Bind an actual NPZ payload to the shape and dtype declared by its manifest."""

    if set(arrays) != set(fields):
        missing = sorted(set(fields) - set(arrays))
        extra = sorted(set(arrays) - set(fields))
        raise ContractError(f"{label} field set mismatch; missing={missing} extra={extra}")
    mismatched = []
    for name, value in arrays.items():
        array = np.asarray(value)
        declaration = fields[name]
        if list(array.shape) != declaration.get("shape") or str(array.dtype) != declaration.get(
            "dtype"
        ):
            mismatched.append(name)
    if mismatched:
        raise ContractError(f"{label} shape or dtype differs from its manifest: {mismatched}")


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
    if schema_name == "detection_2d_bundle.schema.json":
        _validate_detection_manifest_shapes(document)
    if schema_name == "trajectory_bundle.schema.json":
        _validate_trajectory_manifest_shapes(document)
    if schema_name == "processed_observables.schema.json":
        _validate_common_manifest_shapes(document)
    if schema_name == "model_input_binding.schema.json":
        _validate_model_input_provenance(document)
    if document.get("data_origin") in {
        "MEASURED",
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


def _field_shapes(document: Any, expected_fields: set[str]) -> dict[str, list[int]]:
    fields = document.get("fields", {})
    if set(fields) != expected_fields:
        missing = sorted(expected_fields - set(fields))
        extra = sorted(set(fields) - expected_fields)
        raise ContractError(f"array field manifest mismatch; missing={missing} extra={extra}")
    return {name: fields[name].get("shape") for name in expected_fields}


def _validate_detection_manifest_shapes(document: Any) -> None:
    expected = {
        "time_s",
        "frame_index",
        "raw_timestamp_s",
        "aligned_timestamp_s",
        "sync_event_id",
        "sync_offset_s",
        "sync_uncertainty_s",
        "dropped_frame_flag",
        "pixels_px",
        "pixel_covariance_px2",
        "valid_mask",
        "occlusion_mask",
        "detection_score",
        "invalid_reason",
    }
    shapes = _field_shapes(document, expected)
    sample_count = document.get("sample_count")
    camera_count = len(document.get("camera_ids", []))
    marker_count = len(document.get("marker_ids", []))
    expected_shapes = {
        "time_s": [sample_count],
        "frame_index": [sample_count, camera_count],
        "raw_timestamp_s": [sample_count, camera_count],
        "aligned_timestamp_s": [sample_count, camera_count],
        "sync_event_id": [sample_count, camera_count],
        "sync_offset_s": [sample_count, camera_count],
        "sync_uncertainty_s": [sample_count, camera_count],
        "dropped_frame_flag": [sample_count, camera_count],
        "pixels_px": [sample_count, camera_count, marker_count, 2],
        "pixel_covariance_px2": [sample_count, camera_count, marker_count, 2, 2],
        "valid_mask": [sample_count, camera_count, marker_count],
        "occlusion_mask": [sample_count, camera_count, marker_count],
        "detection_score": [sample_count, camera_count, marker_count],
        "invalid_reason": [sample_count, camera_count, marker_count],
    }
    mismatched = sorted(name for name in expected if shapes[name] != expected_shapes[name])
    if mismatched:
        raise ContractError(f"detection field shapes do not match declared axes: {mismatched}")


def _validate_trajectory_manifest_shapes(document: Any) -> None:
    expected = {
        "time_s",
        "r_bob_W_m",
        "r_junction_W_m",
        "branch_marker_positions_W_m",
        "bob_orientation_WB",
        "position_covariance",
        "valid_mask",
        "occlusion_mask",
        "event_annotations",
    }
    shapes = _field_shapes(document, expected)
    sample_count = document.get("sample_count")
    exact = {
        "time_s": [sample_count],
        "r_bob_W_m": [sample_count, 3],
        "r_junction_W_m": [sample_count, 3],
        "bob_orientation_WB": [sample_count, 3, 3],
        "position_covariance": [sample_count, 2, 3, 3],
        "valid_mask": [sample_count],
        "occlusion_mask": [sample_count, 2],
        "event_annotations": [sample_count],
    }
    mismatched = sorted(name for name, shape in exact.items() if shapes[name] != shape)
    branch_shape = shapes["branch_marker_positions_W_m"]
    if not (
        isinstance(branch_shape, list)
        and len(branch_shape) == 3
        and branch_shape[0] == sample_count
        and isinstance(branch_shape[1], int)
        and branch_shape[1] >= 3
        and branch_shape[2] == 3
    ):
        mismatched.append("branch_marker_positions_W_m")
    if mismatched:
        raise ContractError(f"trajectory field shapes do not match declared axes: {mismatched}")


def _validate_common_manifest_shapes(document: Any) -> None:
    expected = {
        "time_s",
        "r_bob_W_m",
        "r_junction_W_m",
        "modal_basis_W",
        "q_fast_m",
        "q_slow_m",
        "resonant_phase_rad",
        "valid_mask",
    }
    shapes = _field_shapes(document, expected)
    sample_count = document.get("sample_count")
    exact = {
        "time_s": [sample_count],
        "r_bob_W_m": [sample_count, 3],
        "r_junction_W_m": [sample_count, 3],
        "modal_basis_W": [2, 3],
        "q_fast_m": [sample_count],
        "q_slow_m": [sample_count],
        "resonant_phase_rad": [sample_count],
        "valid_mask": [sample_count],
    }
    mismatched = sorted(name for name in expected if shapes[name] != exact[name])
    if mismatched:
        raise ContractError(f"common field shapes do not match declared axes: {mismatched}")


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
    """Cross-bind preregistered slots, actual attempts, retries and stop dispositions."""

    attempts = document.get("attempts", [])
    by_id = {attempt.get("attempt_id"): attempt for attempt in attempts}
    if len(by_id) != len(attempts):
        raise ContractError("attempt_id values must be unique")

    planned_slots = document.get("planned_slots", [])
    slot_keys = [(slot.get("slot_id"), slot.get("repeat_index")) for slot in planned_slots]
    if len(set(slot_keys)) != len(slot_keys):
        raise ContractError("planned slot and repeat pairs must be unique")
    slots_by_key = dict(zip(slot_keys, planned_slots, strict=True))

    linked_ids: list[str] = []
    for slot in planned_slots:
        key = (slot.get("slot_id"), slot.get("repeat_index"))
        slot_linked_ids = slot.get("linked_attempt_ids", [])
        slot_attempts = []
        for attempt_id in slot_linked_ids:
            attempt = by_id.get(attempt_id)
            if attempt is None:
                raise ContractError(f"planned slot links an absent attempt: {attempt_id}")
            if (attempt.get("slot_id"), attempt.get("repeat_index")) != key:
                raise ContractError(
                    f"planned slot links an attempt from another slot: {attempt_id}"
                )
            if attempt.get("operation") != slot.get("operation"):
                raise ContractError(
                    f"attempt operation differs from its planned slot: {attempt_id}"
                )
            if attempt.get("release_target_id") != slot.get("release_target_id"):
                raise ContractError(
                    f"attempt release target differs from its planned slot: {attempt_id}"
                )
            slot_attempts.append(attempt)
            linked_ids.append(attempt_id)

        state = slot.get("state")
        final_attempt = slot_attempts[-1] if slot_attempts else None
        if state == "IN_PROGRESS" and (
            final_attempt is None or final_attempt.get("status") != "IN_PROGRESS"
        ):
            raise ContractError(f"in-progress slot lacks a final in-progress attempt: {key}")
        if state == "COMPLETED" and (
            final_attempt is None or final_attempt.get("status") != "COMPLETED"
        ):
            raise ContractError(f"completed slot lacks a final completed attempt: {key}")
        if state == "RETRY_PENDING" and (
            final_attempt is None
            or final_attempt.get("status") not in {"FAILED", "ABORTED"}
            or final_attempt.get("attempt_id") != slot.get("governing_attempt_id")
        ):
            raise ContractError(
                f"retry-pending slot does not bind its latest failed attempt: {key}"
            )
        expected_final_status = {
            "FAILED_FINAL": "FAILED",
            "ABORTED_FINAL": "ABORTED",
        }.get(state)
        if expected_final_status is not None:
            governing_id = slot.get("governing_attempt_id")
            if (
                final_attempt is None
                or final_attempt.get("status") != expected_final_status
                or final_attempt.get("attempt_id") != governing_id
            ):
                raise ContractError(f"terminal slot does not bind its final attempt: {key}")

        governing_id = slot.get("governing_attempt_id")
        if governing_id is not None:
            governing = by_id.get(governing_id)
            if governing is None or governing.get("status") not in {"FAILED", "ABORTED"}:
                raise ContractError(f"slot disposition lacks a failed governing attempt: {key}")
            failure = governing.get("failure") or {}
            if failure.get("reason_code") != slot.get("disposition_reason_code"):
                raise ContractError(
                    f"slot disposition reason differs from governing attempt: {key}"
                )

    if len(linked_ids) != len(set(linked_ids)):
        raise ContractError("an actual attempt is linked from more than one planned slot")
    if set(linked_ids) != set(by_id):
        raise ContractError("every actual attempt must be linked from exactly one planned slot")

    apparatus_revision = document.get("apparatus_revision")
    for attempt in attempts:
        attempt_id = attempt.get("attempt_id")
        key = (attempt.get("slot_id"), attempt.get("repeat_index"))
        if key not in slots_by_key:
            raise ContractError(f"attempt has no preregistered slot: {attempt_id}")
        if attempt.get("apparatus_revision") != apparatus_revision:
            raise ContractError(f"attempt apparatus revision differs from campaign: {attempt_id}")
        raw_files = attempt.get("raw_files", [])
        evidence_state = attempt.get("evidence_state")
        if not raw_files and evidence_state != "NO_RAW_DATA_CREATED":
            raise ContractError(
                f"attempt without raw files has an invalid evidence state: {attempt_id}"
            )
        if raw_files and evidence_state == "NO_RAW_DATA_CREATED":
            raise ContractError(f"attempt with raw files claims no raw evidence: {attempt_id}")

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
        slot = slots_by_key[key]
        slot_ids = slot.get("linked_attempt_ids", [])
        if slot_ids.index(parent_id) >= slot_ids.index(attempt_id):
            raise ContractError(f"retry appears before its parent in slot lineage: {attempt_id}")

    campaign_status = document.get("campaign_status")
    states = {slot.get("state") for slot in planned_slots}
    if campaign_status == "NOT_STARTED" and (attempts or states != {"PENDING"}):
        raise ContractError("not-started campaign must contain only pending slots and no attempts")
    if campaign_status == "IN_PROGRESS" and not states.intersection(
        {"PENDING", "RETRY_PENDING", "IN_PROGRESS"}
    ):
        raise ContractError("in-progress campaign must retain a pending or active slot")
    if campaign_status == "HARD_STOPPED":
        if states.intersection({"PENDING", "RETRY_PENDING", "IN_PROGRESS"}):
            raise ContractError("hard-stopped campaign cannot retain pending or active slots")
        if "NOT_STARTED_DUE_TO_STOP" not in states:
            raise ContractError(
                "hard-stopped campaign must identify slots not started due to the stop"
            )
    if campaign_status == "COMPLETED" and states.intersection(
        {"PENDING", "RETRY_PENDING", "IN_PROGRESS", "NOT_STARTED_DUE_TO_STOP"}
    ):
        raise ContractError("completed campaign retains a non-terminal or hard-stop slot")


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
    for record in bindings:
        if record.get("source_type") != "DERIVED_FROM_MEASURED":
            continue
        derivation = record.get("derivation")
        if not isinstance(derivation, dict):
            raise ContractError("derived parameter binding lacks derivation content")
        if sha256_document(derivation) != record.get("derivation_sha256"):
            raise ContractError("derivation hash does not match its content")
        if derivation.get("input_measurement_ids") != record.get("measurement_ids"):
            raise ContractError("derivation inputs differ from parameter measurement IDs")
        if derivation.get("input_record_sha256") != record.get("source_record_sha256"):
            raise ContractError("derivation input hash differs from cited measurement records")
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

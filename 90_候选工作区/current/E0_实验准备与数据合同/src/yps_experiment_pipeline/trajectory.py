"""Trajectory bundle identity, masking and NPZ/JSON separation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .contracts import (
    SCHEMA_ROOT,
    assert_array_manifest_matches,
    assert_no_unset_tokens,
    canonical_json_bytes,
    load_json,
    sha256_file,
    validate_document,
)
from .detections import validate_detection_arrays

DOMAIN_EXIT_EVENTS = {"SLACK", "RE_TENSION", "NEAR_CONTACT", "CONTACT", "MODEL_GUARD"}
REQUIRED_ARRAY_FIELDS = {
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


def validate_trajectory_arrays(
    arrays: dict[str, np.ndarray],
    units: dict[str, str],
    valid_mask: np.ndarray,
) -> np.ndarray:
    missing = sorted(REQUIRED_ARRAY_FIELDS - set(arrays))
    extra = sorted(set(arrays) - REQUIRED_ARRAY_FIELDS)
    if missing or extra:
        raise ValueError(f"trajectory array contract mismatch; missing={missing} extra={extra}")
    if set(units) != set(arrays):
        raise ValueError("trajectory units must have exactly one entry per array")
    valid = np.asarray(valid_mask, dtype=bool)
    if valid.ndim != 1 or valid.size == 0:
        raise ValueError("valid_mask must be a non-empty one-dimensional array")
    for name, value in arrays.items():
        array = np.asarray(value)
        if array.ndim == 0 or array.shape[0] != valid.size:
            raise ValueError(f"trajectory array has incompatible sample axis: {name}")
    stored_valid = np.asarray(arrays["valid_mask"], dtype=bool)
    if stored_valid.shape != valid.shape or not np.array_equal(stored_valid, valid):
        raise ValueError("stored valid_mask does not match manifest valid_mask")
    time = np.asarray(arrays["time_s"], dtype=float)
    if not np.all(np.isfinite(time)) or not np.all(np.diff(time) > 0):
        raise ValueError("time_s must be finite and strictly increasing")
    bob = np.asarray(arrays["r_bob_W_m"], dtype=float)
    junction = np.asarray(arrays["r_junction_W_m"], dtype=float)
    branch_markers = np.asarray(arrays["branch_marker_positions_W_m"], dtype=float)
    orientation = np.asarray(arrays["bob_orientation_WB"], dtype=float)
    covariance = np.asarray(arrays["position_covariance"], dtype=float)
    occlusion = np.asarray(arrays["occlusion_mask"], dtype=bool)
    annotations = np.asarray(arrays["event_annotations"])
    if bob.shape != (valid.size, 3) or junction.shape != (valid.size, 3):
        raise ValueError("bob and junction positions must have shape (sample, 3)")
    if branch_markers.ndim != 3 or branch_markers.shape[1] < 3 or branch_markers.shape[2] != 3:
        raise ValueError("branch markers must have shape (sample, marker>=3, 3)")
    if orientation.shape != (valid.size, 3, 3):
        raise ValueError("bob orientation must have shape (sample, 3, 3)")
    if covariance.shape != (valid.size, 2, 3, 3):
        raise ValueError("position covariance must have shape (sample, 2, 3, 3)")
    if occlusion.shape != (valid.size, 2):
        raise ValueError("trajectory occlusion mask must have shape (sample, 2)")
    if annotations.shape != (valid.size,):
        raise ValueError("event annotations must have shape (sample,)")
    if not (
        np.all(np.isfinite(bob[valid]))
        and np.all(np.isfinite(junction[valid]))
        and np.all(np.isfinite(branch_markers[valid]))
        and np.all(np.isfinite(orientation[valid]))
        and np.all(np.isfinite(covariance[valid]))
    ):
        raise ValueError("trajectory arrays must be finite on valid samples")
    selected_orientation = orientation[valid]
    if selected_orientation.size:
        orthogonality_error = np.max(
            np.abs(np.swapaxes(selected_orientation, -1, -2) @ selected_orientation - np.eye(3))
        )
        determinants = np.linalg.det(selected_orientation)
        if orthogonality_error > 1e-8 or np.max(np.abs(determinants - 1.0)) > 1e-8:
            raise ValueError("bob orientations must be members of SO(3)")
    selected_covariance = covariance[valid]
    if selected_covariance.size:
        if np.max(np.abs(selected_covariance - np.swapaxes(selected_covariance, -1, -2))) > 1e-12:
            raise ValueError("position covariance must be symmetric")
        if float(np.min(np.linalg.eigvalsh(selected_covariance))) < -1e-12:
            raise ValueError("position covariance must be positive semidefinite")
    return valid


def mask_after_first_domain_event(
    time_s: np.ndarray,
    base_valid: np.ndarray,
    events: list[dict[str, Any]],
) -> tuple[np.ndarray, float | None]:
    time = np.asarray(time_s, dtype=float)
    valid = np.asarray(base_valid, dtype=bool).copy()
    if time.ndim != 1 or valid.shape != time.shape:
        raise ValueError("time and valid mask must have common one-dimensional shape")
    if not np.all(np.isfinite(time)) or not np.all(np.diff(time) > 0):
        raise ValueError("time must be finite and strictly increasing")
    event_times = [
        float(event["time_s"])
        for event in events
        if event.get("code") in DOMAIN_EXIT_EVENTS and np.isfinite(event.get("time_s", np.nan))
    ]
    if not event_times:
        return valid, None
    first = min(event_times)
    valid &= time < first
    return valid, first


def bundle_manifest(
    *,
    run_id: str,
    attempt_id: str,
    apparatus_revision: str,
    data_origin: str,
    detection_manifest: dict[str, Any],
    detection_manifest_file: Path,
    camera_rig_sha256: str,
    array_file: Path,
    arrays: dict[str, np.ndarray],
    units: dict[str, str],
    valid_mask: np.ndarray,
    event_codes: list[str],
) -> dict[str, Any]:
    valid = validate_trajectory_arrays(arrays, units, valid_mask)
    fields = {}
    for name, value in sorted(arrays.items()):
        array = np.asarray(value)
        fields[name] = {"shape": list(array.shape), "unit": units[name], "dtype": str(array.dtype)}
    return {
        "schema_id": "YPS-E0-TRAJECTORY-BUNDLE-1.2",
        "data_origin": data_origin,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "apparatus_revision": apparatus_revision,
        "source_detection_schema_id": detection_manifest["schema_id"],
        "detection_manifest_file": detection_manifest_file.name,
        "detection_manifest_sha256": sha256_file(detection_manifest_file),
        "camera_rig_sha256": camera_rig_sha256,
        "array_file": array_file.name,
        "array_sha256": sha256_file(array_file),
        "fields": fields,
        "sample_count": int(valid.size),
        "valid_fraction": float(np.mean(valid)),
        "position_covariance_marker_ids": ["BOB", "JUNCTION"],
        "covariance_convention": "WORLD_XYZ_3X3_PER_BOB_AND_JUNCTION_SAMPLE",
        "event_codes": list(event_codes),
    }


def write_bundle(
    output_directory: Path,
    *,
    run_id: str,
    attempt_id: str,
    apparatus_revision: str,
    data_origin: str,
    detection_manifest_file: Path,
    camera_rig_sha256: str,
    arrays: dict[str, np.ndarray],
    units: dict[str, str],
    valid_mask: np.ndarray,
    event_codes: list[str],
    schema_root: Path = SCHEMA_ROOT,
) -> dict[str, Any]:
    validate_trajectory_arrays(arrays, units, valid_mask)
    if not detection_manifest_file.is_file():
        raise ValueError("source 2D detection manifest does not exist")
    detection_manifest = load_json(detection_manifest_file)
    validate_document(
        "detection_2d_bundle.schema.json",
        detection_manifest,
        schema_root=schema_root,
    )
    expected_identity = {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "apparatus_revision": apparatus_revision,
        "camera_rig_sha256": camera_rig_sha256,
        "data_origin": data_origin,
    }
    mismatched = sorted(
        key for key, value in expected_identity.items() if detection_manifest.get(key) != value
    )
    if mismatched:
        raise ValueError(
            "source 2D detection identity does not match trajectory: " + ", ".join(mismatched)
        )
    detection_array_file = detection_manifest_file.parent / detection_manifest["array_file"]
    if not detection_array_file.is_file():
        raise ValueError("source 2D detection array does not exist")
    if sha256_file(detection_array_file) != detection_manifest["array_sha256"]:
        raise ValueError("source 2D detection array hash does not match its manifest")
    with np.load(detection_array_file, allow_pickle=False) as loaded:
        detection_arrays = {name: loaded[name] for name in loaded.files}
    assert_array_manifest_matches(
        detection_arrays,
        detection_manifest["fields"],
        label="source 2D detection array",
    )
    validate_detection_arrays(
        detection_arrays,
        camera_ids=detection_manifest["camera_ids"],
        marker_ids=detection_manifest["marker_ids"],
    )
    if detection_manifest["sample_count"] != np.asarray(arrays["time_s"]).size:
        raise ValueError("source 2D detection and trajectory sample counts differ")
    if not np.array_equal(
        np.asarray(detection_arrays["time_s"], dtype=float),
        np.asarray(arrays["time_s"], dtype=float),
    ):
        raise ValueError("source 2D detection and trajectory time axes differ")
    if data_origin == "MEASURED":
        assert_no_unset_tokens(expected_identity)
    output_directory.mkdir(parents=True, exist_ok=False)
    array_file = output_directory / "trajectory.npz"
    np.savez_compressed(array_file, **arrays)
    manifest = bundle_manifest(
        run_id=run_id,
        attempt_id=attempt_id,
        apparatus_revision=apparatus_revision,
        data_origin=data_origin,
        detection_manifest=detection_manifest,
        detection_manifest_file=detection_manifest_file,
        camera_rig_sha256=camera_rig_sha256,
        array_file=array_file,
        arrays=arrays,
        units=units,
        valid_mask=valid_mask,
        event_codes=event_codes,
    )
    if data_origin == "MEASURED":
        assert_no_unset_tokens(manifest)
    validate_document(
        "trajectory_bundle.schema.json",
        manifest,
        schema_root=schema_root,
    )
    (output_directory / "trajectory_bundle.json").write_bytes(
        canonical_json_bytes(manifest) + b"\n"
    )
    return manifest

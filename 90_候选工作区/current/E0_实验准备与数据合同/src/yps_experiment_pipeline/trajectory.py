"""Trajectory bundle identity, masking and NPZ/JSON separation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .contracts import canonical_json_bytes, sha256_file

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


def _validate_bundle_arrays(
    arrays: dict[str, np.ndarray],
    units: dict[str, str],
    valid_mask: np.ndarray,
) -> np.ndarray:
    missing = sorted(REQUIRED_ARRAY_FIELDS - set(arrays))
    if missing:
        raise ValueError(f"trajectory bundle lacks required arrays: {missing}")
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
    data_origin: str,
    array_file: Path,
    arrays: dict[str, np.ndarray],
    units: dict[str, str],
    valid_mask: np.ndarray,
    event_codes: list[str],
) -> dict[str, Any]:
    valid = _validate_bundle_arrays(arrays, units, valid_mask)
    fields = {}
    for name, value in sorted(arrays.items()):
        array = np.asarray(value)
        fields[name] = {"shape": list(array.shape), "unit": units[name], "dtype": str(array.dtype)}
    return {
        "schema_id": "YPS-E0-TRAJECTORY-BUNDLE-1.0",
        "data_origin": data_origin,
        "run_id": run_id,
        "array_file": array_file.name,
        "array_sha256": sha256_file(array_file),
        "fields": fields,
        "sample_count": int(valid.size),
        "valid_fraction": float(np.mean(valid)),
        "event_codes": list(event_codes),
    }


def write_bundle(
    output_directory: Path,
    *,
    run_id: str,
    data_origin: str,
    arrays: dict[str, np.ndarray],
    units: dict[str, str],
    valid_mask: np.ndarray,
    event_codes: list[str],
) -> dict[str, Any]:
    _validate_bundle_arrays(arrays, units, valid_mask)
    output_directory.mkdir(parents=True, exist_ok=False)
    array_file = output_directory / "trajectory.npz"
    np.savez_compressed(array_file, **arrays)
    manifest = bundle_manifest(
        run_id=run_id,
        data_origin=data_origin,
        array_file=array_file,
        arrays=arrays,
        units=units,
        valid_mask=valid_mask,
        event_codes=event_codes,
    )
    (output_directory / "trajectory_bundle.json").write_bytes(
        canonical_json_bytes(manifest) + b"\n"
    )
    return manifest

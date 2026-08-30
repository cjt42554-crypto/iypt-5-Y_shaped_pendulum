"""Hash-bound 2D detections and covariance-aware stereo reconstruction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .camera import triangulate_two_view
from .contracts import canonical_json_bytes, sha256_file

REQUIRED_DETECTION_ARRAYS = {
    "time_s",
    "pixels_px",
    "pixel_covariance_px2",
    "valid_mask",
    "occlusion_mask",
    "detection_score",
}


def _assert_covariance_stack(
    covariance: np.ndarray,
    valid: np.ndarray,
    *,
    label: str,
) -> None:
    selected = np.asarray(covariance, dtype=float)[np.asarray(valid, dtype=bool)]
    if selected.size == 0:
        return
    if not np.all(np.isfinite(selected)):
        raise ValueError(f"{label} must be finite for every valid observation")
    symmetry_error = np.max(np.abs(selected - np.swapaxes(selected, -1, -2)))
    if symmetry_error > 1e-12:
        raise ValueError(f"{label} must be symmetric")
    eigenvalues = np.linalg.eigvalsh(selected)
    if float(np.min(eigenvalues)) < -1e-12:
        raise ValueError(f"{label} must be positive semidefinite")


def validate_detection_arrays(
    arrays: dict[str, np.ndarray],
    *,
    camera_ids: list[str],
    marker_ids: list[str],
) -> None:
    missing = sorted(REQUIRED_DETECTION_ARRAYS - set(arrays))
    if missing:
        raise ValueError(f"2D detection bundle lacks required arrays: {missing}")
    time = np.asarray(arrays["time_s"], dtype=float)
    if time.ndim != 1 or time.size == 0 or not np.all(np.isfinite(time)):
        raise ValueError("detection time_s must be a non-empty finite vector")
    if not np.all(np.diff(time) > 0):
        raise ValueError("detection time_s must be strictly increasing")
    shape = (time.size, len(camera_ids), len(marker_ids))
    pixels = np.asarray(arrays["pixels_px"], dtype=float)
    covariance = np.asarray(arrays["pixel_covariance_px2"], dtype=float)
    valid = np.asarray(arrays["valid_mask"], dtype=bool)
    occlusion = np.asarray(arrays["occlusion_mask"], dtype=bool)
    score = np.asarray(arrays["detection_score"], dtype=float)
    if pixels.shape != (*shape, 2):
        raise ValueError("pixels_px must have shape (sample, camera, marker, 2)")
    if covariance.shape != (*shape, 2, 2):
        raise ValueError("pixel_covariance_px2 must have shape (sample, camera, marker, 2, 2)")
    if valid.shape != shape or occlusion.shape != shape or score.shape != shape:
        raise ValueError("detection masks and score must have shape (sample, camera, marker)")
    if np.any(valid & occlusion):
        raise ValueError("an occluded detection cannot be marked valid")
    if not np.all(np.isfinite(pixels[valid])):
        raise ValueError("valid pixel coordinates must be finite")
    if not np.all(np.isfinite(score)) or np.any((score < 0) | (score > 1)):
        raise ValueError("detection_score must be finite and lie in [0, 1]")
    _assert_covariance_stack(covariance, valid, label="pixel covariance")


def _field_manifest(arrays: dict[str, np.ndarray], units: dict[str, str]) -> dict[str, Any]:
    if set(units) != set(arrays):
        raise ValueError("detection units must have exactly one entry per array")
    result: dict[str, Any] = {}
    for name, value in sorted(arrays.items()):
        array = np.asarray(value)
        result[name] = {"shape": list(array.shape), "unit": units[name], "dtype": str(array.dtype)}
    return result


def write_detection_bundle(
    output_directory: Path,
    *,
    run_id: str,
    attempt_id: str,
    apparatus_revision: str,
    data_origin: str,
    camera_rig_file: str,
    camera_rig_sha256: str,
    raw_video_files: list[dict[str, str]],
    detector: dict[str, str],
    camera_ids: list[str],
    marker_ids: list[str],
    arrays: dict[str, np.ndarray],
    units: dict[str, str],
) -> dict[str, Any]:
    """Validate first, then atomically establish an NPZ/manifest identity pair."""

    validate_detection_arrays(arrays, camera_ids=camera_ids, marker_ids=marker_ids)
    if len(raw_video_files) != len(camera_ids):
        raise ValueError("raw video list must contain one binding per camera")
    if {item["camera_id"] for item in raw_video_files} != set(camera_ids):
        raise ValueError("raw video camera IDs do not match the detection camera axis")
    output_directory.mkdir(parents=True, exist_ok=False)
    array_file = output_directory / "detections_2d.npz"
    np.savez_compressed(array_file, **arrays)
    manifest = {
        "schema_id": "YPS-E0-DETECTION-2D-BUNDLE-1.0",
        "data_origin": data_origin,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "apparatus_revision": apparatus_revision,
        "camera_rig_file": camera_rig_file,
        "camera_rig_sha256": camera_rig_sha256,
        "raw_video_files": list(raw_video_files),
        "detector": dict(detector),
        "array_file": array_file.name,
        "array_sha256": sha256_file(array_file),
        "fields": _field_manifest(arrays, units),
        "sample_count": int(np.asarray(arrays["time_s"]).size),
        "camera_ids": list(camera_ids),
        "marker_ids": list(marker_ids),
        "covariance_convention": "PIXEL_UV_2X2_PER_CAMERA_MARKER_SAMPLE",
    }
    (output_directory / "detection_2d_bundle.json").write_bytes(
        canonical_json_bytes(manifest) + b"\n"
    )
    return manifest


def triangulate_markers_with_covariance(
    pixels_px: np.ndarray,
    pixel_covariance_px2: np.ndarray,
    valid_mask: np.ndarray,
    camera_a: dict[str, Any],
    camera_b: dict[str, Any],
    *,
    finite_difference_step_px: float = 1e-4,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Propagate per-camera 2D covariance into per-marker 3D covariance.

    The stereo mapping Jacobian is evaluated numerically around the exact
    Brown--Conrady/DLT reconstruction used by this package.
    """

    pixels = np.asarray(pixels_px, dtype=float)
    covariance_2d = np.asarray(pixel_covariance_px2, dtype=float)
    valid_2d = np.asarray(valid_mask, dtype=bool)
    if pixels.ndim != 4 or pixels.shape[1] != 2 or pixels.shape[-1] != 2:
        raise ValueError("pixels_px must have shape (sample, 2, marker, 2)")
    expected_covariance_shape = (*pixels.shape[:-1], 2, 2)
    if covariance_2d.shape != expected_covariance_shape:
        raise ValueError("pixel covariance shape does not match pixels")
    if valid_2d.shape != pixels.shape[:-1]:
        raise ValueError("2D valid mask shape does not match pixels")
    if not np.isfinite(finite_difference_step_px) or finite_difference_step_px <= 0:
        raise ValueError("finite difference step must be positive and finite")
    _assert_covariance_stack(covariance_2d, valid_2d, label="pixel covariance")

    sample_count, _, marker_count, _ = pixels.shape
    points = np.full((sample_count, marker_count, 3), np.nan)
    covariance_3d = np.full((sample_count, marker_count, 3, 3), np.nan)
    valid_3d = np.zeros((sample_count, marker_count), dtype=bool)
    for sample in range(sample_count):
        for marker in range(marker_count):
            if not np.all(valid_2d[sample, :, marker]):
                continue
            observation = pixels[sample, :, marker].reshape(4)

            def reconstruct(flat_pixels: np.ndarray) -> tuple[np.ndarray, bool]:
                reconstructed, valid = triangulate_two_view(
                    flat_pixels[:2][None, :],
                    flat_pixels[2:][None, :],
                    camera_a,
                    camera_b,
                )
                return reconstructed[0], bool(valid[0])

            point, point_valid = reconstruct(observation)
            if not point_valid:
                continue
            jacobian = np.empty((3, 4), dtype=float)
            derivative_valid = True
            for component in range(4):
                plus = observation.copy()
                minus = observation.copy()
                plus[component] += finite_difference_step_px
                minus[component] -= finite_difference_step_px
                point_plus, valid_plus = reconstruct(plus)
                point_minus, valid_minus = reconstruct(minus)
                if not (valid_plus and valid_minus):
                    derivative_valid = False
                    break
                jacobian[:, component] = (point_plus - point_minus) / (
                    2.0 * finite_difference_step_px
                )
            if not derivative_valid:
                continue
            covariance_pixel = np.zeros((4, 4), dtype=float)
            covariance_pixel[:2, :2] = covariance_2d[sample, 0, marker]
            covariance_pixel[2:, 2:] = covariance_2d[sample, 1, marker]
            propagated = jacobian @ covariance_pixel @ jacobian.T
            propagated = 0.5 * (propagated + propagated.T)
            if not np.all(np.isfinite(propagated)):
                continue
            if float(np.min(np.linalg.eigvalsh(propagated))) < -1e-12:
                continue
            points[sample, marker] = point
            covariance_3d[sample, marker] = propagated
            valid_3d[sample, marker] = True
    return points, covariance_3d, valid_3d

"""Brown--Conrady projection and two-view reconstruction.

The convention matches the formal forward solver:
``X_camera = R_c @ (X_world - c_c)``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import least_squares


class CameraContractError(ValueError):
    pass


def _array(camera: dict[str, Any], key: str, shape: tuple[int, ...]) -> np.ndarray:
    value = np.asarray(camera[key], dtype=float)
    if value.shape != shape or not np.all(np.isfinite(value)):
        raise CameraContractError(f"{key} must have shape {shape} and finite entries")
    return value


def validate_camera(camera: dict[str, Any]) -> None:
    rotation = _array(camera, "R_c", (3, 3))
    _array(camera, "c_c", (3,))
    if not (
        np.linalg.norm(rotation.T @ rotation - np.eye(3), ord=np.inf) <= 1e-9
        and abs(np.linalg.det(rotation) - 1.0) <= 1e-9
    ):
        raise CameraContractError("R_c must be a member of SO(3)")
    scalar_keys = ("f_x", "f_y", "c_x", "c_y", "k1", "k2", "k3", "p1", "p2")
    scalars = {key: float(camera[key]) for key in scalar_keys}
    if not all(np.isfinite(value) for value in scalars.values()):
        raise CameraContractError("camera scalar parameters must be finite")
    if scalars["f_x"] <= 0 or scalars["f_y"] <= 0:
        raise CameraContractError("f_x and f_y must be positive")
    omega = _array(camera, "Omega_cal", (4,))
    if not (omega[0] < omega[1] and omega[2] < omega[3]):
        raise CameraContractError("Omega_cal must contain strict bounds")


def _distort_normalized(xn: float, yn: float, camera: dict[str, Any]) -> tuple[float, float]:
    radius2 = xn * xn + yn * yn
    radial = (
        1.0
        + float(camera["k1"]) * radius2
        + float(camera["k2"]) * radius2**2
        + float(camera["k3"]) * radius2**3
    )
    p1, p2 = float(camera["p1"]), float(camera["p2"])
    xd = xn * radial + 2.0 * p1 * xn * yn + p2 * (radius2 + 2.0 * xn * xn)
    yd = yn * radial + p1 * (radius2 + 2.0 * yn * yn) + 2.0 * p2 * xn * yn
    return float(xd), float(yd)


def project_points(
    points_world: np.ndarray,
    camera: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Project world points and retain a per-sample validity mask."""

    validate_camera(camera)
    points = np.asarray(points_world, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise CameraContractError("points_world must have shape (n, 3)")
    rotation = np.asarray(camera["R_c"], dtype=float)
    center = np.asarray(camera["c_c"], dtype=float)
    omega = np.asarray(camera["Omega_cal"], dtype=float)
    camera_points = (rotation @ (points - center).T).T
    pixels = np.full((points.shape[0], 2), np.nan)
    valid = np.zeros(points.shape[0], dtype=bool)
    reasons: list[str] = []
    for index, (xc, yc, zc) in enumerate(camera_points):
        reason = "VALID"
        if not np.all(np.isfinite([xc, yc, zc])):
            reason = "OBSERVATION_NUMERICAL_NONFINITE"
        elif not zc > 0.0:
            reason = "CAMERA_BEHIND_OR_ON_PLANE"
        else:
            xn, yn = float(xc / zc), float(yc / zc)
            if not (omega[0] < xn < omega[1] and omega[2] < yn < omega[3]):
                reason = "OUTSIDE_CALIBRATION_DOMAIN"
            else:
                xd, yd = _distort_normalized(xn, yn, camera)
                pixel = np.array(
                    [
                        float(camera["f_x"]) * xd + float(camera["c_x"]),
                        float(camera["f_y"]) * yd + float(camera["c_y"]),
                    ]
                )
                if np.all(np.isfinite(pixel)):
                    pixels[index] = pixel
                    valid[index] = True
                else:
                    reason = "OBSERVATION_NUMERICAL_NONFINITE"
        reasons.append(reason)
    return pixels, valid, reasons


def undistort_pixel(pixel: np.ndarray, camera: dict[str, Any]) -> np.ndarray:
    validate_camera(camera)
    pixel = np.asarray(pixel, dtype=float)
    if pixel.shape != (2,) or not np.all(np.isfinite(pixel)):
        raise CameraContractError("pixel must be a finite two-vector")
    target = np.array(
        [
            (pixel[0] - float(camera["c_x"])) / float(camera["f_x"]),
            (pixel[1] - float(camera["c_y"])) / float(camera["f_y"]),
        ]
    )

    def residual(value: np.ndarray) -> np.ndarray:
        return np.asarray(_distort_normalized(float(value[0]), float(value[1]), camera)) - target

    result = least_squares(residual, target, xtol=1e-13, ftol=1e-13, gtol=1e-13)
    if not result.success or np.linalg.norm(result.fun, ord=np.inf) > 1e-10:
        raise CameraContractError("pixel undistortion did not converge")
    omega = np.asarray(camera["Omega_cal"], dtype=float)
    if not (omega[0] < result.x[0] < omega[1] and omega[2] < result.x[1] < omega[3]):
        raise CameraContractError("undistorted pixel is outside the calibration domain")
    return result.x


def _normalized_projection_matrix(camera: dict[str, Any]) -> np.ndarray:
    rotation = np.asarray(camera["R_c"], dtype=float)
    center = np.asarray(camera["c_c"], dtype=float)
    return np.column_stack((rotation, -rotation @ center))


def triangulate_two_view(
    pixels_a: np.ndarray,
    pixels_b: np.ndarray,
    camera_a: dict[str, Any],
    camera_b: dict[str, Any],
    *,
    valid_a: np.ndarray | None = None,
    valid_b: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """DLT triangulation after Brown--Conrady undistortion."""

    validate_camera(camera_a)
    validate_camera(camera_b)
    pixels_a = np.asarray(pixels_a, dtype=float)
    pixels_b = np.asarray(pixels_b, dtype=float)
    if pixels_a.shape != pixels_b.shape or pixels_a.ndim != 2 or pixels_a.shape[1] != 2:
        raise CameraContractError("pixel arrays must have common shape (n, 2)")
    n = pixels_a.shape[0]
    mask_a = np.ones(n, dtype=bool) if valid_a is None else np.asarray(valid_a, dtype=bool)
    mask_b = np.ones(n, dtype=bool) if valid_b is None else np.asarray(valid_b, dtype=bool)
    if mask_a.shape != (n,) or mask_b.shape != (n,):
        raise CameraContractError("valid masks must have shape (n,)")
    projection_a = _normalized_projection_matrix(camera_a)
    projection_b = _normalized_projection_matrix(camera_b)
    points = np.full((n, 3), np.nan)
    valid = np.zeros(n, dtype=bool)
    for index in range(n):
        if not (mask_a[index] and mask_b[index]):
            continue
        try:
            xa, ya = undistort_pixel(pixels_a[index], camera_a)
            xb, yb = undistort_pixel(pixels_b[index], camera_b)
        except CameraContractError:
            continue
        system = np.vstack(
            (
                xa * projection_a[2] - projection_a[0],
                ya * projection_a[2] - projection_a[1],
                xb * projection_b[2] - projection_b[0],
                yb * projection_b[2] - projection_b[1],
            )
        )
        _, _, vh = np.linalg.svd(system)
        homogeneous = vh[-1]
        if abs(homogeneous[3]) <= 1e-14:
            continue
        point = homogeneous[:3] / homogeneous[3]
        if not np.all(np.isfinite(point)):
            continue
        depths = []
        for camera in (camera_a, camera_b):
            rotation = np.asarray(camera["R_c"], dtype=float)
            center = np.asarray(camera["c_c"], dtype=float)
            depths.append(float((rotation @ (point - center))[2]))
        if min(depths) <= 0.0:
            continue
        points[index] = point
        valid[index] = True
    return points, valid

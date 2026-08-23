"""Pinhole camera projection with Brown--Conrady distortion."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

Array = npt.NDArray[np.float64]


@dataclass(frozen=True)
class PinholeCamera:
    intrinsic: Array
    rotation_world_to_camera: Array
    translation_world_to_camera: Array
    distortion: tuple[float, float, float, float, float] = (0, 0, 0, 0, 0)

    def __post_init__(self) -> None:
        if self.intrinsic.shape != (3, 3):
            raise ValueError("Camera intrinsic matrix must be 3x3.")
        if self.rotation_world_to_camera.shape != (3, 3):
            raise ValueError("Camera rotation must be 3x3.")
        if self.translation_world_to_camera.shape != (3,):
            raise ValueError("Camera translation must have shape (3,).")
        should_be_identity = self.rotation_world_to_camera @ self.rotation_world_to_camera.T
        if not np.allclose(should_be_identity, np.eye(3), atol=1e-8):
            raise ValueError("Camera rotation is not orthonormal.")

    def project(self, points_world: Array) -> Array:
        points = np.asarray(points_world, dtype=float)
        original_shape = points.shape[:-1]
        flat = points.reshape(-1, 3)
        cam = flat @ self.rotation_world_to_camera.T + self.translation_world_to_camera
        z = cam[:, 2]
        if np.any(z <= 0):
            raise ValueError("One or more projected points lie behind the pinhole camera.")
        x = cam[:, 0] / z
        y = cam[:, 1] / z
        k1, k2, p1, p2, k3 = self.distortion
        r2 = x * x + y * y
        radial = 1.0 + k1 * r2 + k2 * r2**2 + k3 * r2**3
        xd = x * radial + 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x)
        yd = y * radial + p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y
        homogeneous = np.column_stack([xd, yd, np.ones_like(xd)])
        pixels_h = homogeneous @ self.intrinsic.T
        pixels = pixels_h[:, :2] / pixels_h[:, 2, None]
        return pixels.reshape(*original_shape, 2)

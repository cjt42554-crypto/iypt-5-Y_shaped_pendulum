"""Rotation-group operations without quaternion normalization or projection."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _vector3(value: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape != (3,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be a finite three-vector.")
    return array


@dataclass(frozen=True)
class RotationMetrics:
    orthogonality_error: float
    determinant: float

    @property
    def determinant_error(self) -> float:
        return abs(self.determinant - 1.0)


def rotation_metrics(rotation: np.ndarray) -> RotationMetrics:
    matrix = np.asarray(rotation, dtype=float)
    if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
        raise ValueError("rotation must be a finite 3-by-3 matrix.")
    return RotationMetrics(
        orthogonality_error=float(np.linalg.norm(matrix.T @ matrix - np.eye(3), ord="fro")),
        determinant=float(np.linalg.det(matrix)),
    )


def _validated_rotation(rotation: np.ndarray, name: str = "rotation") -> np.ndarray:
    matrix = np.asarray(rotation, dtype=float)
    metrics = rotation_metrics(matrix)
    if metrics.orthogonality_error > 5.0e-12 or metrics.determinant_error > 5.0e-12:
        raise ValueError(f"{name} must lie in SO(3) to roundoff tolerance.")
    return matrix


def hat(vector: np.ndarray) -> np.ndarray:
    """Return the cross-product matrix of a three-vector."""

    x, y, z = _vector3(vector, "vector")
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]], dtype=float)


def exp_so3(rotation_vector: np.ndarray) -> np.ndarray:
    """Evaluate the Rodrigues exponential map with its analytic small-angle series."""

    vector = _vector3(rotation_vector, "rotation_vector")
    theta_squared = float(np.dot(vector, vector))
    theta = float(np.sqrt(theta_squared))
    generator = hat(vector)
    if theta < 1.0e-8:
        theta_fourth = theta_squared**2
        sine_coefficient = 1.0 - theta_squared / 6.0 + theta_fourth / 120.0
        cosine_coefficient = 0.5 - theta_squared / 24.0 + theta_fourth / 720.0
    else:
        sine_coefficient = float(np.sin(theta) / theta)
        cosine_coefficient = float((1.0 - np.cos(theta)) / theta_squared)
    result = np.eye(3) + sine_coefficient * generator + cosine_coefficient * (generator @ generator)
    metrics = rotation_metrics(result)
    if metrics.orthogonality_error > 5.0e-12 or metrics.determinant_error > 5.0e-12:
        raise FloatingPointError("SO(3) exponential lost its group property.")
    return result


def compose_rotation(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Group multiplication of two validated rotations."""

    first = _validated_rotation(left, "left")
    second = _validated_rotation(right, "right")
    product = first @ second
    metrics = rotation_metrics(product)
    if metrics.orthogonality_error > 1.0e-11 or metrics.determinant_error > 1.0e-11:
        raise FloatingPointError("SO(3) multiplication left the roundoff-scale group tube.")
    return product


def advance_rotation_body(
    rotation: np.ndarray, angular_velocity_body: np.ndarray, time_step: float
) -> np.ndarray:
    """Right-multiply by ``Exp(dt*omega_body)``."""

    if not np.isfinite(time_step):
        raise ValueError("time_step must be finite.")
    matrix = _validated_rotation(rotation)
    increment = exp_so3(float(time_step) * _vector3(angular_velocity_body, "angular_velocity_body"))
    return compose_rotation(matrix, increment)


def advance_rotation_world(
    rotation: np.ndarray, angular_velocity_world: np.ndarray, time_step: float
) -> np.ndarray:
    """Left-multiply by ``Exp(dt*omega_world)``."""

    if not np.isfinite(time_step):
        raise ValueError("time_step must be finite.")
    matrix = _validated_rotation(rotation)
    increment = exp_so3(
        float(time_step) * _vector3(angular_velocity_world, "angular_velocity_world")
    )
    return compose_rotation(increment, matrix)


def body_to_world_angular_velocity(
    rotation: np.ndarray, angular_velocity_body: np.ndarray
) -> np.ndarray:
    return _validated_rotation(rotation) @ _vector3(angular_velocity_body, "angular_velocity_body")


def world_to_body_angular_velocity(
    rotation: np.ndarray, angular_velocity_world: np.ndarray
) -> np.ndarray:
    return _validated_rotation(rotation).T @ _vector3(
        angular_velocity_world, "angular_velocity_world"
    )

"""P3R contact assembly with finite signed socket-validity inequalities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

import numpy as np

from ypendulum_hfv2.statics.assembly import StaticAssembly, StaticEvaluation
from ypendulum_hfv2.statics.contact_assembly import (
    ContactCoordinates,
    ContactStaticAssembly,
    ContactStaticEvaluation,
    ContactValidityMetrics,
    _junction_validity,
    _material_point_from_socket_endpoint,
    _socket_breakpoints,
)
from ypendulum_hfv2.statics.contracts import StaticSeed

from . import P3R_CONTACT_ASSEMBLY_IDENTITY_SCHEMA, P3R_CONTACT_MODEL_ID


def _positive(value: float, name: str) -> float:
    scalar = float(value)
    if not np.isfinite(scalar) or scalar <= 0.0:
        raise ValueError(f"{name} must be finite and strictly positive.")
    return scalar


def _sha256_identity(value: str, name: str) -> str:
    if len(value) != 64:
        raise ValueError(f"{name} must be one SHA-256 hexadecimal identity.")
    int(value, 16)
    return value


def _readonly(value: np.ndarray, ndim: int, name: str) -> np.ndarray:
    array = np.array(value, dtype=float, copy=True)
    if array.ndim != ndim or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be a finite {ndim}-dimensional array.")
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class ValidityEvaluation:
    """Complete identity-bound signed residuals for the registered socket domain."""

    constraint_ids: tuple[str, ...]
    units: tuple[str, ...]
    scales: np.ndarray
    signed_residuals: np.ndarray
    residual_jacobian: np.ndarray

    def __post_init__(self) -> None:
        identities = tuple(self.constraint_ids)
        units = tuple(self.units)
        scales = _readonly(self.scales, 1, "scales")
        residuals = _readonly(self.signed_residuals, 1, "signed_residuals")
        jacobian = _readonly(self.residual_jacobian, 2, "residual_jacobian")
        count = len(identities)
        if count != len(set(identities)):
            raise ValueError("Validity constraint identities must be unique.")
        if len(units) != count or scales.shape != (count,) or residuals.shape != (count,):
            raise ValueError("Validity metadata must contain one entry per identity.")
        if jacobian.shape[0] != count:
            raise ValueError("Validity Jacobian must contain one row per identity.")
        if np.any(scales <= 0.0):
            raise ValueError("Validity scales must be strictly positive.")
        object.__setattr__(self, "constraint_ids", identities)
        object.__setattr__(self, "units", units)
        object.__setattr__(self, "scales", scales)
        object.__setattr__(self, "signed_residuals", residuals)
        object.__setattr__(self, "residual_jacobian", jacobian)

    @property
    def normalized_residuals(self) -> np.ndarray:
        return self.signed_residuals / self.scales

    @property
    def normalized_jacobian(self) -> np.ndarray:
        return self.residual_jacobian / self.scales[:, None]


@dataclass(frozen=True)
class P3RContactEvaluation:
    """Physical contact evaluation plus solver-facing validity inequalities."""

    contact: ContactStaticEvaluation
    validity: ValidityEvaluation
    contact_gap_scale_m: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "contact_gap_scale_m",
            _positive(self.contact_gap_scale_m, "contact_gap_scale_m"),
        )
        if self.validity.residual_jacobian.shape[1] != self.contact.gap_jacobian.shape[1]:
            raise ValueError("Contact and validity Jacobians must share one coordinate layout.")
        overlap = set(self.contact.constraint_ids) & set(self.validity.constraint_ids)
        if overlap:
            raise ValueError(f"Physical and validity constraint identities overlap: {sorted(overlap)}")

    @property
    def coordinates(self) -> ContactCoordinates:
        return self.contact.coordinates

    @property
    def total_potential(self) -> float:
        return self.contact.total_potential

    @property
    def generalized_force(self) -> np.ndarray:
        return self.contact.generalized_force

    @property
    def solver_constraint_ids(self) -> tuple[str, ...]:
        return self.contact.constraint_ids + self.validity.constraint_ids

    @property
    def solver_inequality_residuals(self) -> np.ndarray:
        return np.concatenate(
            [
                self.contact.gaps_m / self.contact_gap_scale_m,
                self.validity.normalized_residuals,
            ]
        )

    @property
    def solver_inequality_jacobian(self) -> np.ndarray:
        return np.vstack(
            [
                self.contact.gap_jacobian / self.contact_gap_scale_m,
                self.validity.normalized_jacobian,
            ]
        )


class P3RContactAssembly(ContactStaticAssembly):
    """Versioned contact assembly that keeps finite invalid trials evaluable.

    The inherited registered contact gaps and analytic gap Jacobian remain
    byte-identical P3 components.  P3R changes the assembly identity and exposes
    every finite socket-domain validity requirement as a signed inequality.
    Truly undefined closest-point geometry continues to raise through the
    inherited witness construction.
    """

    def __init__(
        self,
        *,
        base_assembly: StaticAssembly,
        surface: object,
        tolerances: object,
        adapter_contract_sha256: str,
        frozen_protocol_sha256: str,
        contact_gap_scale_m: float,
        validity_scale_m: float,
        validity_scale_m2: float,
        validity_scale_dimensionless: float,
        translation_difference_step_m: float,
        rotation_difference_step_rad: float,
    ) -> None:
        adapter_hash = _sha256_identity(adapter_contract_sha256, "adapter_contract_sha256")
        protocol_hash = _sha256_identity(frozen_protocol_sha256, "frozen_protocol_sha256")
        super().__init__(
            base_assembly=base_assembly,
            surface=surface,
            tolerances=tolerances,
            formal_registration_contract_sha256=adapter_hash,
            protocol_amendment_sha256=protocol_hash,
        )
        scales = {
            "m": _positive(validity_scale_m, "validity_scale_m"),
            "m^2": _positive(validity_scale_m2, "validity_scale_m2"),
            "1": _positive(
                validity_scale_dimensionless,
                "validity_scale_dimensionless",
            ),
        }
        translation_step = _positive(
            translation_difference_step_m,
            "translation_difference_step_m",
        )
        rotation_step = _positive(
            rotation_difference_step_rad,
            "rotation_difference_step_rad",
        )
        gap_scale = _positive(contact_gap_scale_m, "contact_gap_scale_m")
        binding = {
            "identity_schema": P3R_CONTACT_ASSEMBLY_IDENTITY_SCHEMA,
            "contact_model_id": P3R_CONTACT_MODEL_ID,
            "base_static_assembly_token": base_assembly.layout.layout_token,
            "adapter_contract_sha256": adapter_hash,
            "frozen_protocol_sha256": protocol_hash,
            "geometry_tolerances": asdict(tolerances),
            "contact_registry": self.registry.serializable(),
            "solver_scaling": {
                "contact_gap_scale_m": gap_scale,
                "validity_scales": scales,
            },
            "validity_jacobian": {
                "scheme": "deterministic_centered_difference",
                "translation_difference_step_m": translation_step,
                "rotation_difference_step_rad": rotation_step,
            },
        }
        token = hashlib.sha256(
            json.dumps(
                binding,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.adapter_contract_sha256 = adapter_hash
        self.frozen_protocol_sha256 = protocol_hash
        self.contact_gap_scale_m = gap_scale
        self.validity_scales = scales
        self.translation_difference_step_m = translation_step
        self.rotation_difference_step_rad = rotation_step
        self.identity_binding = binding
        self.contact_assembly_token = token

    def coordinates_from_seed(self, seed: StaticSeed) -> ContactCoordinates:
        return super().coordinates_from_seed(seed)

    def _validity_metrics(self, evaluation: StaticEvaluation) -> ContactValidityMetrics:
        """Return finite metrics without applying the historical exception policy."""

        bob_socket = self.registry.bob_socket
        breakpoints = _socket_breakpoints(self.base_assembly, bob_socket.socket)
        points = [
            _material_point_from_socket_endpoint(
                self.base_assembly,
                evaluation,
                bob_socket.socket,
                float(distance),
            )
            for distance in breakpoints
        ]
        radial = min(
            float((start - evaluation.bob_position) @ (end - start))
            for start, end in zip(points[:-1], points[1:], strict=True)
        )
        cut_gap = (
            float(np.linalg.norm(points[-1] - evaluation.bob_position))
            - bob_socket.required_center_distance_m
        )
        extent = bob_socket.socket.total_material_length_m - bob_socket.socket.socket_length_m
        junction_metrics = tuple(
            (
                registration.registration_id,
                *_junction_validity(self.base_assembly, evaluation, registration),
            )
            for registration in self.registry.junction_sockets
        )
        return ContactValidityMetrics(
            bob_socket_material_extent_m=extent,
            bob_socket_radial_monotonicity_m2=radial,
            bob_socket_cut_gap_m=cut_gap,
            junction_socket_metrics=junction_metrics,
        )

    def _signed_validity_rows(
        self,
        metrics: ContactValidityMetrics,
    ) -> tuple[tuple[str, str, float], ...]:
        bob_id = self.registry.bob_socket.registration_id
        rows: list[tuple[str, str, float]] = [
            (
                f"validity:{bob_id}:material_extent",
                "m",
                metrics.bob_socket_material_extent_m,
            ),
            (
                f"validity:{bob_id}:radial_monotonicity_margin",
                "m^2",
                metrics.bob_socket_radial_monotonicity_m2
                - self.tolerances.socket_radial_monotonicity_min_m2,
            ),
            (
                f"validity:{bob_id}:cut_gap_margin",
                "m",
                metrics.bob_socket_cut_gap_m - self.tolerances.socket_cut_gap_min_m,
            ),
        ]
        for registration_id, extent, opening, cut_gap in metrics.junction_socket_metrics:
            prefix = f"validity:junction_socket:{registration_id}"
            rows.extend(
                [
                    (f"{prefix}:material_extent", "m", extent),
                    (
                        f"{prefix}:projective_opening_margin",
                        "1",
                        opening - self.tolerances.socket_projective_opening_margin_min,
                    ),
                    (
                        f"{prefix}:cut_gap_margin",
                        "m",
                        cut_gap - self.tolerances.socket_cut_gap_min_m,
                    ),
                ]
            )
        return tuple(rows)

    def _validity_values_from_coordinates(self, values: np.ndarray) -> np.ndarray:
        base_coordinates = self.base_assembly.coordinates_from_values(values)
        base_evaluation = self.base_assembly.evaluate(base_coordinates)
        metrics = self._validity_metrics(base_evaluation)
        return np.array([row[2] for row in self._signed_validity_rows(metrics)])

    def _validity_jacobian(self, values: np.ndarray, row_count: int) -> np.ndarray:
        size = values.size
        jacobian = np.empty((row_count, size))
        rotation_start = self.base_assembly.layout.bob_rotation_slice.start
        for column in range(size):
            step = (
                self.translation_difference_step_m
                if column < rotation_start
                else self.rotation_difference_step_rad
            )
            plus = np.array(values, copy=True)
            minus = np.array(values, copy=True)
            plus[column] += step
            minus[column] -= step
            jacobian[:, column] = (
                self._validity_values_from_coordinates(plus)
                - self._validity_values_from_coordinates(minus)
            ) / (2.0 * step)
        return jacobian

    def evaluate(self, coordinates: ContactCoordinates) -> P3RContactEvaluation:
        contact = super().evaluate(coordinates)
        rows = self._signed_validity_rows(contact.validity)
        values = np.array([row[2] for row in rows])
        units = tuple(row[1] for row in rows)
        scales = np.array([self.validity_scales[unit] for unit in units])
        jacobian = self._validity_jacobian(coordinates.values, len(rows))
        validity = ValidityEvaluation(
            constraint_ids=tuple(row[0] for row in rows),
            units=units,
            scales=scales,
            signed_residuals=values,
            residual_jacobian=jacobian,
        )
        return P3RContactEvaluation(
            contact=contact,
            validity=validity,
            contact_gap_scale_m=self.contact_gap_scale_m,
        )

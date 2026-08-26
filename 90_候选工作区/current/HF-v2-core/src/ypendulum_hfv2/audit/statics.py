"""Independent finite-difference, balance and second-order static audits."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ypendulum_hfv2.rigid.rotation import hat
from ypendulum_hfv2.statics.assembly import StaticAssembly, StaticEvaluation
from ypendulum_hfv2.statics.contracts import StaticCoordinates


@dataclass(frozen=True)
class EnergyForceSample:
    relative_step: float
    relative_error: float


@dataclass(frozen=True)
class BalanceAudit:
    force_scale_N: float
    scaled_generalized_force_residual: float
    scaled_global_force_balance: float
    scaled_global_moment_balance: float
    global_force_closure_residual_N: np.ndarray
    global_moment_closure_residual_N_m: np.ndarray
    raw_equilibrium_force_residual_N: np.ndarray
    raw_equilibrium_moment_residual_N_m: np.ndarray


@dataclass(frozen=True)
class HessianAudit:
    normalized_unsymmetrized_hessian: np.ndarray
    normalized_symmetric_hessian: np.ndarray
    unsymmetrized_relative_asymmetry: float
    gauge_curvatures: np.ndarray
    nongauge_eigenvalues: np.ndarray
    directional_curvatures: np.ndarray


def _right_jacobian_so3(rotation_vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(rotation_vector, dtype=float)
    squared = float(vector @ vector)
    angle = float(np.sqrt(squared))
    generator = hat(vector)
    if angle < 1.0e-6:
        angle_fourth = squared**2
        first = 0.5 - squared / 24.0 + angle_fourth / 720.0
        second = 1.0 / 6.0 - squared / 120.0 + angle_fourth / 5040.0
    else:
        first = float((1.0 - np.cos(angle)) / squared)
        second = float((angle - np.sin(angle)) / (squared * angle))
    return np.eye(3) - first * generator + second * (generator @ generator)


def coordinate_scales(assembly: StaticAssembly) -> np.ndarray:
    """Frozen SI normalization: one metre for translations and one radian for rotation."""

    return np.ones(assembly.layout.generalized_size, dtype=float)


def force_scale(assembly: StaticAssembly) -> float:
    gravity_magnitude = float(np.linalg.norm(assembly.environment.gravity))
    buoyant_density = (
        assembly.environment.fluid_density if assembly.environment.buoyancy_enabled else 0.0
    )
    node_effective_mass = assembly.node_mass - buoyant_density * assembly.node_displaced_volume
    bob_effective_mass = assembly.bob.mass - buoyant_density * assembly.bob.displaced_volume
    scale = gravity_magnitude * (
        float(np.sum(np.abs(node_effective_mass))) + abs(bob_effective_mass)
    )
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("Static audit requires a strictly positive external-force scale.")
    return scale


def energy_force_samples(
    assembly: StaticAssembly,
    coordinates: StaticCoordinates,
    relative_steps: tuple[float, ...],
) -> tuple[EnergyForceSample, ...]:
    base = assembly.evaluate(coordinates)
    values = coordinates.values
    scales = coordinate_scales(assembly)
    analytic_gradient = -base.generalized_force
    samples: list[EnergyForceSample] = []
    for relative_step in relative_steps:
        step = float(relative_step)
        if not np.isfinite(step) or step <= 0.0:
            raise ValueError("Finite-difference steps must be finite and positive.")
        gradient = np.empty_like(values)
        for index, scale in enumerate(scales):
            increment = step * scale
            plus = values.copy()
            minus = values.copy()
            plus[index] += increment
            minus[index] -= increment
            plus_energy = assembly.evaluate(assembly.coordinates_from_values(plus)).total_potential
            minus_energy = assembly.evaluate(assembly.coordinates_from_values(minus)).total_potential
            gradient[index] = (plus_energy - minus_energy) / (2.0 * increment)
        denominator = max(
            float(np.linalg.norm(analytic_gradient)),
            float(np.linalg.norm(gradient)),
            np.finfo(float).tiny,
        )
        samples.append(
            EnergyForceSample(
                relative_step=step,
                relative_error=float(np.linalg.norm(gradient - analytic_gradient) / denominator),
            )
        )
    return tuple(samples)


def strict_decrease_interval(
    values: tuple[float, ...], minimum_steps: int
) -> tuple[int, int] | None:
    if minimum_steps <= 0:
        raise ValueError("minimum_steps must be positive.")
    if not values or not all(np.isfinite(value) for value in values):
        raise ValueError("values must be a non-empty finite tuple.")
    first_minimum = int(np.argmin(values))
    run_start = 0
    run_length = 0
    for index in range(1, first_minimum + 1):
        if values[index] < values[index - 1]:
            if run_length == 0:
                run_start = index - 1
            run_length += 1
            if run_length >= minimum_steps:
                return run_start, index
        else:
            run_length = 0
    return None


def balance_audit(
    assembly: StaticAssembly,
    evaluation: StaticEvaluation,
) -> BalanceAudit:
    scale = force_scale(assembly)
    equilibrium_force = np.sum(evaluation.external_node_forces, axis=0)
    equilibrium_force += evaluation.bob_external_force
    equilibrium_moment = np.sum(
        np.cross(evaluation.node_positions, evaluation.external_node_forces),
        axis=0,
    )
    equilibrium_moment += np.cross(
        evaluation.bob_position,
        evaluation.bob_external_force,
    )
    for node_id, reaction in zip(
        evaluation.prescribed_node_ids,
        evaluation.support_reactions,
        strict=True,
    ):
        position = evaluation.node_positions[assembly.topology.node_index(node_id)]
        equilibrium_force += reaction
        equilibrium_moment += np.cross(position, reaction)

    unconstrained_force = np.array(
        evaluation.generalized_force[assembly.layout.bob_position_slice.slice],
        copy=True,
    )
    unconstrained_moment = np.cross(
        evaluation.bob_position,
        evaluation.generalized_force[assembly.layout.bob_position_slice.slice],
    )
    unconstrained_moment += evaluation.bob_rotation @ evaluation.bob_torque_body
    for node_id in assembly.layout.free_node_ids:
        node_force = evaluation.generalized_force[assembly.layout.free_slice(node_id)]
        node_position = evaluation.node_positions[assembly.topology.node_index(node_id)]
        unconstrained_force += node_force
        unconstrained_moment += np.cross(node_position, node_force)
    closure_force = equilibrium_force - unconstrained_force
    closure_moment = equilibrium_moment - unconstrained_moment
    return BalanceAudit(
        force_scale_N=scale,
        scaled_generalized_force_residual=float(
            np.linalg.norm(evaluation.generalized_force, ord=np.inf) / scale
        ),
        scaled_global_force_balance=float(np.linalg.norm(closure_force) / scale),
        scaled_global_moment_balance=float(np.linalg.norm(closure_moment) / scale),
        global_force_closure_residual_N=np.array(closure_force, copy=True),
        global_moment_closure_residual_N_m=np.array(closure_moment, copy=True),
        raw_equilibrium_force_residual_N=np.array(equilibrium_force, copy=True),
        raw_equilibrium_moment_residual_N_m=np.array(equilibrium_moment, copy=True),
    )


def _gauge_basis(
    assembly: StaticAssembly,
    coordinates: StaticCoordinates,
    scales: np.ndarray,
) -> np.ndarray:
    size = assembly.layout.generalized_size
    rotation_slice = assembly.layout.bob_rotation_slice.slice
    rotation_vector = coordinates.values[rotation_slice]
    jacobian = _right_jacobian_so3(rotation_vector)
    arm = assembly.bob.attachment_arm_body
    arm_norm = float(np.linalg.norm(arm))
    body_directions = np.eye(3) if arm_norm == 0.0 else (arm / arm_norm)[:, None].T
    columns: list[np.ndarray] = []
    for body_direction in body_directions:
        coordinate_direction = np.linalg.solve(jacobian, body_direction)
        full = np.zeros(size)
        full[rotation_slice] = coordinate_direction
        normalized = full / scales
        normalized /= np.linalg.norm(normalized)
        columns.append(normalized)
    return np.column_stack(columns)


def independent_hessian_audit(
    assembly: StaticAssembly,
    coordinates: StaticCoordinates,
    *,
    normalized_step: float,
    directional_energy_step: float,
    direction_count: int,
) -> HessianAudit:
    values = coordinates.values
    scales = coordinate_scales(assembly)
    energy_scale = force_scale(assembly)
    size = values.size
    hessian = np.empty((size, size), dtype=float)
    for index, scale in enumerate(scales):
        increment = normalized_step * scale
        plus = values.copy()
        minus = values.copy()
        plus[index] += increment
        minus[index] -= increment
        plus_gradient = -assembly.evaluate(
            assembly.coordinates_from_values(plus)
        ).generalized_force
        minus_gradient = -assembly.evaluate(
            assembly.coordinates_from_values(minus)
        ).generalized_force
        hessian[:, index] = (plus_gradient - minus_gradient) / (2.0 * increment)
    normalized = scales[:, None] * hessian * scales[None, :] / energy_scale
    symmetric = 0.5 * (normalized + normalized.T)
    asymmetry = float(
        np.linalg.norm(normalized - normalized.T)
        / max(np.linalg.norm(normalized), np.finfo(float).tiny)
    )
    gauge = _gauge_basis(assembly, coordinates, scales)
    complete, _ = np.linalg.qr(gauge, mode="complete")
    gauge_basis = complete[:, : gauge.shape[1]]
    complement = complete[:, gauge.shape[1] :]
    gauge_curvatures = np.linalg.eigvalsh(gauge_basis.T @ symmetric @ gauge_basis)
    nongauge_eigenvalues = np.linalg.eigvalsh(complement.T @ symmetric @ complement)

    base_energy = assembly.evaluate(coordinates).total_potential
    directional: list[float] = []
    candidate_index = 0
    while len(directional) < direction_count:
        indices = np.arange(1, size + 1, dtype=float)
        raw = np.sin(indices * (candidate_index + 1) * np.sqrt(2.0))
        raw += np.cos(indices * (candidate_index + 2) * np.sqrt(3.0))
        direction = complement @ (complement.T @ raw)
        norm = float(np.linalg.norm(direction))
        candidate_index += 1
        if norm <= 1.0e-12:
            continue
        direction /= norm
        delta = scales * direction * directional_energy_step
        plus_energy = assembly.evaluate(
            assembly.coordinates_from_values(values + delta)
        ).total_potential
        minus_energy = assembly.evaluate(
            assembly.coordinates_from_values(values - delta)
        ).total_potential
        curvature = (
            plus_energy - 2.0 * base_energy + minus_energy
        ) / (directional_energy_step**2 * energy_scale)
        directional.append(float(curvature))
    return HessianAudit(
        normalized_unsymmetrized_hessian=np.array(normalized, copy=True),
        normalized_symmetric_hessian=np.array(symmetric, copy=True),
        unsymmetrized_relative_asymmetry=asymmetry,
        gauge_curvatures=np.array(gauge_curvatures, copy=True),
        nongauge_eigenvalues=np.array(nongauge_eigenvalues, copy=True),
        directional_curvatures=np.array(directional, copy=True),
    )

"""Vectorised 3-D two-node tension-only cable element operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import numpy.typing as npt

from ypendulum.materials.kelvin_voigt import evaluate_kelvin_voigt
from ypendulum.materials.base import AxialMaterial

Array = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True)
class CableElementBatch:
    node_i: IntArray
    node_j: IntArray
    rest_length: Array
    ea: Array
    eta_a: Array
    area: Array
    density: Array
    diameter: Array
    drag_cd_normal: Array
    cable_id: IntArray

    @property
    def count(self) -> int:
        return int(self.node_i.size)

    @property
    def element_mass(self) -> Array:
        return self.density * self.area * self.rest_length


@dataclass(frozen=True)
class CableKinematics:
    d: Array
    length: Array
    direction: Array
    relative_velocity: Array
    delta: Array
    delta_dot: Array


@dataclass(frozen=True)
class CableResponse:
    kinematics: CableKinematics
    tension: Array
    active: npt.NDArray[np.bool_]
    elastic_energy: Array
    dissipation_rate: Array
    force_i: Array
    force_j: Array
    tangent_position: Array
    tangent_velocity: Array


def cable_kinematics(
    positions: Array,
    velocities: Array,
    elements: CableElementBatch,
    *,
    length_guard: float,
) -> CableKinematics:
    xi = positions[elements.node_i]
    xj = positions[elements.node_j]
    vi = velocities[elements.node_i]
    vj = velocities[elements.node_j]
    d = xj - xi
    length = np.linalg.norm(d, axis=1)
    if np.any(length <= length_guard) or not np.all(np.isfinite(length)):
        bad = np.where(length <= length_guard)[0]
        raise FloatingPointError(f"Degenerate cable element length at indices {bad[:10].tolist()}.")
    direction = d / length[:, None]
    relative_velocity = vj - vi
    delta = length - elements.rest_length
    delta_dot = np.einsum("ij,ij->i", direction, relative_velocity)
    return CableKinematics(d, length, direction, relative_velocity, delta, delta_dot)


def evaluate_cable_elements(
    positions: Array,
    velocities: Array,
    elements: CableElementBatch,
    *,
    length_guard: float,
    compute_tangent: bool = True,
    material_overrides: Mapping[int, AxialMaterial] | None = None,
) -> CableResponse:
    kin = cable_kinematics(positions, velocities, elements, length_guard=length_guard)
    mat = evaluate_kelvin_voigt(
        kin.delta, kin.delta_dot, elements.rest_length, elements.ea, elements.eta_a
    )
    if material_overrides:
        # Material selection is frozen per cable, so the small number of
        # subset assignments below preserves vectorisation within each cable
        # while keeping the common Kelvin--Voigt path allocation-free.
        tension = mat.tension.copy()
        active = mat.active.copy()
        elastic_energy = mat.elastic_energy.copy()
        dissipation_rate = mat.dissipation_rate.copy()
        d_tension_d_delta = mat.d_tension_d_delta.copy()
        d_tension_d_delta_dot = mat.d_tension_d_delta_dot.copy()
        for cable_id, material in material_overrides.items():
            mask = elements.cable_id == int(cable_id)
            if not np.any(mask):
                continue
            response = material.evaluate(
                kin.delta[mask], kin.delta_dot[mask], elements.rest_length[mask]
            )
            tension[mask] = response.tension
            active[mask] = response.active
            elastic_energy[mask] = response.elastic_energy
            dissipation_rate[mask] = response.dissipation_rate
            d_tension_d_delta[mask] = response.d_tension_d_delta
            d_tension_d_delta_dot[mask] = response.d_tension_d_delta_dot
        mat = type(mat)(
            tension=tension,
            active=active,
            elastic_energy=elastic_energy,
            dissipation_rate=dissipation_rate,
            d_tension_d_delta=d_tension_d_delta,
            d_tension_d_delta_dot=d_tension_d_delta_dot,
        )
    force_i = mat.tension[:, None] * kin.direction
    force_j = -force_i

    n_elem = elements.count
    tangent_x = np.zeros((n_elem, 3, 3), dtype=float)
    tangent_v = np.zeros((n_elem, 3, 3), dtype=float)
    if compute_tangent and n_elem:
        eye = np.eye(3)[None, :, :]
        nn = kin.direction[:, :, None] * kin.direction[:, None, :]
        projector = eye - nn
        p_v = np.einsum("eij,ej->ei", projector, kin.relative_velocity)
        grad_t_d = (
            mat.d_tension_d_delta[:, None] * kin.direction
            + mat.d_tension_d_delta_dot[:, None] * p_v / kin.length[:, None]
        )
        tangent_x = (
            kin.direction[:, :, None] * grad_t_d[:, None, :]
            + mat.tension[:, None, None] * projector / kin.length[:, None, None]
        )
        tangent_v = mat.d_tension_d_delta_dot[:, None, None] * nn

    return CableResponse(
        kinematics=kin,
        tension=mat.tension,
        active=mat.active,
        elastic_energy=mat.elastic_energy,
        dissipation_rate=mat.dissipation_rate,
        force_i=force_i,
        force_j=force_j,
        tangent_position=tangent_x,
        tangent_velocity=tangent_v,
    )

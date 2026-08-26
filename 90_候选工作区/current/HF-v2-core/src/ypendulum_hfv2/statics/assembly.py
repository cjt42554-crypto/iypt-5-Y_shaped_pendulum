"""Strongly bound no-contact total-potential and generalized-force assembly."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from ..constitutive.axial import AxialMaterial, axial_segment_response
from ..constitutive.bending import bending_energy_forces
from ..loads import IsotropicDragLaw, point_external_load
from ..mass import MassProperties
from ..rigid.rotation import compose_rotation, exp_so3, hat
from ..state import HFV2State
from ..topology import HFV2Topology
from .contracts import (
    BranchMaterial,
    RigidBobProperties,
    StaticCoordinates,
    StaticEnvironment,
    StaticSeed,
)


def _readonly(value: np.ndarray) -> np.ndarray:
    array = np.array(value, dtype=float, copy=True)
    array.setflags(write=False)
    return array


def _vector3(value: np.ndarray, name: str) -> np.ndarray:
    array = np.array(value, dtype=float, copy=True)
    if array.shape != (3,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be a finite three-vector.")
    array.setflags(write=False)
    return array


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


@dataclass(frozen=True)
class CoordinateSlice:
    identity: str
    start: int
    stop: int

    @property
    def slice(self) -> slice:
        return slice(self.start, self.stop)


@dataclass(frozen=True)
class BoundStaticLayout:
    layout_token: str
    node_ids: tuple[str, ...]
    free_node_ids: tuple[str, ...]
    segment_ids: tuple[str, ...]
    segment_rest_lengths: np.ndarray
    free_position_slices: tuple[CoordinateSlice, ...]
    bob_position_slice: CoordinateSlice
    bob_rotation_slice: CoordinateSlice
    generalized_size: int

    def free_slice(self, node_id: str) -> slice:
        for entry in self.free_position_slices:
            if entry.identity == node_id:
                return entry.slice
        raise KeyError(node_id)


@dataclass(frozen=True)
class StaticEvaluation:
    coordinates: StaticCoordinates
    total_potential: float
    energy_components: tuple[tuple[str, float], ...]
    generalized_force: np.ndarray
    bob_torque_body: np.ndarray
    node_positions: np.ndarray
    node_forces: np.ndarray
    external_node_forces: np.ndarray
    prescribed_node_ids: tuple[str, ...]
    support_reactions: np.ndarray
    bob_position: np.ndarray
    bob_rotation: np.ndarray
    attachment_position: np.ndarray
    bob_external_force: np.ndarray
    segment_ids: tuple[str, ...]
    segment_current_lengths: np.ndarray
    segment_extensions: np.ndarray
    segment_tensions: np.ndarray
    branch_minimum_curvature_denominators: tuple[tuple[str, float], ...]


class StaticAssembly:
    """Bind topology, state, mass, materials, segment order and coordinate slices.

    Every numerical entry point requires :class:`StaticCoordinates` carrying the
    deterministic token generated from the complete binding.  Rest lengths are
    derived internally from material coordinates and are never accepted as an
    assembly input.
    """

    def __init__(
        self,
        *,
        topology: HFV2Topology,
        reference_state: HFV2State,
        branch_materials: tuple[BranchMaterial, ...],
        prescribed_node_positions: Mapping[str, np.ndarray],
        environment: StaticEnvironment,
        bob: RigidBobProperties,
        explicit_node_mass: Mapping[str, float] | None = None,
        explicit_node_displaced_volume: Mapping[str, float] | None = None,
        rotation_chart_norm_max: float = 0.75,
    ) -> None:
        reference_state.validate_topology(topology)
        if any(
            np.any(value != 0.0)
            for value in (
                reference_state.free_node_velocities,
                reference_state.bob_velocity,
                reference_state.bob_angular_velocity_body,
            )
        ):
            raise ValueError("The bound static reference state must have zero velocities.")
        chart_limit = float(rotation_chart_norm_max)
        if not np.isfinite(chart_limit) or chart_limit <= 0.0 or chart_limit >= np.pi:
            raise ValueError("rotation_chart_norm_max must lie strictly between zero and pi.")

        materials = tuple(branch_materials)
        material_ids = tuple(material.branch_id for material in materials)
        branch_ids = tuple(dict.fromkeys(segment.branch_id for segment in topology.segments))
        if len(material_ids) != len(set(material_ids)) or set(material_ids) != set(branch_ids):
            raise ValueError("Branch materials must identify every topology branch exactly once.")
        material_by_branch = {material.branch_id: material for material in materials}

        prescribed_ids = tuple(node.node_id for node in topology.nodes if node.kind == "prescribed")
        if set(prescribed_node_positions) != set(prescribed_ids):
            raise ValueError("Prescribed positions must identify every prescribed node exactly.")
        prescribed = {
            node_id: _vector3(prescribed_node_positions[node_id], f"position[{node_id}]")
            for node_id in prescribed_ids
        }

        explicit_mass = self._validated_node_scalars(
            topology,
            explicit_node_mass or {},
            "explicit_node_mass",
        )
        explicit_volume = self._validated_node_scalars(
            topology,
            explicit_node_displaced_volume or {},
            "explicit_node_displaced_volume",
        )
        node_mass = np.array([explicit_mass[node_id] for node_id in topology.node_ids])
        node_volume = np.array([explicit_volume[node_id] for node_id in topology.node_ids])
        segment_rest = np.array([segment.rest_length for segment in topology.segments])
        segment_materials: list[BranchMaterial] = []
        axial_materials: list[AxialMaterial] = []
        for segment_index, segment in enumerate(topology.segments):
            material = material_by_branch[segment.branch_id]
            segment_materials.append(material)
            rest = float(segment_rest[segment_index])
            contribution_mass = 0.5 * material.line_density * rest
            contribution_volume = 0.5 * material.displaced_volume_per_length * rest
            for node_id in (segment.start_node, segment.end_node):
                node_index = topology.node_index(node_id)
                node_mass[node_index] += contribution_mass
                node_volume[node_index] += contribution_volume
            axial_materials.append(
                AxialMaterial(
                    rest_length=rest,
                    axial_rigidity=material.axial_rigidity,
                    axial_viscosity=0.0,
                )
            )
        if np.any(node_mass <= 0.0):
            raise ValueError("Every material node must receive strictly positive lumped mass.")

        free_mass = np.array(
            [node_mass[topology.node_index(node_id)] for node_id in topology.free_node_ids]
        )
        mass_properties = MassProperties(
            free_node_ids=topology.free_node_ids,
            free_node_mass=free_mass,
            bob_mass=bob.mass,
            bob_inertia_body=bob.inertia_body,
        )
        mass_properties.validate_topology(topology)
        mass_properties.validate_state(reference_state)

        generalized_size = topology.generalized_position_tangent_size
        free_slices = tuple(
            CoordinateSlice(node_id, 3 * index, 3 * index + 3)
            for index, node_id in enumerate(topology.free_node_ids)
        )
        bob_start = 3 * topology.free_node_count
        bob_position_slice = CoordinateSlice("bob_position", bob_start, bob_start + 3)
        bob_rotation_slice = CoordinateSlice("bob_rotation_body", bob_start + 3, bob_start + 6)
        binding = {
            "node_ids": topology.node_ids,
            "free_node_ids": topology.free_node_ids,
            "segments": [
                [
                    segment.segment_id,
                    segment.branch_id,
                    segment.start_node,
                    segment.end_node,
                    segment.material_start,
                    segment.material_end,
                ]
                for segment in topology.segments
            ],
            "materials": [
                [
                    material.branch_id,
                    material.axial_rigidity,
                    material.bending_stiffness,
                    material.line_density,
                    material.displaced_volume_per_length,
                ]
                for material in materials
            ],
            "node_mass": node_mass.tolist(),
            "node_volume": node_volume.tolist(),
            "bob_mass": bob.mass,
            "bob_volume": bob.displaced_volume,
            "bob_inertia": bob.inertia_body.tolist(),
            "attachment_arm": bob.attachment_arm_body.tolist(),
            "generalized_size": generalized_size,
        }
        token = hashlib.sha256(
            json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        layout = BoundStaticLayout(
            layout_token=token,
            node_ids=topology.node_ids,
            free_node_ids=topology.free_node_ids,
            segment_ids=tuple(segment.segment_id for segment in topology.segments),
            segment_rest_lengths=_readonly(segment_rest),
            free_position_slices=free_slices,
            bob_position_slice=bob_position_slice,
            bob_rotation_slice=bob_rotation_slice,
            generalized_size=generalized_size,
        )

        self.topology = topology
        self.reference_state = reference_state
        self.branch_materials = materials
        self.environment = environment
        self.bob = bob
        self.rotation_chart_norm_max = chart_limit
        self.prescribed_node_ids = prescribed_ids
        self.prescribed_node_positions = MappingProxyType(prescribed)
        self.explicit_node_mass = MappingProxyType(explicit_mass)
        self.explicit_node_displaced_volume = MappingProxyType(explicit_volume)
        self.node_mass = _readonly(node_mass)
        self.node_displaced_volume = _readonly(node_volume)
        self.segment_materials = tuple(segment_materials)
        self.axial_materials = tuple(axial_materials)
        self.mass_properties = mass_properties
        self.layout = layout
        self._material_by_branch = MappingProxyType(material_by_branch)

    @staticmethod
    def _validated_node_scalars(
        topology: HFV2Topology,
        values: Mapping[str, float],
        name: str,
    ) -> dict[str, float]:
        unknown = set(values) - set(topology.node_ids)
        if unknown:
            raise ValueError(f"{name} contains unknown nodes {sorted(unknown)}.")
        result: dict[str, float] = {}
        for node_id in topology.node_ids:
            scalar = float(values.get(node_id, 0.0))
            if not np.isfinite(scalar) or scalar < 0.0:
                raise ValueError(f"{name}[{node_id!r}] must be finite and non-negative.")
            result[node_id] = scalar
        return result

    def coordinates_from_seed(self, seed: StaticSeed) -> StaticCoordinates:
        if seed.free_node_ids != self.layout.free_node_ids:
            raise ValueError("Seed free-node identities do not match the bound layout.")
        values = np.empty(self.layout.generalized_size, dtype=float)
        values[: 3 * len(seed.free_node_ids)] = seed.free_node_positions.reshape(-1)
        values[self.layout.bob_position_slice.slice] = seed.bob_position
        values[self.layout.bob_rotation_slice.slice] = seed.bob_rotation_vector
        return self.coordinates_from_values(values)

    def coordinates_from_values(self, values: np.ndarray) -> StaticCoordinates:
        vector = np.asarray(values, dtype=float)
        if vector.shape != (self.layout.generalized_size,) or not np.all(np.isfinite(vector)):
            raise ValueError("Coordinate vector does not match the bound generalized layout.")
        rotation_vector = vector[self.layout.bob_rotation_slice.slice]
        if float(np.linalg.norm(rotation_vector)) >= self.rotation_chart_norm_max:
            raise ValueError("Rotation vector left the frozen static coordinate chart.")
        return StaticCoordinates(self.layout.layout_token, vector)

    def _validate_coordinates(self, coordinates: StaticCoordinates) -> np.ndarray:
        if coordinates.layout_token != self.layout.layout_token:
            raise ValueError("StaticCoordinates belong to a different assembly layout.")
        if coordinates.values.shape != (self.layout.generalized_size,):
            raise ValueError("StaticCoordinates size differs from the bound layout.")
        rotation_vector = coordinates.values[self.layout.bob_rotation_slice.slice]
        if float(np.linalg.norm(rotation_vector)) >= self.rotation_chart_norm_max:
            raise ValueError("Rotation vector left the frozen static coordinate chart.")
        return coordinates.values

    def branch_node_ids(self, branch_id: str) -> tuple[str, ...]:
        branch = self.topology.branch_segments(branch_id)
        return (branch[0].start_node,) + tuple(segment.end_node for segment in branch)

    def _node_positions_and_rotation(
        self, values: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        positions = np.empty((len(self.topology.nodes), 3), dtype=float)
        for node_id in self.layout.free_node_ids:
            positions[self.topology.node_index(node_id)] = values[self.layout.free_slice(node_id)]
        for node_id in self.prescribed_node_ids:
            positions[self.topology.node_index(node_id)] = self.prescribed_node_positions[node_id]
        bob_position = values[self.layout.bob_position_slice.slice]
        rotation_vector = values[self.layout.bob_rotation_slice.slice]
        rotation = compose_rotation(
            self.reference_state.bob_rotation,
            exp_so3(rotation_vector),
        )
        attachment_position = bob_position + rotation @ self.bob.attachment_arm_body
        attachment_id = next(
            node.node_id for node in self.topology.nodes if node.kind == "bob_attachment"
        )
        positions[self.topology.node_index(attachment_id)] = attachment_position
        return positions, bob_position, rotation, rotation_vector

    def evaluate(self, coordinates: StaticCoordinates) -> StaticEvaluation:
        values = self._validate_coordinates(coordinates)
        positions, bob_position, rotation, rotation_vector = self._node_positions_and_rotation(
            values
        )
        node_forces = np.zeros_like(positions)
        external_node_forces = np.zeros_like(positions)
        segment_lengths = np.empty(len(self.topology.segments), dtype=float)
        segment_extensions = np.empty(len(self.topology.segments), dtype=float)
        segment_tensions = np.empty(len(self.topology.segments), dtype=float)
        axial_energy = 0.0
        zero = np.zeros(3)
        for index, (segment, material) in enumerate(
            zip(self.topology.segments, self.axial_materials, strict=True)
        ):
            start_index = self.topology.node_index(segment.start_node)
            end_index = self.topology.node_index(segment.end_node)
            response = axial_segment_response(
                positions[start_index],
                positions[end_index],
                zero,
                zero,
                material,
            )
            node_forces[start_index] += response.force_on_start
            node_forces[end_index] += response.force_on_end
            axial_energy += response.stored_energy
            segment_lengths[index] = response.current_length
            segment_extensions[index] = response.extension
            segment_tensions[index] = response.tension

        bending_energy = 0.0
        curvature_denominators: list[tuple[str, float]] = []
        for material in self.branch_materials:
            branch_segments = self.topology.branch_segments(material.branch_id)
            branch_nodes = self.branch_node_ids(material.branch_id)
            if material.bending_stiffness == 0.0 or len(branch_nodes) < 3:
                curvature_denominators.append((material.branch_id, float("inf")))
                continue
            node_indices = [self.topology.node_index(node_id) for node_id in branch_nodes]
            rest = np.array([segment.rest_length for segment in branch_segments])
            response = bending_energy_forces(
                positions[node_indices],
                rest,
                material.bending_stiffness,
            )
            bending_energy += response.energy
            for local_index, node_index in enumerate(node_indices):
                node_forces[node_index] += response.forces[local_index]
            curvature_denominators.append(
                (material.branch_id, float(response.minimum_turn_clearance))
            )

        no_drag = IsotropicDragLaw(enabled=False)
        node_potential = 0.0
        attachment_potential = 0.0
        attachment_id = next(
            node.node_id for node in self.topology.nodes if node.kind == "bob_attachment"
        )
        for node_index, node in enumerate(self.topology.nodes):
            load = point_external_load(
                mass=float(self.node_mass[node_index]),
                displaced_volume=float(self.node_displaced_volume[node_index]),
                fluid_density=self.environment.fluid_density,
                gravity=self.environment.gravity,
                velocity=zero,
                air_velocity=zero,
                drag=no_drag,
                buoyancy_enabled=self.environment.buoyancy_enabled,
            )
            external_node_forces[node_index] = load.total_force
            node_forces[node_index] += load.total_force
            contribution = -float(load.total_force @ positions[node_index])
            if node.node_id == attachment_id:
                attachment_potential += contribution
            else:
                node_potential += contribution

        bob_load = point_external_load(
            mass=self.bob.mass,
            displaced_volume=self.bob.displaced_volume,
            fluid_density=self.environment.fluid_density,
            gravity=self.environment.gravity,
            velocity=zero,
            air_velocity=zero,
            drag=no_drag,
            buoyancy_enabled=self.environment.buoyancy_enabled,
        )
        bob_potential = -float(bob_load.total_force @ bob_position)
        attachment_index = self.topology.node_index(attachment_id)
        attachment_force = node_forces[attachment_index]
        bob_torque_body = np.cross(
            self.bob.attachment_arm_body,
            rotation.T @ attachment_force,
        )
        coordinate_rotation_force = _right_jacobian_so3(rotation_vector).T @ bob_torque_body

        generalized_force = np.empty(self.layout.generalized_size, dtype=float)
        for node_id in self.layout.free_node_ids:
            generalized_force[self.layout.free_slice(node_id)] = node_forces[
                self.topology.node_index(node_id)
            ]
        generalized_force[self.layout.bob_position_slice.slice] = (
            bob_load.total_force + attachment_force
        )
        generalized_force[self.layout.bob_rotation_slice.slice] = coordinate_rotation_force

        support_reactions = np.vstack(
            [-node_forces[self.topology.node_index(node_id)] for node_id in self.prescribed_node_ids]
        )
        components = (
            ("unilateral_axial", float(axial_energy)),
            ("discrete_bending", float(bending_energy)),
            ("material_node_gravity_buoyancy", float(node_potential)),
            ("attachment_node_gravity_buoyancy", float(attachment_potential)),
            ("bob_center_gravity_buoyancy", float(bob_potential)),
        )
        total_potential = float(sum(value for _, value in components))
        if not np.isfinite(total_potential) or not np.all(np.isfinite(generalized_force)):
            raise FloatingPointError("Static total potential or generalized force is non-finite.")
        return StaticEvaluation(
            coordinates=coordinates,
            total_potential=total_potential,
            energy_components=components,
            generalized_force=_readonly(generalized_force),
            bob_torque_body=_readonly(bob_torque_body),
            node_positions=_readonly(positions),
            node_forces=_readonly(node_forces),
            external_node_forces=_readonly(external_node_forces),
            prescribed_node_ids=self.prescribed_node_ids,
            support_reactions=_readonly(support_reactions),
            bob_position=_readonly(bob_position),
            bob_rotation=_readonly(rotation),
            attachment_position=_readonly(positions[attachment_index]),
            bob_external_force=_readonly(bob_load.total_force),
            segment_ids=self.layout.segment_ids,
            segment_current_lengths=_readonly(segment_lengths),
            segment_extensions=_readonly(segment_extensions),
            segment_tensions=_readonly(segment_tensions),
            branch_minimum_curvature_denominators=tuple(curvature_denominators),
        )

    def total_reference_material_mass(self) -> float:
        return float(np.sum(self.node_mass))

    def expected_reference_material_mass(self) -> float:
        explicit = float(sum(self.explicit_node_mass.values()))
        segments = sum(
            material.line_density * segment.rest_length
            for segment, material in zip(
                self.topology.segments,
                self.segment_materials,
                strict=True,
            )
        )
        return float(explicit + segments)

    def total_reference_displaced_volume(self) -> float:
        return float(np.sum(self.node_displaced_volume))

    def expected_reference_displaced_volume(self) -> float:
        explicit = float(sum(self.explicit_node_displaced_volume.values()))
        segments = sum(
            material.displaced_volume_per_length * segment.rest_length
            for segment, material in zip(
                self.topology.segments,
                self.segment_materials,
                strict=True,
            )
        )
        return float(explicit + segments)

    def rest_binding_errors(self) -> np.ndarray:
        return _readonly(
            np.array(
                [
                    material.rest_length - segment.rest_length
                    for segment, material in zip(
                        self.topology.segments,
                        self.axial_materials,
                        strict=True,
                    )
                ]
            )
        )

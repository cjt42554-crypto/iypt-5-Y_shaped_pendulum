"""Regression and canonical static-case construction kept outside production."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ypendulum_static_reference.rigid.rotation import exp_so3
from ypendulum_static_reference.state import StaticReferenceState
from ypendulum_static_reference.statics.assembly import StaticAssembly
from ypendulum_static_reference.statics.contracts import (
    BranchMaterial,
    RigidBobProperties,
    StaticEnvironment,
    StaticSeed,
)
from ypendulum_static_reference.topology import (
    MaterialNode,
    MaterialSegment,
    StaticReferenceTopology,
)


@dataclass(frozen=True)
class VerticalAnalyticExpectation:
    bob_position_m: np.ndarray
    support_reaction_N: np.ndarray
    tension_N: float
    physical_translation_hessian_eigenvalues: np.ndarray


@dataclass(frozen=True)
class VerticalCase:
    assembly: StaticAssembly
    seeds: tuple[StaticSeed, ...]
    expectation: VerticalAnalyticExpectation


@dataclass(frozen=True)
class YAnchorCase:
    assembly: StaticAssembly
    seeds: tuple[StaticSeed, ...]
    mesh_segments_per_branch: int
    junction_id: str
    attachment_id: str


def _static_state(
    free_node_ids: tuple[str, ...],
    free_positions: np.ndarray,
    bob_position: np.ndarray,
    bob_rotation: np.ndarray,
) -> StaticReferenceState:
    return StaticReferenceState(
        free_node_ids=free_node_ids,
        free_node_positions=free_positions,
        bob_position=bob_position,
        bob_rotation=bob_rotation,
    )


def build_vertical_case(manifest: dict[str, Any]) -> VerticalCase:
    case = manifest["analytic_vertical_case"]
    rest = float(case["rest_length_m"])
    topology = StaticReferenceTopology(
        nodes=(
            MaterialNode("support", "prescribed"),
            MaterialNode("attachment", "bob_attachment"),
        ),
        segments=(
            MaterialSegment(
                "vertical_s000",
                "vertical",
                "support",
                "attachment",
                0.0,
                rest,
            ),
        ),
    )
    initial_bob = np.asarray(case["initial_bob_position_m"], dtype=float)
    state = _static_state((), np.empty((0, 3)), initial_bob, np.eye(3))
    material = BranchMaterial(
        branch_id="vertical",
        axial_rigidity=float(case["axial_rigidity_N"]),
        bending_stiffness=float(case["bending_stiffness_N_m2"]),
        line_density=float(case["line_density_kg_per_m"]),
        displaced_volume_per_length=float(case["displaced_volume_per_length_m2"]),
    )
    environment = StaticEnvironment(
        gravity=np.asarray(case["gravity_m_per_s2"], dtype=float),
        fluid_density=float(case["fluid_density_kg_per_m3"]),
        buoyancy_enabled=bool(case["buoyancy_enabled"]),
    )
    bob = RigidBobProperties(
        mass=float(case["bob_mass_kg"]),
        displaced_volume=float(case["bob_displaced_volume_m3"]),
        attachment_arm_body=np.asarray(case["attachment_arm_body_m"], dtype=float),
    )
    assembly = StaticAssembly(
        topology=topology,
        reference_state=state,
        branch_materials=(material,),
        prescribed_node_positions={
            "support": np.asarray(case["support_position_m"], dtype=float)
        },
        environment=environment,
        bob=bob,
        rotation_chart_norm_max=float(
            manifest["coordinate_chart"]["rotation_chart_norm_max_rad"]
        ),
    )
    seed = StaticSeed(
        seed_id="vertical_seed_00",
        free_node_ids=(),
        free_node_positions=np.empty((0, 3)),
        bob_position=initial_bob,
        bob_rotation_vector=np.zeros(3),
    )

    fluid_density = environment.fluid_density if environment.buoyancy_enabled else 0.0
    segment_effective_mass = rest * (
        material.line_density
        - fluid_density * material.displaced_volume_per_length
    )
    bob_effective_mass = bob.mass - fluid_density * bob.displaced_volume
    moving_effective_mass = bob_effective_mass + 0.5 * segment_effective_mass
    gravity_magnitude = float(np.linalg.norm(environment.gravity))
    tension = moving_effective_mass * gravity_magnitude
    extension = tension * rest / material.axial_rigidity
    current_length = rest + extension
    support_position = np.asarray(case["support_position_m"], dtype=float)
    direction = environment.gravity / gravity_magnitude
    expected_bob = support_position + current_length * direction
    total_effective_mass = bob_effective_mass + segment_effective_mass
    support_reaction = -total_effective_mass * environment.gravity
    stiffness = material.axial_rigidity / rest
    translation_eigenvalues = np.array(
        [tension / current_length, tension / current_length, stiffness]
    )
    return VerticalCase(
        assembly=assembly,
        seeds=(seed,),
        expectation=VerticalAnalyticExpectation(
            bob_position_m=expected_bob,
            support_reaction_N=support_reaction,
            tension_N=tension,
            physical_translation_hessian_eigenvalues=np.sort(translation_eigenvalues),
        ),
    )


def _branch_segments(
    branch_id: str,
    node_ids: tuple[str, ...],
    rest_length: float,
) -> tuple[MaterialSegment, ...]:
    count = len(node_ids) - 1
    return tuple(
        MaterialSegment(
            segment_id=f"{branch_id}_s{index:03d}",
            branch_id=branch_id,
            start_node=node_ids[index],
            end_node=node_ids[index + 1],
            material_start=rest_length * index / count,
            material_end=rest_length * (index + 1) / count,
        )
        for index in range(count)
    )


def _interpolate_chain(
    node_ids: tuple[str, ...],
    start: np.ndarray,
    end: np.ndarray,
    *,
    transverse_amplitude: float,
) -> dict[str, np.ndarray]:
    result: dict[str, np.ndarray] = {}
    denominator = len(node_ids) - 1
    for index, node_id in enumerate(node_ids):
        fraction = index / denominator
        position = (1.0 - fraction) * start + fraction * end
        position = np.array(position, copy=True)
        position[1] += transverse_amplitude * np.sin(np.pi * fraction)
        result[node_id] = position
    return result


def build_y_anchor_case(
    manifest: dict[str, Any],
    mesh_segments_per_branch: int,
) -> YAnchorCase:
    case = manifest["y_anchor"]
    count = int(mesh_segments_per_branch)
    if count not in tuple(int(value) for value in case["mesh_segments_per_branch"]):
        raise ValueError("Requested Y mesh is absent from the frozen manifest.")
    left_interior = tuple(f"left_n{index:03d}" for index in range(1, count))
    right_interior = tuple(f"right_n{index:03d}" for index in range(1, count))
    lower_interior = tuple(f"lower_n{index:03d}" for index in range(1, count))
    left_chain = ("support_left",) + left_interior + ("junction",)
    right_chain = ("support_right",) + right_interior + ("junction",)
    lower_chain = ("junction",) + lower_interior + ("attachment",)
    nodes = (
        MaterialNode("support_left", "prescribed"),
        MaterialNode("support_right", "prescribed"),
        *(MaterialNode(node_id, "free") for node_id in left_interior),
        *(MaterialNode(node_id, "free") for node_id in right_interior),
        MaterialNode("junction", "free"),
        *(MaterialNode(node_id, "free") for node_id in lower_interior),
        MaterialNode("attachment", "bob_attachment"),
    )
    upper_rest = float(case["upper_branch_rest_length_m"])
    lower_rest = float(case["lower_branch_rest_length_m"])
    segments = (
        *_branch_segments("left", left_chain, upper_rest),
        *_branch_segments("right", right_chain, upper_rest),
        *_branch_segments("lower", lower_chain, lower_rest),
    )
    topology = StaticReferenceTopology(nodes=nodes, segments=segments)
    left_support = np.asarray(case["support_left_position_m"], dtype=float)
    right_support = np.asarray(case["support_right_position_m"], dtype=float)
    geometry = case["base_geometry"]
    junction = np.asarray(geometry["junction_position_m"], dtype=float)
    attachment = np.asarray(geometry["attachment_position_m"], dtype=float)
    bob_position = np.asarray(geometry["bob_position_m"], dtype=float)
    reference_rotation = np.asarray(geometry["reference_rotation"], dtype=float)
    arm = np.asarray(case["attachment_arm_body_m"], dtype=float)
    if not np.allclose(bob_position + reference_rotation @ arm, attachment, atol=1.0e-15):
        raise ValueError("Frozen base attachment position conflicts with rigid kinematics.")
    base_positions: dict[str, np.ndarray] = {}
    base_positions.update(
        _interpolate_chain(
            left_chain,
            left_support,
            junction,
            transverse_amplitude=0.0,
        )
    )
    base_positions.update(
        _interpolate_chain(
            right_chain,
            right_support,
            junction,
            transverse_amplitude=0.0,
        )
    )
    base_positions.update(
        _interpolate_chain(
            lower_chain,
            junction,
            attachment,
            transverse_amplitude=0.0,
        )
    )
    free_positions = np.vstack(
        [base_positions[node_id] for node_id in topology.free_node_ids]
    )
    state = _static_state(
        topology.free_node_ids,
        free_positions,
        bob_position,
        reference_rotation,
    )
    common = {
        "bending_stiffness": float(case["bending_stiffness_N_m2"]),
        "line_density": float(case["line_density_kg_per_m"]),
        "displaced_volume_per_length": float(
            case["displaced_volume_per_length_m2"]
        ),
    }
    materials = (
        BranchMaterial(
            "left",
            axial_rigidity=float(case["upper_axial_rigidity_N"]),
            **common,
        ),
        BranchMaterial(
            "right",
            axial_rigidity=float(case["upper_axial_rigidity_N"]),
            **common,
        ),
        BranchMaterial(
            "lower",
            axial_rigidity=float(case["lower_axial_rigidity_N"]),
            **common,
        ),
    )
    environment = StaticEnvironment(
        gravity=np.asarray(case["gravity_m_per_s2"], dtype=float),
        fluid_density=float(case["fluid_density_kg_per_m3"]),
        buoyancy_enabled=bool(case["buoyancy_enabled"]),
    )
    bob = RigidBobProperties(
        mass=float(case["bob_mass_kg"]),
        displaced_volume=float(case["bob_displaced_volume_m3"]),
        attachment_arm_body=arm,
    )
    assembly = StaticAssembly(
        topology=topology,
        reference_state=state,
        branch_materials=materials,
        prescribed_node_positions={
            "support_left": left_support,
            "support_right": right_support,
        },
        environment=environment,
        bob=bob,
        explicit_node_mass={
            key: float(value) for key, value in case["explicit_node_mass_kg"].items()
        },
        explicit_node_displaced_volume={
            key: float(value)
            for key, value in case["explicit_node_displaced_volume_m3"].items()
        },
        rotation_chart_norm_max=float(
            manifest["coordinate_chart"]["rotation_chart_norm_max_rad"]
        ),
    )

    seeds: list[StaticSeed] = []
    for seed_contract in case["deterministic_seeds"]:
        seed_junction = junction + np.asarray(
            seed_contract["junction_offset_m"], dtype=float
        )
        seed_bob = bob_position + np.asarray(seed_contract["bob_offset_m"], dtype=float)
        rotation_vector = np.asarray(seed_contract["rotation_vector_rad"], dtype=float)
        seed_attachment = seed_bob + reference_rotation @ exp_so3(rotation_vector) @ arm
        amplitude = float(seed_contract["interior_y_amplitude_m"])
        seed_positions: dict[str, np.ndarray] = {}
        seed_positions.update(
            _interpolate_chain(
                left_chain,
                left_support,
                seed_junction,
                transverse_amplitude=amplitude,
            )
        )
        seed_positions.update(
            _interpolate_chain(
                right_chain,
                right_support,
                seed_junction,
                transverse_amplitude=-amplitude,
            )
        )
        seed_positions.update(
            _interpolate_chain(
                lower_chain,
                seed_junction,
                seed_attachment,
                transverse_amplitude=0.5 * amplitude,
            )
        )
        seeds.append(
            StaticSeed(
                seed_id=str(seed_contract["seed_id"]),
                free_node_ids=topology.free_node_ids,
                free_node_positions=np.vstack(
                    [seed_positions[node_id] for node_id in topology.free_node_ids]
                ),
                bob_position=seed_bob,
                bob_rotation_vector=rotation_vector,
            )
        )
    return YAnchorCase(
        assembly=assembly,
        seeds=tuple(seeds),
        mesh_segments_per_branch=count,
        junction_id="junction",
        attachment_id="attachment",
    )

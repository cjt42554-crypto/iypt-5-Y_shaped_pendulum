from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from ypendulum_hfv2.audit.g2_cases import build_vertical_case, build_y_anchor_case
from ypendulum_hfv2.audit.statics import energy_force_samples, force_scale
from ypendulum_hfv2.statics.contracts import BranchMaterial, StaticCoordinates, StaticSeed

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads(
    (CANDIDATE_ROOT / "contracts" / "g2_acceptance_manifest.json").read_text(
        encoding="utf-8"
    )
)


def test_branch_material_has_no_second_rest_length_input() -> None:
    assert "rest_length" not in BranchMaterial.__dataclass_fields__


def test_assembly_binds_layout_and_rejects_identity_mismatch() -> None:
    case = build_y_anchor_case(MANIFEST, 2)
    seed = case.seeds[0]
    wrong_seed = StaticSeed(
        seed_id="wrong",
        free_node_ids=tuple(reversed(seed.free_node_ids)),
        free_node_positions=seed.free_node_positions[::-1],
        bob_position=seed.bob_position,
        bob_rotation_vector=seed.bob_rotation_vector,
    )
    with pytest.raises(ValueError, match="identities"):
        case.assembly.coordinates_from_seed(wrong_seed)
    valid = case.assembly.coordinates_from_seed(seed)
    alien = StaticCoordinates("alien-layout", valid.values)
    with pytest.raises(ValueError, match="different assembly"):
        case.assembly.evaluate(alien)


def test_reference_mass_lumping_accumulates_shared_and_attachment_nodes() -> None:
    case = build_y_anchor_case(MANIFEST, 2)
    assembly = case.assembly
    density = MANIFEST["y_anchor"]["line_density_kg_per_m"]
    upper_segment_rest = MANIFEST["y_anchor"]["upper_branch_rest_length_m"] / 2
    lower_segment_rest = MANIFEST["y_anchor"]["lower_branch_rest_length_m"] / 2
    expected_junction = MANIFEST["y_anchor"]["explicit_node_mass_kg"]["junction"]
    expected_junction += 0.5 * density * (
        upper_segment_rest + upper_segment_rest + lower_segment_rest
    )
    expected_attachment = MANIFEST["y_anchor"]["explicit_node_mass_kg"]["attachment"]
    expected_attachment += 0.5 * density * lower_segment_rest
    assert assembly.node_mass[assembly.topology.node_index("junction")] == pytest.approx(
        expected_junction
    )
    assert assembly.node_mass[assembly.topology.node_index("attachment")] == pytest.approx(
        expected_attachment
    )
    assert assembly.total_reference_material_mass() == pytest.approx(
        assembly.expected_reference_material_mass(), abs=2.0e-15
    )
    assert assembly.total_reference_displaced_volume() == pytest.approx(
        assembly.expected_reference_displaced_volume(), abs=2.0e-15
    )


def test_assembly_energy_force_includes_nonzero_rotation_probe() -> None:
    case = build_y_anchor_case(MANIFEST, 2)
    probe = case.assembly.coordinates_from_seed(case.seeds[1])
    samples = energy_force_samples(
        case.assembly,
        probe,
        tuple(MANIFEST["finite_difference"]["relative_step_sequence"]),
    )
    assert samples[-1].relative_error <= MANIFEST["finite_difference"][
        "final_relative_error_max"
    ]
    rotation_force = case.assembly.evaluate(probe).generalized_force[
        case.assembly.layout.bob_rotation_slice.slice
    ]
    assert np.linalg.norm(rotation_force) > 0.0


def test_vertical_attachment_endpoint_mass_is_not_merged_into_bob_center() -> None:
    case = build_vertical_case(MANIFEST)
    assembly = case.assembly
    attachment_mass = assembly.node_mass[assembly.topology.node_index("attachment")]
    assert attachment_mass > 0.0
    assert assembly.bob.mass == MANIFEST["analytic_vertical_case"]["bob_mass_kg"]
    assert assembly.bob.mass != pytest.approx(assembly.bob.mass + attachment_mass)


def test_prescribed_endpoint_mass_contributes_constant_gravitational_potential() -> None:
    base = build_vertical_case(MANIFEST)
    shifted_manifest = copy.deepcopy(MANIFEST)
    vertical = shifted_manifest["analytic_vertical_case"]
    vertical_shift = 0.4
    vertical["support_position_m"][2] += vertical_shift
    vertical["initial_bob_position_m"][2] += vertical_shift
    shifted = build_vertical_case(shifted_manifest)
    base_evaluation = base.assembly.evaluate(
        base.assembly.coordinates_from_seed(base.seeds[0])
    )
    shifted_evaluation = shifted.assembly.evaluate(
        shifted.assembly.coordinates_from_seed(shifted.seeds[0])
    )
    assert shifted_evaluation.total_potential - base_evaluation.total_potential == pytest.approx(
        force_scale(base.assembly) * vertical_shift,
        abs=2.0e-14,
    )
    np.testing.assert_allclose(
        shifted_evaluation.generalized_force,
        base_evaluation.generalized_force,
        rtol=0.0,
        atol=2.0e-14,
    )

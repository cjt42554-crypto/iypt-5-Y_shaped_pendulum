from __future__ import annotations

import copy
import json
import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.optimize import OptimizeWarning

from ypendulum_hfv2.audit.g2_cases import build_vertical_case, build_y_anchor_case
from ypendulum_hfv2.audit.statics import energy_force_samples, force_scale
from ypendulum_hfv2.rigid.rotation import exp_so3
from ypendulum_hfv2.state import HFV2State
from ypendulum_hfv2.statics import solver as static_solver
from ypendulum_hfv2.statics.assembly import StaticAssembly
from ypendulum_hfv2.statics.contracts import (
    BranchMaterial,
    StaticCoordinates,
    StaticSeed,
)
from ypendulum_hfv2.topology import HFV2Topology, MaterialNode

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


def _assert_foreign_coordinates_fail_closed(
    source: StaticAssembly,
    variant: StaticAssembly,
    seed: StaticSeed,
) -> None:
    coordinates = source.coordinates_from_seed(seed)
    assert source.layout.identity_schema == "YPS-HFV2-STATIC-ASSEMBLY-IDENTITY-1.0"
    assert variant.layout.layout_token != source.layout.layout_token
    with pytest.raises(ValueError, match="different assembly"):
        variant.evaluate(coordinates)


def test_complete_assembly_identity_rejects_real_physical_variants() -> None:
    base_case = build_y_anchor_case(MANIFEST, 2)
    base = base_case.assembly
    seed = base_case.seeds[0]

    rotated_manifest = copy.deepcopy(MANIFEST)
    rotated_manifest["y_anchor"]["base_geometry"]["reference_rotation"] = exp_so3(
        np.array([0.0, 0.0, 0.1])
    ).tolist()
    rotated = build_y_anchor_case(rotated_manifest, 2).assembly
    _assert_foreign_coordinates_fail_closed(base, rotated, seed)

    shifted_manifest = copy.deepcopy(MANIFEST)
    shifted_manifest["y_anchor"]["support_left_position_m"][1] = 0.01
    shifted = build_y_anchor_case(shifted_manifest, 2).assembly
    _assert_foreign_coordinates_fail_closed(base, shifted, seed)

    gravity_manifest = copy.deepcopy(MANIFEST)
    gravity_manifest["y_anchor"]["gravity_m_per_s2"][2] = -9.8
    changed_gravity = build_y_anchor_case(gravity_manifest, 2).assembly
    _assert_foreign_coordinates_fail_closed(base, changed_gravity, seed)

    swapped_nodes = tuple(
        MaterialNode(
            node.node_id,
            "bob_attachment"
            if node.node_id == "support_left"
            else "prescribed"
            if node.node_id == "attachment"
            else node.kind,
        )
        for node in base.topology.nodes
    )
    swapped_topology = HFV2Topology(nodes=swapped_nodes, segments=base.topology.segments)
    swapped_state = HFV2State(
        free_node_ids=base.reference_state.free_node_ids,
        free_node_positions=base.reference_state.free_node_positions,
        free_node_velocities=base.reference_state.free_node_velocities,
        bob_position=base.reference_state.bob_position,
        bob_velocity=base.reference_state.bob_velocity,
        bob_rotation=base.reference_state.bob_rotation,
        bob_angular_velocity_body=base.reference_state.bob_angular_velocity_body,
    )
    swapped = StaticAssembly(
        topology=swapped_topology,
        reference_state=swapped_state,
        branch_materials=base.branch_materials,
        prescribed_node_positions={
            "support_right": base.prescribed_node_positions["support_right"],
            "attachment": base.prescribed_node_positions["support_left"],
        },
        environment=base.environment,
        bob=base.bob,
        explicit_node_mass=base.explicit_node_mass,
        explicit_node_displaced_volume=base.explicit_node_displaced_volume,
        rotation_chart_norm_max=base.rotation_chart_norm_max,
    )
    _assert_foreign_coordinates_fail_closed(base, swapped, seed)


def test_bfgs_receives_every_frozen_option(monkeypatch: pytest.MonkeyPatch) -> None:
    case = build_vertical_case(MANIFEST)
    contract = MANIFEST["primary_solver"]
    settings = static_solver.StaticSolverSettings(
        method=contract["method"],
        gradient_infinity_tolerance=contract["gradient_infinity_tolerance"],
        maximum_iterations=contract["maximum_iterations"],
        x_relative_tolerance=contract["x_relative_tolerance"],
        armijo_c1=contract["armijo_c1"],
        curvature_c2=contract["curvature_c2"],
    )
    captured: dict[str, object] = {}

    def fake_minimize(objective: object, initial: np.ndarray, **kwargs: object) -> object:
        captured.update(kwargs)
        value, gradient = objective(initial)  # type: ignore[operator]
        assert np.isfinite(value)
        assert np.all(np.isfinite(gradient))
        return SimpleNamespace(
            x=np.array(initial, copy=True),
            success=False,
            status=2,
            message="captured without iteration",
            nit=0,
            nfev=1,
            njev=1,
        )

    monkeypatch.setattr(static_solver, "minimize", fake_minimize)
    static_solver.solve_static_seed(case.assembly, case.seeds[0], settings)
    assert captured["method"] == "BFGS"
    assert captured["jac"] is True
    options = captured["options"]
    assert isinstance(options, dict)
    assert options == {
        "gtol": 1.0e-9,
        "maxiter": 2500,
        "xrtol": 0.0,
        "norm": np.inf,
        "disp": False,
        "c1": 1.0e-4,
        "c2": 0.9,
    }


def test_unknown_scipy_solver_options_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_vertical_case(MANIFEST)
    contract = MANIFEST["primary_solver"]
    settings = static_solver.StaticSolverSettings(
        method=contract["method"],
        gradient_infinity_tolerance=contract["gradient_infinity_tolerance"],
        maximum_iterations=contract["maximum_iterations"],
        x_relative_tolerance=contract["x_relative_tolerance"],
        armijo_c1=contract["armijo_c1"],
        curvature_c2=contract["curvature_c2"],
    )

    def warning_minimize(*args: object, **kwargs: object) -> object:
        del args, kwargs
        warnings.warn("Unknown solver options: c1, c2", OptimizeWarning, stacklevel=2)
        raise AssertionError("The warning must be promoted before a result is returned.")

    monkeypatch.setattr(static_solver, "minimize", warning_minimize)
    with pytest.raises(OptimizeWarning, match="Unknown solver options"):
        static_solver.solve_static_seed(case.assembly, case.seeds[0], settings)


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

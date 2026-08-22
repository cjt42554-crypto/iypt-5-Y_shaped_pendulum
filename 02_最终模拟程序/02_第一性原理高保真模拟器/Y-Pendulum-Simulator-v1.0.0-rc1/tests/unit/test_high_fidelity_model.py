from __future__ import annotations

import numpy as np
import pytest

from ypendulum.hf.model import (
    HighFidelityModel,
    _batched_segment_segment_distance,
    _materially_separated_segment_distance,
    _passive_axial_kelvin_voigt_response,
    _segment_segment_distance,
    discrete_bending_energy_forces,
    quaternion_multiply,
    rotate_body_vector,
)
from ypendulum.hf.solver import (
    _coalesce_terminal_certificate,
    _integrate_with_accepted_step_cap,
    _sampled_axial_events,
    prepare_initial_state,
    simulate_high_fidelity,
)


def _hf_config(config):
    config.run.mode = "high_fidelity"
    config.initial_condition.bob_position = {
        "value": [0.0, 0.0, -0.70],
        "unit": "m",
    }
    config.initial_condition.type = "cartesian_release"
    config.initial_condition.bob_velocity = {
        "value": [0.0, 0.0, 0.0],
        "unit": "m/s",
    }
    config.initial_condition.bob_angular_velocity = {
        "value": [0.0, 0.0, 0.0],
        "unit": "rad/s",
    }
    config.high_fidelity.contact_guard_enabled = False
    return config


def test_batched_segment_distance_matches_scalar_for_adversarial_pairs() -> None:
    rng = np.random.default_rng(20260821)
    first_start = rng.normal(size=(512, 3))
    first_end = first_start + rng.normal(size=(512, 3))
    second_start = rng.normal(size=(512, 3))
    second_end = second_start + rng.normal(size=(512, 3))
    first_end[:8] = first_start[:8]
    second_end[8:16] = second_start[8:16]
    second_start[16:24] = first_start[16:24] + np.array([0.0, 1.0, 0.0])
    second_end[16:24] = second_start[16:24] + (
        first_end[16:24] - first_start[16:24]
    )
    batched = _batched_segment_segment_distance(
        first_start,
        first_end,
        second_start,
        second_end,
    )
    scalar = np.asarray(
        [
            _segment_segment_distance(p0, p1, q0, q1)
            for p0, p1, q0, q1 in zip(
                first_start,
                first_end,
                second_start,
                second_end,
                strict=True,
            )
        ]
    )
    assert np.allclose(batched, scalar, rtol=2.0e-15, atol=2.0e-15)


def test_discrete_bending_force_is_negative_energy_gradient_and_objective() -> None:
    points = np.array(
        [
            [-0.31, 0.11, 0.07],
            [-0.09, -0.04, -0.02],
            [0.14, 0.02, -0.13],
            [0.32, 0.16, -0.06],
        ],
        dtype=float,
    )
    rest = np.array([0.25, 0.27, 0.24])
    ei = 3.7e-5
    energy, force = discrete_bending_energy_forces(points, rest, ei)

    numerical_gradient = np.empty_like(points)
    step = 2.0e-7
    for index in np.ndindex(points.shape):
        plus = points.copy()
        minus = points.copy()
        plus[index] += step
        minus[index] -= step
        e_plus, _ = discrete_bending_energy_forces(plus, rest, ei)
        e_minus, _ = discrete_bending_energy_forces(minus, rest, ei)
        numerical_gradient[index] = (e_plus - e_minus) / (2.0 * step)

    assert energy > 0.0
    assert np.allclose(force, -numerical_gradient, rtol=2.0e-7, atol=2.0e-10)
    # Translation and rotation invariance imply zero resultant force and torque.
    assert np.allclose(np.sum(force, axis=0), 0.0, atol=2.0e-14)
    assert np.allclose(
        np.sum(np.cross(points, force), axis=0), 0.0, atol=2.0e-14
    )

    angle = 0.63
    rotation = np.array(
        [
            [np.cos(angle), -np.sin(angle), 0.0],
            [np.sin(angle), np.cos(angle), 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    rotated_energy, rotated_force = discrete_bending_energy_forces(
        points @ rotation.T + np.array([0.8, -0.3, 0.4]), rest, ei
    )
    assert np.isclose(rotated_energy, energy, rtol=2.0e-14, atol=2.0e-14)
    assert np.allclose(rotated_force, force @ rotation.T, rtol=2.0e-13, atol=2.0e-13)


def test_discrete_bending_energy_converges_to_circular_elastica_limit() -> None:
    radius = 0.43
    angle = 0.72
    ei = 2.6e-5
    errors = []
    for point_count in (9, 17, 33):
        parameter = np.linspace(-0.5 * angle, 0.5 * angle, point_count)
        points = np.column_stack(
            [
                radius * np.sin(parameter),
                radius * (1.0 - np.cos(parameter)),
                np.zeros(point_count),
            ]
        )
        segment_length = np.linalg.norm(points[1:] - points[:-1], axis=1)
        energy, _ = discrete_bending_energy_forces(points, segment_length, ei)
        # Only internal dual cells carry curvature; the two endpoint traces are
        # natural hinges rather than prescribed directors.
        represented_length = float(
            np.sum(0.5 * (segment_length[:-1] + segment_length[1:]))
        )
        continuum = 0.5 * ei * (1.0 / radius) ** 2 * represented_length
        errors.append(abs(energy - continuum))
    assert max(errors) < 2.0e-13 * continuum


@pytest.mark.parametrize("alpha", [0.0, 0.3, 1.0])
def test_passive_axial_blend_closes_power_for_all_constitutive_regions(
    alpha,
) -> None:
    stiffness = 4.0
    viscosity = 0.7
    states = (
        (-0.02, -0.30),
        (-0.02, 0.30),
        (0.0, 0.30),
        (0.02, 0.10),
        (0.02, -0.10),
        (0.02, -1.00),
    )
    for extension, rate in states:
        signed, tensile, energy, dissipation = (
            _passive_axial_kelvin_voigt_response(
                np.array([extension]),
                np.array([rate]),
                np.array([stiffness]),
                np.array([viscosity]),
                alpha,
            )
        )
        bilateral_force = stiffness * extension + viscosity * rate
        active = extension > 0.0 and bilateral_force > 0.0
        unilateral_force = bilateral_force if active else 0.0
        expected_force = (
            (1.0 - alpha) * unilateral_force + alpha * bilateral_force
        )
        expected_energy = (
            (1.0 - alpha)
            * 0.5
            * stiffness
            * max(extension, 0.0) ** 2
            + alpha * 0.5 * stiffness * extension**2
        )
        energy_rate = (
            (1.0 - alpha)
            * stiffness
            * max(extension, 0.0)
            * rate
            + alpha * stiffness * extension * rate
        )
        assert signed[0] == pytest.approx(expected_force, abs=2.0e-15)
        assert tensile[0] == pytest.approx(max(expected_force, 0.0), abs=2.0e-15)
        assert energy == pytest.approx(expected_energy, abs=2.0e-15)
        assert dissipation >= 0.0
        assert -signed[0] * rate + energy_rate + dissipation == pytest.approx(
            0.0, abs=3.0e-15
        )


def test_uniform_shortening_has_finite_bilateral_energy_and_signed_force(config) -> None:
    cfg = _hf_config(config)
    bilateral = HighFidelityModel(cfg)
    lower = bilateral.branches["lower"]
    particles = bilateral.reference_particle_positions.copy()
    junction = particles[bilateral.junction_index].copy()
    material_length = float(np.sum(lower.segment_rest_length))
    attachment = junction + 0.90 * material_length * bilateral.gravity_direction
    bob = attachment - bilateral.attachment_body
    fractions = np.cumsum(lower.segment_rest_length)[:-1] / material_length
    particles[lower.bead_indices] = (
        junction[None, :]
        + fractions[:, None] * (attachment - junction)[None, :]
    )
    zero_particles = np.zeros_like(particles)
    zero3 = np.zeros(3)
    quaternion = np.array([1.0, 0.0, 0.0, 0.0])
    finite = bilateral.evaluate(
        0.0,
        particles,
        zero_particles,
        bob,
        zero3,
        quaternion,
        zero3,
        include_aero=False,
        compute_contact=False,
    )
    extension = -0.10 * lower.segment_rest_length
    expected_force = (lower.ea / lower.segment_rest_length) * extension
    expected_energy = 0.5 * float(
        np.sum((lower.ea / lower.segment_rest_length) * extension**2)
    )
    assert np.allclose(
        finite.branch_axial_force["lower"], expected_force, rtol=2.0e-14
    )
    assert np.array_equal(
        finite.branch_tension["lower"], np.zeros_like(expected_force)
    )

    cfg.high_fidelity.compression_regularization_scale = 0.0
    unilateral_model = HighFidelityModel(cfg)
    unilateral = unilateral_model.evaluate(
        0.0,
        particles,
        zero_particles,
        bob,
        zero3,
        quaternion,
        zero3,
        include_aero=False,
        compute_contact=False,
    )
    assert np.array_equal(
        unilateral.branch_axial_force["lower"], np.zeros_like(expected_force)
    )
    assert finite.axial_energy - unilateral.axial_energy == pytest.approx(
        expected_energy, rel=3.0e-13, abs=2.0e-15
    )


def test_bilateral_compression_events_are_never_named_slack_or_retension() -> None:
    time = np.array([0.0, 0.1, 0.2])
    signed = {"lower": np.array([[-1.0], [0.0], [2.0]])}
    tensile = {"lower": np.maximum(signed["lower"], 0.0)}
    events = _sampled_axial_events(
        time,
        tensile,
        signed,
        zero_tolerance=1.0e-12,
        compression_regularization_scale=1.0,
    )
    event_types = {event["type"] for event in events}
    assert "HF_SEGMENT_INITIAL_AXIAL_REGIME" in event_types
    assert "HF_SEGMENT_AXIAL_REGIME_CHANGE_SAMPLED_BRACKET" in event_types
    assert all("SLACK" not in name and "RETENSION" not in name for name in event_types)
    assert events[0]["axial_regime"] == "COMPRESSION"

    unilateral = _sampled_axial_events(
        time,
        {"lower": np.array([[0.0], [0.0], [2.0]])},
        {"lower": np.array([[0.0], [0.0], [2.0]])},
        zero_tolerance=1.0e-12,
        compression_regularization_scale=0.0,
    )
    assert any("SLACK" in event["type"] for event in unilateral)


def test_closed_segment_distance_is_symmetric_for_overlap_and_near_parallel_crossing() -> None:
    cases = (
        (
            np.array([-1.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),
            np.array([-0.5, 0.0, 0.0]),
            np.array([0.5, 0.0, 0.0]),
            0.0,
        ),
        (
            np.array([-0.5, 0.0, 0.0]),
            np.array([0.5, 0.0, 0.0]),
            np.array([-0.5, -5.0e-9, 0.0]),
            np.array([0.5, 5.0e-9, 0.0]),
            0.0,
        ),
        (
            np.array([0.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),
            np.array([0.2, 0.04, 0.0]),
            np.array([0.8, 0.04, 0.0]),
            0.04,
        ),
    )
    for first_start, first_end, second_start, second_end, expected in cases:
        for reverse_first in (False, True):
            for reverse_second in (False, True):
                p0, p1 = (
                    (first_end, first_start)
                    if reverse_first
                    else (first_start, first_end)
                )
                q0, q1 = (
                    (second_end, second_start)
                    if reverse_second
                    else (second_start, second_end)
                )
                forward = _segment_segment_distance(p0, p1, q0, q1)
                exchanged = _segment_segment_distance(q0, q1, p0, p1)
                assert forward == pytest.approx(expected, abs=2.0e-15)
                assert exchanged == pytest.approx(forward, abs=2.0e-15)


def test_fixed_material_self_neighbourhood_is_mesh_objective_and_detects_hairpin() -> None:
    length = 0.30
    diameter = 0.003
    clearance = 0.0002
    registered_length = 1.01 * (diameter + clearance)
    expected_guard = registered_length - diameter - clearance
    for count in (16, 48, 96, 192, 256):
        nodes = np.linspace(0.0, length, count + 1)
        points = np.column_stack([nodes, np.zeros_like(nodes), np.zeros_like(nodes)])
        minimum = float("inf")
        for first in range(count):
            for second in range(first + 1, count):
                minimum = min(
                    minimum,
                    _materially_separated_segment_distance(
                        points[first],
                        points[first + 1],
                        points[second],
                        points[second + 1],
                        first_material_start=float(nodes[first]),
                        first_material_end=float(nodes[first + 1]),
                        second_material_start=float(nodes[second]),
                        second_material_end=float(nodes[second + 1]),
                        minimum_material_separation=registered_length,
                    ),
                )
        assert minimum - diameter - clearance == pytest.approx(
            expected_guard, abs=3.0e-14
        )

    crossing = _materially_separated_segment_distance(
        np.array([-0.03, 0.0, 0.0]),
        np.array([0.03, 0.0, 0.0]),
        np.array([0.0, -0.03, 0.0]),
        np.array([0.0, 0.03, 0.0]),
        first_material_start=0.0,
        first_material_end=0.06,
        second_material_start=0.12,
        second_material_end=0.18,
        minimum_material_separation=registered_length,
    )
    assert crossing == pytest.approx(0.0, abs=2.0e-15)


def test_material_contact_domain_is_scale_homogeneous() -> None:
    values = []
    for scale in (1.0, 1.0e-6):
        distance = _materially_separated_segment_distance(
            scale * np.array([0.0, 0.0, 0.0]),
            scale * np.array([0.04, 0.0, 0.0]),
            scale * np.array([0.01, 0.006, 0.0]),
            scale * np.array([0.03, 0.006, 0.0]),
            first_material_start=scale * 0.0,
            first_material_end=scale * 0.04,
            second_material_start=scale * 0.08,
            second_material_end=scale * 0.10,
            minimum_material_separation=scale * 0.0032,
        )
        values.append(distance / scale)
    assert values[1] == pytest.approx(values[0], rel=3.0e-14, abs=2.0e-15)


def test_material_bead_masses_exactly_recover_each_measured_cable_mass(config) -> None:
    cfg = _hf_config(config)
    model = HighFidelityModel(cfg)
    for name, branch in model.branches.items():
        cable = getattr(cfg.cables, name)
        diameter = float(cable.diameter["value"])
        density = float(cable.density["value"])
        rest_length = float(cable.rest_length["value"])
        expected = density * np.pi * diameter**2 / 4.0 * rest_length
        represented = float(np.sum(model.particle_mass[branch.bead_indices]))
        assert np.isclose(represented, expected, rtol=2.0e-15, atol=2.0e-18)


def test_finite_bob_attachment_generates_newton_euler_torque(config) -> None:
    cfg = _hf_config(config)
    model = HighFidelityModel(cfg)
    particles = model.reference_particle_positions.copy()
    # Move the bob sideways so the lower-rod force does not pass through its COM.
    bob = model.reference_bob_position + np.array([0.035, -0.012, 0.0])
    zero_particles = np.zeros_like(particles)
    zero3 = np.zeros(3)
    quaternion = np.array([1.0, 0.0, 0.0, 0.0])
    evaluation = model.evaluate(
        0.0,
        particles,
        zero_particles,
        bob,
        zero3,
        quaternion,
        zero3,
        include_aero=False,
    )
    cable_force = evaluation.bob_force - model.bob_mass * model.gravity - model.bob_buoyancy
    expected_torque = np.cross(model.attachment_body, cable_force)

    assert np.linalg.norm(cable_force) > 0.0
    assert np.linalg.norm(evaluation.bob_torque) > 0.0
    assert np.allclose(evaluation.bob_torque, expected_torque, rtol=2.0e-13, atol=2.0e-13)


def test_hf_static_preparation_and_short_run_close_contracts(config) -> None:
    cfg = _hf_config(config)
    cfg.solver.t_end = {"value": 4.0e-4, "unit": "s"}
    cfg.solver.output_dt = {"value": 1.0e-4, "unit": "s"}
    cfg.solver.max_step = {"value": 5.0e-5, "unit": "s"}
    model = HighFidelityModel(cfg)
    # Use the model's own geometric release point; the held preparation solves
    # all rod beads and the junction while keeping the bob at this measured input.
    cfg.initial_condition.bob_position = {
        "value": model.reference_bob_position.tolist(),
        "unit": "m",
    }
    preparation = prepare_initial_state(cfg, model)
    result = simulate_high_fidelity(cfg, model=model, preparation=preparation)

    assert preparation.residual_inf_N <= 1.0e-8
    assert result.model_id == "HF-DISCRETE-ROD-RIGID-BOB-1.0"
    assert result.physical_status == "UNDETERMINED"
    assert result.numerical_status == "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"
    assert result.time.shape == (5,)
    assert result.particle_positions.shape[1:] == (model.particle_count, 3)
    assert np.all(np.isfinite(result.particle_positions))
    assert np.all(np.isfinite(result.bob_quaternion))
    assert result.diagnostics["maximum_quaternion_norm_error"] < 1.0e-10
    assert result.diagnostics["max_abs_energy_balance_residual"] < 1.0e-7
    assert result.energy["elastic_bending"].max() > 0.0
    assert (
        result.diagnostics["accepted_integration_step_count"]
        <= result.diagnostics["accepted_integration_step_hard_cap"]
    )


def test_hf_integration_checkpoint_replays_identical_scientific_result(
    config, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("YPS_HF_POSTPROCESS_WORKERS", "1")
    cfg = _hf_config(config)
    cfg.solver.t_end = {"value": 1.0e-4, "unit": "s"}
    cfg.solver.output_dt = {"value": 5.0e-5, "unit": "s"}
    cfg.solver.max_step = {"value": 2.5e-5, "unit": "s"}
    model = HighFidelityModel(cfg)
    cfg.initial_condition.bob_position = {
        "value": model.reference_bob_position.tolist(),
        "unit": "m",
    }
    preparation = prepare_initial_state(cfg, model)
    checkpoint = tmp_path / "integration_checkpoint.npz"
    direct = simulate_high_fidelity(
        cfg,
        model=model,
        preparation=preparation,
        checkpoint_path=checkpoint,
    )
    replay = simulate_high_fidelity(
        cfg,
        model=HighFidelityModel(cfg),
        checkpoint_path=checkpoint,
        resume_from_checkpoint=True,
    )

    for name in (
        "time",
        "integration_time",
        "integration_particle_positions",
        "integration_particle_velocities",
        "integration_bob_position",
        "integration_bob_velocity",
        "integration_bob_quaternion",
        "integration_bob_angular_velocity",
        "particle_positions",
        "particle_velocities",
        "bob_position",
        "bob_velocity",
        "bob_quaternion",
        "bob_angular_velocity",
        "bob_attachment_position",
    ):
        assert np.array_equal(getattr(direct, name), getattr(replay, name))
    for mapping in (
        "cable_positions",
        "cable_velocities",
        "cable_axial_force",
        "cable_tension",
        "guard_margins",
        "energy",
        "reactions",
    ):
        direct_values = getattr(direct, mapping)
        replay_values = getattr(replay, mapping)
        assert direct_values.keys() == replay_values.keys()
        for key in direct_values:
            assert np.array_equal(direct_values[key], replay_values[key])
    assert direct.events == replay.events
    assert replay.diagnostics["integration_checkpoint_reused"] is True
    assert replay.diagnostics["integration_wall_seconds"] == 0.0


def test_bounded_integrator_stops_before_exceeding_accepted_step_cap() -> None:
    class ScalarDecay:
        @staticmethod
        def rhs(_time, state):
            return -np.asarray(state)

    with pytest.raises(RuntimeError, match="HF_ACCEPTED_STEP_BUDGET_EXCEEDED"):
        _integrate_with_accepted_step_cap(
            ScalarDecay(),
            np.array([1.0]),
            t_end=1.0,
            output_time=np.array([0.0, 1.0]),
            method="Radau",
            rtol=1.0e-8,
            atol=np.array([1.0e-10]),
            max_step=0.1,
            jac_sparsity=None,
            guard_names=("ALWAYS_POSITIVE",),
            guard_metadata={
                "ALWAYS_POSITIVE": {
                    "unit": "dimensionless",
                    "scale": 1.0,
                    "tolerance": 0.0,
                }
            },
            guard_components=lambda _time, _state: {
                "ALWAYS_POSITIVE": 1.0
            },
            accepted_step_cap=1,
            terminal_time_tolerance=1.0e-12,
        )


def test_public_hf_solver_rejects_resource_overrun_before_any_allocation(
    config, monkeypatch
) -> None:
    cfg = _hf_config(config)

    def forbidden(*_args, **_kwargs):
        raise AssertionError(
            "resource preflight must precede model/grid allocation"
        )

    monkeypatch.setattr("ypendulum.hf.solver.HighFidelityModel", forbidden)
    monkeypatch.setattr("ypendulum.hf.solver.np.arange", forbidden)

    cfg.solver.t_end = {"value": 1.0, "unit": "s"}
    cfg.solver.output_dt = {"value": 5.0e-324, "unit": "s"}
    with pytest.raises(
        RuntimeError,
        match="HF_RESOURCE_BUDGET_EXCEEDED_AT_SOLVER_ENTRY",
    ):
        simulate_high_fidelity(cfg)

    cfg.solver.output_dt = {"value": float("inf"), "unit": "s"}
    with pytest.raises(ValueError, match="NaN or infinity"):
        simulate_high_fidelity(cfg)

    cfg.solver.t_end = {"value": 0.01, "unit": "s"}
    cfg.solver.output_dt = {"value": 0.001, "unit": "s"}
    cfg.cables.upper_A.elements = 10**200
    with pytest.raises(
        RuntimeError,
        match="HF_RESOURCE_BUDGET_EXCEEDED_AT_SOLVER_ENTRY",
    ):
        simulate_high_fidelity(cfg)


def test_bounded_integrator_preserves_steep_bracketed_guard_identity() -> None:
    class StationaryState:
        @staticmethod
        def rhs(_time, state):
            return np.zeros_like(state)

    trace = _integrate_with_accepted_step_cap(
        StationaryState(),
        np.array([0.0]),
        t_end=1.0,
        output_time=np.array([0.0, 0.25, 0.5, 0.75, 1.0]),
        method="Radau",
        rtol=1.0e-8,
        atol=np.array([1.0e-10]),
        max_step=0.2,
        jac_sparsity=None,
        guard_names=("STEEP", "ALWAYS_POSITIVE"),
        guard_metadata={
            name: {
                "unit": "dimensionless",
                "scale": 1.0,
                "tolerance": 1024.0 * np.finfo(float).eps,
            }
            for name in ("STEEP", "ALWAYS_POSITIVE")
        },
        guard_components=lambda time, _state: {
            "STEEP": 1.0e12 * (0.123456789 - time**3),
            "ALWAYS_POSITIVE": 1.0,
        },
        accepted_step_cap=100,
        terminal_time_tolerance=1.0e-12,
    )
    assert trace.event_time == pytest.approx(
        0.123456789 ** (1.0 / 3.0), rel=0.0, abs=2.0e-13
    )
    assert trace.event_guard_names == ("STEEP",)


def test_hf_local_physics_has_controlled_forward_limit(config) -> None:
    cfg = _hf_config(config)
    finite = HighFidelityModel(cfg)
    finite_bending = finite.branches["lower"].ei
    finite_arm = np.linalg.norm(finite.attachment_body)

    cfg.high_fidelity.bending_stiffness_scale = 1.0e-8
    cfg.high_fidelity.bob_attachment_radius_fraction = 1.0e-8
    cfg.high_fidelity.bob_contact_radius_fraction = 1.0e-8
    near_limit = HighFidelityModel(cfg)

    assert np.isclose(
        near_limit.branches["lower"].ei / finite_bending, 1.0e-8, rtol=1.0e-14
    )
    assert np.isclose(
        np.linalg.norm(near_limit.attachment_body) / finite_arm,
        1.0e-8,
        rtol=1.0e-14,
    )
    assert np.isclose(
        near_limit.bob_contact_radius / finite.bob_contact_radius,
        1.0e-8,
        rtol=1.0e-14,
    )


def test_machine_scale_terminal_tail_is_coalesced_without_dropping_endpoint() -> None:
    time = np.array([0.0, 0.001, 0.00199999999999994, 0.002])
    state = np.arange(12.0).reshape(4, 3)
    cleaned_time, cleaned_state, count = _coalesce_terminal_certificate(
        time,
        state,
        terminal_target=0.002,
        tolerance=1.0e-14,
    )
    assert count == 1
    assert np.array_equal(cleaned_time, np.array([0.0, 0.001, 0.002]))
    assert np.array_equal(cleaned_state[-1], state[-1])


def test_hf_local_air_power_splits_relative_dissipation_and_air_work(config) -> None:
    cfg = _hf_config(config)
    cfg.environment.air_velocity = {
        "value": [0.13, -0.07, 0.04],
        "unit": "m/s",
    }
    cfg.bob.drag.enabled = True
    cfg.bob.drag.linear_coefficient = {"value": 0.02, "unit": "N*s/m"}
    cfg.junction.drag_linear = {"value": 0.01, "unit": "N*s/m"}
    for cable in (cfg.cables.upper_A, cfg.cables.upper_B, cfg.cables.lower):
        cable.drag_enabled = True
        cable.drag_cd_normal = 0.7
        cable.drag_cd_tangent = 0.08
        cable.drag_linear_normal_per_length = {
            "value": 0.003,
            "unit": "N*s/m^2",
        }
        cable.drag_linear_tangent_per_length = {
            "value": 0.0004,
            "unit": "N*s/m^2",
        }
    model = HighFidelityModel(cfg)
    positions = model.reference_particle_positions.copy()
    velocities = np.tile(np.array([0.21, -0.16, 0.09]), (model.particle_count, 1))
    bob = model.reference_bob_position.copy()
    bob_velocity = np.array([0.25, -0.12, 0.08])
    quaternion = np.array([1.0, 0.0, 0.0, 0.0])
    omega = np.zeros(3)
    with_air = model.evaluate(
        0.0, positions, velocities, bob, bob_velocity, quaternion, omega
    )
    without_air = model.evaluate(
        0.0,
        positions,
        velocities,
        bob,
        bob_velocity,
        quaternion,
        omega,
        include_aero=False,
    )
    aerodynamic_power = float(
        np.sum((with_air.particle_force - without_air.particle_force) * velocities)
        + np.dot(with_air.bob_force - without_air.bob_force, bob_velocity)
    )
    assert with_air.aero_dissipation_rate > 0.0
    assert np.isclose(
        aerodynamic_power,
        -with_air.aero_dissipation_rate + with_air.air_work_rate,
        rtol=5.0e-13,
        atol=5.0e-13,
    )


def test_geometric_direct_release_rejects_missing_compressed_material_state(config) -> None:
    cfg = _hf_config(config)
    cfg.initial_condition.junction_position = {
        "value": [0.0, 0.0, -0.35],
        "unit": "m",
    }
    cfg.initial_condition.bob_position = {
        "value": [0.0, 0.0, -0.63],
        "unit": "m",
    }
    cfg.initial_condition.type = "geometric_direct_release"
    model = HighFidelityModel(cfg)
    with pytest.raises(ValueError, match="cannot infer a complete compressed rod"):
        prepare_initial_state(cfg, model)


def test_held_endpoint_prepares_stable_material_arcs_and_preserves_release_velocity(
    config,
) -> None:
    cfg = _hf_config(config)
    cfg.initial_condition.junction_position = {
        "value": [0.020, 0.015, -0.350],
        "unit": "m",
    }
    cfg.initial_condition.bob_position = {
        "value": [0.035, -0.010, -0.620],
        "unit": "m",
    }
    cfg.initial_condition.type = "held_endpoint_equilibrium_release"
    cfg.initial_condition.junction_velocity = {
        "value": [-0.010, 0.015, 0.000],
        "unit": "m/s",
    }
    cfg.initial_condition.bob_velocity = {
        "value": [0.020, -0.010, 0.030],
        "unit": "m/s",
    }
    cfg.initial_condition.bob_angular_velocity = {
        "value": [0.30, -0.20, 0.10],
        "unit": "rad/s",
    }
    cfg.solver.static.method = "energy_minimize"
    cfg.solver.static.continuation_steps = 2
    cfg.solver.static.max_iterations = 120
    model = HighFidelityModel(cfg)
    preparation = prepare_initial_state(cfg, model)
    (
        particles,
        bob,
        quaternion,
        particle_velocity,
        bob_velocity,
        angular_velocity,
    ) = model.unpack_state(preparation.state)

    assert preparation.residual_inf_N <= 1.0e-8
    assert preparation.audit["minimum_hessian_eigenvalue_N_per_m"] >= -preparation.audit[
        "hessian_tolerance_N_per_m"
    ]
    assert preparation.audit["stability_class"] == "PSD_STABLE_LOCAL_MINIMUM"
    assert preparation.audit["selected_seed"]
    assert preparation.audit["static_free_material_residual_inf_N"] == pytest.approx(
        preparation.residual_inf_N
    )
    assert (
        preparation.audit["actual_release_free_material_net_force_inf_N"]
        > preparation.residual_inf_N
    )
    assert set(preparation.audit["static_fixture_reaction_force_world_N"]) == {
        "support_A",
        "support_B",
        "junction",
        "bob_com",
    }
    assert np.array_equal(
        particles[model.junction_index], np.array([0.020, 0.015, -0.350])
    )
    assert np.array_equal(bob, np.array([0.035, -0.010, -0.620]))
    assert np.array_equal(quaternion, np.array([1.0, 0.0, 0.0, 0.0]))
    assert np.array_equal(
        particle_velocity[model.junction_index], np.array([-0.010, 0.015, 0.0])
    )
    assert np.array_equal(bob_velocity, np.array([0.020, -0.010, 0.030]))
    assert np.array_equal(angular_velocity, np.array([0.30, -0.20, 0.10]))

    evaluation = model.evaluate(
        0.0,
        particles,
        particle_velocity,
        bob,
        bob_velocity,
        quaternion,
        angular_velocity,
        compute_contact=False,
    )
    lower_points = evaluation.branch_positions["lower"]
    material_arc = float(
        np.sum(np.linalg.norm(lower_points[1:] - lower_points[:-1], axis=1))
    )
    endpoint_chord = float(np.linalg.norm(lower_points[-1] - lower_points[0]))
    assert material_arc > endpoint_chord + 1.0e-5

    lower = model.branches["lower"]
    fractions = np.cumsum(lower.segment_rest_length)[:-1] / np.sum(
        lower.segment_rest_length
    )
    attachment_velocity = bob_velocity + np.cross(
        angular_velocity, model.attachment_body
    )
    expected_lower_velocity = (
        (1.0 - fractions[:, None])
        * particle_velocity[model.junction_index][None, :]
        + fractions[:, None] * attachment_velocity[None, :]
    )
    assert np.allclose(
        particle_velocity[lower.bead_indices],
        expected_lower_velocity,
        rtol=0.0,
        atol=2.0e-16,
    )


def test_held_multistart_detects_and_escapes_force_balanced_saddle(config) -> None:
    cfg = _hf_config(config)
    cfg.initial_condition.junction_position = {
        "value": [0.0, 0.0, -0.25],
        "unit": "m",
    }
    cfg.initial_condition.bob_position = {
        "value": [0.0, 0.0, -0.47],
        "unit": "m",
    }
    cfg.initial_condition.type = "held_endpoint_equilibrium_release"
    cfg.solver.static.method = "energy_minimize"
    cfg.solver.static.continuation_steps = 2
    cfg.solver.static.max_iterations = 120
    preparation = prepare_initial_state(cfg, HighFidelityModel(cfg))
    assert preparation.audit["minimum_hessian_eigenvalue_N_per_m"] >= -preparation.audit[
        "hessian_tolerance_N_per_m"
    ]
    assert any(
        record["escaped_negative_curvature"]
        for record in preparation.audit["candidate_records"]
    )


def test_held_endpoint_closes_with_formal_mesh_and_contact_domain(config) -> None:
    cfg = _hf_config(config)
    cfg.cables.upper_A.elements = 12
    cfg.cables.upper_B.elements = 12
    cfg.cables.lower.elements = 20
    cfg.solver.allow_subminimum_mesh = False
    cfg.high_fidelity.contact_guard_enabled = True
    reference = HighFidelityModel(cfg)
    cfg.initial_condition.junction_position = {
        "value": reference.reference_particle_positions[
            reference.junction_index
        ].tolist(),
        "unit": "m",
    }
    cfg.initial_condition.bob_position = {
        "value": reference.reference_bob_position.tolist(),
        "unit": "m",
    }
    cfg.initial_condition.type = "held_endpoint_equilibrium_release"
    cfg.solver.static.method = "energy_minimize"
    cfg.solver.static.continuation_steps = 2
    cfg.solver.static.max_iterations = 120
    model = HighFidelityModel(cfg)
    preparation = prepare_initial_state(cfg, model)

    guards = model.guard_components(0.0, preparation.state)
    metadata = model.guard_component_metadata()
    assert preparation.residual_inf_N <= 1.0e-8
    assert preparation.audit["stability_class"] == "PSD_STABLE_LOCAL_MINIMUM"
    assert all(
        value > float(metadata[name]["tolerance"])
        for name, value in guards.items()
    )
    assert guards["ROD_SELF_CLEARANCE"] > 0.0
    assert guards["JUNCTION_SOCKET_PROJECTIVE_OPENING"] > 0.0


def test_bob_socket_is_fixed_material_and_rejects_inward_reentry(config) -> None:
    cfg = _hf_config(config)
    cfg.high_fidelity.contact_guard_enabled = True
    cfg.high_fidelity.minimum_clearance = {"value": 0.0002, "unit": "m"}
    cfg.bob.radius = {"value": 0.020, "unit": "m"}
    for cable in (cfg.cables.upper_A, cfg.cables.upper_B, cfg.cables.lower):
        cable.diameter = {"value": 0.003, "unit": "m"}
    model = HighFidelityModel(cfg)
    far = {
        "upper_A": np.column_stack(
            [
                np.linspace(0.08, 0.11, 4),
                np.full(4, 0.08),
                np.zeros(4),
            ]
        ),
        "upper_B": np.column_stack(
            [
                np.linspace(-0.08, -0.11, 4),
                np.full(4, 0.08),
                np.zeros(4),
            ]
        ),
    }
    bob = np.zeros(3)
    inward = {
        **far,
        "lower": np.array(
            [
                [0.050, 0.010, 0.0],
                [0.030, 0.010, 0.0],
                [0.022, 0.003, 0.0],
                [0.018, 0.000, 0.0],
                [0.020, 0.000, 0.0],
            ]
        ),
    }
    _, extent, radial, cut = model._bob_contact_margin(inward, bob)
    assert extent > 0.0
    assert radial < 0.0
    assert np.isfinite(cut)

    outward = {
        **far,
        "lower": np.array(
            [
                [0.100, 0.000, 0.0],
                [0.080, 0.000, 0.0],
                [0.060, 0.000, 0.0],
                [0.040, 0.000, 0.0],
                [0.020, 0.000, 0.0],
            ]
        ),
    }
    bob_margin, extent, radial, cut = model._bob_contact_margin(outward, bob)
    assert min(bob_margin - model.minimum_clearance, extent, radial, cut) > 0.0


def test_registered_socket_longer_than_its_branch_fails_closed(config) -> None:
    cfg = _hf_config(config)
    cfg.high_fidelity.contact_guard_enabled = True
    cfg.bob.radius = {"value": 0.40, "unit": "m"}
    bob_model = HighFidelityModel(cfg)
    positions = {
        name: np.vstack(
            [
                np.linspace(0.8, 1.2, branch.bead_indices.size + 2),
                np.zeros(branch.bead_indices.size + 2),
                np.zeros(branch.bead_indices.size + 2),
            ]
        ).T
        for name, branch in bob_model.branches.items()
    }
    _, material_extent, _, _ = bob_model._bob_contact_margin(
        positions, np.zeros(3)
    )
    assert material_extent < 0.0

    cfg = _hf_config(config.model_copy(deep=True))
    cfg.high_fidelity.contact_guard_enabled = True
    for cable in (cfg.cables.upper_A, cfg.cables.upper_B, cfg.cables.lower):
        cable.diameter = {"value": 0.30, "unit": "m"}
    junction_model = HighFidelityModel(cfg)
    branch_positions = {
        name: np.vstack(
            [
                np.linspace(index, index + 0.2, branch.bead_indices.size + 2),
                np.full(branch.bead_indices.size + 2, float(index)),
                np.zeros(branch.bead_indices.size + 2),
            ]
        ).T
        for index, (name, branch) in enumerate(junction_model.branches.items())
    }
    _, junction_extent, _, _ = junction_model._rod_self_contact_margin(
        branch_positions
    )
    assert junction_extent < 0.0


def _junction_counterexample_positions(model, initial_angle_degrees):
    angle = np.deg2rad(initial_angle_degrees)
    branch_positions = {}
    upper_a = model.branches["upper_A"]
    upper_a_s = np.concatenate(
        [[0.0], np.cumsum(upper_a.segment_rest_length[::-1])]
    )
    upper_a_from_joint = np.column_stack(
        [upper_a_s, np.zeros_like(upper_a_s), np.zeros_like(upper_a_s)]
    )
    branch_positions["upper_A"] = upper_a_from_joint[::-1]

    upper_b = model.branches["upper_B"]
    upper_b_s = np.concatenate(
        [[0.0], np.cumsum(upper_b.segment_rest_length[::-1])]
    )
    upper_b_from_joint = np.column_stack(
        [
            np.zeros_like(upper_b_s),
            -upper_b_s,
            0.2 * upper_b_s,
        ]
    )
    branch_positions["upper_B"] = upper_b_from_joint[::-1]

    lower = model.branches["lower"]
    lower_s = np.concatenate([[0.0], np.cumsum(lower.segment_rest_length)])
    corner_s = 0.010
    endpoint_s = 0.030
    corner = corner_s * np.array([np.cos(angle), np.sin(angle), 0.0])
    endpoint = np.array([0.030, -0.020, 0.0])
    lower_points = np.empty((lower_s.size, 3))
    for index, material in enumerate(lower_s):
        if material <= corner_s:
            lower_points[index] = material * np.array(
                [np.cos(angle), np.sin(angle), 0.0]
            )
        elif material <= endpoint_s:
            fraction = (material - corner_s) / (endpoint_s - corner_s)
            lower_points[index] = (1.0 - fraction) * corner + fraction * endpoint
        else:
            lower_points[index] = endpoint + (material - endpoint_s) * np.array(
                [1.0, -0.2, 0.0]
            )
    branch_positions["lower"] = lower_points
    return branch_positions


def test_fixed_junction_socket_rejects_narrow_opening_and_external_turnback(config) -> None:
    cfg = _hf_config(config)
    cfg.high_fidelity.contact_guard_enabled = True
    cfg.high_fidelity.minimum_clearance = {"value": 0.0002, "unit": "m"}
    for cable in (cfg.cables.upper_A, cfg.cables.upper_B, cfg.cables.lower):
        cable.diameter = {"value": 0.003, "unit": "m"}
        cable.elements = 96
    model = HighFidelityModel(cfg)

    narrow = _junction_counterexample_positions(model, 10.0)
    _, material_extent, monotonicity, cut_clearance = (
        model._rod_self_contact_margin(narrow)
    )
    assert material_extent > 0.0
    assert min(monotonicity, cut_clearance) < 0.0

    turnback = _junction_counterexample_positions(model, 60.0)
    rod_margin, material_extent, projective_opening, cut_clearance = (
        model._rod_self_contact_margin(turnback)
    )
    assert material_extent > 0.0
    assert projective_opening > 0.0
    assert cut_clearance > 0.0
    assert rod_margin - model.minimum_clearance < 0.0

    reentry = _junction_counterexample_positions(model, 60.0)
    lower = model.branches["lower"]
    upper_a = model.branches["upper_A"]
    socket_length = model._junction_socket_length(lower, upper_a)
    lower_s = np.concatenate([[0.0], np.cumsum(lower.segment_rest_length)])
    first_outside = int(np.searchsorted(lower_s, socket_length, side="right"))
    ray = np.array([0.5, np.sqrt(3.0) / 2.0, 0.0])
    lower_points = lower_s[:, None] * ray[None, :]
    target = np.array([0.5 * socket_length, 0.0, 0.0])
    target_index = first_outside + 1
    lower_points[target_index] = target
    for index in range(target_index + 1, lower_s.size):
        lower_points[index] = target + (
            lower_s[index] - lower_s[target_index]
        ) * np.array([-0.2, -1.0, 0.0])
    reentry["lower"] = lower_points
    rod_margin, material_extent, projective_opening, cut_clearance = (
        model._rod_self_contact_margin(reentry)
    )
    assert material_extent > 0.0
    assert projective_opening > 0.0
    assert cut_clearance > 0.0
    assert rod_margin - model.minimum_clearance < 0.0


def test_fixed_junction_socket_rejects_finite_collinear_overlap(config) -> None:
    cfg = _hf_config(config)
    cfg.high_fidelity.contact_guard_enabled = True
    cfg.high_fidelity.minimum_clearance = {"value": 0.0002, "unit": "m"}
    for cable in (cfg.cables.upper_A, cfg.cables.upper_B, cfg.cables.lower):
        cable.diameter = {"value": 0.003, "unit": "m"}
        cable.elements = 96
    model = HighFidelityModel(cfg)

    upper_a = model.branches["upper_A"]
    upper_a_s = np.concatenate(
        [[0.0], np.cumsum(upper_a.segment_rest_length[::-1])]
    )
    upper_a_from_joint = np.column_stack(
        [upper_a_s, np.zeros_like(upper_a_s), np.zeros_like(upper_a_s)]
    )

    upper_b = model.branches["upper_B"]
    upper_b_s = np.concatenate(
        [[0.0], np.cumsum(upper_b.segment_rest_length[::-1])]
    )
    upper_b_from_joint = np.column_stack(
        [np.zeros_like(upper_b_s), -upper_b_s, 0.2 * upper_b_s]
    )

    lower = model.branches["lower"]
    lower_s = np.concatenate([[0.0], np.cumsum(lower.segment_rest_length)])
    # The first complete lower material cell follows upper_A exactly.  It then
    # opens rapidly, so a guard based only on the fixed socket cut point would
    # miss the finite coincident interval inside the registered connector.
    overlap_length = float(lower_s[1])
    lower_points = np.column_stack(
        [
            lower_s,
            20.0 * np.maximum(lower_s - overlap_length, 0.0),
            np.zeros_like(lower_s),
        ]
    )
    positions = {
        "upper_A": upper_a_from_joint[::-1],
        "upper_B": upper_b_from_joint[::-1],
        "lower": lower_points,
    }

    _, material_extent, monotonicity, _ = model._rod_self_contact_margin(
        positions
    )
    assert material_extent > 0.0
    assert monotonicity <= 0.0

    # A comparison at equal material distance alone is insufficient: unequal
    # material coordinates can occupy the same point while both equal-s
    # traces appear to open.  Projective (s,t) minimisation must reject this
    # speed-mismatched collinear ray as well.
    unequal_material_lower = np.column_stack(
        [2.0 * lower_s, np.zeros_like(lower_s), np.zeros_like(lower_s)]
    )
    unequal_positions = {**positions, "lower": unequal_material_lower}
    _, material_extent, projective_opening, _ = (
        model._rod_self_contact_margin(unequal_positions)
    )
    assert material_extent > 0.0
    assert projective_opening < 0.0
    translated = {
        name: points + np.array([1.0e8, -2.0e8, 3.0e8])
        for name, points in unequal_positions.items()
    }
    _, _, translated_opening, _ = model._rod_self_contact_margin(translated)
    assert translated_opening == pytest.approx(
        projective_opening, rel=0.0, abs=2.0e-15
    )


def test_length_turn_and_aerodynamic_chord_guards_have_closed_domains(config) -> None:
    cfg = _hf_config(config)
    cfg.cables.upper_A.drag_enabled = True
    model = HighFidelityModel(cfg)
    particles = model.reference_particle_positions.copy()
    branch = model.branches["upper_A"]
    support, _, _ = model.support_motion["support_A"].state(0.0)
    segment_length = 1.01 * model.length_guard
    turn = 1.01 * model.bending_turn_clearance_floor
    cosine = -1.0 + turn
    sine = np.sqrt(1.0 - cosine**2)
    first = support + segment_length * np.array([1.0, 0.0, 0.0])
    second = first + segment_length * np.array([cosine, sine, 0.0])
    junction = second + segment_length * np.array([0.0, 1.0, 0.0])
    particles[branch.bead_indices] = np.vstack([first, second])
    particles[model.junction_index] = junction
    state = model.pack_state(
        particles,
        model.reference_bob_position,
        np.array([1.0, 0.0, 0.0, 0.0]),
        np.zeros_like(particles),
        np.zeros(3),
        np.zeros(3),
    )
    components = model.guard_components(0.0, state)
    assert components["MINIMUM_SEGMENT_LENGTH"] > 0.0
    assert components["BENDING_TURN_CLEARANCE"] > 0.0
    assert components["AERODYNAMIC_CHORD_LENGTH"] < 0.0
    metadata = model.guard_component_metadata()
    assert metadata["MINIMUM_SEGMENT_LENGTH"]["unit"] == "m"
    assert metadata["BENDING_TURN_CLEARANCE"]["unit"] == "dimensionless"
    assert model.guard_value(0.0, state) < 0.0

    with pytest.raises(FloatingPointError, match="degenerate aerodynamic bead chord"):
        model.evaluate(
            0.0,
            particles,
            np.zeros_like(particles),
            model.reference_bob_position,
            np.zeros(3),
            np.array([1.0, 0.0, 0.0, 0.0]),
            np.zeros(3),
            include_aero=True,
            compute_contact=False,
        )

    # A segment between the hard singularity floor and the public length guard
    # remains evaluable, so an event root can be located before hard failure.
    particles[branch.bead_indices[0]] = support + 2.0 * model.geometry_singularity_floor * np.array(
        [1.0, 0.0, 0.0]
    )
    state = model.pack_state(
        particles,
        model.reference_bob_position,
        np.array([1.0, 0.0, 0.0, 0.0]),
        np.zeros_like(particles),
        np.zeros(3),
        np.zeros(3),
    )
    assert model.guard_components(0.0, state)["MINIMUM_SEGMENT_LENGTH"] < 0.0


def test_quaternion_rotation_and_world_angular_velocity_kinematics(config) -> None:
    half = np.sqrt(0.5)
    quarter_turn_z = np.array([half, 0.0, 0.0, half])
    assert np.allclose(
        rotate_body_vector(quarter_turn_z, np.array([1.0, 0.0, 0.0])),
        np.array([0.0, 1.0, 0.0]),
        atol=3.0e-16,
    )

    cfg = _hf_config(config)
    model = HighFidelityModel(cfg)
    quarter_turn_x = np.array([half, half, 0.0, 0.0])
    omega_world = np.array([0.0, 0.7, -0.2])
    state = model.pack_state(
        model.reference_particle_positions,
        model.reference_bob_position,
        quarter_turn_x,
        np.zeros_like(model.reference_particle_positions),
        np.zeros(3),
        omega_world,
    )
    _, _, quaternion_rate, _, _, _ = model.unpack_state(model.rhs(0.0, state))
    expected = 0.5 * quaternion_multiply(
        np.concatenate([[0.0], omega_world]), quarter_turn_x
    )
    assert np.allclose(quaternion_rate, expected, rtol=0.0, atol=3.0e-16)


def test_energy_balance_normalization_scale_is_coordinate_origin_invariant(config) -> None:
    cfg = _hf_config(config)
    original = HighFidelityModel(cfg)
    translated_cfg = cfg.model_copy(deep=True)
    shift = np.array([12.0, -7.0, 4.0])
    for support_name in ("A", "B"):
        support = getattr(translated_cfg.supports, support_name)
        support.position = {
            "value": (np.asarray(support.position["value"]) + shift).tolist(),
            "unit": "m",
        }
    translated_cfg.initial_condition.bob_position = {
        "value": (
            np.asarray(translated_cfg.initial_condition.bob_position["value"])
            + shift
        ).tolist(),
        "unit": "m",
    }
    translated = HighFidelityModel(translated_cfg)
    assert translated.force_scale == pytest.approx(original.force_scale, rel=0.0)
    assert translated.characteristic_length == pytest.approx(
        original.characteristic_length, rel=2.0e-15
    )
    assert (
        translated.force_scale * translated.characteristic_length
        == pytest.approx(
            original.force_scale * original.characteristic_length,
            rel=2.0e-15,
        )
    )


def test_colored_finite_difference_pattern_covers_every_observed_rhs_dependency(
    config,
) -> None:
    cfg = _hf_config(config)
    cfg.initial_condition.junction_position = {
        "value": [0.012, -0.006, -0.45],
        "unit": "m",
    }
    cfg.initial_condition.bob_position = {
        "value": [0.031, 0.017, -0.82],
        "unit": "m",
    }
    cfg.initial_condition.junction_velocity = {
        "value": [0.013, -0.021, 0.008],
        "unit": "m/s",
    }
    cfg.initial_condition.bob_velocity = {
        "value": [-0.017, 0.011, -0.004],
        "unit": "m/s",
    }
    cfg.initial_condition.bob_angular_velocity = {
        "value": [0.3, -0.2, 0.1],
        "unit": "rad/s",
    }
    cfg.initial_condition.type = "geometric_direct_release"
    model = HighFidelityModel(cfg)
    state = prepare_initial_state(cfg, model).state
    pattern = model.jacobian_sparsity().toarray().astype(bool)

    # A conservative colored-FD pattern may contain extra entries, but it may
    # never omit a derivative that is numerically observable away from a guard.
    for column in range(model.state_size):
        step = 2.0e-7 * max(1.0, abs(float(state[column])))
        plus = state.copy()
        minus = state.copy()
        plus[column] += step
        minus[column] -= step
        derivative = (model.rhs(0.0013, plus) - model.rhs(0.0013, minus)) / (
            2.0 * step
        )
        observed = np.flatnonzero(np.abs(derivative) > 2.0e-8)
        assert np.all(pattern[observed, column]), (
            column,
            observed[~pattern[observed, column]],
        )

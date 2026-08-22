from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path

import numpy as np
import pytest

from ypendulum.ui.desktop_config import (
    DesktopYPendulumAdapter,
    InitialReleaseParameters,
    apply_initial_release_to_forward,
    apply_initial_release_to_hf,
    default_desktop_configuration,
    estimate_reference_periods,
    initial_release_from_forward,
    initial_release_from_hf,
    make_desktop_request,
    numeric_sweep_values,
    parameter_fields,
    parse_parameter_text,
    shared_input_audit,
    validate_desktop_request,
    write_desktop_request,
)


def _independent_leaf_paths(value: object, prefix: str = "") -> set[str]:
    if not isinstance(value, dict):
        return {prefix}
    paths: set[str] = set()
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        paths.update(_independent_leaf_paths(child, path))
    return paths


def test_default_profiles_cover_every_leaf_and_validate_all_backends(tmp_path: Path) -> None:
    forward, high_fidelity = default_desktop_configuration()
    assert {item.path for item in parameter_fields(forward, "forward")} == _independent_leaf_paths(
        forward
    )
    assert {
        item.path for item in parameter_fields(high_fidelity, "high_fidelity")
    } == _independent_leaf_paths(high_fidelity)

    for backend in ("forward", "high_fidelity", "both"):
        request = make_desktop_request(
            label=f"default_{backend}",
            backend=backend,
            forward_config=forward,
            high_fidelity_config=high_fidelity,
        )
        identity = validate_desktop_request(request)
        assert identity["backend"] == backend
        assert len(identity["request_sha256"]) == 64
        path = write_desktop_request(tmp_path / f"{backend}.json", request)
        command = DesktopYPendulumAdapter().build_command(
            path,
            backend=backend,
            output_directory=tmp_path / f"output-{backend}",
        )
        joined = " ".join(command).lower()
        assert "desktop_worker" in joined
        assert "streamlit" not in joined
        assert "http://" not in joined
        assert "https://" not in joined


def test_default_shared_input_audit_passes() -> None:
    forward, high_fidelity = default_desktop_configuration()
    audit = shared_input_audit(forward, high_fidelity)
    assert audit["passed"] is True
    assert audit["check_count"] >= 30


def test_default_length_angle_release_round_trip_preserves_cartesian_state() -> None:
    forward, high_fidelity = default_desktop_configuration()
    parameters = initial_release_from_forward(forward)

    assert parameters.upper_a_length_m == pytest.approx(0.291547594742265)
    assert parameters.upper_b_length_m == pytest.approx(0.291547594742265)
    assert parameters.junction_roll_deg == pytest.approx(0.0)
    assert parameters.lower_branch_length_m == pytest.approx(0.3523137805990563)
    assert parameters.lower_polar_deg == pytest.approx(6.570098351254273)
    assert parameters.lower_azimuth_deg == pytest.approx(-29.74488129694222)

    converted_forward = apply_initial_release_to_forward(forward, parameters)
    converted_hf = apply_initial_release_to_hf(high_fidelity, parameters)
    for path in ("r_J", "r_m", "v_J", "v_m"):
        np.testing.assert_allclose(
            converted_forward["initial_state"][path],
            forward["initial_state"][path],
            rtol=0.0,
            atol=2.0e-15,
        )
    for path in (
        "junction_position",
        "bob_position",
        "junction_velocity",
        "bob_velocity",
        "bob_angular_velocity",
    ):
        np.testing.assert_allclose(
            converted_hf["initial_condition"][path],
            high_fidelity["initial_condition"][path],
            rtol=0.0,
            atol=2.0e-15,
        )


def test_nonzero_length_angle_rates_and_hf_spin_round_trip() -> None:
    forward, high_fidelity = default_desktop_configuration()
    requested = InitialReleaseParameters(
        upper_a_length_m=0.30,
        upper_b_length_m=0.31,
        junction_roll_deg=23.0,
        lower_branch_length_m=0.34,
        lower_polar_deg=12.0,
        lower_azimuth_deg=-37.0,
        upper_a_length_rate_m_s=0.002,
        upper_b_length_rate_m_s=-0.001,
        junction_roll_rate_deg_s=4.0,
        lower_length_rate_m_s=0.003,
        lower_polar_rate_deg_s=-2.0,
        lower_azimuth_rate_deg_s=5.0,
        bob_spin_support_deg_s=6.0,
        bob_spin_radial_deg_s=-7.0,
        bob_spin_tangent_deg_s=8.0,
    )
    converted_forward = apply_initial_release_to_forward(forward, requested)
    converted_hf = apply_initial_release_to_hf(high_fidelity, requested)
    recovered_forward = initial_release_from_forward(converted_forward)
    recovered_hf = initial_release_from_hf(converted_hf)

    for field in fields(requested):
        if not field.name.startswith("bob_spin_"):
            assert getattr(recovered_forward, field.name) == pytest.approx(
                getattr(requested, field.name), abs=2.0e-12
            )
        assert getattr(recovered_hf, field.name) == pytest.approx(
            getattr(requested, field.name), abs=2.0e-12
        )
    np.testing.assert_allclose(
        converted_forward["initial_state"]["r_J"],
        converted_hf["initial_condition"]["junction_position"],
        rtol=0.0,
        atol=2.0e-15,
    )
    np.testing.assert_allclose(
        converted_forward["initial_state"]["r_m"],
        converted_hf["initial_condition"]["bob_position"],
        rtol=0.0,
        atol=2.0e-15,
    )
    np.testing.assert_allclose(
        converted_forward["initial_state"]["v_m"],
        converted_hf["initial_condition"]["bob_velocity"],
        rtol=0.0,
        atol=2.0e-15,
    )

    initial = converted_forward["initial_state"]
    for branch, start, end in (
        ("A", [0.0, 0.0, 0.0], initial["v_J"]),
        ("B", [0.0, 0.0, 0.0], initial["v_J"]),
        ("lower", initial["v_J"], initial["v_m"]),
    ):
        coefficients = np.asarray(
            initial["branches"][branch]["velocity"]["coefficients"], dtype=float
        )
        np.testing.assert_allclose(coefficients[0], start, rtol=0.0, atol=2.0e-15)
        np.testing.assert_allclose(
            coefficients[0] + coefficients[1], end, rtol=0.0, atol=2.0e-15
        )

    request = make_desktop_request(
        label="angle_rate_round_trip",
        backend="both",
        forward_config=converted_forward,
        high_fidelity_config=converted_hf,
    )
    assert validate_desktop_request(request)["backend"] == "both"


def test_length_angle_release_rejects_degenerate_geometry() -> None:
    forward, _high_fidelity = default_desktop_configuration()
    parameters = initial_release_from_forward(forward)

    with pytest.raises(ValueError, match="非退化 Y 形三角形"):
        apply_initial_release_to_forward(
            forward,
            replace(parameters, upper_a_length_m=0.10, upper_b_length_m=0.10),
        )
    polar_limit = apply_initial_release_to_forward(
        forward,
        replace(parameters, lower_polar_deg=180.0),
    )
    assert np.linalg.norm(
        np.asarray(polar_limit["initial_state"]["r_m"])
        - np.asarray(polar_limit["initial_state"]["r_J"])
    ) == pytest.approx(parameters.lower_branch_length_m)
    with pytest.raises(ValueError, match="0° ≤ 偏角 ≤ 180°"):
        apply_initial_release_to_forward(
            forward,
            replace(parameters, lower_polar_deg=180.0001),
        )


def test_default_disables_uncalibrated_material_box_but_keeps_lambda_guard() -> None:
    forward, _high_fidelity = default_desktop_configuration()

    assert float(forward["physical"]["lambda_min"]) > 0.0
    for branch in forward["physical"]["branches"].values():
        domain = branch["material_domain"]
        assert domain["kind"] == "open_box"
        assert domain["lambda_lower"] is None
        assert domain["lambda_upper"] is None
        assert domain["rate_lower"] is None
        assert domain["rate_upper"] is None


def test_long_lower_branch_release_above_old_example_bound_validates() -> None:
    forward, high_fidelity = default_desktop_configuration()
    parameters = replace(
        initial_release_from_forward(forward),
        upper_a_length_m=0.3,
        upper_b_length_m=0.3,
        junction_roll_deg=0.0,
        lower_branch_length_m=0.5,
        lower_polar_deg=30.0,
        lower_azimuth_deg=20.0,
    )
    converted_forward = apply_initial_release_to_forward(forward, parameters)
    converted_hf = apply_initial_release_to_hf(high_fidelity, parameters)
    stretch = (
        np.linalg.norm(
            np.asarray(converted_forward["initial_state"]["r_m"])
            - np.asarray(converted_forward["initial_state"]["r_J"])
        )
        / float(converted_forward["physical"]["branches"]["lower"]["L0"])
    )

    assert stretch > 1.5
    request = make_desktop_request(
        label="lower_branch_length_above_old_example_bound",
        backend="both",
        forward_config=converted_forward,
        high_fidelity_config=converted_hf,
    )
    assert validate_desktop_request(request)["backend"] == "both"


def test_default_profiles_cover_multiple_reference_periods_with_explicit_preview_mesh() -> None:
    forward, high_fidelity = default_desktop_configuration()
    periods = estimate_reference_periods(forward)

    assert periods["fast_cycles"] >= 5.0
    assert periods["slow_cycles"] >= 5.0
    assert forward["physical"]["T"] == high_fidelity["solver"]["t_end"]
    assert forward["numerics"]["output_dt"] <= periods["fast_period_s"] / 100.0
    assert high_fidelity["solver"]["output_dt"] <= periods["fast_period_s"] / 100.0
    assert forward["numerics"]["elements"] == {"A": 2, "B": 2, "lower": 3}
    assert high_fidelity["solver"]["allow_subminimum_mesh"] is True
    assert high_fidelity["run"]["claim_level"] == "DERIVED"
    assert {
        name: high_fidelity["cables"][name]["elements"]
        for name in ("upper_A", "upper_B", "lower")
    } == {"upper_A": 1, "upper_B": 1, "lower": 1}


def test_typed_parameter_parser_handles_vectors_matrices_and_text_lists() -> None:
    forward, _high_fidelity = default_desktop_configuration()
    fields = {item.path: item for item in parameter_fields(forward, "forward")}
    assert parse_parameter_text(fields["initial_state.r_J"], "0.1, -0.2, 0.3") == [
        0.1,
        -0.2,
        0.3,
    ]
    assert parse_parameter_text(
        fields["initial_state.branches.A.position.coefficients"],
        "0, 0, 0; 1, 2, 3",
    ) == [[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]]
    assert parse_parameter_text(
        fields["validation.expected_contract_status"], "COMPLETED"
    ) == ["COMPLETED"]


def test_sweep_values_are_explicit_and_deterministic() -> None:
    assert numeric_sweep_values(0.0, 1.0, 5) == (0.0, 0.25, 0.5, 0.75, 1.0)

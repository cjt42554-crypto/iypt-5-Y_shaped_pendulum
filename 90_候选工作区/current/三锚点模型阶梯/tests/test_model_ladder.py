from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model_ladder as ladder


def test_anchor_geometry_preserves_atlas_upper_slope_and_taut_initial_state() -> None:
    for anchor in ladder.ANCHORS:
        setup = ladder.anchor_setup(anchor)
        assert setup["half_support_span_m"] / setup["h_m"] == pytest_approx(
            ladder.UPPER_SLOPE
        )
        assert setup["upper_loaded_length_m"] > setup["upper_rest_length_m"]
        assert setup["lower_loaded_length_m"] > setup["lower_rest_length_m"]
        assert min(setup["ideal_initial_tension_N"].values()) > 0.0


def test_three_model_configs_keep_identities_and_shared_endpoint_audit() -> None:
    anchor = ladder.ANCHORS[1]
    setup = ladder.anchor_setup(anchor)
    torus, cable, hf, audit = ladder.build_configs(
        anchor,
        setup,
        horizon_s=0.05,
        output_dt_s=0.0005,
    )
    assert torus["model_id"] == "FWD-TORUS-1.0"
    assert cable["model_id"] == "FWD-CABLE-1.0"
    assert hf["high_fidelity"]["model_id"] == (
        "HF-DISCRETE-ROD-RIGID-BOB-1.0"
    )
    assert cable["initial_state"]["mode"] == "STATIC_HOLD_RELEASE"
    assert hf["initial_condition"]["type"] == (
        "held_endpoint_equilibrium_release"
    )
    assert audit["passed"] is True


def test_frequency_fit_and_closure_are_accurate_for_synthetic_two_mode_series() -> None:
    anchor = ladder.Anchor(3, 2, 0.15, 0.10)
    setup = ladder.anchor_setup(anchor)
    fast_hz = 0.90
    slow_hz = 0.60
    time = np.linspace(0.0, 12.0, 6001)
    position = np.zeros((time.size, 3))
    velocity = np.zeros_like(position)
    position[:, 0] = 0.04 * np.cos(2.0 * math.pi * fast_hz * time)
    velocity[:, 0] = -0.04 * 2.0 * math.pi * fast_hz * np.sin(
        2.0 * math.pi * fast_hz * time
    )
    position[:, 1] = 0.05 * np.cos(2.0 * math.pi * slow_hz * time)
    velocity[:, 1] = -0.05 * 2.0 * math.pi * slow_hz * np.sin(
        2.0 * math.pi * slow_hz * time
    )
    metrics = ladder.modal_metrics(
        ladder.Series(time, position, velocity),
        anchor,
        setup,
        closure_cycles=6,
    )
    assert metrics["frequency_ratio"] == pytest_approx(1.5, abs=2.0e-6)
    assert metrics["resonant_phase_drift_rad"] == pytest_approx(0.0, abs=1.0e-4)
    assert metrics["normalized_four_state_closure_error"] == pytest_approx(
        0.0, abs=2.0e-4
    )


def test_series_comparison_uses_reference_grid() -> None:
    first_time = np.linspace(0.0, 1.0, 101)
    second_time = np.linspace(0.0, 1.0, 41)
    first_position = np.column_stack((first_time, 2.0 * first_time, 0.0 * first_time))
    second_position = first_position[::5].copy()
    second_time = first_time[::5]
    first = ladder.Series(first_time, first_position, np.ones_like(first_position))
    second = ladder.Series(second_time, second_position, np.ones_like(second_position))
    metrics = ladder.compare_series(first, second)
    assert metrics["status"] == "DIFFERENCE_COMPUTED"
    assert metrics["maximum_point_bob_position_m"] == pytest_approx(0.0, abs=1.0e-14)


def pytest_approx(value: float, **kwargs):
    import pytest

    return pytest.approx(value, **kwargs)

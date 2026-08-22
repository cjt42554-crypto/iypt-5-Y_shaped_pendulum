from __future__ import annotations

import numpy as np
import pytest

from ypendulum.calibration import (
    build_tabulated_tension_extension,
    compare_envelope_models,
    fit_axial_stiffness,
)


def test_axial_calibration_recovers_ea_and_uncertainty() -> None:
    force = np.linspace(0.0, 12.0, 25)
    rest = 0.8
    ea = 2400.0
    rng = np.random.default_rng(7)
    extension = force * rest / ea + 2e-5 + rng.normal(scale=2e-7, size=force.size)
    fit = fit_axial_stiffness(force, extension, rest)
    assert abs(fit.ea / ea - 1.0) < 2e-3
    assert fit.ea_confidence_interval_95[0] < ea < fit.ea_confidence_interval_95[1]
    assert fit.r_squared > 0.99999


def test_tabulated_curve_is_monotone_and_mesh_calibration_length_is_saved() -> None:
    curve = build_tabulated_tension_extension(
        np.array([0.0, 1.0, 2.0, 3.0]),
        np.array([0.0, 0.001, 0.002, 0.003]),
        0.5,
    )
    assert curve["calibration_length_m"] == 0.5
    assert np.all(np.diff(curve["tension_n"]) >= 0.0)
    with pytest.raises(ValueError):
        build_tabulated_tension_extension(
            np.array([0.0, 2.0, 1.0]), np.array([0.0, 0.001, 0.002]), 0.5
        )


def test_damping_model_comparison_selects_exponential_signature() -> None:
    time = np.linspace(0.0, 10.0, 101)
    amplitude = 0.12 * np.exp(-0.08 * time)
    report = compare_envelope_models(time, amplitude)
    assert report["preferred_by_transformed_aic"] == "exponential"
    assert abs(report["fits"]["exponential"]["coefficient"] - 0.08) < 1e-10

from hashlib import sha256

import numpy as np
import pytest

from yps_experiment_pipeline.contracts import validate_document
from yps_experiment_pipeline.observables import (
    common_observables,
    estimate_damped_mode,
    normalized_closure_error,
    resonant_phase,
)


def test_damped_two_mode_parameters_are_recovered():
    time = np.linspace(0.0, 20.0, 4001)
    fast_truth = {"amplitude": 0.14, "gamma": 0.026, "omega": 4.2, "phase": 0.3}
    slow_truth = {"amplitude": 0.09, "gamma": 0.014, "omega": 2.8, "phase": -0.4}
    fast_signal = (
        fast_truth["amplitude"]
        * np.exp(-fast_truth["gamma"] * time)
        * np.cos(fast_truth["omega"] * time + fast_truth["phase"])
    )
    slow_signal = (
        slow_truth["amplitude"]
        * np.exp(-slow_truth["gamma"] * time)
        * np.cos(slow_truth["omega"] * time + slow_truth["phase"])
    )
    fast = estimate_damped_mode(time, fast_signal)
    slow = estimate_damped_mode(time, slow_signal)
    assert fast.omega_rad_s == pytest.approx(fast_truth["omega"], abs=2e-5)
    assert slow.omega_rad_s == pytest.approx(slow_truth["omega"], abs=2e-5)
    assert fast.damping_per_s == pytest.approx(fast_truth["gamma"], abs=2e-5)
    assert slow.damping_per_s == pytest.approx(slow_truth["gamma"], abs=2e-5)
    phase = resonant_phase(
        fast.omega_rad_s * time + fast.phase_rad,
        slow.omega_rad_s * time + slow.phase_rad,
        p=3,
        q=2,
    )
    closure = normalized_closure_error(np.array([0.0, 1.0]), np.array([0.1, 1.0]), 1.0)
    common = common_observables(
        data_origin="SYNTHETIC",
        identity={
            "source_id": "SYNTHETIC_TWO_MODE",
            "source_sha256": sha256(b"SYNTHETIC_TWO_MODE").hexdigest(),
        },
        valid_interval_s=(time[0], time[-1]),
        fast=fast,
        slow=slow,
        phase=phase[::200],
        closure_error=closure,
        events=[],
        uncertainty={
            "method": "SYNTHETIC_KNOWN_TRUTH",
            "components": {"frequency_rad_s": 0.0},
            "covariance_ref": None,
        },
        domain_status="IN_DOMAIN",
    )
    validate_document("processed_observables.schema.json", common)
    assert common["frequency"]["ratio"] == pytest.approx(1.5, abs=1e-5)

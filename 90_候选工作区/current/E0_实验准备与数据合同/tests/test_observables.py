from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest

from yps_experiment_pipeline.contracts import validate_document
from yps_experiment_pipeline.observables import (
    estimate_damped_mode,
    normalized_closure_error,
    resonant_phase,
    write_common_observables,
)


def test_damped_two_mode_parameters_are_recovered(tmp_path: Path):
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
    trajectory_manifest_file = tmp_path / "trajectory_bundle.json"
    trajectory_manifest_file.write_text("{}\n", encoding="utf-8")
    arrays = {
        "time_s": time,
        "r_bob_W_m": np.column_stack((fast_signal, slow_signal, np.zeros_like(time))),
        "r_junction_W_m": np.column_stack(
            (0.5 * fast_signal, 0.5 * slow_signal, np.zeros_like(time))
        ),
        "modal_basis_W": np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
        "q_fast_m": fast_signal,
        "q_slow_m": slow_signal,
        "resonant_phase_rad": phase,
        "valid_mask": np.ones(time.size, dtype=bool),
    }
    common = write_common_observables(
        tmp_path / "common",
        data_origin="SYNTHETIC_REAL_SHAPE_FIXTURE",
        identity={
            "source_id": "SYNTHETIC_TWO_MODE",
            "source_sha256": sha256(b"SYNTHETIC_TWO_MODE").hexdigest(),
            "run_id": "SYNTHETIC_TWO_MODE",
            "apparatus_revision": "SYNTHETIC_TWO_MODE_RIG",
        },
        trajectory_manifest_file=trajectory_manifest_file,
        arrays=arrays,
        units={
            "time_s": "s",
            "r_bob_W_m": "m",
            "r_junction_W_m": "m",
            "modal_basis_W": "1",
            "q_fast_m": "m",
            "q_slow_m": "m",
            "resonant_phase_rad": "rad",
            "valid_mask": "1",
        },
        modal_basis_provenance={
            "method": "SYNTHETIC_KNOWN_BASIS",
            "method_sha256": sha256(b"SYNTHETIC_KNOWN_BASIS").hexdigest(),
            "source_run_ids": ["SYNTHETIC_FAST", "SYNTHETIC_SLOW"],
            "source_bundle_sha256": [
                sha256(b"SYNTHETIC_FAST").hexdigest(),
                sha256(b"SYNTHETIC_SLOW").hexdigest(),
            ],
            "basis_frozen_before_run": True,
        },
        fast=fast,
        slow=slow,
        closure_error=closure,
        events=[],
        uncertainty={
            "method": "SYNTHETIC_KNOWN_TRUTH",
            "components": {"frequency_rad_s": 0.0},
            "covariance_ref": None,
            "covariance_sha256": None,
        },
        domain_status="IN_DOMAIN",
    )
    validate_document("processed_observables.schema.json", common)
    assert common["frequency"]["ratio"] == pytest.approx(1.5, abs=1e-5)

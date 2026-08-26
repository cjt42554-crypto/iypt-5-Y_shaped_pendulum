from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = (
    ROOT / "compression_limit" / "alpha_specific_preparation_worker.py"
)


def _load_worker():
    spec = importlib.util.spec_from_file_location(
        "alpha_specific_preparation_worker_test", WORKER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hessian_crosscheck_spec_is_prefrozen_and_fail_closed() -> None:
    spec = json.loads(
        (
            ROOT
            / "compression_limit"
            / "hessian_crosscheck_spec.json"
        ).read_text(encoding="utf-8")
    )
    assert spec["finite_difference_step_multipliers"] == [0.5, 1.0, 2.0]
    assert spec["required_for_scales_at_or_below"] == pytest.approx(1.0e-4)
    assert spec["cross_alpha_warm_start"] is False
    assert spec["formal_change_authorized"] is False
    assert spec["condition_number"]["role"] == (
        "reported diagnostic across alpha; no new arbitrary acceptance threshold is introduced"
    )


def test_dense_gradient_hessian_and_energy_probe_recover_quadratic_curvature() -> None:
    worker = _load_worker()
    matrix = np.diag([2.0, 5.0, 11.0])
    candidate = np.array([0.3, -0.2, 0.1])

    def gradient(value: np.ndarray) -> np.ndarray:
        return matrix @ value

    def energy(value: np.ndarray) -> float:
        return 0.5 * float(value @ matrix @ value)

    eigenvalues, eigenvectors, _ = worker._dense_hessian_spectrum(
        gradient, candidate, 1.0e-5, 1
    )
    assert eigenvalues == pytest.approx([2.0, 5.0, 11.0], abs=1.0e-10)
    direction = eigenvectors[:, 0]
    curvature = worker._energy_directional_curvature(
        energy, candidate, direction, 1.0e-4
    )
    assert curvature == pytest.approx(2.0, rel=1.0e-8)


def test_tolerance_class_and_raw_sign_are_separate_decisions() -> None:
    worker = _load_worker()
    tolerance = 1.0e-3
    assert worker._classification(-2.0e-3, tolerance) == (
        "NEGATIVE_BEYOND_TOLERANCE"
    )
    assert worker._classification(-2.0e-4, tolerance) == (
        "MARGINAL_WITHIN_TOLERANCE"
    )
    assert worker._classification(2.0e-3, tolerance) == "POSITIVE_RESOLVED"
    assert worker._raw_sign(-2.0e-4) == "NEGATIVE"
    assert worker._raw_sign(0.0) == "ZERO"
    assert worker._raw_sign(2.0e-4) == "POSITIVE"

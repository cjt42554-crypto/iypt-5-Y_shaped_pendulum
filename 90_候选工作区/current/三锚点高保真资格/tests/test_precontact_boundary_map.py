from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "compression_limit" / "run_precontact_boundary_map.py"
SPEC_PATH = ROOT / "compression_limit" / "precontact_boundary_spec.json"


def _load_runner():
    spec = importlib.util.spec_from_file_location("precontact_boundary_tested", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def test_frozen_spec_is_valid_and_forbids_dynamics() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    runner.validate_map_spec(spec)
    assert spec["sampling"]["cross_alpha_warm_start"] is False
    assert spec["sampling"]["maximum_unique_alpha_evaluations"] == 10
    assert spec["dynamic_run_count"] == 0
    assert spec["formal_change_authorized"] is False


def test_geometric_midpoint_and_bracket_update() -> None:
    midpoint = runner.geometric_midpoint(1.0e-2, 1.0)
    assert midpoint == pytest.approx(1.0e-1)
    assert runner.update_bracket(1.0e-2, 1.0, midpoint, False) == (
        midpoint,
        1.0,
    )
    assert runner.update_bracket(1.0e-2, 1.0, midpoint, True) == (
        1.0e-2,
        midpoint,
    )


def test_monotone_predicate_is_fail_closed() -> None:
    monotone = [
        {"alpha": 0.01, "primary_pass": False},
        {"alpha": 0.1, "primary_pass": False},
        {"alpha": 1.0, "primary_pass": True},
    ]
    nonmonotone = [
        {"alpha": 0.01, "primary_pass": False},
        {"alpha": 0.1, "primary_pass": True},
        {"alpha": 1.0, "primary_pass": False},
    ]
    unresolved = [
        {"alpha": 0.01, "primary_pass": False},
        {"alpha": 1.0, "primary_pass": None},
    ]
    assert runner.monotone_false_to_true(monotone)
    assert not runner.monotone_false_to_true(nonmonotone)
    assert not runner.monotone_false_to_true(unresolved)


def test_raw_contact_bracket_uses_unconstrained_selected_branch() -> None:
    def sample(alpha: float, raw: float) -> dict:
        return {
            "alpha": alpha,
            "diagnostic_unconstrained_selected": {
                "raw_guard_components": {"ROD_SELF_CLEARANCE": raw}
            },
        }

    bracket = runner._raw_contact_bracket(
        [sample(0.01, -1.0e-4), sample(0.1, -1.0e-6), sample(1.0, 1.0e-5)]
    )
    assert bracket is not None
    assert bracket["lower_alpha_nonpositive"] == pytest.approx(0.1)
    assert bracket["upper_alpha_positive"] == pytest.approx(1.0)
    assert bracket["alpha_ratio"] == pytest.approx(10.0)


def test_child_path_prepares_only_and_contains_no_dynamic_entrypoint() -> None:
    assert "prepare_initial_state" in runner.CHILD_CODE
    assert "simulate_high_fidelity" not in runner.CHILD_CODE
    assert "dynamic_gate_open" not in runner.CHILD_CODE


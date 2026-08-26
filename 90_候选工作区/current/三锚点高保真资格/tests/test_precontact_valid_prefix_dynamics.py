from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "compression_limit" / "run_precontact_valid_prefix_dynamics.py"
FREEZER_PATH = ROOT / "compression_limit" / "freeze_precontact_valid_prefix_dynamics.py"
PREPARATION_PATH = (
    ROOT / "compression_limit" / "precontact_upper_gate" / "preparation_result.json"
)
STATE_PATH = ROOT / "compression_limit" / "precontact_upper_gate" / "prepared_state.npz"


def _load_runner():
    spec = importlib.util.spec_from_file_location("precontact_dynamic_tested", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_exact_preparation_archive_is_the_admitted_upper_gate() -> None:
    report = json.loads(PREPARATION_PATH.read_text(encoding="utf-8"))
    assert report["status"] == "ALPHA_SPECIFIC_PREPARATION_QUALIFIED_FOR_DYNAMIC_GATE"
    assert report["passed"] is True
    assert all(report["checks"].values())
    assert report["dynamic_run_count"] == 0
    assert _sha256(STATE_PATH) == report["prepared_state_sha256"]


def test_freezer_does_not_confuse_static_hessian_and_dynamic_state_dimensions() -> None:
    source = FREEZER_PATH.read_text(encoding="utf-8")
    assert "state.size == 0" in source
    assert "state.shape != (240,)" not in source


def test_first_failed_sample_fails_closed() -> None:
    assert runner.first_failed_sample([{"passed": True}, {"passed": True}]) is None
    assert runner.first_failed_sample([{"passed": True}, {"passed": False}]) == 1
    assert runner.first_failed_sample([{"passed": True}, {}]) == 1


def test_runner_passes_exact_preparation_and_does_not_continue_contact() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "simulate_high_fidelity(" in source
    assert "preparation=preparation" in source
    assert "postcontact_run_count\": 0" in source
    assert "contact_force_model" not in source
    assert "impact_model" not in source
    assert "friction_model" not in source


def test_freeze_contract_declares_discrete_candidate_diagnostic() -> None:
    source = FREEZER_PATH.read_text(encoding="utf-8")
    assert '"continuous_certificate": False' in source
    assert '"postcontact_continuation": False' in source
    assert '"dynamic_run_count_at_freeze": 0' in source
    assert '"formal_change_authorized": False' in source

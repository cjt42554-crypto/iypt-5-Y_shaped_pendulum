from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from ypendulum.scientific_revision.ablation import validate_ablation_transition
from ypendulum.scientific_revision.event_qualification import (
    compare_event_runs,
    validate_axis_variant,
)
from ypendulum.scientific_revision.model_identity import (
    EvidenceLevel,
    derive_evidence_assessment,
    evidence_transition_allowed,
    get_model_identity,
)
from ypendulum.scientific_revision.numerics import trapezoid_integral
from ypendulum.scientific_revision.overlay import (
    apply_overlay_to_model,
    load_overlay,
    overlay_from_mapping,
    seal_overlay_bytes,
    verify_sealed_overlay,
)
from ypendulum.scientific_revision.scientific_guard import frequency_preview


@dataclass(frozen=True)
class _Branch:
    ei: float


class _FakeModel:
    def __init__(self):
        self.branches = {
            name: _Branch(1.0) for name in ("upper_A", "upper_B", "lower")
        }
        self.compression_regularization_scale = 1.0
        self.model_id = "legacy"
        self.attachment_body = np.array([0.0, 0.0, 0.01])
        self.reference_bob_position = np.array([0.0, 0.0, -0.5])
        self.bob_contact_radius = 0.01
        self.bob_radius = 0.01
        self.bob_inertia = 1.0e-5
        self.length_guard = 1.0e-12
        self.contact_guard_enabled = True
        self.air_density = 1.2
        self.gravity = np.array([0.0, 0.0, -9.80665])
        self.bob_buoyancy = np.zeros(3)
        self.cfg = SimpleNamespace(bob=SimpleNamespace(buoyancy=False))


def _overlay_mapping(
    *, model_id="HF-BILATERAL-ROD-RIGID-BOB-1.1", compression=1.0
):
    return {
        "schema_version": "YPS-SCIENTIFIC-REVISION-OVERLAY-1.1",
        "model_id": model_id,
        "compression_scale": compression,
        "branch_bending_stiffness": {
            "upper_A": {"value": 1.0e-6, "unit": "N*m^2", "source": "test"},
            "upper_B": {"value": 2.0e-6, "unit": "N*m^2", "source": "test"},
            "lower": {"value": 3.0e-6, "unit": "N*m^2", "source": "test"},
        },
        "bob_mode": "finite",
        "contact_guard_mode": "inherited",
        "requested_claim": "PREDICTIVE",
        "initial_state_semantics": "test",
    }


def test_model_identity_caps_unvalidated_claims():
    identity = get_model_identity("HF-BILATERAL-ROD-RIGID-BOB-1.1")
    assert identity.claim_ceiling is EvidenceLevel.CODE_VERIFIED
    overlay = overlay_from_mapping(_overlay_mapping())
    assert overlay.requested_ceiling is EvidenceLevel.CODE_VERIFIED
    assessment = derive_evidence_assessment(
        requested_analysis_level=overlay.requested_analysis_level,
        model_claim_ceiling=overlay.model_claim_ceiling,
        evidence=None,
    )
    assert assessment.actual_evidence_level is EvidenceLevel.MODEL_CONSISTENT
    assert "missing_evidence_bundle" in assessment.downgrade_reasons
    allowed, missing = evidence_transition_allowed(
        EvidenceLevel.CODE_VERIFIED,
        EvidenceLevel.PREDICTIVE,
        {"tests_passed": True},
    )
    assert not allowed
    assert "sealed_real_experiment_data" in missing
    assert "held_out_initial_conditions_passed" in missing


def _code_evidence(commit: str = "a" * 40) -> dict[str, object]:
    return {
        "git_commit": commit,
        "source_commit_matches": True,
        "clean_worktree": True,
        "tests_passed": True,
        "energy_and_invariant_checks_passed": True,
        "input_identity_complete": True,
        "contact_guards_enabled": True,
        "space_time_output_refinement_passed": False,
        "solver_crosscheck_passed": False,
        "event_signature_stable": False,
        "thresholds_frozen_before_runs": False,
    }


def test_machine_evidence_can_grant_code_verified_but_not_numerical_qualification():
    assessment = derive_evidence_assessment(
        requested_analysis_level="NUMERICALLY_QUALIFIED",
        model_claim_ceiling="NUMERICALLY_QUALIFIED",
        evidence=_code_evidence(),
        evidence_bundle_sha256="b" * 64,
        source_commit="a" * 40,
    )
    assert assessment.actual_evidence_level is EvidenceLevel.CODE_VERIFIED
    assert "space_time_output_refinement_passed" in assessment.downgrade_reasons
    assert assessment.evidence_bundle_sha256 == "b" * 64


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("tests_passed", "tests_passed"),
        ("clean_worktree", "clean_worktree"),
        ("input_identity_complete", "input_identity_complete"),
        ("contact_guards_enabled", "contact_guards_enabled"),
        ("source_commit_matches", "source_commit_matches"),
    ],
)
def test_code_evidence_downgrades_fail_closed(field, reason):
    evidence = _code_evidence()
    evidence[field] = False
    assessment = derive_evidence_assessment(
        requested_analysis_level="CODE_VERIFIED",
        model_claim_ceiling="CODE_VERIFIED",
        evidence=evidence,
    )
    assert assessment.actual_evidence_level is EvidenceLevel.MODEL_CONSISTENT
    assert reason in assessment.downgrade_reasons


def test_runner_enforces_live_input_and_contact_guards(tmp_path):
    from ypendulum.scientific_revision.runner import _evidence_assessment

    commit = "a" * 40
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(_code_evidence(commit)), encoding="utf-8")
    overlay = overlay_from_mapping(_overlay_mapping())
    accepted, _identity = _evidence_assessment(
        overlay,
        evidence_path,
        tmp_path / "accepted-inputs",
        live_commit=commit,
        live_clean=True,
        current_input_identity_complete=True,
        current_contact_guards_enabled=True,
    )
    assert accepted.actual_evidence_level is EvidenceLevel.CODE_VERIFIED

    rejected, identity = _evidence_assessment(
        overlay,
        evidence_path,
        tmp_path / "rejected-inputs",
        live_commit=commit,
        live_clean=True,
        current_input_identity_complete=True,
        current_contact_guards_enabled=False,
    )
    assert rejected.actual_evidence_level is EvidenceLevel.MODEL_CONSISTENT
    assert "contact_guards_enabled" in rejected.downgrade_reasons
    assert identity is not None
    assert identity["current_contact_guards_enabled"] is False


def test_overlay_replaces_each_branch_ei():
    overlay = overlay_from_mapping(_overlay_mapping())
    model = _FakeModel()
    manifest = apply_overlay_to_model(model, overlay)
    assert model.model_id == overlay.model_id
    assert model.branches["upper_A"].ei == 1.0e-6
    assert model.branches["upper_B"].ei == 2.0e-6
    assert model.branches["lower"].ei == 3.0e-6
    assert manifest["actual_compression_scale"] == 1.0


def test_exact_unilateral_point_limit_is_explicit():
    mapping = _overlay_mapping(
        model_id="HF-TENSION-ROD-RIGID-BOB-LIMIT-1.1",
        compression=0.0,
    )
    mapping["bob_mode"] = "point_limit"
    mapping["contact_guard_mode"] = "disabled"
    mapping["point_limit_fraction"] = 1.0e-3
    overlay = overlay_from_mapping(mapping)
    model = _FakeModel()
    apply_overlay_to_model(model, overlay)
    assert model.compression_regularization_scale == 0.0
    assert not model.contact_guard_enabled
    np.testing.assert_allclose(
        np.linalg.norm(model.attachment_body), 1.0e-5, rtol=0, atol=1e-15
    )


def test_frequency_guard_rejects_short_record_and_accepts_stable_preview():
    short_t = np.linspace(0.0, 0.2, 200)
    short_y = np.sin(2.0 * np.pi * short_t)
    assert frequency_preview(short_t, short_y).status == "UNAVAILABLE"
    long_t = np.linspace(0.0, 20.0, 5000)
    long_y = np.sin(2.0 * np.pi * 1.25 * long_t)
    audit = frequency_preview(long_t, long_y)
    assert audit.status == "PREVIEW_STABLE"
    assert audit.frequency_hz is not None
    np.testing.assert_allclose(audit.frequency_hz, 1.25, rtol=0.01, atol=0.0)


def _write_run(path: Path, scale: float, event_time: float) -> None:
    path.mkdir(parents=True)
    time = np.linspace(0.0, 1.0, 1001)
    bob = np.column_stack(
        [
            0.1 * np.sin(2.0 * np.pi * time),
            0.05 * np.sin(3.0 * np.pi * time),
            -0.5 + 0.01 * np.cos(2.0 * np.pi * time),
        ]
    )
    tension = scale * (1.0 + 0.3 * np.exp(-((time - event_time) / 0.03) ** 2))
    balance = np.full_like(time, 1.0e-9)
    np.savez_compressed(
        path / "trajectory.npz",
        time=time,
        bob_position=bob,
        tension_lower=np.repeat(tension[:, None], 5, axis=1),
        tension_upper_A=np.repeat((0.8 * tension)[:, None], 4, axis=1),
        tension_upper_B=np.repeat((0.8 * tension)[:, None], 4, axis=1),
        energy_balance_residual=balance,
    )
    (path / "summary.json").write_text(
        json.dumps({"max_abs_energy_balance_residual": 1.0e-9}),
        encoding="utf-8",
    )
    (path / "qualification-events.json").write_text(
        json.dumps(
            [
                {
                    "event_type": "HF_SEGMENT_RETENSION_SAMPLED_BRACKET",
                    "time_s": event_time,
                    "branch": "lower",
                    "material_coordinate_or_segment": "segment:3",
                    "direction": "rising",
                    "ordinal": 1,
                    "window_before_s": 0.05,
                    "window_after_s": 0.05,
                }
            ]
        ),
        encoding="utf-8",
    )


def test_event_qualification_passes_close_synthetic_runs(tmp_path):
    _write_run(tmp_path / "coarse", 1.0, 0.50000)
    _write_run(tmp_path / "fine", 1.001, 0.50002)
    plan = {
        "schema_version": "YPS-EVENT-DIAGNOSTIC-2.0",
        "thresholds": {
            "trajectory_normalized_rms": 0.001,
            "event_time_absolute_s": 0.0001,
            "event_time_relative": 0.005,
            "peak_tension_relative": 0.02,
            "tension_impulse_relative": 0.02,
            "energy_residual_absolute": 1.0e-7,
        },
        "runs": [
            {"label": "coarse", "path": "coarse"},
            {"label": "fine", "path": "fine"},
        ],
    }
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan), encoding="utf-8")
    report = compare_event_runs(plan_path, tmp_path / "report")
    assert report["passed"]
    assert report["comparisons"][0]["metrics"]["event_local_metrics_left"][0][
        "local_tension_impulse_N_s"
    ] > 0.0


def test_event_qualification_fails_closed_when_event_is_missing(tmp_path):
    _write_run(tmp_path / "left", 1.0, 0.5)
    _write_run(tmp_path / "right", 1.0, 0.5)
    (tmp_path / "right" / "qualification-events.json").write_text(
        "[]\n", encoding="utf-8"
    )
    plan_path = tmp_path / "missing-event-plan.yaml"
    plan_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "YPS-EVENT-DIAGNOSTIC-2.0",
                "runs": [
                    {"label": "left", "path": "left"},
                    {"label": "right", "path": "right"},
                ],
            }
        ),
        encoding="utf-8",
    )
    report = compare_event_runs(plan_path, tmp_path / "missing-event-report")
    assert report["passed"] is False
    checks = report["comparisons"][0]["checks"]
    assert checks["event_counts_equal"] is False
    assert checks["event_set_nonempty"] is False


def test_desktop_revision_metadata_is_removed_from_user_scan_coordinates():
    from ypendulum.scientific_revision.desktop_contract import (
        OVERLAY_PATH_KEY,
        OVERLAY_SHA256_KEY,
        scientific_revision_metadata,
        user_scan_coordinates,
    )

    request = {
        "scan_coordinates": {
            "physical.T": 8.0,
            OVERLAY_PATH_KEY: "/tmp/overlay.yaml",
            OVERLAY_SHA256_KEY: "a" * 64,
        }
    }
    assert user_scan_coordinates(request) == {"physical.T": 8.0}
    assert scientific_revision_metadata(request) == {
        "overlay_path": "/tmp/overlay.yaml",
        "overlay_sha256": "a" * 64,
    }


def test_event_qualification_rejects_changed_event_order(tmp_path):
    _write_run(tmp_path / "left", 1.0, 0.4)
    _write_run(tmp_path / "right", 1.0, 0.4)
    for name, rows in (
        ("left", [("slack", 0.30), ("retension", 0.40)]),
        ("right", [("retension", 0.30), ("slack", 0.40)]),
    ):
        events = []
        for event_type, event_time in rows:
            events.append(
                {
                    "event_type": event_type,
                    "time_s": event_time,
                    "branch": "lower",
                    "material_coordinate_or_segment": "segment:3",
                    "direction": "falling" if event_type == "slack" else "rising",
                    "ordinal": 1,
                    "window_before_s": 0.05,
                    "window_after_s": 0.05,
                }
            )
        (tmp_path / name / "qualification-events.json").write_text(
            json.dumps(events), encoding="utf-8"
        )
    plan = {
        "schema_version": "YPS-EVENT-DIAGNOSTIC-2.0",
        "runs": [
            {"label": "left", "path": "left"},
            {"label": "right", "path": "right"},
        ],
    }
    plan_path = tmp_path / "order-plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan), encoding="utf-8")
    report = compare_event_runs(plan_path, tmp_path / "order-report")
    assert not report["passed"]
    assert not report["comparisons"][0]["checks"]["event_order_equal"]


def test_sealed_overlay_uses_checked_bytes_and_rejects_tampering(tmp_path):
    source = tmp_path / "overlay.yaml"
    source.write_text(yaml.safe_dump(_overlay_mapping()), encoding="utf-8")
    checked = source.read_bytes()
    sealed = seal_overlay_bytes(
        checked,
        tmp_path / "inputs",
        original_source_path_for_information_only=str(source),
    )
    source.write_text("replaced: true\n", encoding="utf-8")
    assert load_overlay(sealed.raw_path).model_id == "HF-BILATERAL-ROD-RIGID-BOB-1.1"
    verify_sealed_overlay(sealed)
    sealed.raw_path.write_bytes(sealed.raw_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="篡改"):
        verify_sealed_overlay(sealed)


def test_desktop_worker_uses_sealed_overlay_after_source_replacement(
    tmp_path, monkeypatch
):
    from ypendulum.scientific_revision import revised_desktop_worker as worker
    from ypendulum.scientific_revision.desktop_contract import (
        OVERLAY_PATH_KEY,
        OVERLAY_SHA256_KEY,
    )
    from ypendulum.ui.desktop_config import (
        default_desktop_configuration,
        make_desktop_request,
        write_desktop_request,
    )

    source = tmp_path / "overlay.yaml"
    source.write_text(yaml.safe_dump(_overlay_mapping()), encoding="utf-8")
    checked = source.read_bytes()
    checked_sha = hashlib.sha256(checked).hexdigest()
    _forward, high_fidelity = default_desktop_configuration()
    request = make_desktop_request(
        label="overlay-toctou-negative",
        backend="high_fidelity",
        forward_config=None,
        high_fidelity_config=high_fidelity,
        scan_coordinates={
            OVERLAY_PATH_KEY: str(source),
            OVERLAY_SHA256_KEY: checked_sha,
        },
    )
    request_path = write_desktop_request(tmp_path / "request.json", request)
    observed: dict[str, object] = {}

    def fake_run(command, *, environment):
        del environment
        source.write_text("replaced_after_validation: true\n", encoding="utf-8")
        overlay_argument = Path(command[command.index("--overlay") + 1])
        observed["path"] = overlay_argument
        observed["bytes"] = overlay_argument.read_bytes()
        observed["expected"] = command[command.index("--expected-overlay-sha256") + 1]
        return 0

    monkeypatch.setattr(worker, "_run_and_relay", fake_run)
    monkeypatch.setattr(
        worker,
        "_hf_outcome",
        lambda _directory, _code: {"status": "COMPLETE", "numerical_status": "SMOKE"},
    )
    output = tmp_path / "worker-output"
    assert worker.run_request(request_path, "high_fidelity", output) == 0
    assert observed["bytes"] == checked
    assert observed["expected"] == checked_sha
    assert observed["path"] != source
    result = json.loads((output / "desktop_result.json").read_text(encoding="utf-8"))
    revision = result["scientific_revision"]
    assert revision["actual_evidence_level"] == "MODEL_CONSISTENT"
    assert "missing_evidence_bundle" in revision["downgrade_reasons"]


def test_trapezoid_helper_is_independent_of_numpy_aliases(monkeypatch):
    monkeypatch.delattr(np, "trapz", raising=False)
    monkeypatch.delattr(np, "trapezoid", raising=False)
    assert trapezoid_integral([0.0, 1.0, 0.0], [0.0, 1.0, 2.0]) == pytest.approx(1.0)


def test_event_axis_whitelist_rejects_unplanned_drift():
    base = {
        "cables": {
            "upper_A": {"elements": 2},
            "upper_B": {"elements": 2},
            "lower": {"elements": 3},
        },
        "solver": {"max_step": {"value": 1e-4, "unit": "s"}},
        "bob": {"mass": {"value": 0.08, "unit": "kg"}},
    }
    candidate = json.loads(json.dumps(base))
    candidate["cables"]["upper_A"]["elements"] = 4
    assert validate_axis_variant(base, candidate, "space") == (
        "cables.upper_A.elements",
    )
    candidate["bob"]["mass"]["value"] = 0.09
    with pytest.raises(ValueError, match="白名单外"):
        validate_axis_variant(base, candidate, "space")


def _event_executor_plan(tmp_path: Path, commit: str) -> Path:
    project = Path(__file__).resolve().parents[2]
    sources = {
        "base-config.yaml": project / "configs/revision/smoke/hf-common-state-smoke.yaml",
        "initial-state.yaml": project / "configs/revision/smoke/event-initial-state.yaml",
        "overlay.yaml": project / "configs/revision/hf-bilateral-explicit-ei-baseline.yaml",
    }
    for name, source in sources.items():
        shutil.copyfile(source, tmp_path / name)
    digest = {
        name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
        for name in sources
    }
    plan = {
        "schema_version": "YPS-EVENT-QUALIFICATION-EXECUTION-2.0",
        "plan_id": "unit-event-executor",
        "git_commit": commit,
        "base_config": "base-config.yaml",
        "base_config_sha256": digest["base-config.yaml"],
        "overlay": "overlay.yaml",
        "overlay_sha256": digest["overlay.yaml"],
        "initial_state": "initial-state.yaml",
        "initial_state_sha256": digest["initial-state.yaml"],
        "thresholds": {},
        "matrix_axes": {
            "space": {"factors": [1, 2, 4]},
            "time": {"max_step_s": [2.5e-4, 1.25e-4]},
            "output": {"output_dt_s": [2.5e-4, 1.25e-4]},
            "solver": {"methods": ["Radau", "BDF"]},
        },
        "planned_events": [
            {
                "branch": "lower",
                "material_coordinate_or_segment": "coordinate:0.5",
                "event_type": "PLANNED_LOCAL_TENSION_PROBE",
                "direction": "sample",
                "ordinal": 1,
                "time_s": 7.5e-4,
                "window_before_s": 2.5e-4,
                "window_after_s": 2.5e-4,
            }
        ],
    }
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    return plan_path


def test_event_executor_rejects_wrong_grid_and_input_hash(tmp_path, monkeypatch):
    from ypendulum.scientific_revision import event_qualification as event_module

    invalid_axes = {
        "space": {"factors": [1, 2, 3]},
        "time": {"max_step_s": [2.5e-4, 1.25e-4]},
        "output": {"output_dt_s": [2.5e-4, 1.25e-4]},
        "solver": {"methods": ["Radau", "BDF"]},
    }
    with pytest.raises(ValueError, match="N/2N/4N"):
        event_module._validate_matrix_axes(invalid_axes)

    commit = "c" * 40
    plan_path = _event_executor_plan(tmp_path, commit)
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    plan["base_config_sha256"] = "0" * 64
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(event_module, "_git_commit", lambda: commit)
    monkeypatch.setattr(event_module, "_git_worktree_clean", lambda: True)
    with pytest.raises(ValueError, match="base_config_sha256"):
        event_module.execute_event_qualification(plan_path, tmp_path / "output")


def test_event_executor_fails_if_threshold_plan_changes_after_start(
    tmp_path, monkeypatch
):
    from ypendulum.scientific_revision import event_qualification as event_module
    from ypendulum.scientific_revision import runner as runner_module

    commit = "d" * 40
    plan_path = _event_executor_plan(tmp_path, commit)
    monkeypatch.setattr(event_module, "_git_commit", lambda: commit)
    monkeypatch.setattr(event_module, "_git_worktree_clean", lambda: True)
    changed = False

    def fake_run(_config, _overlay, output, **_kwargs):
        nonlocal changed
        output = Path(output)
        output.mkdir(parents=True)
        time = np.linspace(0.0, 1.5e-3, 13)
        np.savez_compressed(
            output / "trajectory.npz",
            time=time,
            bob_position=np.zeros((time.size, 3)),
            tension_lower=np.ones((time.size, 3)),
            energy_balance_residual=np.zeros(time.size),
        )
        (output / "summary.json").write_text(
            json.dumps({"max_abs_energy_balance_residual": 0.0}),
            encoding="utf-8",
        )
        if not changed:
            plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
            plan["thresholds"]["trajectory_normalized_rms"] = 1.0
            plan_path.write_text(
                yaml.safe_dump(plan, sort_keys=False), encoding="utf-8"
            )
            changed = True
        return output

    monkeypatch.setattr(runner_module, "run_revised_high_fidelity", fake_run)
    output = tmp_path / "qualification"
    with pytest.raises(RuntimeError, match="未通过"):
        event_module.execute_event_qualification(plan_path, output)
    report = json.loads((output / "event-qualification.json").read_text(encoding="utf-8"))
    assert report["plan_unchanged_after_runs"] is False
    assert report["passed"] is False


def test_ablation_transition_rejects_extra_parameter_drift():
    shared = {
        "backend": "HF",
        "model_id": "m",
        "bob_mode": "point_limit",
        "contact_guard_mode": "disabled",
        "compression_scale": 0.0,
        "branch_EI_N_m2": {"upper_A": 0.0, "upper_B": 0.0, "lower": 0.0},
        "requested_analysis_level": "MODEL_CONSISTENT",
        "model_claim_ceiling": "MODEL_CONSISTENT",
        "initial_state_semantics": "sealed_common_hf_material_state",
        "common_state_raw_sha256": "a" * 64,
        "mapping_residuals": {"hf_discrete_state_residual": 0.0},
        "external_mechanisms": [],
    }
    right = json.loads(json.dumps(shared))
    right["bob_mode"] = "finite"
    right["contact_guard_mode"] = "inherited"
    assert validate_ablation_transition("M1", "M2", shared, right) == (
        "bob_mode",
        "contact_guard_mode",
    )
    right["unexpected"] = 1
    with pytest.raises(ValueError, match="白名单外"):
        validate_ablation_transition("M1", "M2", shared, right)

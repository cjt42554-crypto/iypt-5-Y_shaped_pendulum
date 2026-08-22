from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import yaml

from ypendulum.scientific_revision.event_qualification import qualify_event_plan
from ypendulum.scientific_revision.model_identity import (
    EvidenceLevel,
    evidence_transition_allowed,
    get_model_identity,
)
from ypendulum.scientific_revision.overlay import apply_overlay_to_model, overlay_from_mapping
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
    assert overlay.effective_claim is EvidenceLevel.CODE_VERIFIED
    allowed, missing = evidence_transition_allowed(
        EvidenceLevel.CODE_VERIFIED,
        EvidenceLevel.PREDICTIVE,
        {"tests_passed": True},
    )
    assert not allowed
    assert "sealed_real_experiment_data" in missing
    assert "held_out_initial_conditions_passed" in missing


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
        max_tension=tension,
        energy_balance_residual=balance,
    )
    (path / "summary.json").write_text(
        json.dumps({"max_abs_energy_balance_residual": 1.0e-9}),
        encoding="utf-8",
    )
    with (path / "events.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["type", "time", "branch", "material_segment"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "type": "HF_SEGMENT_RETENSION_SAMPLED_BRACKET",
                "time": event_time,
                "branch": "lower",
                "material_segment": "3",
            }
        )


def test_event_qualification_passes_close_synthetic_runs(tmp_path):
    _write_run(tmp_path / "coarse", 1.0, 0.50000)
    _write_run(tmp_path / "fine", 1.001, 0.50002)
    plan = {
        "schema_version": "YPS-EVENT-QUALIFICATION-1.1",
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
    report = qualify_event_plan(plan_path, tmp_path / "report")
    assert report["passed"]


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
        with (tmp_path / name / "events.csv").open(
            "w", encoding="utf-8", newline=""
        ) as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=["type", "time", "branch", "material_segment"],
            )
            writer.writeheader()
            for event_type, event_time in rows:
                writer.writerow(
                    {
                        "type": event_type,
                        "time": event_time,
                        "branch": "lower",
                        "material_segment": "3",
                    }
                )
    plan = {
        "schema_version": "YPS-EVENT-QUALIFICATION-1.1",
        "runs": [
            {"label": "left", "path": "left"},
            {"label": "right", "path": "right"},
        ],
    }
    plan_path = tmp_path / "order-plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan), encoding="utf-8")
    report = qualify_event_plan(plan_path, tmp_path / "order-report")
    assert not report["passed"]
    assert not report["comparisons"][0]["checks"]["event_order_equal"]

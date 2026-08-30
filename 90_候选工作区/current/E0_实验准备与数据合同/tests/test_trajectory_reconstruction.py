from pathlib import Path

import numpy as np
import pytest

from yps_experiment_pipeline.contracts import validate_document
from yps_experiment_pipeline.trajectory import (
    mask_after_first_domain_event,
    validate_trajectory_arrays,
    write_bundle,
)


def test_first_domain_event_masks_all_later_torus_samples():
    time = np.linspace(0.0, 2.0, 21)
    valid, first = mask_after_first_domain_event(
        time,
        np.ones(time.size, dtype=bool),
        [{"code": "SLACK", "time_s": 1.1}, {"code": "CONTACT", "time_s": 1.6}],
    )
    assert first == 1.1
    assert np.all(valid[time < 1.1])
    assert not np.any(valid[time >= 1.1])


def test_npz_and_manifest_are_hash_bound(tmp_path: Path):
    time = np.linspace(0.0, 1.0, 11)
    points = np.column_stack((time, 0.0 * time, 1.0 + 0.0 * time))
    arrays = {
        "time_s": time,
        "r_bob_W_m": points,
        "r_junction_W_m": 0.5 * points,
        "branch_marker_positions_W_m": np.zeros((time.size, 3, 3)),
        "bob_orientation_WB": np.repeat(np.eye(3)[None, :, :], time.size, axis=0),
        "position_covariance": np.repeat(
            (1e-8 * np.eye(3))[None, None, :, :], time.size, axis=0
        ).repeat(2, axis=1),
        "valid_mask": np.ones(time.size, dtype=bool),
        "occlusion_mask": np.zeros((time.size, 2), dtype=bool),
        "event_annotations": np.full(time.size, "NONE"),
    }
    units = {
        "time_s": "s",
        "r_bob_W_m": "m",
        "r_junction_W_m": "m",
        "branch_marker_positions_W_m": "m",
        "bob_orientation_WB": "1",
        "position_covariance": "m^2",
        "valid_mask": "1",
        "occlusion_mask": "1",
        "event_annotations": "code",
    }
    detection_manifest_file = tmp_path / "detection_2d_bundle.json"
    detection_manifest_file.write_text("{}\n", encoding="utf-8")
    manifest = write_bundle(
        tmp_path / "bundle",
        run_id="SYNTHETIC_RUN",
        attempt_id="SYNTHETIC_ATTEMPT",
        apparatus_revision="SYNTHETIC_RIG",
        data_origin="SYNTHETIC_REAL_SHAPE_FIXTURE",
        detection_manifest_file=detection_manifest_file,
        camera_rig_sha256="0" * 64,
        arrays=arrays,
        units=units,
        valid_mask=arrays["valid_mask"],
        event_codes=[],
    )
    validate_document("trajectory_bundle.schema.json", manifest)
    assert len(manifest["array_sha256"]) == 64
    assert manifest["valid_fraction"] == 1.0


def test_bundle_writer_rejects_incomplete_array_contract_before_creating_output(tmp_path: Path):
    time = np.linspace(0.0, 1.0, 11)
    with pytest.raises(ValueError, match="lacks required arrays"):
        write_bundle(
            tmp_path / "incomplete",
            run_id="SYNTHETIC_INCOMPLETE",
            attempt_id="SYNTHETIC_ATTEMPT",
            apparatus_revision="SYNTHETIC_RIG",
            data_origin="SYNTHETIC_REAL_SHAPE_FIXTURE",
            detection_manifest_file=tmp_path / "missing_detection.json",
            camera_rig_sha256="0" * 64,
            arrays={"time_s": time, "valid_mask": np.ones(time.size, dtype=bool)},
            units={"time_s": "s", "valid_mask": "1"},
            valid_mask=np.ones(time.size, dtype=bool),
            event_codes=[],
        )
    assert not (tmp_path / "incomplete").exists()


def test_trajectory_covariance_must_be_symmetric_and_positive_semidefinite():
    time = np.linspace(0.0, 1.0, 11)
    points = np.column_stack((time, 0.0 * time, 1.0 + 0.0 * time))
    arrays = {
        "time_s": time,
        "r_bob_W_m": points,
        "r_junction_W_m": 0.5 * points,
        "branch_marker_positions_W_m": np.zeros((time.size, 3, 3)),
        "bob_orientation_WB": np.repeat(np.eye(3)[None, :, :], time.size, axis=0),
        "position_covariance": np.repeat(np.eye(3)[None, None, :, :], time.size, axis=0).repeat(
            2, axis=1
        ),
        "valid_mask": np.ones(time.size, dtype=bool),
        "occlusion_mask": np.zeros((time.size, 2), dtype=bool),
        "event_annotations": np.full(time.size, "NONE"),
    }
    units = {name: "1" for name in arrays}
    arrays["position_covariance"][0, 0, 0, 1] = 0.2
    with pytest.raises(ValueError, match="symmetric"):
        validate_trajectory_arrays(arrays, units, arrays["valid_mask"])

    arrays["position_covariance"][0, 0] = np.diag([-1.0, 1.0, 1.0])
    with pytest.raises(ValueError, match="positive semidefinite"):
        validate_trajectory_arrays(arrays, units, arrays["valid_mask"])

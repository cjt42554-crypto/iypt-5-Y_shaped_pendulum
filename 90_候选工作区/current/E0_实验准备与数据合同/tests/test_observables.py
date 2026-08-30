from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
from real_shape_fixture import camera_rig_document, digest

from yps_experiment_pipeline.contracts import sha256_document, sha256_file, validate_document
from yps_experiment_pipeline.detections import write_detection_bundle
from yps_experiment_pipeline.observables import (
    estimate_damped_mode,
    normalized_closure_error,
    resonant_phase,
    write_common_observables,
)
from yps_experiment_pipeline.trajectory import write_bundle


def _valid_trajectory_source(
    tmp_path: Path,
    time: np.ndarray,
    bob: np.ndarray,
    junction: np.ndarray,
) -> tuple[Path, str]:
    camera_rig = camera_rig_document()
    camera_hash = sha256_document(camera_rig)
    sample_count = time.size
    camera_count = 2
    marker_count = 2
    frame_time = np.repeat(time[:, None], camera_count, axis=1)
    detection_arrays = {
        "time_s": time,
        "frame_index": np.repeat(
            np.arange(sample_count, dtype=np.int64)[:, None], camera_count, axis=1
        ),
        "raw_timestamp_s": frame_time.copy(),
        "aligned_timestamp_s": frame_time.copy(),
        "sync_event_id": np.full((sample_count, camera_count), "SYNTHETIC_COMMON_EVENT"),
        "sync_offset_s": np.zeros((sample_count, camera_count)),
        "sync_uncertainty_s": np.full((sample_count, camera_count), 2.0e-5),
        "dropped_frame_flag": np.zeros((sample_count, camera_count), dtype=bool),
        "pixels_px": np.zeros((sample_count, camera_count, marker_count, 2)),
        "pixel_covariance_px2": np.broadcast_to(
            0.04 * np.eye(2), (sample_count, camera_count, marker_count, 2, 2)
        ).copy(),
        "valid_mask": np.ones((sample_count, camera_count, marker_count), dtype=bool),
        "occlusion_mask": np.zeros((sample_count, camera_count, marker_count), dtype=bool),
        "detection_score": np.ones((sample_count, camera_count, marker_count)),
        "invalid_reason": np.full((sample_count, camera_count, marker_count), "VALID"),
    }
    detection_units = {
        "time_s": "s",
        "frame_index": "1",
        "raw_timestamp_s": "s",
        "aligned_timestamp_s": "s",
        "sync_event_id": "code",
        "sync_offset_s": "s",
        "sync_uncertainty_s": "s",
        "dropped_frame_flag": "1",
        "pixels_px": "px",
        "pixel_covariance_px2": "px^2",
        "valid_mask": "1",
        "occlusion_mask": "1",
        "detection_score": "1",
        "invalid_reason": "code",
    }
    detection_directory = tmp_path / "detections"
    write_detection_bundle(
        detection_directory,
        run_id="SYNTHETIC_TWO_MODE",
        attempt_id="SYNTHETIC_TWO_MODE_A00",
        apparatus_revision="SYNTHETIC_TWO_MODE_RIG",
        data_origin="SYNTHETIC_REAL_SHAPE_FIXTURE",
        camera_rig_file="camera_rig.json",
        camera_rig_sha256=camera_hash,
        raw_video_files=[
            {"camera_id": "CAM_A", "path": "a.mp4", "sha256": digest("obs-a")},
            {"camera_id": "CAM_B", "path": "b.mp4", "sha256": digest("obs-b")},
        ],
        detector={
            "name": "SYNTHETIC_OBSERVABLE_FIXTURE",
            "version": "1.0",
            "configuration_sha256": digest("obs-detector"),
        },
        camera_ids=["CAM_A", "CAM_B"],
        marker_ids=["BOB", "JUNCTION"],
        arrays=detection_arrays,
        units=detection_units,
    )
    trajectory_arrays = {
        "time_s": time,
        "r_bob_W_m": bob,
        "r_junction_W_m": junction,
        "branch_marker_positions_W_m": np.zeros((sample_count, 3, 3)),
        "bob_orientation_WB": np.repeat(np.eye(3)[None, :, :], sample_count, axis=0),
        "position_covariance": np.broadcast_to(1.0e-8 * np.eye(3), (sample_count, 2, 3, 3)).copy(),
        "valid_mask": np.ones(sample_count, dtype=bool),
        "occlusion_mask": np.zeros((sample_count, 2), dtype=bool),
        "event_annotations": np.full(sample_count, "NONE"),
    }
    trajectory_units = {
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
    trajectory_directory = tmp_path / "trajectory"
    write_bundle(
        trajectory_directory,
        run_id="SYNTHETIC_TWO_MODE",
        attempt_id="SYNTHETIC_TWO_MODE_A00",
        apparatus_revision="SYNTHETIC_TWO_MODE_RIG",
        data_origin="SYNTHETIC_REAL_SHAPE_FIXTURE",
        detection_manifest_file=detection_directory / "detection_2d_bundle.json",
        camera_rig_sha256=camera_hash,
        arrays=trajectory_arrays,
        units=trajectory_units,
        valid_mask=trajectory_arrays["valid_mask"],
        event_codes=[],
    )
    return trajectory_directory / "trajectory_bundle.json", camera_hash


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
    trajectory_manifest_file, camera_hash = _valid_trajectory_source(
        tmp_path,
        time,
        arrays["r_bob_W_m"],
        arrays["r_junction_W_m"],
    )
    common = write_common_observables(
        tmp_path / "common",
        data_origin="SYNTHETIC_REAL_SHAPE_FIXTURE",
        identity={
            "source_id": "SYNTHETIC_TWO_MODE",
            "source_sha256": sha256_file(trajectory_manifest_file),
            "run_id": "SYNTHETIC_TWO_MODE",
            "attempt_id": "SYNTHETIC_TWO_MODE_A00",
            "apparatus_revision": "SYNTHETIC_TWO_MODE_RIG",
            "camera_rig_sha256": camera_hash,
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

    common_units = {
        "time_s": "s",
        "r_bob_W_m": "m",
        "r_junction_W_m": "m",
        "modal_basis_W": "1",
        "q_fast_m": "m",
        "q_slow_m": "m",
        "resonant_phase_rad": "rad",
        "valid_mask": "1",
    }
    identity_mismatches = {
        "source_id": "WRONG_SOURCE",
        "source_sha256": "f" * 64,
        "run_id": "WRONG_RUN",
        "attempt_id": "WRONG_ATTEMPT",
        "apparatus_revision": "SYNTHETIC_WRONG_RIG",
        "camera_rig_sha256": "e" * 64,
    }
    for field, wrong_value in identity_mismatches.items():
        bad_identity = dict(common["identity"])
        bad_identity[field] = wrong_value
        output = tmp_path / f"common_wrong_{field}"
        with pytest.raises(ValueError, match=field):
            write_common_observables(
                output,
                data_origin="SYNTHETIC_REAL_SHAPE_FIXTURE",
                identity=bad_identity,
                trajectory_manifest_file=trajectory_manifest_file,
                arrays=arrays,
                units=common_units,
                modal_basis_provenance=common["modal_basis_provenance"],
                fast=fast,
                slow=slow,
                closure_error=closure,
                events=[],
                uncertainty=common["uncertainty"],
                domain_status="IN_DOMAIN",
            )
        assert not output.exists()

    invalid_upstream = tmp_path / "invalid_trajectory.json"
    invalid_upstream.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        write_common_observables(
            tmp_path / "common_invalid_upstream",
            data_origin="SYNTHETIC_REAL_SHAPE_FIXTURE",
            identity=common["identity"],
            trajectory_manifest_file=invalid_upstream,
            arrays=arrays,
            units=common_units,
            modal_basis_provenance=common["modal_basis_provenance"],
            fast=fast,
            slow=slow,
            closure_error=closure,
            events=[],
            uncertainty=common["uncertainty"],
            domain_status="IN_DOMAIN",
        )
    assert not (tmp_path / "common_invalid_upstream").exists()

    with pytest.raises(ValueError, match="data origin"):
        write_common_observables(
            tmp_path / "common_wrong_origin",
            data_origin="MEASURED",
            identity=common["identity"],
            trajectory_manifest_file=trajectory_manifest_file,
            arrays=arrays,
            units=common_units,
            modal_basis_provenance=common["modal_basis_provenance"],
            fast=fast,
            slow=slow,
            closure_error=closure,
            events=[],
            uncertainty=common["uncertainty"],
            domain_status="IN_DOMAIN",
        )
    assert not (tmp_path / "common_wrong_origin").exists()

    shifted_arrays = dict(arrays)
    shifted_arrays["time_s"] = arrays["time_s"] + 1.0e-4
    with pytest.raises(ValueError, match="time_s differ"):
        write_common_observables(
            tmp_path / "common_wrong_time",
            data_origin="SYNTHETIC_REAL_SHAPE_FIXTURE",
            identity=common["identity"],
            trajectory_manifest_file=trajectory_manifest_file,
            arrays=shifted_arrays,
            units=common_units,
            modal_basis_provenance=common["modal_basis_provenance"],
            fast=fast,
            slow=slow,
            closure_error=closure,
            events=[],
            uncertainty=common["uncertainty"],
            domain_status="IN_DOMAIN",
        )
    assert not (tmp_path / "common_wrong_time").exists()

"""Builders for the E0R synthetic fixture with real contract shapes."""

from __future__ import annotations

from hashlib import sha256

import numpy as np

from yps_experiment_pipeline.camera import project_points
from yps_experiment_pipeline.contracts import sha256_document

APPARATUS_REVISION = "SYNTHETIC_REAL_SHAPE_V1"


def digest(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def _vector_measurement(
    measurement_id: str,
    component_id: str,
    quantity: str,
    unit: str,
    labels: list[str],
    repeats: list[list[float]],
    uncertainty: list[float],
) -> dict:
    values = np.mean(np.asarray(repeats, dtype=float), axis=0)
    covariance = np.diag(np.square(np.asarray(uncertainty, dtype=float)))
    return {
        "measurement_id": measurement_id,
        "component_id": component_id,
        "quantity": quantity,
        "unit": unit,
        "operational_definition": f"Synthetic real-shape contract fixture for {measurement_id}.",
        "value_kind": "VECTOR",
        "component_labels": labels,
        "source_type": "SYNTHETIC_REAL_SHAPE_FIXTURE",
        "raw_repeats": repeats,
        "value_si": values.tolist(),
        "type_a_standard_uncertainty": uncertainty,
        "type_b_standard_uncertainty": uncertainty,
        "combined_standard_uncertainty": (np.sqrt(2.0) * np.asarray(uncertainty)).tolist(),
        "covariance_si": covariance.tolist(),
        "covariance_group": f"SYNTHETIC_{component_id}",
        "instrument_id": "SYNTHETIC_COORDINATE_METROLOGY",
        "calibration_ref": "SYNTHETIC_CALIBRATION_CERTIFICATE",
        "timestamp": "2030-01-01T00:00:00Z",
        "environment": {
            "temperature_c": 20.0,
            "relative_humidity_percent": 50.0,
            "pressure_pa": 101325.0,
        },
        "raw_data_sha256": digest(f"raw:{measurement_id}"),
        "derivation": None,
    }


def apparatus_document() -> dict:
    document = {
        "schema_id": "YPS-E0-APPARATUS-MEASUREMENTS-1.1",
        "data_origin": "SYNTHETIC_REAL_SHAPE_FIXTURE",
        "apparatus_revision": APPARATUS_REVISION,
        "measurements": [
            _vector_measurement(
                "SUPPORT_A_XYZ",
                "SUPPORT_A",
                "position_world",
                "m",
                ["x", "y", "z"],
                [[-0.3001, 0.0001, 1.5000], [-0.3000, 0.0000, 1.5001], [-0.2999, -0.0001, 1.4999]],
                [8.0e-5, 8.0e-5, 8.0e-5],
            ),
            _vector_measurement(
                "SUPPORT_B_XYZ",
                "SUPPORT_B",
                "position_world",
                "m",
                ["x", "y", "z"],
                [[0.2999, 0.0001, 1.5000], [0.3000, 0.0000, 1.5001], [0.3001, -0.0001, 1.4999]],
                [8.0e-5, 8.0e-5, 8.0e-5],
            ),
            _vector_measurement(
                "BOB_COM_TO_ATTACHMENT",
                "BOB",
                "com_to_attachment_vector_body",
                "m",
                ["body_x", "body_y", "body_z"],
                [[0.0001, -0.0001, 0.0250], [0.0000, 0.0000, 0.0251], [-0.0001, 0.0001, 0.0249]],
                [6.0e-5, 6.0e-5, 8.0e-5],
            ),
            _vector_measurement(
                "BOB_PRINCIPAL_INERTIA",
                "BOB",
                "principal_inertia",
                "kg m^2",
                ["I1", "I2", "I3"],
                [
                    [1.20e-4, 1.35e-4, 1.48e-4],
                    [1.21e-4, 1.34e-4, 1.49e-4],
                    [1.19e-4, 1.36e-4, 1.47e-4],
                ],
                [4.0e-6, 4.0e-6, 4.0e-6],
            ),
        ],
    }
    return document


def _camera(camera_id: str, center_x: float) -> dict:
    return {
        "camera_id": camera_id,
        "source_type": "SYNTHETIC_REAL_SHAPE_FIXTURE",
        "image_width_px": 1280,
        "image_height_px": 720,
        "nominal_fps": 50.0,
        "timestamp_source": "SYNTHETIC_SHARED_CLOCK",
        "R_c": np.eye(3).tolist(),
        "c_c": [center_x, 0.0, 0.0],
        "f_x": 1000.0,
        "f_y": 990.0,
        "c_x": 640.0,
        "c_y": 360.0,
        "k1": -0.015,
        "k2": 0.001,
        "k3": -0.0001,
        "p1": 0.0002,
        "p2": -0.0003,
        "Omega_cal": [-0.9, 0.9, -0.9, 0.9],
        "calibration_board_id": "SYNTHETIC_BOARD_9X6",
        "board_dimensions_m": [0.240, 0.150],
        "board_dimension_uncertainty_m": 2.0e-5,
        "calibration_time": "2030-01-01T00:00:00Z",
        "reprojection_rms_px": 0.08,
        "raw_calibration_sha256": digest(f"calibration:{camera_id}"),
        "parameter_covariance_sha256": digest(f"calibration-covariance:{camera_id}"),
    }


def camera_rig_document() -> dict:
    return {
        "schema_id": "YPS-E0-CAMERA-RIG-1.1",
        "data_origin": "SYNTHETIC_REAL_SHAPE_FIXTURE",
        "apparatus_revision": APPARATUS_REVISION,
        "world_frame": {
            "origin": "MIDPOINT_OF_SUPPORTS_A_B",
            "x_axis": "HORIZONTAL_PROJECTION_FROM_A_TO_B",
            "y_axis": "Z_CROSS_X",
            "z_axis": "UP_OPPOSITE_GRAVITY",
        },
        "cameras": [_camera("CAM_A", -0.25), _camera("CAM_B", 0.25)],
        "synchronization": {
            "method": "SYNTHETIC_COMMON_EVENT",
            "maximum_residual_fraction_of_frame": 0.25,
            "measured_residual_fraction_of_frame": 0.02,
            "offset_s": 0.0,
            "offset_standard_uncertainty_s": 2.0e-5,
            "jitter_standard_uncertainty_s": 1.0e-5,
            "timestamp_alignment_method": "SYNTHETIC_SHARED_EVENT_FIT",
            "raw_sync_sha256": digest("synthetic-sync-events"),
        },
    }


def acquisition_document(camera_rig_sha256: str) -> dict:
    common = {
        "slot_id": "P02",
        "operation": "small_near_fast_mode_release",
        "release_target_id": "PILOT_FAST_SMALL",
        "operator_id": "SYNTHETIC_OPERATOR",
        "apparatus_revision": APPARATUS_REVISION,
        "camera_rig_sha256": camera_rig_sha256,
    }
    attempts = [
        {
            **common,
            "attempt_id": "P02-R01-A00",
            "repeat_index": 1,
            "status": "COMPLETED",
            "started_at": "2030-01-01T00:10:00Z",
            "ended_at": "2030-01-01T00:10:09Z",
            "raw_files": [
                {
                    "path": "cam_a_repeat_01.mp4",
                    "media_type": "video/mp4",
                    "sha256": digest("video-a-r1"),
                },
                {
                    "path": "cam_b_repeat_01.mp4",
                    "media_type": "video/mp4",
                    "sha256": digest("video-b-r1"),
                },
            ],
            "evidence_state": "COMPLETE_RAW_DATA_RETAINED",
            "failure": None,
            "retry_parent_id": None,
            "corrective_action": None,
        },
        {
            **common,
            "attempt_id": "P02-R02-A00",
            "repeat_index": 2,
            "status": "FAILED",
            "started_at": "2030-01-01T00:12:00Z",
            "ended_at": "2030-01-01T00:12:02Z",
            "raw_files": [
                {
                    "path": "cam_a_repeat_02_failed.mp4",
                    "media_type": "video/mp4",
                    "sha256": digest("video-a-r2-failed"),
                },
                {
                    "path": "cam_b_repeat_02_failed.mp4",
                    "media_type": "video/mp4",
                    "sha256": digest("video-b-r2-failed"),
                },
            ],
            "evidence_state": "PARTIAL_RAW_DATA_RETAINED",
            "failure": {
                "stage": "ACQUISITION",
                "reason_code": "STOP_EXCESSIVE_OCCLUSION",
                "occurred_at": "2030-01-01T00:12:02Z",
                "operator_note": "Synthetic marker occlusion injected for retry-lineage coverage.",
            },
            "retry_parent_id": None,
            "corrective_action": "Reposition the second camera before retrying the same repeat.",
        },
        {
            **common,
            "attempt_id": "P02-R02-A01",
            "repeat_index": 2,
            "status": "COMPLETED",
            "started_at": "2030-01-01T00:14:00Z",
            "ended_at": "2030-01-01T00:14:09Z",
            "raw_files": [
                {
                    "path": "cam_a_repeat_02_retry.mp4",
                    "media_type": "video/mp4",
                    "sha256": digest("video-a-r2-retry"),
                },
                {
                    "path": "cam_b_repeat_02_retry.mp4",
                    "media_type": "video/mp4",
                    "sha256": digest("video-b-r2-retry"),
                },
            ],
            "evidence_state": "COMPLETE_RAW_DATA_RETAINED",
            "failure": None,
            "retry_parent_id": "P02-R02-A00",
            "corrective_action": "Second camera repositioned; retry retained a new attempt identity.",
        },
    ]
    return {
        "schema_id": "YPS-E0-ACQUISITION-LEDGER-1.1",
        "data_origin": "SYNTHETIC_REAL_SHAPE_FIXTURE",
        "contains_measured_values": False,
        "campaign_id": "SYNTHETIC_E0R_PILOT",
        "campaign_status": "COMPLETED",
        "preregistration": {
            "plan_id": "E0_PILOT_V1",
            "plan_file": "04_GEOMETRY_AND_PILOT_PROTOCOL.md",
            "plan_sha256": digest("frozen-pilot-protocol"),
        },
        "apparatus_revision": APPARATUS_REVISION,
        "planned_slots": [
            {
                "slot_id": "P02",
                "repeat_index": 1,
                "operation": common["operation"],
                "release_target_id": common["release_target_id"],
                "state": "COMPLETED",
                "disposition_reason_code": None,
                "governing_attempt_id": None,
                "linked_attempt_ids": ["P02-R01-A00"],
            },
            {
                "slot_id": "P02",
                "repeat_index": 2,
                "operation": common["operation"],
                "release_target_id": common["release_target_id"],
                "state": "COMPLETED",
                "disposition_reason_code": None,
                "governing_attempt_id": None,
                "linked_attempt_ids": ["P02-R02-A00", "P02-R02-A01"],
            },
        ],
        "attempts": attempts,
    }


def p00_failure_document() -> dict:
    attempt_id = "P00-R01-A00"
    reason = "STOP_CAMERA_CALIBRATION"
    return {
        "schema_id": "YPS-E0-ACQUISITION-LEDGER-1.1",
        "data_origin": "SYNTHETIC_REAL_SHAPE_FIXTURE",
        "contains_measured_values": False,
        "campaign_id": "SYNTHETIC_P00_FAILURE",
        "campaign_status": "HARD_STOPPED",
        "preregistration": {
            "plan_id": "E0_PILOT_V1",
            "plan_file": "04_GEOMETRY_AND_PILOT_PROTOCOL.md",
            "plan_sha256": digest("frozen-pilot-protocol"),
        },
        "apparatus_revision": APPARATUS_REVISION,
        "planned_slots": [
            {
                "slot_id": "P00",
                "repeat_index": 1,
                "operation": "calibration_board_and_sync_flash_batch_start",
                "release_target_id": "NO_RELEASE_CALIBRATION",
                "state": "FAILED_FINAL",
                "disposition_reason_code": reason,
                "governing_attempt_id": attempt_id,
                "linked_attempt_ids": [attempt_id],
            },
            {
                "slot_id": "P01",
                "repeat_index": 1,
                "operation": "static_rig_recording_60_s",
                "release_target_id": "NO_RELEASE_STATIC",
                "state": "NOT_STARTED_DUE_TO_STOP",
                "disposition_reason_code": reason,
                "governing_attempt_id": attempt_id,
                "linked_attempt_ids": [],
            },
        ],
        "attempts": [
            {
                "slot_id": "P00",
                "attempt_id": attempt_id,
                "repeat_index": 1,
                "operation": "calibration_board_and_sync_flash_batch_start",
                "release_target_id": "NO_RELEASE_CALIBRATION",
                "status": "FAILED",
                "started_at": "2030-01-01T00:00:00Z",
                "ended_at": "2030-01-01T00:00:03Z",
                "operator_id": "SYNTHETIC_OPERATOR",
                "raw_files": [],
                "evidence_state": "NO_RAW_DATA_CREATED",
                "failure": {
                    "stage": "CALIBRATION",
                    "reason_code": reason,
                    "occurred_at": "2030-01-01T00:00:03Z",
                    "operator_note": "Calibration failed before a valid rig or raw file existed.",
                },
                "retry_parent_id": None,
                "corrective_action": "Inspect the calibration target before a new attempt.",
                "apparatus_revision": APPARATUS_REVISION,
                "camera_rig_sha256": None,
            }
        ],
    }


def mid_campaign_stop_document(camera_rig_sha256: str) -> dict:
    p00_id = "P00-R01-A00"
    stop_id = "P01-R01-A00"
    reason = "STOP_SAFETY"
    common_preregistration = {
        "plan_id": "E0_PILOT_V1",
        "plan_file": "04_GEOMETRY_AND_PILOT_PROTOCOL.md",
        "plan_sha256": digest("frozen-pilot-protocol"),
    }
    return {
        "schema_id": "YPS-E0-ACQUISITION-LEDGER-1.1",
        "data_origin": "SYNTHETIC_REAL_SHAPE_FIXTURE",
        "contains_measured_values": False,
        "campaign_id": "SYNTHETIC_MID_CAMPAIGN_STOP",
        "campaign_status": "HARD_STOPPED",
        "preregistration": common_preregistration,
        "apparatus_revision": APPARATUS_REVISION,
        "planned_slots": [
            {
                "slot_id": "P00",
                "repeat_index": 1,
                "operation": "calibration_board_and_sync_flash_batch_start",
                "release_target_id": "NO_RELEASE_CALIBRATION",
                "state": "COMPLETED",
                "disposition_reason_code": None,
                "governing_attempt_id": None,
                "linked_attempt_ids": [p00_id],
            },
            {
                "slot_id": "P01",
                "repeat_index": 1,
                "operation": "static_rig_recording_60_s",
                "release_target_id": "NO_RELEASE_STATIC",
                "state": "FAILED_FINAL",
                "disposition_reason_code": reason,
                "governing_attempt_id": stop_id,
                "linked_attempt_ids": [stop_id],
            },
            {
                "slot_id": "P01",
                "repeat_index": 2,
                "operation": "static_rig_recording_60_s",
                "release_target_id": "NO_RELEASE_STATIC",
                "state": "NOT_STARTED_DUE_TO_STOP",
                "disposition_reason_code": reason,
                "governing_attempt_id": stop_id,
                "linked_attempt_ids": [],
            },
            {
                "slot_id": "P02",
                "repeat_index": 1,
                "operation": "small_near_fast_mode_release",
                "release_target_id": "PILOT_FAST_SMALL",
                "state": "NOT_STARTED_DUE_TO_STOP",
                "disposition_reason_code": reason,
                "governing_attempt_id": stop_id,
                "linked_attempt_ids": [],
            },
        ],
        "attempts": [
            {
                "slot_id": "P00",
                "attempt_id": p00_id,
                "repeat_index": 1,
                "operation": "calibration_board_and_sync_flash_batch_start",
                "release_target_id": "NO_RELEASE_CALIBRATION",
                "status": "COMPLETED",
                "started_at": "2030-01-01T00:00:00Z",
                "ended_at": "2030-01-01T00:00:10Z",
                "operator_id": "SYNTHETIC_OPERATOR",
                "raw_files": [
                    {
                        "path": "calibration_board.mp4",
                        "media_type": "video/mp4",
                        "sha256": digest("p00-calibration-video"),
                    }
                ],
                "evidence_state": "COMPLETE_RAW_DATA_RETAINED",
                "failure": None,
                "retry_parent_id": None,
                "corrective_action": None,
                "apparatus_revision": APPARATUS_REVISION,
                "camera_rig_sha256": camera_rig_sha256,
            },
            {
                "slot_id": "P01",
                "attempt_id": stop_id,
                "repeat_index": 1,
                "operation": "static_rig_recording_60_s",
                "release_target_id": "NO_RELEASE_STATIC",
                "status": "FAILED",
                "started_at": "2030-01-01T00:01:00Z",
                "ended_at": "2030-01-01T00:01:02Z",
                "operator_id": "SYNTHETIC_OPERATOR",
                "raw_files": [],
                "evidence_state": "NO_RAW_DATA_CREATED",
                "failure": {
                    "stage": "SAFETY",
                    "reason_code": reason,
                    "occurred_at": "2030-01-01T00:01:02Z",
                    "operator_note": "A synthetic safety stop occurred before recording began.",
                },
                "retry_parent_id": None,
                "corrective_action": "End the campaign and record all later slots as not started.",
                "apparatus_revision": APPARATUS_REVISION,
                "camera_rig_sha256": camera_rig_sha256,
            },
        ],
    }


def trajectory_truth() -> dict[str, np.ndarray]:
    time = np.linspace(0.0, 8.0, 401)
    q_fast = 0.055 * np.exp(-0.020 * time) * np.cos(4.2 * time + 0.2)
    q_slow = 0.035 * np.exp(-0.012 * time) * np.cos(2.8 * time - 0.3)
    modal_basis = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    bob = (
        np.array([0.0, 0.0, 2.0])
        + q_fast[:, None] * modal_basis[0]
        + q_slow[:, None] * modal_basis[1]
    )
    junction = (
        np.array([0.0, 0.0, 1.72])
        + 0.45 * q_fast[:, None] * modal_basis[0]
        + 0.30 * q_slow[:, None] * modal_basis[1]
    )
    return {
        "time_s": time,
        "q_fast_m": q_fast,
        "q_slow_m": q_slow,
        "modal_basis_W": modal_basis,
        "r_bob_W_m": bob,
        "r_junction_W_m": junction,
    }


def detection_arrays(camera_rig: dict) -> tuple[dict[str, np.ndarray], dict[str, str]]:
    truth = trajectory_truth()
    points = np.stack((truth["r_bob_W_m"], truth["r_junction_W_m"]), axis=1)
    sample_count, marker_count, _ = points.shape
    pixels = np.empty((sample_count, 2, marker_count, 2), dtype=float)
    valid = np.empty((sample_count, 2, marker_count), dtype=bool)
    for camera_index, camera in enumerate(camera_rig["cameras"]):
        projected, projected_valid, _ = project_points(points.reshape(-1, 3), camera)
        pixels[:, camera_index] = projected.reshape(sample_count, marker_count, 2)
        valid[:, camera_index] = projected_valid.reshape(sample_count, marker_count)
    covariance = np.zeros((sample_count, 2, marker_count, 2, 2), dtype=float)
    covariance[..., 0, 0] = 0.04
    covariance[..., 1, 1] = 0.04
    aligned_time = np.repeat(truth["time_s"][:, None], 2, axis=1)
    invalid_reason = np.where(valid, "VALID", "OUTSIDE_CALIBRATION_DOMAIN")
    arrays = {
        "time_s": truth["time_s"],
        "frame_index": np.repeat(np.arange(sample_count, dtype=np.int64)[:, None], 2, axis=1),
        "raw_timestamp_s": aligned_time.copy(),
        "aligned_timestamp_s": aligned_time.copy(),
        "sync_event_id": np.full((sample_count, 2), "SYNTHETIC_COMMON_EVENT"),
        "sync_offset_s": np.zeros((sample_count, 2), dtype=float),
        "sync_uncertainty_s": np.full((sample_count, 2), 2.0e-5),
        "dropped_frame_flag": np.zeros((sample_count, 2), dtype=bool),
        "pixels_px": pixels,
        "pixel_covariance_px2": covariance,
        "valid_mask": valid,
        "occlusion_mask": np.zeros_like(valid),
        "detection_score": np.full(valid.shape, 0.99),
        "invalid_reason": invalid_reason,
    }
    units = {
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
    return arrays, units


def measurement_record_hash(document: dict, measurement_ids: list[str]) -> str:
    by_id = {record["measurement_id"]: record for record in document["measurements"]}
    return sha256_document([by_id[measurement_id] for measurement_id in measurement_ids])

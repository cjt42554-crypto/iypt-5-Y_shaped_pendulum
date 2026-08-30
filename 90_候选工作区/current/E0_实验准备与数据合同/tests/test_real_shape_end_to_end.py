from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from real_shape_fixture import (
    APPARATUS_REVISION,
    acquisition_document,
    apparatus_document,
    camera_rig_document,
    detection_arrays,
    digest,
    measurement_record_hash,
    trajectory_truth,
)

from yps_experiment_pipeline.camera import validate_camera
from yps_experiment_pipeline.contracts import (
    ContractError,
    canonical_json_bytes,
    sha256_document,
    sha256_file,
    validate_document,
)
from yps_experiment_pipeline.detections import (
    triangulate_markers_with_covariance,
    write_detection_bundle,
)
from yps_experiment_pipeline.forward_adapter import (
    TORUS_READY,
    FormalAdapterError,
    model_input_binding,
    torus_compatibility,
)
from yps_experiment_pipeline.observables import (
    estimate_damped_mode,
    normalized_closure_error,
    resonant_phase,
    write_common_observables,
)
from yps_experiment_pipeline.trajectory import write_bundle

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def test_synthetic_real_shape_fixture_closes_the_provenance_chain(tmp_path: Path):
    apparatus = apparatus_document()
    validate_document("apparatus_measurements.schema.json", apparatus)
    measurement_ids = {record["measurement_id"] for record in apparatus["measurements"]}
    assert {
        "SUPPORT_A_XYZ",
        "SUPPORT_B_XYZ",
        "BOB_COM_TO_ATTACHMENT",
        "BOB_PRINCIPAL_INERTIA",
    } <= measurement_ids

    camera_rig = camera_rig_document()
    validate_document("camera_rig.schema.json", camera_rig)
    for camera in camera_rig["cameras"]:
        validate_camera(camera)
        assert np.asarray(camera["R_c"]).shape == (3, 3)
    camera_rig_hash = sha256_document(camera_rig)

    attempts = acquisition_document(camera_rig_hash)
    validate_document("acquisition_attempts.schema.json", attempts)
    completed_repeats = {
        attempt["repeat_index"]
        for attempt in attempts["attempts"]
        if attempt["status"] == "COMPLETED"
    }
    assert completed_repeats == {1, 2}
    retry = next(
        attempt for attempt in attempts["attempts"] if attempt["attempt_id"].endswith("A01")
    )
    assert retry["retry_parent_id"] == "P02-R02-A00"

    detection_values, detection_units = detection_arrays(camera_rig)
    detection_directory = tmp_path / "detections"
    detection_manifest = write_detection_bundle(
        detection_directory,
        run_id="SYNTHETIC_P02_REPEAT_02_RETRY",
        attempt_id="P02-R02-A01",
        apparatus_revision=APPARATUS_REVISION,
        data_origin="SYNTHETIC_REAL_SHAPE_FIXTURE",
        camera_rig_file="camera_rig.json",
        camera_rig_sha256=camera_rig_hash,
        raw_video_files=[
            {
                "camera_id": "CAM_A",
                "path": "cam_a_repeat_02_retry.mp4",
                "sha256": digest("video-a-r2-retry"),
            },
            {
                "camera_id": "CAM_B",
                "path": "cam_b_repeat_02_retry.mp4",
                "sha256": digest("video-b-r2-retry"),
            },
        ],
        detector={
            "name": "SYNTHETIC_KNOWN_PROJECTION",
            "version": "1.0",
            "configuration_sha256": digest("synthetic-detector-configuration"),
        },
        camera_ids=["CAM_A", "CAM_B"],
        marker_ids=["BOB", "JUNCTION"],
        arrays=detection_values,
        units=detection_units,
    )
    validate_document("detection_2d_bundle.schema.json", detection_manifest)

    reconstructed, covariance_3d, valid_3d = triangulate_markers_with_covariance(
        detection_values["pixels_px"],
        detection_values["pixel_covariance_px2"],
        detection_values["valid_mask"],
        camera_rig["cameras"][0],
        camera_rig["cameras"][1],
    )
    truth = trajectory_truth()
    expected = np.stack((truth["r_bob_W_m"], truth["r_junction_W_m"]), axis=1)
    assert np.all(valid_3d)
    np.testing.assert_allclose(reconstructed, expected, rtol=0.0, atol=2e-9)
    assert float(np.min(np.linalg.eigvalsh(covariance_3d))) >= -1e-12

    support_a = next(
        record["value_si"]
        for record in apparatus["measurements"]
        if record["measurement_id"] == "SUPPORT_A_XYZ"
    )
    support_b = next(
        record["value_si"]
        for record in apparatus["measurements"]
        if record["measurement_id"] == "SUPPORT_B_XYZ"
    )
    sample_count = truth["time_s"].size
    branch_markers = np.empty((sample_count, 3, 3), dtype=float)
    branch_markers[:, 0] = support_a
    branch_markers[:, 1] = support_b
    branch_markers[:, 2] = reconstructed[:, 1]
    trajectory_arrays = {
        "time_s": truth["time_s"],
        "r_bob_W_m": reconstructed[:, 0],
        "r_junction_W_m": reconstructed[:, 1],
        "branch_marker_positions_W_m": branch_markers,
        "bob_orientation_WB": np.repeat(np.eye(3)[None, :, :], sample_count, axis=0),
        "position_covariance": covariance_3d,
        "valid_mask": np.all(valid_3d, axis=1),
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
    detection_manifest_file = detection_directory / "detection_2d_bundle.json"
    trajectory_manifest = write_bundle(
        trajectory_directory,
        run_id="SYNTHETIC_P02_REPEAT_02_RETRY",
        attempt_id="P02-R02-A01",
        apparatus_revision=APPARATUS_REVISION,
        data_origin="SYNTHETIC_REAL_SHAPE_FIXTURE",
        detection_manifest_file=detection_manifest_file,
        camera_rig_sha256=camera_rig_hash,
        arrays=trajectory_arrays,
        units=trajectory_units,
        valid_mask=trajectory_arrays["valid_mask"],
        event_codes=[],
    )
    validate_document("trajectory_bundle.schema.json", trajectory_manifest)
    assert trajectory_manifest["detection_manifest_sha256"] == sha256_file(detection_manifest_file)

    reconstructed_fast = (reconstructed[:, 0] - np.array([0.0, 0.0, 2.0])) @ truth["modal_basis_W"][
        0
    ]
    reconstructed_slow = (reconstructed[:, 0] - np.array([0.0, 0.0, 2.0])) @ truth["modal_basis_W"][
        1
    ]
    fast = estimate_damped_mode(truth["time_s"], reconstructed_fast)
    slow = estimate_damped_mode(truth["time_s"], reconstructed_slow)
    phase = resonant_phase(
        fast.omega_rad_s * truth["time_s"] + fast.phase_rad,
        slow.omega_rad_s * truth["time_s"] + slow.phase_rad,
        p=3,
        q=2,
    )
    common_arrays = {
        "time_s": truth["time_s"],
        "r_bob_W_m": reconstructed[:, 0],
        "r_junction_W_m": reconstructed[:, 1],
        "modal_basis_W": truth["modal_basis_W"],
        "q_fast_m": reconstructed_fast,
        "q_slow_m": reconstructed_slow,
        "resonant_phase_rad": phase,
        "valid_mask": trajectory_arrays["valid_mask"],
    }
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
    trajectory_manifest_file = trajectory_directory / "trajectory_bundle.json"
    common_manifest = write_common_observables(
        tmp_path / "common",
        data_origin="SYNTHETIC_REAL_SHAPE_FIXTURE",
        identity={
            "source_id": "SYNTHETIC_P02_REPEAT_02_RETRY",
            "source_sha256": sha256_file(trajectory_manifest_file),
            "run_id": "SYNTHETIC_P02_REPEAT_02_RETRY",
            "apparatus_revision": APPARATUS_REVISION,
        },
        trajectory_manifest_file=trajectory_manifest_file,
        arrays=common_arrays,
        units=common_units,
        modal_basis_provenance={
            "method": "SYNTHETIC_PREREGISTERED_ORTHONORMAL_BASIS",
            "method_sha256": digest("synthetic-modal-basis-method"),
            "source_run_ids": ["SYNTHETIC_P02_REPEAT_01", "SYNTHETIC_P03_REPEAT_01"],
            "source_bundle_sha256": [
                digest("synthetic-fast-basis-run"),
                digest("synthetic-slow-basis-run"),
            ],
            "basis_frozen_before_run": True,
        },
        fast=fast,
        slow=slow,
        closure_error=normalized_closure_error(
            np.array([reconstructed_fast[0], reconstructed_slow[0]]),
            np.array([reconstructed_fast[-1], reconstructed_slow[-1]]),
            1.0,
        ),
        events=[],
        uncertainty={
            "method": "SYNTHETIC_2D_TO_3D_COVARIANCE_PROPAGATION",
            "components": {"pixel_localization_px": 0.2},
            "covariance_ref": "trajectory.npz",
            "covariance_sha256": trajectory_manifest["array_sha256"],
        },
        domain_status="IN_DOMAIN",
    )
    validate_document("processed_observables.schema.json", common_manifest)
    assert common_manifest["fields"]["modal_basis_W"]["shape"] == [2, 3]

    measurement_bundle_hash = sha256_document(apparatus)
    trajectory_bundle_hash = sha256_file(trajectory_manifest_file)
    parameter_measurements = ["SUPPORT_A_XYZ", "SUPPORT_B_XYZ", "BOB_COM_TO_ATTACHMENT"]
    parameter_bindings = [
        {
            "parameter_name": "geometry_embedding",
            "source_type": "SYNTHETIC_REAL_SHAPE_FIXTURE",
            "measurement_ids": parameter_measurements,
            "measurement_bundle_sha256": measurement_bundle_hash,
            "source_record_sha256": measurement_record_hash(apparatus, parameter_measurements),
            "derivation_sha256": None,
        }
    ]
    compatibility_evidence = {
        "torus": {
            "geometry_embedding": {
                "decision": True,
                "evidence_sha256": digest("geometry-embedding-evidence"),
            },
            "initial_state_mapping": {
                "decision": True,
                "evidence_sha256": digest("initial-state-evidence"),
            },
            "domain_window": {
                "decision": True,
                "evidence_sha256": digest("domain-window-evidence"),
            },
            "mapping_residual": 2.0e-5,
            "mapping_standard_uncertainty": 8.0e-5,
        },
        "cable": None,
    }
    assert torus_compatibility({"compatibility_evidence": compatibility_evidence}) == TORUS_READY
    binding = model_input_binding(
        REPOSITORY_ROOT,
        model_id="FWD-TORUS-1.0",
        purpose="SYNTHETIC_CONTRACT_TEST",
        measurement_document=apparatus,
        measurement_bundle_sha256=measurement_bundle_hash,
        trajectory_bundle_sha256=trajectory_bundle_hash,
        parameter_bindings=parameter_bindings,
        compatibility_evidence=compatibility_evidence,
        compatibility_status=TORUS_READY,
        missing_fields=[],
    )
    validate_document("model_input_binding.schema.json", binding)
    assert binding["measurement_bundle_sha256"] == sha256_document(apparatus)
    assert binding["trajectory_bundle_sha256"] == sha256_file(trajectory_manifest_file)


def test_measured_contracts_cannot_retain_unset_or_missing_provenance():
    document = apparatus_document()
    document["data_origin"] = "MEASURED_BUNDLE"
    document["apparatus_revision"] = "REAL_RIG_V1"
    for record in document["measurements"]:
        record["source_type"] = "MEASURED"
    document["measurements"][0]["calibration_ref"] = "UNSET_REQUIRES_HUMAN"
    with pytest.raises(ContractError, match="UNSET_REQUIRES_HUMAN"):
        validate_document("apparatus_measurements.schema.json", document)

    no_uncertainty = deepcopy(document)
    no_uncertainty["measurements"][0]["calibration_ref"] = "REAL_CALIBRATION"
    no_uncertainty["measurements"][0]["combined_standard_uncertainty"] = None
    with pytest.raises(ContractError, match="combined_standard_uncertainty"):
        validate_document("apparatus_measurements.schema.json", no_uncertainty)

    no_raw_hash = deepcopy(document)
    no_raw_hash["measurements"][0]["calibration_ref"] = "REAL_CALIBRATION"
    no_raw_hash["measurements"][0]["raw_data_sha256"] = None
    with pytest.raises(ContractError, match="raw_data_sha256"):
        validate_document("apparatus_measurements.schema.json", no_raw_hash)

    non_psd = apparatus_document()
    non_psd["measurements"][0]["covariance_si"] = [
        [-1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    with pytest.raises(ContractError, match="positive semidefinite"):
        validate_document("apparatus_measurements.schema.json", non_psd)


def test_source_labels_cannot_be_substituted_for_measurement_evidence():
    apparatus = apparatus_document()
    bundle_hash = sha256_document(apparatus)
    compatibility_evidence = {
        "torus": {
            "geometry_embedding": {"decision": True, "evidence_sha256": digest("geometry")},
            "initial_state_mapping": {"decision": True, "evidence_sha256": digest("initial")},
            "domain_window": {"decision": True, "evidence_sha256": digest("domain")},
            "mapping_residual": 0.0,
            "mapping_standard_uncertainty": 1.0e-4,
        },
        "cable": None,
    }
    fake_binding = {
        "parameter_name": "geometry_embedding",
        "source_type": "MEASURED",
        "measurement_ids": ["SUPPORT_A_XYZ"],
        "measurement_bundle_sha256": bundle_hash,
        "source_record_sha256": measurement_record_hash(apparatus, ["SUPPORT_A_XYZ"]),
        "derivation_sha256": None,
    }
    with pytest.raises(FormalAdapterError, match="non-measured"):
        model_input_binding(
            REPOSITORY_ROOT,
            model_id="FWD-TORUS-1.0",
            purpose="EXPERIMENT_COMPARISON",
            measurement_document=apparatus,
            measurement_bundle_sha256=bundle_hash,
            trajectory_bundle_sha256=digest("trajectory"),
            parameter_bindings=[fake_binding],
            compatibility_evidence=compatibility_evidence,
            compatibility_status=TORUS_READY,
            missing_fields=[],
        )


def test_attempt_retry_parent_and_camera_completion_fail_closed():
    camera_rig = camera_rig_document()
    camera_hash = sha256_document(camera_rig)
    attempts = acquisition_document(camera_hash)
    attempts["attempts"][-1]["retry_parent_id"] = "ABSENT_ATTEMPT"
    with pytest.raises(ContractError, match="retry parent"):
        validate_document("acquisition_attempts.schema.json", attempts)

    measured_rig = camera_rig_document()
    measured_rig["data_origin"] = "MEASURED_CALIBRATION"
    measured_rig["apparatus_revision"] = "REAL_RIG_V1"
    for camera in measured_rig["cameras"]:
        camera["source_type"] = "MEASURED"
    measured_rig["synchronization"]["method"] = "COMMON_FLASH"
    measured_rig["cameras"][0]["R_c"] = None
    with pytest.raises(ContractError, match="R_c"):
        validate_document("camera_rig.schema.json", measured_rig)


def test_detection_covariance_must_be_symmetric_before_bundle_creation(tmp_path: Path):
    camera_rig = camera_rig_document()
    arrays, units = detection_arrays(camera_rig)
    arrays["pixel_covariance_px2"][0, 0, 0, 0, 1] = 0.1
    output = tmp_path / "invalid_detection"
    with pytest.raises(ValueError, match="symmetric"):
        write_detection_bundle(
            output,
            run_id="INVALID",
            attempt_id="INVALID",
            apparatus_revision=APPARATUS_REVISION,
            data_origin="SYNTHETIC_REAL_SHAPE_FIXTURE",
            camera_rig_file="camera_rig.json",
            camera_rig_sha256=sha256_document(camera_rig),
            raw_video_files=[
                {"camera_id": "CAM_A", "path": "a.mp4", "sha256": digest("a")},
                {"camera_id": "CAM_B", "path": "b.mp4", "sha256": digest("b")},
            ],
            detector={
                "name": "INVALID_COVARIANCE_TEST",
                "version": "1.0",
                "configuration_sha256": digest("invalid-covariance-test"),
            },
            camera_ids=["CAM_A", "CAM_B"],
            marker_ids=["BOB", "JUNCTION"],
            arrays=arrays,
            units=units,
        )
    assert not output.exists()


def test_irregular_sampling_is_not_silently_treated_as_uniform():
    time = np.linspace(0.0, 4.0, 401)
    time[200:] += 0.006
    signal = np.cos(3.0 * time)
    with pytest.raises(ValueError, match="irregular sampling"):
        estimate_damped_mode(time, signal)


def test_canonical_fixture_documents_do_not_claim_measured_values():
    apparatus = apparatus_document()
    camera_rig = camera_rig_document()
    attempts = acquisition_document(sha256_document(camera_rig))
    encoded = b"\n".join(
        canonical_json_bytes(document) for document in (apparatus, camera_rig, attempts)
    )
    assert b'"data_origin":"MEASURED' not in encoded
    assert b'"source_type":"MEASURED"' not in encoded

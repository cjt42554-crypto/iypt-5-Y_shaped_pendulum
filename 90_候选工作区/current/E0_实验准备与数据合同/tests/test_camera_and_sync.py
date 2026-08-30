import importlib
from pathlib import Path

import numpy as np
import pytest

from yps_experiment_pipeline.camera import (
    CameraContractError,
    project_points,
    triangulate_two_view,
    validate_camera,
)
from yps_experiment_pipeline.forward_adapter import load_formal_forward
from yps_experiment_pipeline.synchronization import align_timestamps, estimate_event_offset

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def camera(center_x: float) -> dict:
    return {
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
    }


def test_projection_matches_formal_brown_conrady_operator():
    load_formal_forward(REPOSITORY_ROOT)
    formal_observations = importlib.import_module("y_pendulum_forward.observations")
    points = np.array([[0.1, -0.05, 2.0], [-0.08, 0.06, 2.2]])
    local_camera = camera(-0.2)
    pixels, valid, _ = project_points(points, local_camera)
    spec = {
        "type": "camera_brown_conrady",
        **local_camera,
        "t0": 0.0,
        "record_times": [0.0, 1.0],
    }

    def position_at(times):
        return points[np.asarray(times, dtype=int)]

    formal = formal_observations.evaluate_observations(
        spec,
        position_at=position_at,
        interval_end=1.0,
        completed=True,
        e_z=np.array([0.0, 0.0, 1.0]),
        event_time_tolerance=1e-12,
    )
    np.testing.assert_array_equal(valid, formal["valid_mask"])
    np.testing.assert_allclose(pixels, formal["values"], rtol=0.0, atol=1e-12)


def test_two_view_reconstruction_recovers_synthetic_trajectory():
    time = np.linspace(0.0, 5.0, 251)
    points = np.column_stack(
        (0.09 * np.sin(time), 0.07 * np.cos(1.3 * time), 2.0 + 0.04 * np.sin(0.7 * time))
    )
    camera_a, camera_b = camera(-0.25), camera(0.25)
    pixels_a, valid_a, _ = project_points(points, camera_a)
    pixels_b, valid_b, _ = project_points(points, camera_b)
    reconstructed, valid = triangulate_two_view(
        pixels_a,
        pixels_b,
        camera_a,
        camera_b,
        valid_a=valid_a,
        valid_b=valid_b,
    )
    assert np.all(valid)
    np.testing.assert_allclose(reconstructed, points, rtol=0.0, atol=1e-9)


def test_camera_and_triangulation_fail_closed_outside_physical_domain():
    invalid_camera = camera(-0.25)
    invalid_camera["k1"] = float("nan")
    with pytest.raises(CameraContractError, match="finite"):
        validate_camera(invalid_camera)

    point = np.array([[0.0, 0.0, 2.0]])
    camera_a, camera_b = camera(-0.25), camera(0.25)
    pixels_a, _, _ = project_points(point, camera_a)
    pixels_b, _, _ = project_points(point, camera_b)
    _, valid = triangulate_two_view(pixels_b, pixels_a, camera_a, camera_b)
    assert not valid[0]


def test_common_event_offset_is_recovered_and_applied():
    reference = np.array([0.2, 1.0, 2.5, 4.8])
    shifted = reference + 0.012
    estimate = estimate_event_offset(reference, shifted)
    assert estimate["offset_s"] == pytest.approx(0.012, abs=1e-14)
    np.testing.assert_allclose(align_timestamps(shifted, estimate["offset_s"]), reference)

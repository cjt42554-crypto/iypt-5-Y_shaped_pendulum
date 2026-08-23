from __future__ import annotations

import unittest

import numpy as np

from y_pendulum_forward.observations import evaluate_observations


class ObservationTests(unittest.TestCase):
    def test_camera_partial_domain_is_reported_per_sample(self):
        spec = {
            "type": "camera_brown_conrady",
            "R_c": np.eye(3).tolist(),
            "c_c": [0, 0, 0],
            "f_x": 100,
            "f_y": 100,
            "c_x": 320,
            "c_y": 240,
            "k1": 0,
            "k2": 0,
            "k3": 0,
            "p1": 0,
            "p2": 0,
            "Omega_cal": [-1, 1, -1, 1],
            "t0": 0,
            "record_times": [0, 1, 2],
        }

        def positions(times):
            table = np.array([[0.1, 0.2, 1.0], [0.1, 0.2, -1.0], [2.0, 0.0, 1.0]])
            return table[np.asarray(times, dtype=int)]

        result = evaluate_observations(
            spec,
            position_at=positions,
            interval_end=2,
            completed=True,
            e_z=np.array([0, 0, 1.0]),
            event_time_tolerance=1e-8,
        )
        np.testing.assert_array_equal(result["valid_mask"], [True, False, False])
        self.assertEqual(result["status"], ["OBSERVATION_INPUT_VALID"])
        self.assertEqual(len(result["errors"]), 2)

    def test_invalid_camera_does_not_call_physical_state(self):
        called = False

        def positions(_times):
            nonlocal called
            called = True
            return np.empty((0, 3))

        result = evaluate_observations(
            {"type": "camera_brown_conrady", "t0": 0, "record_times": []},
            position_at=positions,
            interval_end=1,
            completed=True,
            e_z=np.array([0, 0, 1.0]),
            event_time_tolerance=1e-8,
        )
        self.assertEqual(result["status"], ["INVALID_OBSERVATION_INPUT"])
        self.assertFalse(called)

    def test_nonfinite_distortion_output_is_never_marked_valid(self):
        spec = {
            "type": "camera_brown_conrady",
            "R_c": np.eye(3).tolist(),
            "c_c": [0.0, 0.0, 0.0],
            "f_x": 1e308,
            "f_y": 1e308,
            "c_x": 0.0,
            "c_y": 0.0,
            "k1": 1e308,
            "k2": 1e308,
            "k3": 1e308,
            "p1": 1e308,
            "p2": 1e308,
            "Omega_cal": [-1e200, 1e200, -1e200, 1e200],
            "t0": 0.0,
            "record_times": [0.0],
        }
        result = evaluate_observations(
            spec,
            position_at=lambda _times: np.array([[1e100, 0.0, 1.0]]),
            interval_end=0.0,
            completed=True,
            e_z=np.array([0.0, 0.0, 1.0]),
            event_time_tolerance=1e-8,
        )
        self.assertEqual(result["status"], ["OBSERVATION_INPUT_VALID"])
        self.assertFalse(bool(result["valid_mask"][0]))
        self.assertTrue(
            any(
                error["code"] == "OBSERVATION_NUMERICAL_NONFINITE"
                for error in result["errors"]
            )
        )


if __name__ == "__main__":
    unittest.main()

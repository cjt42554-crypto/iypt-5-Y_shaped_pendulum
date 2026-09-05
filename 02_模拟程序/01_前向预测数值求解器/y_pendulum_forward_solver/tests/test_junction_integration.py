"""Public-entry and serialization regression for the third physical model."""

from copy import deepcopy
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from y_pendulum_forward.contracts import (
    JUNCTION_THEORY_SHA256,
    THEORY_SHA256,
    load_json,
)
from y_pendulum_forward.io import write_result
from y_pendulum_forward.runner import run_config


PROJECT = Path(__file__).resolve().parents[1]


def short_junction():
    config = load_json(PROJECT / "configs/junction_example.json")
    config["physical"]["T"] = 0.04
    config["observation"] = None
    config["numerics"]["output_dt"] = 0.002
    return config


class JunctionIntegrationTests(unittest.TestCase):
    def test_public_dispatch_binds_distinct_physical_and_numerical_identity(self):
        config = short_junction()
        result = run_config(config)
        self.assertEqual(result.contract_status, ["COMPLETED"])
        self.assertEqual(result.numerical_status, "SUCCESS_SINGLE_RUN")
        summary = result.summary_dict()
        self.assertEqual(summary["model_id"], "YP-FWD-J3-v1")
        self.assertEqual(summary["theory_sha256"], JUNCTION_THEORY_SHA256)
        self.assertNotEqual(summary["theory_sha256"], THEORY_SHA256)
        self.assertEqual(
            summary["numerical_model_id"], "NUM-YP-FWD-J3-DOP853-1.0"
        )
        self.assertTrue(result.metadata["source_tree_stable_during_run"])
        self.assertEqual(result.metadata["model_id"], config["model_id"])

    def test_export_round_trip_preserves_states_observations_and_energy(self):
        config = short_junction()
        config["observation"] = {
            "type": "orthographic",
            "axis_1": [1.0, 0.0, 0.0],
            "axis_2": [0.0, 1.0, 0.0],
            "t0": 0.0,
            "record_times": {"kind": "uniform", "start": 0.0, "stop": 0.04, "step": 0.002},
        }
        result = run_config(config)
        self.assertEqual(result.numerical_status, "SUCCESS_SINGLE_RUN")
        with tempfile.TemporaryDirectory() as temporary:
            output = write_result(Path(temporary) / "j3", config, result, plots=False)
            summary = json.loads((output / "result.json").read_text())
            snapshot = load_json(output / "config.snapshot.json")
            self.assertEqual(snapshot, config)
            self.assertEqual(summary["theory_sha256"], config["theory_sha256"])
            with np.load(output / "trajectory.npz", allow_pickle=False) as arrays:
                np.testing.assert_array_equal(arrays["state__X_junction"], result.state["X_junction"])
                np.testing.assert_array_equal(arrays["derived__E_junction"], result.derived["E_junction"])
                np.testing.assert_allclose(arrays["observations__values"], arrays["state__r_m"][:, :2], atol=1e-12)
                self.assertNotIn("derived__branches", arrays.files)
                self.assertNotIn("state__X_torus", arrays.files)
            with (output / "series.csv").open(newline="") as handle:
                rows = csv.DictReader(handle)
                self.assertIn("E_junction", rows.fieldnames)
                self.assertIn("r_J_x", rows.fieldnames)
                self.assertIn("T_lower", rows.fieldnames)
                self.assertEqual(len(list(rows)), result.time.size)

    def test_omitted_numerics_records_actual_default_integrator(self):
        config = short_junction()
        del config["numerics"]
        result = run_config(config)
        self.assertEqual(result.numerical_status, "SUCCESS_SINGLE_RUN")
        self.assertEqual(result.metadata["integrator"], "DOP853")
        self.assertEqual(
            result.metadata["numerical_model_id"], "NUM-YP-FWD-J3-DOP853-1.0"
        )

    def test_output_sampling_does_not_change_physical_identity_or_integration(self):
        fine = short_junction()
        coarse = deepcopy(fine)
        coarse["numerics"]["output_dt"] *= 2
        fine_result, coarse_result = run_config(fine), run_config(coarse)
        self.assertEqual(fine_result.numerical_status, "SUCCESS_SINGLE_RUN")
        self.assertEqual(coarse_result.numerical_status, "SUCCESS_SINGLE_RUN")
        self.assertEqual(fine_result.metadata["physical_input_sha256"], coarse_result.metadata["physical_input_sha256"])
        self.assertNotEqual(fine_result.metadata["numerical_config_sha256"], coarse_result.metadata["numerical_config_sha256"])
        np.testing.assert_allclose(fine_result.time[::2], coarse_result.time, atol=1e-15)
        np.testing.assert_allclose(fine_result.state["X_junction"][::2], coarse_result.state["X_junction"], rtol=1e-12, atol=1e-13)

    def test_legacy_theory_hash_is_not_accepted_as_junction_identity(self):
        config = short_junction()
        config["theory_sha256"] = THEORY_SHA256
        result = run_config(config)
        self.assertEqual(result.numerical_status, "INPUT_REJECTED")
        self.assertEqual(result.time.size, 0)
        self.assertIn("THEORY_IDENTITY", str(result.events))

    def test_junction_hash_does_not_relabel_old_models(self):
        for name in ("torus", "cable"):
            with self.subTest(model=name):
                config = load_json(PROJECT / f"configs/{name}_example.json")
                config["theory_sha256"] = JUNCTION_THEORY_SHA256
                result = run_config(config)
                self.assertEqual(result.numerical_status, "INPUT_REJECTED")
                self.assertEqual(result.time.size, 0)

    def test_unknown_model_is_rejected_without_a_curve(self):
        config = short_junction()
        config["model_id"] = "YP-FWD-J3-UNKNOWN"
        config["theory_sha256"] = THEORY_SHA256
        result = run_config(config)
        self.assertEqual(result.numerical_status, "INPUT_REJECTED")
        self.assertEqual(result.time.size, 0)
        self.assertIn("MODEL_ID", str(result.events))

    def test_cli_runs_and_exports_junction_from_same_public_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "j3.json"
            path.write_text(json.dumps(short_junction()))
            output = root / "export"
            completed = subprocess.run(
                [sys.executable, str(PROJECT / "run.py"), "run", str(path), "--output", str(output), "--no-plots"],
                cwd=temporary,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            summary = json.loads((output / "result.json").read_text())
            self.assertEqual(summary["model_id"], "YP-FWD-J3-v1")
            self.assertEqual(summary["contract_status"], ["COMPLETED"])


if __name__ == "__main__":
    unittest.main()

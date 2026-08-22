from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from y_pendulum_forward.contracts import load_json
from y_pendulum_forward.io import write_result
from y_pendulum_forward.runner import run_config


ROOT = Path(__file__).resolve().parents[1]


class IOTests(unittest.TestCase):
    def test_result_round_trip_contains_identity_and_arrays(self):
        config = load_json(ROOT / "configs" / "torus_example.json")
        config = deepcopy(config)
        config["physical"]["T"] = 0.02
        config["observation"] = None
        result = run_config(config)
        with tempfile.TemporaryDirectory() as directory:
            output = write_result(Path(directory) / "run", config, result, plots=False)
            summary = json.loads((output / "result.json").read_text(encoding="utf-8"))
            arrays = np.load(output / "trajectory.npz")
            self.assertEqual(summary["theory_sha256"], config["theory_sha256"])
            self.assertEqual(
                summary["metadata"]["numerical_model_id"],
                "NUM-FWD-TORUS-DOP853-1.0",
            )
            self.assertEqual(len(summary["metadata"]["source_tree_sha256"]), 64)
            self.assertEqual(len(summary["metadata"]["physical_input_sha256"]), 64)
            self.assertEqual(len(summary["metadata"]["numerical_config_sha256"]), 64)
            self.assertEqual(len(summary["metadata"]["observation_input_sha256"]), 64)
            self.assertIn("state__X_torus", arrays.files)
            self.assertIn("derived__E_torus", arrays.files)

    def test_cable_algebraic_reactions_live_in_diagnostics_not_derived(self):
        config = load_json(ROOT / "configs" / "cable_example.json")
        config = deepcopy(config)
        config["physical"]["T"] = 0.005
        config["numerics"]["elements"] = {"A": 2, "B": 2, "lower": 2}
        config["numerics"]["max_step"] = 0.0005
        config["numerics"]["output_dt"] = 0.001
        config["observation"] = None
        result = run_config(config)
        self.assertNotIn("reaction_algebraic_A", result.derived)
        self.assertNotIn("P_base_algebraic", result.derived)
        self.assertIn("reaction_algebraic", result.diagnostics)
        with tempfile.TemporaryDirectory() as directory:
            output = write_result(
                Path(directory) / "run", config, result, plots=False
            )
            arrays = np.load(output / "trajectory.npz")
            self.assertIn("diagnostics__reaction_algebraic__A", arrays.files)
            self.assertIn("diagnostics__P_base_algebraic", arrays.files)

    def test_nonempty_unknown_output_directory_is_not_overwritten(self):
        config = load_json(ROOT / "configs" / "torus_example.json")
        config = deepcopy(config)
        config["physical"]["T"] = 0.01
        config["observation"] = None
        result = run_config(config)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            output.mkdir()
            (output / "user-data.txt").write_text("preserve", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_result(output, config, result, overwrite=True, plots=False)
            self.assertEqual((output / "user-data.txt").read_text(encoding="utf-8"), "preserve")

    def test_writer_rejects_config_mutated_after_run(self):
        config = load_json(ROOT / "configs" / "torus_example.json")
        config = deepcopy(config)
        config["physical"]["T"] = 0.01
        config["observation"] = None
        result = run_config(config)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            write_result(output, config, result, plots=False)
            before = {
                path.name: path.read_bytes()
                for path in output.iterdir()
                if path.is_file()
            }
            config["physical"]["mass"] *= 2.0
            with self.assertRaises(ValueError):
                write_result(
                    output,
                    config,
                    result,
                    overwrite=True,
                    plots=False,
                )
            after = {
                path.name: path.read_bytes()
                for path in output.iterdir()
                if path.is_file()
            }
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()

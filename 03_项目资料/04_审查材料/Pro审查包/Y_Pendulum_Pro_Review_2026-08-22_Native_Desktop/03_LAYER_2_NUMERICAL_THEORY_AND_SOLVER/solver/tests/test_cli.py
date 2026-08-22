import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "run.py"), *arguments],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_nonstandard_nan_run_input_is_rejected_without_output_or_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "nan.json"
            config.write_text(
                '{"model_id":"FWD-TORUS-1.0","metadata":NaN}',
                encoding="utf-8",
            )
            output = root / "should-not-exist"
            completed = self._run(
                "run",
                str(config),
                "--output",
                str(output),
                "--no-plots",
            )
            self.assertEqual(completed.returncode, 2)
            self.assertFalse(output.exists())
            self.assertNotIn("Traceback", completed.stdout + completed.stderr)
            self.assertIn("INPUT_REJECTED", completed.stderr)

    def test_nonstandard_nan_ensemble_is_rejected_without_output_or_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = root / "nan-ensemble.json"
            spec.write_text('{"metadata":NaN}', encoding="utf-8")
            output = root / "should-not-exist"
            completed = self._run(
                "ensemble",
                str(spec),
                "--output",
                str(output),
            )
            self.assertEqual(completed.returncode, 4)
            self.assertFalse(output.exists())
            self.assertNotIn("Traceback", completed.stdout + completed.stderr)
            self.assertIn("INPUT_REJECTED", completed.stderr)

    def test_canonical_invalid_ensemble_is_reported_without_partial_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = root / "invalid-ensemble.json"
            spec.write_text("{}", encoding="utf-8")
            output = root / "should-not-exist"
            completed = self._run(
                "ensemble",
                str(spec),
                "--output",
                str(output),
            )
            self.assertEqual(completed.returncode, 4)
            self.assertFalse(output.exists())
            self.assertNotIn("Traceback", completed.stdout + completed.stderr)
            self.assertIn("INVALID_ENSEMBLE_INPUT", completed.stdout)

    def test_malformed_json_is_a_friendly_input_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "malformed.json"
            config.write_text("{", encoding="utf-8")
            output = root / "should-not-exist"
            completed = self._run(
                "run",
                str(config),
                "--output",
                str(output),
            )
            self.assertEqual(completed.returncode, 2)
            self.assertFalse(output.exists())
            self.assertNotIn("Traceback", completed.stdout + completed.stderr)
            self.assertIn("INPUT_REJECTED", completed.stderr)

    def test_duplicate_json_keys_are_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "duplicate.json"
            config.write_text(
                '{"model_id":"FWD-TORUS-1.0","model_id":"FWD-CABLE-1.0"}',
                encoding="utf-8",
            )
            output = root / "should-not-exist"
            completed = self._run(
                "run",
                str(config),
                "--output",
                str(output),
            )
            self.assertEqual(completed.returncode, 2)
            self.assertFalse(output.exists())
            self.assertNotIn("Traceback", completed.stdout + completed.stderr)
            self.assertIn("duplicate JSON object key", completed.stderr)


if __name__ == "__main__":
    unittest.main()

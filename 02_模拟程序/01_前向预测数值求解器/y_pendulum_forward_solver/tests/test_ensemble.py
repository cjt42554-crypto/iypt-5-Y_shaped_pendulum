from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from y_pendulum_forward.contracts import THEORY_SHA256, load_json
from y_pendulum_forward.ensemble import run_ensemble, write_ensemble


ROOT = Path(__file__).resolve().parents[1]


class EnsembleTests(unittest.TestCase):
    @staticmethod
    def _components():
        return {
            "physical_parameters": {},
            "initial_state": {},
            "numerical_error": {},
            "observation_calibration": {},
            "experimental_noise": {
                "role": "observation-layer descriptor only"
            },
        }

    def _spec(self):
        valid = load_json(ROOT / "configs" / "torus_example.json")
        valid = deepcopy(valid)
        valid["physical"]["T"] = 0.01
        valid["numerics"]["max_step"] = 0.001
        valid["numerics"]["output_dt"] = 0.002
        valid["observation"] = None
        invalid = deepcopy(valid)
        invalid["physical"]["mass"] = -1.0
        return {
            "schema_version": "YPS-FWD-ENSEMBLE-1.0",
            "set_kind": "SAMPLED_PREDICTION_SET",
            "model_id": "FWD-TORUS-1.0",
            "theory_sha256": THEORY_SHA256,
            "units": "SI",
            "weight_semantics": "probability",
            "members": [
                {
                    "member_id": "valid",
                    "weight": 0.75,
                    "uncertainty_components": self._components(),
                    "config": valid,
                },
                {
                    "member_id": "invalid",
                    "weight": 0.25,
                    "uncertainty_components": self._components(),
                    "config": invalid,
                },
            ],
        }

    def test_invalid_physical_member_is_retained_with_trajectory_contract(self):
        result = run_ensemble(self._spec())
        self.assertEqual(result.status, "SAMPLED_PREDICTION_SET_COMPLETE")
        self.assertEqual(len(result.members), 2)
        self.assertEqual(result.members[0].result.contract_status, ["COMPLETED"])
        self.assertEqual(result.members[1].result.contract_status, ["INVALID_INPUT"])
        self.assertEqual(result.members[1].result.numerical_status, "INPUT_REJECTED")
        self.assertEqual(result.summary_dict()["member_count"], 2)

    def test_writer_preserves_each_member_and_refuses_overwrite(self):
        spec = self._spec()
        result = run_ensemble(spec)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "prediction-set"
            write_ensemble(output, spec, result)
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest["members"]), 2)
            self.assertTrue((output / "members" / "valid" / "trajectory.npz").is_file())
            self.assertTrue((output / "members" / "invalid" / "result.json").is_file())
            with self.assertRaises(FileExistsError):
                write_ensemble(output, spec, result)

    def test_unsafe_or_duplicate_member_identity_rejects_entire_spec(self):
        spec = self._spec()
        spec["members"][0]["member_id"] = "../escape"
        spec["members"][1]["member_id"] = "../escape"
        result = run_ensemble(spec)
        self.assertEqual(result.status, "INVALID_ENSEMBLE_INPUT")
        self.assertEqual(result.members, ())

        for field, malformed in (("model_id", []), ("weight_semantics", {})):
            malformed_spec = self._spec()
            malformed_spec[field] = malformed
            result = run_ensemble(malformed_spec)
            self.assertEqual(result.status, "INVALID_ENSEMBLE_INPUT")
            self.assertEqual(result.members, ())

    def test_unexpected_member_exception_is_retained_and_later_members_run(self):
        spec = self._spec()
        from y_pendulum_forward.runner import run_config as real_run_config

        call_count = 0

        def one_failure(config):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("synthetic member failure")
            return real_run_config(config)

        with patch(
            "y_pendulum_forward.ensemble.run_config",
            side_effect=one_failure,
        ):
            result = run_ensemble(spec)
        self.assertEqual(
            result.status,
            "SAMPLED_PREDICTION_SET_MEMBER_EXECUTION_FAILURE",
        )
        self.assertEqual(len(result.members), 2)
        self.assertEqual(
            result.members[0].result.numerical_status,
            "INTERNAL_EXECUTION_FAILURE",
        )
        self.assertEqual(result.members[1].result.contract_status, ["INVALID_INPUT"])
        self.assertEqual(call_count, 2)

    def test_wrong_result_model_cannot_qualify_the_set(self):
        spec = self._spec()
        from y_pendulum_forward.runner import run_config as real_run_config

        def wrong_model(config):
            result = real_run_config(config)
            result.model_id = "FWD-CABLE-1.0"
            return result

        with patch(
            "y_pendulum_forward.ensemble.run_config",
            side_effect=wrong_model,
        ):
            result = run_ensemble(spec)
        self.assertEqual(
            result.status,
            "SAMPLED_PREDICTION_SET_IDENTITY_UNRESOLVED",
        )
        self.assertTrue(result.members)
        self.assertTrue(
            all(
                not member.identity_checks["result_model_matches_set"]
                for member in result.members
            )
        )

    def test_recursive_non_json_or_nonfinite_metadata_is_rejected(self):
        mutations = (
            lambda spec: spec.update(metadata={"bad": float("nan")}),
            lambda spec: spec["members"][0]["uncertainty_components"][
                "physical_parameters"
            ].update(bad=float("nan")),
            lambda spec: spec["members"][0]["uncertainty_components"][
                "physical_parameters"
            ].update(bad={1, 2}),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                spec = self._spec()
                mutate(spec)
                result = run_ensemble(spec)
                self.assertEqual(result.status, "INVALID_ENSEMBLE_INPUT")
                self.assertEqual(result.members, ())
                self.assertEqual(
                    result.ensemble_sha256,
                    "UNHASHABLE_INVALID_ENSEMBLE",
                )
                self.assertTrue(result.validation_errors)

    def test_relative_weights_with_overflowing_sum_are_rejected(self):
        spec = self._spec()
        spec["weight_semantics"] = "relative"
        for member in spec["members"]:
            member["weight"] = 1e308
        result = run_ensemble(spec)
        self.assertEqual(result.status, "INVALID_ENSEMBLE_INPUT")
        self.assertEqual(result.members, ())
        self.assertTrue(result.validation_errors)

    def test_huge_json_integer_weight_is_rejected_without_exception(self):
        spec = self._spec()
        spec["members"][0]["weight"] = 10**10000
        result = run_ensemble(spec)
        self.assertEqual(result.status, "INVALID_ENSEMBLE_INPUT")
        self.assertEqual(result.members, ())

    def test_omitted_member_method_uses_closed_default_identity(self):
        spec = self._spec()
        for member in spec["members"]:
            member["config"]["numerics"].pop("method")
        result = run_ensemble(spec)
        self.assertEqual(result.status, "SAMPLED_PREDICTION_SET_COMPLETE")
        self.assertTrue(
            all(
                member.result.metadata["numerical_model_id"]
                == "NUM-FWD-TORUS-DOP853-1.0"
                for member in result.members
            )
        )


if __name__ == "__main__":
    unittest.main()

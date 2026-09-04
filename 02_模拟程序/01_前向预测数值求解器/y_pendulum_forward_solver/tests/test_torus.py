from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import unittest

import numpy as np
from scipy.special import ellipk

from y_pendulum_forward.contracts import load_json
from y_pendulum_forward.runner import run_config


ROOT = Path(__file__).resolve().parents[1]


class TorusTests(unittest.TestCase):
    def setUp(self):
        self.config = load_json(ROOT / "configs" / "torus_example.json")

    def test_nontrivial_run_geometry_energy_and_tension(self):
        config = deepcopy(self.config)
        config["physical"]["T"] = 0.2
        config["numerics"]["output_dt"] = 0.002
        result = run_config(config)
        self.assertEqual(result.contract_status, ["COMPLETED"])
        self.assertTrue(result.numerical_status.startswith("SUCCESS"))
        self.assertLess(result.diagnostics["max_relative_energy_drift"], 1e-9)
        self.assertLess(result.diagnostics["max_abs_torus_unsquared_residual"], 1e-12)
        self.assertGreater(result.diagnostics["min_Q_T"], 0.0)
        for key in ("T_A", "T_B", "T_lower"):
            self.assertGreater(float(np.min(result.derived[key])), 0.0)

    def test_omitted_method_binds_the_actual_default_integrator_identity(self):
        config = deepcopy(self.config)
        config["numerics"].pop("method")
        config["physical"]["T"] = 0.01
        config["observation"] = None
        result = run_config(config)
        self.assertEqual(result.contract_status, ["COMPLETED"])
        self.assertEqual(result.metadata["integrator"], "DOP853")
        self.assertEqual(
            result.metadata["numerical_model_id"],
            "NUM-FWD-TORUS-DOP853-1.0",
        )

    def test_explicit_null_method_is_not_mislabeled_as_the_default(self):
        config = deepcopy(self.config)
        config["numerics"]["method"] = None
        config["physical"]["T"] = 0.01
        config["observation"] = None
        result = run_config(config)
        self.assertEqual(result.contract_status, [])
        self.assertEqual(result.numerical_status, "INVALID_NUMERICAL_CONFIG")
        self.assertEqual(
            result.metadata["numerical_model_id"],
            "NUM-FWD-TORUS-UNRESOLVED-1.0",
        )

    def test_unhashable_method_values_are_rejected_without_dispatch_crash(self):
        for malformed in ([], {}):
            config = deepcopy(self.config)
            config["numerics"]["method"] = malformed
            config["physical"]["T"] = 0.01
            config["observation"] = None
            result = run_config(config)
            self.assertEqual(result.contract_status, [])
            self.assertEqual(
                result.numerical_status,
                "INVALID_NUMERICAL_CONFIG",
            )
            self.assertEqual(
                result.metadata["numerical_model_id"],
                "NUM-FWD-TORUS-UNRESOLVED-1.0",
            )

    def test_extreme_time_grids_fail_closed_before_allocation_or_integration(self):
        for field in ("output_dt", "max_step"):
            config = deepcopy(self.config)
            config["physical"]["T"] = 0.001
            config["numerics"][field] = 5e-324
            config["observation"] = None
            result = run_config(config)
            self.assertEqual(result.contract_status, [])
            self.assertEqual(
                result.numerical_status,
                "INVALID_NUMERICAL_CONFIG",
            )
            self.assertTrue(
                any(
                    failure["code"] == "NUMERICAL_RESOURCE_LIMIT"
                    for failure in result.events[0]["failures"]
                )
            )

    def test_extreme_uniform_observation_grid_is_observation_invalid_only(self):
        config = deepcopy(self.config)
        config["physical"]["T"] = 0.001
        config["numerics"]["max_step"] = 0.0001
        config["numerics"]["output_dt"] = 0.0001
        config["observation"]["record_times"] = {
            "kind": "uniform",
            "start": 0.0,
            "stop": 0.001,
            "step": 5e-324,
        }
        result = run_config(config)
        self.assertEqual(result.contract_status, ["COMPLETED"])
        self.assertEqual(result.numerical_status, "SUCCESS_SINGLE_RUN")
        self.assertEqual(
            result.observations["status"],
            ["INVALID_OBSERVATION_INPUT"],
        )

    def test_unhashable_observation_type_does_not_abort_physical_run(self):
        for malformed in ([], {}):
            config = deepcopy(self.config)
            config["physical"]["T"] = 0.001
            config["numerics"]["max_step"] = 0.0001
            config["observation"]["type"] = malformed
            result = run_config(config)
            self.assertEqual(result.contract_status, ["COMPLETED"])
            self.assertEqual(
                result.observations["status"],
                ["INVALID_OBSERVATION_INPUT"],
            )

    def test_whole_config_must_be_finite_acyclic_canonical_json(self):
        configs = []

        nonfinite = deepcopy(self.config)
        nonfinite["metadata"] = {"bad": float("nan")}
        configs.append(nonfinite)

        non_json = deepcopy(self.config)
        non_json["metadata"] = {"bad": {1, 2}}
        configs.append(non_json)

        non_string_key = deepcopy(self.config)
        non_string_key["metadata"] = {1: "bad"}
        configs.append(non_string_key)

        cyclic = deepcopy(self.config)
        cyclic["metadata"] = {}
        cyclic["metadata"]["self"] = cyclic["metadata"]
        configs.append(cyclic)

        unhashable_integer = deepcopy(self.config)
        unhashable_integer["metadata"] = {"bad": 10**10000}
        configs.append(unhashable_integer)

        for config in configs:
            with self.subTest(metadata_type=type(config.get("metadata"))):
                result = run_config(config)
                self.assertEqual(result.contract_status, [])
                self.assertEqual(result.numerical_status, "INPUT_REJECTED")
                self.assertIn("config_sha256", result.metadata)

    def test_noncanonical_numerics_is_not_mislabeled_physical_invalid_input(self):
        mutations = (
            lambda config: config["numerics"].update(rtol=float("nan")),
            lambda config: config["numerics"].update(rtol=float("inf")),
            lambda config: config["numerics"].update(extra={1, 2}),
            lambda config: config["numerics"].update(extra={1: "bad"}),
        )
        for mutate in mutations:
            config = deepcopy(self.config)
            mutate(config)
            result = run_config(config)
            self.assertEqual(result.contract_status, [])
            self.assertEqual(
                result.numerical_status,
                "INVALID_NUMERICAL_CONFIG",
            )

        cyclic = deepcopy(self.config)
        cyclic["numerics"]["cycle"] = cyclic["numerics"]
        result = run_config(cyclic)
        self.assertEqual(result.contract_status, [])
        self.assertEqual(result.numerical_status, "INVALID_NUMERICAL_CONFIG")

    def test_noncanonical_observation_is_not_a_physical_invalid_input(self):
        config = deepcopy(self.config)
        config["observation"] = {"bad": {1, 2}}
        result = run_config(config)
        self.assertEqual(result.contract_status, [])
        self.assertEqual(result.numerical_status, "INPUT_REJECTED")
        self.assertEqual(
            result.observations["status"],
            ["INVALID_OBSERVATION_INPUT"],
        )

    def test_software_envelope_errors_are_not_physical_invalid_input(self):
        mutations = (
            lambda config: config.update(schema_version="wrong"),
            lambda config: config.update(theory_sha256="wrong"),
            lambda config: config.update(schema_version={"not", "json"}),
            lambda config: config.update(theory_sha256=float("nan")),
            lambda config: config.update(unknown_envelope_field=1),
        )
        for mutate in mutations:
            config = deepcopy(self.config)
            mutate(config)
            result = run_config(config)
            self.assertEqual(result.contract_status, [])
            self.assertEqual(result.numerical_status, "INPUT_REJECTED")
            self.assertIn(
                result.events[0]["kind"],
                {"config_envelope", "input_validation"},
            )

    def test_non_object_config_roots_are_structurally_rejected(self):
        for config in ([], None, "bad", 3):
            with self.subTest(root_type=type(config).__name__):
                result = run_config(config)
                self.assertEqual(result.contract_status, [])
                self.assertEqual(result.numerical_status, "INPUT_REJECTED")
                self.assertEqual(
                    result.events[0]["failures"][0]["code"],
                    "CONFIG_ROOT_TYPE",
                )

    def test_equilibrium_is_stationary_and_tensions_match(self):
        config = deepcopy(self.config)
        config["physical"]["initial_state"] = [0.0, 0.0, 0.0, 0.0]
        config["physical"]["T"] = 0.05
        result = run_config(config)
        np.testing.assert_allclose(result.state["X_torus"], 0.0, atol=2e-14)
        expected_lower = config["physical"]["mass"] * config["physical"]["g"]
        np.testing.assert_allclose(result.derived["T_lower"], expected_lower, rtol=1e-13)

    def test_tilted_support_axis_is_rejected(self):
        config = deepcopy(self.config)
        config["physical"]["B"][2] = 0.01
        result = run_config(config)
        self.assertEqual(result.contract_status, ["INVALID_INPUT"])
        failures = result.events[0]["failures"]
        self.assertTrue(any(item["code"] == "TORUS_GEOMETRY" for item in failures))

    def test_tiny_vertical_support_axis_is_not_hidden_by_absolute_tolerance(self):
        config = deepcopy(self.config)
        config["physical"].update(
            A=[0.0, 0.0, 0.0],
            B=[0.0, 0.0, 1e-12],
            e_z=[0.0, 0.0, 1.0],
            s_A=1.0,
            s_B=1.0,
            lower_length=1.0,
            initial_state=[0.0, 0.0, 0.0, 0.0],
            T=0.01,
        )
        result = run_config(config)
        self.assertEqual(result.contract_status, ["INVALID_INPUT"])
        self.assertEqual(result.numerical_status, "INPUT_REJECTED")

    def test_unknown_or_malformed_numerical_field_is_rejected_without_crash(self):
        unknown = deepcopy(self.config)
        unknown["numerics"]["rtlo"] = 1e-8
        result = run_config(unknown)
        self.assertEqual(result.contract_status, [])
        self.assertEqual(result.numerical_status, "INVALID_NUMERICAL_CONFIG")

    def test_strings_and_booleans_are_not_coerced_into_physical_numbers(self):
        strings = deepcopy(self.config)
        strings["physical"]["A"] = ["-0.15", "0", "0"]
        strings["physical"]["B"] = ["0.15", "0", "0"]
        strings["physical"]["e_z"] = ["0", "0", "1"]
        result = run_config(strings)
        self.assertEqual(result.contract_status, ["INVALID_INPUT"])

        booleans = deepcopy(self.config)
        booleans["physical"]["initial_state"] = [False, False, False, False]
        result = run_config(booleans)
        self.assertEqual(result.contract_status, ["INVALID_INPUT"])

        malformed = deepcopy(self.config)
        malformed["numerics"]["rtol"] = "bad"
        result = run_config(malformed)
        self.assertEqual(result.contract_status, [])
        self.assertEqual(result.numerical_status, "INVALID_NUMERICAL_CONFIG")

        below_machine_floor = deepcopy(self.config)
        below_machine_floor["numerics"]["rtol"] = 1e-40
        result = run_config(below_machine_floor)
        self.assertEqual(result.contract_status, [])
        self.assertEqual(result.numerical_status, "INVALID_NUMERICAL_CONFIG")

    def test_first_tension_loss_stops_without_model_switch(self):
        config = deepcopy(self.config)
        config["physical"]["initial_state"] = [0.30, 0.0, 2.0, 0.0]
        config["physical"]["T"] = 0.5
        config["numerics"]["max_step"] = 0.001
        result = run_config(config)
        self.assertEqual(result.contract_status, ["OUT_OF_SCOPE"])
        self.assertLess(result.tau, config["physical"]["T"])
        self.assertTrue(any("T_B_ZERO" in trigger for trigger in result.events[0]["triggers"]))
        self.assertEqual(result.model_id, "FWD-TORUS-1.0")
        self.assertIn("derived_left", result.events[0])
        self.assertIn("E_torus", result.events[0]["derived_left"])

    def test_simultaneous_zero_tensions_are_all_reported(self):
        config = deepcopy(self.config)
        config["physical"]["initial_state"] = [0.0, 1.2, 0.0, 3.3]
        config["physical"]["T"] = 0.5
        config["numerics"]["max_step"] = 0.001
        config["observation"] = None
        result = run_config(config)
        self.assertEqual(result.contract_status, ["OUT_OF_SCOPE"])
        self.assertEqual(
            set(result.events[0]["triggers"]),
            {"T_A_ZERO", "T_B_ZERO", "T_LOWER_ZERO"},
        )

    def test_small_mass_does_not_turn_nonzero_tensions_into_simultaneous_roots(self):
        config = deepcopy(self.config)
        config["physical"]["mass"] = 1e-12
        config["physical"]["initial_state"] = [0.30, 0.0, 2.0, 0.0]
        config["physical"]["T"] = 0.5
        config["numerics"]["max_step"] = 0.001
        config["observation"] = None
        result = run_config(config)
        self.assertEqual(result.contract_status, ["OUT_OF_SCOPE"])
        self.assertIn("T_B_ZERO", result.events[0]["triggers"])
        self.assertNotIn("T_A_ZERO", result.events[0]["triggers"])
        self.assertNotIn("T_LOWER_ZERO", result.events[0]["triggers"])

    def test_tangential_tension_touch_is_not_reported_as_completed(self):
        config = deepcopy(self.config)
        physical = config["physical"]
        support_distance = float(
            np.linalg.norm(
                np.asarray(physical["B"]) - np.asarray(physical["A"])
            )
        )
        upper = float(physical["s_A"])
        height = math.sqrt(upper * upper - (support_distance / 2.0) ** 2)
        alpha = math.atan((support_distance / 2.0) / height)
        modulus = math.sin(alpha / 2.0)
        omega = math.sqrt(physical["g"] / physical["lower_length"])
        tangent_time = float(ellipk(modulus * modulus) / omega)
        physical["initial_state"] = [0.0, 0.0, 2.0 * modulus * omega, 0.0]
        physical["T"] = 1.5 * tangent_time
        config["numerics"].update(
            output_dt=tangent_time,
            max_step=tangent_time / 100.0,
            rtol=1e-11,
            atol=1e-13,
        )
        config["observation"] = None
        result = run_config(config)
        # A double root is ill-conditioned: last-bit platform differences can
        # either create a tiny sign change (located by SciPy) or leave the
        # sampled guard at roundoff (caught by our completion audit). Both
        # outcomes must exclude completion.
        self.assertIn(
            (tuple(result.contract_status), result.numerical_status),
            (((), "EVENT_UNRESOLVED"), (("OUT_OF_SCOPE",), "SUCCESS_EVENT")),
        )
        if result.numerical_status == "EVENT_UNRESOLVED":
            self.assertAlmostEqual(result.tau, tangent_time, places=12)
        else:
            self.assertLess(abs(result.tau - tangent_time), 1e-6)
            event = result.events[0]
            self.assertLessEqual(
                abs(event["guard_values"]["T_B_ZERO"]),
                event["guard_zero_tolerances"]["T_B_ZERO"],
            )
        self.assertTrue(np.all(result.time < result.tau))
        self.assertIn("T_B_ZERO", result.events[0]["triggers"])

    def test_sampled_tangency_audit_is_independent_of_root_finder(self):
        from y_pendulum_forward.torus import (
            _torus_completed_sample_failure, validate_torus_config, torus_derived,
        )
        issues, params = validate_torus_config(self.config)
        self.assertEqual(issues, [])
        assert params is not None
        alpha = math.atan(params.a_A / params.h)
        states = np.array([[0., 0., 0., 0.], [alpha, 0., 0., 0.]])
        derived = torus_derived(params, states)
        failure = _torus_completed_sample_failure(
            params, np.array([0., 0.3]), states, derived,
        )
        self.assertIsNotNone(failure)
        assert failure is not None
        self.assertEqual(failure["numerical_status"], "EVENT_UNRESOLVED")
        self.assertEqual(failure["sample_index"], 1)
        self.assertEqual(failure["time"], 0.3)
        self.assertIn("T_B_ZERO", failure["triggers"])


if __name__ == "__main__":
    unittest.main()

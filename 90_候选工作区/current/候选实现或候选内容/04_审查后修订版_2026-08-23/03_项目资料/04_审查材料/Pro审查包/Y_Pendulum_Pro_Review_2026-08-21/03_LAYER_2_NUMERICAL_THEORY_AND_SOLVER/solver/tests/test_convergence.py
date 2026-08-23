from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from y_pendulum_forward.contracts import SimulationResult, load_json
from y_pendulum_forward.convergence import (
    _canonical_output_contract,
    _cable_dynamics_defect,
    _compare,
    _dynamics_trend_checks,
    _event_contract,
    _event_sets_stable,
    _expected_guard_schema,
    _guard_error_budget,
    _guard_output_contract,
    _observation_result_contract,
    _physics_checks,
    _refinement_level_physics_checks,
    _torus_dynamics_defect,
    run_refinement_study,
)
from y_pendulum_forward.runner import run_config
from y_pendulum_forward.torus import validate_torus_config


ROOT = Path(__file__).resolve().parents[1]


class ConvergenceTests(unittest.TestCase):
    def _short_torus(self):
        config = load_json(ROOT / "configs" / "torus_example.json")
        config = deepcopy(config)
        config["physical"]["T"] = 0.02
        config["numerics"]["max_step"] = 0.001
        config["validation"]["studies"]["time"][
            "comparison_time_step"
        ] = 0.002
        config["validation"]["studies"]["time"][
            "minimum_comparison_samples"
        ] = 10
        config["observation"] = None
        return config

    def _short_cable(self, *, observation=False):
        config = deepcopy(load_json(ROOT / "configs" / "cable_example.json"))
        config["physical"]["T"] = 0.004
        config["numerics"]["elements"] = {"A": 2, "B": 2, "lower": 2}
        config["numerics"]["quadrature_order"] = 3
        config["numerics"]["max_step"] = 0.0005
        config["numerics"]["output_dt"] = 0.001
        if observation:
            config["observation"]["record_times"] = {
                "kind": "uniform",
                "start": 0.0,
                "stop": 0.004,
                "step": 0.001,
            }
        else:
            config["observation"] = None
        return config

    def test_missing_validation_thresholds_fail_closed(self):
        config = load_json(ROOT / "configs" / "torus_example.json")
        config.pop("validation")
        report = run_refinement_study(config)
        self.assertEqual(report["qualification"], "INVALID_VALIDATION_CONFIG")

    def test_unhashable_model_id_is_structurally_rejected(self):
        config = self._short_torus()
        config["model_id"] = []
        report = run_refinement_study(config)
        self.assertEqual(report["qualification"], "INVALID_MODEL_ID")

    def test_duplicate_quadrature_levels_fail_closed(self):
        config = load_json(ROOT / "configs" / "cable_example.json")
        config["numerics"]["quadrature_order"] = 4
        report = run_refinement_study(config)
        self.assertEqual(report["qualification"], "INVALID_VALIDATION_CONFIG")

    def test_production_config_is_the_finest_level(self):
        config = self._short_torus()
        report = run_refinement_study(config)
        self.assertTrue(report["base_config_is_finest_level"])
        self.assertEqual(
            report["studies"]["time"]["levels"][-1][
                "expected_config_sha256"
            ],
            report["base_config_sha256"],
        )
        finest_checks = report["studies"]["time"][
            "finest_threshold_checks"
        ]
        self.assertTrue(
            finest_checks["finest_energy_metric_finite_and_bounded"]
        )
        self.assertTrue(
            finest_checks["finest_dynamics_defect_finite_and_bounded"]
        )

    def test_validation_grid_is_independent_of_sparse_presentation_output(self):
        config = load_json(ROOT / "configs" / "torus_example.json")
        config = deepcopy(config)
        config["physical"]["T"] = 0.2
        config["numerics"]["output_dt"] = 10.0
        config["validation"]["studies"]["time"]["comparison_time_step"] = 0.002
        config["validation"]["studies"]["time"]["minimum_comparison_samples"] = 100
        report = run_refinement_study(config)
        comparison = report["studies"]["time"]["comparisons"][-1]
        self.assertGreaterEqual(comparison["comparison_sample_count"], 100)
        self.assertTrue(
            report["studies"]["time"]["finest_threshold_checks"][
                "minimum_comparison_samples"
            ]
        )

    def test_string_numerics_are_not_repaired_by_refinement_generation(self):
        config = self._short_torus()
        for key in ("rtol", "atol", "max_step"):
            config["numerics"][key] = str(config["numerics"][key])
        report = run_refinement_study(config)
        self.assertEqual(report["qualification"], "INVALID_BASE_CONFIG")
        self.assertEqual(report["studies"], {})

    def test_string_validation_threshold_is_rejected(self):
        config = self._short_torus()
        config["validation"]["studies"]["time"][
            "max_finest_rms_angle"
        ] = "1e-9"
        report = run_refinement_study(config)
        self.assertEqual(report["qualification"], "INVALID_VALIDATION_CONFIG")

    def test_non_json_or_cyclic_base_config_is_rejected_before_hashing(self):
        nonfinite = self._short_torus()
        nonfinite["metadata"] = {"bad": float("nan")}
        report = run_refinement_study(nonfinite)
        self.assertEqual(report["qualification"], "INVALID_BASE_CONFIG")
        self.assertEqual(report["studies"], {})

        cyclic = self._short_torus()
        cyclic["metadata"] = {}
        cyclic["metadata"]["self"] = cyclic["metadata"]
        report = run_refinement_study(cyclic)
        self.assertEqual(report["qualification"], "INVALID_BASE_CONFIG")
        self.assertEqual(report["studies"], {})

    def test_canonical_rate_difference_cannot_hide_behind_same_bob_output(self):
        config = self._short_torus()
        call_index = 0

        def corrupt(candidate):
            nonlocal call_index
            result = run_config(candidate)
            if call_index == 1:
                result.state["X_torus"] = result.state["X_torus"].copy()
                result.state["X_torus"][:, 2] += 1e6
            call_index += 1
            return result

        with patch("y_pendulum_forward.convergence.run_config", side_effect=corrupt):
            report = run_refinement_study(config)
        self.assertEqual(report["qualification"], "CONVERGENCE_NOT_DEMONSTRATED")
        checks = report["studies"]["time"]["finest_threshold_checks"]
        self.assertFalse(checks["rms_angular_rate"])

    def test_fake_shared_identity_and_prefix_success_do_not_qualify(self):
        config = self._short_torus()

        def corrupt(candidate):
            result = run_config(candidate)
            result.numerical_status = "SUCCESS_WITH_UNCHECKED_WARNING"
            for key in (
                "config_sha256",
                "physical_input_sha256",
                "numerical_config_sha256",
                "observation_input_sha256",
                "source_tree_sha256",
            ):
                result.metadata[key] = "f" * 64
            return result

        with patch("y_pendulum_forward.convergence.run_config", side_effect=corrupt):
            report = run_refinement_study(config)
        self.assertEqual(report["qualification"], "CONVERGENCE_NOT_DEMONSTRATED")
        for level in report["studies"]["time"]["levels"]:
            self.assertFalse(level["numerical_success_exact"])
            self.assertFalse(level["identity_valid"])

    def test_wrong_result_model_cannot_qualify_refinement(self):
        config = self._short_torus()

        def wrong_model(candidate):
            result = run_config(candidate)
            result.model_id = "FWD-CABLE-1.0"
            return result

        with patch(
            "y_pendulum_forward.convergence.run_config",
            side_effect=wrong_model,
        ):
            report = run_refinement_study(config)
        self.assertEqual(
            report["qualification"],
            "CONVERGENCE_NOT_DEMONSTRATED",
        )
        for level in report["studies"]["time"]["levels"]:
            self.assertFalse(
                level["identity_checks"]["result_model_matches_requested"]
            )

    def test_event_contract_rejects_empty_or_inconsistent_root_evidence(self):
        config = self._short_torus()
        config["physical"].update(
            initial_state=[0.30, 0.0, 2.0, 0.0],
            T=0.5,
        )
        config["numerics"]["max_step"] = 0.001
        result = run_config(config)
        schema = _expected_guard_schema(config, "FWD-TORUS-1.0")
        valid, _signature = _event_contract(
            result,
            ["OUT_OF_SCOPE"],
            "FWD-TORUS-1.0",
            schema,
            config,
        )
        self.assertTrue(valid)
        self.assertTrue(
            _guard_output_contract(
                result,
                schema,
                "FWD-TORUS-1.0",
                ["OUT_OF_SCOPE"],
            )["passed"]
        )

        corrupted = deepcopy(result)
        corrupted.events[0]["time"] = 999.0
        corrupted.events[0]["state_left"] = None
        corrupted.events[0]["derived_left"] = None
        corrupted.events[0]["guard_values"] = {}
        valid, _signature = _event_contract(
            corrupted,
            ["OUT_OF_SCOPE"],
            "FWD-TORUS-1.0",
            schema,
            config,
        )
        self.assertFalse(valid)
        self.assertFalse(
            _guard_output_contract(
                corrupted,
                schema,
                "FWD-TORUS-1.0",
                ["OUT_OF_SCOPE"],
            )["passed"]
        )

        forged = deepcopy(result)
        trigger = forged.events[0]["triggers"][0]
        forged.events[0]["guard_values"][trigger] = 0.5
        forged.events[0]["guard_zero_tolerances"][trigger] = 1.0
        valid, _signature = _event_contract(
            forged,
            ["OUT_OF_SCOPE"],
            "FWD-TORUS-1.0",
            schema,
            config,
        )
        self.assertFalse(valid)
        self.assertFalse(
            _guard_output_contract(
                forged,
                schema,
                "FWD-TORUS-1.0",
                ["OUT_OF_SCOPE"],
            )["passed"]
        )

    def test_torus_guard_registry_cannot_consistently_omit_one_component(self):
        config = self._short_torus()
        result = run_config(config)
        schema = _expected_guard_schema(config, "FWD-TORUS-1.0")
        baseline = _guard_output_contract(
            result,
            schema,
            "FWD-TORUS-1.0",
            ["COMPLETED"],
        )
        self.assertTrue(baseline["passed"])

        for field in (
            "sampled_guard_component_series",
            "guard_component_scales",
        ):
            corrupted = deepcopy(result)
            del corrupted.diagnostics[field]["T_B_ZERO"]
            report = _guard_output_contract(
                corrupted,
                schema,
                "FWD-TORUS-1.0",
                ["COMPLETED"],
            )
            self.assertFalse(report["passed"])
        corrupted = deepcopy(result)
        corrupted.diagnostics["guard_component_scales"]["T_B_ZERO"] = 1e30
        self.assertFalse(
            _guard_output_contract(
                corrupted,
                schema,
                "FWD-TORUS-1.0",
                ["COMPLETED"],
            )["passed"]
        )

    def test_cable_guard_registry_requires_element_material_and_custom_fields(self):
        config = load_json(ROOT / "configs" / "cable_example.json")
        config = deepcopy(config)
        config["physical"]["T"] = 0.002
        config["numerics"]["elements"] = {"A": 2, "B": 2, "lower": 2}
        config["numerics"]["max_step"] = 0.0005
        config["numerics"]["output_dt"] = 0.001
        config["observation"] = None
        config["inputs"]["exit_guards"] = [
            {
                "kind": "bob_plane",
                "name": "far",
                "normal": [0.0, 0.0, 1.0],
                "offset": 1.0,
            }
        ]
        result = run_config(config)
        schema = _expected_guard_schema(config, "FWD-CABLE-1.0")
        baseline = _guard_output_contract(
            result,
            schema,
            "FWD-CABLE-1.0",
            ["COMPLETED"],
        )
        self.assertTrue(baseline["passed"])

        deletions = (
            ("sampled_guard_component_series", "LAMBDA_MIN:A:element:0"),
            (
                "sampled_guard_component_series",
                "MATERIAL_DOMAIN:B:rate_upper:element:0",
            ),
            ("sampled_guard_component_series", "EXIT_GUARD:far"),
            ("guard_component_scales", "EXIT_GUARD:far"),
            ("sampled_guard_minima", "custom:far"),
            ("sampled_guard_series", "custom:far"),
        )
        for field, key in deletions:
            with self.subTest(field=field, key=key):
                corrupted = deepcopy(result)
                del corrupted.diagnostics[field][key]
                report = _guard_output_contract(
                    corrupted,
                    schema,
                    "FWD-CABLE-1.0",
                    ["COMPLETED"],
                )
                self.assertFalse(report["passed"])
        corrupted = deepcopy(result)
        corrupted.diagnostics["guard_component_scales"][
            "EXIT_GUARD:far"
        ] = 1e30
        self.assertFalse(
            _guard_output_contract(
                corrupted,
                schema,
                "FWD-CABLE-1.0",
                ["COMPLETED"],
            )["passed"]
        )

    def test_cable_topology_and_full_field_shapes_cannot_hide_differences(self):
        config = self._short_cable()
        result = run_config(config)
        schema = _expected_guard_schema(config, "FWD-CABLE-1.0")
        baseline = _canonical_output_contract(
            config, result, "FWD-CABLE-1.0", ["COMPLETED"], schema
        )
        self.assertTrue(baseline["passed"])

        corruptions = []
        branch_nodes = deepcopy(result)
        branch_nodes.metadata["branch_nodes"]["A"] = [0, 2]
        corruptions.append(branch_nodes)
        node_state = deepcopy(result)
        node_state.state["node_positions"] = node_state.state[
            "node_positions"
        ][:, :-1]
        corruptions.append(node_state)
        element_field = deepcopy(result)
        element_field.derived["branches"]["lower"]["lambda"] = (
            element_field.derived["branches"]["lower"]["lambda"][:, :1]
        )
        corruptions.append(element_field)
        for corrupted in corruptions:
            with self.subTest(corruption=len(corruptions)):
                report = _canonical_output_contract(
                    config,
                    corrupted,
                    "FWD-CABLE-1.0",
                    ["COMPLETED"],
                    schema,
                )
                self.assertFalse(report["passed"])

    def test_completed_result_is_bound_to_candidate_horizon(self):
        config = self._short_torus()
        result = run_config(config)
        schema = _expected_guard_schema(config, "FWD-TORUS-1.0")
        baseline = _canonical_output_contract(
            config, result, "FWD-TORUS-1.0", ["COMPLETED"], schema
        )
        self.assertTrue(baseline["passed"])

        two_point = deepcopy(result)
        indices = np.array([0, result.time.size - 1])
        two_point.time = two_point.time[indices]
        two_point.state["X_torus"] = two_point.state["X_torus"][indices]
        for name in two_point.derived:
            two_point.derived[name] = two_point.derived[name][indices]
        for name in two_point.diagnostics["sampled_guard_component_series"]:
            two_point.diagnostics["sampled_guard_component_series"][name] = (
                two_point.diagnostics["sampled_guard_component_series"][name][
                    indices
                ]
            )
        two_point_report = _canonical_output_contract(
            config,
            two_point,
            "FWD-TORUS-1.0",
            ["COMPLETED"],
            schema,
        )
        self.assertFalse(two_point_report["horizon"]["passed"])
        self.assertFalse(
            two_point_report["horizon"]["checks"][
                "output_grid_matches_candidate_output_dt"
            ]
        )

        result.tau = config["physical"]["T"] / 2.0
        result.returned_interval = f"[0,{result.tau}]"
        result.time = result.time[result.time <= result.tau]
        result.state["X_torus"] = result.state["X_torus"][: result.time.size]
        for name in result.derived:
            result.derived[name] = result.derived[name][: result.time.size]
        for name in result.diagnostics["sampled_guard_component_series"]:
            result.diagnostics["sampled_guard_component_series"][name] = (
                result.diagnostics["sampled_guard_component_series"][name][
                    : result.time.size
                ]
            )
        report = _canonical_output_contract(
            config, result, "FWD-TORUS-1.0", ["COMPLETED"], schema
        )
        self.assertFalse(report["passed"])
        self.assertFalse(report["horizon"]["passed"])

    def test_derived_invariants_and_summaries_are_recomputed_from_state(self):
        torus_config = self._short_torus()
        torus = run_config(torus_config)
        torus_schema = _expected_guard_schema(
            torus_config, "FWD-TORUS-1.0"
        )
        torus.derived["Q_T"] = torus.derived["Q_T"].copy()
        torus.derived["Q_T"][0] = -1.0
        torus.derived["E_torus"] = torus.derived["E_torus"].copy()
        torus.derived["E_torus"][-1] += 1.0
        torus.diagnostics["min_Q_T"] = 1.0
        torus.diagnostics["max_relative_energy_drift"] = 0.0
        report = _canonical_output_contract(
            torus_config,
            torus,
            "FWD-TORUS-1.0",
            ["COMPLETED"],
            torus_schema,
        )
        self.assertFalse(report["passed"])

        cable_config = self._short_cable()
        cable = run_config(cable_config)
        cable_schema = _expected_guard_schema(
            cable_config, "FWD-CABLE-1.0"
        )
        cable.derived["D_ax"] = cable.derived["D_ax"].copy()
        cable.derived["D_ax"][0] = -1.0
        cable.diagnostics["min_D_ax"] = 0.0
        cable.diagnostics[
            "max_relative_energy_power_residual_physical_traction"
        ] = 0.0
        report = _canonical_output_contract(
            cable_config,
            cable,
            "FWD-CABLE-1.0",
            ["COMPLETED"],
            cable_schema,
        )
        self.assertFalse(report["passed"])

    def test_initial_binding_and_dynamics_defect_reject_frozen_false_trajectory(self):
        config = self._short_torus()
        result = run_config(config)
        schema = _expected_guard_schema(config, "FWD-TORUS-1.0")
        wrong_initial = deepcopy(result)
        wrong_initial.state["X_torus"] = wrong_initial.state[
            "X_torus"
        ].copy()
        wrong_initial.state["X_torus"][0, 0] += 0.1
        report = _canonical_output_contract(
            config,
            wrong_initial,
            "FWD-TORUS-1.0",
            ["COMPLETED"],
            schema,
        )
        self.assertFalse(
            report["trajectory"]["checks"][
                "initial_state_matches_candidate"
            ]
        )

        issues, params = validate_torus_config(config)
        self.assertEqual(issues, [])
        frozen = np.repeat(
            params.initial_state[None, :], result.time.size, axis=0
        )
        defect = _torus_dynamics_defect(params, result.time, frozen)
        self.assertGreater(
            defect["maximum_normalized_dynamics_defect"],
            config["validation"]["physics_checks"][
                "maximum_normalized_dynamics_defect"
            ],
        )

    def test_all_three_dynamics_defect_budgets_are_independently_gated(self):
        config = self._short_torus()
        result = run_config(config)
        schema = _expected_guard_schema(config, "FWD-TORUS-1.0")
        canonical = _canonical_output_contract(
            config,
            result,
            "FWD-TORUS-1.0",
            ["COMPLETED"],
            schema,
        )
        certified = canonical["recomputed_diagnostics"]
        criteria = config["validation"]["physics_checks"]
        checks, _, _ = _physics_checks(
            result,
            "FWD-TORUS-1.0",
            criteria,
            ["COMPLETED"],
            certified,
        )
        self.assertTrue(checks["dynamics_defect_finite_and_bounded"])
        self.assertTrue(
            checks["dynamics_cumulative_defect_finite_and_bounded"]
        )
        self.assertTrue(
            checks["dynamics_absolute_defect_finite_and_bounded"]
        )
        for metric, check_name in (
            (
                "maximum_normalized_cumulative_dynamics_defect",
                "dynamics_cumulative_defect_finite_and_bounded",
            ),
            (
                "maximum_normalized_absolute_dynamics_defect",
                "dynamics_absolute_defect_finite_and_bounded",
            ),
        ):
            attacked = deepcopy(certified)
            attacked[metric] = 2.0 * criteria[metric]
            attacked_checks, _, _ = _physics_checks(
                result,
                "FWD-TORUS-1.0",
                criteria,
                ["COMPLETED"],
                attacked,
            )
            self.assertFalse(attacked_checks[check_name])

    def test_each_dynamics_certificate_has_its_own_time_trend_gate(self):
        thresholds = {
            "maximum_normalized_dynamics_defect": 1.0,
            "maximum_normalized_cumulative_dynamics_defect": 1.0,
            "maximum_normalized_absolute_dynamics_defect": 1.0,
        }
        values = {
            "maximum_normalized_dynamics_defect": [0.9, 0.8, 0.7],
            # This field is never dominant in the display maximum, but its
            # coarse-to-middle deterioration must still fail qualification.
            "maximum_normalized_cumulative_dynamics_defect": [
                1.0e-5,
                1.0e-2,
                9.0e-3,
            ],
            "maximum_normalized_absolute_dynamics_defect": [
                2.0e-2,
                1.5e-2,
                1.0e-2,
            ],
        }
        checks = _dynamics_trend_checks(
            "time", values, thresholds, 1.05, 1.0e-6
        )
        self.assertTrue(checks["maximum_normalized_dynamics_defect"])
        self.assertFalse(
            checks["maximum_normalized_cumulative_dynamics_defect"]
        )
        self.assertTrue(
            checks["maximum_normalized_absolute_dynamics_defect"]
        )

    def test_only_finest_level_uses_absolute_accuracy_bounds(self):
        checks = {
            "canonical_fields_finite": True,
            "energy_metric_finite_and_bounded": False,
            "dynamics_defect_finite_and_bounded": False,
            "dynamics_cumulative_defect_finite_and_bounded": False,
            "dynamics_absolute_defect_finite_and_bounded": False,
            "dissipations_nonnegative_within_tolerance": True,
            "mass_matrix_positive": True,
        }
        metrics = {
            "energy_metric": 2.0,
            "maximum_normalized_dynamics_defect": 2.0,
            "maximum_normalized_cumulative_dynamics_defect": 2.0,
            "maximum_normalized_absolute_dynamics_defect": 2.0,
        }
        coarse = _refinement_level_physics_checks(
            checks, metrics, is_finest=False
        )
        self.assertTrue(all(coarse.values()))
        self.assertNotIn("energy_metric_finite_and_bounded", coarse)
        finest = _refinement_level_physics_checks(
            checks, metrics, is_finest=True
        )
        self.assertFalse(all(finest.values()))

        nan_metrics = deepcopy(metrics)
        nan_metrics["maximum_normalized_absolute_dynamics_defect"] = float(
            "nan"
        )
        coarse_nan = _refinement_level_physics_checks(
            checks, nan_metrics, is_finest=False
        )
        self.assertFalse(
            coarse_nan["coarse_accuracy_metrics_nonnegative_finite"]
        )
        bad_structure = deepcopy(checks)
        bad_structure["mass_matrix_positive"] = False
        coarse_bad_structure = _refinement_level_physics_checks(
            bad_structure, metrics, is_finest=False
        )
        self.assertFalse(coarse_bad_structure["mass_matrix_positive"])

    def test_refinement_study_separates_coarse_validity_from_finest_accuracy(self):
        config = self._short_torus()
        accuracy_names = (
            "energy_metric_finite_and_bounded",
            "dynamics_defect_finite_and_bounded",
            "dynamics_cumulative_defect_finite_and_bounded",
            "dynamics_absolute_defect_finite_and_bounded",
        )

        def run_with(levels):
            call_index = 0

            def fake_physics(*_args, **_kwargs):
                nonlocal call_index
                level = levels[call_index]
                call_index += 1
                checks = {
                    name: bool(level["accuracy_bounded"])
                    for name in accuracy_names
                }
                checks["structural_physics_valid"] = bool(
                    level.get("structural_valid", True)
                )
                metrics = {
                    "energy_metric": level["energy"],
                    "maximum_normalized_dynamics_defect": level["local"],
                    "maximum_normalized_cumulative_dynamics_defect": level[
                        "cumulative"
                    ],
                    "maximum_normalized_absolute_dynamics_defect": level[
                        "absolute"
                    ],
                }
                return checks, float(level["energy"]), metrics

            with patch(
                "y_pendulum_forward.convergence._physics_checks",
                side_effect=fake_physics,
            ):
                return run_refinement_study(config)

        valid_sequence = [
            {
                "accuracy_bounded": False,
                "energy": 3.0e-10,
                "local": 3.0e-6,
                "cumulative": 3.0e-8,
                "absolute": 3.0e-7,
            },
            {
                "accuracy_bounded": True,
                "energy": 2.0e-10,
                "local": 2.0e-6,
                "cumulative": 2.0e-8,
                "absolute": 2.0e-7,
            },
            {
                "accuracy_bounded": True,
                "energy": 1.0e-10,
                "local": 1.0e-6,
                "cumulative": 1.0e-8,
                "absolute": 1.0e-7,
            },
        ]
        report = run_with(deepcopy(valid_sequence))
        self.assertEqual(report["qualification"], "REFINEMENT_SUPPORTED")
        coarse = report["studies"]["time"]["levels"][0]
        self.assertFalse(
            coarse["physics_checks"][
                "dynamics_absolute_defect_finite_and_bounded"
            ]
        )
        self.assertTrue(all(coarse["physics_checks_applied"].values()))

        fine_failure = deepcopy(valid_sequence)
        fine_failure[-1]["accuracy_bounded"] = False
        self.assertEqual(
            run_with(fine_failure)["qualification"],
            "CONVERGENCE_NOT_DEMONSTRATED",
        )

        coarse_nonfinite = deepcopy(valid_sequence)
        coarse_nonfinite[0]["absolute"] = float("nan")
        self.assertEqual(
            run_with(coarse_nonfinite)["qualification"],
            "CONVERGENCE_NOT_DEMONSTRATED",
        )

        coarse_structural_failure = deepcopy(valid_sequence)
        coarse_structural_failure[0]["structural_valid"] = False
        self.assertEqual(
            run_with(coarse_structural_failure)["qualification"],
            "CONVERGENCE_NOT_DEMONSTRATED",
        )

    def test_cable_same_sign_small_local_defects_accumulate(self):
        interval_count = 100
        time = np.arange(interval_count + 1, dtype=float)
        positions = np.zeros((interval_count + 1, 1, 3), dtype=float)
        velocities = np.zeros_like(positions)
        acceleration = np.zeros_like(positions)
        midpoint_velocities = np.zeros((interval_count, 1, 3), dtype=float)
        # With h=1 and zero endpoint velocities this produces a +1e-4
        # Simpson position defect on every interval.
        midpoint_velocities[:, 0, 0] = -1.5e-4
        midpoint_acceleration = np.zeros_like(midpoint_velocities)
        metrics = _cable_dynamics_defect(
            time,
            positions,
            velocities,
            acceleration,
            midpoint_velocities,
            midpoint_acceleration,
            1.0,
            1.0,
            1.0,
        )
        self.assertAlmostEqual(
            metrics["maximum_normalized_dynamics_defect"], 1.0e-4
        )
        self.assertAlmostEqual(
            metrics["maximum_normalized_cumulative_dynamics_defect"],
            1.0e-2,
        )
        self.assertAlmostEqual(
            metrics["maximum_normalized_absolute_dynamics_defect"],
            1.0e-2,
        )

    def test_event_payload_must_match_independently_recomputed_left_state(self):
        config = self._short_torus()
        config["physical"].update(
            initial_state=[0.30, 0.0, 2.0, 0.0], T=0.5
        )
        config["numerics"]["max_step"] = 0.001
        result = run_config(config)
        schema = _expected_guard_schema(config, "FWD-TORUS-1.0")
        valid, _ = _event_contract(
            result,
            ["OUT_OF_SCOPE"],
            "FWD-TORUS-1.0",
            schema,
            config,
        )
        self.assertTrue(valid)
        result.events[0]["state_left"] = np.asarray(
            result.events[0]["state_left"]
        ).copy()
        result.events[0]["state_left"][0] += 0.1
        valid, _ = _event_contract(
            result,
            ["OUT_OF_SCOPE"],
            "FWD-TORUS-1.0",
            schema,
            config,
        )
        self.assertFalse(valid)

    def test_event_refinement_integration_passes_candidate_to_event_contract(self):
        config = self._short_torus()
        config["physical"].update(
            initial_state=[0.30, 0.0, 2.0, 0.0], T=0.5
        )
        config["numerics"]["max_step"] = 0.001
        config["validation"]["expected_contract_status"] = ["OUT_OF_SCOPE"]
        config["validation"]["studies"]["time"][
            "minimum_comparison_samples"
        ] = 10
        report = run_refinement_study(config)
        levels = report["studies"]["time"]["levels"]
        self.assertTrue(levels)
        self.assertTrue(all(level["event_schema_valid"] for level in levels))
        self.assertTrue(
            all(level["canonical_output_contract"]["passed"] for level in levels)
        )

    def test_event_left_state_is_included_in_cross_level_cauchy_error(self):
        config = self._short_torus()
        config["physical"].update(
            initial_state=[0.30, 0.0, 3.0, 0.0], T=0.5
        )
        config["numerics"]["max_step"] = 0.001
        first = run_config(config)
        self.assertEqual(first.contract_status, ["OUT_OF_SCOPE"])
        second = deepcopy(first)
        second.events[0]["state_left"] = np.asarray(
            second.events[0]["state_left"], dtype=float
        ).copy()
        second.events[0]["state_left"][2] += 1.0e-5
        comparison = _compare(
            first,
            second,
            model_id="FWD-TORUS-1.0",
            comparison_time_step=0.002,
            material_comparison_points=0,
        )
        self.assertGreaterEqual(comparison["max_angular_rate"], 1.0e-5)
        self.assertIn("event_left_errors", comparison)

    def test_near_event_observation_uses_left_state_without_crashing(self):
        config = self._short_torus()
        config["physical"].update(
            initial_state=[0.30, 0.0, 2.0, 0.0], T=0.5
        )
        config["numerics"]["max_step"] = 0.001
        probe = run_config(config)
        self.assertEqual(probe.contract_status, ["OUT_OF_SCOPE"])
        event_tolerance = config["numerics"]["event_cluster_tolerance"]
        config["observation"] = {
            "type": "orthographic",
            "axis_1": [1.0, 0.0, 0.0],
            "axis_2": [0.0, 1.0, 0.0],
            "t0": 0.0,
            "record_times": [
                0.0,
                float(probe.tau) - 0.5 * event_tolerance,
            ],
        }
        config["validation"]["expected_contract_status"] = ["OUT_OF_SCOPE"]
        config["validation"]["studies"]["time"][
            "minimum_comparison_samples"
        ] = 10
        report = run_refinement_study(config)
        levels = report["studies"]["time"]["levels"]
        self.assertTrue(levels)
        self.assertTrue(
            all(level["observation_contract"]["passed"] for level in levels)
        )

    def test_observation_cannot_be_deleted_or_detached_from_time_map(self):
        config = self._short_cable(observation=True)
        result = run_config(config)
        baseline = _observation_result_contract(
            config, result, "FWD-CABLE-1.0"
        )
        self.assertTrue(baseline["passed"])

        deleted = deepcopy(result)
        deleted.observations.update(
            record_time=np.empty(0),
            model_time=np.empty(0),
            time=np.empty(0),
            values=np.empty((0, 2)),
            valid_mask=np.empty(0, dtype=bool),
            event_ambiguous_mask=np.empty(0, dtype=bool),
            errors=[],
        )
        self.assertFalse(
            _observation_result_contract(
                config, deleted, "FWD-CABLE-1.0"
            )["passed"]
        )
        detached = deepcopy(result)
        detached.observations["model_time"] = (
            detached.observations["model_time"] + 1.0
        )
        detached.observations["operator"] = "camera_brown_conrady"
        detached.observations["values"] = (
            detached.observations["values"] + 1.0
        )
        self.assertFalse(
            _observation_result_contract(
                config, detached, "FWD-CABLE-1.0"
            )["passed"]
        )

    def test_event_guard_budget_still_checks_nontriggered_tangent_guard(self):
        time = np.array([0.0, 0.1, 0.2])
        series = {
            "R_ZERO": np.array([1.0, 0.0, 1.0]),
            "T_A_ZERO": np.full(3, 5.0),
            "T_B_ZERO": np.array([1.0, 0.8, 0.6]),
            "T_LOWER_ZERO": np.full(3, 5.0),
        }
        scales = {name: 1.0 for name in series}
        guard_schema = {
            "components": set(series),
            "scales": dict(scales),
            "minima": None,
            "aggregates": None,
            "custom_names": set(),
            "elements": None,
        }
        zero_tolerance = 1024.0 * np.finfo(float).eps

        def level():
            return SimulationResult(
                model_id="FWD-TORUS-1.0",
                contract_status=["OUT_OF_SCOPE"],
                numerical_status="SUCCESS_EVENT",
                tau=0.3,
                returned_interval="[0,0.3)",
                time=time.copy(),
                events=[
                    {
                        "kind": "physical_exit",
                        "triggers": ["T_B_ZERO"],
                        "guard_values": {
                            "R_ZERO": 1.0,
                            "T_A_ZERO": 5.0,
                            "T_B_ZERO": 0.0,
                            "T_LOWER_ZERO": 5.0,
                        },
                        "guard_zero_tolerances": {
                            "T_B_ZERO": zero_tolerance
                        },
                    }
                ],
                diagnostics={
                    "sampled_guard_component_series": {
                        name: values.copy() for name, values in series.items()
                    },
                    "guard_component_scales": dict(scales),
                },
                metadata={"event_cluster_tolerance": 1e-9},
            )

        report = _guard_error_budget(
            [level(), level()],
            "FWD-TORUS-1.0",
            0.1,
            4.0,
            0.01,
            ["OUT_OF_SCOPE"],
            [guard_schema, guard_schema],
        )
        self.assertFalse(report["passed"])
        self.assertFalse(report["guards"]["R_ZERO"]["passed"])
        self.assertEqual(
            report["guards"]["T_B_ZERO"]["scope"],
            "trigger_pre_capture_and_root",
        )
        self.assertTrue(report["guards"]["T_B_ZERO"]["passed"])

    def test_event_guard_budget_rejects_root_missing_from_trigger_set(self):
        time = np.array([0.0, 0.1, 0.2])
        series = {
            "R_ZERO": np.ones(3),
            "T_A_ZERO": np.full(3, 5.0),
            "T_B_ZERO": np.array([1.0, 0.8, 0.6]),
            "T_LOWER_ZERO": np.full(3, 5.0),
        }
        scales = {name: 1.0 for name in series}
        guard_schema = {
            "components": set(series),
            "scales": dict(scales),
            "minima": None,
            "aggregates": None,
            "custom_names": set(),
            "elements": None,
        }
        zero_tolerance = 1024.0 * np.finfo(float).eps

        def level():
            return SimulationResult(
                model_id="FWD-TORUS-1.0",
                contract_status=["OUT_OF_SCOPE"],
                numerical_status="SUCCESS_EVENT",
                tau=0.3,
                returned_interval="[0,0.3)",
                time=time.copy(),
                events=[
                    {
                        "kind": "physical_exit",
                        "triggers": ["T_B_ZERO"],
                        "guard_values": {
                            "R_ZERO": 0.0,
                            "T_A_ZERO": 5.0,
                            "T_B_ZERO": 0.0,
                            "T_LOWER_ZERO": 5.0,
                        },
                        "guard_zero_tolerances": {
                            "T_B_ZERO": zero_tolerance
                        },
                    }
                ],
                diagnostics={
                    "sampled_guard_component_series": {
                        name: values.copy() for name, values in series.items()
                    },
                    "guard_component_scales": dict(scales),
                },
                metadata={"event_cluster_tolerance": 1e-9},
            )

        report = _guard_error_budget(
            [level(), level()],
            "FWD-TORUS-1.0",
            0.1,
            4.0,
            0.01,
            ["OUT_OF_SCOPE"],
            [guard_schema, guard_schema],
        )
        self.assertFalse(report["passed"])
        self.assertFalse(report["guards"]["R_ZERO"]["passed"])
        self.assertEqual(
            report["guards"]["R_ZERO"]["fine_event_guard_value"],
            0.0,
        )

    def test_cable_event_signature_maps_material_location_across_meshes(self):
        def level(elements, trigger):
            return SimulationResult(
                model_id="FWD-CABLE-1.0",
                contract_status=["OUT_OF_SCOPE"],
                numerical_status="SUCCESS_EVENT",
                tau=0.1,
                returned_interval="[0,0.1)",
                time=np.array([0.0, 0.05]),
                events=[
                    {
                        "kind": "physical_exit",
                        "triggers": [trigger],
                    }
                ],
                metadata={"elements": elements},
            )

        coarse = level(
            {"A": 2, "B": 2, "lower": 2},
            "LAMBDA_MIN:A:element:0",
        )
        fine = level(
            {"A": 4, "B": 4, "lower": 4},
            "LAMBDA_MIN:A:element:1",
        )
        self.assertTrue(
            _event_sets_stable(
                [coarse, fine],
                "FWD-CABLE-1.0",
            )
        )
        fine.events[0]["triggers"] = ["LAMBDA_MIN:A:element:3"]
        self.assertFalse(
            _event_sets_stable(
                [coarse, fine],
                "FWD-CABLE-1.0",
            )
        )


if __name__ == "__main__":
    unittest.main()

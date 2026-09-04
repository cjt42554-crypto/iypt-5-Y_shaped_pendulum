from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from y_pendulum_forward.cable import (
    CableFEM,
    _collect_rooted_guard_triggers,
    _sample_cable,
    parse_cable_physical,
)
from y_pendulum_forward.contracts import THEORY_SHA256, load_json
from y_pendulum_forward.runner import run_config


ROOT = Path(__file__).resolve().parents[1]


class CableTests(unittest.TestCase):
    def setUp(self):
        self.config = load_json(ROOT / "configs" / "cable_example.json")
        # Unit tests use a deliberately small mesh.  The production example
        # remains the independently refinement-qualified finest mesh.
        self.config["numerics"]["elements"] = {
            "A": 2,
            "B": 2,
            "lower": 2,
        }
        self.config["numerics"]["quadrature_order"] = 3

    def _model(self, config=None):
        config = deepcopy(config or self.config)
        issues, physical = parse_cable_physical(config)
        self.assertEqual(issues, [])
        model = CableFEM(physical, config["numerics"])
        self.assertEqual(model.numerical_issues, [])
        return model

    def test_mass_is_symmetric_positive_and_point_masses_once(self):
        model = self._model()
        np.testing.assert_allclose(model.mass, model.mass.T, atol=0.0)
        self.assertGreater(np.linalg.eigvalsh(model.M_ff)[0], 0.0)
        total_expected = (
            sum(model.p.branches[name].mu * model.p.branches[name].L0 for name in ("A", "B", "lower"))
            + model.p.junction_mass
            + model.p.bob_mass
        )
        self.assertAlmostEqual(float(np.sum(model.mass)), total_expected, places=14)

    def test_internal_residual_is_axial_energy_gradient(self):
        model = self._model()
        positions = model.initial_positions.copy()
        velocities = np.zeros_like(positions)
        _applied, internal, detail = model.assemble(0.0, positions, velocities, diagnostics=True)
        step = 2e-7
        numerical_gradient = np.zeros_like(positions)
        for node in model.free:
            for coordinate in range(3):
                plus = positions.copy()
                minus = positions.copy()
                plus[node, coordinate] += step
                minus[node, coordinate] -= step
                energy_plus = model.assemble(0.0, plus, velocities, diagnostics=True)[2]["V_ax"]
                energy_minus = model.assemble(0.0, minus, velocities, diagnostics=True)[2]["V_ax"]
                numerical_gradient[node, coordinate] = (energy_plus - energy_minus) / (2 * step)
        np.testing.assert_allclose(internal[model.free], numerical_gradient[model.free], rtol=2e-7, atol=2e-8)
        self.assertGreaterEqual(detail["D_ax"], -1e-14)

    def test_short_whole_run_and_energy_power_account(self):
        config = deepcopy(self.config)
        config["physical"]["T"] = 0.04
        config["numerics"]["elements"] = {"A": 2, "B": 2, "lower": 2}
        config["numerics"]["max_step"] = 0.0005
        config["numerics"]["output_dt"] = 0.0005
        config["observation"]["record_times"]["stop"] = 0.04
        result = run_config(config)
        self.assertEqual(result.contract_status, ["COMPLETED"])
        self.assertTrue(result.numerical_status.startswith("SUCCESS"))
        self.assertLess(result.diagnostics["max_relative_energy_power_residual_algebraic_reaction"], 2e-6)
        self.assertGreaterEqual(result.diagnostics["min_D_ax"], -1e-13)
        self.assertGreaterEqual(result.diagnostics["min_D_string"], -1e-13)
        self.assertGreaterEqual(result.diagnostics["min_D_b"], -1e-13)
        self.assertEqual(result.observations["status"], ["OBSERVATION_INPUT_VALID"])

    def test_multiple_physical_input_failures_are_aggregated(self):
        config = deepcopy(self.config)
        config["physical"]["g"] = -1.0
        config["physical"]["bob_mass"] = 0.0
        config["physical"]["gravty_typo"] = 9.8
        result = run_config(config)
        self.assertEqual(result.contract_status, ["INVALID_INPUT"])
        codes = [item["code"] for item in result.events[0]["failures"]]
        self.assertIn("UNKNOWN_FIELD", codes)
        self.assertGreaterEqual(codes.count("SIGN"), 2)

    def test_exact_theory_identity_is_required(self):
        self.assertEqual(self.config["theory_sha256"], THEORY_SHA256)

    def test_unknown_physical_field_is_not_silently_ignored(self):
        config = deepcopy(self.config)
        config["physical"]["gravty_typo"] = 9.8
        result = run_config(config)
        self.assertEqual(result.contract_status, ["INVALID_INPUT"])
        self.assertTrue(
            any(
                item["code"] == "UNKNOWN_FIELD"
                for item in result.events[0]["failures"]
            )
        )

    def test_unknown_or_malformed_numerical_field_is_rejected_without_crash(self):
        unknown = deepcopy(self.config)
        unknown["numerics"]["rtlo"] = 1e-8
        result = run_config(unknown)
        self.assertEqual(result.contract_status, [])
        self.assertEqual(result.numerical_status, "INVALID_NUMERICAL_CONFIG")

        for malformed_method in ([], {}):
            malformed = deepcopy(self.config)
            malformed["numerics"]["method"] = malformed_method
            malformed["observation"] = None
            result = run_config(malformed)
            self.assertEqual(result.contract_status, [])
            self.assertEqual(
                result.numerical_status,
                "INVALID_NUMERICAL_CONFIG",
            )
            self.assertEqual(
                result.metadata["numerical_model_id"],
                "NUM-FWD-CABLE-P1-UNRESOLVED-1.0",
            )

        excessive_mesh = deepcopy(self.config)
        excessive_mesh["numerics"]["elements"] = {
            "A": 513,
            "B": 1,
            "lower": 1,
        }
        result = run_config(excessive_mesh)
        self.assertEqual(result.contract_status, [])
        self.assertEqual(result.numerical_status, "INVALID_NUMERICAL_CONFIG")

        excessive_static = deepcopy(self.config)
        excessive_static["numerics"]["static_multistart"] = 33
        result = run_config(excessive_static)
        self.assertEqual(result.contract_status, [])
        self.assertEqual(result.numerical_status, "INVALID_NUMERICAL_CONFIG")

    def test_unhashable_enum_values_are_structurally_rejected(self):
        mutations = (
            lambda config: config["initial_state"].update(mode=[]),
            lambda config: config["inputs"].update(
                exit_guards=[{"kind": {}, "name": "bad"}]
            ),
            lambda config: config["inputs"].update(
                support_A={"kind": []}
            ),
            lambda config: config["inputs"].update(
                air_velocity={"kind": {}}
            ),
            lambda config: config["inputs"].update(
                junction_force={"kind": []}
            ),
            lambda config: config["inputs"]["distributed_forces"].update(
                A={"kind": {}}
            ),
        )
        for mutate in mutations:
            config = deepcopy(self.config)
            mutate(config)
            result = run_config(config)
            self.assertEqual(result.contract_status, ["INVALID_INPUT"])
            self.assertEqual(result.numerical_status, "INPUT_REJECTED")

    def test_strings_and_booleans_are_not_coerced_in_vector_or_field_inputs(self):
        vector = deepcopy(self.config)
        vector["physical"]["e_z"] = ["0", "0", "1"]
        result = run_config(vector)
        self.assertEqual(result.contract_status, ["INVALID_INPUT"])

        field = deepcopy(self.config)
        field["initial_state"]["branches"]["A"]["position"][
            "coefficients"
        ][0][0] = False
        result = run_config(field)
        self.assertEqual(result.contract_status, ["INVALID_INPUT"])
        self.assertTrue(
            any(
                item["code"] == "INITIAL_FIELD_TYPE"
                for item in result.events[0]["failures"]
            )
        )

        malformed = deepcopy(self.config)
        malformed["numerics"]["static_energy_tolerance"] = "bad"
        result = run_config(malformed)
        self.assertEqual(result.contract_status, [])
        self.assertEqual(result.numerical_status, "INVALID_NUMERICAL_CONFIG")

        below_machine_floor = deepcopy(self.config)
        below_machine_floor["numerics"]["rtol"] = 1e-40
        result = run_config(below_machine_floor)
        self.assertEqual(result.contract_status, [])
        self.assertEqual(result.numerical_status, "INVALID_NUMERICAL_CONFIG")

    def test_nonpositive_initial_exit_guard_is_physical_invalid_input(self):
        config = deepcopy(self.config)
        config["inputs"]["exit_guards"] = [
            {
                "kind": "bob_plane",
                "name": "already_outside",
                "normal": [0.0, 0.0, 1.0],
                "offset": -0.66,
            }
        ]
        result = run_config(config)
        self.assertEqual(result.contract_status, ["INVALID_INPUT"])
        self.assertEqual(result.numerical_status, "INPUT_REJECTED")
        self.assertTrue(
            any(
                item["code"] == "INITIAL_GUARD"
                for item in result.events[0]["failures"]
            )
        )

    def test_numerical_config_failure_does_not_become_physical_invalid_input(self):
        config = deepcopy(self.config)
        config["numerics"]["elements"]["A"] = 0
        result = run_config(config)
        self.assertEqual(result.contract_status, [])
        self.assertEqual(result.numerical_status, "INVALID_NUMERICAL_CONFIG")

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

    def test_shared_y_topology_is_exact(self):
        model = self._model()
        junction = model.node_index["junction"]
        self.assertEqual(model.branch_nodes["A"][-1], junction)
        self.assertEqual(model.branch_nodes["B"][-1], junction)
        self.assertEqual(model.branch_nodes["lower"][0], junction)
        self.assertEqual(model.branch_nodes["lower"][-1], model.node_index["bob"])

    def test_static_hold_release_uses_frozen_potential_and_zero_velocity(self):
        config = deepcopy(self.config)
        config["physical"]["T"] = 0.005
        config["numerics"]["elements"] = {"A": 2, "B": 2, "lower": 2}
        config["numerics"]["max_step"] = 0.0005
        config["numerics"]["output_dt"] = 0.001
        config["numerics"]["static_multistart"] = 3
        config["initial_state"] = {
            "mode": "STATIC_HOLD_RELEASE",
            "hold": {
                "fixed_nodes": {
                    "junction": [0.0, 0.0, 0.25],
                    "bob": [0.035, 0.02, 0.58],
                }
            },
            "seed": {"r_J": [0.0, 0.0, 0.25], "r_m": [0.035, 0.02, 0.58]},
        }
        config["observation"] = None
        result = run_config(config)
        self.assertEqual(result.contract_status, ["COMPLETED"])
        self.assertEqual(result.diagnostics["preparation"]["mode"], "STATIC_HOLD_RELEASE")
        self.assertLess(result.diagnostics["preparation"]["selected_gradient_inf"], 1e-5)
        np.testing.assert_allclose(result.state["node_velocities"][0], 0.0, atol=0.0)

    def test_static_hold_gradient_threshold_is_not_ignored(self):
        config = deepcopy(self.config)
        config["physical"]["T"] = 0.005
        config["numerics"]["elements"] = {"A": 2, "B": 2, "lower": 2}
        config["numerics"]["static_multistart"] = 3
        config["numerics"]["static_gradient_tolerance"] = 1e-30
        config["initial_state"] = {
            "mode": "STATIC_HOLD_RELEASE",
            "hold": {
                "fixed_nodes": {
                    "junction": [0.0, 0.0, 0.25],
                    "bob": [0.035, 0.02, 0.58],
                }
            },
            "seed": {
                "r_J": [0.0, 0.0, 0.25],
                "r_m": [0.035, 0.02, 0.58],
            },
        }
        config["observation"] = None
        result = run_config(config)
        self.assertEqual(result.contract_status, [])
        self.assertEqual(result.numerical_status, "NUMERICAL_SETUP_UNRESOLVED")

    def test_internal_force_is_translation_covariant(self):
        model = self._model()
        positions = model.initial_positions.copy()
        velocities = model.initial_velocities.copy()
        internal = model.assemble(0.0, positions, velocities)[1]
        shift = np.array([1.7, -0.8, 2.1])
        shifted_internal = model.assemble(0.0, positions + shift, velocities)[1]
        np.testing.assert_allclose(shifted_internal, internal, rtol=0.0, atol=1e-13)

    def test_moving_support_mass_coupling_is_present(self):
        config = deepcopy(self.config)
        amplitude = np.array([0.002, 0.0, 0.0])
        base_support = np.array(config["inputs"]["support_A"]["value"], dtype=float)
        config["inputs"]["support_A"] = {
            "kind": "harmonic",
            "offset": (base_support - amplitude).tolist(),
            "amplitude": amplitude.tolist(),
            "omega": 3.0,
            "phase": float(np.pi / 2),
        }
        model = self._model(config)
        positions, velocities = model.full_state(0.0, model.y0)
        applied, internal, _ = model.assemble(0.0, positions, velocities)
        actual_acceleration = model.acceleration(0.0, positions, velocities)[0][model.free]
        omitted_coupling = np.column_stack(
            [
                np.linalg.solve(model.M_ff, (applied - internal)[model.free, coordinate])
                for coordinate in range(3)
            ]
        )
        expected_difference = np.column_stack(
            [
                np.linalg.solve(
                    model.M_ff,
                    -(model.M_fp @ model.support_acceleration(0.0))[:, coordinate],
                )
                for coordinate in range(3)
            ]
        )
        np.testing.assert_allclose(actual_acceleration - omitted_coupling, expected_difference, rtol=1e-12, atol=1e-12)
        self.assertGreater(np.linalg.norm(expected_difference), 0.0)

    def test_slack_to_taut_transition_keeps_one_continuous_state(self):
        config = deepcopy(self.config)
        config["physical"]["T"] = 0.12
        config["numerics"]["elements"] = {"A": 2, "B": 2, "lower": 3}
        config["numerics"]["max_step"] = 0.001
        config["numerics"]["output_dt"] = 0.001
        config["initial_state"]["r_m"] = [0.0, 0.0, 0.55]
        config["initial_state"]["branches"]["lower"]["position"]["coefficients"] = [
            [0.0, 0.0, 0.25],
            [0.0, 0.0, 0.30],
        ]
        config["observation"] = None
        result = run_config(config)
        lower = result.derived["branches"]["lower"]
        self.assertTrue(np.all(lower["slack"][0]))
        self.assertTrue(np.any(lower["active"]))
        self.assertEqual(result.events, [])
        # The transition is a force-law switch, not an impact reset.
        self.assertLess(np.max(np.linalg.norm(np.diff(result.state["v_m"], axis=0), axis=1)), 0.05)

    def test_custom_exit_guard_returns_half_open_interval(self):
        config = deepcopy(self.config)
        config["physical"]["T"] = 0.1
        config["numerics"]["elements"] = {"A": 2, "B": 2, "lower": 2}
        config["numerics"]["max_step"] = 0.0005
        config["inputs"]["exit_guards"] = [
            {
                "kind": "bob_plane",
                "name": "floor",
                "normal": [0.0, 0.0, -1.0],
                "offset": 0.59,
            }
        ]
        config["observation"] = None
        result = run_config(config)
        self.assertEqual(result.contract_status, ["OUT_OF_SCOPE"])
        self.assertLess(result.tau, config["physical"]["T"])
        self.assertLess(float(result.time[-1]), result.tau)
        self.assertIn("EXIT_GUARD:floor", result.events[0]["triggers"])
        self.assertIn("derived_left", result.events[0])
        self.assertIn("branches", result.events[0]["derived_left"])

    def test_small_positive_unrelated_guard_is_not_reported_as_simultaneous(self):
        config = deepcopy(self.config)
        config["physical"]["T"] = 0.1
        config["numerics"]["elements"] = {"A": 2, "B": 2, "lower": 2}
        config["numerics"]["max_step"] = 0.0005
        config["inputs"]["exit_guards"] = [
            {
                "kind": "bob_plane",
                "name": "floor",
                "normal": [0.0, 0.0, -1.0],
                "offset": 0.59,
            },
            {
                "kind": "node_distance",
                "name": "positive_margin",
                "node_1": "support_A",
                "node_2": "support_B",
                "minimum": 0.2999995,
            },
        ]
        config["observation"] = None
        result = run_config(config)
        self.assertEqual(result.contract_status, ["OUT_OF_SCOPE"])
        self.assertIn("EXIT_GUARD:floor", result.events[0]["triggers"])
        self.assertNotIn(
            "EXIT_GUARD:positive_margin", result.events[0]["triggers"]
        )

    def test_identical_simultaneous_custom_guards_are_both_reported(self):
        config = deepcopy(self.config)
        config["physical"]["T"] = 0.1
        config["numerics"]["elements"] = {"A": 2, "B": 2, "lower": 2}
        config["numerics"]["max_step"] = 0.0005
        config["inputs"]["exit_guards"] = [
            {
                "kind": "bob_plane",
                "name": name,
                "normal": [0.0, 0.0, -1.0],
                "offset": 0.59,
            }
            for name in ("floor_1", "floor_2")
        ]
        config["observation"] = None
        result = run_config(config)
        self.assertEqual(result.contract_status, ["OUT_OF_SCOPE"])
        self.assertEqual(
            set(result.events[0]["triggers"]),
            {"EXIT_GUARD:floor_1", "EXIT_GUARD:floor_2"},
        )

    def test_large_rate_margin_does_not_inflate_material_root_tie(self):
        components = {
            "lambda": {},
            "custom": {},
            "material": {
                "A": {
                    "lambda_lower": np.array([0.0, 0.2]),
                    "lambda_upper": np.array([0.4, 0.6]),
                    "rate_lower": np.array([1e16, 1e16]),
                    "rate_upper": np.array([1e16, 1e16]),
                }
            },
        }
        triggers = _collect_rooted_guard_triggers(
            components,
            ["MATERIAL_DOMAIN"],
            {
                "lambda": {},
                "material": {
                    "A": {
                        "lambda_lower": 1.0,
                        "lambda_upper": 1.0,
                        "rate_lower": 1e16,
                        "rate_upper": 1e16,
                    }
                },
                "custom": {},
            },
        )
        self.assertEqual(
            triggers, ["MATERIAL_DOMAIN:A:lambda_lower:element:0"]
        )

    def test_large_unrelated_custom_margin_does_not_inflate_zero_tolerance(self):
        components = {
            "lambda": {},
            "material": {},
            "custom": {
                "root": 0.0,
                "small_positive": 5e-7,
                "huge_positive": 1e16,
            },
        }
        triggers = _collect_rooted_guard_triggers(
            components,
            ["EXIT_GUARD:root"],
            {
                "lambda": {},
                "material": {},
                "custom": {
                    "root": 0.3,
                    "small_positive": 0.3,
                    "huge_positive": 0.3,
                },
            },
        )
        self.assertEqual(triggers, ["EXIT_GUARD:root"])

    def test_cross_family_simultaneous_machine_zeros_are_all_reported(self):
        components = {
            "lambda": {"A": np.array([0.0])},
            "material": {
                "A": {
                    "lambda_lower": np.array([0.0]),
                    "lambda_upper": np.array([0.5]),
                    "rate_lower": np.array([10.0]),
                    "rate_upper": np.array([10.0]),
                }
            },
            "custom": {"contact": 0.0},
        }
        scales = {
            "lambda": {"A": 1.0},
            "material": {
                "A": {
                    "lambda_lower": 1.0,
                    "lambda_upper": 1.0,
                    "rate_lower": 50.0,
                    "rate_upper": 50.0,
                }
            },
            "custom": {"contact": 0.3},
        }
        triggers = _collect_rooted_guard_triggers(
            components,
            ["LAMBDA_MIN"],
            scales,
        )
        self.assertEqual(
            triggers,
            [
                "EXIT_GUARD:contact",
                "LAMBDA_MIN:A:element:0",
                "MATERIAL_DOMAIN:A:lambda_lower:element:0",
            ],
        )

    def test_support_motion_overflow_is_physical_invalid_input(self):
        config = deepcopy(self.config)
        config["physical"]["T"] = 1e308
        config["inputs"]["support_A"] = {
            "kind": "harmonic",
            "offset": [-0.15, 0.0, 0.0],
            "amplitude": [0.0, 0.0, 0.0],
            "omega": 1e308,
            "phase": 0.0,
        }
        config["observation"] = None
        result = run_config(config)
        self.assertEqual(result.contract_status, ["INVALID_INPUT"])
        self.assertEqual(result.numerical_status, "INPUT_REJECTED")
        self.assertTrue(
            any(
                failure["code"] == "PROVIDER_WINDOW"
                for failure in result.events[0]["failures"]
            )
        )

    def test_postrun_guard_failure_keeps_only_samples_strictly_before_detection(self):
        config = deepcopy(self.config)
        config["physical"]["T"] = 0.004
        config["numerics"]["max_step"] = 0.0005
        config["numerics"]["output_dt"] = 0.001
        config["observation"] = None
        call_count = 0
        detected_bob = None

        def inject_late_sample_failure(model, time, samples, **kwargs):
            nonlocal call_count, detected_bob
            state, derived, diagnostics = _sample_cable(
                model, time, samples, **kwargs
            )
            if call_count == 0:
                self.assertGreater(time.size, 2)
                detected_bob = np.asarray(state["r_m"][2]).copy()
                diagnostics["sampled_guard_violation"] = {
                    "time": float(time[2]),
                    "sample_index": 2,
                    "triggers": ["EXIT_GUARD:synthetic_tangent"],
                }
            call_count += 1
            return state, derived, diagnostics

        with patch(
            "y_pendulum_forward.cable._sample_cable",
            side_effect=inject_late_sample_failure,
        ):
            result = run_config(config)
        self.assertEqual(result.contract_status, [])
        self.assertEqual(result.numerical_status, "EVENT_UNRESOLVED")
        self.assertEqual(result.tau, 0.002)
        np.testing.assert_allclose(result.time, [0.0, 0.001])
        self.assertTrue(np.all(result.time < result.tau))
        np.testing.assert_allclose(
            result.events[0]["detected_sample_state"]["r_m"],
            detected_bob,
        )
        self.assertEqual(call_count, 2)

    def test_force_envelope_overflow_is_physical_invalid_input(self):
        config = deepcopy(self.config)
        config["inputs"]["bob_force"] = {
            "kind": "harmonic",
            "offset": [1e308, 0.0, 0.0],
            "amplitude": [1e308, 0.0, 0.0],
            "omega": 0.0,
            "phase": -1.5707963267948966,
        }
        config["observation"] = None
        result = run_config(config)
        self.assertEqual(result.contract_status, ["INVALID_INPUT"])
        self.assertTrue(
            any(
                failure["code"] == "PROVIDER_WINDOW"
                and failure["path"] == "inputs.bob_force"
                for failure in result.events[0]["failures"]
            )
        )

    def test_air_time_envelope_overflow_is_physical_invalid_input(self):
        config = deepcopy(self.config)
        config["physical"]["T"] = 2.0
        config["inputs"]["air_velocity"] = {
            "kind": "affine",
            "offset": [1e308, 0.0, 0.0],
            "matrix": [[0.0, 0.0, 0.0]] * 3,
            "time_rate": [1e308, 0.0, 0.0],
        }
        config["observation"] = None
        result = run_config(config)
        self.assertEqual(result.contract_status, ["INVALID_INPUT"])
        self.assertTrue(
            any(
                failure["code"] == "PROVIDER_WINDOW"
                and failure["path"] == "inputs.air_velocity"
                for failure in result.events[0]["failures"]
            )
        )

    def test_upper_branch_label_exchange_preserves_bob_trajectory(self):
        base = deepcopy(self.config)
        base["physical"]["T"] = 0.02
        base["numerics"]["elements"] = {"A": 2, "B": 2, "lower": 2}
        base["numerics"]["max_step"] = 0.0005
        base["numerics"]["output_dt"] = 0.0005
        base["observation"] = None
        exchanged = deepcopy(base)
        exchanged["physical"]["branches"]["A"], exchanged["physical"]["branches"]["B"] = (
            exchanged["physical"]["branches"]["B"],
            exchanged["physical"]["branches"]["A"],
        )
        exchanged["inputs"]["support_A"], exchanged["inputs"]["support_B"] = (
            exchanged["inputs"]["support_B"],
            exchanged["inputs"]["support_A"],
        )
        exchanged["inputs"]["distributed_forces"]["A"], exchanged["inputs"]["distributed_forces"]["B"] = (
            exchanged["inputs"]["distributed_forces"]["B"],
            exchanged["inputs"]["distributed_forces"]["A"],
        )
        exchanged["initial_state"]["branches"]["A"], exchanged["initial_state"]["branches"]["B"] = (
            exchanged["initial_state"]["branches"]["B"],
            exchanged["initial_state"]["branches"]["A"],
        )
        original_result = run_config(base)
        exchanged_result = run_config(exchanged)
        np.testing.assert_allclose(
            exchanged_result.state["r_m"],
            original_result.state["r_m"],
            rtol=2e-11,
            atol=2e-12,
        )


if __name__ == "__main__":
    unittest.main()

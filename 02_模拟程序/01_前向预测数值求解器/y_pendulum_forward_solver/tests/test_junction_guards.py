"""J3 event-classification and fail-closed guard regressions."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from y_pendulum_forward.contracts import load_json
from y_pendulum_forward.junction import (
    _audit_dense_guards,
    validate_junction_config,
)
from y_pendulum_forward.runner import run_config


PROJECT = Path(__file__).resolve().parents[1]


def first_upper_a_loss_config():
    """Return a deterministic positive-tension input whose first exit is T_A=0."""

    config = load_json(PROJECT / "configs/junction_example.json")
    config["physical"].update(
        {
            "T": 1.0,
            "initial_state": [
                0.12040829855911506,
                -2.981024009140075,
                -0.04531561866814682,
                -0.56573993779363,
                -0.8233376084511037,
                -4.244000641003405,
                -1.7858752587747921,
                1.4607136369538702,
            ],
            "obstacles": [],
        }
    )
    config["numerics"].update({"max_step": 0.005, "output_dt": 0.01})
    config["observation"] = None
    return config


class JunctionGuardTests(unittest.TestCase):
    def test_small_positive_unrelated_guard_is_not_a_simultaneous_event(self):
        config = first_upper_a_loss_config()
        # This plane has a 9.6e-10 m positive margin at the independently
        # located T_A exit.  The margin is intentionally below the dense-audit
        # length tolerance, but it never reaches contact before the run stops.
        config["physical"]["obstacles"] = [
            {
                "id": "nearby",
                "kind": "plane",
                "target": "bob",
                "point": [
                    -0.24760556838917844,
                    -0.47125917499846104,
                    -0.07100022425397015,
                ],
                "normal": [
                    0.7250151393442396,
                    0.5521106926476977,
                    -0.41173636077681086,
                ],
                "allowed_side": 1,
            }
        ]

        result = run_config(config)

        self.assertEqual(result.numerical_status, "SUCCESS_EVENT")
        self.assertEqual(result.contract_status, ["OUT_OF_SCOPE"])
        self.assertEqual(result.events[0]["triggers"], ["T_A_ZERO"])
        clearance = result.events[0]["guard_values"]["CONTACT_nearby"]
        tolerance = result.events[0]["guard_zero_tolerances"]["CONTACT_nearby"]
        self.assertGreater(clearance, 0.0)
        self.assertLess(clearance, tolerance)
        self.assertIn("accepted solver times", result.events[0]["root_bracket_basis"])

    def test_failed_dense_guard_minimization_is_numerically_unresolved(self):
        config = first_upper_a_loss_config()
        issues, params = validate_junction_config(config)
        self.assertEqual(issues, [])
        self.assertIsNotNone(params)
        assert params is not None

        class ConstantDenseSolution:
            t = np.array([0.0, 0.001])

            @staticmethod
            def sol(_time):
                return params.initial_state

        failed = SimpleNamespace(
            success=False,
            x=0.0005,
            fun=1.0,
            message="forced audit failure",
        )
        with patch(
            "y_pendulum_forward.junction.minimize_scalar", return_value=failed
        ):
            issue = _audit_dense_guards(
                params,
                ConstantDenseSolution(),
                ["T_A_ZERO", "T_B_ZERO", "T_LOWER_ZERO"],
                known_event_tau=np.inf,
                known_triggers=set(),
                event_tolerance=1.0e-9,
                rtol=1.0e-10,
            )

        self.assertIsNotNone(issue)
        assert issue is not None
        self.assertEqual(issue["numerical_status"], "EVENT_UNRESOLVED")
        self.assertEqual(issue["reason"], "guard minimum search failed")
        self.assertEqual(issue["root_bracket"], [0.0, 0.001])


if __name__ == "__main__":
    unittest.main()

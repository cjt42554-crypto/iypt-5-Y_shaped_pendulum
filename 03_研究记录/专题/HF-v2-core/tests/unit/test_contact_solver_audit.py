from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.optimize import minimize

from ypendulum_hfv2.audit.contact import ContactKKTThresholds, audit_kkt_arrays
from ypendulum_hfv2.statics import contact_solver

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads(
    (CANDIDATE_ROOT / "contracts" / "p3_acceptance_manifest.json").read_text(
        encoding="utf-8"
    )
)


def _thresholds() -> ContactKKTThresholds:
    contract = MANIFEST["kkt"]
    return ContactKKTThresholds(
        active_gap_max_m=contract["active_gap_max_m"],
        primal_penetration_max_m=contract["primal_penetration_max_m"],
        dual_negative_max_N=contract["dual_negative_max_N"],
        stationarity_absolute_max_N=contract["stationarity_absolute_max_N"],
        stationarity_force_scale_factor_max=contract[
            "stationarity_force_scale_factor_max"
        ],
        complementarity_absolute_max_N_m=contract[
            "complementarity_absolute_max_N_m"
        ],
        complementarity_energy_scale_factor_max=contract[
            "complementarity_energy_scale_factor_max"
        ],
        supported_multiplier_min_N=contract["supported_multiplier_min_N"],
        active_constraint_rank_relative_tolerance=contract[
            "active_constraint_rank_relative_tolerance"
        ],
    )


def test_one_dof_unilateral_quadratic_has_exact_slsqp_kkt_and_projected_hessian() -> None:
    stiffness = 7.0
    unconstrained_minimum = -0.3

    def objective(values: np.ndarray) -> tuple[float, np.ndarray]:
        offset = values[0] - unconstrained_minimum
        return 0.5 * stiffness * offset**2, np.array([stiffness * offset])

    result = minimize(
        objective,
        np.array([0.4]),
        method="SLSQP",
        jac=True,
        constraints={
            "type": "ineq",
            "fun": lambda values: values.copy(),
            "jac": lambda values: np.ones((1, values.size)),
        },
        options={"ftol": 1.0e-12, "maxiter": 3000, "disp": False},
    )
    assert result.success
    assert result.x[0] == pytest.approx(0.0, abs=1.0e-12)
    gradient = np.array([stiffness * (result.x[0] - unconstrained_minimum)])
    audit = audit_kkt_arrays(
        gradient_N=gradient,
        gaps_m=result.x,
        gap_jacobian=np.ones((1, 1)),
        force_scale_N=stiffness,
        energy_scale_N_m=stiffness,
        thresholds=_thresholds(),
    )
    assert audit.passed
    assert audit.active_constraint_rank == 1
    assert audit.supported_constraint_rank == 1
    assert audit.multipliers_N[0] == pytest.approx(
        -stiffness * unconstrained_minimum,
        abs=1.0e-12,
    )

    # The sole active row spans the one-dimensional coordinate space, so the
    # projected Lagrangian Hessian has a zero-dimensional tangent space.
    _, singular, right = np.linalg.svd(np.ones((1, 1)), full_matrices=True)
    rank = int(np.count_nonzero(singular > 1.0e-10 * singular[0]))
    tangent = right[rank:].T
    projected = tangent.T @ np.array([[stiffness]]) @ tangent
    assert tangent.shape == (1, 0)
    assert projected.shape == (0, 0)


def test_duplicate_gap_active_rows_fail_the_frozen_rank_gate() -> None:
    audit = audit_kkt_arrays(
        gradient_N=np.array([2.1]),
        gaps_m=np.array([0.0, 0.0]),
        gap_jacobian=np.array([[1.0], [1.0]]),
        force_scale_N=7.0,
        energy_scale_N_m=7.0,
        thresholds=_thresholds(),
    )
    assert audit.passed is False
    assert audit.active_indices.tolist() == [0, 1]
    assert audit.active_constraint_rank == 1


def test_slsqp_receives_only_the_frozen_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Assembly:
        def coordinates_from_seed(self, seed: object) -> SimpleNamespace:
            del seed
            return SimpleNamespace(values=np.array([0.0]))

        def coordinates_from_values(self, values: np.ndarray) -> SimpleNamespace:
            return SimpleNamespace(values=np.array(values, copy=True))

        def evaluate(self, coordinates: SimpleNamespace) -> SimpleNamespace:
            value = float(coordinates.values[0])
            return SimpleNamespace(
                total_potential=value**2,
                generalized_force=np.array([-2.0 * value]),
                gaps_m=np.array([value + 1.0]),
                gap_jacobian=np.ones((1, 1)),
            )

    def fake_minimize(objective: object, initial: np.ndarray, **kwargs: object) -> object:
        captured.update(kwargs)
        value, gradient = objective(initial)  # type: ignore[operator]
        assert value == 0.0
        np.testing.assert_array_equal(gradient, np.zeros(1))
        return SimpleNamespace(
            x=np.array(initial, copy=True),
            success=True,
            status=0,
            message="captured",
            nit=0,
            nfev=1,
            njev=1,
        )

    monkeypatch.setattr(contact_solver, "minimize", fake_minimize)
    settings = contact_solver.ContactSolverSettings("SLSQP", 1.0e-12, 3000)
    seed = SimpleNamespace(seed_id="capture")
    contact_solver.solve_contact_seed(Assembly(), seed, settings)  # type: ignore[arg-type]
    assert set(captured) == {"method", "jac", "constraints", "options"}
    assert captured["method"] == "SLSQP"
    assert captured["jac"] is True
    constraints = captured["constraints"]
    assert isinstance(constraints, dict)
    assert constraints["type"] == "ineq"
    assert callable(constraints["fun"])
    assert callable(constraints["jac"])
    assert captured["options"] == {
        "ftol": 1.0e-12,
        "maxiter": 3000,
        "disp": False,
    }

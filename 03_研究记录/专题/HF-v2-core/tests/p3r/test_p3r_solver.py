from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from ypendulum_hfv2_p3r import solver


def test_slsqp_receives_one_combined_inequality_vector_and_only_frozen_options(
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
                solver_inequality_residuals=np.array([value + 1.0, value + 0.25]),
                solver_inequality_jacobian=np.ones((2, 1)),
            )

    def fake_minimize(objective: object, initial: np.ndarray, **kwargs: object) -> object:
        captured.update(kwargs)
        value, gradient = objective(initial)  # type: ignore[operator]
        assert value == 0.0
        np.testing.assert_array_equal(gradient, np.zeros(1))
        constraints = kwargs["constraints"]
        assert isinstance(constraints, dict)
        np.testing.assert_array_equal(constraints["fun"](initial), np.array([1.0, 0.25]))
        np.testing.assert_array_equal(constraints["jac"](initial), np.ones((2, 1)))
        return SimpleNamespace(
            x=np.array(initial, copy=True),
            success=True,
            status=0,
            message="captured",
            nit=0,
            nfev=1,
            njev=1,
        )

    monkeypatch.setattr(solver, "minimize", fake_minimize)
    settings = solver.P3RSolverSettings("SLSQP", 1.0e-12, 3000)
    seed = SimpleNamespace(seed_id="capture")
    solver.solve_contact_seed(Assembly(), seed, settings)  # type: ignore[arg-type]
    assert set(captured) == {"method", "jac", "constraints", "options"}
    assert captured["method"] == "SLSQP"
    assert captured["jac"] is True
    assert captured["options"] == {"ftol": 1.0e-12, "maxiter": 3000, "disp": False}

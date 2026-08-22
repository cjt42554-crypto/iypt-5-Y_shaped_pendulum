from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ypendulum import analyze_linear_modes
from ypendulum.config import load_config
from ypendulum.models.analytic import predict_analytic
from ypendulum.models.full_cable import FullCableModel
from ypendulum.models.torus import simulate_torus
from ypendulum.solvers.dynamic import simulate_full
from ypendulum.solvers.static import solve_static_equilibrium


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = json.loads(
    (ROOT / "validation/regression/reference_summary.json").read_text(encoding="utf-8")
)


def test_saved_numeric_reference_manifest() -> None:
    analytic = predict_analytic(load_config(ROOT / "configs/examples/analytic_3to2.yaml"))
    assert np.isclose(
        analytic.frequency_ratio, REFERENCE["analytic"]["frequency_ratio"], rtol=1e-13
    )
    assert np.isclose(
        analytic.omega_fast, REFERENCE["analytic"]["omega_fast"], rtol=1e-12
    )
    assert np.isclose(
        analytic.omega_slow, REFERENCE["analytic"]["omega_slow"], rtol=1e-12
    )

    torus = simulate_torus(load_config(ROOT / "configs/examples/ideal_3to2.yaml"))
    assert np.allclose(torus.state[-1], REFERENCE["torus"]["final_state"], rtol=1e-9, atol=1e-10)
    assert np.allclose(
        torus.position[-1], REFERENCE["torus"]["final_position"], rtol=1e-9, atol=1e-10
    )

    cfg = load_config(ROOT / "configs/examples/convergence_smooth.yaml")
    model = FullCableModel(cfg)
    equilibrium = solve_static_equilibrium(cfg, model)
    result = simulate_full(cfg, model=model, equilibrium=equilibrium)
    modes = analyze_linear_modes(cfg, count=2)
    assert np.allclose(
        [mode["frequency_hz"] for mode in modes["modes"]],
        REFERENCE["h1"]["mode_frequencies_hz"],
        rtol=2e-7,
        atol=1e-9,
    )
    assert np.allclose(
        result.positions[-1, model.topology.bob_node],
        REFERENCE["h1"]["final_bob_position"],
        rtol=2e-7,
        atol=2e-9,
    )
    assert np.isclose(
        np.max(result.tension), REFERENCE["h1"]["maximum_tension_N"], rtol=2e-7
    )

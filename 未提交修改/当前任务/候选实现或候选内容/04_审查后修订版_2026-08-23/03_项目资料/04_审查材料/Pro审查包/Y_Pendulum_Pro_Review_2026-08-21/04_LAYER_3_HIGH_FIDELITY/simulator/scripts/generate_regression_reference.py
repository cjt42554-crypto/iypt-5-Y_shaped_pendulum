#!/usr/bin/env python3
"""Generate the small deterministic numerical regression manifest.

This script is intentionally not run automatically by tests.  Updating the
reference requires an explicit review of the physics/numerical change and the
generated diff.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ypendulum import analyze_linear_modes
from ypendulum.config import load_config
from ypendulum.io.provenance import json_safe
from ypendulum.models.analytic import predict_analytic
from ypendulum.models.full_cable import FullCableModel
from ypendulum.models.torus import simulate_torus
from ypendulum.solvers.dynamic import simulate_full
from ypendulum.solvers.static import solve_static_equilibrium


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    analytic_cfg = load_config(root / "configs/examples/analytic_3to2.yaml")
    analytic = predict_analytic(analytic_cfg)

    torus_cfg = load_config(root / "configs/examples/ideal_3to2.yaml")
    torus = simulate_torus(torus_cfg)

    full_cfg = load_config(root / "configs/examples/convergence_smooth.yaml")
    model = FullCableModel(full_cfg)
    equilibrium = solve_static_equilibrium(full_cfg, model)
    result = simulate_full(full_cfg, model=model, equilibrium=equilibrium)
    modes = analyze_linear_modes(full_cfg, count=2)

    payload = {
        "reference_format": "YP-FPSim deterministic regression v1",
        "analytic": {
            "omega_fast": analytic.omega_fast,
            "omega_slow": analytic.omega_slow,
            "frequency_ratio": analytic.frequency_ratio,
        },
        "torus": {
            "final_state": torus.state[-1].tolist(),
            "final_position": torus.position[-1].tolist(),
            "relative_energy_drift": float(
                np.max(np.abs(torus.energy - torus.energy[0]))
                / max(abs(float(torus.energy[0])), 1e-12)
            ),
        },
        "h1": {
            "static_force_residual_N": equilibrium.force_residual_max,
            "static_minimum_eigenvalue_s-2": equilibrium.metadata["stability"][
                "minimum_generalized_eigenvalue_s-2"
            ],
            "mode_frequencies_hz": [mode["frequency_hz"] for mode in modes["modes"]],
            "final_bob_position": result.positions[-1, model.topology.bob_node].tolist(),
            "maximum_tension_N": float(np.max(result.tension)),
            "maximum_energy_balance_residual": float(
                np.max(np.abs(result.energy["balance_residual"]))
            ),
        },
    }
    target = root / "validation/regression/reference_summary.json"
    target.write_text(json.dumps(json_safe(payload), indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()

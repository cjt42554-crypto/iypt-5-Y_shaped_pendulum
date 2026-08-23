from __future__ import annotations

import numpy as np

from ypendulum.config import load_config
from ypendulum.models.full_cable import FullCableModel


def test_uniform_air_power_and_relative_drag_close_the_aero_power_identity() -> None:
    """The air ledger must not disguise total drag power as external air work."""

    cfg = load_config("configs/examples/full_quick_3to2.yaml")
    cfg.environment.air_velocity = {
        "value": [0.25, -0.10, 0.05],
        "unit": "m/s",
    }
    cfg.bob.drag.enabled = True
    cfg.bob.drag.linear_coefficient = {"value": 0.03, "unit": "N*s/m"}
    cfg.junction.drag_linear = {"value": 0.02, "unit": "N*s/m"}
    cfg.cables.upper_A.drag_enabled = True
    cfg.cables.upper_B.drag_enabled = True
    cfg.cables.lower.drag_enabled = True

    model = FullCableModel(cfg)
    positions = model.topology.reference_positions.copy()
    velocities = np.zeros_like(positions)
    free_velocity = np.array([0.35, -0.22, 0.14])
    velocities[model.topology.free_nodes] = free_velocity
    q_free = model.topology.pack_free(positions)
    v_free = model.topology.pack_free(velocities)

    evaluation = model.evaluate(0.0, q_free, v_free)
    mechanical_aero_power = float(
        np.sum(evaluation.aero_force * evaluation.full_velocities)
    )

    assert evaluation.aero_relative_dissipation_rate > 0.0
    assert np.isclose(
        mechanical_aero_power,
        -evaluation.aero_relative_dissipation_rate + evaluation.aero_work_rate,
        rtol=2.0e-13,
        atol=2.0e-13,
    )


def test_still_air_has_zero_external_air_work_but_positive_drag_dissipation() -> None:
    cfg = load_config("configs/examples/full_quick_3to2.yaml")
    cfg.bob.drag.enabled = True
    cfg.bob.drag.linear_coefficient = {"value": 0.03, "unit": "N*s/m"}

    model = FullCableModel(cfg)
    positions = model.topology.reference_positions.copy()
    velocities = np.zeros_like(positions)
    velocities[model.topology.bob_node] = np.array([0.4, -0.2, 0.1])
    evaluation = model.evaluate(
        0.0,
        model.topology.pack_free(positions),
        model.topology.pack_free(velocities),
    )

    assert evaluation.aero_relative_dissipation_rate > 0.0
    assert evaluation.aero_work_rate == 0.0
    assert np.isclose(
        float(np.sum(evaluation.aero_force * evaluation.full_velocities)),
        -evaluation.aero_relative_dissipation_rate,
        rtol=2.0e-13,
        atol=2.0e-13,
    )

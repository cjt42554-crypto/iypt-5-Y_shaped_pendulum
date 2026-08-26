from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np


CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = CANDIDATE_ROOT.parents[2]
FORMAL_SRC = (
    REPOSITORY_ROOT
    / "02_模拟程序"
    / "02_第一性原理高保真模拟器"
    / "Y-Pendulum-Simulator-v1.0.0-rc1"
    / "src"
)


def _case() -> dict:
    return json.loads(
        (CANDIDATE_ROOT / "contracts" / "rc1_characterization_case.json").read_text(
            encoding="utf-8"
        )
    )


def test_frozen_rc1_local_taut_no_contact_characterization() -> None:
    sys.path.insert(0, str(FORMAL_SRC))
    try:
        from ypendulum.hf.model import (
            _passive_axial_kelvin_voigt_response,
            discrete_bending_energy_forces,
        )
    finally:
        sys.path.pop(0)

    data = _case()["input"]
    axial = data["axial"]
    extension = np.asarray(axial["extension_m"], dtype=float)
    extension_rate = np.asarray(axial["extension_rate_m_per_s"], dtype=float)
    stiffness = np.asarray(axial["stiffness_N_per_m"], dtype=float)
    viscosity = np.asarray(axial["viscosity_N_s_per_m"], dtype=float)
    signed_force, tension, stored_energy, dissipation = (
        _passive_axial_kelvin_voigt_response(
            extension,
            extension_rate,
            stiffness,
            viscosity,
            axial["compression_regularization_scale"],
        )
    )
    trial = stiffness * extension + viscosity * extension_rate
    assert np.all(extension > 0.0)
    assert np.all(trial > 0.0)
    np.testing.assert_array_equal(signed_force, tension)
    assert stored_energy > 0.0
    assert dissipation >= 0.0

    bending = data["bending"]
    points = np.asarray(bending["points_m"], dtype=float)
    energy, forces = discrete_bending_energy_forces(
        points,
        np.asarray(bending["segment_rest_length_m"], dtype=float),
        bending["bending_stiffness_N_m2"],
    )
    origin = np.array([0.17, -0.23, 0.31])
    assert energy > 0.0
    np.testing.assert_allclose(np.sum(forces, axis=0), 0.0, atol=2.0e-15)
    np.testing.assert_allclose(
        np.sum(np.cross(points - origin, forces), axis=0),
        0.0,
        atol=2.0e-15,
    )

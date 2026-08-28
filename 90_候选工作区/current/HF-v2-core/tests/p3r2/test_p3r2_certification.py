from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ypendulum_hfv2_p3r2.certification import (
    COORDINATE_IDS,
    COORDINATE_UNITS,
    STATIONARITY_UNITS,
    CharacteristicScales,
)
from ypendulum_hfv2_p3r2.kkt import (
    audit_kkt_arrays,
    component_allowed_raw,
    thresholds_from_manifest,
)

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads(
    (CANDIDATE_ROOT / "contracts" / "p3r2_acceptance_manifest.json").read_text(
        encoding="utf-8"
    )
)


def _scales() -> CharacteristicScales:
    return CharacteristicScales(
        length_m=2.0,
        force_N=4.0,
        energy_N_m=8.0,
        coordinate_scales=np.array([2.0, 2.0, 2.0, 1.0, 1.0, 1.0]),
        stationarity_scales=np.array([4.0, 4.0, 4.0, 8.0, 8.0, 8.0]),
    )


def test_component_scale_contract_separates_force_and_torque_units() -> None:
    scales = _scales()
    assert COORDINATE_IDS == tuple(
        MANIFEST["component_scale_contract"]["coordinate_ids"]
    )
    assert COORDINATE_UNITS == tuple(
        MANIFEST["component_scale_contract"]["coordinate_units"]
    )
    assert STATIONARITY_UNITS == tuple(
        MANIFEST["component_scale_contract"]["stationarity_units"]
    )
    np.testing.assert_array_equal(
        scales.stationarity_scales,
        np.array([4.0, 4.0, 4.0, 8.0, 8.0, 8.0]),
    )
    allowed = component_allowed_raw(scales, thresholds_from_manifest(MANIFEST))
    np.testing.assert_array_equal(
        allowed,
        np.array([1.0e-8, 1.0e-8, 1.0e-8, 2.0e-8, 2.0e-8, 2.0e-8]),
    )


def test_scaled_dual_intervals_use_the_componentwise_stationarity_bands() -> None:
    jacobian = np.array(
        [
            [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
        ]
    )
    audit = audit_kkt_arrays(
        gradient=np.array([1.0, 0.0, 2.0, 0.0, 0.0, 0.0]),
        gaps_m=np.zeros(2),
        gap_jacobian=jacobian,
        scales=_scales(),
        thresholds=thresholds_from_manifest(MANIFEST),
    )
    assert audit.passed
    assert audit.dual_interval_feasible
    np.testing.assert_allclose(audit.canonical_multipliers_N, np.array([1.0, 2.0]))
    np.testing.assert_allclose(
        audit.dual_interval_upper_N - audit.dual_interval_lower_N,
        np.array([2.0e-8, 2.0e-8]),
        rtol=1.0e-6,
        atol=1.0e-14,
    )

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import ypendulum_hfv2_p3r3.dual_certification as dual_module
from ypendulum_hfv2_p3r3.certification import CharacteristicScales
from ypendulum_hfv2_p3r3.dual_certification import certify_centered_dual

ROOT = Path(__file__).resolve().parents[2]


class _Contact:
    gaps_m = np.zeros(2)
    gap_jacobian = np.vstack([np.eye(6)[0], np.eye(6)[1]])


class _Evaluation:
    contact = _Contact()
    generalized_force = -np.array([2.0, 3.0, 0.0, 0.0, 0.0, 0.0])


def _manifest() -> dict[str, object]:
    return json.loads(
        (ROOT / "contracts/p3r3_acceptance_manifest.json").read_text(encoding="utf-8")
    )


def _scales() -> CharacteristicScales:
    return CharacteristicScales(
        length_m=1.0,
        force_N=1.0,
        energy_N_m=1.0,
        coordinate_scales=np.ones(6),
        stationarity_scales=np.ones(6),
    )


def test_centered_dual_matches_independent_rectangle_vertices() -> None:
    certificate = certify_centered_dual(
        _Evaluation(),
        np.array([0, 1]),
        np.array([2.0, 3.0]),
        _scales(),
        np.full(6, 1.0e-8),
        _manifest(),
    )
    assert certificate.passed
    assert certificate.status == "PASS"
    assert certificate.independent_vertex_count == 4
    assert np.allclose(certificate.backend_lower_N, [2.0 - 1.0e-8, 3.0 - 1.0e-8])
    assert np.allclose(certificate.backend_upper_N, [2.0 + 1.0e-8, 3.0 + 1.0e-8])
    assert certificate.endpoint_crosscheck_max_N <= 5.0e-9
    assert certificate.endpoint_minimum_slack >= -5.0e-12


def test_feasible_explicit_witness_and_backend_infeasible_is_internal_error(
    monkeypatch: object,
) -> None:
    def fake_linprog(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return SimpleNamespace(
            success=False,
            status=2,
            message="synthetic infeasible",
            nit=0,
            fun=None,
            x=None,
        )

    monkeypatch.setattr(dual_module, "linprog", fake_linprog)
    certificate = certify_centered_dual(
        _Evaluation(),
        np.array([0, 1]),
        np.array([2.0, 3.0]),
        _scales(),
        np.full(6, 1.0e-8),
        _manifest(),
    )
    assert certificate.witness_minimum_slack >= -5.0e-12
    assert not certificate.passed
    assert certificate.status == "CERTIFIER_INTERNAL_INCONSISTENCY"

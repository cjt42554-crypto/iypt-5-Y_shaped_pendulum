from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ypendulum_hfv2_p3r4.second_order import (
    richardson_direction_audit,
    tangent_directions,
)

ROOT = Path(__file__).resolve().parents[2]


def _contract() -> dict[str, object]:
    manifest = json.loads(
        (ROOT / "contracts/p3r4_acceptance_manifest.json").read_text(encoding="utf-8")
    )
    return manifest["second_order_numerics"]


def test_richardson_recovers_positive_curvature_with_resolved_second_order() -> None:
    steps = np.array([4.0e-4, 2.0e-4, 1.0e-4])
    curvatures = 2.0 + 3.0 * steps**2 + 5.0 * steps**4
    audit = richardson_direction_audit(
        "synthetic_quadratic_plus_even_error",
        steps,
        curvatures,
        np.full(3, 1.0e-14),
        _contract(),
    )
    assert audit.passed
    assert audit.order_status == "RESOLVED_ORDER_PASS"
    assert audit.observed_order is not None
    assert 1.9 < audit.observed_order < 2.1
    assert audit.curvature_lower_bound > 1.99


def test_richardson_fails_closed_when_positive_margin_is_not_certified() -> None:
    steps = np.array([4.0e-4, 2.0e-4, 1.0e-4])
    audit = richardson_direction_audit(
        "synthetic_near_zero",
        steps,
        np.full(3, 4.0e-4),
        np.full(3, 1.0e-8),
        _contract(),
    )
    assert not audit.passed
    assert audit.curvature_lower_bound < 5.0e-4


def test_tangent_direction_set_is_fixed_and_nonduplicated() -> None:
    basis = np.eye(6)[:, :3]
    directions = tangent_directions(basis)
    assert len(directions) == 9
    assert len({identity for identity, _ in directions}) == 9
    assert all(np.isclose(np.linalg.norm(direction), 1.0) for _, direction in directions)

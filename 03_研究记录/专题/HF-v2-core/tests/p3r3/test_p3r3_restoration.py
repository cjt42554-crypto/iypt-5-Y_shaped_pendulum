from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from ypendulum_hfv2_p3r3.cases import build_historical_cases
from ypendulum_hfv2_p3r3.certification import (
    characteristic_scales,
    deterministic_nullspace_basis,
)
from ypendulum_hfv2_p3r3.dual_certification import (
    audit_contact_kkt,
    thresholds_from_manifest,
)
from ypendulum_hfv2_p3r3.restoration import audit_full_composite_jacobian
from ypendulum_hfv2_p3r3.solver import settings_from_manifest

ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _sha256(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def test_deterministic_coordinate_projection_basis_is_orthonormal_and_signed() -> None:
    rows = np.array(
        [
            [1.0, 1.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        ]
    )
    basis = deterministic_nullspace_basis(rows, rank_relative_tolerance=1.0e-10)
    reordered = deterministic_nullspace_basis(
        rows[[2, 0, 1]] * np.array([[4.0], [2.0], [3.0]]),
        rank_relative_tolerance=1.0e-10,
    )
    assert basis.shape == (6, 3)
    assert np.allclose(rows @ basis, 0.0, atol=1.0e-12)
    assert np.allclose(basis.T @ basis, np.eye(3), atol=1.0e-12)
    assert np.allclose(basis, reordered, atol=1.0e-12)
    assert all(vector[np.argmax(np.abs(vector))] > 0.0 for vector in basis.T)


def test_full_residual_jacobian_closes_on_frozen_p3r_35_degree_history() -> None:
    manifest = _load("contracts/p3r3_acceptance_manifest.json")
    predecessor = _load("contracts/p3r2_acceptance_manifest.json")
    _, case = build_historical_cases(
        manifest,
        predecessor,
        adapter_contract_sha256=_sha256("contracts/p3r3_contact_adapter_contract.json"),
        frozen_protocol_sha256=_sha256("contracts/P3R3_FROZEN_PROTOCOL.md"),
    )
    coordinates = case.assembly.coordinates_from_values(case.expectation.reference_coordinates)
    evaluation = case.assembly.evaluate(coordinates)
    scales = characteristic_scales(case.assembly)
    kkt = audit_contact_kkt(
        case.assembly,
        evaluation,
        thresholds_from_manifest(manifest),
        scales,
    )
    audit = audit_full_composite_jacobian(
        case.assembly,
        coordinates,
        kkt.supported_indices,
        kkt.canonical_multipliers_N[kkt.supported_indices],
        scales,
        settings_from_manifest(manifest).restoration,
    )
    assert audit.passed
    assert audit.finest_pair_relative_difference <= 5.0e-4
    assert audit.quasi_to_full_relative_difference <= 5.0e-3

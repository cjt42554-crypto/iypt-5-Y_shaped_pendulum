from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from ypendulum_hfv2_p3r4.cases import build_historical_cases
from ypendulum_hfv2_p3r4.certification import (
    characteristic_scales,
    deterministic_tangent_basis,
)
from ypendulum_hfv2_p3r4.dual_certification import (
    audit_contact_kkt,
    thresholds_from_manifest,
)
from ypendulum_hfv2_p3r4.manifold import (
    audit_manifold_neighborhood,
    retract_to_manifold,
    settings_from_manifest,
)

ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _sha256(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def _historical_reference() -> tuple[dict[str, object], object, object, object, np.ndarray]:
    manifest = _load("contracts/p3r4_acceptance_manifest.json")
    p3r2 = _load("contracts/p3r2_acceptance_manifest.json")
    _, case = build_historical_cases(
        manifest,
        p3r2,
        adapter_contract_sha256=_sha256("contracts/p3r4_contact_adapter_contract.json"),
        frozen_protocol_sha256=_sha256("contracts/P3R4_FROZEN_PROTOCOL.md"),
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
    basis = deterministic_tangent_basis(
        case.assembly,
        evaluation,
        kkt.supported_indices,
        scales,
        rank_relative_tolerance=manifest["kkt"]["rank_relative_tolerance"],
    )
    return manifest, case, coordinates, evaluation, kkt.supported_indices, basis


def test_retraction_closes_active_gaps_gauge_and_tangent_coordinates() -> None:
    manifest, case, coordinates, _, supported, basis = _historical_reference()
    scales = characteristic_scales(case.assembly)
    target = np.array([1.0e-5, -7.0e-6, 4.0e-6])
    result = retract_to_manifold(
        case.assembly,
        coordinates,
        supported,
        basis,
        target,
        scales,
        settings_from_manifest(manifest),
    )
    assert result.converged
    assert np.linalg.norm(result.final_residual, ord=np.inf) <= 1.0e-11
    assert np.allclose(result.target_tangent_coordinates, target)


def test_historical_manifold_neighborhood_executes_all_frozen_probes() -> None:
    manifest, case, coordinates, evaluation, supported, basis = _historical_reference()
    audit = audit_manifold_neighborhood(
        case.assembly,
        coordinates,
        evaluation,
        supported,
        characteristic_scales(case.assembly),
        basis,
        manifest,
    )
    assert audit.direction_count_unoriented == 9
    assert audit.endpoint_retraction_count == 36
    assert len(audit.records) == 18
    assert all(
        endpoint["probe_role"] == "constraint_manifold_geometry_probe"
        for record in audit.records
        for endpoint in record["endpoints"]
    )

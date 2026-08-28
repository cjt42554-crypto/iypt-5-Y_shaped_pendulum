from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ypendulum_hfv2.contact import ContactGeometryError
from ypendulum_hfv2_p3r5.cases import build_design_case
from ypendulum_hfv2_p3r5.certification import characteristic_scales
from ypendulum_hfv2_p3r5.dual_certification import (
    audit_contact_kkt,
    component_kkt_finite,
    component_kkt_passed,
    thresholds_from_manifest,
)
from ypendulum_hfv2_p3r5.evidence_support import sha256
from ypendulum_hfv2_p3r5.reference import construct_reference, settings_from_manifest

ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _case(card: dict[str, object]) -> object:
    return build_design_case(
        _load("contracts/p3r5_acceptance_manifest.json"),
        _load("contracts/p3r4_acceptance_manifest.json"),
        card,
        adapter_contract_sha256=sha256(ROOT / "contracts/p3r5_contact_adapter_contract.json"),
        frozen_protocol_sha256=sha256(ROOT / "contracts/P3R5_FROZEN_PROTOCOL.md"),
    )


def _run(card: dict[str, object]) -> tuple[object, object]:
    manifest = _load("contracts/p3r5_acceptance_manifest.json")
    case = _case(card)
    result = construct_reference(
        case.assembly,
        case.initial_coordinates,
        case.declared_active_constraint_ids,
        settings_from_manifest(manifest),
        manifest,
    )
    return case, result


@pytest.mark.parametrize(
    ("source", "design_id"),
    [
        ("p3r3", "ASYM_A01"),
        ("p3r3", "ASYM_A03"),
        ("p3r3", "SCALE_S01"),
        ("p3r3", "SCALE_S02"),
        ("p3r3", "SCALE_S03"),
        ("p3r4", "R4_ASYM_B03"),
        ("p3r4", "R4_SCALE_T01"),
        ("p3r4", "R4_SCALE_T02"),
        ("p3r4", "R4_SCALE_T03"),
        ("p3r4", "R4_SCALE_T04"),
    ],
)
def test_observed_valid_development_cards_close_without_predecessor_solver(
    source: str,
    design_id: str,
) -> None:
    cards = _load(f"contracts/{source}_design_cards.json")["design_cards"]
    card = next(item for item in cards if item["design_id"] == design_id)
    _, result = _run(card)
    assert result.converged
    assert result.status == "CONVERGED_AT_ENTRY"
    assert np.linalg.norm(result.final_composite_residual, ord=np.inf) <= 1.0e-11
    assert result.jacobian_audit is not None and result.jacobian_audit.passed


def test_b03_separates_component_finiteness_from_obsolete_dual_intervals() -> None:
    manifest = _load("contracts/p3r5_acceptance_manifest.json")
    card = next(
        item
        for item in _load("contracts/p3r4_design_cards.json")["design_cards"]
        if item["design_id"] == "R4_ASYM_B03"
    )
    old_outcome = next(
        item
        for item in _load("reports/p3r4_admissibility_metrics.json")["outcomes"]
        if item["design_id"] == "R4_ASYM_B03"
    )
    case = _case(card)
    old_coordinates = case.assembly.coordinates_from_values(
        np.asarray(old_outcome["reference_coordinates"], dtype=float)
    )
    evaluation = case.assembly.evaluate(old_coordinates)
    thresholds = thresholds_from_manifest(manifest)
    kkt = audit_contact_kkt(
        case.assembly,
        evaluation,
        thresholds,
        characteristic_scales(case.assembly),
    )
    assert not kkt.finite
    assert np.isnan(kkt.dual_interval_lower_N[kkt.supported_indices]).all()
    assert component_kkt_finite(kkt, evaluation)
    assert component_kkt_passed(kkt, thresholds, evaluation)


def test_observed_invalid_development_cards_fail_closed_without_retry() -> None:
    p3r3 = _load("contracts/p3r3_design_cards.json")["design_cards"]
    p3r4 = _load("contracts/p3r4_design_cards.json")["design_cards"]
    for source, design_id in (
        (p3r3, "ASYM_A02"),
        (p3r4, "R4_ASYM_B01"),
        (p3r4, "R4_ASYM_B04"),
    ):
        card = next(item for item in source if item["design_id"] == design_id)
        _, result = _run(card)
        assert not result.converged
        assert result.status == "FAIL_CLOSED_INITIAL_DOMAIN"
        assert result.iterations == 0
    b02 = next(item for item in p3r4 if item["design_id"] == "R4_ASYM_B02")
    with pytest.raises(ContactGeometryError):
        _case(b02)

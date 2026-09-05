from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from ypendulum_hfv2_p3r2.cases import (
    build_observed_p3r_35_degree_regression,
    build_observed_symmetric_regression,
)
from ypendulum_hfv2_p3r2.certification import (
    characteristic_scales,
    select_restoration_activity,
)
from ypendulum_hfv2_p3r2.kkt import audit_contact_kkt, thresholds_from_manifest
from ypendulum_hfv2_p3r2.solver import settings_from_manifest, solve_contact_seed

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads(
    (CANDIDATE_ROOT / "contracts" / "p3r2_acceptance_manifest.json").read_text(
        encoding="utf-8"
    )
)
ADAPTER_HASH = hashlib.sha256(
    (CANDIDATE_ROOT / "contracts" / MANIFEST["adapter_contract"]).read_bytes()
).hexdigest()
PROTOCOL_HASH = hashlib.sha256(
    (CANDIDATE_ROOT / "contracts" / MANIFEST["frozen_protocol"]).read_bytes()
).hexdigest()


@lru_cache(maxsize=1)
def _structure_case() -> object:
    return build_observed_symmetric_regression(
        MANIFEST,
        adapter_contract_sha256=ADAPTER_HASH,
        frozen_protocol_sha256=PROTOCOL_HASH,
    )


@lru_cache(maxsize=1)
def _p3r_case() -> object:
    return build_observed_p3r_35_degree_regression(
        MANIFEST,
        adapter_contract_sha256=ADAPTER_HASH,
        frozen_protocol_sha256=PROTOCOL_HASH,
    )


def test_restoration_selects_two_positive_support_rows_and_preserves_weak_rows() -> None:
    case = _structure_case()
    evaluation = case.assembly.evaluate(
        case.assembly.coordinates_from_seed(case.seeds[0])
    )
    restore = MANIFEST["composite_solver"]["restoration"]
    activity = select_restoration_activity(
        evaluation,
        characteristic_scales(case.assembly),
        near_active_gap_max_m=restore["near_active_gap_max_m"],
        supported_multiplier_min_N=restore["canonical_support_multiplier_min_N"],
        rank_relative_tolerance=restore["rank_relative_tolerance"],
    )
    assert activity.near_active_indices.size == 4
    assert activity.restore_indices.size == 2
    assert activity.weak_active_indices.size == 2
    assert activity.near_active_rank == 3
    assert activity.restore_rank == 2


def test_composite_solver_always_enters_restoration_even_when_SLSQP_is_exact() -> None:
    case = _structure_case()
    result = solve_contact_seed(
        case.assembly,
        case.seeds[0],
        settings_from_manifest(MANIFEST),
    )
    assert result.restoration.executed
    assert result.restoration.converged
    assert result.restoration.status in {"CONVERGED_AT_ENTRY", "CONVERGED"}


def test_observed_35_degree_counter_skew_is_closed_without_changing_legacy_gate() -> None:
    case = _p3r_case()
    result = solve_contact_seed(
        case.assembly,
        case.seeds[2],
        settings_from_manifest(MANIFEST),
    )
    thresholds = thresholds_from_manifest(MANIFEST)
    before = audit_contact_kkt(
        case.assembly,
        result.slsqp_evaluation,
        thresholds,
        result.scales,
    )
    after = audit_contact_kkt(
        case.assembly,
        result.evaluation,
        thresholds,
        result.scales,
    )
    assert before.stationarity_residual_N > 1.0e-8
    assert result.restoration.executed
    assert result.restoration.converged
    assert after.legacy_stationarity_passed
    assert after.translation_stationarity_passed
    assert after.rotation_stationarity_passed
    assert after.dimensionless_stationarity_passed
    assert after.stationarity_residual_N <= 1.0e-8

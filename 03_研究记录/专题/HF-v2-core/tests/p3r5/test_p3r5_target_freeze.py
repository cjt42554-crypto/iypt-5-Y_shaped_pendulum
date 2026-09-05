from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ypendulum_hfv2_p3r5.cases import build_target_freeze
from ypendulum_hfv2_p3r5.domain import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _outcome(holdout_id: str, category: str) -> dict[str, object]:
    basis = np.eye(6)[:, :3].tolist()
    return {
        "holdout_id": holdout_id,
        "category": category,
        "status": "ADMISSIBLE",
        "reference_coordinates": [0.0, 0.0, -0.1, 0.0, 0.0, 0.0],
        "characteristic_scales": {"coordinate_scales": [1.0] * 6},
        "manifold_neighborhood": {"tangent_basis": basis},
        "supported_ids": ["bob:upper_A:upper_A_s000", "bob:upper_B:upper_B_s000"],
        "near_active_ids": ["bob:upper_A:upper_A_s000", "bob:upper_B:upper_B_s000"],
        "dual_certificate": {"canonical_active_multipliers_N": [0.4, 0.5]},
        "near_active_rank": 2,
        "supported_rank": 2,
        "contact_assembly_token": "d" * 64,
    }


def test_complete_committed_selection_freezes_two_targets_and_zero_runs() -> None:
    manifest = _load("contracts/p3r5_acceptance_manifest.json")
    categories = manifest["holdout_design_and_selection"]["required_categories"]
    outcomes = [
        _outcome("R5_ASYM_H01", categories[0]),
        _outcome("R5_SCALE_H01", categories[1]),
    ]
    cards = []
    for outcome in outcomes:
        cards.append(
            {
                "holdout_id": outcome["holdout_id"],
                "design_id": outcome["holdout_id"],
                "category": outcome["category"],
                "selection_digest_sha256": "e" * 64,
                "pure_constructibility": {"passed": True},
            }
        )
    selection = {
        "status": "TARGETS_ADMISSIBLE_PENDING_SEPARATE_FREEZE",
        "selected_holdout_ids": {
            categories[0]: "R5_ASYM_H01",
            categories[1]: "R5_SCALE_H01",
        },
        "selected_admissibility_record_sha256": {
            categories[0]: canonical_sha256(outcomes[0]),
            categories[1]: canonical_sha256(outcomes[1]),
        },
    }
    target = build_target_freeze(
        manifest,
        {"holdout_cards": cards},
        {"outcomes": outcomes},
        selection,
        admissibility_commit="a" * 40,
        admissibility_metrics_sha256="b" * 64,
        admissibility_selection_sha256="c" * 64,
        generated_at="2026-08-28T00:00:00+08:00",
    )
    assert len(target["qualification_targets"]) == 2
    assert target["qualification_seed_results_observed_before_target_freeze"] == 0
    assert all(
        value == 0
        for value in target["qualification_seed_execution_counts_before_target_freeze"].values()
    )
    assert all(
        len(item["deterministic_solver_initial_guesses"]) == 3
        for item in target["qualification_targets"]
    )

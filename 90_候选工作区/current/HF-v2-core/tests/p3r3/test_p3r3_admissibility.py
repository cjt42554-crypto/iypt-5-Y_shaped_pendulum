from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ypendulum_hfv2_p3r3.cases import (
    build_target_freeze,
    select_admissible_designs,
)

ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _outcome(design_id: str, category: str) -> dict[str, object]:
    basis = np.eye(6)[:, :3]
    return {
        "design_id": design_id,
        "category": category,
        "status": "ADMISSIBLE",
        "reference_discovery_execution_count": 1,
        "admissibility_execution_count": 1,
        "qualification_seed_execution_count": 0,
        "contact_assembly_token": "a" * 64,
        "reference_coordinates": [0.0, 0.0, -0.1, 0.0, 0.0, 0.0],
        "characteristic_scales": {"coordinate_scales": [1.0] * 6},
        "near_active_ids": [
            "bob:upper_A:upper_A_s000",
            "bob:upper_B:upper_B_s000",
        ],
        "supported_ids": [
            "bob:upper_A:upper_A_s000",
            "bob:upper_B:upper_B_s000",
        ],
        "near_active_rank": 2,
        "supported_rank": 2,
        "dual_certificate": {"canonical_active_multipliers_N": [0.4, 0.5]},
        "local_basin": {"tangent_basis": basis.tolist(), "passed": True},
    }


def test_selection_is_lexicographic_within_each_required_category() -> None:
    categories = (
        "asymmetric_unequal_positive_multipliers",
        "changed_geometry_and_load_scale",
    )
    outcomes = [
        _outcome("ASYM_A03", categories[0]),
        _outcome("SCALE_S02", categories[1]),
        _outcome("ASYM_A01", categories[0]),
        _outcome("SCALE_S01", categories[1]),
    ]
    selected = select_admissible_designs(outcomes, categories)
    assert selected[categories[0]]["design_id"] == "ASYM_A01"
    assert selected[categories[1]]["design_id"] == "SCALE_S01"


def test_target_freeze_generates_three_unexecuted_local_seeds_per_target() -> None:
    manifest = _load("contracts/p3r3_acceptance_manifest.json")
    designs = _load("contracts/p3r3_design_cards.json")
    categories = manifest["target_design_and_selection"]["required_categories"]
    outcomes = [
        _outcome("ASYM_A01", categories[0]),
        _outcome("SCALE_S01", categories[1]),
    ]
    target = build_target_freeze(
        manifest,
        designs,
        outcomes,
        implementation_commit="b" * 40,
        generated_at="2026-08-28T00:00:00+08:00",
    )
    assert target["status"] == "TARGETS_FROZEN"
    assert target["qualification_seed_results_observed_before_target_freeze"] == 0
    assert len(target["qualification_targets"]) == 2
    assert all(
        len(item["deterministic_seeds"]) == 3
        and item["qualification_seed_results_observed_before_target_freeze"] == 0
        for item in target["qualification_targets"]
    )
    assert all(
        value == 0
        for value in target["qualification_seed_execution_counts_before_target_freeze"].values()
    )

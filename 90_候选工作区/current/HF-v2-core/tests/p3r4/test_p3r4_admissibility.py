from __future__ import annotations

import json
from pathlib import Path

from ypendulum_hfv2_p3r4.cases import build_admissibility_selection

ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _outcome(design_id: str, category: str, status: str = "ADMISSIBLE") -> dict[str, object]:
    return {
        "design_id": design_id,
        "category": category,
        "status": status,
        "reference_discovery_execution_count": 1,
        "admissibility_execution_count": 1,
        "second_order_execution_count": 1,
        "manifold_neighborhood_execution_count": 1,
        "qualification_seed_execution_count": 0,
    }


def test_selection_is_lexicographic_and_does_not_generate_seeds() -> None:
    manifest = _load("contracts/p3r4_acceptance_manifest.json")
    designs = _load("contracts/p3r4_design_cards.json")
    categories = manifest["target_design_and_selection"]["required_categories"]
    outcomes = [
        _outcome("R4_ASYM_B03", categories[0]),
        _outcome("R4_SCALE_T03", categories[1]),
        _outcome("R4_ASYM_B01", categories[0]),
        _outcome("R4_SCALE_T01", categories[1]),
    ]
    selection = build_admissibility_selection(
        manifest,
        designs,
        outcomes,
        implementation_commit="a" * 40,
        generated_at="2026-08-28T00:00:00+08:00",
    )
    assert selection["status"] == "TARGETS_ADMISSIBLE_PENDING_SEPARATE_FREEZE"
    assert selection["selected_design_ids"] == {
        categories[0]: "R4_ASYM_B01",
        categories[1]: "R4_SCALE_T01",
    }
    assert selection["target_freeze_generated"] is False
    assert selection["qualification_seed_execution_counts_before_separate_target_freeze"] == {}


def test_incomplete_category_fails_without_partial_target_selection() -> None:
    manifest = _load("contracts/p3r4_acceptance_manifest.json")
    designs = _load("contracts/p3r4_design_cards.json")
    category = manifest["target_design_and_selection"]["required_categories"][0]
    selection = build_admissibility_selection(
        manifest,
        designs,
        [_outcome("R4_ASYM_B01", category)],
        implementation_commit="a" * 40,
        generated_at="2026-08-28T00:00:00+08:00",
    )
    assert selection["status"] == "TARGET_SUITE_NOT_ADMISSIBLE"
    assert selection["qualification_seed_results_observed_before_separate_target_freeze"] == 0

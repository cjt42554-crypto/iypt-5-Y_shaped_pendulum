from __future__ import annotations

import json
from pathlib import Path

from ypendulum_hfv2_p3r5.cases import build_admissibility_selection

ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _holdout() -> dict[str, object]:
    categories = _load("contracts/p3r5_acceptance_manifest.json")["holdout_design_and_selection"][
        "required_categories"
    ]
    cards = []
    for prefix, category in (("ASYM", categories[0]), ("SCALE", categories[1])):
        for index in range(1, 5):
            cards.append({"holdout_id": f"R5_{prefix}_H{index:02d}", "category": category})
    return {"holdout_cards": cards}


def _outcome(card: dict[str, object], status: str = "ADMISSIBLE") -> dict[str, object]:
    return {
        **card,
        "status": status,
        "input_assembly_execution_count": 1,
        "reference_construction_execution_count": 1,
        "target_admissibility_execution_count": 1,
        "second_order_execution_count": 1,
        "manifold_neighborhood_execution_count": 1,
        "qualification_seed_execution_count": 0,
    }


def _selection(outcomes: list[dict[str, object]]) -> dict[str, object]:
    return build_admissibility_selection(
        _load("contracts/p3r5_acceptance_manifest.json"),
        _holdout(),
        outcomes,
        implementation_commit="a" * 40,
        holdout_freeze_commit="b" * 40,
        attempt_ledger_sha256="c" * 64,
        generated_at="2026-08-28T00:00:00+08:00",
    )


def test_complete_selection_is_lexicographic_and_seed_free() -> None:
    cards = _holdout()["holdout_cards"]
    selection = _selection([_outcome(card) for card in cards])
    assert selection["status"] == "TARGETS_ADMISSIBLE_PENDING_SEPARATE_FREEZE"
    assert selection["selected_holdout_ids"] == {
        cards[0]["category"]: "R5_ASYM_H01",
        cards[4]["category"]: "R5_SCALE_H01",
    }
    assert selection["target_freeze_generated"] is False
    assert selection["qualification_seed_execution_counts_before_separate_target_freeze"] == {}


def test_incomplete_suite_discards_partial_selection() -> None:
    cards = _holdout()["holdout_cards"]
    outcomes = [_outcome(card, "TARGET_INVALID") for card in cards]
    outcomes[0] = _outcome(cards[0])
    selection = _selection(outcomes)
    assert selection["status"] == "TARGET_SUITE_NOT_ADMISSIBLE"
    assert selection["selected_holdout_ids"] == {}


def test_protocol_failure_preempts_other_classifications() -> None:
    cards = _holdout()["holdout_cards"]
    outcomes = [_outcome(cards[0], "P3R5_PROTOCOL_CONSTRUCTION_FAILURE")]
    selection = _selection(outcomes)
    assert selection["status"] == "P3R5_PROTOCOL_CONSTRUCTION_FAILURE"
    assert selection["selected_holdout_ids"] == {}

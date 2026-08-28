from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ypendulum_hfv2_p3r4.cases import (
    build_admissibility_selection,
    build_target_freeze,
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
        "input_assembly_validation_execution_count": 1,
        "reference_discovery_execution_count": 1,
        "admissibility_execution_count": 1,
        "second_order_execution_count": 1,
        "manifold_neighborhood_execution_count": 1,
        "qualification_seed_execution_count": 0,
        "contact_assembly_token": "a" * 64,
        "reference_coordinates": [0.0, 0.0, -0.1, 0.0, 0.0, 0.0],
        "characteristic_scales": {
            "coordinate_scales": [1.0] * 6,
        },
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
        "manifold_neighborhood": {"tangent_basis": basis.tolist(), "passed": True},
    }


def test_target_and_solver_initial_guess_freeze_is_a_separate_zero_run_artifact() -> None:
    manifest = _load("contracts/p3r4_acceptance_manifest.json")
    designs = _load("contracts/p3r4_design_cards.json")
    categories = manifest["target_design_and_selection"]["required_categories"]
    outcomes = [
        _outcome("R4_ASYM_B01", categories[0]),
        {**_outcome("R4_ASYM_B02", categories[0]), "status": "TARGET_INVALID"},
        {**_outcome("R4_ASYM_B03", categories[0]), "status": "TARGET_INVALID"},
        {**_outcome("R4_ASYM_B04", categories[0]), "status": "TARGET_INVALID"},
        _outcome("R4_SCALE_T01", categories[1]),
        {**_outcome("R4_SCALE_T02", categories[1]), "status": "TARGET_INVALID"},
        {**_outcome("R4_SCALE_T03", categories[1]), "status": "TARGET_INVALID"},
        {**_outcome("R4_SCALE_T04", categories[1]), "status": "TARGET_INVALID"},
    ]
    selection = build_admissibility_selection(
        manifest,
        designs,
        outcomes,
        implementation_commit="a" * 40,
        generated_at="2026-08-28T00:00:00+08:00",
    )
    metrics = {"outcomes": outcomes}
    target = build_target_freeze(
        manifest,
        designs,
        metrics,
        selection,
        admissibility_commit="b" * 40,
        admissibility_metrics_sha256="c" * 64,
        admissibility_selection_sha256="d" * 64,
        generated_at="2026-08-28T00:01:00+08:00",
    )
    assert target["status"] == "TARGETS_AND_SOLVER_INITIAL_GUESSES_FROZEN"
    assert target["qualification_seed_results_observed_before_target_freeze"] == 0
    assert len(target["qualification_targets"]) == 2
    for contract in target["qualification_targets"]:
        seeds = contract["deterministic_solver_initial_guesses"]
        assert len(seeds) == 3
        assert seeds[0]["seed_role"] == "reference_solver_initial_guess"
        assert all(seed["pre_retraction_required"] is False for seed in seeds)
        offsets = np.asarray([seed["dimensionless_offset"] for seed in seeds])
        assert np.linalg.matrix_rank(offsets[1:]) == 2
    assert all(
        value == 0
        for value in target["qualification_seed_execution_counts_before_target_freeze"].values()
    )

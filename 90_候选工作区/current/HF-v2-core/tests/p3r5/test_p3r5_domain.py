from __future__ import annotations

import ast
import json
from pathlib import Path

from ypendulum_hfv2_p3r5.domain import (
    enumerate_candidates,
    observed_signature_set,
    pure_constructibility,
    select_holdouts,
)

ROOT = Path(__file__).resolve().parents[2]


def _load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _domain_inputs() -> tuple[dict[str, object], set[str]]:
    domain = _load("contracts/p3r5_holdout_domain.json")
    observed = observed_signature_set(
        _load("contracts/p3r3_design_cards.json"),
        _load("contracts/p3r4_design_cards.json"),
    )
    return domain, observed


def test_domain_module_has_no_assembly_solver_or_certifier_import() -> None:
    source = (ROOT / "src/ypendulum_hfv2_p3r5/domain.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    assert not any(name.startswith(("numpy", "scipy", "ypendulum")) for name in imports)


def test_pure_domain_has_at_least_four_candidates_per_category() -> None:
    domain, observed = _domain_inputs()
    candidates = enumerate_candidates(domain)
    assert len(candidates["asymmetric_unequal_positive_multipliers"]) == 768
    assert len(candidates["changed_geometry_and_load_scale"]) == 12
    for category in domain["required_categories_in_order"]:
        passed = [
            item
            for item in candidates[category]
            if pure_constructibility(item, domain, observed)["passed"]
        ]
        assert len(passed) >= 4


def test_hash_selection_is_deterministic_and_commit_bound_without_results() -> None:
    domain, observed = _domain_inputs()
    first, first_trace = select_holdouts(domain, "1" * 40, observed)
    repeated, repeated_trace = select_holdouts(domain, "1" * 40, observed)
    changed, _ = select_holdouts(domain, "2" * 40, observed)
    assert first == repeated
    assert first_trace == repeated_trace
    assert len(first) == 8
    assert [item["holdout_id"] for item in first] == [
        "R5_ASYM_H01",
        "R5_ASYM_H02",
        "R5_ASYM_H03",
        "R5_ASYM_H04",
        "R5_SCALE_H01",
        "R5_SCALE_H02",
        "R5_SCALE_H03",
        "R5_SCALE_H04",
    ]
    assert [item["selection_digest_sha256"] for item in first] != [
        item["selection_digest_sha256"] for item in changed
    ]
    assert all(item["pure_constructibility"]["passed"] for item in first)
    assert all("reference_coordinates" not in item for item in first)

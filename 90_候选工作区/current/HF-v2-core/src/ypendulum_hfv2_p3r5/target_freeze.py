"""Freeze P3R5 targets and solver seeds after committed admissibility."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .cases import build_target_freeze
from .evidence_support import contract_binding, git_head, jsonable, load_json, sha256


def generate_target_freeze(root: Path) -> dict[str, Any]:
    manifest = load_json(root / "contracts/p3r5_acceptance_manifest.json")
    holdout = load_json(root / "contracts/p3r5_holdout_cards.json")
    metrics_path = root / "reports/p3r5_admissibility_metrics.json"
    selection_path = root / "contracts/p3r5_admissibility_selection.json"
    metrics = load_json(metrics_path)
    selection = load_json(selection_path)
    binding = contract_binding(root, manifest, required_stage="admissibility")
    if binding["status"] != "PASS":
        raise RuntimeError("P3R5 admissibility is not a committed closed predecessor.")
    repository_root = root.parents[2]
    head = git_head(repository_root)
    if head != binding["admissibility_commit"]:
        raise RuntimeError("P3R5 target freeze must run directly on admissibility commit.")
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    return jsonable(
        build_target_freeze(
            manifest,
            holdout,
            metrics,
            selection,
            admissibility_commit=head,
            admissibility_metrics_sha256=sha256(metrics_path),
            admissibility_selection_sha256=sha256(selection_path),
            generated_at=generated_at,
        )
    )


__all__ = ["generate_target_freeze"]

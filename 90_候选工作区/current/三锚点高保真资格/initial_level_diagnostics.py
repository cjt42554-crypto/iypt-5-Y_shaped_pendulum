#!/usr/bin/env python3
"""Audit the prepared t=0 state on every formal spatial level.

This is an initial-state diagnostic, not a dynamic convergence study.  It
uses the independent HF reference kernel to recompute signed axial forces and
all registered guard margins from each prepared state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml

import build_qualification_configs as builder

from ypendulum.config import load_config, resolved_config_sha256
from ypendulum.hf import HighFidelityModel
from ypendulum.hf.reference import reference_snapshot_from_state
from ypendulum.hf.solver import prepare_initial_state
from ypendulum.hf.validation import _freeze_and_validate_spec, _space_configs
from ypendulum.io.provenance import source_hash


SCRIPT_PATH = Path(__file__).resolve()
CANDIDATE_ROOT = SCRIPT_PATH.parent
PACKAGE_ROOT = builder.HF_SOURCE_ROOT / "ypendulum"


def initial_level_record(
    config: Any,
    level_index: int,
    required_normalized_guard_margin: float,
) -> dict[str, Any]:
    """Prepare and independently inspect one frozen spatial level."""

    model = HighFidelityModel(config)
    preparation = prepare_initial_state(config, model)
    snapshot = reference_snapshot_from_state(model, 0.0, preparation.state)
    metadata = model.guard_component_metadata()
    normalized_guards = {
        name: float(snapshot.guard_margins[name]) / float(metadata[name]["scale"])
        for name in sorted(metadata)
    }
    axial = {
        name: {
            "minimum_signed_axial_force_N": float(np.min(values)),
            "maximum_signed_axial_force_N": float(np.max(values)),
            "nonpositive_segment_count": int(np.count_nonzero(values <= 0.0)),
            "segment_count": int(np.asarray(values).size),
        }
        for name, values in sorted(snapshot.branch_axial_force.items())
    }
    limiting_guard = min(normalized_guards, key=normalized_guards.__getitem__)
    minimum_axial = min(
        branch["minimum_signed_axial_force_N"] for branch in axial.values()
    )
    return {
        "level_index": level_index,
        "role": ("finest_production" if level_index == 2 else "formal_coarse_trend"),
        "mesh": {
            name: int(getattr(config.cables, name).elements)
            for name in ("upper_A", "upper_B", "lower")
        },
        "allow_subminimum_mesh": bool(config.solver.allow_subminimum_mesh),
        "resolved_config_sha256": resolved_config_sha256(config),
        "preparation": {
            "mode": preparation.preparation_mode,
            "force_residual_inf_N": float(preparation.residual_inf_N),
            "iterations": int(preparation.iterations),
            "bob_held": bool(preparation.bob_held),
        },
        "signed_axial_force": axial,
        "minimum_signed_axial_force_N": minimum_axial,
        "all_segments_strictly_tensile": minimum_axial > 0.0,
        "normalized_guard_margins": normalized_guards,
        "limiting_guard": limiting_guard,
        "minimum_normalized_guard_margin": normalized_guards[limiting_guard],
        "required_minimum_normalized_guard_margin": (
            required_normalized_guard_margin
        ),
        "sampled_guard_threshold_passed": (
            normalized_guards[limiting_guard]
            > required_normalized_guard_margin
        ),
    }


def run(output_path: Path) -> dict[str, Any]:
    plan = json.loads(
        (CANDIDATE_ROOT / "qualification_plan.json").read_text(encoding="utf-8")
    )
    validation_spec = _freeze_and_validate_spec(
        yaml.safe_load(builder.VALIDATION_SPEC_PATH.read_text(encoding="utf-8"))
    )
    required_normalized_guard_margin = float(
        validation_spec["physics_checks"]["minimum_normalized_guard_margin"]
    )
    source_start = source_hash(PACKAGE_ROOT)
    anchors: list[dict[str, Any]] = []
    for anchor in plan["anchors"]:
        base = load_config(CANDIDATE_ROOT / anchor["config"])
        levels = _space_configs(base)
        anchors.append(
            {
                "anchor": anchor["anchor"],
                "slug": anchor["slug"],
                "levels": [
                    initial_level_record(
                        config,
                        index,
                        required_normalized_guard_margin,
                    )
                    for index, config in enumerate(levels)
                ],
            }
        )
    source_end = source_hash(PACKAGE_ROOT)
    report = {
        "schema_version": "YPS-THREE-ANCHOR-HF-INITIAL-LEVEL-DIAGNOSTICS-1.0",
        "scope": (
            "prepared t=0 state only; no dynamic trajectory, continuous guard "
            "certificate, convergence, physical validation, or experiment"
        ),
        "formal_hf_source_sha256_start": source_start,
        "formal_hf_source_sha256_end": source_end,
        "formal_hf_source_stable": source_start == source_end,
        "qualification_plan_sha256": builder.sha256_file(
            CANDIDATE_ROOT / "qualification_plan.json"
        ),
        "formal_validation_spec_sha256": builder.sha256_file(
            builder.VALIDATION_SPEC_PATH
        ),
        "required_minimum_normalized_guard_margin": (
            required_normalized_guard_margin
        ),
        "anchors": anchors,
    }
    builder.write_json(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=CANDIDATE_ROOT / "results" / "initial_level_diagnostics.json",
    )
    args = parser.parse_args()
    report = run(args.output.expanduser().resolve())
    print(
        json.dumps(
            {
                "status": "COMPLETE",
                "anchor_count": len(report["anchors"]),
                "formal_hf_source_stable": report["formal_hf_source_stable"],
                "output": str(args.output.expanduser().resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["formal_hf_source_stable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

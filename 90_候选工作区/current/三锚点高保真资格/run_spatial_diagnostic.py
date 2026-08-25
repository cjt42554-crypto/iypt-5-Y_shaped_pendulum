#!/usr/bin/env python3
"""Run one three-level HF spatial diagnostic under the frozen formal contract.

The script reuses the formal spatial configurations, comparison kernel, Cauchy
gate and event-stability gate.  It deliberately does not call the expensive
per-level continuous-guard/accuracy contract: that gate is evaluated by the
separate certified single-run pilot, and all prepared levels are already known
to miss the frozen sampled ROD_SELF_CLEARANCE margin at t=0.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import yaml

import build_qualification_configs as builder

from ypendulum.config import load_config
from ypendulum.hf.validation import (
    _cauchy_gate,
    _compare,
    _event_stability,
    _freeze_and_validate_spec,
    _run_bundle,
    _runtime_identity,
    _space_configs,
    _write_candidate_artifacts,
)
from ypendulum.io.provenance import source_hash


SCRIPT_PATH = Path(__file__).resolve()
CANDIDATE_ROOT = SCRIPT_PATH.parent
PACKAGE_ROOT = builder.HF_SOURCE_ROOT / "ypendulum"


def json_ready(value: Any) -> Any:
    """Convert NumPy scalar containers from formal reports to strict JSON values."""

    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value


def apparent_tail_diagnostics(
    coarse_to_middle: dict[str, float],
    middle_to_fine: dict[str, float],
) -> dict[str, dict[str, Any]]:
    """Estimate an apparent order and geometric error tail from norm differences.

    These are norm-only diagnostics.  They cannot provide a signed Richardson
    extrapolated field value, and non-contracting metrics fail closed.
    """

    output: dict[str, dict[str, Any]] = {}
    for metric in sorted(coarse_to_middle):
        coarse = float(coarse_to_middle[metric])
        fine = float(middle_to_fine[metric])
        if not (math.isfinite(coarse) and math.isfinite(fine)) or coarse < 0.0 or fine < 0.0:
            raise ValueError(f"Invalid refinement norm for {metric}.")
        if fine == 0.0:
            output[metric] = {
                "coarse_to_middle": coarse,
                "middle_to_fine": fine,
                "contraction_ratio": None,
                "apparent_order_base2": None,
                "estimated_remaining_fine_error_norm": 0.0,
                "status": "FINE_DIFFERENCE_ZERO",
                "signed_field_extrapolation": None,
            }
            continue
        contraction = coarse / fine
        order = math.log2(contraction) if contraction > 0.0 else None
        denominator = contraction - 1.0
        contracting = contraction > 1.0 and order is not None and order > 0.0
        output[metric] = {
            "coarse_to_middle": coarse,
            "middle_to_fine": fine,
            "contraction_ratio": contraction,
            "apparent_order_base2": order,
            "estimated_remaining_fine_error_norm": (
                fine / denominator if contracting else None
            ),
            "status": "CONTRACTING" if contracting else "NONCONTRACTING",
            "signed_field_extrapolation": None,
        }
    return output


def level_summary(bundle: Any, level_index: int) -> dict[str, Any]:
    result = bundle.result
    metadata = bundle.model.guard_component_metadata()
    normalized_guards = {
        name: float(np.min(values)) / float(metadata[name]["scale"])
        for name, values in sorted(result.guard_margins.items())
    }
    signed_force = {
        name: {
            "minimum_N": float(np.min(values)),
            "maximum_N": float(np.max(values)),
        }
        for name, values in sorted(result.cable_axial_force.items())
    }
    limiting_guard = min(normalized_guards, key=normalized_guards.__getitem__)
    return {
        "level_index": level_index,
        "role": "finest_production" if level_index == 2 else "formal_coarse_trend",
        "config_sha256": bundle.config_hash,
        "mesh": {
            name: int(getattr(bundle.config.cables, name).elements)
            for name in ("upper_A", "upper_B", "lower")
        },
        "allow_subminimum_mesh": bool(bundle.config.solver.allow_subminimum_mesh),
        "physical_status": result.physical_status,
        "numerical_status": result.numerical_status,
        "valid_interval_s": [float(value) for value in result.valid_interval],
        "runtime_seconds": float(result.diagnostics["runtime_seconds"]),
        "accepted_integration_step_count": int(
            result.diagnostics["accepted_integration_step_count"]
        ),
        "preparation": {
            "mode": bundle.preparation.preparation_mode,
            "force_residual_inf_N": float(bundle.preparation.residual_inf_N),
            "iterations": int(bundle.preparation.iterations),
        },
        "signed_axial_force": signed_force,
        "minimum_signed_axial_force_N": min(
            item["minimum_N"] for item in signed_force.values()
        ),
        "maximum_absolute_energy_balance_residual": float(
            np.max(np.abs(result.energy["balance_residual"]))
        ),
        "limiting_sampled_guard": limiting_guard,
        "minimum_sampled_normalized_guard_margin": normalized_guards[limiting_guard],
        "sampled_guard_margins_normalized": normalized_guards,
        "event_count": len(result.events),
        "identity": {
            "source_sha256_start": bundle.source_start,
            "source_sha256_end": bundle.source_end,
            "resolved_config_sha256_end": bundle.config_hash_end,
            "runtime_identity_start": bundle.runtime_identity_start,
            "runtime_identity_end": bundle.runtime_identity_end,
            "auxiliary_input_identity_start": bundle.auxiliary_input_hash_start,
            "auxiliary_input_identity_end": bundle.auxiliary_input_hash_end,
            "canonical_result_sha256_start": bundle.result_hash_start,
        },
    }


def run(anchor_slug: str, output_path: Path, artifact_directory: Path) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"Diagnostic output already exists: {output_path}")
    if artifact_directory.exists():
        raise FileExistsError(f"Diagnostic artifact directory already exists: {artifact_directory}")
    if not artifact_directory.is_relative_to(CANDIDATE_ROOT):
        raise ValueError("Diagnostic artifacts must remain inside the candidate directory.")
    plan_path = CANDIDATE_ROOT / "qualification_plan.json"
    plan_bytes = plan_path.read_bytes()
    spec_bytes = builder.VALIDATION_SPEC_PATH.read_bytes()
    script_hash_start = builder.sha256_file(SCRIPT_PATH)
    source_start = source_hash(PACKAGE_ROOT)
    runtime_start = _runtime_identity()
    plan = json.loads(plan_bytes)
    anchor = next(item for item in plan["anchors"] if item["slug"] == anchor_slug)
    config_path = CANDIDATE_ROOT / anchor["config"]
    config_bytes = config_path.read_bytes()
    spec = _freeze_and_validate_spec(yaml.safe_load(spec_bytes))

    base = load_config(config_path)
    candidates = _space_configs(base)
    cache: dict[str, Any] = {}
    bundles = [_run_bundle(candidate, cache, PACKAGE_ROOT) for candidate in candidates]
    comparisons = [
        _compare(bundles[0], bundles[1], int(spec["material_comparison_points"])),
        _compare(bundles[1], bundles[2], int(spec["material_comparison_points"])),
    ]
    cauchy = _cauchy_gate(
        comparisons,
        spec["thresholds"]["space"],
        ratio_slack=float(spec["cauchy_ratio_slack"]),
        numerical_floor_fraction=float(spec["numerical_floor_fraction"]),
    )
    events = _event_stability(bundles, float(spec["maximum_event_time_spread_s"]))

    script_hash_end = builder.sha256_file(SCRIPT_PATH)
    source_end = source_hash(PACKAGE_ROOT)
    runtime_end = _runtime_identity()
    identity_checks = {
        "script_stable": script_hash_start == script_hash_end,
        "formal_source_stable": source_start == source_end,
        "runtime_stable": runtime_start == runtime_end,
        "qualification_plan_file_stable": plan_path.read_bytes() == plan_bytes,
        "validation_spec_file_stable": (
            builder.VALIDATION_SPEC_PATH.read_bytes() == spec_bytes
        ),
        "anchor_config_file_stable": config_path.read_bytes() == config_bytes,
        "bundle_internal_identities_stable": all(
            bundle.source_start == bundle.source_end == source_start
            and bundle.config_hash == bundle.config_hash_end
            and bundle.runtime_identity_start == bundle.runtime_identity_end == runtime_start
            and bundle.auxiliary_input_hash_start == bundle.auxiliary_input_hash_end
            for bundle in bundles
        ),
    }
    if not all(identity_checks.values()):
        raise RuntimeError(f"Spatial diagnostic identity drift: {identity_checks}")
    artifact_records = _write_candidate_artifacts(artifact_directory, cache)
    apparent = apparent_tail_diagnostics(comparisons[0], comparisons[1])
    report = json_ready({
        "schema_version": "YPS-THREE-ANCHOR-HF-SPACE-DIAGNOSTIC-1.0",
        "anchor": anchor["anchor"],
        "slug": anchor_slug,
        "scope": (
            "0.12 s three-level spatial Cauchy diagnostic using formal comparison, "
            "threshold and event-stability kernels; no per-level continuous-guard "
            "or independent-accuracy contract"
        ),
        "qualification": (
            "SPACE_CAUCHY_DIAGNOSTIC_SUPPORTED"
            if cauchy["passed"] and events["passed"]
            else "SPACE_CAUCHY_DIAGNOSTIC_NOT_DEMONSTRATED"
        ),
        "passed": bool(cauchy["passed"] and events["passed"]),
        "formal_hf_source_sha256": source_start,
        "formal_validation_spec_sha256": builder.sha256_file(
            builder.VALIDATION_SPEC_PATH
        ),
        "qualification_plan_sha256": builder.sha256_file(plan_path),
        "script_sha256": script_hash_start,
        "identity_checks": identity_checks,
        "levels": [level_summary(bundle, index) for index, bundle in enumerate(bundles)],
        "comparisons": {
            "coarse_to_middle": comparisons[0],
            "middle_to_fine": comparisons[1],
        },
        "formal_space_cauchy_gate": cauchy,
        "formal_event_stability_gate": events,
        "apparent_norm_tail_diagnostics": apparent,
        "candidate_artifacts": artifact_records,
        "artifact_directory": str(artifact_directory.relative_to(CANDIDATE_ROOT)),
        "claim_boundary": (
            "A passing norm trend is not HF qualification because level contracts, "
            "continuous accepted-step guards, long-window modal convergence, physical "
            "validation and experiment are outside this diagnostic."
        ),
    })
    builder.write_json(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("anchor", choices=("4to3", "3to2", "2to1"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--artifact-directory", type=Path)
    args = parser.parse_args()
    output = (
        args.output
        if args.output is not None
        else CANDIDATE_ROOT / "results" / "spatial" / f"{args.anchor}.json"
    ).expanduser().resolve()
    artifacts = (
        args.artifact_directory
        if args.artifact_directory is not None
        else CANDIDATE_ROOT / "generated" / "spatial" / args.anchor
    ).expanduser().resolve()
    report = run(args.anchor, output, artifacts)
    print(
        json.dumps(
            {
                "anchor": report["anchor"],
                "qualification": report["qualification"],
                "passed": report["passed"],
                "output": str(output),
                "artifact_directory": str(artifacts),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

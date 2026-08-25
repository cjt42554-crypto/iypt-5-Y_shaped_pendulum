#!/usr/bin/env python3
"""Evaluate a candidate, component-specific HF guard qualification contract.

The formal physical guard domains and their raw zero-crossing semantics remain
unchanged.  This module only replaces two qualification normalisations that the
root-cause report showed to depend on an unrelated global length or on the
material-cell span.  It never rewrites historical run status.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
CANDIDATE_ROOT = SCRIPT_PATH.parent
DEFAULT_REPORT = CANDIDATE_ROOT / "results" / "guard_root_cause.json"
DEFAULT_SPEC = CANDIDATE_ROOT / "guard_contract_v2" / "spec.json"
DEFAULT_OUTPUT = CANDIDATE_ROOT / "guard_contract_v2" / "evaluation.json"
REPLACED_COMPONENTS = frozenset(
    {"ROD_SELF_CLEARANCE", "BOB_SOCKET_RADIAL_MONOTONICITY"}
)


class ContractError(ValueError):
    """A candidate contract input is incomplete or internally inconsistent."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _finite(name: str, value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ContractError(f"{name} must be finite; got {value!r}.")
    return number


def _positive_scale(name: str, value: Any) -> float:
    scale = _finite(name, value)
    if scale <= 0.0:
        raise ContractError(f"{name} must be strictly positive; got {scale!r}.")
    return scale


def _candidate_record(
    *,
    label: str,
    raw_margin: Any,
    local_scale: Any,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    raw = _finite(f"{label}.raw_margin", raw_margin)
    scale = _positive_scale(f"{label}.local_scale", local_scale)
    return {
        "label": label,
        "raw_margin": raw,
        "local_scale": scale,
        "normalized_margin": raw / scale,
        "raw_positive": raw > 0.0,
        **metadata,
    }


def rod_self_clearance_v2(level: dict[str, Any]) -> dict[str, Any]:
    """Use the local required centre separation, without changing the domain."""

    minimum_clearance = _finite(
        "minimum_clearance_m", level["minimum_clearance_m"]
    )
    if minimum_clearance < 0.0:
        raise ContractError("minimum_clearance_m cannot be negative.")
    rod = level["rod_self_clearance"]
    candidates: list[dict[str, Any]] = []

    same = rod["same_branch"]
    for branch, record in sorted(same["per_branch"].items()):
        diameter = _positive_scale(
            f"same_branch.{branch}.diameter_m", record["diameter_m"]
        )
        candidates.append(
            _candidate_record(
                label=f"same_branch:{branch}",
                raw_margin=record["raw_guard_margin_m"],
                local_scale=diameter + minimum_clearance,
                metadata={
                    "category": "SAME_BRANCH",
                    "branch_or_pair": branch,
                    "first_segment_index": record["first_segment_index"],
                    "second_segment_index": record["second_segment_index"],
                },
            )
        )

    cross = rod["cross_branch"]
    for pair, record in sorted(cross["per_pair"].items()):
        candidates.append(
            _candidate_record(
                label=f"cross_branch:{pair}",
                raw_margin=record["raw_guard_margin_m"],
                local_scale=record["required_center_separation_m"],
                metadata={
                    "category": "CROSS_BRANCH",
                    "branch_or_pair": pair,
                    "domain_mode": record["domain_mode"],
                },
            )
        )

    if not candidates:
        raise ContractError("ROD_SELF_CLEARANCE has no candidate records.")
    winner = min(candidates, key=lambda item: item["normalized_margin"])
    return {
        "contract_component": "ROD_SELF_CLEARANCE_LOCAL_RELATIVE_V2",
        "physical_domain_changed": False,
        "raw_guard_changed": False,
        "candidate_count": len(candidates),
        "all_stored_minima_raw_positive": all(
            item["raw_positive"] for item in candidates
        ),
        "normalized_margin": winner["normalized_margin"],
        "winner": winner,
    }


def bob_socket_radial_v2(level: dict[str, Any]) -> dict[str, Any]:
    """Use the local radial-increment cosine and preserve raw sign gating."""

    radial = level["bob_socket_radial_monotonicity"]
    cells: list[dict[str, Any]] = []
    for index, cell in enumerate(radial["cells"]):
        raw = _finite(
            f"bob_socket_radial.cells[{index}].raw_dot_product_m2",
            cell["raw_dot_product_m2"],
        )
        cosine = _finite(
            f"bob_socket_radial.cells[{index}].radial_increment_cosine",
            cell["radial_increment_cosine"],
        )
        if abs(cosine) > 1.0 + 5.0e-12:
            raise ContractError(
                f"Cell {index} has an impossible radial cosine {cosine!r}."
            )
        cells.append(
            {
                "cell_index": index,
                "material_interval_from_bob_attachment_m": cell[
                    "material_interval_from_bob_attachment_m"
                ],
                "raw_dot_product_m2": raw,
                "radial_increment_cosine": max(-1.0, min(1.0, cosine)),
                "raw_positive": raw > 0.0,
            }
        )
    if not cells:
        raise ContractError("BOB_SOCKET_RADIAL_MONOTONICITY has no cells.")
    winner = min(cells, key=lambda item: item["radial_increment_cosine"])
    return {
        "contract_component": "BOB_SOCKET_RADIAL_MONOTONICITY_COSINE_V2",
        "physical_domain_changed": False,
        "raw_guard_changed": False,
        "cell_count": len(cells),
        "all_cell_raw_dot_products_positive": all(
            item["raw_positive"] for item in cells
        ),
        "normalized_margin": winner["radial_increment_cosine"],
        "winner": winner,
    }


def evaluate_level(level: dict[str, Any], threshold: float) -> dict[str, Any]:
    rod = rod_self_clearance_v2(level)
    radial = bob_socket_radial_v2(level)
    unchanged = {
        name: _finite(f"normalized_guards.{name}", value)
        for name, value in sorted(level["normalized_guards"].items())
        if name not in REPLACED_COMPONENTS
    }
    if not unchanged:
        raise ContractError("No unchanged guard components were supplied.")

    components = dict(unchanged)
    components["ROD_SELF_CLEARANCE"] = rod["normalized_margin"]
    components["BOB_SOCKET_RADIAL_MONOTONICITY"] = radial[
        "normalized_margin"
    ]
    threshold_failures = sorted(
        name for name, value in components.items() if value <= threshold
    )
    raw_gate_failures: list[str] = []
    if not rod["all_stored_minima_raw_positive"]:
        raw_gate_failures.append("ROD_SELF_CLEARANCE")
    if not radial["all_cell_raw_dot_products_positive"]:
        raw_gate_failures.append("BOB_SOCKET_RADIAL_MONOTONICITY")
    passed = not threshold_failures and not raw_gate_failures
    minimum_unchanged_name, minimum_unchanged_margin = min(
        unchanged.items(), key=lambda item: item[1]
    )
    return {
        "level_index": int(level["level_index"]),
        "role": level["role"],
        "mesh": level["mesh"],
        "resolved_config_sha256": level["resolved_config_sha256"],
        "preparation": level["preparation"],
        "original_v1_failed_guard_components": [
            item["guard"] for item in level["failed_guard_components"]
        ],
        "two_component_hybrid_prepared_state_guard_passed": passed,
        "two_component_hybrid_minimum_normalized_margin": min(components.values()),
        "two_component_hybrid_threshold_failures": threshold_failures,
        "two_component_hybrid_raw_gate_failures": raw_gate_failures,
        "minimum_unchanged_component": {
            "name": minimum_unchanged_name,
            "normalized_margin": minimum_unchanged_margin,
        },
        "rod_self_clearance_v2": rod,
        "bob_socket_radial_monotonicity_v2": radial,
    }


def evaluate_report(
    report: dict[str, Any],
    spec: dict[str, Any],
    *,
    source_report_sha256: str | None = None,
    contract_sha256: str | None = None,
) -> dict[str, Any]:
    if report.get("schema_version") != "YPS-THREE-ANCHOR-HF-GUARD-ROOT-CAUSE-1.0":
        raise ContractError("Unsupported guard root-cause report schema.")
    if spec.get("schema_version") != "YPS-HF-GUARD-QUALIFICATION-CONTRACT-2.0-CANDIDATE":
        raise ContractError("Unsupported candidate guard contract schema.")
    if spec.get("formal_change_authorized") is not False:
        raise ContractError("Candidate spec must not claim formal authorization.")

    threshold = _positive_scale(
        "minimum_normalized_margin", spec["minimum_normalized_margin"]
    )
    report_threshold = _positive_scale(
        "report.required_normalized_guard_margin",
        report["required_normalized_guard_margin"],
    )
    if threshold != report_threshold:
        raise ContractError(
            "Candidate contract must preserve the pre-frozen numeric threshold; "
            f"spec={threshold!r}, report={report_threshold!r}."
        )

    anchors: list[dict[str, Any]] = []
    for anchor in report["anchors"]:
        levels = [evaluate_level(level, threshold) for level in anchor["levels"]]
        anchors.append(
            {
                "anchor": anchor["anchor"],
                "slug": anchor["slug"],
                "levels": levels,
                "all_prepared_levels_passed_two_component_hybrid": all(
                    item["two_component_hybrid_prepared_state_guard_passed"] for item in levels
                ),
            }
        )
    all_passed = all(
        item["all_prepared_levels_passed_two_component_hybrid"] for item in anchors
    )
    return {
        "schema_version": "YPS-HF-GUARD-TWO-COMPONENT-CANDIDATE-EVALUATION-2.0",
        "status": (
            "TWO_COMPONENT_HYBRID_PREPARED_STATE_REEVALUATION_PASS__FULL_COMPONENT_AUDIT_PENDING__HF_NUMERICAL_QUALIFICATION_REMAINS_NO_GO"
            if all_passed
            else "TWO_COMPONENT_HYBRID_PREPARED_STATE_REEVALUATION_FAIL__FULL_COMPONENT_AUDIT_PENDING__HF_NUMERICAL_QUALIFICATION_REMAINS_NO_GO"
        ),
        "contract_schema_version": spec["schema_version"],
        "source_report_schema_version": report["schema_version"],
        "source_report_sha256": source_report_sha256,
        "contract_sha256": contract_sha256,
        "formal_hf_source_sha256": report["formal_hf_source_sha256"],
        "minimum_normalized_margin": threshold,
        "formal_change_authorized": False,
        "physical_guard_domains_changed": False,
        "raw_zero_crossing_semantics_changed": False,
        "all_prepared_levels_passed_two_component_hybrid": all_passed,
        "implemented_component_scope": sorted(REPLACED_COMPONENTS),
        "hybrid_evaluation_only": True,
        "full_component_mesh_objectivity_audit_complete": False,
        "prepared_level_count": sum(len(item["levels"]) for item in anchors),
        "anchors": anchors,
        "historical_v1_status_preserved": report["status"],
        "historical_dynamic_qualification": "HF_NUMERICAL_QUALIFICATION_NO_GO_UNCHANGED",
        "source_endpoint_probe_status": "SOURCE_ENDPOINT_PROBE_INVALID_UNCHANGED",
        "claim_boundary": (
            "This is a prepared-state hybrid re-evaluation of two components under a "
            "candidate local normalisation.  The remaining components still use "
            "v1 metadata and have not completed a mesh-objectivity audit.  It does "
            "not modify the formal solver/spec, does not "
            "re-certify any historical trajectory, does not repair the historical "
            "source-endpoint probe, and does not overturn the spatial Cauchy failures."
        ),
    }


def run(report_path: Path, spec_path: Path, output_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    evaluation = evaluate_report(
        report,
        spec,
        source_report_sha256=sha256_file(report_path),
        contract_sha256=sha256_file(spec_path),
    )
    write_json(output_path, evaluation)
    return evaluation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    evaluation = run(
        args.report.expanduser().resolve(),
        args.spec.expanduser().resolve(),
        args.output.expanduser().resolve(),
    )
    print(
        json.dumps(
            {
                "status": evaluation["status"],
                "prepared_level_count": evaluation["prepared_level_count"],
                "all_prepared_levels_passed_two_component_hybrid": evaluation[
                    "all_prepared_levels_passed_two_component_hybrid"
                ],
                "output": str(args.output),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

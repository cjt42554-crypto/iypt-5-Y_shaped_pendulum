#!/usr/bin/env python3
"""Bracket the candidate preparation boundary before any contact dynamics.

Every alpha is prepared in a fresh process from the same deterministic seed
family.  The contact-free conservative objective is not altered.  Contact
geometry is observed only after each seed has reached the existing preparation
audit, and the frozen complete guard-v2 contract decides candidate admission.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

SCRIPT_PATH = Path(__file__).resolve()
COMPRESSION_ROOT = SCRIPT_PATH.parent
CANDIDATE_ROOT = COMPRESSION_ROOT.parent
BUILDER_PATH = COMPRESSION_ROOT / "build_alpha_specific_candidate.py"
GUARD_IMPLEMENTATION_PATH = CANDIDATE_ROOT / "guard_contract_v2_full.py"
GUARD_SPEC_PATH = CANDIDATE_ROOT / "guard_contract_v2" / "full_spec.json"
MAP_SPEC_PATH = COMPRESSION_ROOT / "precontact_boundary_spec.json"
PREFREEZE_PATH = COMPRESSION_ROOT / "precontact_boundary_prefreeze.json"
RESULTS_PATH = COMPRESSION_ROOT / "precontact_boundary_results.json"
DEFAULT_OUTPUT_ROOT = CANDIDATE_ROOT / "generated" / "precontact_alpha_boundary"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = _load_module(BUILDER_PATH, "precontact_boundary_builder")
full_v2 = _load_module(GUARD_IMPLEMENTATION_PATH, "precontact_boundary_guard_v2")


def _sha256(path: Path) -> str:
    return builder.sha256_file(path)


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        relative = str(path.relative_to(root)).encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def validate_map_spec(spec: dict[str, Any]) -> None:
    if spec.get("schema_version") != "YPS-PRECONTACT-ALPHA-BOUNDARY-SPEC-1.0":
        raise RuntimeError("Unexpected precontact-boundary specification schema.")
    bracket = spec["alpha_bracket"]
    lower = float(bracket["lower"])
    upper = float(bracket["upper"])
    if not 0.0 < lower < upper <= 1.0:
        raise RuntimeError("The alpha bracket must satisfy 0 < lower < upper <= 1.")
    sampling = spec["sampling"]
    iterations = int(sampling["bisection_iterations"])
    if not 1 <= iterations <= 16:
        raise RuntimeError("bisection_iterations must lie in [1,16].")
    if sampling["midpoint_rule"] != "geometric_mean":
        raise RuntimeError("Only the frozen geometric-mean rule is supported.")
    if sampling["cross_alpha_warm_start"] is not False:
        raise RuntimeError("Cross-alpha warm starts are forbidden by this map.")
    if int(sampling["maximum_unique_alpha_evaluations"]) != iterations + 2:
        raise RuntimeError("Maximum alpha evaluations must equal endpoints plus iterations.")
    if spec["dynamic_run_count"] != 0:
        raise RuntimeError("The precontact map cannot authorize dynamics.")
    if spec["formal_change_authorized"] is not False:
        raise RuntimeError("The precontact map cannot authorize formal changes.")


def geometric_midpoint(lower: float, upper: float) -> float:
    if not 0.0 < lower < upper:
        raise ValueError("geometric_midpoint requires 0 < lower < upper.")
    return math.sqrt(lower * upper)


def monotone_false_to_true(samples: list[dict[str, Any]]) -> bool:
    ordered = sorted(samples, key=lambda item: float(item["alpha"]))
    seen_true = False
    for sample in ordered:
        value = sample.get("primary_pass")
        if not isinstance(value, bool):
            return False
        if value:
            seen_true = True
        elif seen_true:
            return False
    return True


def update_bracket(
    lower: float, upper: float, alpha: float, primary_pass: bool
) -> tuple[float, float]:
    if not lower < alpha < upper:
        raise ValueError("A bisection sample must lie strictly inside its bracket.")
    return (lower, alpha) if primary_pass else (alpha, upper)


def _alpha_key(alpha: float) -> str:
    return format(float(alpha), ".17g")


def _alpha_slug(index: int, alpha: float) -> str:
    encoded = format(float(alpha), ".12e").replace("+", "p").replace("-", "m")
    return f"sample_{index:02d}_alpha_{encoded.replace('.', 'p')}"


def _verify_prefreeze(prefreeze: dict[str, Any]) -> dict[str, bool]:
    bindings = prefreeze["bindings"]
    paths = {
        "map_spec_sha256": MAP_SPEC_PATH,
        "run_script_sha256": SCRIPT_PATH,
        "builder_sha256": BUILDER_PATH,
        "guard_implementation_sha256": GUARD_IMPLEMENTATION_PATH,
        "guard_spec_sha256": GUARD_SPEC_PATH,
        "base_config_sha256": (
            CANDIDATE_ROOT
            / json.loads(MAP_SPEC_PATH.read_text(encoding="utf-8"))["base_configuration"]
        ),
    }
    checks = {name: _sha256(path) == bindings[name] for name, path in paths.items()}
    if not all(checks.values()):
        raise RuntimeError(f"Frozen precontact inputs drifted: {checks}")
    return checks


def _emit_config(
    base: dict[str, Any], alpha: float, index: int, output_root: Path
) -> dict[str, Any]:
    slug = _alpha_slug(index, alpha)
    candidate = json.loads(json.dumps(base))
    candidate["run"]["name"] = f"four_to_three_precontact_{slug}"
    candidate["run"]["output_directory"] = (
        f"generated/precontact_alpha_boundary/dynamics_forbidden/{slug}"
    )
    candidate["run"]["claim_level"] = "OUT_OF_SCOPE"
    candidate["high_fidelity"]["compression_regularization_scale"] = float(alpha)
    candidate["high_fidelity"]["controlled_limit_study"] = True
    differences = builder.leaf_differences(base, candidate)
    allowed = {
        "run.name",
        "run.output_directory",
        "run.claim_level",
        "high_fidelity.compression_regularization_scale",
        "high_fidelity.controlled_limit_study",
    }
    if not set(differences) <= allowed:
        raise RuntimeError(f"Unexpected map-config differences: {differences}")
    config_root = output_root / "sample_configs"
    config_root.mkdir(parents=True, exist_ok=True)
    path = config_root / f"{slug}.yaml"
    path.write_text(
        yaml.safe_dump(
            candidate,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )
    return {
        "slug": slug,
        "path": str(path),
        "sha256": _sha256(path),
        "differences_from_template": differences,
    }


CHILD_CODE = r'''
import ast
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from ypendulum.config import load_config, resolved_config_sha256, validate_physical_config
from ypendulum.config.units import to_si
from ypendulum.hf import HighFidelityModel
from ypendulum.hf.solver import prepare_initial_state
import guard_contract_v2_full as full_v2

config_path = Path(sys.argv[1]).resolve()
guard_spec_path = Path(sys.argv[2]).resolve()
state_root = Path(sys.argv[3]).resolve()
candidate_root = Path(sys.argv[4]).resolve()
state_root.mkdir(parents=True, exist_ok=True)

cfg = load_config(config_path)
validate_physical_config(cfg)
model = HighFidelityModel(cfg)
guard_spec = json.loads(guard_spec_path.read_text(encoding="utf-8"))
captured = []
original_guard_components = HighFidelityModel.guard_components

def capture_guard_state(self, time_s, state):
    values = original_guard_components(self, time_s, state)
    captured.append(np.asarray(state, dtype=float).copy())
    return values

HighFidelityModel.guard_components = capture_guard_state
preparation = None
preparation_error_type = None
try:
    preparation = prepare_initial_state(cfg, model)
    records = preparation.audit["candidate_records"]
except RuntimeError as exc:
    marker = "conservative minimum: "
    if marker not in str(exc):
        raise
    records = ast.literal_eval(str(exc).split(marker, 1)[1])
    preparation_error_type = type(exc).__name__
finally:
    HighFidelityModel.guard_components = original_guard_components

if len(records) != len(captured):
    raise RuntimeError(
        f"candidate/state capture mismatch: {len(records)} records, {len(captured)} states"
    )

force_tolerance = float(to_si(cfg.solver.static.force_tolerance, default_unit="N"))
stiffness_scale = max(
    model.force_scale / model.characteristic_length,
    *(branch.ea / float(np.min(branch.segment_rest_length)) for branch in model.branches.values()),
    *(branch.ei / float(np.min(branch.segment_rest_length)) ** 3 for branch in model.branches.values()),
)
hessian_tolerance = 1.0e-7 * stiffness_scale

summaries = []
for index, (record, state) in enumerate(zip(records, captured, strict=True)):
    report = full_v2.evaluate_prepared_state(model, state, guard_spec)
    rod = report["components"]["ROD_SELF_CLEARANCE"]
    state_bytes = np.asarray(state, dtype=np.dtype("<f8")).tobytes(order="C")
    state_sha256 = hashlib.sha256(state_bytes).hexdigest()
    state_path = state_root / f"candidate_{index:02d}.npz"
    np.savez_compressed(state_path, state=np.asarray(state, dtype=float))
    residual = float(record["free_material_residual_inf_N"])
    eigenvalue = record["minimum_hessian_eigenvalue_N_per_m"]
    direct_psd = eigenvalue is not None and float(eigenvalue) >= -hessian_tolerance
    inherited_psd = (
        record.get("stability_audit_skipped_reason")
        == "duplicate_of_existing_psd_stable_candidate"
    )
    force_balanced_psd = (
        np.isfinite(residual)
        and residual <= force_tolerance
        and (direct_psd or inherited_psd)
    )
    raw_guards = {
        name: float(component["public_raw_margin"])
        for name, component in report["components"].items()
    }
    summaries.append({
        "seed_index": index,
        "seed": record["seed"],
        "iterations": int(record["iterations"]),
        "energy_J": float(record["energy_J"]),
        "free_material_residual_inf_N": residual,
        "minimum_hessian_eigenvalue_N_per_m": (
            None if eigenvalue is None else float(eigenvalue)
        ),
        "stability_audit_skipped_reason": record.get("stability_audit_skipped_reason"),
        "force_balanced_psd": bool(force_balanced_psd),
        "full_candidate_guard_passed": bool(report["passed"]),
        "full_candidate_guard_status": report["status"],
        "full_candidate_failed_components": list(report["failed_components"]),
        "minimum_candidate_component": report["minimum_component"],
        "minimum_candidate_normalized_margin": float(report["minimum_normalized_margin"]),
        "raw_guard_components": raw_guards,
        "rod_self_clearance_raw_winner": rod["raw_winner"],
        "rod_self_clearance_normalized_winner": rod["normalized_winner"],
        "state_sha256": state_sha256,
        "state_path": str(state_path.relative_to(candidate_root)),
    })

def order_key(item):
    return (
        float(item["energy_J"]),
        float(item["free_material_residual_inf_N"]),
        int(item["seed_index"]),
    )

equilibria = [item for item in summaries if item["force_balanced_psd"]]
qualified = [item for item in equilibria if item["full_candidate_guard_passed"]]
diagnostic_selected = min(equilibria, key=order_key) if equilibria else None
qualified_selected = min(qualified, key=order_key) if qualified else None
preparation_state_sha256 = None
if preparation is not None:
    preparation_state_sha256 = hashlib.sha256(
        np.asarray(preparation.state, dtype=np.dtype("<f8")).tobytes(order="C")
    ).hexdigest()

payload = {
    "resolved_config_sha256": resolved_config_sha256(cfg),
    "formal_model_id": model.model_id,
    "compression_regularization_scale": float(model.compression_regularization_scale),
    "force_tolerance_N": force_tolerance,
    "hessian_tolerance_N_per_m": float(hessian_tolerance),
    "preparation_api_success": preparation is not None,
    "preparation_error_type": preparation_error_type,
    "preparation_state_sha256": preparation_state_sha256,
    "seed_candidate_count": len(summaries),
    "force_balanced_psd_candidate_count": len(equilibria),
    "qualified_candidate_count": len(qualified),
    "primary_pass": bool(qualified),
    "diagnostic_unconstrained_selected": diagnostic_selected,
    "qualified_selected": qualified_selected,
    "candidates": summaries,
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False))
'''


def _run_sample(
    *,
    alpha: float,
    index: int,
    base: dict[str, Any],
    output_root: Path,
    overlay_source: Path,
) -> dict[str, Any]:
    config = _emit_config(base, alpha, index, output_root)
    state_root = output_root / "sample_states" / config["slug"]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(overlay_source), str(CANDIDATE_ROOT)]
    )
    started = time.perf_counter()
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            CHILD_CODE,
            config["path"],
            str(GUARD_SPEC_PATH),
            str(state_root),
            str(CANDIDATE_ROOT),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=CANDIDATE_ROOT,
        env=environment,
    )
    duration = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"Precontact alpha child failed at alpha={alpha!r}:\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    payload = json.loads(completed.stdout)
    if float(payload["compression_regularization_scale"]) != float(alpha):
        raise RuntimeError("Child preparation used the wrong alpha.")
    return {
        "alpha": float(alpha),
        "alpha_key": _alpha_key(alpha),
        "sample_index": index,
        "config": config,
        "duration_s": duration,
        **payload,
    }


def _raw_contact_bracket(samples: list[dict[str, Any]]) -> dict[str, Any] | None:
    resolved = [
        sample
        for sample in samples
        if sample.get("diagnostic_unconstrained_selected") is not None
    ]
    negative = [
        sample
        for sample in resolved
        if float(
            sample["diagnostic_unconstrained_selected"]["raw_guard_components"][
                "ROD_SELF_CLEARANCE"
            ]
        )
        <= 0.0
    ]
    positive = [
        sample
        for sample in resolved
        if float(
            sample["diagnostic_unconstrained_selected"]["raw_guard_components"][
                "ROD_SELF_CLEARANCE"
            ]
        )
        > 0.0
    ]
    if not negative or not positive:
        return None
    lower = max(negative, key=lambda item: float(item["alpha"]))
    upper_candidates = [
        item for item in positive if float(item["alpha"]) > float(lower["alpha"])
    ]
    if not upper_candidates:
        return None
    upper = min(upper_candidates, key=lambda item: float(item["alpha"]))
    return {
        "lower_alpha_nonpositive": float(lower["alpha"]),
        "lower_raw_margin_m": float(
            lower["diagnostic_unconstrained_selected"]["raw_guard_components"][
                "ROD_SELF_CLEARANCE"
            ]
        ),
        "upper_alpha_positive": float(upper["alpha"]),
        "upper_raw_margin_m": float(
            upper["diagnostic_unconstrained_selected"]["raw_guard_components"][
                "ROD_SELF_CLEARANCE"
            ]
        ),
        "alpha_ratio": float(upper["alpha"]) / float(lower["alpha"]),
    }


def run(output_root: Path) -> dict[str, Any]:
    if RESULTS_PATH.exists():
        raise RuntimeError(
            "precontact_boundary_results.json already exists; refusing to overwrite "
            "a completed frozen map."
        )
    if not PREFREEZE_PATH.is_file():
        raise RuntimeError("Freeze precontact-boundary inputs before running the map.")
    output_root = output_root.expanduser().resolve()
    if output_root.exists():
        raise RuntimeError(
            f"Generated precontact output root already exists: {output_root}"
        )
    spec = json.loads(MAP_SPEC_PATH.read_text(encoding="utf-8"))
    validate_map_spec(spec)
    prefreeze = json.loads(PREFREEZE_PATH.read_text(encoding="utf-8"))
    frozen_checks = _verify_prefreeze(prefreeze)
    prefreeze_sha256 = _sha256(PREFREEZE_PATH)
    formal_tree_start = _tree_sha256(builder.FORMAL_SOURCE_ROOT)

    overlay_root = output_root / "alpha_specific_overlay"
    overlay_plan = builder.build(overlay_root)
    overlay_source = overlay_root / "overlay" / "src"
    overlay_tree_start = _tree_sha256(overlay_source)
    base_path = CANDIDATE_ROOT / spec["base_configuration"]
    base = yaml.safe_load(base_path.read_text(encoding="utf-8"))

    cache: dict[str, dict[str, Any]] = {}

    def evaluate(alpha: float) -> dict[str, Any]:
        key = _alpha_key(alpha)
        if key not in cache:
            print(
                json.dumps(
                    {
                        "phase": "START_PRECONTACT_ALPHA_PREPARATION",
                        "sample_index": len(cache),
                        "alpha": float(alpha),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                flush=True,
            )
            cache[key] = _run_sample(
                alpha=alpha,
                index=len(cache),
                base=base,
                output_root=output_root,
                overlay_source=overlay_source,
            )
            selected = cache[key]["diagnostic_unconstrained_selected"]
            print(
                json.dumps(
                    {
                        "phase": "FINISH_PRECONTACT_ALPHA_PREPARATION",
                        "alpha": float(alpha),
                        "primary_pass": cache[key]["primary_pass"],
                        "force_balanced_psd_candidate_count": cache[key][
                            "force_balanced_psd_candidate_count"
                        ],
                        "rod_self_clearance_raw_m": (
                            None
                            if selected is None
                            else selected["raw_guard_components"][
                                "ROD_SELF_CLEARANCE"
                            ]
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                flush=True,
            )
        return cache[key]

    bracket_spec = spec["alpha_bracket"]
    lower = float(bracket_spec["lower"])
    upper = float(bracket_spec["upper"])
    lower_sample = evaluate(lower)
    upper_sample = evaluate(upper)
    endpoint_checks = {
        "lower_matches_expected_primary_pass": (
            lower_sample["primary_pass"]
            is bool(bracket_spec["lower_expected_primary_pass"])
        ),
        "upper_matches_expected_primary_pass": (
            upper_sample["primary_pass"]
            is bool(bracket_spec["upper_expected_primary_pass"])
        ),
    }
    completed_iterations = 0
    stop_reason: str | None = None
    if not all(endpoint_checks.values()):
        stop_reason = "PREDECLARED_ENDPOINT_CLASSIFICATION_MISMATCH"
    elif (
        lower_sample["force_balanced_psd_candidate_count"] == 0
        or upper_sample["force_balanced_psd_candidate_count"] == 0
    ):
        stop_reason = "ENDPOINT_EQUILIBRIUM_UNRESOLVED"
    else:
        for _ in range(int(spec["sampling"]["bisection_iterations"])):
            alpha = geometric_midpoint(lower, upper)
            sample = evaluate(alpha)
            if sample["force_balanced_psd_candidate_count"] == 0:
                stop_reason = "INTERMEDIATE_EQUILIBRIUM_UNRESOLVED"
                break
            lower, upper = update_bracket(
                lower, upper, alpha, bool(sample["primary_pass"])
            )
            completed_iterations += 1

    samples = sorted(cache.values(), key=lambda item: float(item["alpha"]))
    monotone = monotone_false_to_true(samples)
    if stop_reason is None and not monotone:
        stop_reason = "PRIMARY_PREDICATE_NONMONOTONE_ON_SAMPLED_ALPHAS"
    identity_checks = {
        **frozen_checks,
        "prefreeze_stable": prefreeze_sha256 == _sha256(PREFREEZE_PATH),
        "formal_python_tree_stable": (
            formal_tree_start == _tree_sha256(builder.FORMAL_SOURCE_ROOT)
        ),
        "overlay_python_tree_stable": (
            overlay_tree_start == _tree_sha256(overlay_source)
        ),
        "overlay_builder_plan_preparation_count_zero": (
            overlay_plan["prepared_state_count"] == 0
        ),
        "overlay_builder_plan_dynamic_count_zero": (
            overlay_plan["dynamic_run_count"] == 0
        ),
    }
    expected_iterations = int(spec["sampling"]["bisection_iterations"])
    completed = (
        stop_reason is None
        and completed_iterations == expected_iterations
        and all(identity_checks.values())
    )
    final_bracket = {
        "lower_alpha_primary_fail": lower,
        "upper_alpha_primary_pass": upper,
        "alpha_ratio": upper / lower,
        "log10_width": math.log10(upper) - math.log10(lower),
        "completed_bisection_iterations": completed_iterations,
        "expected_bisection_iterations": expected_iterations,
    }
    report = {
        "schema_version": "YPS-PRECONTACT-ALPHA-BOUNDARY-MAP-1.0",
        "status": (
            "PRECONTACT_QUALIFICATION_BOUNDARY_BRACKET_RESOLVED__NO_POSTCONTACT_MODEL"
            if completed
            else "PRECONTACT_BOUNDARY_MAP_NO_GO"
        ),
        "research_identity": spec["research_identity"],
        "spec_sha256": _sha256(MAP_SPEC_PATH),
        "prefreeze_sha256": prefreeze_sha256,
        "identity_checks": identity_checks,
        "endpoint_checks": endpoint_checks,
        "primary_predicate_monotone_on_sampled_alphas": monotone,
        "stop_reason": stop_reason,
        "final_primary_bracket": final_bracket,
        "raw_contact_sign_bracket": _raw_contact_bracket(samples),
        "sample_count": len(samples),
        "samples": samples,
        "dynamic_gate_open": False,
        "dynamic_run_count": 0,
        "formal_tree_modified": False,
        "formal_change_authorized": False,
        "postcontact_model_selected": False,
        "claim_boundary": spec["claim_boundary"],
    }
    builder.write_json(RESULTS_PATH, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    report = run(args.output_root)
    print(
        json.dumps(
            {
                "status": report["status"],
                "sample_count": report["sample_count"],
                "final_primary_bracket": report["final_primary_bracket"],
                "raw_contact_sign_bracket": report["raw_contact_sign_bracket"],
                "dynamic_run_count": report["dynamic_run_count"],
            },
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

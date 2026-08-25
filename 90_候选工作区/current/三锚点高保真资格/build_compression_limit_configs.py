#!/usr/bin/env python3
"""Preflight the 4:3 compression-regularisation limit study.

The frozen 4:3 production input uses a bilateral held-endpoint equilibrium.
The formal configuration contract intentionally refuses to reuse that
preparation protocol when ``compression_regularization_scale < 1``.  This
script records that fail-closed boundary, resolves the endpoint geometry, and
evaluates the already-prepared alpha=1 state under the constitutive limit.

It does not emit runnable alpha<1 configurations and does not bypass the
formal preparation validator.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import yaml

import build_qualification_configs as builder

from ypendulum.config import (
    ConfigurationError,
    load_config,
    resolved_config_dict,
    resolved_config_sha256,
    validate_physical_config,
)
from ypendulum.config.units import as_vector3
from ypendulum.hf import HighFidelityModel
from ypendulum.hf.reference import reference_snapshot_from_state
from ypendulum.hf.solver import prepare_initial_state
from ypendulum.io.provenance import source_hash


SCRIPT_PATH = Path(__file__).resolve()
CANDIDATE_ROOT = SCRIPT_PATH.parent
OUTPUT_ROOT = CANDIDATE_ROOT / "compression_limit"
BASE_CONFIG_PATH = CANDIDATE_ROOT / "configs" / "4to3.yaml"
INDEPENDENCE_SPEC_PATH = (
    builder.HF_ROOT / "configs" / "high_fidelity_independence_validation.yaml"
)
PACKAGE_ROOT = builder.HF_SOURCE_ROOT / "ypendulum"
CONFIG_CANDIDATE_SCALES = (1.0, 1.0e-2, 1.0e-4, 1.0e-6)
FIXED_STATE_SNAPSHOT_SCALES = (*CONFIG_CANDIDATE_SCALES, 0.0)


def scale_slug(scale: float) -> str:
    mapping = {
        1.0: "alpha_1",
        1.0e-2: "alpha_1e-2",
        1.0e-4: "alpha_1e-4",
        1.0e-6: "alpha_1e-6",
        0.0: "alpha_0_mathematical_endpoint",
    }
    return mapping[float(scale)]


def leaf_differences(left: Any, right: Any, prefix: str = "") -> list[str]:
    """Return sorted dotted paths whose resolved values differ."""

    if isinstance(left, dict) and isinstance(right, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(leaf_differences(left[key], right[key], child))
        return paths
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [prefix]
        paths: list[str] = []
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            paths.extend(
                leaf_differences(
                    left_item,
                    right_item,
                    f"{prefix}[{index}]",
                )
            )
        return paths
    return [] if left == right else [prefix]


def candidate_config(base: Any, scale: float) -> Any:
    """Build an in-memory isolated candidate without writing an invalid file."""

    candidate = base.model_copy(deep=True)
    candidate.high_fidelity.compression_regularization_scale = float(scale)
    candidate.high_fidelity.controlled_limit_study = scale != 1.0
    candidate.run.claim_level = "DERIVED" if scale == 1.0 else "OUT_OF_SCOPE"
    slug = scale_slug(scale)
    candidate.run.name = f"four_to_three_compression_limit_{slug}"
    candidate.run.output_directory = f"generated/compression_limit/{slug}"
    return candidate


def configuration_preflight(base: Any, scale: float) -> dict[str, Any]:
    """Validate an isolated candidate and serialize the formal rejection."""

    candidate = candidate_config(base, scale)
    differences = leaf_differences(
        resolved_config_dict(base),
        resolved_config_dict(candidate),
    )
    record: dict[str, Any] = {
        "scale": float(scale),
        "slug": scale_slug(scale),
        "differences_from_production_base": differences,
        "config_emitted": False,
    }
    try:
        validate_physical_config(candidate)
    except ConfigurationError as error:
        record.update(
            {
                "formal_config_accepted": False,
                "rejection_type": type(error).__name__,
                "rejection_code": error.code,
                "rejection_details": error.details,
                "rejection_message": str(error),
            }
        )
    else:
        record.update(
            {
                "formal_config_accepted": True,
                "resolved_config_sha256": resolved_config_sha256(candidate),
                "rejection_type": None,
                "rejection_code": None,
                "rejection_details": None,
                "rejection_message": None,
            }
        )
    return record


def fixed_endpoint_chord_audit(base: Any, model: HighFidelityModel) -> dict[str, Any]:
    """Compare each requested endpoint chord with its material rest length."""

    initial = base.initial_condition
    if initial.bob_position is None or initial.junction_position is None:
        raise ValueError("The frozen held-endpoint base has lost its endpoint geometry.")
    bob = as_vector3(initial.bob_position, default_unit="m")
    junction = as_vector3(initial.junction_position, default_unit="m")
    attachment = bob + model.attachment_body
    support_a = model.support_motion["support_A"].state(0.0)[0]
    support_b = model.support_motion["support_B"].state(0.0)[0]
    endpoints = {
        "upper_A": (support_a, junction),
        "upper_B": (support_b, junction),
        "lower": (junction, attachment),
    }
    branches: dict[str, Any] = {}
    for name, (start, end) in endpoints.items():
        chord = float(np.linalg.norm(end - start))
        material = float(np.sum(model.branches[name].segment_rest_length))
        branches[name] = {
            "endpoint_chord_m": chord,
            "material_rest_length_m": material,
            "chord_minus_rest_length_m": chord - material,
            "chord_to_rest_length_ratio": chord / material,
            "straight_material_embedding_possible": chord >= material,
        }
    compressed = [
        name
        for name, record in branches.items()
        if not record["straight_material_embedding_possible"]
    ]
    return {
        "branches": branches,
        "branches_with_chord_shorter_than_rest_length": compressed,
        "geometric_direct_release_can_preserve_all_endpoints": not compressed,
        "formal_geometric_direct_release_consequence": (
            "geometric_direct_release rejects a branch whose endpoint chord is "
            "shorter than its material rest length; the frozen lower branch has "
            "exactly this geometry."
        ),
    }


def _state_sha256(state: np.ndarray) -> str:
    value = np.asarray(state, dtype="<f8")
    return hashlib.sha256(value.tobytes(order="C")).hexdigest()


def _branch_force_summary(values: np.ndarray) -> dict[str, Any]:
    array = np.asarray(values, dtype=float)
    return {
        "minimum_signed_axial_force_N": float(np.min(array)),
        "maximum_signed_axial_force_N": float(np.max(array)),
        "negative_segment_count": int(np.count_nonzero(array < 0.0)),
        "nonpositive_segment_count": int(np.count_nonzero(array <= 0.0)),
        "segment_count": int(array.size),
    }


def fixed_state_constitutive_audit(
    base: Any,
    model: HighFidelityModel,
) -> dict[str, Any]:
    """Evaluate one alpha=1 prepared state under the constitutive endpoint.

    Runtime mutation is confined to instantaneous evaluation and restored
    before return.  No candidate configuration or dynamic trajectory is run.
    """

    preparation = prepare_initial_state(base, model)
    original_scale = float(model.compression_regularization_scale)
    particles, bob, quaternion, velocities, bob_velocity, omega = model.unpack_state(
        preparation.state
    )
    records: list[dict[str, Any]] = []
    baseline_forces: dict[str, np.ndarray] | None = None
    baseline_compressed_masks: dict[str, np.ndarray] | None = None
    try:
        for scale in FIXED_STATE_SNAPSHOT_SCALES:
            model.compression_regularization_scale = float(scale)
            reference = reference_snapshot_from_state(
                model,
                0.0,
                preparation.state,
                include_aero=False,
                compute_contact=True,
            )
            production = model.evaluate(
                0.0,
                particles,
                velocities,
                bob,
                bob_velocity,
                quaternion,
                omega,
                include_aero=False,
                compute_contact=True,
            )
            if baseline_forces is None:
                baseline_forces = {
                    name: np.asarray(values, dtype=float).copy()
                    for name, values in reference.branch_axial_force.items()
                }
                baseline_compressed_masks = {
                    name: values < 0.0
                    for name, values in baseline_forces.items()
                }
            assert baseline_compressed_masks is not None
            branch_differences = {
                name: float(
                    np.max(
                        np.abs(
                            np.asarray(reference.branch_axial_force[name])
                            - np.asarray(production.branch_axial_force[name])
                        )
                    )
                )
                for name in sorted(reference.branch_axial_force)
            }
            compressed_scaling_residuals: dict[str, float] = {}
            for name in sorted(reference.branch_axial_force):
                mask = baseline_compressed_masks[name]
                if np.any(mask):
                    expected = float(scale) * baseline_forces[name][mask]
                    observed = np.asarray(reference.branch_axial_force[name])[mask]
                    compressed_scaling_residuals[name] = float(
                        np.max(np.abs(observed - expected))
                    )
                else:
                    compressed_scaling_residuals[name] = 0.0
            force_scale = max(
                model.force_scale,
                *(
                    float(np.max(np.abs(values)))
                    for values in reference.branch_axial_force.values()
                ),
            )
            tolerance = 5.0e-12 * max(force_scale, 1.0)
            records.append(
                {
                    "scale": float(scale),
                    "slug": scale_slug(scale),
                    "role": (
                        "mathematical_fixed_state_endpoint"
                        if scale == 0.0
                        else "fixed_state_constitutive_snapshot"
                    ),
                    "branches": {
                        name: _branch_force_summary(values)
                        for name, values in sorted(
                            reference.branch_axial_force.items()
                        )
                    },
                    "axial_energy_J": float(reference.axial_energy),
                    "rod_self_clearance_raw_margin_m": float(
                        reference.guard_margins["ROD_SELF_CLEARANCE"]
                    ),
                    "bob_socket_radial_raw_margin_m2": float(
                        reference.guard_margins[
                            "BOB_SOCKET_RADIAL_MONOTONICITY"
                        ]
                    ),
                    "production_reference_max_axial_force_difference_N": max(
                        branch_differences.values()
                    ),
                    "production_reference_axial_energy_difference_J": abs(
                        float(production.axial_energy)
                        - float(reference.axial_energy)
                    ),
                    "compressed_force_linear_scaling_max_residual_N": max(
                        compressed_scaling_residuals.values()
                    ),
                    "instantaneous_kernel_crosscheck_passed": (
                        max(branch_differences.values()) <= tolerance
                        and abs(
                            float(production.axial_energy)
                            - float(reference.axial_energy)
                        )
                        <= tolerance * model.characteristic_length
                    ),
                }
            )
    finally:
        model.compression_regularization_scale = original_scale

    return {
        "scope": (
            "the single alpha=1 held-endpoint prepared state at t=0, with no "
            "re-preparation, time integration, event comparison, or qualification"
        ),
        "prepared_state_sha256_little_endian_float64": _state_sha256(
            preparation.state
        ),
        "preparation": {
            "mode": preparation.preparation_mode,
            "force_residual_inf_N": float(preparation.residual_inf_N),
            "iterations": int(preparation.iterations),
            "bob_held": bool(preparation.bob_held),
        },
        "snapshots": records,
        "all_instantaneous_kernel_crosschecks_passed": all(
            item["instantaneous_kernel_crosscheck_passed"] for item in records
        ),
        "interpretation": (
            "At fixed geometry and velocity the registered constitutive blend "
            "scales the bilateral compressive contribution continuously to zero. "
            "This is not an alpha-specific prepared state and cannot substitute "
            "for a dynamic compression-limit study."
        ),
    }


def build(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    raw_independence = yaml.safe_load(
        INDEPENDENCE_SPEC_PATH.read_text(encoding="utf-8")
    )
    frozen_scales = tuple(float(value) for value in raw_independence["limit_scales"])
    if frozen_scales != CONFIG_CANDIDATE_SCALES:
        raise ValueError(
            "Formal independence limit scales drifted from the locked preflight."
        )

    script_hash_start = builder.sha256_file(SCRIPT_PATH)
    source_start = source_hash(PACKAGE_ROOT)
    base = load_config(BASE_CONFIG_PATH)
    validate_physical_config(base)
    model = HighFidelityModel(base)
    config_preflight = [
        configuration_preflight(base, scale)
        for scale in (*CONFIG_CANDIDATE_SCALES, 0.0)
    ]
    chord_audit = fixed_endpoint_chord_audit(base, model)
    fixed_state = fixed_state_constitutive_audit(base, model)
    source_end = source_hash(PACKAGE_ROOT)
    script_hash_end = builder.sha256_file(SCRIPT_PATH)
    identity_checks = {
        "script_stable": script_hash_start == script_hash_end,
        "formal_source_stable": source_start == source_end,
        "formal_source_matches_qualification_freeze": source_start
        == json.loads(
            (CANDIDATE_ROOT / "qualification_plan.json").read_text(
                encoding="utf-8"
            )
        )["formal_hf_source_sha256"],
        "instantaneous_production_reference_crosscheck": fixed_state[
            "all_instantaneous_kernel_crosschecks_passed"
        ],
    }
    if not all(identity_checks.values()):
        raise RuntimeError(f"Compression preflight identity drift: {identity_checks}")

    expected_held_rejections = [
        item
        for item in config_preflight
        if 0.0 < item["scale"] < 1.0
    ]
    if any(
        item["rejection_code"] != "HF_HELD_PREPARATION_REQUIRES_BILATERAL_ROD"
        for item in expected_held_rejections
    ):
        raise RuntimeError(
            "An alpha<1 held candidate no longer fails at the registered boundary."
        )
    exact_zero = next(item for item in config_preflight if item["scale"] == 0.0)
    if exact_zero["formal_config_accepted"]:
        raise RuntimeError("The exact unilateral endpoint became executable silently.")

    report = {
        "schema_version": "YPS-4TO3-HF-COMPRESSION-LIMIT-PREFLIGHT-1.0",
        "status": "BLOCKED_PENDING_PREPARATION_PROTOCOL_DECISION",
        "scope": (
            "4:3 production-mesh compression-limit preflight and frozen-state "
            "constitutive audit; no alpha<1 config emission or dynamic run"
        ),
        "git_head_at_preflight": builder.git_head(),
        "script_sha256": script_hash_start,
        "base_config": str(BASE_CONFIG_PATH.relative_to(CANDIDATE_ROOT)),
        "base_config_file_sha256": builder.sha256_file(BASE_CONFIG_PATH),
        "base_resolved_config_sha256": resolved_config_sha256(base),
        "base_initial_condition_type": base.initial_condition.type,
        "formal_hf_source_sha256": source_start,
        "formal_independence_spec": str(
            INDEPENDENCE_SPEC_PATH.relative_to(builder.REPOSITORY_ROOT)
        ),
        "formal_independence_spec_sha256": builder.sha256_file(
            INDEPENDENCE_SPEC_PATH
        ),
        "formal_limit_scales": list(CONFIG_CANDIDATE_SCALES),
        "isolated_field": "high_fidelity.compression_regularization_scale",
        "config_preflight": config_preflight,
        "fixed_endpoint_chord_audit": chord_audit,
        "fixed_state_constitutive_audit": fixed_state,
        "identity_checks": identity_checks,
        "runnable_candidate_count": 0,
        "dynamic_run_count": 0,
        "decision_required": {
            "question": (
                "Which initial-state preparation identity should define the "
                "alpha<1 and unilateral dynamic study?"
            ),
            "why_a_technical_default_is_not_selected": (
                "The available alternatives answer different physical questions: "
                "re-equilibrating each constitutive law changes the prepared rod "
                "shape and stored energy, while injecting the alpha=1 state creates "
                "an instantaneous constitutive quench."
            ),
            "options": [
                {
                    "id": "ALPHA_SPECIFIC_HELD_EQUILIBRIUM",
                    "description": (
                        "Keep the same held bob and junction endpoints, prepare a "
                        "separate equilibrium for every alpha, and compare both "
                        "preparation and release dynamics."
                    ),
                    "required_change": (
                        "Register and verify a new alpha<1 held-endpoint preparation "
                        "implementation; the current formal backend does not provide it."
                    ),
                },
                {
                    "id": "SHARED_ALPHA1_STATE_CONSTITUTIVE_QUENCH",
                    "description": (
                        "Reuse the exact alpha=1 prepared material state for every "
                        "alpha and change the constitutive response at release."
                    ),
                    "required_change": (
                        "Register explicit state injection/restart semantics and "
                        "accept that the alpha<1 runs do not start in their own equilibrium."
                    ),
                },
                {
                    "id": "CHANGE_ENDPOINT_PREPARATION",
                    "description": (
                        "Use cartesian_release or static_equilibrium so existing "
                        "alpha<1 configuration validation can be satisfied."
                    ),
                    "required_change": (
                        "Accept a changed release identity: cartesian_release does "
                        "not hold the junction, and static_equilibrium does not "
                        "preserve the frozen bob/junction endpoint pair."
                    ),
                },
            ],
            "geometric_direct_release_excluded": (
                "It would preserve both requested endpoints, but the 4:3 lower "
                "endpoint chord is shorter than its material rest length, so the "
                "formal implementation rejects the inferred straight state."
            ),
        },
        "claim_boundary": (
            "The fixed-state audit demonstrates only the instantaneous algebraic "
            "constitutive limit on one bilateral prepared state.  It is not a "
            "prepared-state, trajectory, numerical-qualification, physical, or "
            "experimental result."
        ),
    }
    builder.write_json(output_root / "preflight.json", report)
    manifest_entries = [
        ("build_compression_limit_configs.py", SCRIPT_PATH),
        ("compression_limit/preflight.json", output_root / "preflight.json"),
        (
            str(BASE_CONFIG_PATH.relative_to(CANDIDATE_ROOT)),
            BASE_CONFIG_PATH,
        ),
        (
            os.path.relpath(INDEPENDENCE_SPEC_PATH, CANDIDATE_ROOT),
            INDEPENDENCE_SPEC_PATH,
        ),
    ]
    manifest_lines = [
        f"{builder.sha256_file(path)}  {label}"
        for label, path in sorted(manifest_entries)
    ]
    manifest_path = output_root / "MANIFEST.inputs.sha256"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    report = build()
    print(
        json.dumps(
            {
                "status": report["status"],
                "runnable_candidate_count": report["runnable_candidate_count"],
                "dynamic_run_count": report["dynamic_run_count"],
                "formal_limit_scales": report["formal_limit_scales"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

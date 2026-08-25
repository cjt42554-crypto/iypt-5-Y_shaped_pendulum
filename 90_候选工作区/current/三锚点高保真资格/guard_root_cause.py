#!/usr/bin/env python3
"""Locate the prepared-state guard minima behind the three-anchor HF NO-GO.

This is a read-only diagnostic of the formal backend.  It preserves the frozen
3e-4 normalized qualification margin and resolves the public scalar guards into
their branch, material-cell and geometric-scale contributors.  Counterfactual
exclusion factors are reported as diagnostics, not recommendations.
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
from ypendulum.hf.reference import (
    _rod_rod_margins_reference,
    material_point_from_joint_reference,
    material_segments_outside_socket_reference,
    materially_separated_segment_distance_reference,
    reference_snapshot_from_state,
    segment_segment_distance_reference,
    socket_material_breakpoints_reference,
)
from ypendulum.hf.solver import prepare_initial_state
from ypendulum.hf.validation import _freeze_and_validate_spec, _space_configs
from ypendulum.io.provenance import source_hash


SCRIPT_PATH = Path(__file__).resolve()
CANDIDATE_ROOT = SCRIPT_PATH.parent
PACKAGE_ROOT = builder.HF_SOURCE_ROOT / "ypendulum"
BRANCH_NAMES = ("upper_A", "upper_B", "lower")
CURRENT_SAME_BRANCH_EXCLUSION_FACTOR = 1.01


def materially_separated_argmin(
    first_start: np.ndarray,
    first_end: np.ndarray,
    second_start: np.ndarray,
    second_end: np.ndarray,
    *,
    first_material_start: float,
    first_material_end: float,
    second_material_start: float,
    second_material_end: float,
    minimum_material_separation: float,
) -> dict[str, Any]:
    """Return an argmin for the formal fixed-material separation domain."""

    first_span = float(first_material_end - first_material_start)
    second_span = float(second_material_end - second_material_start)
    offset = float(
        minimum_material_separation
        - (second_material_start - first_material_start)
    )

    def feasible(parameter: np.ndarray) -> float:
        first_parameter, second_parameter = parameter
        return (
            second_parameter * second_span
            - first_parameter * first_span
            - offset
        )

    polygon = [
        np.array([0.0, 0.0]),
        np.array([1.0, 0.0]),
        np.array([1.0, 1.0]),
        np.array([0.0, 1.0]),
    ]
    tolerance = 128.0 * np.finfo(float).eps * max(
        first_span,
        second_span,
        abs(offset),
        np.finfo(float).tiny,
    )
    clipped: list[np.ndarray] = []
    for start, end in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        start_value = feasible(start)
        end_value = feasible(end)
        start_inside = start_value >= -tolerance
        end_inside = end_value >= -tolerance
        if start_inside:
            clipped.append(start)
        if start_inside != end_inside:
            fraction = start_value / (start_value - end_value)
            clipped.append(start + fraction * (end - start))
    if not clipped:
        return {
            "distance_m": float("inf"),
            "first_parameter": None,
            "second_parameter": None,
            "candidate_type": "EMPTY_FEASIBLE_DOMAIN",
        }

    p0 = np.asarray(first_start, dtype=float)
    q0 = np.asarray(second_start, dtype=float)
    first_direction = np.asarray(first_end, dtype=float) - p0
    second_direction = np.asarray(second_end, dtype=float) - q0

    def delta(parameter: np.ndarray) -> np.ndarray:
        return (
            p0
            + parameter[0] * first_direction
            - q0
            - parameter[1] * second_direction
        )

    candidates: list[tuple[float, np.ndarray, str]] = [
        (float(np.linalg.norm(delta(vertex))), vertex.copy(), "CLIPPED_VERTEX")
        for vertex in clipped
    ]
    for start, end in zip(clipped, clipped[1:] + clipped[:1], strict=True):
        parameter_direction = end - start
        spatial_start = delta(start)
        spatial_direction = (
            parameter_direction[0] * first_direction
            - parameter_direction[1] * second_direction
        )
        denominator = float(spatial_direction @ spatial_direction)
        if denominator > 0.0:
            fraction = float(
                np.clip(
                    -(spatial_start @ spatial_direction) / denominator,
                    0.0,
                    1.0,
                )
            )
            parameter = start + fraction * parameter_direction
            candidates.append(
                (
                    float(np.linalg.norm(delta(parameter))),
                    parameter,
                    "CLIPPED_EDGE",
                )
            )

    normal = np.cross(first_direction, second_direction)
    normal_squared = float(normal @ normal)
    if normal_squared > 0.0:
        offset_vector = q0 - p0
        first_parameter = float(
            np.cross(offset_vector, second_direction) @ normal
            / normal_squared
        )
        second_parameter = float(
            np.cross(offset_vector, first_direction) @ normal
            / normal_squared
        )
        parameter = np.array([first_parameter, second_parameter])
        if (
            -tolerance <= first_parameter <= 1.0 + tolerance
            and -tolerance <= second_parameter <= 1.0 + tolerance
            and feasible(parameter) >= -tolerance
        ):
            candidates.append(
                (
                    float(np.linalg.norm(delta(parameter))),
                    parameter,
                    "INTERIOR_LINES",
                )
            )

    distance, parameter, candidate_type = min(candidates, key=lambda item: item[0])
    first_material = first_material_start + parameter[0] * first_span
    second_material = second_material_start + parameter[1] * second_span
    return {
        "distance_m": distance,
        "first_parameter": float(parameter[0]),
        "second_parameter": float(parameter[1]),
        "first_material_coordinate_from_branch_start_m": float(first_material),
        "second_material_coordinate_from_branch_start_m": float(second_material),
        "material_separation_m": float(second_material - first_material),
        "required_material_separation_m": float(minimum_material_separation),
        "material_constraint_slack_m": float(
            second_material - first_material - minimum_material_separation
        ),
        "candidate_type": candidate_type,
    }


def same_branch_minimum(
    model: HighFidelityModel,
    branch_positions: dict[str, np.ndarray],
    exclusion_factor: float,
) -> dict[str, Any]:
    """Resolve the minimum same-branch surface clearance and its argmin."""

    records: list[dict[str, Any]] = []
    for name in BRANCH_NAMES:
        points = branch_positions[name]
        branch = model.branches[name]
        material_nodes = np.concatenate(
            [[0.0], np.cumsum(branch.segment_rest_length)]
        )
        separation = exclusion_factor * (
            branch.diameter + model.minimum_clearance
        )
        for first in range(points.shape[0] - 1):
            for second in range(first + 1, points.shape[0] - 1):
                kwargs = {
                    "first_material_start": float(material_nodes[first]),
                    "first_material_end": float(material_nodes[first + 1]),
                    "second_material_start": float(material_nodes[second]),
                    "second_material_end": float(material_nodes[second + 1]),
                    "minimum_material_separation": float(separation),
                }
                reference_distance = materially_separated_segment_distance_reference(
                    points[first],
                    points[first + 1],
                    points[second],
                    points[second + 1],
                    **kwargs,
                )
                if not np.isfinite(reference_distance):
                    continue
                argmin = materially_separated_argmin(
                    points[first],
                    points[first + 1],
                    points[second],
                    points[second + 1],
                    **kwargs,
                )
                tolerance = 5.0e-12 * max(model.characteristic_length, 1.0)
                if abs(argmin["distance_m"] - reference_distance) > tolerance:
                    raise RuntimeError(
                        "Diagnostic same-branch argmin disagrees with the formal "
                        f"reference distance for {name}:{first},{second}."
                    )
                surface_clearance = reference_distance - branch.diameter
                records.append(
                    {
                        "branch": name,
                        "first_segment_index": first,
                        "second_segment_index": second,
                        "segment_count": points.shape[0] - 1,
                        "diameter_m": branch.diameter,
                        "minimum_material_separation_m": separation,
                        "centerline_distance_m": reference_distance,
                        "surface_clearance_m": surface_clearance,
                        "raw_guard_margin_m": (
                            surface_clearance - model.minimum_clearance
                        ),
                        "argmin": argmin,
                    }
                )
    if not records:
        raise RuntimeError("No finite same-branch contact candidate was found.")
    winner = min(records, key=lambda item: item["surface_clearance_m"])
    per_branch = {
        name: min(
            (item for item in records if item["branch"] == name),
            key=lambda item: item["surface_clearance_m"],
        )
        for name in BRANCH_NAMES
    }
    return {
        "exclusion_factor": float(exclusion_factor),
        "overall": winner,
        "per_branch": per_branch,
    }


def reference_material_coordinate(
    segment_rest_length: np.ndarray,
    reference: tuple[int, int, float],
) -> float:
    nodes = np.concatenate([[0.0], np.cumsum(segment_rest_length)])
    left, right, fraction = reference
    return float((1.0 - fraction) * nodes[left] + fraction * nodes[right])


def cross_branch_minimum(
    model: HighFidelityModel,
    branch_positions: dict[str, np.ndarray],
) -> dict[str, Any]:
    """Resolve the cross-branch part of the formal rod-self guard."""

    records: list[dict[str, Any]] = []
    items = [(name, branch_positions[name]) for name in BRANCH_NAMES]
    for first_index, (name_a, points_a) in enumerate(items):
        branch_a = model.branches[name_a]
        side_a = "start" if branch_a.start_kind == "junction" else "end"
        for name_b, points_b in items[first_index + 1 :]:
            branch_b = model.branches[name_b]
            side_b = "start" if branch_b.start_kind == "junction" else "end"
            required_separation = (
                0.5 * (branch_a.diameter + branch_b.diameter)
                + model.minimum_clearance
            )
            socket_length = 2.0 * required_separation
            active_a = material_segments_outside_socket_reference(
                points_a,
                branch_a.segment_rest_length,
                side_a,
                socket_length,
            )
            active_b = material_segments_outside_socket_reference(
                points_b,
                branch_b.segment_rest_length,
                side_b,
                socket_length,
            )
            all_a = [
                (
                    points_a[index],
                    points_a[index + 1],
                    (index, index, 0.0),
                    (index + 1, index + 1, 0.0),
                )
                for index in range(points_a.shape[0] - 1)
            ]
            all_b = [
                (
                    points_b[index],
                    points_b[index + 1],
                    (index, index, 0.0),
                    (index + 1, index + 1, 0.0),
                )
                for index in range(points_b.shape[0] - 1)
            ]
            for mode, first_segments, second_segments in (
                ("FIRST_OUTSIDE_SOCKET", active_a, all_b),
                ("SECOND_OUTSIDE_SOCKET", all_a, active_b),
            ):
                for local_a, segment_a in enumerate(first_segments):
                    for local_b, segment_b in enumerate(second_segments):
                        distance = segment_segment_distance_reference(
                            segment_a[0],
                            segment_a[1],
                            segment_b[0],
                            segment_b[1],
                        )
                        surface_clearance = distance - 0.5 * (
                            branch_a.diameter + branch_b.diameter
                        )
                        records.append(
                            {
                                "first_branch": name_a,
                                "second_branch": name_b,
                                "domain_mode": mode,
                                "first_local_segment_index": local_a,
                                "second_local_segment_index": local_b,
                                "first_material_interval_from_branch_start_m": [
                                    reference_material_coordinate(
                                        branch_a.segment_rest_length,
                                        segment_a[2],
                                    ),
                                    reference_material_coordinate(
                                        branch_a.segment_rest_length,
                                        segment_a[3],
                                    ),
                                ],
                                "second_material_interval_from_branch_start_m": [
                                    reference_material_coordinate(
                                        branch_b.segment_rest_length,
                                        segment_b[2],
                                    ),
                                    reference_material_coordinate(
                                        branch_b.segment_rest_length,
                                        segment_b[3],
                                    ),
                                ],
                                "socket_rest_material_length_m": socket_length,
                                "required_center_separation_m": required_separation,
                                "centerline_distance_m": distance,
                                "surface_clearance_m": surface_clearance,
                                "raw_guard_margin_m": (
                                    surface_clearance - model.minimum_clearance
                                ),
                            }
                        )
    if not records:
        raise RuntimeError("No finite cross-branch contact candidate was found.")
    winner = min(records, key=lambda item: item["surface_clearance_m"])
    per_pair: dict[str, dict[str, Any]] = {}
    for item in records:
        pair = f"{item['first_branch']}__{item['second_branch']}"
        if (
            pair not in per_pair
            or item["surface_clearance_m"]
            < per_pair[pair]["surface_clearance_m"]
        ):
            per_pair[pair] = item
    return {"overall": winner, "per_pair": per_pair}


def same_branch_raw_guard_for_factor(
    model: HighFidelityModel,
    branch_positions: dict[str, np.ndarray],
    factor: float,
) -> float:
    return float(
        same_branch_minimum(model, branch_positions, factor)["overall"][
            "raw_guard_margin_m"
        ]
    )


def counterfactual_factor_for_threshold(
    model: HighFidelityModel,
    branch_positions: dict[str, np.ndarray],
    required_raw_margin: float,
) -> float:
    """Find a diagnostic exclusion factor on the fixed prepared geometry."""

    lower = CURRENT_SAME_BRANCH_EXCLUSION_FACTOR
    if (
        same_branch_raw_guard_for_factor(model, branch_positions, lower)
        >= required_raw_margin
    ):
        return lower
    upper = 1.25
    while (
        same_branch_raw_guard_for_factor(model, branch_positions, upper)
        < required_raw_margin
    ):
        upper *= 1.5
        if upper > 8.0:
            raise RuntimeError("Could not bracket a counterfactual exclusion factor.")
    for _ in range(60):
        middle = 0.5 * (lower + upper)
        if (
            same_branch_raw_guard_for_factor(model, branch_positions, middle)
            >= required_raw_margin
        ):
            upper = middle
        else:
            lower = middle
    return upper


def bob_socket_radial_diagnostic(
    model: HighFidelityModel,
    branch_positions: dict[str, np.ndarray],
    bob_position: np.ndarray,
    required_normalized_margin: float,
) -> dict[str, Any]:
    """Resolve the cellwise radial-monotonicity dot-product guard."""

    branch = model.branches["lower"]
    points = branch_positions["lower"]
    socket_length = (
        model.bob_contact_radius
        + 0.5 * branch.diameter
        + model.minimum_clearance
    )
    breakpoints = socket_material_breakpoints_reference(
        branch.segment_rest_length,
        "end",
        socket_length,
    )
    cells: list[dict[str, Any]] = []
    for left, right in zip(breakpoints[:-1], breakpoints[1:], strict=True):
        start, _ = material_point_from_joint_reference(
            points,
            branch.segment_rest_length,
            "end",
            float(left),
        )
        end, _ = material_point_from_joint_reference(
            points,
            branch.segment_rest_length,
            "end",
            float(right),
        )
        radial = start - bob_position
        increment = end - start
        radial_norm = float(np.linalg.norm(radial))
        increment_norm = float(np.linalg.norm(increment))
        dot = float(radial @ increment)
        cosine = (
            dot / (radial_norm * increment_norm)
            if radial_norm > 0.0 and increment_norm > 0.0
            else None
        )
        span = float(right - left)
        cells.append(
            {
                "material_interval_from_bob_attachment_m": [
                    float(left),
                    float(right),
                ],
                "rest_material_span_m": span,
                "spatial_increment_m": increment_norm,
                "start_radius_from_bob_center_m": radial_norm,
                "radial_increment_cosine": cosine,
                "raw_dot_product_m2": dot,
                "raw_dot_product_per_rest_span_m": dot / span,
            }
        )
    winner = min(cells, key=lambda item: item["raw_dot_product_m2"])
    scale = model.characteristic_length**2
    required_raw = required_normalized_margin * scale
    return {
        "socket_rest_material_length_m": socket_length,
        "cell_count": len(cells),
        "cells": cells,
        "minimum_cell": winner,
        "raw_guard_margin_m2": winner["raw_dot_product_m2"],
        "normalization_scale_m2": scale,
        "normalized_guard_margin": winner["raw_dot_product_m2"] / scale,
        "required_normalized_guard_margin": required_normalized_margin,
        "required_raw_margin_m2": required_raw,
        "raw_margin_deficit_m2": max(
            required_raw - winner["raw_dot_product_m2"],
            0.0,
        ),
        "threshold_passed": (
            winner["raw_dot_product_m2"] > required_raw
        ),
        "maximum_global_length_scale_for_current_raw_margin_m": (
            float(
                np.sqrt(
                    winner["raw_dot_product_m2"]
                    / required_normalized_margin
                )
            )
            if winner["raw_dot_product_m2"] > 0.0
            else 0.0
        ),
        "scaling_identity": (
            "raw dot product is local radius times local cell increment times "
            "their cosine; it decreases with material-cell size on a smooth rod"
        ),
    }


def level_diagnostic(
    config: Any,
    level_index: int,
    required_normalized_margin: float,
) -> dict[str, Any]:
    model = HighFidelityModel(config)
    preparation = prepare_initial_state(config, model)
    snapshot = reference_snapshot_from_state(model, 0.0, preparation.state)
    branch_positions = snapshot.branch_positions
    same = same_branch_minimum(
        model,
        branch_positions,
        CURRENT_SAME_BRANCH_EXCLUSION_FACTOR,
    )
    cross = cross_branch_minimum(model, branch_positions)
    formal_rod = _rod_rod_margins_reference(model, branch_positions)
    category_surface_minimum = min(
        same["overall"]["surface_clearance_m"],
        cross["overall"]["surface_clearance_m"],
    )
    tolerance = 5.0e-12 * max(model.characteristic_length, 1.0)
    if abs(category_surface_minimum - formal_rod[0]) > tolerance:
        raise RuntimeError("Category decomposition disagrees with the formal rod guard.")
    public_rod_raw = float(snapshot.guard_margins["ROD_SELF_CLEARANCE"])
    if abs(public_rod_raw - (formal_rod[0] - model.minimum_clearance)) > tolerance:
        raise RuntimeError("Public and formal-reference rod guards disagree.")

    metadata = model.guard_component_metadata()
    normalized_guards = {
        name: float(value) / float(metadata[name]["scale"])
        for name, value in sorted(snapshot.guard_margins.items())
    }
    failures = [
        {
            "guard": name,
            "normalized_margin": value,
            "required_normalized_margin": required_normalized_margin,
        }
        for name, value in normalized_guards.items()
        if value <= required_normalized_margin
    ]
    characteristic_length = model.characteristic_length
    required_raw_rod = required_normalized_margin * characteristic_length
    nominal_excess = (
        (CURRENT_SAME_BRANCH_EXCLUSION_FACTOR - 1.0)
        * (
            same["overall"]["diameter_m"]
            + model.minimum_clearance
        )
    )
    actual_factor = counterfactual_factor_for_threshold(
        model,
        branch_positions,
        required_raw_rod,
    )
    straight_factor = 1.0 + required_raw_rod / (
        same["overall"]["diameter_m"] + model.minimum_clearance
    )
    _, bob_position, _, _, _, _ = model.unpack_state(preparation.state)
    radial = bob_socket_radial_diagnostic(
        model,
        branch_positions,
        bob_position,
        required_normalized_margin,
    )
    public_radial = float(
        snapshot.guard_margins["BOB_SOCKET_RADIAL_MONOTONICITY"]
    )
    if abs(public_radial - radial["raw_guard_margin_m2"]) > tolerance:
        raise RuntimeError("Resolved and public bob-socket radial guards disagree.")

    return {
        "level_index": level_index,
        "role": "finest_production" if level_index == 2 else "formal_coarse_trend",
        "mesh": {
            name: int(getattr(config.cables, name).elements)
            for name in BRANCH_NAMES
        },
        "resolved_config_sha256": resolved_config_sha256(config),
        "preparation": {
            "mode": preparation.preparation_mode,
            "force_residual_inf_N": float(preparation.residual_inf_N),
            "iterations": int(preparation.iterations),
        },
        "characteristic_length_m": characteristic_length,
        "minimum_clearance_m": model.minimum_clearance,
        "normalized_guards": normalized_guards,
        "failed_guard_components": failures,
        "rod_self_clearance": {
            "formal_surface_clearance_m": formal_rod[0],
            "public_raw_guard_margin_m": public_rod_raw,
            "normalized_guard_margin": public_rod_raw / characteristic_length,
            "required_raw_margin_m": required_raw_rod,
            "raw_margin_deficit_m": max(required_raw_rod - public_rod_raw, 0.0),
            "winning_category": (
                "SAME_BRANCH"
                if same["overall"]["surface_clearance_m"]
                <= cross["overall"]["surface_clearance_m"]
                else "CROSS_BRANCH"
            ),
            "same_branch": same,
            "cross_branch": cross,
            "nominal_straight_local_excess_m": nominal_excess,
            "actual_minus_nominal_local_excess_m": public_rod_raw - nominal_excess,
            "maximum_global_length_scale_for_current_raw_margin_m": (
                public_rod_raw / required_normalized_margin
            ),
            "counterfactual_same_branch_exclusion_factor_for_fixed_state": actual_factor,
            "straight_rod_exclusion_factor_estimate_for_threshold": straight_factor,
            "counterfactual_boundary": (
                "Factors are fixed-state diagnostics only; changing the formal "
                "contact domain is a model-definition decision."
            ),
        },
        "bob_socket_radial_monotonicity": radial,
    }


def run(output_path: Path) -> dict[str, Any]:
    plan_path = CANDIDATE_ROOT / "qualification_plan.json"
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    spec_bytes = builder.VALIDATION_SPEC_PATH.read_bytes()
    spec = _freeze_and_validate_spec(yaml.safe_load(spec_bytes))
    required_normalized_margin = float(
        spec["physics_checks"]["minimum_normalized_guard_margin"]
    )
    script_hash_start = builder.sha256_file(SCRIPT_PATH)
    source_start = source_hash(PACKAGE_ROOT)
    anchors: list[dict[str, Any]] = []
    for anchor in plan["anchors"]:
        base = load_config(CANDIDATE_ROOT / anchor["config"])
        anchors.append(
            {
                "anchor": anchor["anchor"],
                "slug": anchor["slug"],
                "levels": [
                    level_diagnostic(
                        config,
                        index,
                        required_normalized_margin,
                    )
                    for index, config in enumerate(_space_configs(base))
                ],
            }
        )
    source_end = source_hash(PACKAGE_ROOT)
    script_hash_end = builder.sha256_file(SCRIPT_PATH)
    identities = {
        "script_stable": script_hash_start == script_hash_end,
        "formal_source_stable": source_start == source_end,
        "formal_source_matches_frozen_plan": (
            source_start == plan["formal_hf_source_sha256"]
        ),
        "qualification_plan_file_stable": plan_path.read_bytes() == plan_bytes,
        "validation_spec_file_stable": (
            builder.VALIDATION_SPEC_PATH.read_bytes() == spec_bytes
        ),
    }
    if not all(identities.values()):
        raise RuntimeError(f"Guard diagnostic identity drift: {identities}")

    finest = {item["slug"]: item["levels"][2] for item in anchors}
    report = {
        "schema_version": "YPS-THREE-ANCHOR-HF-GUARD-ROOT-CAUSE-1.0",
        "status": "ROOT_CAUSE_DIAGNOSTIC_COMPLETE__FORMAL_CHANGE_NOT_AUTHORIZED",
        "scope": (
            "prepared t=0 guard decomposition on all three formal spatial levels; "
            "no dynamic rerun and no formal model/spec modification"
        ),
        "required_normalized_guard_margin": required_normalized_margin,
        "formal_hf_source_sha256": source_start,
        "formal_validation_spec_sha256": builder.sha256_file(
            builder.VALIDATION_SPEC_PATH
        ),
        "qualification_plan_sha256": builder.sha256_file(plan_path),
        "script_sha256": script_hash_start,
        "identity_checks": identities,
        "anchors": anchors,
        "cross_anchor_findings": {
            "rod_self_winning_category_all_levels": all(
                level["rod_self_clearance"]["winning_category"]
                == "SAME_BRANCH"
                for item in anchors
                for level in item["levels"]
            ),
            "rod_self_winning_branch_all_levels": all(
                level["rod_self_clearance"]["same_branch"]["overall"]["branch"]
                == "lower"
                for item in anchors
                for level in item["levels"]
            ),
            "rod_self_nominal_guard_origin": (
                "The registered same-branch material exclusion is only 1.01 times "
                "(diameter + minimum_clearance), leaving a nominal straight-rod "
                "raw margin of 0.01 times that local distance.  The qualification "
                "threshold instead requires 3e-4 times the global characteristic "
                "length."
            ),
            "finest_raw_rod_margin_m": {
                slug: level["rod_self_clearance"]["public_raw_guard_margin_m"]
                for slug, level in finest.items()
            },
            "finest_required_raw_rod_margin_m": {
                slug: level["rod_self_clearance"]["required_raw_margin_m"]
                for slug, level in finest.items()
            },
            "two_to_one_additional_failed_guard": [
                item["guard"]
                for item in finest["2to1"]["failed_guard_components"]
                if item["guard"] != "ROD_SELF_CLEARANCE"
            ],
            "bob_socket_radial_mesh_scaling": (
                "BOB_SOCKET_RADIAL_MONOTONICITY is a cellwise r dot delta-r "
                "quantity.  Its raw positive value shrinks with local material-cell "
                "span, while the qualification scale remains global length squared."
            ),
            "diagnostic_conclusion": (
                "The t=0 failures are guard-contract scale incompatibilities, not "
                "evidence of negative raw clearance or socket reversal.  Choosing a "
                "different exclusion domain, component scale, or component-specific "
                "qualification rule changes the formal model/spec and is not made here."
            ),
        },
        "claim_boundary": (
            "This diagnosis identifies implementation-level guard contributors.  It "
            "does not select the physically correct contact/socket definition and does "
            "not restore HF numerical qualification."
        ),
    }
    builder.write_json(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=CANDIDATE_ROOT / "results" / "guard_root_cause.json",
    )
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    report = run(output)
    print(
        json.dumps(
            {
                "status": report["status"],
                "anchor_count": len(report["anchors"]),
                "output": str(output),
                "two_to_one_additional_failed_guard": report[
                    "cross_anchor_findings"
                ]["two_to_one_additional_failed_guard"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

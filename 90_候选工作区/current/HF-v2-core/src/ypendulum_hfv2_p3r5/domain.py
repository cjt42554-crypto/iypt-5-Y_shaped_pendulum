"""Pure P3R5 candidate enumeration, constructibility and hash selection."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from copy import deepcopy
from typing import Any

PHYSICAL_KEYS = (
    "support_A_position_m",
    "support_B_position_m",
    "junction_position_m",
    "upper_branch_rest_length_m",
    "lower_branch_rest_length_m",
    "axial_rigidity_N",
    "line_density_kg_per_m",
    "branch_contact_radius_m",
    "minimum_clearance_m",
    "bob_mass_kg",
    "bob_contact_radius_m",
    "bob_inertia_body_kg_m2",
    "attachment_arm_body_m",
    "gravity_m_per_s2",
    "analytic_stationary_bob_position_m",
)


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def physical_signature(contract: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(contract[key]) for key in PHYSICAL_KEYS}


def physical_signature_sha256(contract: dict[str, Any]) -> str:
    return canonical_sha256(physical_signature(contract))


def _diagonal(value: float) -> list[list[float]]:
    return [[value, 0.0, 0.0], [0.0, value, 0.0], [0.0, 0.0, value]]


def _asymmetric_candidates(source: dict[str, Any]) -> list[dict[str, Any]]:
    names = tuple(source["cartesian_product_order"])
    candidates = []
    for values in itertools.product(*(source[name] for name in names)):
        parameters = dict(zip(names, values, strict=True))
        theta_a = math.radians(float(parameters["upper_A_angle_from_vertical_deg"]))
        theta_b = math.radians(float(parameters["upper_B_angle_from_vertical_deg"]))
        depth = float(parameters["analytic_bob_depth_m"])
        length_a = float(parameters["upper_A_rest_length_m"])
        length_b = float(parameters["upper_B_rest_length_m"])
        bob_radius = float(parameters["bob_contact_radius_m"])
        clearance = float(parameters["minimum_clearance_m"])
        radius_a = depth * math.sin(theta_a) - bob_radius - clearance
        radius_b = depth * math.sin(theta_b) - bob_radius - clearance
        lower_radius = 0.05 * depth
        bob_mass = 0.95 * depth
        inertia = 0.5 * bob_mass * bob_radius**2
        candidates.append(
            {
                "category": "asymmetric_unequal_positive_multipliers",
                "design_construction": (
                    "analytic_axis_point_tangent_to_two_unequal_angle_upper_branch_capsules"
                ),
                "design_angles_from_vertical_deg": {
                    "upper_A": math.degrees(theta_a),
                    "upper_B": math.degrees(theta_b),
                },
                "support_A_position_m": [
                    -length_a * math.sin(theta_a),
                    0.0,
                    -length_a * math.cos(theta_a),
                ],
                "support_B_position_m": [
                    length_b * math.sin(theta_b),
                    0.0,
                    -length_b * math.cos(theta_b),
                ],
                "junction_position_m": [0.0, 0.0, 0.0],
                "upper_branch_rest_length_m": {
                    "upper_A": length_a,
                    "upper_B": length_b,
                },
                "lower_branch_rest_length_m": 0.78 * depth,
                "axial_rigidity_N": 800.0 * depth,
                "line_density_kg_per_m": 0.0098 * depth,
                "branch_contact_radius_m": {
                    "upper_A": radius_a,
                    "upper_B": radius_b,
                    "lower": lower_radius,
                },
                "minimum_clearance_m": clearance,
                "bob_mass_kg": bob_mass,
                "bob_contact_radius_m": bob_radius,
                "bob_inertia_body_kg_m2": _diagonal(inertia),
                "attachment_arm_body_m": [0.0, 0.0, 0.21 * depth],
                "gravity_m_per_s2": [0.0, 0.0, -9.81],
                "analytic_stationary_bob_position_m": [0.0, 0.0, -depth],
                "declared_active_constraint_ids": list(
                    source["derived_values"]["declared_active_constraint_ids"]
                ),
            }
        )
    return candidates


def _scale_candidate(source: dict[str, Any], scale: float) -> dict[str, Any]:
    base = source["base_family"]

    def scaled_vector(name: str) -> list[float]:
        return [scale * float(value) for value in base[name]]

    inertia = scale**3 * float(base["bob_inertia_diagonal_kg_m2"])
    radius = scale * float(base["branch_contact_radius_m"])
    upper_length = scale * float(base["upper_branch_rest_length_m"])
    return {
        "category": "changed_geometry_and_load_scale",
        "design_construction": (
            "uniform_geometry_scale_of_read_only_P3R_35_degree_family_with_new_unobserved_scale"
        ),
        "geometry_scale_from_P3R_35_degree": scale,
        "support_A_position_m": scaled_vector("support_A_position_m"),
        "support_B_position_m": scaled_vector("support_B_position_m"),
        "junction_position_m": scaled_vector("junction_position_m"),
        "upper_branch_rest_length_m": {
            "upper_A": upper_length,
            "upper_B": upper_length,
        },
        "lower_branch_rest_length_m": scale * float(base["lower_branch_rest_length_m"]),
        "axial_rigidity_N": scale * float(base["axial_rigidity_N"]),
        "line_density_kg_per_m": scale * float(base["line_density_kg_per_m"]),
        "branch_contact_radius_m": {
            "upper_A": radius,
            "upper_B": radius,
            "lower": radius,
        },
        "minimum_clearance_m": scale * float(base["minimum_clearance_m"]),
        "bob_mass_kg": scale * float(base["bob_mass_kg"]),
        "bob_contact_radius_m": scale * float(base["bob_contact_radius_m"]),
        "bob_inertia_body_kg_m2": _diagonal(inertia),
        "attachment_arm_body_m": [
            0.0,
            0.0,
            scale * float(base["attachment_arm_z_m"]),
        ],
        "gravity_m_per_s2": list(base["gravity_m_per_s2"]),
        "analytic_stationary_bob_position_m": scaled_vector("analytic_stationary_bob_position_m"),
        "declared_active_constraint_ids": list(source["declared_active_constraint_ids"]),
    }


def enumerate_candidates(domain: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    sources = domain["candidate_enumeration"]
    asymmetric = _asymmetric_candidates(sources["asymmetric_unequal_positive_multipliers"])
    scale_source = sources["changed_geometry_and_load_scale"]
    excluded = {float(value) for value in scale_source["excluded_observed_scale_values"]}
    scale = [
        _scale_candidate(scale_source, float(value))
        for value in scale_source["scale_values_in_enumeration_order"]
        if float(value) not in excluded
    ]
    return {
        "asymmetric_unequal_positive_multipliers": asymmetric,
        "changed_geometry_and_load_scale": scale,
    }


def _numeric_values(value: object) -> list[float]:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _numeric_values(child)]
    if isinstance(value, (list, tuple)):
        return [item for child in value for item in _numeric_values(child)]
    raise TypeError(f"Unsupported candidate value {type(value)!r}.")


def _distance(first: list[float], second: list[float]) -> float:
    return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(first, second, strict=True)))


def _segment_witness(
    point: list[float],
    start: list[float],
    end: list[float],
) -> tuple[float, float]:
    direction = [float(b) - float(a) for a, b in zip(start, end, strict=True)]
    offset = [float(p) - float(a) for p, a in zip(point, start, strict=True)]
    squared = sum(value * value for value in direction)
    parameter = sum(a * b for a, b in zip(offset, direction, strict=True)) / squared
    closest = [float(a) + parameter * value for a, value in zip(start, direction, strict=True)]
    return parameter, _distance(point, closest)


def pure_constructibility(
    contract: dict[str, Any],
    domain: dict[str, Any],
    observed_physical_signatures: set[str],
) -> dict[str, Any]:
    predicate = domain["pure_input_constructibility_predicate"]
    numeric = _numeric_values(contract)
    upper = contract["upper_branch_rest_length_m"]
    radii = contract["branch_contact_radius_m"]
    lengths = {
        "upper_A": float(upper["upper_A"]),
        "upper_B": float(upper["upper_B"]),
        "lower": float(contract["lower_branch_rest_length_m"]),
    }
    positive = [
        *lengths.values(),
        float(contract["axial_rigidity_N"]),
        float(contract["line_density_kg_per_m"]),
        *(float(value) for value in radii.values()),
        float(contract["minimum_clearance_m"]),
        float(contract["bob_mass_kg"]),
        float(contract["bob_contact_radius_m"]),
        *(float(contract["bob_inertia_body_kg_m2"][index][index]) for index in range(3)),
        math.sqrt(sum(float(value) ** 2 for value in contract["attachment_arm_body_m"])),
    ]
    junction = list(contract["junction_position_m"])
    support_a = list(contract["support_A_position_m"])
    support_b = list(contract["support_B_position_m"])
    bob = list(contract["analytic_stationary_bob_position_m"])
    tolerance = float(predicate["support_length_identity_absolute_tolerance_m"])
    support_identity = bool(
        abs(_distance(support_a, junction) - lengths["upper_A"]) <= tolerance
        and abs(_distance(support_b, junction) - lengths["upper_B"]) <= tolerance
    )
    witness_a, distance_a = _segment_witness(bob, support_a, junction)
    witness_b, distance_b = _segment_witness(bob, support_b, junction)
    clearance = float(contract["minimum_clearance_m"])
    bob_radius = float(contract["bob_contact_radius_m"])
    tangency_tolerance = float(predicate["analytic_tangency_identity_absolute_tolerance_m"])
    tangency = bool(
        abs(distance_a - (bob_radius + float(radii["upper_A"]) + clearance)) <= tangency_tolerance
        and abs(distance_b - (bob_radius + float(radii["upper_B"]) + clearance))
        <= tangency_tolerance
    )
    witness_margin = min(witness_a, 1.0 - witness_a, witness_b, 1.0 - witness_b)
    pair_socket_margins = []
    branches = ("upper_A", "upper_B", "lower")
    for first, second in itertools.combinations(branches, 2):
        socket = 2.0 * (float(radii[first]) + float(radii[second]) + clearance)
        pair_socket_margins.append(min(lengths[first], lengths[second]) - socket)
    bob_socket_margin = lengths["lower"] - (bob_radius + float(radii["lower"]) + clearance)
    declared_ids = tuple(contract["declared_active_constraint_ids"])
    signature = physical_signature_sha256(contract)
    checks = {
        "all_numeric_values_finite": bool(numeric and all(math.isfinite(item) for item in numeric)),
        "positive_fields": bool(positive and min(positive) > 0.0),
        "support_length_identity": support_identity,
        "analytic_tangency_identity": tangency,
        "junction_socket_positive_active_extent": min(pair_socket_margins) > 0.0,
        "bob_socket_positive_active_extent": bob_socket_margin > 0.0,
        "upper_contact_witness_parameter_margin": witness_margin
        >= float(predicate["upper_contact_witness_parameter_margin_min"]),
        "declared_active_identity_count": len(declared_ids)
        == int(predicate["declared_active_identity_count"]),
        "declared_active_identities_unique": len(declared_ids) == len(set(declared_ids)),
        "noncollapsed_distinct_supports": bool(
            _distance(support_a, junction) > 0.0
            and _distance(support_b, junction) > 0.0
            and _distance(support_a, support_b) > 0.0
        ),
        "physical_signature_unobserved": signature not in observed_physical_signatures,
    }
    return {
        "identity": domain["pure_input_constructibility_predicate"]["identity"],
        "passed": all(checks.values()),
        "checks": checks,
        "minimum_junction_socket_active_extent_margin_m": min(pair_socket_margins),
        "bob_socket_active_extent_margin_m": bob_socket_margin,
        "minimum_upper_contact_witness_parameter_margin": witness_margin,
        "physical_signature_sha256": signature,
    }


def observed_signature_set(*design_documents: dict[str, Any]) -> set[str]:
    return {
        physical_signature_sha256(contract)
        for document in design_documents
        for contract in document["design_cards"]
    }


def select_holdouts(
    domain: dict[str, Any],
    implementation_commit: str,
    observed_physical_signatures: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(implementation_commit) != 40 or any(
        character not in "0123456789abcdef" for character in implementation_commit
    ):
        raise ValueError("P3R5 holdout selection requires one lowercase Git commit hash.")
    candidates = enumerate_candidates(domain)
    selected_cards: list[dict[str, Any]] = []
    selection_trace: list[dict[str, Any]] = []
    count = int(domain["holdout_count_per_category"])
    for category in domain["required_categories_in_order"]:
        eligible = []
        for candidate in candidates[category]:
            predicate = pure_constructibility(
                candidate,
                domain,
                observed_physical_signatures,
            )
            if not predicate["passed"]:
                continue
            payload = canonical_json(candidate)
            preimage = (
                "P3R5-HOLDOUT-1.0\0" + implementation_commit + "\0" + category + "\0" + payload
            ).encode("utf-8")
            digest = hashlib.sha256(preimage).hexdigest()
            eligible.append((digest, payload, candidate, predicate))
        eligible.sort(key=lambda item: (item[0], item[1]))
        if len(eligible) < count:
            raise ValueError(f"P3R5 pure domain has fewer than {count} {category} cards.")
        prefix = "ASYM" if category.startswith("asymmetric") else "SCALE"
        for index, (digest, _payload, candidate, predicate) in enumerate(eligible[:count], start=1):
            holdout_id = f"R5_{prefix}_H{index:02d}"
            card = deepcopy(candidate)
            card["holdout_id"] = holdout_id
            card["design_id"] = holdout_id
            card["selection_digest_sha256"] = digest
            card["pure_constructibility"] = predicate
            card["input_assembly_execution_count_before_holdout_freeze"] = 0
            card["reference_construction_execution_count_before_holdout_freeze"] = 0
            card["target_admissibility_execution_count_before_holdout_freeze"] = 0
            card["second_order_execution_count_before_holdout_freeze"] = 0
            card["manifold_neighborhood_execution_count_before_holdout_freeze"] = 0
            card["qualification_seed_execution_count_before_holdout_freeze"] = 0
            selected_cards.append(card)
            selection_trace.append(
                {
                    "holdout_id": holdout_id,
                    "category": category,
                    "selection_digest_sha256": digest,
                    "canonical_candidate_sha256": canonical_sha256(candidate),
                    "physical_signature_sha256": predicate["physical_signature_sha256"],
                }
            )
    return selected_cards, selection_trace


def build_holdout_freeze(
    domain: dict[str, Any],
    implementation_commit: str,
    observed_physical_signatures: set[str],
    *,
    generated_at: str,
    domain_sha256: str,
) -> dict[str, Any]:
    cards, trace = select_holdouts(
        domain,
        implementation_commit,
        observed_physical_signatures,
    )
    return {
        "schema": "YPS-HFV2-P3R5-HOLDOUT-CARDS-1.0",
        "generated_at": generated_at,
        "implementation_commit": implementation_commit,
        "holdout_domain_sha256": domain_sha256,
        "selection_rule": domain["selection"],
        "required_categories_in_order": list(domain["required_categories_in_order"]),
        "holdout_count_per_category": int(domain["holdout_count_per_category"]),
        "pure_input_constructibility_identity": domain["pure_input_constructibility_predicate"][
            "identity"
        ],
        "selection_trace": trace,
        "holdout_cards": cards,
        "input_assembly_run_count_before_holdout_freeze": 0,
        "reference_construction_run_count_before_holdout_freeze": 0,
        "target_admissibility_run_count_before_holdout_freeze": 0,
        "second_order_run_count_before_holdout_freeze": 0,
        "manifold_neighborhood_run_count_before_holdout_freeze": 0,
        "target_freeze_run_count_before_holdout_freeze": 0,
        "qualification_seed_run_count_before_holdout_freeze": 0,
        "status": "P3R5_HOLDOUTS_FROZEN_WITH_ZERO_NUMERICAL_RUNS",
    }


__all__ = [
    "build_holdout_freeze",
    "canonical_json",
    "canonical_sha256",
    "enumerate_candidates",
    "observed_signature_set",
    "physical_signature",
    "physical_signature_sha256",
    "pure_constructibility",
    "select_holdouts",
]

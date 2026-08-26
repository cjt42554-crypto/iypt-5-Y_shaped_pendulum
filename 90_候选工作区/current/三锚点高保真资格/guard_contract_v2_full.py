#!/usr/bin/env python3
"""Evaluate the complete candidate HF guard qualification contract v2.

The formal model remains the sole owner of physical guard domains and raw
zero-crossing semantics.  This module independently resolves every public raw
guard into local geometric candidates and changes only the dimensionless
qualification normalization.  It is a candidate research layer; it does not
rewrite historical status or patch the formal solver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

import numpy as np


SCRIPT_PATH = Path(__file__).resolve()
CANDIDATE_ROOT = SCRIPT_PATH.parent
DEFAULT_SPEC = CANDIDATE_ROOT / "guard_contract_v2" / "full_spec.json"
COMPONENT_NAMES = (
    "MINIMUM_SEGMENT_LENGTH",
    "BENDING_TURN_CLEARANCE",
    "AERODYNAMIC_CHORD_LENGTH",
    "BOB_ROD_CLEARANCE",
    "ROD_SELF_CLEARANCE",
    "BOB_SOCKET_MATERIAL_EXTENT",
    "BOB_SOCKET_RADIAL_MONOTONICITY",
    "BOB_SOCKET_CUT_CLEARANCE",
    "JUNCTION_SOCKET_MATERIAL_EXTENT",
    "JUNCTION_SOCKET_PROJECTIVE_OPENING",
    "JUNCTION_SOCKET_CUT_CLEARANCE",
)


class ContractError(ValueError):
    """A full candidate-contract input is incomplete or inconsistent."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


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


def _positive(name: str, value: Any) -> float:
    number = _finite(name, value)
    if number <= 0.0:
        raise ContractError(f"{name} must be strictly positive; got {number!r}.")
    return number


def _candidate(
    label: str,
    raw_margin: Any,
    local_scale: Any,
    **metadata: Any,
) -> dict[str, Any]:
    raw = _finite(f"{label}.raw_margin", raw_margin)
    scale = _positive(f"{label}.local_scale", local_scale)
    return {
        "label": label,
        "raw_margin": raw,
        "local_scale": scale,
        "normalized_margin": raw / scale,
        "raw_positive": raw > 0.0,
        **metadata,
    }


def _point_segment_distance(
    point: np.ndarray, start: np.ndarray, end: np.ndarray
) -> float:
    direction = np.asarray(end, dtype=float) - np.asarray(start, dtype=float)
    denominator = float(direction @ direction)
    if denominator <= 0.0:
        return float(np.linalg.norm(np.asarray(point, dtype=float) - start))
    fraction = float(
        np.clip(
            (np.asarray(point, dtype=float) - start) @ direction / denominator,
            0.0,
            1.0,
        )
    )
    closest = np.asarray(start, dtype=float) + fraction * direction
    return float(np.linalg.norm(np.asarray(point, dtype=float) - closest))


def segment_length_candidates(
    branch: str,
    points: np.ndarray,
    rest_lengths: np.ndarray,
    length_guard: float,
) -> list[dict[str, Any]]:
    """Resolve segment-length margins using each segment's own rest span."""

    positions = np.asarray(points, dtype=float)
    rest = np.asarray(rest_lengths, dtype=float)
    lengths = np.linalg.norm(np.diff(positions, axis=0), axis=1)
    if lengths.shape != rest.shape:
        raise ContractError(f"{branch}: segment/rest shapes differ.")
    return [
        _candidate(
            f"{branch}:segment:{index}",
            length - length_guard,
            rest[index],
            branch=branch,
            segment_index=index,
            current_length_m=float(length),
            rest_length_m=float(rest[index]),
        )
        for index, length in enumerate(lengths)
    ]


def bending_turn_candidates(
    branch: str,
    points: np.ndarray,
    clearance_floor: float,
) -> list[dict[str, Any]]:
    """Resolve the native dimensionless anti-reversal turn measure."""

    segments = np.diff(np.asarray(points, dtype=float), axis=0)
    lengths = np.linalg.norm(segments, axis=1)
    if np.any(lengths <= 0.0):
        raise ContractError(f"{branch}: collapsed segment in turn audit.")
    tangents = segments / lengths[:, None]
    raw = 1.0 + np.einsum("ij,ij->i", tangents[:-1], tangents[1:]) - clearance_floor
    return [
        _candidate(
            f"{branch}:turn:{index + 1}",
            value,
            1.0,
            branch=branch,
            internal_vertex_index=index + 1,
            scale_identity="native_dimensionless_turn_measure",
        )
        for index, value in enumerate(raw)
    ]


def aerodynamic_chord_candidates(
    branch: str,
    points: np.ndarray,
    rest_lengths: np.ndarray,
    chord_guard: float,
) -> list[dict[str, Any]]:
    """Resolve two-segment bead chords against their adjacent rest span."""

    positions = np.asarray(points, dtype=float)
    rest = np.asarray(rest_lengths, dtype=float)
    chords = np.linalg.norm(positions[2:] - positions[:-2], axis=1)
    local_spans = rest[:-1] + rest[1:]
    if chords.shape != local_spans.shape:
        raise ContractError(f"{branch}: chord/rest-span shapes differ.")
    return [
        _candidate(
            f"{branch}:chord:{index + 1}",
            chord - chord_guard,
            local_spans[index],
            branch=branch,
            bead_point_index=index + 1,
            current_chord_m=float(chord),
            adjacent_rest_span_m=float(local_spans[index]),
        )
        for index, chord in enumerate(chords)
    ]


def radial_monotonicity_candidates(
    socket_points: np.ndarray, bob_position: np.ndarray
) -> list[dict[str, Any]]:
    """Resolve every unchanged bob-socket material cell as a local cosine."""

    points = np.asarray(socket_points, dtype=float)
    bob = np.asarray(bob_position, dtype=float)
    radial = points[:-1] - bob
    increments = points[1:] - points[:-1]
    records: list[dict[str, Any]] = []
    for index, (radius, increment) in enumerate(
        zip(radial, increments, strict=True)
    ):
        raw = float(radius @ increment)
        scale = float(np.linalg.norm(radius) * np.linalg.norm(increment))
        records.append(
            _candidate(
                f"bob_socket:radial_cell:{index}",
                raw,
                scale,
                cell_index=index,
                radial_norm_m=float(np.linalg.norm(radius)),
                increment_norm_m=float(np.linalg.norm(increment)),
                scale_identity="norm_r_times_norm_delta_r",
            )
        )
    return records


def _aggregate_component(
    name: str,
    unit: str,
    candidates: Iterable[dict[str, Any]],
    public_raw_margin: Any,
    threshold: float,
) -> dict[str, Any]:
    records = list(candidates)
    if not records:
        raise ContractError(f"{name} has no local candidates.")
    public_raw = _finite(f"{name}.public_raw_margin", public_raw_margin)
    raw_winner = min(records, key=lambda item: item["raw_margin"])
    normalized_winner = min(
        records, key=lambda item: item["normalized_margin"]
    )
    identity_tolerance = 8192.0 * np.finfo(float).eps * max(
        1.0, abs(public_raw), abs(float(raw_winner["raw_margin"]))
    )
    identity_error = abs(float(raw_winner["raw_margin"]) - public_raw)
    if identity_error > identity_tolerance:
        raise ContractError(
            f"{name} local resolution disagrees with the formal raw guard: "
            f"resolved={raw_winner['raw_margin']!r}, public={public_raw!r}, "
            f"tolerance={identity_tolerance!r}."
        )
    raw_passed = public_raw > 0.0
    normalized = float(normalized_winner["normalized_margin"])
    threshold_passed = normalized > threshold
    return {
        "component": name,
        "raw_unit": unit,
        "candidate_count": len(records),
        "public_raw_margin": public_raw,
        "resolved_raw_minimum": float(raw_winner["raw_margin"]),
        "raw_identity_error": identity_error,
        "raw_identity_tolerance": identity_tolerance,
        "raw_domain_and_zero_preserved": True,
        "raw_gate_passed": raw_passed,
        "normalized_minimum": normalized,
        "minimum_normalized_margin_required": threshold,
        "strict_threshold_passed": threshold_passed,
        "passed": raw_passed and threshold_passed,
        "raw_winner": raw_winner,
        "normalized_winner": normalized_winner,
    }


def validate_spec(spec: dict[str, Any]) -> float:
    expected_schema = "YPS-HF-GUARD-QUALIFICATION-CONTRACT-2.1-FULL-CANDIDATE"
    if spec.get("schema_version") != expected_schema:
        raise ContractError("Unsupported full candidate guard-contract schema.")
    if spec.get("formal_change_authorized") is not False:
        raise ContractError("Full candidate spec must not claim formal authorization.")
    if spec.get("physical_guard_domains_changed") is not False:
        raise ContractError("Physical guard domains must remain unchanged.")
    if spec.get("raw_zero_crossing_semantics_changed") is not False:
        raise ContractError("Raw zero-crossing semantics must remain unchanged.")
    if spec.get("comparison") != "strictly_greater_than":
        raise ContractError("The full contract must retain strict comparison.")
    components = spec.get("components")
    if not isinstance(components, dict) or set(components) != set(COMPONENT_NAMES):
        raise ContractError("The full contract must classify exactly all public guards.")
    return _positive(
        "minimum_normalized_margin", spec["minimum_normalized_margin"]
    )


def evaluate_prepared_state(
    model: Any,
    state: np.ndarray,
    spec: dict[str, Any],
    *,
    time_s: float = 0.0,
) -> dict[str, Any]:
    """Evaluate all 11 local-scale components at one formal HF state."""

    from ypendulum.hf.model import (
        _batched_segment_segment_distance,
        _materially_separated_segment_distance,
        _minimum_cartesian_segment_distance,
        _registered_active_segments,
        _registered_material_points,
        _registered_projective_opening_squared,
        _registered_socket_cut,
    )

    threshold = validate_spec(spec)
    state_array = np.asarray(state, dtype=float)
    (
        particle_positions,
        bob_position,
        quaternion,
        particle_velocities,
        bob_velocity,
        angular_velocity,
    ) = model.unpack_state(state_array)
    evaluation = model.evaluate(
        float(time_s),
        particle_positions,
        particle_velocities,
        bob_position,
        bob_velocity,
        quaternion,
        angular_velocity,
        include_aero=False,
        compute_contact=True,
    )
    public = model.guard_components_from_evaluation(evaluation)
    if set(public) != set(COMPONENT_NAMES):
        raise ContractError(
            f"Formal public guard vocabulary drifted: {sorted(public)}."
        )
    branch_positions = evaluation.branch_positions
    records: dict[str, list[dict[str, Any]]] = {
        name: [] for name in COMPONENT_NAMES
    }

    for branch_name, branch in model.branches.items():
        points = branch_positions[branch_name]
        rest = branch.segment_rest_length
        records["MINIMUM_SEGMENT_LENGTH"].extend(
            segment_length_candidates(
                branch_name, points, rest, model.length_guard
            )
        )
        records["BENDING_TURN_CLEARANCE"].extend(
            bending_turn_candidates(
                branch_name, points, model.bending_turn_clearance_floor
            )
        )
        records["AERODYNAMIC_CHORD_LENGTH"].extend(
            aerodynamic_chord_candidates(
                branch_name, points, rest, model.aerodynamic_chord_guard
            )
        )

    for branch_name, branch in model.branches.items():
        points = branch_positions[branch_name]
        required = (
            model.bob_contact_radius
            + 0.5 * branch.diameter
            + model.minimum_clearance
        )
        if branch_name == "lower":
            checked = _registered_active_segments(
                points, model.bob_socket_registration
            )
        else:
            checked = np.stack([points[:-1], points[1:]], axis=1)
        for index, segment in enumerate(checked):
            records["BOB_ROD_CLEARANCE"].append(
                _candidate(
                    f"{branch_name}:bob_rod:{index}",
                    _point_segment_distance(
                        bob_position, segment[0], segment[1]
                    )
                    - required,
                    required,
                    branch=branch_name,
                    checked_segment_index=index,
                    required_center_distance_m=float(required),
                )
            )

    for branch_name, branch in model.branches.items():
        points = branch_positions[branch_name]
        registration = model.same_branch_contact_registration[branch_name]
        required = branch.diameter + model.minimum_clearance
        if registration.full_pairs.size:
            pairs = registration.full_pairs
            distances = _batched_segment_segment_distance(
                points[pairs[:, 0]],
                points[pairs[:, 0] + 1],
                points[pairs[:, 1]],
                points[pairs[:, 1] + 1],
            )
            for pair, distance in zip(pairs, distances, strict=True):
                records["ROD_SELF_CLEARANCE"].append(
                    _candidate(
                        f"{branch_name}:same_full:{int(pair[0])}:{int(pair[1])}",
                        float(distance) - required,
                        required,
                        category="SAME_BRANCH_FULL",
                        branch=branch_name,
                        first_segment_index=int(pair[0]),
                        second_segment_index=int(pair[1]),
                    )
                )
        for partial in registration.partial_pairs:
            (
                first,
                second,
                first_start,
                first_end,
                second_start,
                second_end,
            ) = partial
            distance = _materially_separated_segment_distance(
                points[first],
                points[first + 1],
                points[second],
                points[second + 1],
                first_material_start=first_start,
                first_material_end=first_end,
                second_material_start=second_start,
                second_material_end=second_end,
                minimum_material_separation=(
                    registration.minimum_material_separation
                ),
            )
            if np.isfinite(distance):
                records["ROD_SELF_CLEARANCE"].append(
                    _candidate(
                        f"{branch_name}:same_partial:{first}:{second}",
                        float(distance) - required,
                        required,
                        category="SAME_BRANCH_PARTIAL",
                        branch=branch_name,
                        first_segment_index=int(first),
                        second_segment_index=int(second),
                    )
                )

    for registration in model.junction_contact_registration:
        name_a = registration.first_name
        name_b = registration.second_name
        points_a = branch_positions[name_a]
        points_b = branch_positions[name_b]
        branch_a = model.branches[name_a]
        branch_b = model.branches[name_b]
        required = registration.required_center_separation
        active_a = _registered_active_segments(
            points_a, registration.first_socket
        )
        active_b = _registered_active_segments(
            points_b, registration.second_socket
        )

        for side, socket in (
            (name_a, registration.first_socket),
            (name_b, registration.second_socket),
        ):
            records["JUNCTION_SOCKET_MATERIAL_EXTENT"].append(
                _candidate(
                    f"{name_a}__{name_b}:extent:{side}",
                    socket.total_length - socket.socket_length,
                    socket.socket_length,
                    branch_pair=f"{name_a}__{name_b}",
                    branch=side,
                    socket_rest_material_length_m=float(socket.socket_length),
                )
            )
        if active_a.size == 0 or active_b.size == 0:
            continue
        all_a = np.stack([points_a[:-1], points_a[1:]], axis=1)
        all_b = np.stack([points_b[:-1], points_b[1:]], axis=1)
        for mode, first_segments, second_segments in (
            ("FIRST_OUTSIDE_SOCKET", active_a, all_b),
            ("SECOND_OUTSIDE_SOCKET", all_a, active_b),
        ):
            distance = _minimum_cartesian_segment_distance(
                first_segments, second_segments
            )
            records["ROD_SELF_CLEARANCE"].append(
                _candidate(
                    f"{name_a}__{name_b}:cross:{mode}",
                    distance - required,
                    required,
                    category="CROSS_BRANCH",
                    branch_pair=f"{name_a}__{name_b}",
                    domain_mode=mode,
                )
            )
        opening_squared = _registered_projective_opening_squared(
            points_a,
            registration.first_socket,
            points_b,
            registration.second_socket,
        )
        records["JUNCTION_SOCKET_PROJECTIVE_OPENING"].append(
            _candidate(
                f"{name_a}__{name_b}:projective_opening",
                opening_squared
                - registration.registered_projective_opening_squared,
                1.0,
                branch_pair=f"{name_a}__{name_b}",
                opening_squared=float(opening_squared),
                registered_opening_squared=float(
                    registration.registered_projective_opening_squared
                ),
                scale_identity="native_dimensionless_projective_measure",
            )
        )
        boundary_a = _registered_socket_cut(
            points_a, registration.first_socket
        )
        boundary_b = _registered_socket_cut(
            points_b, registration.second_socket
        )
        records["JUNCTION_SOCKET_CUT_CLEARANCE"].append(
            _candidate(
                f"{name_a}__{name_b}:socket_cut",
                float(np.linalg.norm(boundary_a - boundary_b)) - required,
                required,
                branch_pair=f"{name_a}__{name_b}",
                required_center_separation_m=float(required),
            )
        )

    bob_registration = model.bob_socket_registration
    records["BOB_SOCKET_MATERIAL_EXTENT"].append(
        _candidate(
            "lower:bob_socket_material_extent",
            bob_registration.total_length - bob_registration.socket_length,
            bob_registration.socket_length,
            socket_rest_material_length_m=float(
                bob_registration.socket_length
            ),
            lower_total_rest_material_length_m=float(
                bob_registration.total_length
            ),
        )
    )
    socket_points = _registered_material_points(
        branch_positions["lower"], bob_registration
    )
    records["BOB_SOCKET_RADIAL_MONOTONICITY"].extend(
        radial_monotonicity_candidates(socket_points, bob_position)
    )
    required_bob_radius = bob_registration.socket_length
    bob_boundary = _registered_socket_cut(
        branch_positions["lower"], bob_registration
    )
    records["BOB_SOCKET_CUT_CLEARANCE"].append(
        _candidate(
            "lower:bob_socket_cut",
            float(np.linalg.norm(bob_boundary - bob_position))
            - required_bob_radius,
            required_bob_radius,
            required_center_distance_m=float(required_bob_radius),
        )
    )

    units = {
        name: str(model.guard_component_metadata()[name]["unit"])
        for name in COMPONENT_NAMES
    }
    components = {
        name: _aggregate_component(
            name,
            units[name],
            records[name],
            public[name],
            threshold,
        )
        for name in COMPONENT_NAMES
    }
    failures = [
        name for name in COMPONENT_NAMES if not components[name]["passed"]
    ]
    minimum_name = min(
        COMPONENT_NAMES,
        key=lambda name: components[name]["normalized_minimum"],
    )
    return {
        "schema_version": "YPS-HF-GUARD-FULL-CANDIDATE-STATE-EVALUATION-2.1",
        "status": (
            "FULL_CANDIDATE_GUARD_PASS"
            if not failures
            else "FULL_CANDIDATE_GUARD_FAIL"
        ),
        "time_s": float(time_s),
        "formal_model_id": model.model_id,
        "compression_regularization_scale": float(
            model.compression_regularization_scale
        ),
        "minimum_normalized_margin_required": threshold,
        "strict_comparison": True,
        "physical_guard_domains_changed": False,
        "raw_zero_crossing_semantics_changed": False,
        "all_public_raw_guards_resolved": True,
        "component_count": len(components),
        "passed": not failures,
        "failed_components": failures,
        "minimum_component": minimum_name,
        "minimum_normalized_margin": float(
            components[minimum_name]["normalized_minimum"]
        ),
        "components": components,
        "spec_schema_version": spec["schema_version"],
        "spec_canonical_sha256": canonical_sha256(spec),
        "claim_boundary": (
            "Prepared-state candidate qualification only. It preserves every "
            "formal raw guard and does not certify a continuous trajectory, "
            "numerical convergence, physical validity or experiment."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and hash the complete candidate guard spec. Live state "
            "evaluation is invoked by the mesh-audit and alpha-preparation runners."
        )
    )
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    args = parser.parse_args()
    spec_path = args.spec.expanduser().resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    threshold = validate_spec(spec)
    print(
        json.dumps(
            {
                "status": "FULL_CANDIDATE_GUARD_SPEC_VALID",
                "component_count": len(COMPONENT_NAMES),
                "minimum_normalized_margin": threshold,
                "spec_sha256": sha256_file(spec_path),
                "spec_canonical_sha256": canonical_sha256(spec),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

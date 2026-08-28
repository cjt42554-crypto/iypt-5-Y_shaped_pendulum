"""Build a bounded reduced-Hessian stability map without new contact runs."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import PchipInterpolator

matplotlib.use("Agg", force=True)
matplotlib.rcParams["svg.fonttype"] = "none"
matplotlib.rcParams["svg.hashsalt"] = "yps-p3r5-readonly-stability-map-1.0"

OUTPUT_SCHEMA = "YPS-P3R5-READONLY-REDUCED-HESSIAN-MAP-1.0"
FIGURE_METADATA = {
    "Creator": "YPS-P3R5-READONLY-REDUCED-HESSIAN-MAP-1.0",
    "Date": None,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class ObservedMode:
    holdout_id: str
    geometry_scale: float
    length_scale_m: float
    reference_z_m: float
    negative_y_normalized: float
    negative_rotation_x: float
    positive_y_normalized: float
    positive_rotation_x: float
    lambda_negative: float
    lambda_rotation_y: float
    lambda_stiff: float
    independent_negative_curvature: float
    curvature_crosscheck_error: float

    @property
    def mode_angle_rad(self) -> float:
        return math.atan2(self.negative_rotation_x, self.negative_y_normalized)

    @property
    def physical_rotation_per_lateral_translation_rad_per_m(self) -> float:
        return self.negative_rotation_x / (self.length_scale_m * self.negative_y_normalized)


def _load_bound_json(repository_root: Path, binding: dict[str, Any]) -> Any:
    path = repository_root / str(binding["path"])
    actual = _sha256(path)
    expected = str(binding["sha256"])
    if actual != expected:
        raise RuntimeError(
            f"Frozen source hash mismatch for {path}: expected {expected}, got {actual}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_modes(
    config: dict[str, Any], cards_document: dict[str, Any], metrics: dict[str, Any]
) -> tuple[ObservedMode, ...]:
    category = str(config["source_category"])
    cards = {
        str(card["holdout_id"]): card
        for card in cards_document["holdout_cards"]
        if card["category"] == category
    }
    outcomes = {
        str(outcome["holdout_id"]): outcome
        for outcome in metrics["outcomes"]
        if outcome["category"] == category
    }
    expected = tuple(config["expected_holdout_ids"])
    if tuple(cards) != expected or tuple(outcomes) != expected:
        raise RuntimeError(
            "Frozen scale-card identities or order changed; refusing to construct a map."
        )
    rows: list[ObservedMode] = []
    for holdout_id in expected:
        card = cards[holdout_id]
        outcome = outcomes[holdout_id]
        critical = outcome["critical_cone"]
        if outcome["status"] != "TARGET_INVALID" or critical["passed"] is not False:
            raise RuntimeError(f"Unexpected frozen classification for {holdout_id}.")
        directions = np.asarray(critical["critical_directions"], dtype=float)
        curvatures = np.asarray(critical["matrix_directional_curvatures"], dtype=float)
        independent = np.asarray(critical["independent_directional_curvatures"], dtype=float)
        if directions.shape != (6, 6) or curvatures.shape != (6,):
            raise RuntimeError(f"Unexpected critical-cone dimensions for {holdout_id}.")
        basis = np.column_stack([directions[0], directions[2], directions[4]])
        if not np.allclose(basis.T @ basis, np.eye(3), rtol=0.0, atol=2.0e-12):
            raise RuntimeError(f"Supported tangent basis is not orthonormal: {holdout_id}")
        eigenvalues = np.asarray(critical["supported_tangent_eigenvalues"], dtype=float)
        expected_eigenvalues = np.sort([curvatures[0], curvatures[4], curvatures[2]])
        if not np.allclose(eigenvalues, expected_eigenvalues, rtol=0.0, atol=2.0e-12):
            raise RuntimeError(f"Directional/eigenvalue identity mismatch: {holdout_id}")
        off_mode = directions[0].copy()
        off_mode[[1, 3]] = 0.0
        if float(np.linalg.norm(off_mode, ord=np.inf)) > 2.0e-12:
            raise RuntimeError(
                f"Negative direction is not confined to lateral translation and roll: {holdout_id}"
            )
        rows.append(
            ObservedMode(
                holdout_id=holdout_id,
                geometry_scale=float(card["geometry_scale_from_P3R_35_degree"]),
                length_scale_m=float(outcome["characteristic_scales"]["length_m"]),
                reference_z_m=float(outcome["reference_coordinates"][2]),
                negative_y_normalized=float(directions[0, 1]),
                negative_rotation_x=float(directions[0, 3]),
                positive_y_normalized=float(directions[2, 1]),
                positive_rotation_x=float(directions[2, 3]),
                lambda_negative=float(curvatures[0]),
                lambda_rotation_y=float(curvatures[4]),
                lambda_stiff=float(curvatures[2]),
                independent_negative_curvature=float(independent[0]),
                curvature_crosscheck_error=float(critical["maximum_curvature_crosscheck_error"]),
            )
        )
    return tuple(sorted(rows, key=lambda row: row.geometry_scale))


def _pchip_coefficients(interpolator: PchipInterpolator) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(interpolator.x.size - 1):
        rows.append(
            {
                "left": float(interpolator.x[index]),
                "right": float(interpolator.x[index + 1]),
                "coefficients_descending_local_power": [
                    float(value) for value in interpolator.c[:, index]
                ],
                "local_variable": (f"geometry_scale - {float(interpolator.x[index]):.17g}"),
            }
        )
    return rows


def _parameterize(
    modes: tuple[ObservedMode, ...], grid_points: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scale = np.asarray([mode.geometry_scale for mode in modes], dtype=float)
    negative = PchipInterpolator(scale, [mode.lambda_negative for mode in modes], extrapolate=False)
    rotation_y = PchipInterpolator(
        scale, [mode.lambda_rotation_y for mode in modes], extrapolate=False
    )
    stiff = PchipInterpolator(scale, [mode.lambda_stiff for mode in modes], extrapolate=False)
    angle = PchipInterpolator(scale, [mode.mode_angle_rad for mode in modes], extrapolate=False)
    grid = np.linspace(scale[0], scale[-1], grid_points)
    rows: list[dict[str, Any]] = []
    for value in grid:
        alpha = float(angle(value))
        a = math.cos(alpha)
        b = math.sin(alpha)
        lambda_negative = float(negative(value))
        lambda_rotation_y = float(rotation_y(value))
        lambda_stiff = float(stiff(value))
        rotation = np.array([[a, -b], [b, a]])
        block = rotation @ np.diag([lambda_negative, lambda_stiff]) @ rotation.T
        reduced = np.array(
            [
                [block[0, 0], block[0, 1], 0.0],
                [block[1, 0], block[1, 1], 0.0],
                [0.0, 0.0, lambda_rotation_y],
            ]
        )
        rows.append(
            {
                "geometry_scale": float(value),
                "lambda_negative": lambda_negative,
                "lambda_rotation_y": lambda_rotation_y,
                "lambda_stiff": lambda_stiff,
                "negative_y_normalized": a,
                "negative_rotation_x": b,
                "mode_angle_deg": math.degrees(alpha),
                "H_reduced_coordinate_order": [
                    "delta_y_over_length_scale",
                    "delta_rotation_x_rad",
                    "delta_rotation_y_rad",
                ],
                "H_reduced": reduced.tolist(),
                "spectral_signature": "(-,+,+)",
            }
        )
    parameterization = {
        "domain": [float(scale[0]), float(scale[-1])],
        "extrapolation_allowed": False,
        "interpolator": "shape_preserving_piecewise_cubic_PCHIP",
        "coordinate_definition": (
            "dimensionless delta_y/length_scale, rotation_x_rad, rotation_y_rad"
        ),
        "local_quadratic_potential": ("Delta_Pi = 0.5 * xi^T H_reduced(scale) xi + O(norm(xi)^3)"),
        "coefficients": {
            "lambda_negative": _pchip_coefficients(negative),
            "lambda_rotation_y": _pchip_coefficients(rotation_y),
            "lambda_stiff": _pchip_coefficients(stiff),
            "mode_angle_rad": _pchip_coefficients(angle),
        },
        "zero_crossing_status": (
            "NO_ZERO_CROSSING_OBSERVED_IN_FROZEN_DEVELOPMENT_INTERVAL"
            if all(row["lambda_negative"] < 0.0 for row in rows)
            else "ZERO_CROSSING_PRESENT_IN_INTERPOLATED_DEVELOPMENT_INTERVAL"
        ),
    }
    return rows, parameterization


def _observed_rows(modes: tuple[ObservedMode, ...]) -> list[dict[str, Any]]:
    return [
        {
            "holdout_id": mode.holdout_id,
            "geometry_scale": mode.geometry_scale,
            "length_scale_m": mode.length_scale_m,
            "reference_z_m": mode.reference_z_m,
            "negative_y_normalized": mode.negative_y_normalized,
            "negative_rotation_x": mode.negative_rotation_x,
            "mode_angle_deg": math.degrees(mode.mode_angle_rad),
            "physical_rotation_per_lateral_translation_rad_per_m": (
                mode.physical_rotation_per_lateral_translation_rad_per_m
            ),
            "lambda_negative": mode.lambda_negative,
            "lambda_rotation_y": mode.lambda_rotation_y,
            "lambda_stiff": mode.lambda_stiff,
            "independent_negative_curvature": mode.independent_negative_curvature,
            "curvature_crosscheck_error": mode.curvature_crosscheck_error,
        }
        for mode in modes
    ]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _plot(
    output_base: Path,
    observed: list[dict[str, Any]],
    grid: list[dict[str, Any]],
) -> None:
    figure, axes = plt.subplots(2, 1, figsize=(8.0, 8.2), sharex=True)
    scale = [row["geometry_scale"] for row in grid]
    axes[0].plot(scale, [row["lambda_negative"] for row in grid], label="lambda negative")
    axes[0].plot(
        scale,
        [row["lambda_rotation_y"] for row in grid],
        label="lambda rotation-y",
    )
    axes[0].plot(scale, [row["lambda_stiff"] for row in grid], label="lambda stiff")
    axes[0].scatter(
        [row["geometry_scale"] for row in observed],
        [row["lambda_negative"] for row in observed],
        color="black",
        marker="x",
        zorder=4,
        label="frozen scale cards",
    )
    axes[0].axhline(0.0, color="black", linewidth=0.8)
    axes[0].set_yscale("symlog", linthresh=0.1)
    axes[0].set_ylabel("normalized reduced-Hessian eigenvalue")
    axes[0].grid(alpha=0.25)
    axes[0].legend(ncol=2)

    axes[1].plot(
        scale,
        [abs(row["negative_y_normalized"]) for row in grid],
        label="abs(delta y / L)",
    )
    axes[1].plot(
        scale,
        [abs(row["negative_rotation_x"]) for row in grid],
        label="abs(delta rotation x)",
    )
    axes[1].scatter(
        [row["geometry_scale"] for row in observed],
        [abs(row["negative_y_normalized"]) for row in observed],
        color="tab:blue",
        marker="x",
    )
    axes[1].scatter(
        [row["geometry_scale"] for row in observed],
        [abs(row["negative_rotation_x"]) for row in observed],
        color="tab:orange",
        marker="x",
    )
    axes[1].set_xlabel("uniform geometry scale from P3R 35-degree family")
    axes[1].set_ylabel("negative-mode normalized component")
    axes[1].grid(alpha=0.25)
    axes[1].legend()
    figure.suptitle(
        "Frozen P3R5 scale-card reduced spectrum\n"
        "candidate fixed-double-active branch; not device stability"
    )
    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.95))
    figure.savefig(output_base.with_suffix(".svg"), metadata=FIGURE_METADATA)
    figure.savefig(output_base.with_suffix(".png"), dpi=180, metadata=FIGURE_METADATA)
    plt.close(figure)


def build_stability_map(
    config_path: Path, repository_root: Path, output_directory: Path
) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("schema") != "YPS-P3R5-READONLY-STABILITY-MAP-CONFIG-1.0":
        raise ValueError("Unexpected stability-map configuration schema.")
    cards = _load_bound_json(repository_root, config["source_cards"])
    metrics = _load_bound_json(repository_root, config["source_metrics"])
    modes = _extract_modes(config, cards, metrics)
    grid, parameterization = _parameterize(modes, int(config["parameterization"]["grid_points"]))
    observed = _observed_rows(modes)
    payload = {
        "schema": OUTPUT_SCHEMA,
        "analysis_identity": "P3R5_FROZEN_SCALE_DEVELOPMENT_SET_READONLY_MAP",
        "qualification_run": False,
        "new_contact_cards_generated": 0,
        "contact_solver_runs": 0,
        "source_binding": {
            "cards": config["source_cards"],
            "metrics": config["source_metrics"],
            "expected_holdout_ids": config["expected_holdout_ids"],
        },
        "coordinate_order": config["coordinate_order"],
        "interpretation_limit": config["interpretation_limit"],
        "direction_interpretation": (
            "The negative eigenvector is confined, in the normalized coordinate chart, "
            "to lateral bob translation y plus roll about x. The orthogonal y-roll "
            "combination and rotation about y remain positive on all four frozen cards."
        ),
        "observed_modes": observed,
        "parameterization": parameterization,
        "interpolated_map": grid,
        "conclusion": (
            "The frozen P3R5 fixed-double-active candidate reference has spectral "
            "signature (-,+,+) over the observed scale interval under the bounded "
            "PCHIP descriptor. No zero crossing is observed inside that interval; "
            "nothing is inferred outside it or about the physical device."
        ),
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "stability_map.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(output_directory / "observed_modes.csv", observed)
    compact_grid = [
        {
            key: row[key]
            for key in (
                "geometry_scale",
                "lambda_negative",
                "lambda_rotation_y",
                "lambda_stiff",
                "negative_y_normalized",
                "negative_rotation_x",
                "mode_angle_deg",
                "spectral_signature",
            )
        }
        for row in grid
    ]
    _write_csv(output_directory / "parameterized_map.csv", compact_grid)
    _plot(
        output_directory / "reduced_hessian_stability_map",
        observed,
        grid,
    )
    artifacts = sorted(
        path
        for path in output_directory.iterdir()
        if path.is_file() and path.name != "artifact_manifest.json"
    )
    manifest = {
        "schema": "YPS-P3R5-STABILITY-MAP-ARTIFACT-MANIFEST-1.0",
        "deterministic": True,
        "artifacts": [
            {
                "path": path.name,
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in artifacts
        ],
    }
    (output_directory / "artifact_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload

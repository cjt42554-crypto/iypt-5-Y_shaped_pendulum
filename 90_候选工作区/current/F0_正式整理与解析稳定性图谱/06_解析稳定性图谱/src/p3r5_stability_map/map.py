"""Build a bounded reduced-Hessian stability map without new contact runs."""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg", force=True)

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np
from scipy.interpolate import PchipInterpolator

matplotlib.rcParams["svg.fonttype"] = "none"
matplotlib.rcParams["svg.hashsalt"] = "yps-p3r5-readonly-stability-map-1.1"

OUTPUT_SCHEMA = "YPS-P3R5-READONLY-REDUCED-HESSIAN-MAP-1.1"
OBSERVED_EVIDENCE = "OBSERVED_AT_FOUR_FROZEN_POINTS"
INTERPOLANT_EVIDENCE = "INTERPOLANT_PROPERTY"
FIGURE_METADATA = {
    "Creator": OUTPUT_SCHEMA,
    "Date": None,
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _runtime_identity() -> dict[str, Any]:
    identity = {
        "schema": "YPS-P3R5-STABILITY-MAP-RUNTIME-IDENTITY-1.0",
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("matplotlib", "numpy", "scipy")
        },
    }
    return identity


def _analysis_source_manifest(config_path: Path) -> dict[str, Any]:
    entries = [
        ("configuration", config_path),
        ("build_metadata", PROJECT_ROOT / "pyproject.toml"),
        ("production_source", PROJECT_ROOT / "src/p3r5_stability_map/__init__.py"),
        ("production_source", PROJECT_ROOT / "src/p3r5_stability_map/__main__.py"),
        ("production_source", PROJECT_ROOT / "src/p3r5_stability_map/map.py"),
    ]
    rows = []
    for role, path in entries:
        resolved = path.resolve()
        try:
            relative_path = resolved.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            relative_path = resolved.as_posix()
        rows.append(
            {
                "role": role,
                "path": relative_path,
                "sha256": _sha256(resolved),
            }
        )
    rows.sort(key=lambda row: (row["path"], row["role"]))
    return {
        "schema": "YPS-P3R5-STABILITY-MAP-ANALYSIS-SOURCE-MANIFEST-1.0",
        "entries": rows,
    }


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


def _descriptor_interpolators(
    modes: tuple[ObservedMode, ...],
) -> tuple[np.ndarray, dict[str, PchipInterpolator]]:
    scale = np.asarray([mode.geometry_scale for mode in modes], dtype=float)
    return scale, {
        "lambda_negative": PchipInterpolator(
            scale,
            [mode.lambda_negative for mode in modes],
            extrapolate=False,
        ),
        "lambda_rotation_y": PchipInterpolator(
            scale,
            [mode.lambda_rotation_y for mode in modes],
            extrapolate=False,
        ),
        "lambda_stiff": PchipInterpolator(
            scale,
            [mode.lambda_stiff for mode in modes],
            extrapolate=False,
        ),
        "mode_angle_rad": PchipInterpolator(
            scale,
            [mode.mode_angle_rad for mode in modes],
            extrapolate=False,
        ),
    }


def _evaluate_descriptor(
    scale: np.ndarray,
    interpolators: dict[str, PchipInterpolator],
    geometry_scale: float,
) -> dict[str, Any]:
    value = float(geometry_scale)
    if not np.isfinite(value):
        raise ValueError("geometry_scale must be finite.")
    if value < float(scale[0]) or value > float(scale[-1]):
        raise ValueError(
            "NO_EXTRAPOLATION: geometry_scale lies outside the observed convex hull."
        )
    alpha = float(interpolators["mode_angle_rad"](value))
    a = math.cos(alpha)
    b = math.sin(alpha)
    lambda_negative = float(interpolators["lambda_negative"](value))
    lambda_rotation_y = float(interpolators["lambda_rotation_y"](value))
    lambda_stiff = float(interpolators["lambda_stiff"](value))
    rotation = np.array([[a, -b], [b, a]])
    block = rotation @ np.diag([lambda_negative, lambda_stiff]) @ rotation.T
    reduced = np.array(
        [
            [block[0, 0], block[0, 1], 0.0],
            [block[1, 0], block[1, 1], 0.0],
            [0.0, 0.0, lambda_rotation_y],
        ]
    )
    return {
        "evidence_class": INTERPOLANT_EVIDENCE,
        "geometry_scale": value,
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
        "H_reduced_descriptor": reduced.tolist(),
        "interpolant_spectral_signature": "(-,+,+)",
    }


def evaluate_descriptor_at_scale(
    modes: tuple[ObservedMode, ...], geometry_scale: float
) -> dict[str, Any]:
    """Evaluate the descriptive interpolant only inside the observed convex hull."""

    scale, interpolators = _descriptor_interpolators(modes)
    return _evaluate_descriptor(scale, interpolators, geometry_scale)


def _parameterize(
    modes: tuple[ObservedMode, ...], grid_points: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scale, interpolators = _descriptor_interpolators(modes)
    grid = np.linspace(scale[0], scale[-1], grid_points)
    rows = [_evaluate_descriptor(scale, interpolators, float(value)) for value in grid]
    parameterization = {
        "evidence_class": INTERPOLANT_EVIDENCE,
        "domain": [float(scale[0]), float(scale[-1])],
        "extrapolation_allowed": False,
        "interpolator": "shape_preserving_piecewise_cubic_PCHIP",
        "interpretation": (
            "descriptive visualization of four frozen observations only; values between "
            "observations are not evaluated model results or continuous proof"
        ),
        "coordinate_definition": (
            "dimensionless delta_y/length_scale, rotation_x_rad, rotation_y_rad"
        ),
        "descriptor_matrix_definition": (
            "H_reduced_descriptor is reconstructed from independently interpolated "
            "eigenvalues and mode angle"
        ),
        "coefficients": {
            name: _pchip_coefficients(interpolator)
            for name, interpolator in interpolators.items()
        },
        "zero_crossing_status": (
            "INTERPOLANT_HAS_NO_ZERO_CROSSING_ON_OBSERVED_CONVEX_HULL"
            if all(row["lambda_negative"] < 0.0 for row in rows)
            else "INTERPOLANT_HAS_ZERO_CROSSING_ON_OBSERVED_CONVEX_HULL"
        ),
    }
    return rows, parameterization


def _observed_rows(modes: tuple[ObservedMode, ...]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_class": OBSERVED_EVIDENCE,
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
    observed_scale = [row["geometry_scale"] for row in observed]
    axes[0].plot(
        scale,
        [row["lambda_negative"] for row in grid],
        label="descriptive PCHIP: lambda negative",
    )
    axes[0].plot(
        scale,
        [row["lambda_rotation_y"] for row in grid],
        label="descriptive PCHIP: lambda rotation-y",
    )
    axes[0].plot(
        scale,
        [row["lambda_stiff"] for row in grid],
        label="descriptive PCHIP: lambda stiff",
    )
    axes[0].scatter(
        observed_scale,
        [row["lambda_negative"] for row in observed],
        color="black",
        marker="x",
        zorder=4,
        label="four observed negative values",
    )
    axes[0].scatter(
        observed_scale,
        [row["lambda_rotation_y"] for row in observed],
        color="tab:orange",
        marker="o",
        facecolors="none",
        zorder=4,
        label="four observed rotation-y values",
    )
    axes[0].scatter(
        observed_scale,
        [row["lambda_stiff"] for row in observed],
        color="tab:green",
        marker="s",
        facecolors="none",
        zorder=4,
        label="four observed stiff values",
    )
    axes[0].axhline(0.0, color="black", linewidth=0.8)
    axes[0].set_yscale("symlog", linthresh=0.1)
    axes[0].set_ylabel("normalized reduced-Hessian eigenvalue")
    axes[0].grid(alpha=0.25)
    axes[0].legend(ncol=2)
    axes[0].text(
        0.02,
        0.97,
        "Observed: four frozen points\nCurves: descriptive PCHIP only\nNo extrapolation",
        transform=axes[0].transAxes,
        fontsize=9,
        verticalalignment="top",
        bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "0.7"},
    )

    axes[1].plot(
        scale,
        [abs(row["negative_y_normalized"]) for row in grid],
        label="descriptive PCHIP: abs(delta y / L)",
    )
    axes[1].plot(
        scale,
        [abs(row["negative_rotation_x"]) for row in grid],
        label="descriptive PCHIP: abs(delta rotation x)",
    )
    axes[1].scatter(
        observed_scale,
        [abs(row["negative_y_normalized"]) for row in observed],
        color="tab:blue",
        marker="x",
    )
    axes[1].scatter(
        observed_scale,
        [abs(row["negative_rotation_x"]) for row in observed],
        color="tab:orange",
        marker="x",
    )
    axes[1].set_xlabel("uniform geometry scale from P3R 35-degree family")
    axes[1].set_ylabel("negative-mode normalized component")
    axes[1].grid(alpha=0.25)
    axes[1].legend()
    axes[1].set_xlim(min(observed_scale), max(observed_scale))
    figure.suptitle(
        "Four frozen P3R5 observations with a descriptive interpolant\n"
        "interpolant properties are not unobserved model evidence"
    )
    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.95))
    figure.savefig(output_base.with_suffix(".svg"), metadata=FIGURE_METADATA)
    figure.savefig(output_base.with_suffix(".png"), dpi=180, metadata=FIGURE_METADATA)
    plt.close(figure)


def build_stability_map(
    config_path: Path, repository_root: Path, output_directory: Path
) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("schema") != "YPS-P3R5-READONLY-STABILITY-MAP-CONFIG-1.1":
        raise ValueError("Unexpected stability-map configuration schema.")
    cards = _load_bound_json(repository_root, config["source_cards"])
    metrics = _load_bound_json(repository_root, config["source_metrics"])
    modes = _extract_modes(config, cards, metrics)
    grid, parameterization = _parameterize(modes, int(config["parameterization"]["grid_points"]))
    observed = _observed_rows(modes)
    runtime_identity = _runtime_identity()
    source_manifest = _analysis_source_manifest(config_path)
    payload = {
        "schema": OUTPUT_SCHEMA,
        "analysis_identity": "P3R5_FOUR_FROZEN_POINTS_READONLY_DESCRIPTIVE_MAP",
        "qualification_run": False,
        "new_contact_cards_generated": 0,
        "contact_solver_runs": 0,
        "source_binding": {
            "cards": config["source_cards"],
            "metrics": config["source_metrics"],
            "expected_holdout_ids": config["expected_holdout_ids"],
        },
        "analysis_source_manifest": source_manifest,
        "analysis_source_manifest_sha256": _sha256_json(source_manifest),
        "runtime_identity": runtime_identity,
        "runtime_identity_sha256": _sha256_json(runtime_identity),
        "coordinate_order": config["coordinate_order"],
        "interpretation_limit": config["interpretation_limit"],
        "evidence_layers": {
            "observed": {
                "evidence_class": OBSERVED_EVIDENCE,
                "point_count": len(observed),
                "geometry_scales": [row["geometry_scale"] for row in observed],
                "interpretation": "directly extracted from four hash-bound frozen cards",
            },
            "interpolant": {
                "evidence_class": INTERPOLANT_EVIDENCE,
                "domain": parameterization["domain"],
                "extrapolation_allowed": False,
                "interpretation": (
                    "descriptive PCHIP visualization only; not evaluated model evidence "
                    "between observations"
                ),
            },
        },
        "direction_interpretation": (
            "At each of the four frozen observations, the negative eigenvector is confined, "
            "in the normalized coordinate chart, to lateral bob translation y plus roll "
            "about x. The orthogonal y-roll combination and rotation about y are positive "
            "at those same four points."
        ),
        "observed_modes": observed,
        "parameterization": parameterization,
        "descriptive_interpolant": grid,
        "conclusion": (
            "All four frozen observations have spectral signature (-,+,+). Separately, "
            "the chosen bounded PCHIP descriptor retains that signature and has no zero "
            "crossing on the observed convex hull. This is an interpolant property, not "
            "evidence at unobserved scales, a continuous proof, a bifurcation inference, "
            "a device prediction or an experimental conclusion."
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
                "evidence_class",
                "interpolant_spectral_signature",
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
        "determinism_scope": (
            "BYTE_IDENTICAL_WITHIN_RECORDED_ANALYSIS_SOURCE_CONFIG_AND_RUNTIME"
        ),
        "analysis_source_manifest_sha256": _sha256_json(source_manifest),
        "runtime_identity": runtime_identity,
        "runtime_identity_sha256": _sha256_json(runtime_identity),
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

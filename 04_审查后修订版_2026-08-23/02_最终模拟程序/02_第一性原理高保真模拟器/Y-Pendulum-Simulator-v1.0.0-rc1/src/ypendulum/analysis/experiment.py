"""Forward comparison of a frozen simulation run with experimental observations.

The comparison layer deliberately separates physical prediction from nuisance
alignment. By default no nuisance parameter is fitted. Optional time shift,
translation and planar rotation are reported explicitly so that calibration
choices can be frozen before a validation set is opened.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

from ypendulum.analysis.closure import chamfer_distance, hausdorff_distance
from ypendulum.io.csv import read_experiment_csv
from ypendulum.io.provenance import json_safe, write_json


@dataclass(frozen=True)
class AlignmentOptions:
    """Nuisance alignment options for experiment comparison."""

    estimate_time_shift: bool = False
    maximum_time_shift_s: float = 0.0
    estimate_translation: bool = False
    estimate_planar_rotation: bool = False
    minimum_overlap_samples: int = 12

    def __post_init__(self) -> None:
        if self.maximum_time_shift_s < 0.0:
            raise ValueError("maximum_time_shift_s cannot be negative.")
        if self.minimum_overlap_samples < 4:
            raise ValueError("minimum_overlap_samples must be at least four.")
        if self.estimate_time_shift and self.maximum_time_shift_s <= 0.0:
            raise ValueError("estimate_time_shift requires a strictly positive maximum_time_shift_s.")


@dataclass(frozen=True)
class AlignedComparison:
    experiment_time: np.ndarray
    prediction_time: np.ndarray
    observed: np.ndarray
    predicted_raw: np.ndarray
    predicted_aligned: np.ndarray
    overlap_mask: np.ndarray
    report: dict[str, Any]


def _validate_series(time: np.ndarray, values: np.ndarray, *, label: str) -> tuple[np.ndarray, np.ndarray]:
    t = np.asarray(time, dtype=float)
    x = np.asarray(values, dtype=float)
    if t.ndim != 1 or x.ndim != 2 or x.shape[0] != t.size:
        raise ValueError(f"{label} must have time shape (n,) and values shape (n,d).")
    if t.size < 4 or np.any(np.diff(t) <= 0.0):
        raise ValueError(f"{label} time must be strictly increasing with at least four samples.")
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(x)):
        raise ValueError(f"{label} contains NaN or infinity.")
    return t, x


def _interpolate(time: np.ndarray, values: np.ndarray, query: np.ndarray) -> np.ndarray:
    return np.column_stack([np.interp(query, time, values[:, j]) for j in range(values.shape[1])])


def _rigid_planar_fit(
    predicted: np.ndarray,
    observed: np.ndarray,
    *,
    estimate_translation: bool,
    estimate_planar_rotation: bool,
) -> tuple[np.ndarray, float, np.ndarray]:
    if predicted.shape != observed.shape or predicted.ndim != 2:
        raise ValueError("Predicted and observed arrays must have the same two-dimensional shape.")
    dimension = predicted.shape[1]
    if dimension not in (2, 3):
        raise ValueError("Planar rigid alignment supports two- or three-component observations.")

    pred_center = np.mean(predicted, axis=0) if estimate_translation else np.zeros(dimension)
    obs_center = np.mean(observed, axis=0) if estimate_translation else np.zeros(dimension)
    p = predicted - pred_center
    o = observed - obs_center

    angle = 0.0
    rotation = np.eye(dimension)
    if estimate_planar_rotation:
        numerator = float(np.sum(p[:, 0] * o[:, 1] - p[:, 1] * o[:, 0]))
        denominator = float(np.sum(p[:, 0] * o[:, 0] + p[:, 1] * o[:, 1]))
        angle = float(np.arctan2(numerator, denominator))
        c, s = float(np.cos(angle)), float(np.sin(angle))
        rotation[:2, :2] = np.array([[c, -s], [s, c]])

    transformed_centered = p @ rotation.T
    del transformed_centered
    translation = obs_center - pred_center @ rotation.T if estimate_translation else np.zeros(dimension)
    aligned = predicted @ rotation.T + translation
    return aligned, angle, translation


def align_prediction_to_experiment(
    prediction_time: np.ndarray,
    prediction_values: np.ndarray,
    experiment_time: np.ndarray,
    experiment_values: np.ndarray,
    *,
    options: AlignmentOptions | None = None,
    observation_kind: str = "cartesian",
) -> AlignedComparison:
    """Compare time-resolved prediction and experiment with explicit nuisance fitting."""

    options = AlignmentOptions() if options is None else options
    tp, xp = _validate_series(prediction_time, prediction_values, label="prediction")
    te, xe = _validate_series(experiment_time, experiment_values, label="experiment")
    if xp.shape[1] != xe.shape[1]:
        raise ValueError(f"Prediction has {xp.shape[1]} components but experiment has {xe.shape[1]}.")

    def evaluate_shift(shift: float, *, full: bool = False):
        query = te + float(shift)
        mask = (query >= tp[0]) & (query <= tp[-1])
        if int(np.count_nonzero(mask)) < options.minimum_overlap_samples:
            return (float("inf"), None) if full else float("inf")
        raw = _interpolate(tp, xp, query[mask])
        aligned, angle, translation = _rigid_planar_fit(
            raw,
            xe[mask],
            estimate_translation=options.estimate_translation,
            estimate_planar_rotation=options.estimate_planar_rotation,
        )
        error = aligned - xe[mask]
        score = float(np.sqrt(np.mean(error**2)))
        if full:
            return score, (query, mask, raw, aligned, angle, translation)
        return score

    shift = 0.0
    shift_optimisation_success = True
    if options.estimate_time_shift:
        optimum = minimize_scalar(
            lambda value: evaluate_shift(float(value)),
            bounds=(-options.maximum_time_shift_s, options.maximum_time_shift_s),
            method="bounded",
            options={"xatol": max(1e-10, options.maximum_time_shift_s * 1e-7)},
        )
        shift_optimisation_success = bool(optimum.success and np.isfinite(optimum.fun))
        if not shift_optimisation_success:
            raise RuntimeError("Time-shift optimisation failed to find a valid overlap interval.")
        shift = float(optimum.x)

    score, details = evaluate_shift(shift, full=True)
    if details is None or not np.isfinite(score):
        raise ValueError("Prediction and experiment have insufficient overlapping time samples.")
    query, mask, raw, aligned, angle, translation = details
    observed = xe[mask]
    error = aligned - observed
    point_error = np.linalg.norm(error, axis=1)
    observed_scale = float(np.sqrt(np.mean((observed - np.mean(observed, axis=0)) ** 2)))
    observed_scale = max(observed_scale, 1e-15)
    ss_res = float(np.sum(error**2))
    centered_observed = observed - np.mean(observed, axis=0)
    ss_tot = float(np.sum(centered_observed**2))

    fitted: list[str] = []
    if options.estimate_time_shift:
        fitted.append("time_shift")
    if options.estimate_translation:
        fitted.append("translation")
    if options.estimate_planar_rotation:
        fitted.append("planar_rotation")

    report: dict[str, Any] = {
        "observation_kind": observation_kind,
        "components": int(observed.shape[1]),
        "experiment_samples_total": int(te.size),
        "overlap_samples": int(observed.shape[0]),
        "overlap_fraction": float(observed.shape[0] / te.size),
        "time_shift_s": shift,
        "time_shift_definition": "prediction evaluated at experiment_time + time_shift_s",
        "time_shift_optimisation_success": shift_optimisation_success,
        "planar_rotation_rad": angle,
        "translation": translation.tolist(),
        "nuisance_parameters_fitted": fitted,
        "rms_component_error": float(np.sqrt(np.mean(error**2))),
        "normalized_rms_error": float(np.sqrt(np.mean(error**2)) / observed_scale),
        "rms_point_error": float(np.sqrt(np.mean(point_error**2))),
        "maximum_point_error": float(np.max(point_error)),
        "mean_component_bias": np.mean(error, axis=0).tolist(),
        "component_rms_error": np.sqrt(np.mean(error**2, axis=0)).tolist(),
        "r_squared_global": float(1.0 - ss_res / ss_tot) if ss_tot > 0.0 else None,
        "chamfer_distance": chamfer_distance(aligned, observed),
        "hausdorff_distance": hausdorff_distance(aligned, observed),
        "validation_interpretation": (
            "No nuisance parameter was fitted; this is a direct forward comparison."
            if not fitted
            else "Fitted nuisance parameters must be calibrated and frozen before using this metric on a validation set."
        ),
    }
    return AlignedComparison(te, query, observed, raw, aligned, mask, report)


def _run_observation(
    run_directory: Path,
    experiment: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, str, list[str], dict[str, Any]]:
    result_path = run_directory / "result.h5"
    if not result_path.exists():
        raise FileNotFoundError(f"No result.h5 found in {run_directory}.")
    spatial = {"x", "y", "z"}.issubset(experiment.columns)
    pixels = {"u_pixel", "v_pixel"}.issubset(experiment.columns)
    with h5py.File(result_path, "r") as h5:
        model = str(h5.attrs.get("model", ""))
        qualification: dict[str, Any] = {"model": model}
        if model == "HF-DISCRETE-ROD-RIGID-BOB-1.0":
            raw_status = (
                str(h5.attrs.get("physical_status", "")),
                str(h5.attrs.get("numerical_status", "")),
            )
            if raw_status not in {
                ("UNDETERMINED", "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"),
                ("OUT_OF_SCOPE", "SUCCESS_EVENT"),
            }:
                raise ValueError(
                    "Experiment comparison refuses a failed or numerically "
                    f"unresolved HF trajectory: {raw_status[0]}/{raw_status[1]}."
                )
            qualification.update(
                {
                    "physical_status": raw_status[0],
                    "numerical_status": raw_status[1],
                    "interpretation": (
                        "RAW_PERSONAL_RESEARCH_RESULT"
                        if raw_status[0] == "UNDETERMINED"
                        else "VALID_PREFIX_TERMINATED_AT_REPORTED_EVENT"
                    ),
                }
            )
        if spatial:
            bob_path = (
                "/bodies/bob/com_position"
                if model == "HF-DISCRETE-ROD-RIGID-BOB-1.0"
                else "/bodies/bob/position"
            )
            if bob_path not in h5:
                raise ValueError("Simulation result does not contain bob centre-of-mass positions.")
            return (
                np.asarray(h5["/time"]),
                np.asarray(h5[bob_path]),
                "cartesian_xyz",
                ["x", "y", "z"],
                qualification,
            )
        if pixels and "/observer/pixels" in h5 and "/observer/time" in h5:
            return (
                np.asarray(h5["/observer/time"]),
                np.asarray(h5["/observer/pixels"]),
                "camera_pixels",
                ["u_pixel", "v_pixel"],
                qualification,
            )
    if pixels:
        fallback = run_directory / "observer_output.npz"
        if fallback.exists():
            with np.load(fallback) as data:
                values = np.asarray(data["values"], dtype=float)
                if values.shape[1] != 2:
                    raise ValueError("observer_output.npz does not contain two-component pixels.")
                unit = str(np.asarray(data["value_unit"]).item()) if "value_unit" in data else ""
                operator = (
                    str(np.asarray(data["operator_id"]).item())
                    if "operator_id" in data
                    else ""
                )
                if unit != "pixel" or operator != "brown_conrady_pinhole":
                    raise ValueError(
                        "Pixel experiment cannot consume a metre-valued or unidentified "
                        "two-component observer output."
                    )
                return (
                    np.asarray(data["time"], dtype=float),
                    values,
                    "observer_2d",
                    ["u_pixel", "v_pixel"],
                    qualification,
                )
        raise ValueError("Pixel experiment requires a run generated with a pinhole observer or observer_output.npz.")
    raise ValueError("Experiment CSV does not contain a supported observation contract.")


def compare_run_to_experiment(
    run_directory: str | Path,
    experiment_csv: str | Path,
    *,
    options: AlignmentOptions | None = None,
    output_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Compare a stored run with an experimental CSV and optionally write audit files."""

    run_dir = Path(run_directory)
    experiment_path = Path(experiment_csv)
    frame = read_experiment_csv(experiment_path)
    prediction_time, prediction_values, kind, columns, qualification = (
        _run_observation(run_dir, frame)
    )
    comparison = align_prediction_to_experiment(
        prediction_time,
        prediction_values,
        frame["time"].to_numpy(dtype=float),
        frame[columns].to_numpy(dtype=float),
        options=options,
        observation_kind=kind,
    )
    report = {
        "run_directory": str(run_dir),
        "experiment_csv": str(experiment_path),
        "prediction_qualification": qualification,
        **comparison.report,
    }
    if output_directory is not None:
        target = Path(output_directory)
        target.mkdir(parents=True, exist_ok=True)
        write_json(target / "experiment_comparison.json", json_safe(report))
        out = pd.DataFrame({"time_experiment": comparison.experiment_time[comparison.overlap_mask]})
        out["time_prediction"] = comparison.prediction_time[comparison.overlap_mask]
        for j, name in enumerate(columns):
            out[f"observed_{name}"] = comparison.observed[:, j]
            out[f"predicted_raw_{name}"] = comparison.predicted_raw[:, j]
            out[f"predicted_aligned_{name}"] = comparison.predicted_aligned[:, j]
            out[f"residual_{name}"] = comparison.predicted_aligned[:, j] - comparison.observed[:, j]
        out.to_csv(target / "experiment_aligned.csv", index=False)
    return report

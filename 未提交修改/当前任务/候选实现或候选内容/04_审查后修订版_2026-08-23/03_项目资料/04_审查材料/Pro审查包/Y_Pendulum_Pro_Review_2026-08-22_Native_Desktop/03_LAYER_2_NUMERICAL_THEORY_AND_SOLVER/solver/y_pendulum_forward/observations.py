"""Frozen orthographic and Brown--Conrady observation operators."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

from .contracts import (
    MAX_UNIFORM_SAMPLES,
    ValidationIssue,
    as_vector3,
    is_finite_number,
    reject_unknown_keys,
    safe_uniform_sample_count,
    strict_finite_array,
)


def _record_times(spec: Any, path: str, issues: list[ValidationIssue]) -> np.ndarray:
    if isinstance(spec, list):
        values = strict_finite_array(spec)
        conversion_ok = values is not None
        if values is None:
            values = np.empty(0)
        if not conversion_ok or values.ndim != 1:
            issues.append(
                ValidationIssue("OBS_TIME", path, spec, "finite one-dimensional time list")
            )
            return np.empty(0)
        if values.size > MAX_UNIFORM_SAMPLES:
            issues.append(
                ValidationIssue(
                    "OBS_TIME",
                    path,
                    int(values.size),
                    f"at most {MAX_UNIFORM_SAMPLES} observation times",
                )
            )
            return np.empty(0)
        return values
    if isinstance(spec, dict) and spec.get("kind") == "uniform":
        reject_unknown_keys(
            spec, {"kind", "start", "stop", "step"}, path, issues
        )
        start, stop, step = spec.get("start"), spec.get("stop"), spec.get("step")
        if not all(is_finite_number(v) for v in (start, stop, step)) or float(step) <= 0:
            issues.append(
                ValidationIssue(
                    "OBS_TIME",
                    path,
                    spec,
                    "uniform times with finite start/stop and step > 0",
                )
            )
            return np.empty(0)
        start, stop, step = float(start), float(stop), float(step)
        if stop < start:
            issues.append(ValidationIssue("OBS_TIME", path, spec, "stop >= start"))
            return np.empty(0)
        count = safe_uniform_sample_count(
            stop - start,
            step,
            maximum_samples=MAX_UNIFORM_SAMPLES,
        )
        if count is None:
            issues.append(
                ValidationIssue(
                    "OBS_TIME",
                    path,
                    spec,
                    f"uniform grid with at most {MAX_UNIFORM_SAMPLES} samples",
                )
            )
            return np.empty(0)
        values = start + step * np.arange(count)
        if values.size == 0 or values[-1] < stop - 1e-12 * max(1.0, abs(stop)):
            values = np.append(values, stop)
        else:
            values[-1] = min(values[-1], stop)
        return values
    issues.append(
        ValidationIssue(
            "OBS_TIME",
            path,
            spec,
            "finite list or {kind:'uniform', start, stop, step}",
        )
    )
    return np.empty(0)


def evaluate_observations(
    spec: Any,
    *,
    position_at: Callable[[np.ndarray], np.ndarray],
    interval_end: float,
    completed: bool,
    e_z: np.ndarray,
    event_time_tolerance: float,
) -> dict[str, Any]:
    """Evaluate an optional observation input without changing physics status."""

    if spec is None:
        return {}
    issues: list[ValidationIssue] = []
    if not isinstance(spec, dict):
        issues.append(ValidationIssue("OBS_TYPE", "observation", spec, "object"))
        return _invalid_observation(issues)
    obs_type = spec.get("type")
    obs_type_key = obs_type if isinstance(obs_type, str) else None
    observation_allowed = {
        "orthographic": {
            "type",
            "axis_1",
            "axis_2",
            "t0",
            "record_times",
        },
        "camera_brown_conrady": {
            "type",
            "R_c",
            "c_c",
            "f_x",
            "f_y",
            "c_x",
            "c_y",
            "k1",
            "k2",
            "k3",
            "p1",
            "p2",
            "Omega_cal",
            "t0",
            "record_times",
        },
    }.get(obs_type_key, {"type", "t0", "record_times"})
    reject_unknown_keys(spec, observation_allowed, "observation", issues)
    t0 = spec.get("t0")
    if not is_finite_number(t0):
        issues.append(ValidationIssue("OBS_TIME", "observation.t0", t0, "finite real"))
        t0 = 0.0
    record = _record_times(spec.get("record_times"), "observation.record_times", issues)
    model_times = record + float(t0)

    static: dict[str, Any] = {}
    if obs_type == "orthographic":
        axis_1 = as_vector3(spec.get("axis_1"), "observation.axis_1", issues)
        axis_2 = as_vector3(spec.get("axis_2"), "observation.axis_2", issues)
        tol = 1e-10
        if abs(np.linalg.norm(axis_1) - 1.0) > tol:
            issues.append(ValidationIssue("OBS_AXIS", "observation.axis_1", axis_1, "unit vector"))
        if abs(np.linalg.norm(axis_2) - 1.0) > tol:
            issues.append(ValidationIssue("OBS_AXIS", "observation.axis_2", axis_2, "unit vector"))
        if abs(float(axis_1 @ axis_2)) > tol:
            issues.append(ValidationIssue("OBS_AXIS", "observation.axes", [axis_1, axis_2], "orthogonal"))
        if abs(float(axis_1 @ e_z)) > tol or abs(float(axis_2 @ e_z)) > tol:
            issues.append(ValidationIssue("OBS_AXIS", "observation.axes", [axis_1, axis_2], "horizontal"))
        static = {"axis_1": axis_1, "axis_2": axis_2}
    elif obs_type == "camera_brown_conrady":
        rotation_raw = spec.get("R_c")
        rotation = strict_finite_array(rotation_raw)
        if rotation is None:
            rotation = np.zeros((3, 3))
        if rotation.shape != (3, 3) or not np.all(np.isfinite(rotation)):
            issues.append(ValidationIssue("OBS_CAMERA", "observation.R_c", rotation_raw, "finite 3x3 rotation"))
            rotation = np.eye(3)
        elif not (
            np.linalg.norm(rotation.T @ rotation - np.eye(3), ord=np.inf) <= 1e-9
            and abs(np.linalg.det(rotation) - 1.0) <= 1e-9
        ):
            issues.append(ValidationIssue("OBS_CAMERA", "observation.R_c", rotation, "member of SO(3)"))
        center = as_vector3(spec.get("c_c"), "observation.c_c", issues)
        scalars = {}
        for key in ("f_x", "f_y", "c_x", "c_y", "k1", "k2", "k3", "p1", "p2"):
            value = spec.get(key)
            if not is_finite_number(value):
                issues.append(ValidationIssue("OBS_CAMERA", f"observation.{key}", value, "finite real"))
                value = 0.0
            scalars[key] = float(value)
        if scalars["f_x"] <= 0 or scalars["f_y"] <= 0:
            issues.append(ValidationIssue("OBS_CAMERA", "observation.focal", [scalars["f_x"], scalars["f_y"]], "positive"))
        omega = spec.get("Omega_cal")
        omega_arr = strict_finite_array(omega)
        if omega_arr is None:
            omega_arr = np.zeros(4)
        if (
            omega_arr.shape != (4,)
            or not np.all(np.isfinite(omega_arr))
            or not (omega_arr[0] < omega_arr[1] and omega_arr[2] < omega_arr[3])
        ):
            issues.append(
                ValidationIssue(
                    "OBS_CAMERA",
                    "observation.Omega_cal",
                    omega,
                    "[x_min,x_max,y_min,y_max] with strict bounds",
                )
            )
            omega_arr = np.array([-1.0, 1.0, -1.0, 1.0])
        static = {"R_c": rotation, "c_c": center, "Omega_cal": omega_arr, **scalars}
    else:
        issues.append(
            ValidationIssue(
                "OBS_OPERATOR",
                "observation.type",
                obs_type,
                "orthographic or camera_brown_conrady",
            )
        )

    if issues:
        return _invalid_observation(issues)

    if completed:
        in_return = (model_times >= 0.0) & (model_times <= interval_end)
    else:
        in_return = (model_times >= 0.0) & (model_times < interval_end)
    candidate_indices = np.flatnonzero(in_return)
    candidate_times = model_times[candidate_indices]
    positions = (
        np.asarray(position_at(candidate_times), dtype=float)
        if candidate_times.size
        else np.empty((0, 3))
    )
    values = np.full((record.size, 2), np.nan)
    valid = np.zeros(record.size, dtype=bool)
    reasons: list[dict[str, Any]] = []
    for index in np.flatnonzero(~in_return):
        reasons.append({"index": int(index), "code": "OUTSIDE_RETURN_INTERVAL"})

    if obs_type == "orthographic":
        projected = np.column_stack((positions @ static["axis_1"], positions @ static["axis_2"]))
        values[candidate_indices] = projected
        valid[candidate_indices] = True
    else:
        with np.errstate(over="ignore", invalid="ignore", under="ignore"):
            camera = (static["R_c"] @ (positions - static["c_c"]).T).T
        for local, index in enumerate(candidate_indices):
            Xc, Yc, Zc = camera[local]
            if not np.all(np.isfinite(camera[local])):
                reasons.append(
                    {
                        "index": int(index),
                        "code": "OBSERVATION_NUMERICAL_NONFINITE",
                        "stage": "camera_coordinates",
                    }
                )
                continue
            if not Zc > 0.0:
                reasons.append({"index": int(index), "code": "CAMERA_BEHIND_OR_ON_PLANE", "Z_c": float(Zc)})
                continue
            with np.errstate(over="ignore", invalid="ignore", under="ignore"):
                xn, yn = Xc / Zc, Yc / Zc
            if not (np.isfinite(xn) and np.isfinite(yn)):
                reasons.append(
                    {
                        "index": int(index),
                        "code": "OBSERVATION_NUMERICAL_NONFINITE",
                        "stage": "normalized_coordinates",
                    }
                )
                continue
            xmin, xmax, ymin, ymax = static["Omega_cal"]
            if not (xmin < xn < xmax and ymin < yn < ymax):
                reasons.append({"index": int(index), "code": "OUTSIDE_CALIBRATION_DOMAIN", "x_n": float(xn), "y_n": float(yn)})
                continue
            with np.errstate(over="ignore", invalid="ignore", under="ignore"):
                radius2 = xn * xn + yn * yn
                radial = 1 + static["k1"] * radius2 + static["k2"] * radius2**2 + static["k3"] * radius2**3
                xd = xn * radial + 2 * static["p1"] * xn * yn + static["p2"] * (radius2 + 2 * xn * xn)
                yd = yn * radial + static["p1"] * (radius2 + 2 * yn * yn) + 2 * static["p2"] * xn * yn
                pixel = np.asarray(
                    [
                        static["f_x"] * xd + static["c_x"],
                        static["f_y"] * yd + static["c_y"],
                    ],
                    dtype=float,
                )
            if not (
                np.isfinite(radius2)
                and np.isfinite(radial)
                and np.isfinite(xd)
                and np.isfinite(yd)
                and np.all(np.isfinite(pixel))
            ):
                reasons.append(
                    {
                        "index": int(index),
                        "code": "OBSERVATION_NUMERICAL_NONFINITE",
                        "stage": "distortion_or_pixel",
                    }
                )
                continue
            values[index] = pixel
            valid[index] = True

    ambiguous = np.abs(model_times - interval_end) <= event_time_tolerance if not completed else np.zeros(record.size, dtype=bool)
    for index in np.flatnonzero(ambiguous):
        reasons.append({"index": int(index), "code": "OBSERVATION_EVENT_AMBIGUOUS"})

    return {
        "status": ["OBSERVATION_INPUT_VALID"],
        "operator": obs_type,
        "record_time": record,
        "model_time": model_times,
        "time": model_times,
        "values": values,
        "valid_mask": valid,
        "errors": reasons,
        "event_ambiguous_mask": ambiguous,
    }


def _invalid_observation(issues: list[ValidationIssue]) -> dict[str, Any]:
    return {
        "status": ["INVALID_OBSERVATION_INPUT"],
        "operator": None,
        "time": np.empty(0),
        "values": np.empty((0, 2)),
        "valid_mask": np.empty(0, dtype=bool),
        "errors": [issue.as_dict() for issue in issues],
    }

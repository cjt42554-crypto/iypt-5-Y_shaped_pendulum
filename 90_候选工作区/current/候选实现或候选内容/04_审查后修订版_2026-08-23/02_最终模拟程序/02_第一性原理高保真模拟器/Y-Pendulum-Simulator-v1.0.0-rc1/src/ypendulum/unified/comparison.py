"""Observable-level comparison without treating model disagreement as a failed run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np
from scipy.interpolate import CubicHermiteSpline

from ypendulum.hf import read_hf_certificate_sidecar


def _vector_metrics(difference: np.ndarray, prefix: str) -> dict[str, float]:
    delta = np.asarray(difference, dtype=float)
    point_norm = np.linalg.norm(delta, axis=1)
    return {
        f"rms_component_{prefix}": float(np.sqrt(np.mean(delta**2))),
        f"rms_point_{prefix}": float(np.sqrt(np.mean(point_norm**2))),
        f"maximum_point_{prefix}": float(np.max(point_norm)),
    }


def _read_forward(directory: Path) -> dict[str, Any]:
    result_path = directory / "result.json"
    trajectory_path = directory / "trajectory.npz"
    if not result_path.is_file() or not trajectory_path.is_file():
        raise FileNotFoundError("Forward result requires result.json and trajectory.npz.")
    summary = json.loads(result_path.read_text(encoding="utf-8"))
    with np.load(trajectory_path) as archive:
        required = {
            "time",
            "state__r_m",
            "state__v_m",
            "state__r_J",
            "state__v_J",
            "derived__E_F",
            "derived__R_A",
            "derived__R_B",
        }
        if not required.issubset(archive.files):
            raise ValueError("Forward trajectory lacks canonical comparison fields.")
        data = {name: np.asarray(archive[name], dtype=float) for name in required}
    if summary.get("model_id") != "FWD-CABLE-1.0":
        raise ValueError("Unified comparison received a non-Cable forward result.")
    if summary.get("numerical_status") != "SUCCESS_SINGLE_RUN" or summary.get(
        "contract_status"
    ) != ["COMPLETED"]:
        raise ValueError("Forward result is not a completed certified single run.")
    time = data["time"]
    vector_fields = (
        "state__r_m",
        "state__v_m",
        "state__r_J",
        "state__v_J",
        "derived__R_A",
        "derived__R_B",
    )
    canonical = (
        time.ndim == 1
        and time.size >= 2
        and np.all(np.isfinite(time))
        and np.all(np.diff(time) > 0.0)
        and data["derived__E_F"].shape == (time.size,)
        and all(data[name].shape == (time.size, 3) for name in vector_fields)
        and all(np.all(np.isfinite(values)) for values in data.values())
    )
    if not canonical:
        raise ValueError("Forward comparison trajectory is not a finite canonical time series.")
    return {"summary": summary, **data}


def _read_hf(directory: Path) -> dict[str, Any]:
    path = directory / "result.h5"
    if not path.is_file():
        raise FileNotFoundError("HF result requires result.h5.")
    certificate_sidecar = read_hf_certificate_sidecar(
        directory, require_full=True
    )
    with h5py.File(path, "r") as h5:
        if str(h5.attrs.get("model", "")) != "HF-DISCRETE-ROD-RIGID-BOB-1.0":
            raise ValueError("Unified comparison received an unexpected HF model.")
        if str(h5.attrs.get("physical_status", "")) != "UNDETERMINED" or str(
            h5.attrs.get("numerical_status", "")
        ) != "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED":
            raise ValueError("HF result is not a completed certified single run.")
        data = {
            "time": np.asarray(h5["/time"], dtype=float),
            "bob_position": np.asarray(h5["/bodies/bob/com_position"], dtype=float),
            "bob_velocity": np.asarray(h5["/bodies/bob/com_velocity"], dtype=float),
            "junction_position": np.asarray(h5["/bodies/junction/position"], dtype=float),
            "junction_velocity": np.asarray(h5["/bodies/junction/velocity"], dtype=float),
            "mechanical_energy": np.asarray(h5["/energy/mechanical"], dtype=float),
            "reaction_A": np.asarray(h5["/reactions/support_A"], dtype=float),
            "reaction_B": np.asarray(h5["/reactions/support_B"], dtype=float),
        }
    time = data["time"]
    vector_fields = (
        "bob_position",
        "bob_velocity",
        "junction_position",
        "junction_velocity",
        "reaction_A",
        "reaction_B",
    )
    canonical = (
        time.ndim == 1
        and time.size >= 2
        and np.all(np.isfinite(time))
        and np.all(np.diff(time) > 0.0)
        and data["mechanical_energy"].shape == (time.size,)
        and all(data[name].shape == (time.size, 3) for name in vector_fields)
        and all(np.all(np.isfinite(values)) for values in data.values())
    )
    if not canonical:
        raise ValueError("HF comparison trajectory is not a finite canonical time series.")
    return {
        **data,
        "certificate_sha256": certificate_sidecar["certificate"][
            "certificate_sha256"
        ],
    }


def _interpolate_position_velocity(
    source_time: np.ndarray,
    position: np.ndarray,
    velocity: np.ndarray,
    target_time: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    if not (
        source_time.ndim == 1
        and position.shape == velocity.shape == (source_time.size, 3)
        and np.all(np.diff(source_time) > 0.0)
    ):
        raise ValueError("Position/velocity interpolation input is not canonical.")
    spline = CubicHermiteSpline(source_time, position, velocity, axis=0)
    return np.asarray(spline(target_time)), np.asarray(spline.derivative()(target_time))


def compare_backend_directories(
    forward_directory: str | Path,
    high_fidelity_directory: str | Path,
    *,
    output_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Compare the common state/observer subset on the forward output grid.

    A completed comparison means the data contracts and common time window are
    valid.  It deliberately does not label small disagreement as "pass" or
    large disagreement as "failure"; those differences are the scientific
    object consumed later by the structural-research layer.
    """

    forward = _read_forward(Path(forward_directory))
    hf = _read_hf(Path(high_fidelity_directory))
    time = np.asarray(forward["time"], dtype=float)
    if time.ndim != 1 or time.size < 2 or not np.all(np.diff(time) > 0.0):
        raise ValueError("Forward comparison time grid is not strictly increasing.")
    if time[0] < hf["time"][0] or time[-1] > hf["time"][-1] + 1.0e-14:
        raise ValueError("HF trajectory does not cover the complete forward return window.")

    hf_bob, hf_bob_velocity = _interpolate_position_velocity(
        hf["time"], hf["bob_position"], hf["bob_velocity"], time
    )
    hf_junction, hf_junction_velocity = _interpolate_position_velocity(
        hf["time"], hf["junction_position"], hf["junction_velocity"], time
    )
    scalar_spline = CubicHermiteSpline(
        hf["time"],
        hf["mechanical_energy"],
        np.gradient(
            hf["mechanical_energy"],
            hf["time"],
            edge_order=2 if hf["time"].size >= 3 else 1,
        ),
    )
    hf_energy = np.asarray(scalar_spline(time), dtype=float)
    reaction_a = np.column_stack(
        [np.interp(time, hf["time"], hf["reaction_A"][:, axis]) for axis in range(3)]
    )
    reaction_b = np.column_stack(
        [np.interp(time, hf["time"], hf["reaction_B"][:, axis]) for axis in range(3)]
    )

    bob_difference = hf_bob - forward["state__r_m"]
    bob_velocity_difference = hf_bob_velocity - forward["state__v_m"]
    junction_difference = hf_junction - forward["state__r_J"]
    junction_velocity_difference = hf_junction_velocity - forward["state__v_J"]
    metrics = {
        **_vector_metrics(bob_difference, "bob_position_m"),
        **_vector_metrics(bob_velocity_difference, "bob_velocity_m_s"),
        **_vector_metrics(junction_difference, "junction_position_m"),
        **_vector_metrics(junction_velocity_difference, "junction_velocity_m_s"),
        **_vector_metrics(bob_difference[:, :2], "orthographic_xy_m"),
        **_vector_metrics(reaction_a - forward["derived__R_A"], "support_A_reaction_N"),
        **_vector_metrics(reaction_b - forward["derived__R_B"], "support_B_reaction_N"),
        "initial_mechanical_energy_offset_J": float(
            hf_energy[0] - forward["derived__E_F"][0]
        ),
        "rms_energy_change_difference_J": float(
            np.sqrt(
                np.mean(
                    (
                        (hf_energy - hf_energy[0])
                        - (forward["derived__E_F"] - forward["derived__E_F"][0])
                    )
                    ** 2
                )
            )
        ),
    }
    report = {
        "schema_version": "YPS-UNIFIED-COMPARISON-1.0",
        "status": "COMPARISON_COMPLETE",
        "units": "SI",
        "comparison_grid": "FWD-CABLE canonical output time; HF cubic-Hermite state interpolation",
        "sample_count": int(time.size),
        "window_s": [float(time[0]), float(time[-1])],
        "high_fidelity_certificate_sha256": hf["certificate_sha256"],
        "metrics": metrics,
        "interpretation": (
            "Metrics quantify model-form differences under a separately audited shared input. "
            "They are not numerical convergence errors and are not pass/fail thresholds."
        ),
    }
    if output_directory is not None:
        output = Path(output_directory)
        if output.exists():
            raise FileExistsError(f"Comparison output already exists: {output}")
        output.mkdir(parents=True)
        (output / "comparison.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        np.savez_compressed(
            output / "comparison_series.npz",
            time_s=time,
            forward_bob_position_m=forward["state__r_m"],
            high_fidelity_bob_position_m=hf_bob,
            bob_position_difference_m=bob_difference,
            forward_bob_velocity_m_s=forward["state__v_m"],
            high_fidelity_bob_velocity_m_s=hf_bob_velocity,
            bob_velocity_difference_m_s=bob_velocity_difference,
            forward_junction_position_m=forward["state__r_J"],
            high_fidelity_junction_position_m=hf_junction,
            junction_position_difference_m=junction_difference,
        )
    return report

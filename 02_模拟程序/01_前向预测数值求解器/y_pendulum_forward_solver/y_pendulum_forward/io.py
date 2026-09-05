"""Reproducible, non-destructive result serialization and compact plots."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
from typing import Any

import numpy as np

from .contracts import SimulationResult, config_sha256


KNOWN_OUTPUT_FILES = {
    "config.snapshot.json",
    "result.json",
    "trajectory.npz",
    "series.csv",
    "trajectory.png",
    "energy.png",
}


def write_result(
    output_directory: str | Path,
    config: dict[str, Any],
    result: SimulationResult,
    *,
    overwrite: bool = False,
    plots: bool = True,
) -> Path:
    output = Path(output_directory)
    if output.exists() and not output.is_dir():
        raise FileExistsError(f"output path is not a directory: {output}")
    existing = list(output.iterdir()) if output.exists() else []
    if existing and not overwrite:
        raise FileExistsError(
            f"refusing to overwrite nonempty output directory: {output}"
        )
    if output.exists() and overwrite:
        unknown = [
            path.name
            for path in existing
            if path.name not in KNOWN_OUTPUT_FILES or not path.is_file()
        ]
        if unknown:
            raise FileExistsError(
                "output directory contains unknown files; choose a new directory: "
                + ", ".join(sorted(unknown))
            )

    # Every identity and serialization check precedes mkdir, deletion, or
    # replacement.  A mismatched config can never damage an existing run.
    if "source_tree_sha256" not in result.metadata:
        raise ValueError(
            "SimulationResult lacks the run-start source_tree_sha256 identity"
        )
    if config_sha256(config) != result.metadata.get("config_sha256"):
        raise ValueError(
            "configuration no longer matches the immutable snapshot executed by the run"
        )
    snapshot_bytes = json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ).encode("utf-8")
    summary_text = json.dumps(
        result.summary_dict(),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    arrays: dict[str, np.ndarray] = {"time": np.asarray(result.time)}
    _flatten_arrays("state", result.state, arrays)
    _flatten_arrays("derived", result.derived, arrays)
    _flatten_arrays("diagnostics", result.diagnostics, arrays)
    _flatten_arrays("observations", result.observations, arrays)

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=output.parent,
        prefix=f".{output.name}.tmp-",
        ignore_cleanup_errors=True,
    ) as temporary:
        temporary_root = Path(temporary)
        staging = temporary_root / "payload"
        staging.mkdir()
        (staging / "config.snapshot.json").write_bytes(snapshot_bytes)
        (staging / "result.json").write_text(
            summary_text,
            encoding="utf-8",
        )
        np.savez_compressed(staging / "trajectory.npz", **arrays)
        _write_series_csv(staging / "series.csv", result)
        if plots and result.time.size:
            _write_plots(staging, result)

        if output.exists():
            backup = temporary_root / "previous"
            output.replace(backup)
            try:
                staging.replace(output)
            except Exception:
                backup.replace(output)
                raise
        else:
            staging.replace(output)
    return output


def _flatten_arrays(prefix: str, value: Any, output: dict[str, np.ndarray]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _flatten_arrays(f"{prefix}__{key}", child, output)
        return
    if isinstance(value, np.ndarray) and value.dtype != object:
        output[prefix] = value
        return
    if isinstance(value, (list, tuple)):
        try:
            array = np.asarray(value)
        except (TypeError, ValueError):
            return
        if array.dtype != object:
            output[prefix] = array


def _write_series_csv(path: Path, result: SimulationResult) -> None:
    headers = ["t"]
    columns = [np.asarray(result.time)]
    state = result.state
    for key in ("r_J", "r_m"):
        if key in state:
            values = np.asarray(state[key])
            for coordinate, suffix in enumerate("xyz"):
                headers.append(f"{key}_{suffix}")
                columns.append(values[:, coordinate])
    for key in (
        "E_F",
        "E_torus",
        "E_junction",
        "D_ax",
        "D_string",
        "D_b",
        "P_base",
        "P_air",
        "P_ext",
        "P_hold",
        "T_A",
        "T_B",
        "T_lower",
    ):
        if key in result.derived:
            values = np.asarray(result.derived[key])
            if values.ndim == 1 and values.size == result.time.size:
                headers.append(key)
                columns.append(values)
    if "power_integral_hold" in result.diagnostics:
        headers.append("W_hold")
        columns.append(np.asarray(result.diagnostics["power_integral_hold"]))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in zip(*columns):
            writer.writerow([f"{float(value):.17g}" for value in row])


def _write_plots(output: Path, result: SimulationResult) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bob = result.state.get("r_m")
    if bob is None and "r_m" in result.derived:
        bob = result.derived["r_m"]
    if bob is not None:
        bob = np.asarray(bob)
        fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
        axes[0].plot(bob[:, 0], bob[:, 1], linewidth=1.0)
        axes[0].set_aspect("equal", adjustable="datalim")
        axes[0].set_xlabel("x / m")
        axes[0].set_ylabel("y / m")
        axes[0].set_title("Bob horizontal trajectory")
        axes[1].plot(result.time, bob[:, 0], label="x")
        axes[1].plot(result.time, bob[:, 1], label="y")
        axes[1].plot(result.time, bob[:, 2], label="z")
        axes[1].set_xlabel("t / s")
        axes[1].set_ylabel("position / m")
        axes[1].legend()
        fig.tight_layout()
        fig.savefig(output / "trajectory.png", dpi=160)
        plt.close(fig)
    energy = result.derived.get(
        "E_F", result.derived.get("E_torus", result.derived.get("E_junction"))
    )
    if energy is not None:
        energy = np.asarray(energy)
        fig, ax = plt.subplots(figsize=(7, 4.2))
        ax.plot(result.time, energy, label="mechanical energy")
        ax.set_xlabel("t / s")
        ax.set_ylabel("E / J")
        ax.legend()
        fig.tight_layout()
        fig.savefig(output / "energy.png", dpi=160)
        plt.close(fig)

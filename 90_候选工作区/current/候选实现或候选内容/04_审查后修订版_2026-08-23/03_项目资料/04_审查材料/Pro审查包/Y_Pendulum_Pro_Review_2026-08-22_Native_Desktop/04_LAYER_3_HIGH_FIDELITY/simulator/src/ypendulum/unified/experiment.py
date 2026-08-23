"""Explicit-unit experiment comparison for a completed unified run."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_unified_run(run: Path) -> dict[str, Any]:
    root_path = run / "delivery_root.json"
    manifest_path = run / "artifact_manifest.json"
    if not root_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("Experiment comparison requires a sealed unified run.")
    root = json.loads(root_path.read_text(encoding="utf-8"))
    if (
        root.get("schema_version") != "YPS-UNIFIED-DELIVERY-ROOT-1.0"
        or root.get("status") != "COMPLETE"
    ):
        raise ValueError("Experiment comparison requires a scientifically completed run.")
    manifest_sha = _sha256_file(manifest_path)
    if root.get("artifact_manifest_sha256") != manifest_sha:
        raise ValueError("Unified artifact-manifest identity does not match delivery root.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "YPS-UNIFIED-ARTIFACT-MANIFEST-1.0":
        raise ValueError("Unsupported unified artifact-manifest schema.")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError("Unified artifact manifest lacks its file entries.")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Unified artifact entry must be an object.")
        relative = entry.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or relative in seen
            or Path(relative).is_absolute()
        ):
            raise ValueError("Unified artifact manifest has a duplicate/invalid path.")
        seen.add(relative)
        path = (run / relative).resolve()
        if not path.is_relative_to(run.resolve()) or not path.is_file():
            raise ValueError(f"Unified artifact path is absent or escapes the run: {relative}")
        if path.stat().st_size != entry.get("bytes") or _sha256_file(path) != entry.get(
            "sha256"
        ):
            raise ValueError(f"Unified artifact identity mismatch: {relative}")
    required = "comparison/comparison_series.npz"
    if required not in seen:
        raise ValueError("Unified manifest does not bind the comparison series.")
    return {
        "delivery_root_sha256": _sha256_file(root_path),
        "artifact_manifest_sha256": manifest_sha,
        "comparison_series_sha256": _sha256_file(run / required),
        "manifest_file_count": len(entries),
    }


def _metrics(predicted: np.ndarray, observed: np.ndarray) -> dict[str, Any]:
    error = np.asarray(predicted) - np.asarray(observed)
    point = np.linalg.norm(error, axis=1)
    return {
        "rms_component_error_m": float(np.sqrt(np.mean(error**2))),
        "rms_point_error_m": float(np.sqrt(np.mean(point**2))),
        "maximum_point_error_m": float(np.max(point)),
        "mean_component_bias_m": np.mean(error, axis=0).tolist(),
    }


def compare_experiment_to_unified_run(
    run_directory: str | Path,
    experiment_csv: str | Path,
    *,
    output_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Compare metre-valued orthographic data without fitted nuisance parameters."""

    run = Path(run_directory)
    identities_start = _verified_unified_run(run)
    series_path = run / "comparison" / "comparison_series.npz"
    if not series_path.is_file():
        raise FileNotFoundError("Unified run lacks comparison/comparison_series.npz.")
    experiment_path = Path(experiment_csv).expanduser().resolve()
    experiment_bytes = experiment_path.read_bytes()
    frame = pd.read_csv(io.BytesIO(experiment_bytes))
    required = ["time_s", "x_m", "y_m"]
    if list(frame.columns) != required:
        raise ValueError(
            "Experiment CSV must contain exactly time_s,x_m,y_m. Pixel-valued data "
            "requires an explicitly calibrated camera case and is not silently reinterpreted."
        )
    values = frame.to_numpy(dtype=float)
    if values.shape[0] < 3 or not np.all(np.isfinite(values)):
        raise ValueError("Experiment record must contain at least three finite samples.")
    experiment_time = values[:, 0]
    observed = values[:, 1:]
    if not np.all(np.diff(experiment_time) > 0.0):
        raise ValueError("Experiment time_s must be strictly increasing.")
    series_bytes = series_path.read_bytes()
    if _sha256_bytes(series_bytes) != identities_start["comparison_series_sha256"]:
        raise RuntimeError("Unified comparison series drifted before it could be read.")
    with np.load(io.BytesIO(series_bytes)) as archive:
        time = np.asarray(archive["time_s"], dtype=float)
        forward = np.asarray(archive["forward_bob_position_m"], dtype=float)[:, :2]
        hf = np.asarray(archive["high_fidelity_bob_position_m"], dtype=float)[:, :2]
    if experiment_time[0] < time[0] or experiment_time[-1] > time[-1]:
        raise ValueError("Experiment time range lies outside the common returned interval.")
    predicted_forward = CubicSpline(time, forward, axis=0)(experiment_time)
    predicted_hf = CubicSpline(time, hf, axis=0)(experiment_time)
    report = {
        "schema_version": "YPS-UNIFIED-EXPERIMENT-COMPARISON-1.0",
        "status": "COMPARISON_COMPLETE",
        "observation_contract": "ORTHOGRAPHIC_XY_METRE-1.0",
        "sample_count": int(experiment_time.size),
        "nuisance_parameters_fitted": [],
        "source_identity": identities_start,
        "experiment_csv_sha256": _sha256_bytes(experiment_bytes),
        "forward": _metrics(predicted_forward, observed),
        "high_fidelity": _metrics(predicted_hf, observed),
        "interpretation": (
            "This is a direct no-fit comparison. It does not promote either model to "
            "VALIDATED without a separately frozen experimental campaign."
        ),
    }
    if output_directory is not None:
        output = Path(output_directory).expanduser().resolve()
        if output.is_relative_to(run.resolve()):
            raise ValueError(
                "Experiment comparison must be a sibling artifact, not a mutation "
                "inside the sealed unified run."
            )
        if output.exists():
            raise FileExistsError(f"Experiment comparison output exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent)
        )
        try:
            (staging / "experiment_comparison.json").write_text(
                json.dumps(
                    report,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n",
                encoding="utf-8",
            )
            aligned = pd.DataFrame(
                {
                    "time_s": experiment_time,
                    "observed_x_m": observed[:, 0],
                    "observed_y_m": observed[:, 1],
                    "forward_x_m": predicted_forward[:, 0],
                    "forward_y_m": predicted_forward[:, 1],
                    "high_fidelity_x_m": predicted_hf[:, 0],
                    "high_fidelity_y_m": predicted_hf[:, 1],
                }
            )
            aligned.to_csv(staging / "experiment_aligned.csv", index=False)
            files = [
                {
                    "path": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
                for path in sorted(staging.iterdir())
                if path.is_file()
            ]
            manifest_path = staging / "artifact_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "YPS-UNIFIED-EXPERIMENT-MANIFEST-1.0",
                        "files": files,
                    },
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n",
                encoding="utf-8",
            )
            identities_end = _verified_unified_run(run)
            if identities_end != identities_start:
                raise RuntimeError("Sealed unified-run identity drifted during comparison.")
            (staging / "delivery_root.json").write_text(
                json.dumps(
                    {
                        "schema_version": "YPS-UNIFIED-EXPERIMENT-ROOT-1.0",
                        "status": "COMPARISON_COMPLETE",
                        "source_unified_run": str(run.resolve()),
                        "source_identity": identities_start,
                        "experiment_csv_sha256": _sha256_bytes(experiment_bytes),
                        "artifact_manifest_sha256": _sha256_file(manifest_path),
                    },
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(staging, output)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return report

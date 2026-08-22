"""Desktop child worker using the explicit-EI scientific revision backend."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from ypendulum.ui.desktop_config import (
    DESKTOP_RESULT_SCHEMA,
    FORWARD_ROOT,
    canonical_json_sha256,
    load_desktop_request,
)
from ypendulum.ui.desktop_results import write_comparison_artifacts
from ypendulum.ui.desktop_worker import (
    _forward_outcome,
    _hf_outcome,
    _overall_status,
    _progress,
    _run_and_relay,
    _utc_now,
    _write_json,
)

from .desktop_contract import scientific_revision_metadata, user_scan_coordinates
from .overlay import load_overlay


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_overlay(request: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    metadata = scientific_revision_metadata(request)
    path = Path(metadata["overlay_path"]).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"科学修订 overlay 不存在：{path}")
    actual = _sha256_file(path)
    if actual != metadata["overlay_sha256"]:
        raise ValueError(
            "科学修订 overlay 在请求封存后发生变化："
            f"expected={metadata['overlay_sha256']}, actual={actual}"
        )
    overlay = load_overlay(path)
    return path, {
        "path": str(path),
        "sha256": actual,
        "model_id": overlay.model_id,
        "effective_claim": overlay.effective_claim.value,
        "branch_EI_N_m2": {
            name: value.value_N_m2 for name, value in overlay.branch_bending.items()
        },
        "compression_scale": overlay.compression_scale,
    }


def run_request(request_path: Path, backend: str, output: Path) -> int:
    request = load_desktop_request(request_path)
    if request["backend"] != backend:
        raise ValueError(
            f"Request backend {request['backend']!r} does not match {backend!r}."
        )
    output.mkdir(parents=True, exist_ok=False)
    request_sha = canonical_json_sha256(request)
    started = _utc_now()
    outcomes: dict[str, dict[str, Any]] = {}
    comparison: dict[str, Any] | None = None
    revision: dict[str, Any] | None = None
    environment = dict(os.environ)
    forward_pythonpath = str(FORWARD_ROOT)
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        forward_pythonpath
        if not existing_pythonpath
        else forward_pythonpath + os.pathsep + existing_pythonpath
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    try:
        if backend in {"high_fidelity", "both"}:
            overlay_path, revision = _verified_overlay(request)
        else:
            overlay_path = None

        _progress(output, "PREPARING", 0.02, "Validating and materialising configurations")
        if backend in {"forward", "both"}:
            forward_config = deepcopy(request["forward_config"])
            forward_config_path = output / "forward_config.json"
            _write_json(forward_config_path, forward_config)
            _progress(output, "FORWARD", 0.08, "Running the FWD tension-cable backend")
            forward_directory = output / "forward"
            code = _run_and_relay(
                [
                    sys.executable,
                    "-c",
                    (
                        "import numpy as np; "
                        "np.trapz = getattr(np, 'trapz', np.trapezoid); "
                        "from y_pendulum_forward.cli import main; "
                        "raise SystemExit(main())"
                    ),
                    "run",
                    str(forward_config_path),
                    "--output",
                    str(forward_directory),
                    "--no-plots",
                ],
                environment=environment,
            )
            outcomes["forward"] = _forward_outcome(forward_directory, code)
            if outcomes["forward"]["status"] == "FAILED":
                raise RuntimeError(
                    "FWD backend failed: "
                    f"{outcomes['forward'].get('numerical_status', code)}"
                )

        if backend in {"high_fidelity", "both"}:
            assert overlay_path is not None
            hf_config = deepcopy(request["high_fidelity_config"])
            hf_directory = output / "high_fidelity"
            hf_config["run"]["output_directory"] = str(hf_directory)
            hf_config_path = output / "high_fidelity_config.yaml"
            hf_config_path.write_text(
                yaml.safe_dump(
                    hf_config,
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False,
                ),
                encoding="utf-8",
            )
            _progress(
                output,
                "HIGH_FIDELITY",
                0.52 if backend == "both" else 0.08,
                "Running the explicit-EI flexible-rod backend",
            )
            code = _run_and_relay(
                [
                    sys.executable,
                    "-m",
                    "ypendulum.scientific_revision",
                    "run-hf",
                    "--config",
                    str(hf_config_path),
                    "--overlay",
                    str(overlay_path),
                    "--output",
                    str(hf_directory),
                ],
                environment=environment,
            )
            outcomes["high_fidelity"] = _hf_outcome(hf_directory, code)
            if outcomes["high_fidelity"]["status"] == "FAILED":
                raise RuntimeError(
                    "Revised HF backend failed: "
                    f"{outcomes['high_fidelity'].get('numerical_status', code)}"
                )

        if backend == "both" and all(
            item["status"] == "COMPLETE" for item in outcomes.values()
        ):
            _progress(output, "COMPARING", 0.94, "Computing model-form differences")
            comparison = write_comparison_artifacts(
                output / "forward",
                output / "high_fidelity",
                output / "comparison",
            )

        status = _overall_status(outcomes)
        result = {
            "schema_version": DESKTOP_RESULT_SCHEMA,
            "status": status,
            "message": (
                "Scientific artifacts are readable. FWD-CABLE and revised HF-ROD "
                "are different physical models; their difference is not a convergence test."
            ),
            "request_sha256": request_sha,
            "backend": backend,
            "label": request["label"],
            "scan_coordinates": user_scan_coordinates(request),
            "scientific_revision": revision,
            "started_at_utc": started,
            "ended_at_utc": _utc_now(),
            "backend_outcomes": outcomes,
            "comparison": comparison,
        }
        _write_json(output / "desktop_result.json", result)
        _progress(output, "FINISHED", 1.0, status)
        return 0
    except Exception as exc:
        result = {
            "schema_version": DESKTOP_RESULT_SCHEMA,
            "status": "FAILED",
            "message": f"{type(exc).__name__}: {exc}",
            "request_sha256": request_sha,
            "backend": backend,
            "label": request["label"],
            "scan_coordinates": user_scan_coordinates(request),
            "scientific_revision": revision,
            "started_at_utc": started,
            "ended_at_utc": _utc_now(),
            "backend_outcomes": outcomes,
            "comparison": comparison,
        }
        _write_json(output / "desktop_result.json", result)
        _progress(output, "FAILED", 1.0, result["message"])
        print(result["message"], file=sys.stderr, flush=True)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scientific-revision Y-pendulum desktop worker"
    )
    parser.add_argument("request", type=Path)
    parser.add_argument(
        "--backend",
        required=True,
        choices=("forward", "high_fidelity", "both"),
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return run_request(
        arguments.request.expanduser().resolve(),
        arguments.backend,
        arguments.output.expanduser().resolve(),
    )


if __name__ == "__main__":
    raise SystemExit(main())

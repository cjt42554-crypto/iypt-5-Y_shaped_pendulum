"""Child-process runner for the native desktop research application.

The worker deliberately contains no equations of motion.  It materialises the
two complete configuration snapshots prepared by the GUI, invokes the
existing FWD/HF command-line entry points, and writes one small result envelope
that the persistent desktop job manager can inspect.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import h5py
import yaml

from ypendulum.ui.desktop_config import (
    DESKTOP_RESULT_SCHEMA,
    FORWARD_ROOT,
    canonical_json_sha256,
    load_desktop_request,
)
from ypendulum.ui.desktop_results import write_comparison_artifacts

PROGRESS_SCHEMA = "YPS-DESKTOP-PROGRESS-1.0"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _progress(output: Path, phase: str, fraction: float, detail: str) -> None:
    _write_json(
        output / ".desktop_progress.json",
        {
            "schema_version": PROGRESS_SCHEMA,
            "phase": phase,
            "fraction": max(0.0, min(1.0, float(fraction))),
            "detail": detail,
            "updated_at_utc": _utc_now(),
        },
    )


def _run_and_relay(command: list[str], *, environment: dict[str, str]) -> int:
    """Run one backend in this worker's process group and relay its log."""

    print("$ " + " ".join(command), flush=True)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=environment,
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
    return int(process.wait())


def _forward_outcome(directory: Path, return_code: int) -> dict[str, Any]:
    path = directory / "result.json"
    if not path.is_file():
        return {
            "backend": "forward",
            "status": "FAILED",
            "return_code": return_code,
            "message": "FWD did not produce result.json.",
        }
    result = json.loads(path.read_text(encoding="utf-8"))
    contract = result.get("contract_status", [])
    numerical = str(result.get("numerical_status", "UNKNOWN"))
    if contract == ["COMPLETED"] and numerical == "SUCCESS_SINGLE_RUN":
        status = "COMPLETE"
    elif contract == ["OUT_OF_SCOPE"] and numerical == "SUCCESS_EVENT":
        status = "OUT_OF_SCOPE_PREFIX"
    else:
        status = "FAILED"
    return {
        "backend": "forward",
        "status": status,
        "return_code": return_code,
        "contract_status": contract,
        "numerical_status": numerical,
        "result_directory": str(directory),
    }


def _hf_outcome(directory: Path, return_code: int) -> dict[str, Any]:
    path = directory / "summary.json"
    result_path = directory / "result.h5"
    if not path.is_file() or not result_path.is_file():
        return {
            "backend": "high_fidelity",
            "status": "FAILED",
            "return_code": return_code,
            "message": "HF did not produce summary.json and result.h5.",
        }
    summary = json.loads(path.read_text(encoding="utf-8"))
    with h5py.File(result_path, "r") as h5:
        physical = str(h5.attrs.get("physical_status", "UNKNOWN"))
        numerical = str(h5.attrs.get("numerical_status", "UNKNOWN"))
    if physical == "OUT_OF_SCOPE" and numerical == "SUCCESS_EVENT":
        status = "OUT_OF_SCOPE_PREFIX"
    elif (
        physical == "UNDETERMINED"
        and numerical == "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"
        and return_code == 0
    ):
        # This is a usable raw personal-research trajectory, not a claim that
        # the optional independent whole-run certificate has been completed.
        status = "COMPLETE"
    elif physical == "COMPLETED" and numerical == "SUCCESS_SINGLE_RUN":
        status = "COMPLETE"
    else:
        status = "FAILED"
    return {
        "backend": "high_fidelity",
        "status": status,
        "return_code": return_code,
        "physical_status": physical,
        "numerical_status": numerical,
        "raw_guard_certificate": (
            "NOT_RUN"
            if numerical == "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"
            else "NOT_APPLICABLE"
        ),
        "result_directory": str(directory),
        "summary_status": summary.get("status"),
    }


def _overall_status(outcomes: dict[str, dict[str, Any]]) -> str:
    states = {item["status"] for item in outcomes.values()}
    if "FAILED" in states:
        return "FAILED"
    if "OUT_OF_SCOPE_PREFIX" in states:
        return "OUT_OF_SCOPE_PREFIX"
    return "COMPLETE"


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
        _progress(output, "PREPARING", 0.02, "Validating and materialising configurations")
        if backend in {"forward", "both"}:
            forward_config = deepcopy(request["forward_config"])
            forward_config_path = output / "forward_config.json"
            _write_json(forward_config_path, forward_config)
            _progress(output, "FORWARD", 0.08, "Running the forward-prediction backend")
            forward_directory = output / "forward"
            code = _run_and_relay(
                [
                    sys.executable,
                    "-m",
                    "y_pendulum_forward.cli",
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
                "Running the high-fidelity backend",
            )
            code = _run_and_relay(
                [
                    sys.executable,
                    "-m",
                    "ypendulum.cli",
                    "simulate",
                    str(hf_config_path),
                ],
                environment=environment,
            )
            outcomes["high_fidelity"] = _hf_outcome(hf_directory, code)
            if outcomes["high_fidelity"]["status"] == "FAILED":
                raise RuntimeError(
                    "HF backend failed: "
                    f"{outcomes['high_fidelity'].get('numerical_status', code)}"
                )

        if backend == "both" and all(
            item["status"] == "COMPLETE" for item in outcomes.values()
        ):
            _progress(output, "COMPARING", 0.94, "Computing shared-time model differences")
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
                "Scientific artifacts are readable. Inspect each backend's exact "
                "physical/numerical status before interpretation."
            ),
            "request_sha256": request_sha,
            "backend": backend,
            "label": request["label"],
            "scan_coordinates": request["scan_coordinates"],
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
            "scan_coordinates": request["scan_coordinates"],
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
    parser = argparse.ArgumentParser(description="Native Y-pendulum desktop worker")
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

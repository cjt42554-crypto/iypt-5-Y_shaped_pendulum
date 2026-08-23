#!/usr/bin/env python3
"""Materialize immutable, portable low-cost corrective smoke plans."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _head(project: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=project, text=True
    ).strip()


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _copy(source: Path, destination: Path) -> None:
    shutil.copyfile(source, destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    commit = _head(project)

    base_source = project / "configs/revision/smoke/hf-common-state-smoke.yaml"
    state_source = project / "configs/revision/smoke/event-initial-state.yaml"
    overlay_source = project / "configs/revision/hf-bilateral-explicit-ei-baseline.yaml"
    forward_source = (
        project
        / "../../01_前向预测数值求解器/"
        "y_pendulum_forward_solver/configs/cable_example.json"
    ).resolve()

    event = output / "event"
    event.mkdir()
    _copy(base_source, event / "base-config.yaml")
    _copy(state_source, event / "initial-state.yaml")
    _copy(overlay_source, event / "overlay.yaml")
    event_plan = {
        "schema_version": "YPS-EVENT-QUALIFICATION-EXECUTION-2.0",
        "plan_id": "corrective-low-cost-event-smoke-2026-08-23",
        "git_commit": commit,
        "base_config": "base-config.yaml",
        "base_config_sha256": _sha256(event / "base-config.yaml"),
        "overlay": "overlay.yaml",
        "overlay_sha256": _sha256(event / "overlay.yaml"),
        "initial_state": "initial-state.yaml",
        "initial_state_sha256": _sha256(event / "initial-state.yaml"),
        "thresholds": {
            "trajectory_normalized_rms": 1.0e-3,
            "event_time_absolute_s": 1.0e-4,
            "event_time_relative": 5.0e-3,
            "peak_tension_relative": 2.0e-2,
            "tension_impulse_relative": 2.0e-2,
            "energy_residual_absolute": 1.0e-7,
        },
        "matrix_axes": {
            "space": {"factors": [1, 2, 4]},
            "time": {"max_step_s": [2.5e-4, 1.25e-4]},
            "output": {"output_dt_s": [2.5e-4, 1.25e-4]},
            "solver": {"methods": ["Radau", "BDF"]},
        },
        "planned_events": [
            {
                "branch": "lower",
                "material_coordinate_or_segment": "coordinate:0.5",
                "event_type": "PLANNED_LOCAL_TENSION_PROBE",
                "direction": "sample",
                "ordinal": 1,
                "time_s": 7.5e-4,
                "window_before_s": 2.5e-4,
                "window_after_s": 2.5e-4,
            }
        ],
    }
    _write_yaml(event / "event-plan.yaml", event_plan)

    ablation = output / "ablation"
    ablation.mkdir()
    _copy(base_source, ablation / "base-hf-config.yaml")
    _copy(overlay_source, ablation / "measured-overlay.yaml")
    _copy(forward_source, ablation / "forward-config.json")
    ablation_plan = {
        "schema_version": "YPS-ABLATION-EXECUTION-2.0",
        "plan_id": "corrective-low-cost-ablation-smoke-2026-08-23",
        "git_commit": commit,
        "base_hf_config": "base-hf-config.yaml",
        "base_hf_config_sha256": _sha256(ablation / "base-hf-config.yaml"),
        "forward_config": "forward-config.json",
        "forward_config_sha256": _sha256(ablation / "forward-config.json"),
        "measured_overlay": "measured-overlay.yaml",
        "measured_overlay_sha256": _sha256(ablation / "measured-overlay.yaml"),
        "duration_s": 1.5e-3,
    }
    _write_yaml(ablation / "ablation-plan.yaml", ablation_plan)

    identity = {
        "git_commit": commit,
        "event_plan": {
            "path": "event/event-plan.yaml",
            "sha256": _sha256(event / "event-plan.yaml"),
        },
        "ablation_plan": {
            "path": "ablation/ablation-plan.yaml",
            "sha256": _sha256(ablation / "ablation-plan.yaml"),
        },
    }
    (output / "smoke-plan-identity.json").write_text(
        json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

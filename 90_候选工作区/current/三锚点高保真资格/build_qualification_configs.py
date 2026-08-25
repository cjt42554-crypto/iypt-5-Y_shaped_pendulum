#!/usr/bin/env python3
"""Freeze three-anchor high-fidelity qualification inputs.

The emitted configurations use the formal HF validation target rather than
the subminimum preview meshes used by the preceding model-ladder study.  The
formal validation routine expands each finest configuration into the frozen
6/6/8, 12/12/16 and 24/24/32 spatial sequence.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

SCRIPT_PATH = Path(__file__).resolve()
CANDIDATE_ROOT = SCRIPT_PATH.parent
REPOSITORY_ROOT = SCRIPT_PATH.parents[3]
LADDER_ROOT = (
    REPOSITORY_ROOT
    / "90_候选工作区"
    / "current"
    / "三锚点模型阶梯"
)
LADDER_PATH = LADDER_ROOT / "model_ladder.py"
HF_ROOT = (
    REPOSITORY_ROOT
    / "02_模拟程序"
    / "02_第一性原理高保真模拟器"
    / "Y-Pendulum-Simulator-v1.0.0-rc1"
)
HF_SOURCE_ROOT = HF_ROOT / "src"
VALIDATION_SPEC_PATH = HF_ROOT / "configs" / "high_fidelity_shared_forward_validation.yaml"

TARGET_WINDOW_S = 0.12
FINEST_OUTPUT_DT_S = 7.8125e-6
FINEST_MESH = {"upper_A": 24, "upper_B": 24, "lower": 32}

if str(HF_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(HF_SOURCE_ROOT))

from ypendulum.config import (
    load_config,
    resolved_config_sha256,
    validate_physical_config,
)
from ypendulum.config.validation import _high_fidelity_resource_estimate
from ypendulum.config.units import to_si
from ypendulum.hf.validation import (
    _freeze_and_validate_spec,
    _space_configs,
    _validation_target_applicability,
)
from ypendulum.io.provenance import source_hash


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        yaml.safe_dump(
            value,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def git_head() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def load_ladder() -> ModuleType:
    module_name = "three_anchor_model_ladder_frozen_input"
    spec = importlib.util.spec_from_file_location(module_name, LADDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import model ladder from {LADDER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def production_config(anchor: Any, ladder: ModuleType) -> tuple[dict[str, Any], dict[str, Any]]:
    setup = ladder.anchor_setup(anchor)
    _torus, _cable, high_fidelity, audit = ladder.build_configs(
        anchor,
        setup,
        horizon_s=TARGET_WINDOW_S,
        output_dt_s=FINEST_OUTPUT_DT_S,
    )
    if audit.get("passed") is not True:
        raise ValueError(f"Shared-input audit failed for {anchor.label}: {audit}")

    high_fidelity["run"].update(
        {
            "name": f"three_anchor_hf_qualification_{anchor.slug}",
            "output_directory": f"generated/direct_runs/{anchor.slug}",
            "claim_level": "DERIVED",
        }
    )
    high_fidelity["solver"].update(
        {
            "profile": "production",
            "t_end": TARGET_WINDOW_S,
            "output_dt": FINEST_OUTPUT_DT_S,
            "max_step": FINEST_OUTPUT_DT_S,
            "method": "Radau",
            "resolve_longitudinal_waves": True,
            "analytic_jacobian": True,
            "allow_subminimum_mesh": False,
            "rtol": 1.0e-8,
            "position_atol": 1.0e-10,
            "velocity_atol": 1.0e-9,
            "quaternion_atol": 1.0e-10,
            "angular_velocity_atol": 1.0e-9,
        }
    )
    high_fidelity["solver"]["static"].update(
        {
            "method": "energy_minimize",
            "force_tolerance": 1.0e-8,
            "max_iterations": 200,
            "continuation_steps": 6,
            "line_search_min": 1.0e-5,
        }
    )
    for branch, elements in FINEST_MESH.items():
        high_fidelity["cables"][branch]["elements"] = elements
    return high_fidelity, audit


def build_all(output_root: Path = CANDIDATE_ROOT) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    configs_root = output_root / "configs"
    ladder = load_ladder()
    frozen_spec = _freeze_and_validate_spec(
        yaml.safe_load(VALIDATION_SPEC_PATH.read_text(encoding="utf-8"))
    )
    records: list[dict[str, Any]] = []
    audits: dict[str, Any] = {}

    for anchor in ladder.ANCHORS:
        raw, audit = production_config(anchor, ladder)
        config = load_config(raw)
        validate_physical_config(config)
        target = _validation_target_applicability(config, frozen_spec)
        if target["passed"] is not True:
            raise ValueError(
                f"Formal validation target does not apply to {anchor.label}: {target}"
            )
        levels = _space_configs(config)
        meshes = [
            {
                branch: int(getattr(level.cables, branch).elements)
                for branch in FINEST_MESH
            }
            for level in levels
        ]
        expected_meshes = [
            {"upper_A": 6, "upper_B": 6, "lower": 8},
            {"upper_A": 12, "upper_B": 12, "lower": 16},
            FINEST_MESH,
        ]
        if meshes != expected_meshes:
            raise ValueError(f"Unexpected formal space levels for {anchor.label}: {meshes}")

        config_path = configs_root / f"{anchor.slug}.yaml"
        write_yaml(config_path, raw)
        reloaded = load_config(config_path)
        validate_physical_config(reloaded)
        resource = _high_fidelity_resource_estimate(
            reloaded,
            t_end=float(to_si(reloaded.solver.t_end, default_unit="s")),
            output_dt=float(to_si(reloaded.solver.output_dt, default_unit="s")),
        )
        records.append(
            {
                "anchor": anchor.label,
                "slug": anchor.slug,
                "config": str(config_path.relative_to(output_root)),
                "config_file_sha256": sha256_file(config_path),
                "resolved_config_sha256": resolved_config_sha256(reloaded),
                "space_mesh_levels": meshes,
                "formal_target": target,
                "resource_estimate": resource,
            }
        )
        audits[anchor.label] = audit

    write_json(output_root / "shared_input_audits.json", audits)
    plan = {
        "schema_version": "YPS-THREE-ANCHOR-HF-QUALIFICATION-PLAN-1.0",
        "scope": (
            "0.12 s initial-window production HF numerical qualification; "
            "not long-window modal convergence or apparatus validation"
        ),
        "git_head_at_freeze": git_head(),
        "generator_sha256": sha256_file(SCRIPT_PATH),
        "model_ladder_sha256": sha256_file(LADDER_PATH),
        "formal_hf_source_sha256": source_hash(HF_SOURCE_ROOT / "ypendulum"),
        "formal_validation_spec": str(VALIDATION_SPEC_PATH.relative_to(REPOSITORY_ROOT)),
        "formal_validation_spec_sha256": sha256_file(VALIDATION_SPEC_PATH),
        "formal_validation_spec_canonical_sha256": canonical_sha256(frozen_spec),
        "target_window_s": TARGET_WINDOW_S,
        "finest_output_dt_s": FINEST_OUTPUT_DT_S,
        "finest_mesh": FINEST_MESH,
        "anchors": records,
    }
    write_json(output_root / "qualification_plan.json", plan)

    release_files = [
        ("build_qualification_configs.py", SCRIPT_PATH),
        ("qualification_plan.json", output_root / "qualification_plan.json"),
        ("shared_input_audits.json", output_root / "shared_input_audits.json"),
        *[
            (str(path.relative_to(output_root)), path)
            for path in sorted(configs_root.glob("*.yaml"))
        ],
    ]
    lines = [
        f"{sha256_file(path)}  {label}"
        for label, path in sorted(release_files)
    ]
    (output_root / "MANIFEST.inputs.sha256").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return plan


def main() -> int:
    plan = build_all()
    print(
        json.dumps(
            {
                "status": "FROZEN",
                "anchor_count": len(plan["anchors"]),
                "git_head": plan["git_head_at_freeze"],
                "target_window_s": plan["target_window_s"],
                "finest_mesh": plan["finest_mesh"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

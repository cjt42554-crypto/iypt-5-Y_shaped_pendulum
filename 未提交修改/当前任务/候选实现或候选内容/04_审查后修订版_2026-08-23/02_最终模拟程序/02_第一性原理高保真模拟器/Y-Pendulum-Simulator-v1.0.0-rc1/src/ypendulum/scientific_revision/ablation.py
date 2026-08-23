"""Executable M0--M5 chain with one sealed common material state."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .common_state import create_common_state, forward_initial_state_from_common
from .model_identity import EvidenceLevel
from .overlay import (
    BRANCH_NAMES,
    BranchBendingSpecification,
    RevisionOverlay,
    dump_overlay,
    load_overlay,
)

ABLATION_SCHEMA = "YPS-SCIENTIFIC-REVISION-ABLATION-2.0"
ABLATION_EXECUTION_SCHEMA = "YPS-ABLATION-EXECUTION-2.0"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_hash(value: Any) -> str:
    return _sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_worktree_clean() -> bool:
    try:
        status = subprocess.check_output(
            ["git", "status", "--porcelain=v1"],
            cwd=Path(__file__).resolve().parent,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return not bool(status.strip())


def _zero_bending(source: str) -> dict[str, BranchBendingSpecification]:
    return {name: BranchBendingSpecification(0.0, source) for name in BRANCH_NAMES}


def _ladder_overlays(measured: RevisionOverlay) -> dict[str, RevisionOverlay]:
    shared_semantics = "sealed_common_hf_material_state"
    m1 = replace(
        measured,
        model_id="HF-TENSION-ROD-RIGID-BOB-LIMIT-1.1",
        compression_scale=0.0,
        branch_bending=_zero_bending("M1_zero_EI_controlled_limit"),
        bob_mode="point_limit",
        point_limit_fraction=1.0e-3,
        contact_guard_mode="disabled",
        requested_claim=EvidenceLevel.MODEL_CONSISTENT,
        initial_state_semantics=shared_semantics,
        notes=(
            "M1：精确仅受拉、EI=0、声明的点摆球极限。",
            "与 M0 的差异包含后端状态空间及确定性映射残差。",
        ),
    )
    m2 = replace(
        m1,
        bob_mode="finite",
        contact_guard_mode="inherited",
        notes=("M2：在完全相同的 HF 离散初态上恢复有限刚体摆球与偏心连接。",),
    )
    m3 = replace(
        measured,
        model_id="HF-TENSION-ROD-RIGID-BOB-LIMIT-1.1",
        compression_scale=0.0,
        bob_mode="finite",
        contact_guard_mode="inherited",
        requested_claim=EvidenceLevel.MODEL_CONSISTENT,
        initial_state_semantics=shared_semantics,
        notes=("M3：只加入三支独立 EI；不重新平衡初态。",),
    )
    m4 = replace(
        measured,
        model_id="HF-BILATERAL-ROD-RIGID-BOB-1.1",
        compression_scale=1.0,
        bob_mode="finite",
        contact_guard_mode="inherited",
        requested_claim=EvidenceLevel.CODE_VERIFIED,
        initial_state_semantics=shared_semantics,
        notes=("M4：只加入双边压缩本构；不重新平衡初态。",),
    )
    m5 = replace(
        m4,
        notes=("M5：在同一初态上启用基础配置明确声明的外部机制。",),
    )
    return {"M1": m1, "M2": m2, "M3": m3, "M4": m4, "M5": m5}


def build_ablation_ladder(
    measured_overlay_path: str | Path,
    output_directory: str | Path,
) -> Path:
    """Write a portable, executable ladder definition; do not run it yet."""

    measured_source = Path(measured_overlay_path).expanduser().resolve()
    measured = load_overlay(measured_source)
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    overlays = _ladder_overlays(measured)
    filenames = {
        "M1": "m1-unilateral-zero-ei-point-limit.yaml",
        "M2": "m2-unilateral-zero-ei-finite-bob.yaml",
        "M3": "m3-unilateral-measured-ei-finite-bob.yaml",
        "M4": "m4-bilateral-measured-ei-finite-bob.yaml",
        "M5": "m5-full-mechanisms.yaml",
    }
    for stage, overlay in overlays.items():
        dump_overlay(overlay, output / filenames[stage])
    stages = [
        {
            "stage": "M0",
            "label": "FWD tension-cable / point-bob baseline",
            "model_id": "FWD-TENSION-CABLE-POINT-BOB-1.1",
            "overlay": None,
            "executable": True,
            "isolated_change": "reference",
        }
    ]
    isolated = {
        "M1": "backend_space_discretization_and_state_mapping",
        "M2": "finite_rigid_bob_and_eccentric_attachment",
        "M3": "independent_branch_EI",
        "M4": "bilateral_compression_constitutive_law",
        "M5": "explicitly_enabled_external_mechanisms",
    }
    for stage in ("M1", "M2", "M3", "M4", "M5"):
        overlay = overlays[stage]
        stages.append(
            {
                "stage": stage,
                "label": overlay.notes[0],
                "model_id": overlay.model_id,
                "overlay": filenames[stage],
                "executable": True,
                "isolated_change": isolated[stage],
                "requested_analysis_level": overlay.requested_analysis_level.value,
                "model_claim_ceiling": overlay.model_claim_ceiling.value,
                "initial_state_semantics": overlay.initial_state_semantics,
            }
        )
    manifest = {
        "schema_version": ABLATION_SCHEMA,
        "measured_overlay_sha256": _sha256(measured_source.read_bytes()),
        "source_path_is_identity": False,
        "common_initial_state_contract": {
            "supports": "positions_and_velocities",
            "junction": "position_and_velocity",
            "bob": "COM_orientation_linear_and_angular_velocity",
            "branches": "material_coordinates_positions_velocities_and_natural_lengths",
            "M1_to_M5": "identical_raw_HF_state_bytes",
            "M0": "deterministic_polynomial_projection_with_reported_residual",
        },
        "comparison_policy": {
            "adjacent_stages_only": True,
            "do_not_force_full_model_agreement": True,
            "production_qualification": False,
            "experimental_validation": False,
        },
        "stages": stages,
    }
    (output / "ablation-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        flattened: dict[str, Any] = {}
        for key in sorted(value):
            child = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten(value[key], child))
        return flattened
    return {prefix: value}


_TRANSITION_WHITELISTS = {
    ("M0", "M1"): {
        "backend",
        "model_id",
        "model_claim_ceiling",
        "initial_state_semantics",
        "mapping_residuals",
    },
    ("M1", "M2"): {"bob_mode", "contact_guard_mode"},
    ("M2", "M3"): {"branch_EI_N_m2"},
    ("M3", "M4"): {
        "model_id",
        "compression_scale",
        "requested_analysis_level",
        "model_claim_ceiling",
    },
    ("M4", "M5"): {"external_mechanisms"},
}


def validate_ablation_transition(
    left_stage: str,
    right_stage: str,
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> tuple[str, ...]:
    transition = (left_stage, right_stage)
    if transition not in _TRANSITION_WHITELISTS:
        raise ValueError(f"不允许的消融相邻级：{left_stage}->{right_stage}")
    left_flat = _flatten(dict(left))
    right_flat = _flatten(dict(right))
    changed_leaf = {
        key
        for key in left_flat.keys() | right_flat.keys()
        if left_flat.get(key, object()) != right_flat.get(key, object())
    }
    changed_roots = tuple(sorted({key.split(".", 1)[0] for key in changed_leaf}))
    unexpected = sorted(set(changed_roots) - _TRANSITION_WHITELISTS[transition])
    if unexpected:
        raise ValueError(
            f"{left_stage}->{right_stage} 出现白名单外字段漂移：{unexpected}"
        )
    left_state = left.get("common_state_raw_sha256")
    right_state = right.get("common_state_raw_sha256")
    if left_stage != "M0" and left_state != right_state:
        raise ValueError(f"{left_stage}->{right_stage} 偷偷改变了冻结 HF 初态。")
    return changed_roots


def _resolve_input(plan_source: Path, value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f"{name} 必须是计划目录内的非空相对路径。")
    if ".." in Path(value).parts:
        raise ValueError(f"{name} 不得越出计划目录。")
    root = plan_source.parent.resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise ValueError(f"{name} 不是计划目录内的普通文件。")
    return path


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"{path} 根节点必须是映射。")
    return value


def _disable_external_mechanisms(config: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(config)
    result["bob"]["drag"]["enabled"] = False
    result["bob"]["buoyancy"] = False
    result["junction"]["drag_linear"] = {"value": 0.0, "unit": "N*s/m"}
    for name in BRANCH_NAMES:
        result["cables"][name]["drag_enabled"] = False
    return result


def _enabled_external_mechanisms(config: Mapping[str, Any]) -> list[str]:
    enabled: list[str] = []
    if bool(config.get("bob", {}).get("drag", {}).get("enabled")):
        enabled.append("bob_aerodynamic_drag")
    if bool(config.get("bob", {}).get("buoyancy")):
        enabled.append("bob_buoyancy")
    for name in BRANCH_NAMES:
        if bool(config.get("cables", {}).get(name, {}).get("drag_enabled")):
            enabled.append(f"{name}_aerodynamic_drag")
    if config.get("supports", {}).get("A", {}).get("type") == "prescribed" or config.get(
        "supports", {}
    ).get("B", {}).get("type") == "prescribed":
        enabled.append("prescribed_support_motion")
    drag = config.get("junction", {}).get("drag_linear", 0.0)
    drag_value = drag.get("value", 0.0) if isinstance(drag, dict) else drag
    if float(drag_value) > 0.0:
        enabled.append("junction_drag")
    if isinstance(config.get("observer"), dict):
        enabled.append("declared_observer")
    return enabled


def _forward_root() -> Path:
    simulator_root = Path(__file__).resolve().parents[3]
    root = (
        simulator_root
        / "../../01_前向预测数值求解器/y_pendulum_forward_solver"
    ).resolve()
    if not (root / "y_pendulum_forward" / "cli.py").is_file():
        raise FileNotFoundError("修订副本内 FWD 后端不存在。")
    return root


def _quantity_value(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("value")
    scalar = float(value)
    if not np.isfinite(scalar):
        raise ValueError("配置量不是有限数。")
    return scalar


def _prepare_forward_config(
    source: dict[str, Any],
    hf_config: dict[str, Any],
    common_state_path: Path,
    duration_s: float,
) -> tuple[dict[str, Any], dict[str, float]]:
    config = deepcopy(source)
    config["physical"]["T"] = duration_s
    config["physical"]["rho_air"] = 0.0
    config["physical"]["bob_volume"] = 0.0
    config["physical"]["bob_c1"] = 0.0
    config["physical"]["bob_c2"] = 0.0
    name_map = {"A": "upper_A", "B": "upper_B", "lower": "lower"}
    for fwd_name, hf_name in name_map.items():
        config["numerics"]["elements"][fwd_name] = int(
            hf_config["cables"][hf_name]["elements"]
        )
        branch = config["physical"]["branches"][fwd_name]
        for key in ("c_parallel", "c_perp", "d_parallel", "d_perp"):
            branch[key] = 0.0
    config["numerics"]["max_step"] = _quantity_value(
        hf_config["solver"]["max_step"]
    )
    config["numerics"]["output_dt"] = _quantity_value(
        hf_config["solver"]["output_dt"]
    )
    record_times = config.get("observation", {}).get("record_times")
    if isinstance(record_times, dict) and record_times.get("kind") == "uniform":
        record_times["start"] = 0.0
        record_times["stop"] = duration_s
        record_times["step"] = min(
            duration_s,
            _quantity_value(hf_config["solver"]["output_dt"]),
        )
    initial_state, residuals = forward_initial_state_from_common(common_state_path)
    config["initial_state"] = initial_state
    config.setdefault("metadata", {})["purpose"] = (
        "M0 low-cost common-state smoke; not production qualification"
    )
    return config, residuals


def _run_forward(config_path: Path, output: Path) -> dict[str, Any]:
    environment = dict(os.environ)
    source_root = str(_forward_root())
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = source_root if not existing else source_root + os.pathsep + existing
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "y_pendulum_forward.cli",
            "run",
            str(config_path),
            "--output",
            str(output),
            "--no-plots",
        ],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    (output.parent / "m0-forward-console.log").write_text(
        "command="
        + " ".join(completed.args)
        + f"\nexit_code={completed.returncode}\n"
        + completed.stdout
        + completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"M0 FWD 后端运行失败，退出码 {completed.returncode}。")
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    return result


def _run_arrays(path: Path, *, backend: str) -> tuple[np.ndarray, np.ndarray]:
    with np.load(path / "trajectory.npz", allow_pickle=False) as archive:
        time = np.asarray(archive["time"], dtype=float)
        key = "state__r_m" if backend == "FWD" else "bob_position"
        bob = np.asarray(archive[key], dtype=float)
    return time, bob


def _trajectory_nrms(
    left_time: np.ndarray,
    left_bob: np.ndarray,
    right_time: np.ndarray,
    right_bob: np.ndarray,
) -> float:
    start = max(float(left_time[0]), float(right_time[0]))
    stop = min(float(left_time[-1]), float(right_time[-1]))
    sample = left_time[(left_time >= start) & (left_time <= stop)]
    if sample.size < 2:
        sample = np.linspace(start, stop, 2)
    left = np.column_stack(
        [np.interp(sample, left_time, left_bob[:, index]) for index in range(3)]
    )
    right = np.column_stack(
        [np.interp(sample, right_time, right_bob[:, index]) for index in range(3)]
    )
    scale = max(float(np.linalg.norm(np.ptp(np.vstack((left, right)), axis=0))), 1.0e-12)
    return float(np.sqrt(np.mean(np.sum((left - right) ** 2, axis=1))) / scale)


def _descriptor(
    stage: str,
    overlay: RevisionOverlay | None,
    common_raw_sha: str,
    mapping_residuals: Mapping[str, Any],
    external_mechanisms: list[str],
) -> dict[str, Any]:
    if stage == "M0":
        return {
            "backend": "FWD",
            "model_id": "FWD-TENSION-CABLE-POINT-BOB-1.1",
            "bob_mode": "point_limit",
            "contact_guard_mode": "disabled",
            "compression_scale": 0.0,
            "branch_EI_N_m2": {name: 0.0 for name in BRANCH_NAMES},
            "requested_analysis_level": "MODEL_CONSISTENT",
            "model_claim_ceiling": "CODE_VERIFIED",
            "initial_state_semantics": "deterministic_common_state_projection",
            "common_state_raw_sha256": common_raw_sha,
            "mapping_residuals": dict(mapping_residuals),
            "external_mechanisms": external_mechanisms,
        }
    assert overlay is not None
    return {
        "backend": "HF",
        "model_id": overlay.model_id,
        "bob_mode": overlay.bob_mode,
        "contact_guard_mode": overlay.contact_guard_mode,
        "compression_scale": overlay.compression_scale,
        "branch_EI_N_m2": {
            name: overlay.branch_bending[name].value_N_m2 for name in BRANCH_NAMES
        },
        "requested_analysis_level": overlay.requested_analysis_level.value,
        "model_claim_ceiling": overlay.model_claim_ceiling.value,
        "initial_state_semantics": overlay.initial_state_semantics,
        "common_state_raw_sha256": common_raw_sha,
        "mapping_residuals": {"hf_discrete_state_residual": 0.0},
        "external_mechanisms": external_mechanisms,
    }


def execute_ablation_chain(
    plan_path: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    """Execute M0 through M5 for at most two milliseconds."""

    from .runner import run_revised_high_fidelity

    plan_source = Path(plan_path).expanduser().resolve()
    plan_raw = plan_source.read_bytes()
    plan = _load_mapping(plan_source)
    if plan.get("schema_version") != ABLATION_EXECUTION_SCHEMA:
        raise ValueError(f"消融执行 schema 必须是 {ABLATION_EXECUTION_SCHEMA}。")
    live_commit = _git_commit()
    if live_commit is None or plan.get("git_commit") != live_commit:
        raise ValueError("消融计划 git_commit 与当前源码提交不一致。")
    if not _git_worktree_clean():
        raise ValueError("消融执行器要求干净工作树，以便将运行绑定到确切提交。")
    hf_path = _resolve_input(plan_source, plan.get("base_hf_config"), "base_hf_config")
    fwd_path = _resolve_input(plan_source, plan.get("forward_config"), "forward_config")
    measured_path = _resolve_input(
        plan_source, plan.get("measured_overlay"), "measured_overlay"
    )
    identities = {
        "base_hf_config_sha256": _sha256(hf_path.read_bytes()),
        "forward_config_sha256": _sha256(fwd_path.read_bytes()),
        "measured_overlay_sha256": _sha256(measured_path.read_bytes()),
    }
    for name, actual in identities.items():
        if plan.get(name) != actual:
            raise ValueError(f"{name} 与消融计划不一致。")
    duration = float(plan.get("duration_s", np.nan))
    if not np.isfinite(duration) or not 0.0 < duration <= 0.002:
        raise ValueError("消融冒烟 duration_s 必须位于 (0, 0.002]。")

    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    raw_plan_sha = _sha256(plan_raw)
    (output / "ablation-plan.raw").write_bytes(plan_raw)
    (output / "ablation-plan.raw.sha256").write_text(raw_plan_sha + "\n", encoding="ascii")
    overlay_root = output / "overlays"
    build_ablation_ladder(measured_path, overlay_root)
    overlay_paths = {
        "M1": overlay_root / "m1-unilateral-zero-ei-point-limit.yaml",
        "M2": overlay_root / "m2-unilateral-zero-ei-finite-bob.yaml",
        "M3": overlay_root / "m3-unilateral-measured-ei-finite-bob.yaml",
        "M4": overlay_root / "m4-bilateral-measured-ei-finite-bob.yaml",
        "M5": overlay_root / "m5-full-mechanisms.yaml",
    }
    overlays = {stage: load_overlay(path) for stage, path in overlay_paths.items()}

    hf_base = _load_mapping(hf_path)
    hf_base["solver"]["t_end"] = {"value": duration, "unit": "s"}
    hf_base["analysis"]["compute_spectrum"] = False
    hf_base["solver"]["allow_subminimum_mesh"] = True
    hf_base["run"]["claim_level"] = "DERIVED"
    m1_m4_config = _disable_external_mechanisms(hf_base)
    m5_config = deepcopy(hf_base)
    config_root = output / "stage-configs"
    config_root.mkdir()
    paired_path = config_root / "m1-m4.yaml"
    m5_path = config_root / "m5.yaml"
    paired_path.write_text(
        yaml.safe_dump(m1_m4_config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    m5_path.write_text(
        yaml.safe_dump(m5_config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    common_manifest = create_common_state(
        paired_path,
        overlay_paths["M4"],
        output / "common-state",
    )
    common_payload = json.loads(common_manifest.read_text(encoding="utf-8"))
    common_raw_sha = str(common_payload["raw_state_sha256"])

    fwd_source = _load_mapping(fwd_path)
    fwd_config, forward_mapping = _prepare_forward_config(
        fwd_source,
        m1_m4_config,
        common_manifest,
        duration,
    )
    m0_config_path = config_root / "m0-forward.json"
    m0_config_path.write_text(
        json.dumps(fwd_config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    run_root = output / "runs"
    run_root.mkdir()
    m0_result = _run_forward(m0_config_path, run_root / "M0")
    stages: list[dict[str, Any]] = []
    descriptors: dict[str, dict[str, Any]] = {}
    descriptors["M0"] = _descriptor(
        "M0", None, common_raw_sha, forward_mapping, []
    )
    stages.append(
        {
            "stage": "M0",
            "status": "COMPLETE",
            "run_directory": "runs/M0",
            "numerical_status": m0_result.get("numerical_status"),
            "descriptor": descriptors["M0"],
        }
    )
    for stage in ("M1", "M2", "M3", "M4", "M5"):
        stage_config = m5_path if stage == "M5" else paired_path
        external = _enabled_external_mechanisms(m5_config) if stage == "M5" else []
        if stage == "M5" and not external:
            descriptors[stage] = _descriptor(
                stage, overlays[stage], common_raw_sha, {}, external
            )
            stages.append(
                {
                    "stage": stage,
                    "status": "INCOMPLETE",
                    "reason": "base configuration enables no external mechanism",
                    "descriptor": descriptors[stage],
                }
            )
            continue
        run_path = run_root / stage
        run_revised_high_fidelity(
            stage_config,
            overlay_paths[stage],
            run_path,
            common_state_path=common_manifest,
            execution_identity={
                "schema_version": ABLATION_EXECUTION_SCHEMA,
                "plan_sha256": raw_plan_sha,
                "git_commit": live_commit,
                "stage": stage,
                "common_state_raw_sha256": common_raw_sha,
            },
        )
        summary = json.loads((run_path / "summary.json").read_text(encoding="utf-8"))
        descriptors[stage] = _descriptor(
            stage, overlays[stage], common_raw_sha, {}, external
        )
        stages.append(
            {
                "stage": stage,
                "status": "COMPLETE",
                "run_directory": f"runs/{stage}",
                "numerical_status": summary.get("numerical_status"),
                "actual_evidence_level": summary.get("actual_evidence_level"),
                "descriptor": descriptors[stage],
            }
        )

    transition_records: list[dict[str, Any]] = []
    for left, right in zip(
        ("M0", "M1", "M2", "M3", "M4"),
        ("M1", "M2", "M3", "M4", "M5"),
        strict=True,
    ):
        changed = validate_ablation_transition(
            left, right, descriptors[left], descriptors[right]
        )
        transition_records.append(
            {"left": left, "right": right, "changed_roots": list(changed), "passed": True}
        )

    comparisons: list[dict[str, Any]] = []
    for left, right in zip(
        ("M0", "M1", "M2", "M3", "M4"),
        ("M1", "M2", "M3", "M4", "M5"),
        strict=True,
    ):
        if not (run_root / right).is_dir():
            comparisons.append(
                {"left": left, "right": right, "status": "INCOMPLETE"}
            )
            continue
        left_time, left_bob = _run_arrays(
            run_root / left, backend="FWD" if left == "M0" else "HF"
        )
        right_time, right_bob = _run_arrays(run_root / right, backend="HF")
        comparisons.append(
            {
                "left": left,
                "right": right,
                "status": "DIAGNOSTIC_ONLY",
                "common_observable_trajectory_NRMS": _trajectory_nrms(
                    left_time, left_bob, right_time, right_bob
                ),
                "event_sets": "reported_without_forcing_model_agreement",
                "energy_ledger": "stored_in_each_backend_run",
                "frequency_reliability": "UNAVAILABLE_SHORT_2MS_SMOKE",
                "mapping_residuals": {
                    "left": descriptors[left]["mapping_residuals"],
                    "right": descriptors[right]["mapping_residuals"],
                },
                "schema_diff": next(
                    item["changed_roots"]
                    for item in transition_records
                    if item["left"] == left and item["right"] == right
                ),
            }
        )

    complete_or_declared = all(item["status"] in {"COMPLETE", "INCOMPLETE"} for item in stages)
    source_unchanged = _git_commit() == live_commit and _git_worktree_clean()
    plan_unchanged = _sha256(plan_source.read_bytes()) == raw_plan_sha
    report = {
        "schema_version": ABLATION_EXECUTION_SCHEMA,
        "plan_id": plan.get("plan_id"),
        "plan_sha256": raw_plan_sha,
        "plan_frozen": plan_unchanged,
        "git_commit": live_commit,
        **identities,
        "common_state_manifest": "common-state/common-state.json",
        "common_state_raw_sha256": common_raw_sha,
        "common_state_canonical_sha256": common_payload["canonical_state_sha256"],
        "m0_executable": stages[0]["status"] == "COMPLETE",
        "common_state_enforced": len(
            {
                descriptors[stage]["common_state_raw_sha256"]
                for stage in ("M1", "M2", "M3", "M4", "M5")
            }
        )
        == 1,
        "adjacent_diff_enforced": all(item["passed"] for item in transition_records),
        "stages": stages,
        "transitions": transition_records,
        "comparisons": comparisons,
        "source_unchanged_after_runs": source_unchanged,
        "status": (
            "PASS"
            if complete_or_declared and plan_unchanged and source_unchanged
            else "FAIL"
        ),
        "actual_evidence_level": "MODEL_CONSISTENT",
        "numerically_qualified": False,
        "experimentally_validated": False,
        "predictive": False,
        "duration_s": duration,
        "interpretation": (
            "这是 1--2 ms 的共同初态全链冒烟。相邻差异用于机制诊断，"
            "不要求 FWD 与 HF 完整模型一致，也不是生产资格或实验验证。"
        ),
        "generated_at_utc": _utc_now(),
    }
    (output / "ablation-smoke.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if report["status"] != "PASS":
        raise RuntimeError("M0--M5 共同初态冒烟链未通过。")
    return report

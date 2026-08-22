"""Standalone and GUI-compatible runner for revised HF model identities.

The runner keeps the inherited HDF5 display layout, but writes a new model
identity, explicit-EI manifest and evidence ceiling. Revised runs never inherit
the original HF production certificate.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from ypendulum.api import (
    _analysis_from_arrays,
    _append_analysis_hdf5,
    _project_positions,
    _short_window_analysis,
    _write_common_config,
)
from ypendulum.config import load_config
from ypendulum.hf.solver import prepare_initial_state, simulate_high_fidelity
from ypendulum.io import write_hf_result

from .overlay import BRANCH_NAMES, RevisionOverlay, load_overlay
from .revised_model import RevisedHighFidelityModel
from .scientific_guard import frequency_preview, mechanism_audit

RUN_SCHEMA = "YPS-SCIENTIFIC-REVISION-RUN-1.1"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _write_events(path: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        path.write_text("type,time\n", encoding="utf-8")
        return
    preferred = [
        "type",
        "time",
        "branch",
        "material_segment",
        "bracket_start_s",
        "bracket_end_s",
        "axial_regime_before",
        "axial_regime_after",
    ]
    keys = set().union(*(event.keys() for event in events))
    fieldnames = [key for key in preferred if key in keys] + sorted(keys - set(preferred))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for event in events:
            writer.writerow(
                {
                    key: (
                        json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True)
                        if isinstance(value, (dict, list, tuple, np.ndarray))
                        else _json_safe(value)
                    )
                    for key, value in event.items()
                }
            )


def _result_arrays(result: Any) -> dict[str, np.ndarray]:
    all_tension = np.concatenate(
        [np.asarray(result.cable_tension[name], dtype=float) for name in BRANCH_NAMES],
        axis=1,
    )
    all_signed = np.concatenate(
        [np.asarray(result.cable_axial_force[name], dtype=float) for name in BRANCH_NAMES],
        axis=1,
    )
    arrays: dict[str, np.ndarray] = {
        "time": np.asarray(result.time, dtype=float),
        "bob_position": np.asarray(result.bob_position, dtype=float),
        "bob_velocity": np.asarray(result.bob_velocity, dtype=float),
        "junction_position": np.asarray(result.junction_position, dtype=float),
        "junction_velocity": np.asarray(result.junction_velocity, dtype=float),
        "max_tension": np.max(all_tension, axis=1),
        "min_tension": np.min(all_tension, axis=1),
        "max_signed_axial_force": np.max(all_signed, axis=1),
        "min_signed_axial_force": np.min(all_signed, axis=1),
    }
    for name in BRANCH_NAMES:
        arrays[f"tension_{name}"] = np.asarray(result.cable_tension[name], dtype=float)
        arrays[f"signed_axial_force_{name}"] = np.asarray(
            result.cable_axial_force[name], dtype=float
        )
    for name in (
        "mechanical",
        "elastic_axial",
        "elastic_bending",
        "balance_residual",
        "axial_dissipation_rate",
        "aero_dissipation_rate",
    ):
        if name in result.energy:
            arrays[f"energy_{name}"] = np.asarray(result.energy[name], dtype=float)
    return arrays


def _summary(
    result: Any,
    model: RevisedHighFidelityModel,
    overlay: RevisionOverlay,
    backend_analysis: dict[str, Any],
) -> dict[str, Any]:
    diagnostics = result.diagnostics
    minimum_signed = float(diagnostics.get("minimum_signed_axial_force_N", 0.0))
    maximum_signed = float(diagnostics.get("maximum_signed_axial_force_N", 0.0))
    minimum_tension = float(diagnostics.get("minimum_tension_N", 0.0))
    maximum_tension = float(diagnostics.get("maximum_tension_N", 0.0))
    bending_fraction = float(diagnostics.get("bending_energy_fraction_peak", 0.0))
    frequency = {
        "x": frequency_preview(result.time, result.bob_position[:, 0]).to_dict(),
        "y": frequency_preview(result.time, result.bob_position[:, 1]).to_dict(),
    }
    guard = mechanism_audit(
        minimum_signed_axial_force_N=minimum_signed,
        bending_energy_fraction_peak=bending_fraction,
    )
    guard["warnings"].append(
        "本结果来自修订模型身份；不得继承原 HF 生产证书或称为实验预测。"
    )
    run_status = (
        "out_of_scope_prefix"
        if result.physical_status == "OUT_OF_SCOPE"
        and result.numerical_status == "SUCCESS_EVENT"
        else "undetermined"
    )
    return {
        "schema_version": RUN_SCHEMA,
        "run_name": str(model.cfg.run.name),
        "model": model.model_id,
        "model_identity": model.revision_manifest["model_identity"],
        "base_configuration_claim_level": str(model.cfg.run.claim_level),
        "effective_claim": overlay.effective_claim.value,
        "status": run_status,
        "physical_status": result.physical_status,
        "numerical_status": result.numerical_status,
        "valid_interval_s": list(result.valid_interval),
        "duration_s": float(result.time[-1] - result.time[0]),
        "sample_count": int(result.time.size),
        "event_count": len(result.events),
        "minimum_tension_N": minimum_tension,
        "maximum_tension_N": maximum_tension,
        "minimum_signed_axial_force_N": minimum_signed,
        "maximum_signed_axial_force_N": maximum_signed,
        "bending_energy_fraction_peak": bending_fraction,
        "max_abs_energy_balance_residual": float(
            diagnostics.get("max_abs_energy_balance_residual", np.nan)
        ),
        "maximum_quaternion_norm_error": float(
            diagnostics.get("maximum_quaternion_norm_error", np.nan)
        ),
        "accepted_integration_step_count": int(
            diagnostics.get("accepted_integration_step_count", 0)
        ),
        "actual_branch_EI_N_m2": {
            name: float(model.branches[name].ei) for name in BRANCH_NAMES
        },
        "compression_scale": float(model.compression_regularization_scale),
        "initial_state_semantics": overlay.initial_state_semantics,
        "backend_frequency_fit": backend_analysis,
        "frequency_analysis_reliable": False,
        "frequency_claim_level": "PREVIEW_ONLY_UNCERTIFIED",
        "frequency_preview": frequency,
        "frequency_policy": (
            "Hann 窗预览与后端有限窗拟合均不构成正式频率证书；"
            "目标工况必须另行完成多周期和数值资格。"
        ),
        "scientific_guard": guard,
        "experimental_validation_status": "NOT_RUN",
        "prediction_status": "NOT_PREDICTIVE",
    }


def _publish_bundle(
    directory: Path,
    *,
    cfg: Any,
    overlay_source: Path,
    overlay: RevisionOverlay,
    model: RevisedHighFidelityModel,
    preparation: Any,
    result: Any,
) -> None:
    _resolved, config_hash = _write_common_config(directory, cfg)
    result.run_directory = directory
    support_a, _, _ = model.support_motion["support_A"].state(0.0)
    support_b, _, _ = model.support_motion["support_B"].state(0.0)
    backend_analysis = (
        _analysis_from_arrays(
            cfg,
            result.time,
            result.bob_position,
            result.bob_velocity,
            support_a,
            support_b,
            model.gravity,
        )
        if result.time.size >= 16
        else _short_window_analysis(cfg, result.time)
    )
    summary = _summary(result, model, overlay, backend_analysis)

    write_hf_result(directory / "result.h5", result, model)
    if result.time.size >= 16:
        _append_analysis_hdf5(
            directory / "result.h5",
            cfg,
            result.time,
            result.bob_position,
            support_a,
            support_b,
            model.gravity,
            backend_analysis,
        )
    observer_time, observer_values, operator_id, value_unit = _project_positions(
        cfg, result.time, result.bob_position
    )
    np.savez_compressed(
        directory / "observer_output.npz",
        time=observer_time,
        values=observer_values,
        operator_id=np.asarray(operator_id),
        value_unit=np.asarray(value_unit),
    )
    np.savez_compressed(directory / "trajectory.npz", **_result_arrays(result))
    _write_events(directory / "events.csv", list(result.events))
    _write_json(directory / "events.json", list(result.events))
    _write_json(directory / "diagnostics.json", result.diagnostics)
    _write_json(directory / "revision_manifest.json", model.revision_manifest)
    _write_json(directory / "summary.json", summary)
    _write_json(
        directory / "observer_summary.json",
        {
            "operator_id": operator_id,
            "value_unit": value_unit,
            "coordinate_source": "rigid_bob_center_of_mass",
            "sample_count": int(observer_time.size),
        },
    )
    _write_json(
        directory / "input_identity.json",
        {
            "config_resolved_sha256": config_hash,
            "overlay_path": str(overlay_source),
            "model_id": model.model_id,
            "initial_state_semantics": overlay.initial_state_semantics,
            "preparation_mode": preparation.preparation_mode,
            "preparation_residual_inf_N": preparation.residual_inf_N,
            "certificate_inheritance": "FORBIDDEN",
        },
    )
    (directory / "report.md").write_text(
        "\n".join(
            [
                "# Y 形摆审查后修订 HF 运行",
                "",
                f"- 模型身份：`{model.model_id}`",
                f"- 有效证据等级：`{overlay.effective_claim.value}`",
                f"- 物理状态：`{result.physical_status}`",
                f"- 数值状态：`{result.numerical_status}`",
                f"- 事件数：`{len(result.events)}`",
                "",
                "该运行使用显式各支路 EI 和独立模型身份，不继承原 HF 生产证书。",
                "没有封存真实实验时，不得标记为 EXPERIMENTALLY_VALIDATED 或 PREDICTIVE。",
                "",
            ]
        ),
        encoding="utf-8",
    )


def run_revised_high_fidelity(
    config_path: str | Path,
    overlay_path: str | Path,
    output_directory: str | Path,
) -> Path:
    config_source = Path(config_path).expanduser().resolve()
    overlay_source = Path(overlay_path).expanduser().resolve()
    output = Path(output_directory).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"修订输出目录已存在，拒绝混写：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    overlay = load_overlay(overlay_source)
    cfg = load_config(config_source)
    if cfg.run.mode != "high_fidelity":
        raise ValueError("修订 HF runner 要求配置 run.mode=high_fidelity。")
    if (
        overlay.compression_scale != 1.0
        and cfg.initial_condition.type == "held_endpoint_equilibrium_release"
    ):
        raise ValueError(
            "held_endpoint_equilibrium_release 是双边杆平衡协议；精确仅受拉消融"
            "必须改用 geometric_direct_release、static_equilibrium 或另行封存的完整材料初态。"
        )

    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.revision-staging-", dir=output.parent)
    )
    try:
        model = RevisedHighFidelityModel(cfg, overlay)
        preparation = prepare_initial_state(cfg, model)
        result = simulate_high_fidelity(cfg, model=model, preparation=preparation)
        result.model_id = model.model_id
        result.diagnostics["model_id"] = model.model_id
        result.diagnostics["scientific_revision"] = model.revision_manifest
        _publish_bundle(
            staging,
            cfg=cfg,
            overlay_source=overlay_source,
            overlay=overlay,
            model=model,
            preparation=preparation,
            result=result,
        )
        if output.exists():
            raise FileExistsError(f"运行期间目标目录出现，拒绝覆盖：{output}")
        os.replace(staging, output)
        result.run_directory = output
        return output
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise

"""Standalone and GUI-compatible runner for revised HF model identities.

The runner keeps the inherited HDF5 display layout, but writes a new model
identity, explicit-EI manifest and evidence ceiling. Revised runs never inherit
the original HF production certificate.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
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

from .common_state import load_common_preparation, seal_common_state
from .model_identity import EvidenceAssessment, derive_evidence_assessment
from .overlay import (
    BRANCH_NAMES,
    RevisionOverlay,
    SealedOverlayInput,
    seal_overlay_source,
    verify_sealed_overlay,
)
from .revised_model import RevisedHighFidelityModel
from .scientific_guard import frequency_preview, mechanism_audit

RUN_SCHEMA = "YPS-SCIENTIFIC-REVISION-RUN-1.1"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _live_git_state() -> tuple[str | None, bool]:
    working_directory = Path(__file__).resolve().parent
    try:
        repository = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=working_directory,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
        simulator_root = Path(__file__).resolve().parents[3]
        forward_root = (
            simulator_root
            / "../../01_前向预测数值求解器/y_pendulum_forward_solver"
        ).resolve()
        source_paths = [
            simulator_root.relative_to(repository).as_posix(),
            forward_root.relative_to(repository).as_posix(),
        ]
        # The evidence-only delivery commit cannot contain its own Git hash.
        # Bind evidence to the newest commit that changed either executable
        # source tree; a later commit containing only evidence leaves this
        # source snapshot identity unchanged.
        commit = subprocess.check_output(
            ["git", "log", "-1", "--format=%H", "--", *source_paths],
            cwd=repository,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain=v1"],
            cwd=repository,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None, False
    return (commit or None), not bool(status.strip())


def _evidence_assessment(
    overlay: RevisionOverlay,
    evidence_bundle_path: str | Path | None,
    input_directory: Path,
    *,
    live_commit: str | None,
    live_clean: bool,
    current_input_identity_complete: bool,
    current_contact_guards_enabled: bool,
) -> tuple[EvidenceAssessment, dict[str, Any] | None]:
    if evidence_bundle_path is None:
        return (
            derive_evidence_assessment(
                requested_analysis_level=overlay.requested_analysis_level,
                model_claim_ceiling=overlay.model_claim_ceiling,
                evidence=None,
                source_commit=live_commit,
            ),
            None,
        )
    source = Path(evidence_bundle_path).expanduser().resolve()
    raw = source.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("证据包必须是有效 UTF-8 JSON 对象。") from exc
    if not isinstance(payload, dict):
        raise ValueError("证据包根节点必须是 JSON 对象。")
    digest = _sha256_bytes(raw)
    input_directory.mkdir(parents=True, exist_ok=True)
    sealed = input_directory / "evidence-bundle.raw.json"
    sealed.write_bytes(raw)
    (input_directory / "evidence-bundle.raw.sha256").write_text(
        digest + "\n", encoding="ascii"
    )
    evidence = dict(payload)
    evidence["source_commit_matches"] = (
        live_commit is not None and payload.get("git_commit") == live_commit
    )
    evidence["clean_worktree"] = bool(
        payload.get(
            "clean_worktree",
            payload.get("clean_worktree_at_evidence_generation", False),
        )
        and live_clean
    )
    evidence["input_identity_complete"] = bool(
        payload.get("input_identity_complete") and current_input_identity_complete
    )
    evidence["contact_guards_enabled"] = bool(
        payload.get("contact_guards_enabled") and current_contact_guards_enabled
    )
    assessment = derive_evidence_assessment(
        requested_analysis_level=overlay.requested_analysis_level,
        model_claim_ceiling=overlay.model_claim_ceiling,
        evidence=evidence,
        evidence_bundle_sha256=digest,
        source_commit=live_commit,
    )
    return assessment, {
        "sealed_path": sealed.relative_to(input_directory.parent).as_posix(),
        "sha256": digest,
        "recorded_git_commit": payload.get("git_commit"),
        "live_git_commit": live_commit,
        "live_clean_worktree": live_clean,
        "current_input_identity_complete": current_input_identity_complete,
        "current_contact_guards_enabled": current_contact_guards_enabled,
    }


def _seal_config(source: Path, input_directory: Path) -> tuple[Path, str]:
    raw = source.read_bytes()
    digest = _sha256_bytes(raw)
    sealed = input_directory / "config.raw.yaml"
    sealed.write_bytes(raw)
    (input_directory / "config.raw.sha256").write_text(digest + "\n", encoding="ascii")
    _write_json(
        input_directory / "config-input.json",
        {
            "original_source_path_for_information_only": str(source),
            "sealed_path": sealed.name,
            "sha256": digest,
        },
    )
    return sealed, digest


def _canonical_sha256(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(
            _json_safe(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


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
    evidence: EvidenceAssessment,
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
        **evidence.to_dict(),
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
    sealed_overlay: SealedOverlayInput,
    overlay: RevisionOverlay,
    evidence: EvidenceAssessment,
    evidence_identity: dict[str, Any] | None,
    common_state_identity: dict[str, Any] | None,
    execution_identity: dict[str, Any] | None,
    config_raw_sha256: str,
    initial_condition_sha256: str,
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
    summary = _summary(result, model, overlay, backend_analysis, evidence)

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
            "config_raw_path": "inputs/config.raw.yaml",
            "config_raw_sha256": config_raw_sha256,
            "initial_condition_canonical_sha256": initial_condition_sha256,
            "overlay_raw_path": sealed_overlay.raw_path.relative_to(directory).as_posix(),
            "overlay_raw_sha256": sealed_overlay.raw_sha256,
            "overlay_canonical_path": sealed_overlay.canonical_path.relative_to(
                directory
            ).as_posix(),
            "overlay_canonical_sha256": sealed_overlay.canonical_sha256,
            "model_id": model.model_id,
            "initial_state_semantics": overlay.initial_state_semantics,
            "preparation_mode": preparation.preparation_mode,
            "preparation_residual_inf_N": preparation.residual_inf_N,
            "common_state": common_state_identity,
            "evidence_bundle": evidence_identity,
            "certificate_inheritance": "FORBIDDEN",
        },
    )
    if execution_identity is not None:
        _write_json(directory / "execution_identity.json", execution_identity)
    (directory / "report.md").write_text(
        "\n".join(
            [
                "# Y 形摆审查后修订 HF 运行",
                "",
                f"- 模型身份：`{model.model_id}`",
                "- 后端：`离散柔性杆—有限刚体摆球 HF`",
                "- HF 名称不表示它自动比 FWD 更接近实验。",
                f"- 模型声明上限：`{evidence.model_claim_ceiling.value}`",
                f"- 请求分析等级：`{evidence.requested_analysis_level.value}`",
                f"- 实际证据等级：`{evidence.actual_evidence_level.value}`",
                f"- 证据包 SHA-256：`{evidence.evidence_bundle_sha256 or 'NONE'}`",
                "- 降级原因：`"
                + (", ".join(evidence.downgrade_reasons) or "NONE")
                + "`",
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
    *,
    evidence_bundle_path: str | Path | None = None,
    common_state_path: str | Path | None = None,
    execution_identity: dict[str, Any] | None = None,
    expected_overlay_sha256: str | None = None,
) -> Path:
    config_source = Path(config_path).expanduser().resolve()
    overlay_source = Path(overlay_path).expanduser().resolve()
    output = Path(output_directory).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"修订输出目录已存在，拒绝混写：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    live_commit, live_clean = _live_git_state()
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.revision-staging-", dir=output.parent)
    )
    try:
        sealed_overlay = seal_overlay_source(
            overlay_source,
            staging / "inputs",
            expected_sha256=expected_overlay_sha256,
        )
        verify_sealed_overlay(sealed_overlay)
        overlay = sealed_overlay.overlay
        sealed_config, config_raw_sha256 = _seal_config(
            config_source, staging / "inputs"
        )
        cfg = load_config(sealed_config)
        if cfg.run.mode != "high_fidelity":
            raise ValueError("修订 HF runner 要求配置 run.mode=high_fidelity。")
        if (
            common_state_path is None
            and overlay.compression_scale != 1.0
            and cfg.initial_condition.type == "held_endpoint_equilibrium_release"
        ):
            raise ValueError(
                "held_endpoint_equilibrium_release 是双边杆平衡协议；精确仅受拉消融"
                "必须改用 geometric_direct_release、static_equilibrium 或另行封存的完整材料初态。"
            )
        model = RevisedHighFidelityModel(cfg, overlay)
        common_state_identity: dict[str, Any] | None = None
        sealed_common_state: Path | None = None
        if common_state_path is None:
            preparation = prepare_initial_state(cfg, model)
        else:
            sealed_common_state = seal_common_state(
                common_state_path, staging / "inputs/common-state"
            )
            preparation, common_state_identity = load_common_preparation(
                sealed_common_state, model
            )
            common_state_identity["sealed_manifest_path"] = (
                sealed_common_state.relative_to(staging).as_posix()
            )
        initial_condition_sha256 = _canonical_sha256(
            cfg.initial_condition.model_dump(mode="json")
        )
        current_input_identity_complete = bool(
            config_raw_sha256
            and sealed_overlay.raw_sha256
            and initial_condition_sha256
            and (common_state_path is None or common_state_identity is not None)
        )
        current_contact_guards_enabled = bool(
            overlay.contact_guard_mode != "disabled"
            and cfg.high_fidelity is not None
            and cfg.high_fidelity.contact_guard_enabled
        )
        evidence, evidence_identity = _evidence_assessment(
            overlay,
            evidence_bundle_path,
            staging / "inputs",
            live_commit=live_commit,
            live_clean=live_clean,
            current_input_identity_complete=current_input_identity_complete,
            current_contact_guards_enabled=current_contact_guards_enabled,
        )
        model.revision_manifest.update(evidence.to_dict())
        result = simulate_high_fidelity(cfg, model=model, preparation=preparation)
        verify_sealed_overlay(sealed_overlay)
        if _sha256_bytes(sealed_config.read_bytes()) != config_raw_sha256:
            raise ValueError("封存配置在运行期间发生变化。")
        if sealed_common_state is not None:
            load_common_preparation(sealed_common_state, model)
        result.model_id = model.model_id
        result.diagnostics["model_id"] = model.model_id
        result.diagnostics["scientific_revision"] = model.revision_manifest
        _publish_bundle(
            staging,
            cfg=cfg,
            sealed_overlay=sealed_overlay,
            overlay=overlay,
            evidence=evidence,
            evidence_identity=evidence_identity,
            common_state_identity=common_state_identity,
            execution_identity=execution_identity,
            config_raw_sha256=config_raw_sha256,
            initial_condition_sha256=initial_condition_sha256,
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

"""Generate the M0--M5 model ladder proposed by the independent review."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from .model_identity import EvidenceLevel
from .overlay import (
    BRANCH_NAMES,
    BranchBendingSpecification,
    RevisionOverlay,
    dump_overlay,
    load_overlay,
)

ABLATION_SCHEMA = "YPS-SCIENTIFIC-REVISION-ABLATION-1.1"


def _zero_bending(source: str) -> dict[str, BranchBendingSpecification]:
    return {name: BranchBendingSpecification(0.0, source) for name in BRANCH_NAMES}


def build_ablation_ladder(
    measured_overlay_path: str | Path,
    output_directory: str | Path,
) -> Path:
    measured = load_overlay(measured_overlay_path)
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)

    m1 = replace(
        measured,
        model_id="HF-TENSION-ROD-RIGID-BOB-LIMIT-1.1",
        compression_scale=0.0,
        branch_bending=_zero_bending("M1_zero_EI_controlled_limit"),
        bob_mode="point_limit",
        point_limit_fraction=1.0e-3,
        contact_guard_mode="disabled",
        requested_claim=EvidenceLevel.MODEL_CONSISTENT,
        initial_state_semantics="shared_full_material_state_required",
        notes=(
            "M1：隔离局部离散化；精确仅受拉、EI=0、声明的点摆球极限。",
            "不得继承原 HF 双边杆资格证书。",
        ),
    )
    m2 = replace(
        m1,
        bob_mode="finite",
        contact_guard_mode="inherited",
        notes=("M2：在 M1 基础上恢复有限刚体摆球与偏心连接。",),
    )
    m3 = replace(
        measured,
        model_id="HF-TENSION-ROD-RIGID-BOB-LIMIT-1.1",
        compression_scale=0.0,
        bob_mode="finite",
        contact_guard_mode="inherited",
        requested_claim=EvidenceLevel.MODEL_CONSISTENT,
        initial_state_semantics="shared_full_material_state_required",
        notes=("M3：在 M2 基础上加入独立测量的各支路 EI。",),
    )
    m4 = replace(
        measured,
        model_id="HF-BILATERAL-ROD-RIGID-BOB-1.1",
        compression_scale=1.0,
        bob_mode="finite",
        contact_guard_mode="inherited",
        requested_claim=EvidenceLevel.CODE_VERIFIED,
        initial_state_semantics="backend_prepared_material_state_explicitly_reported",
        notes=("M4：在 M3 基础上加入双边承压与屈曲机制。",),
    )
    m5 = replace(
        m4,
        notes=(
            "M5：完整机制；空气、移动支点、接头与观测器由完整基础配置启用。",
            "M1--M4 应使用关闭外部耗散和固定支点的配对基础配置。",
        ),
    )

    stages: list[dict[str, Any]] = [
        {
            "stage": "M0",
            "label": "FWD baseline",
            "model_id": "FWD-TENSION-CABLE-POINT-BOB-1.1",
            "overlay": None,
            "executable_by_revised_hf_runner": False,
            "isolated_change": "reference",
            "base_config_profile": "fwd_shared_full_material_state",
        }
    ]
    for stage, label, filename, overlay, isolated, profile in (
        (
            "M1",
            "HF unilateral / zero EI / point-bob limit",
            "m1-unilateral-zero-ei-point-limit.yaml",
            m1,
            "local_discretization_and_state_mapping",
            "hf_geometric_direct_no_drag_fixed_support",
        ),
        (
            "M2",
            "M1 + finite rigid bob",
            "m2-unilateral-zero-ei-finite-bob.yaml",
            m2,
            "finite_bob_and_attachment",
            "hf_geometric_direct_no_drag_fixed_support",
        ),
        (
            "M3",
            "M2 + independently measured EI",
            "m3-unilateral-measured-ei-finite-bob.yaml",
            m3,
            "bending_stiffness",
            "hf_geometric_direct_no_drag_fixed_support",
        ),
        (
            "M4",
            "M3 + bilateral compression",
            "m4-bilateral-measured-ei-finite-bob.yaml",
            m4,
            "compression_and_buckling",
            "hf_held_or_shared_state_no_drag_fixed_support",
        ),
        (
            "M5",
            "M4 + full external mechanisms",
            "m5-full-mechanisms.yaml",
            m5,
            "aero_support_joint_observer",
            "hf_full_experiment_configuration",
        ),
    ):
        path = dump_overlay(overlay, output / filename)
        stages.append(
            {
                "stage": stage,
                "label": label,
                "model_id": overlay.model_id,
                "overlay": path.name,
                "executable_by_revised_hf_runner": True,
                "isolated_change": isolated,
                "base_config_profile": profile,
                "effective_claim": overlay.effective_claim.value,
            }
        )

    manifest = {
        "schema_version": ABLATION_SCHEMA,
        "measured_overlay_source": str(Path(measured_overlay_path).expanduser().resolve()),
        "common_initial_state_contract": {
            "required_macro_fields": [
                "support_A_position_and_velocity",
                "support_B_position_and_velocity",
                "junction_position_and_velocity",
                "bob_COM_position_and_velocity",
                "release_time",
            ],
            "required_material_fields_for_strict_comparison": [
                "material_position_along_each_branch",
                "material_velocity_along_each_branch",
                "internal_strain_or_force_state",
            ],
            "warning": "共享宏观 J/摆球状态而由各后端独立平衡绳形，不是同一个完整初值问题。",
        },
        "comparison_policy": {
            "adjacent_stages_only": True,
            "do_not_force_full_model_agreement": True,
            "controlled_limit_expectation": (
                "M1 与 M0 只在状态空间、点摆球和离散极限均匹配时才应收敛。"
            ),
            "full_model_selection": "由封存留出实验数据决定",
        },
        "stages": stages,
    }
    (output / "ablation-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "ablation-run-plan.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": ABLATION_SCHEMA,
                "stages": [
                    {
                        "stage": item["stage"],
                        "base_config_profile": item["base_config_profile"],
                        "overlay": item["overlay"],
                    }
                    for item in stages
                ],
                "metrics": [
                    "bob_trajectory_NRMS",
                    "phase_drift",
                    "amplitude_envelope",
                    "event_signature_and_time",
                    "peak_tension",
                    "tension_impulse",
                    "minimum_signed_axial_force",
                    "bending_energy_fraction",
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return output

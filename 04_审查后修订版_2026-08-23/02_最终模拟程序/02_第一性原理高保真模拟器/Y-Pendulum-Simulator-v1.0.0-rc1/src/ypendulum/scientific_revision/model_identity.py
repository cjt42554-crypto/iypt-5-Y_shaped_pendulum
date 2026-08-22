"""Explicit scientific identities and evidence levels for the revised project."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


class EvidenceLevel(str, Enum):
    MODEL_CONSISTENT = "MODEL_CONSISTENT"
    CODE_VERIFIED = "CODE_VERIFIED"
    NUMERICALLY_QUALIFIED = "NUMERICALLY_QUALIFIED"
    EXPERIMENTALLY_VALIDATED = "EXPERIMENTALLY_VALIDATED"
    PREDICTIVE = "PREDICTIVE"


_EVIDENCE_RANK = {
    EvidenceLevel.MODEL_CONSISTENT: 0,
    EvidenceLevel.CODE_VERIFIED: 1,
    EvidenceLevel.NUMERICALLY_QUALIFIED: 2,
    EvidenceLevel.EXPERIMENTALLY_VALIDATED: 3,
    EvidenceLevel.PREDICTIVE: 4,
}


@dataclass(frozen=True)
class ModelIdentity:
    model_id: str
    display_name_zh: str
    role: str
    axial_constitutive: str
    bending_constitutive: str
    bob_model: str
    compression_scale: float | None
    claim_ceiling: EvidenceLevel
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["claim_ceiling"] = self.claim_ceiling.value
        payload["notes"] = list(self.notes)
        return payload


MODEL_IDENTITIES: Mapping[str, ModelIdentity] = {
    "FWD-TENSION-CABLE-POINT-BOB-1.1": ModelIdentity(
        model_id="FWD-TENSION-CABLE-POINT-BOB-1.1",
        display_name_zh="前向仅受拉连续柔索—点摆球模型",
        role="predictive_forward_model",
        axial_constitutive="unilateral_tension_only_kelvin_voigt_cable",
        bending_constitutive="none",
        bob_model="point_mass",
        compression_scale=0.0,
        claim_ceiling=EvidenceLevel.CODE_VERIFIED,
        notes=(
            "该身份继承原 FWD-CABLE 主方程；实验验证前不得标记为 PREDICTIVE。",
            "失张与重新受拉事件需要独立的空间、时间和输出带宽资格矩阵。",
        ),
    ),
    "HF-BILATERAL-ROD-RIGID-BOB-1.1": ModelIdentity(
        model_id="HF-BILATERAL-ROD-RIGID-BOB-1.1",
        display_name_zh="双边离散柔性杆—有限刚体摆球模型",
        role="mechanism_resolving_rod_model",
        axial_constitutive="bilateral_kelvin_voigt_rod",
        bending_constitutive="independently_specified_EI",
        bob_model="finite_rigid_body_with_eccentric_attachment",
        compression_scale=1.0,
        claim_ceiling=EvidenceLevel.CODE_VERIFIED,
        notes=(
            "该模型可承受压缩并具有弯曲能，不等同于仅受拉绳。",
            "EI 必须作为独立参数给定；不能仅由拉伸 E 与直径自动认定为实验真值。",
        ),
    ),
    "HF-TENSION-ROD-RIGID-BOB-LIMIT-1.1": ModelIdentity(
        model_id="HF-TENSION-ROD-RIGID-BOB-LIMIT-1.1",
        display_name_zh="仅受拉离散杆—有限刚体摆球受控极限模型",
        role="controlled_ablation_limit",
        axial_constitutive="exact_unilateral_tension_only",
        bending_constitutive="independently_specified_EI",
        bob_model="finite_or_declared_point_limit",
        compression_scale=0.0,
        claim_ceiling=EvidenceLevel.MODEL_CONSISTENT,
        notes=(
            "该身份用于消融和受控极限，不继承原 HF 生产资格证书。",
            "当 EI=0 且采用点摆球极限时，可用于隔离离散化与初态映射误差。",
        ),
    ),
    "STRUCTURAL-IDEAL-TORUS-1.1": ModelIdentity(
        model_id="STRUCTURAL-IDEAL-TORUS-1.1",
        display_name_zh="理想张紧环面结构模型",
        role="structural_theory",
        axial_constitutive="inextensible_massless_positive_tension_constraint",
        bending_constitutive="not_applicable",
        bob_model="point_mass",
        compression_scale=None,
        claim_ceiling=EvidenceLevel.NUMERICALLY_QUALIFIED,
        notes=(
            "结构性结论与实验预测资格分离。",
            "有限窗闭合证据不等于不变环面、内共振锁频或连续参数域定理。",
        ),
    ),
}


def get_model_identity(model_id: str) -> ModelIdentity:
    try:
        return MODEL_IDENTITIES[model_id]
    except KeyError as exc:
        known = ", ".join(sorted(MODEL_IDENTITIES))
        raise ValueError(f"未知修订模型身份 {model_id!r}；可选值：{known}") from exc


def parse_evidence_level(value: str | EvidenceLevel) -> EvidenceLevel:
    if isinstance(value, EvidenceLevel):
        return value
    try:
        return EvidenceLevel(str(value))
    except ValueError as exc:
        allowed = ", ".join(item.value for item in EvidenceLevel)
        raise ValueError(f"未知证据等级 {value!r}；可选值：{allowed}") from exc


def lower_evidence_level(
    requested: str | EvidenceLevel,
    ceiling: str | EvidenceLevel,
) -> EvidenceLevel:
    requested_level = parse_evidence_level(requested)
    ceiling_level = parse_evidence_level(ceiling)
    return (
        requested_level
        if _EVIDENCE_RANK[requested_level] <= _EVIDENCE_RANK[ceiling_level]
        else ceiling_level
    )


def evidence_transition_allowed(
    current: str | EvidenceLevel,
    target: str | EvidenceLevel,
    evidence: Mapping[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    current_level = parse_evidence_level(current)
    target_level = parse_evidence_level(target)
    if _EVIDENCE_RANK[target_level] <= _EVIDENCE_RANK[current_level]:
        return True, ()

    missing: list[str] = []
    if _EVIDENCE_RANK[target_level] >= _EVIDENCE_RANK[EvidenceLevel.CODE_VERIFIED]:
        if not bool(evidence.get("tests_passed")):
            missing.append("tests_passed")
        if not bool(evidence.get("energy_and_invariant_checks_passed")):
            missing.append("energy_and_invariant_checks_passed")
    if _EVIDENCE_RANK[target_level] >= _EVIDENCE_RANK[EvidenceLevel.NUMERICALLY_QUALIFIED]:
        if not bool(evidence.get("space_time_output_refinement_passed")):
            missing.append("space_time_output_refinement_passed")
        if not bool(evidence.get("event_signature_stable")):
            missing.append("event_signature_stable")
        if not bool(evidence.get("thresholds_frozen_before_runs")):
            missing.append("thresholds_frozen_before_runs")
    if _EVIDENCE_RANK[target_level] >= _EVIDENCE_RANK[EvidenceLevel.EXPERIMENTALLY_VALIDATED]:
        if not bool(evidence.get("sealed_real_experiment_data")):
            missing.append("sealed_real_experiment_data")
        if not bool(evidence.get("calibration_validation_split")):
            missing.append("calibration_validation_split")
        if not bool(evidence.get("validation_metrics_passed")):
            missing.append("validation_metrics_passed")
    if _EVIDENCE_RANK[target_level] >= _EVIDENCE_RANK[EvidenceLevel.PREDICTIVE]:
        if not bool(evidence.get("held_out_initial_conditions_passed")):
            missing.append("held_out_initial_conditions_passed")
        if not bool(evidence.get("prediction_interval_coverage_passed")):
            missing.append("prediction_interval_coverage_passed")
    return not missing, tuple(missing)

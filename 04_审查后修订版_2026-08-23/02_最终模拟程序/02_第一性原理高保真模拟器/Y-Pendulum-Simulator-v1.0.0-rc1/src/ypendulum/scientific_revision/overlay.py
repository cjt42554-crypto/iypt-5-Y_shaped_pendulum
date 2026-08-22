"""Load and apply explicit scientific-revision overlays to the HF model."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from .model_identity import (
    EvidenceLevel,
    get_model_identity,
    lower_evidence_level,
    parse_evidence_level,
)

OVERLAY_SCHEMA = "YPS-SCIENTIFIC-REVISION-OVERLAY-1.1"
BRANCH_NAMES = ("upper_A", "upper_B", "lower")


@dataclass(frozen=True)
class BranchBendingSpecification:
    value_N_m2: float
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value_N_m2,
            "unit": "N*m^2",
            "source": self.source,
        }


@dataclass(frozen=True)
class RevisionOverlay:
    schema_version: str
    model_id: str
    compression_scale: float
    branch_bending: Mapping[str, BranchBendingSpecification]
    bob_mode: str = "finite"
    point_limit_fraction: float = 1.0e-3
    contact_guard_mode: str = "inherited"
    requested_claim: EvidenceLevel = EvidenceLevel.CODE_VERIFIED
    initial_state_semantics: str = "backend_native"
    notes: tuple[str, ...] = ()

    @property
    def effective_claim(self) -> EvidenceLevel:
        identity = get_model_identity(self.model_id)
        return lower_evidence_level(self.requested_claim, identity.claim_ceiling)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "model_id": self.model_id,
            "compression_scale": self.compression_scale,
            "branch_bending_stiffness": {
                name: self.branch_bending[name].to_dict() for name in BRANCH_NAMES
            },
            "bob_mode": self.bob_mode,
            "point_limit_fraction": self.point_limit_fraction,
            "contact_guard_mode": self.contact_guard_mode,
            "requested_claim": self.requested_claim.value,
            "effective_claim": self.effective_claim.value,
            "initial_state_semantics": self.initial_state_semantics,
            "notes": list(self.notes),
        }


def _load_mapping(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    payload = json.loads(text) if source.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError("修订 overlay 根节点必须是映射。")
    return payload


def _quantity_to_ei(value: Any, *, path: str) -> BranchBendingSpecification:
    if isinstance(value, bool):
        raise ValueError(f"{path} 不能是布尔值。")
    if isinstance(value, (int, float)):
        scalar = float(value)
        source = "unspecified"
    elif isinstance(value, dict):
        unknown = set(value) - {"value", "unit", "source"}
        if unknown:
            raise ValueError(f"{path} 含未知字段：{sorted(unknown)}")
        if "value" not in value:
            raise ValueError(f"{path}.value 必填。")
        scalar = float(value["value"])
        unit = str(value.get("unit", "N*m^2")).replace(" ", "").replace("·", "*")
        aliases = {
            "N*m^2": 1.0,
            "N*m2": 1.0,
            "N*m**2": 1.0,
            "mN*m^2": 1.0e-3,
            "mN*m2": 1.0e-3,
        }
        if unit not in aliases:
            raise ValueError(f"{path}.unit={value.get('unit')!r} 不受支持；使用 N*m^2。")
        scalar *= aliases[unit]
        source = str(value.get("source", "unspecified"))
    else:
        raise ValueError(f"{path} 必须是数值或带 value/unit/source 的映射。")
    if not np.isfinite(scalar) or scalar < 0.0:
        raise ValueError(f"{path} 必须是有限非负 EI。")
    if not source.strip():
        raise ValueError(f"{path}.source 不能为空。")
    return BranchBendingSpecification(scalar, source.strip())


def overlay_from_mapping(payload: Mapping[str, Any]) -> RevisionOverlay:
    allowed = {
        "schema_version",
        "model_id",
        "compression_scale",
        "branch_bending_stiffness",
        "bob_mode",
        "point_limit_fraction",
        "contact_guard_mode",
        "requested_claim",
        "initial_state_semantics",
        "notes",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"修订 overlay 含未知字段：{sorted(unknown)}")
    schema = str(payload.get("schema_version", ""))
    if schema != OVERLAY_SCHEMA:
        raise ValueError(f"overlay schema 必须是 {OVERLAY_SCHEMA!r}，实际为 {schema!r}。")
    model_id = str(payload.get("model_id", ""))
    identity = get_model_identity(model_id)
    compression_scale = float(payload.get("compression_scale", np.nan))
    if not np.isfinite(compression_scale) or not 0.0 <= compression_scale <= 1.0:
        raise ValueError("compression_scale 必须在 [0,1] 内。")
    if identity.compression_scale is not None and compression_scale != identity.compression_scale:
        raise ValueError(
            f"模型身份 {model_id} 要求 compression_scale={identity.compression_scale}，"
            f"实际为 {compression_scale}。"
        )
    raw_bending = payload.get("branch_bending_stiffness")
    if not isinstance(raw_bending, dict) or set(raw_bending) != set(BRANCH_NAMES):
        raise ValueError("branch_bending_stiffness 必须且只能包含 upper_A、upper_B、lower。")
    bending = {
        name: _quantity_to_ei(raw_bending[name], path=f"branch_bending_stiffness.{name}")
        for name in BRANCH_NAMES
    }
    bob_mode = str(payload.get("bob_mode", "finite"))
    if bob_mode not in {"finite", "point_limit"}:
        raise ValueError("bob_mode 必须是 finite 或 point_limit。")
    point_fraction = float(payload.get("point_limit_fraction", 1.0e-3))
    if not np.isfinite(point_fraction) or not 0.0 < point_fraction <= 0.1:
        raise ValueError("point_limit_fraction 必须位于 (0,0.1]。")
    contact_mode = str(payload.get("contact_guard_mode", "inherited"))
    if contact_mode not in {"inherited", "disabled"}:
        raise ValueError("contact_guard_mode 必须是 inherited 或 disabled。")
    if bob_mode == "point_limit" and contact_mode != "disabled":
        raise ValueError("point_limit 必须显式设置 contact_guard_mode: disabled。")
    notes_raw = payload.get("notes", [])
    if isinstance(notes_raw, str):
        notes = (notes_raw,)
    elif isinstance(notes_raw, list) and all(isinstance(item, str) for item in notes_raw):
        notes = tuple(item for item in notes_raw if item.strip())
    else:
        raise ValueError("notes 必须是字符串或字符串列表。")
    return RevisionOverlay(
        schema_version=schema,
        model_id=model_id,
        compression_scale=compression_scale,
        branch_bending=bending,
        bob_mode=bob_mode,
        point_limit_fraction=point_fraction,
        contact_guard_mode=contact_mode,
        requested_claim=parse_evidence_level(
            payload.get("requested_claim", EvidenceLevel.CODE_VERIFIED.value)
        ),
        initial_state_semantics=str(payload.get("initial_state_semantics", "backend_native")),
        notes=notes,
    )


def load_overlay(path: str | Path) -> RevisionOverlay:
    return overlay_from_mapping(_load_mapping(path))


def dump_overlay(overlay: RevisionOverlay, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = overlay.to_dict()
    payload.pop("effective_claim", None)
    target.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return target


def apply_overlay_to_model(model: Any, overlay: RevisionOverlay) -> dict[str, Any]:
    if set(model.branches) != set(BRANCH_NAMES):
        raise ValueError(
            f"HF 分支集合不兼容：{sorted(model.branches)}，预期 {list(BRANCH_NAMES)}。"
        )
    for name in BRANCH_NAMES:
        model.branches[name] = replace(
            model.branches[name], ei=overlay.branch_bending[name].value_N_m2
        )
    model.compression_regularization_scale = overlay.compression_scale
    model.model_id = overlay.model_id

    bob_limit_metadata: dict[str, Any] = {"mode": overlay.bob_mode}
    if overlay.bob_mode == "point_limit":
        factor = overlay.point_limit_fraction
        old_attachment = np.asarray(model.attachment_body, dtype=float).copy()
        new_attachment = old_attachment * factor
        model.reference_bob_position = (
            np.asarray(model.reference_bob_position, dtype=float)
            + old_attachment
            - new_attachment
        )
        model.attachment_body = new_attachment
        model.bob_radius = max(float(model.bob_radius) * factor, 16.0 * float(model.length_guard))
        model.bob_contact_radius = max(
            float(model.bob_contact_radius) * factor,
            16.0 * float(model.length_guard),
        )
        model.bob_inertia = max(float(model.bob_inertia) * factor**2, np.finfo(float).tiny)
        if bool(model.cfg.bob.buoyancy):
            model.bob_buoyancy = (
                -model.air_density
                * (4.0 * np.pi * model.bob_radius**3 / 3.0)
                * model.gravity
            )
        else:
            model.bob_buoyancy = np.zeros(3, dtype=float)
        model.contact_guard_enabled = False
        bob_limit_metadata.update(
            {
                "scale_fraction": factor,
                "attachment_norm_m": float(np.linalg.norm(model.attachment_body)),
                "contact_radius_m": float(model.bob_contact_radius),
                "radius_m": float(model.bob_radius),
                "inertia_kg_m2": float(model.bob_inertia),
            }
        )
    elif overlay.contact_guard_mode == "disabled":
        model.contact_guard_enabled = False

    manifest = {
        "schema_version": OVERLAY_SCHEMA,
        "model_identity": get_model_identity(overlay.model_id).to_dict(),
        "overlay": overlay.to_dict(),
        "effective_claim": overlay.effective_claim.value,
        "actual_branch_EI_N_m2": {
            name: float(model.branches[name].ei) for name in BRANCH_NAMES
        },
        "actual_compression_scale": float(model.compression_regularization_scale),
        "bob_limit": bob_limit_metadata,
        "contact_guard_enabled": bool(model.contact_guard_enabled),
    }
    model.scientific_revision_metadata = manifest
    return manifest


def overlay_with(overlay: RevisionOverlay, **changes: Any) -> RevisionOverlay:
    return replace(overlay, **changes)

"""Load and apply explicit scientific-revision overlays to the HF model."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .model_identity import (
    EvidenceLevel,
    derive_evidence_assessment,
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
    def model_claim_ceiling(self) -> EvidenceLevel:
        return get_model_identity(self.model_id).claim_ceiling

    @property
    def requested_analysis_level(self) -> EvidenceLevel:
        return self.requested_claim

    @property
    def requested_ceiling(self) -> EvidenceLevel:
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
            "requested_analysis_level": self.requested_analysis_level.value,
            "model_claim_ceiling": self.model_claim_ceiling.value,
            "initial_state_semantics": self.initial_state_semantics,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class SealedOverlayInput:
    overlay: RevisionOverlay
    raw_path: Path
    raw_sha256: str
    canonical_path: Path
    canonical_sha256: str
    manifest_path: Path


def _mapping_from_bytes(raw: bytes, *, source_label: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{source_label} 不是有效 UTF-8 overlay。") from exc
    payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError("修订 overlay 根节点必须是映射。")
    return payload


def _load_mapping(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    return _mapping_from_bytes(source.read_bytes(), source_label=str(source))


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.tmp-",
            delete=False,
        ) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


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
        "requested_analysis_level",
        "initial_state_semantics",
        "notes",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"修订 overlay 含未知字段：{sorted(unknown)}")
    if "requested_claim" in payload and "requested_analysis_level" in payload:
        raise ValueError("requested_claim 与 requested_analysis_level 不能同时出现。")
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
            payload.get(
                "requested_analysis_level",
                payload.get("requested_claim", EvidenceLevel.CODE_VERIFIED.value),
            )
        ),
        initial_state_semantics=str(payload.get("initial_state_semantics", "backend_native")),
        notes=notes,
    )


def load_overlay(path: str | Path) -> RevisionOverlay:
    return overlay_from_mapping(_load_mapping(path))


def load_overlay_bytes(raw: bytes, *, source_label: str = "overlay bytes") -> RevisionOverlay:
    return overlay_from_mapping(_mapping_from_bytes(raw, source_label=source_label))


def seal_overlay_bytes(
    raw: bytes,
    input_directory: str | Path,
    *,
    original_source_path_for_information_only: str,
) -> SealedOverlayInput:
    """Seal exactly the bytes already checked by a caller.

    The mutable source path is never opened here.  Both parsing and all later
    subprocess dispatch are bound to ``overlay.raw`` inside the run package.
    """

    overlay = load_overlay_bytes(raw, source_label=original_source_path_for_information_only)
    directory = Path(input_directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=False)
    raw_sha = hashlib.sha256(raw).hexdigest()
    canonical = (
        json.dumps(
            overlay.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    canonical_sha = hashlib.sha256(canonical).hexdigest()
    raw_path = directory / "overlay.raw"
    canonical_path = directory / "overlay.canonical.json"
    _atomic_write(raw_path, raw)
    _atomic_write(directory / "overlay.raw.sha256", f"{raw_sha}\n".encode("ascii"))
    _atomic_write(canonical_path, canonical)
    _atomic_write(
        directory / "overlay.canonical.sha256",
        f"{canonical_sha}\n".encode("ascii"),
    )
    manifest = {
        "schema_version": "YPS-SEALED-OVERLAY-1.0",
        "overlay_raw": raw_path.name,
        "overlay_raw_sha256": raw_sha,
        "overlay_canonical": canonical_path.name,
        "overlay_canonical_sha256": canonical_sha,
        "original_source_path_for_information_only": (
            original_source_path_for_information_only
        ),
        "identity_uses_original_source_path": False,
    }
    manifest_path = directory / "overlay-input.json"
    _atomic_write(
        manifest_path,
        (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8"),
    )
    return SealedOverlayInput(
        overlay=overlay,
        raw_path=raw_path,
        raw_sha256=raw_sha,
        canonical_path=canonical_path,
        canonical_sha256=canonical_sha,
        manifest_path=manifest_path,
    )


def seal_overlay_source(
    source_path: str | Path,
    input_directory: str | Path,
    *,
    expected_sha256: str | None = None,
) -> SealedOverlayInput:
    source = Path(source_path).expanduser().resolve()
    raw = source.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and actual != expected_sha256:
        raise ValueError(
            "科学修订 overlay 在请求封存后发生变化："
            f"expected={expected_sha256}, actual={actual}"
        )
    return seal_overlay_bytes(
        raw,
        input_directory,
        original_source_path_for_information_only=str(source),
    )


def verify_sealed_overlay(sealed: SealedOverlayInput) -> None:
    raw = sealed.raw_path.read_bytes()
    canonical = sealed.canonical_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sealed.raw_sha256:
        raise ValueError("封存 overlay.raw 在运行前发生篡改。")
    if hashlib.sha256(canonical).hexdigest() != sealed.canonical_sha256:
        raise ValueError("封存 overlay.canonical.json 在运行前发生篡改。")
    reparsed = load_overlay_bytes(raw, source_label=str(sealed.raw_path))
    expected = json.loads(canonical.decode("utf-8"))
    if reparsed.to_dict() != expected:
        raise ValueError("封存 overlay 原始字节与规范表示不一致。")


def dump_overlay(overlay: RevisionOverlay, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = overlay.to_dict()
    payload.pop("model_claim_ceiling", None)
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
        **derive_evidence_assessment(
            requested_analysis_level=overlay.requested_analysis_level,
            model_claim_ceiling=overlay.model_claim_ceiling,
            evidence=None,
        ).to_dict(),
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

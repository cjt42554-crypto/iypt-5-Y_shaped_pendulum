"""Portable, hash-bound common physical/material state for M0--M5."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import numpy as np

from ypendulum.config import load_config
from ypendulum.hf.model import rotate_body_vector
from ypendulum.hf.solver import PreparationResult, prepare_initial_state

from .overlay import load_overlay
from .revised_model import RevisedHighFidelityModel

COMMON_STATE_SCHEMA = "YPS-COMMON-MATERIAL-STATE-1.0"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _npy_bytes(values: np.ndarray) -> bytes:
    stream = io.BytesIO()
    np.save(stream, np.asarray(values, dtype=np.float64), allow_pickle=False)
    return stream.getvalue()


def _branch_endpoints(
    model: RevisedHighFidelityModel,
    *,
    branch_name: str,
    particle_positions: np.ndarray,
    particle_velocities: np.ndarray,
    bob_position: np.ndarray,
    bob_velocity: np.ndarray,
    quaternion: np.ndarray,
    angular_velocity: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    branch = model.branches[branch_name]
    junction_position = particle_positions[model.junction_index]
    junction_velocity = particle_velocities[model.junction_index]
    if branch.start_kind == "support_A":
        start, start_velocity, _ = model.support_motion["support_A"].state(0.0)
    elif branch.start_kind == "support_B":
        start, start_velocity, _ = model.support_motion["support_B"].state(0.0)
    else:
        start, start_velocity = junction_position, junction_velocity
    if branch.end_kind == "junction":
        end, end_velocity = junction_position, junction_velocity
    else:
        arm = rotate_body_vector(quaternion, model.attachment_body)
        end = bob_position + arm
        end_velocity = bob_velocity + np.cross(angular_velocity, arm)
    return (
        np.asarray(start, dtype=float),
        np.asarray(start_velocity, dtype=float),
        np.asarray(end, dtype=float),
        np.asarray(end_velocity, dtype=float),
    )


def _polynomial_mapping(
    material_coordinate_m: np.ndarray,
    values: np.ndarray,
) -> tuple[list[list[float]], float]:
    """Build an endpoint-compatible straight projection and report what it loses.

    M0 has no bending degrees of freedom, so fitting a high-order polynomial
    through every HF bead would preserve a representation that M0 does not
    physically own and can introduce oscillatory negative stretch between
    samples.  The degree-one map preserves both shared endpoints exactly; its
    residual against all frozen HF material samples is retained as evidence.
    """

    natural_length = float(material_coordinate_m[-1])
    xi = material_coordinate_m / natural_length
    coefficients = np.vstack((values[0], values[-1] - values[0]))
    reconstructed = values[0] + xi[:, None] * (values[-1] - values[0])
    residual = float(np.max(np.linalg.norm(reconstructed - values, axis=1)))
    return coefficients.tolist(), residual


def create_common_state(
    config_path: str | Path,
    overlay_path: str | Path,
    output_directory: str | Path,
) -> Path:
    """Prepare once, then freeze every HF material degree of freedom."""

    config_source = Path(config_path).expanduser().resolve()
    overlay_source = Path(overlay_path).expanduser().resolve()
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    cfg = load_config(config_source)
    overlay = load_overlay(overlay_source)
    model = RevisedHighFidelityModel(cfg, overlay)
    preparation = prepare_initial_state(cfg, model)
    (
        particle_positions,
        bob_position,
        quaternion,
        particle_velocities,
        bob_velocity,
        angular_velocity,
    ) = model.unpack_state(preparation.state)

    support_payload: dict[str, Any] = {}
    for name in ("support_A", "support_B"):
        position, velocity, _acceleration = model.support_motion[name].state(0.0)
        support_payload[name] = {
            "position_m": np.asarray(position, dtype=float).tolist(),
            "velocity_m_per_s": np.asarray(velocity, dtype=float).tolist(),
        }

    branches: dict[str, Any] = {}
    forward_branches: dict[str, Any] = {}
    maximum_position_residual = 0.0
    maximum_velocity_residual = 0.0
    for name, branch in model.branches.items():
        start, start_velocity, end, end_velocity = _branch_endpoints(
            model,
            branch_name=name,
            particle_positions=particle_positions,
            particle_velocities=particle_velocities,
            bob_position=bob_position,
            bob_velocity=bob_velocity,
            quaternion=quaternion,
            angular_velocity=angular_velocity,
        )
        bead_coordinate = np.cumsum(branch.segment_rest_length)[:-1]
        coordinate = np.concatenate(
            ([0.0], bead_coordinate, [float(np.sum(branch.segment_rest_length))])
        )
        positions = np.vstack(
            (start, particle_positions[branch.bead_indices], end)
        )
        velocities = np.vstack(
            (start_velocity, particle_velocities[branch.bead_indices], end_velocity)
        )
        forward_positions = positions.copy()
        forward_velocities = velocities.copy()
        if name == "lower":
            # FWD's point bob is the lower-cable endpoint, whereas HF uses an
            # eccentric surface attachment.  Make that state-space mapping
            # explicit and retain its residual instead of hiding it.
            forward_positions[-1] = bob_position
            forward_velocities[-1] = bob_velocity
        position_coefficients, position_residual = _polynomial_mapping(
            coordinate, forward_positions
        )
        velocity_coefficients, velocity_residual = _polynomial_mapping(
            coordinate, forward_velocities
        )
        maximum_position_residual = max(maximum_position_residual, position_residual)
        maximum_velocity_residual = max(maximum_velocity_residual, velocity_residual)
        branches[name] = {
            "natural_length_m": float(coordinate[-1]),
            "material_coordinate_m": coordinate.tolist(),
            "position_m": positions.tolist(),
            "velocity_m_per_s": velocities.tolist(),
            "bead_count": int(branch.bead_indices.size),
        }
        forward_branches[name] = {
            "position_polynomial_coefficients": position_coefficients,
            "velocity_polynomial_coefficients": velocity_coefficients,
            "maximum_position_mapping_residual_m": position_residual,
            "maximum_velocity_mapping_residual_m_per_s": velocity_residual,
        }

    canonical = {
        "schema_version": COMMON_STATE_SCHEMA,
        "supports": support_payload,
        "junction": {
            "position_m": particle_positions[model.junction_index].tolist(),
            "velocity_m_per_s": particle_velocities[model.junction_index].tolist(),
        },
        "bob": {
            "center_of_mass_position_m": bob_position.tolist(),
            "orientation_quaternion_wxyz": quaternion.tolist(),
            "linear_velocity_m_per_s": bob_velocity.tolist(),
            "angular_velocity_rad_per_s": angular_velocity.tolist(),
        },
        "branches": branches,
        "mapping": {
            "hf_discrete_state_residual": 0.0,
            "forward_polynomial": forward_branches,
            "maximum_forward_position_residual_m": maximum_position_residual,
            "maximum_forward_velocity_residual_m_per_s": maximum_velocity_residual,
            "interpretation": (
                "M0 uses a deterministic endpoint-compatible degree-one projection; M1--M5 "
                "consume the exact same frozen HF state vector."
            ),
        },
    }
    raw = _npy_bytes(preparation.state)
    canonical_raw = _canonical_bytes(canonical)
    raw_sha = _sha256(raw)
    canonical_sha = _sha256(canonical_raw)
    (output / "common-state.raw.npy").write_bytes(raw)
    (output / "common-state.raw.sha256").write_text(raw_sha + "\n", encoding="ascii")
    (output / "common-state.canonical.json").write_bytes(canonical_raw)
    (output / "common-state.canonical.sha256").write_text(
        canonical_sha + "\n", encoding="ascii"
    )
    manifest = {
        "schema_version": COMMON_STATE_SCHEMA,
        "raw_state": "common-state.raw.npy",
        "raw_state_sha256": raw_sha,
        "canonical_state": "common-state.canonical.json",
        "canonical_state_sha256": canonical_sha,
        "config_sha256": _sha256(config_source.read_bytes()),
        "overlay_sha256": _sha256(overlay_source.read_bytes()),
        "state_size": int(preparation.state.size),
        "preparation_residual_inf_N": float(preparation.residual_inf_N),
        "preparation_mode": preparation.preparation_mode,
        "portable_identity_uses_source_paths": False,
        "mapping_residuals": canonical["mapping"],
    }
    manifest_path = output / "common-state.json"
    manifest_path.write_bytes(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )
    return manifest_path


def _bound_child(parent: Path, name: Any, *, field: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError(f"{field} 必须是非空相对文件名。")
    if len(Path(name).parts) != 1:
        raise ValueError(f"{field} 不得越出共同初态目录。")
    path = (parent / name).resolve()
    if path.parent != parent.resolve() or not path.is_file() or path.is_symlink():
        raise ValueError(f"{field} 不是共同初态目录内的普通文件。")
    return path


def seal_common_state(
    manifest_path: str | Path,
    output_directory: str | Path,
) -> Path:
    """Copy one already hash-verified common-state bundle into a run package."""

    source = Path(manifest_path).expanduser().resolve()
    manifest_raw = source.read_bytes()
    manifest = json.loads(manifest_raw.decode("utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != COMMON_STATE_SCHEMA:
        raise ValueError("共同初态 manifest schema 不兼容。")
    raw_source = _bound_child(
        source.parent, manifest.get("raw_state"), field="raw_state"
    )
    canonical_source = _bound_child(
        source.parent, manifest.get("canonical_state"), field="canonical_state"
    )
    raw = raw_source.read_bytes()
    canonical = canonical_source.read_bytes()
    if _sha256(raw) != manifest.get("raw_state_sha256"):
        raise ValueError("共同初态原始字节 SHA-256 不匹配。")
    if _sha256(canonical) != manifest.get("canonical_state_sha256"):
        raise ValueError("共同初态规范表示 SHA-256 不匹配。")

    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    raw_name = str(manifest["raw_state"])
    canonical_name = str(manifest["canonical_state"])
    (output / raw_name).write_bytes(raw)
    (output / canonical_name).write_bytes(canonical)
    (output / "common-state.raw.sha256").write_text(
        str(manifest["raw_state_sha256"]) + "\n", encoding="ascii"
    )
    (output / "common-state.canonical.sha256").write_text(
        str(manifest["canonical_state_sha256"]) + "\n", encoding="ascii"
    )
    destination = output / "common-state.json"
    destination.write_bytes(manifest_raw)
    (output / "common-state.manifest.sha256").write_text(
        _sha256(manifest_raw) + "\n", encoding="ascii"
    )
    return destination


def load_common_preparation(
    manifest_path: str | Path,
    model: RevisedHighFidelityModel,
) -> tuple[PreparationResult, dict[str, Any]]:
    source = Path(manifest_path).expanduser().resolve()
    manifest = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != COMMON_STATE_SCHEMA:
        raise ValueError("共同初态 manifest schema 不兼容。")
    raw_path = _bound_child(source.parent, manifest.get("raw_state"), field="raw_state")
    canonical_path = _bound_child(
        source.parent, manifest.get("canonical_state"), field="canonical_state"
    )
    raw = raw_path.read_bytes()
    canonical_raw = canonical_path.read_bytes()
    if _sha256(raw) != manifest.get("raw_state_sha256"):
        raise ValueError("共同初态原始字节 SHA-256 不匹配。")
    if _sha256(canonical_raw) != manifest.get("canonical_state_sha256"):
        raise ValueError("共同初态规范表示 SHA-256 不匹配。")
    canonical = json.loads(canonical_raw.decode("utf-8"))
    if canonical.get("schema_version") != COMMON_STATE_SCHEMA:
        raise ValueError("共同初态规范表示 schema 不兼容。")
    state = np.load(io.BytesIO(raw), allow_pickle=False)
    if state.shape != (model.state_size,) or state.dtype != np.float64:
        raise ValueError(
            f"共同初态维数与 HF 模型不匹配：{state.shape} != {(model.state_size,)}。"
        )
    for name, branch in model.branches.items():
        recorded = canonical.get("branches", {}).get(name, {})
        if recorded.get("bead_count") != int(branch.bead_indices.size):
            raise ValueError(f"共同初态 {name} 离散材料点数与当前模型不匹配。")
    preparation = PreparationResult(
        state=np.asarray(state, dtype=float).copy(),
        residual_inf_N=float(manifest["preparation_residual_inf_N"]),
        iterations=0,
        bob_held=False,
        preparation_mode="sealed_common_material_state",
        audit={
            "common_state_raw_sha256": manifest["raw_state_sha256"],
            "common_state_canonical_sha256": manifest["canonical_state_sha256"],
        },
    )
    identity = {
        "manifest_path": source.name,
        "manifest_sha256": _sha256(source.read_bytes()),
        "raw_state_sha256": manifest["raw_state_sha256"],
        "canonical_state_sha256": manifest["canonical_state_sha256"],
        "mapping_residuals": manifest["mapping_residuals"],
    }
    return preparation, identity


def forward_initial_state_from_common(
    manifest_path: str | Path,
) -> tuple[dict[str, Any], dict[str, float]]:
    source = Path(manifest_path).expanduser().resolve()
    manifest = json.loads(source.read_text(encoding="utf-8"))
    canonical_path = _bound_child(
        source.parent, manifest.get("canonical_state"), field="canonical_state"
    )
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    branch_name = {"upper_A": "A", "upper_B": "B", "lower": "lower"}
    branches: dict[str, Any] = {}
    for hf_name, fwd_name in branch_name.items():
        mapping = canonical["mapping"]["forward_polynomial"][hf_name]
        branches[fwd_name] = {
            "position": {
                "kind": "polynomial",
                "coefficients": mapping["position_polynomial_coefficients"],
            },
            "velocity": {
                "kind": "polynomial",
                "coefficients": mapping["velocity_polynomial_coefficients"],
            },
        }
    initial_state = {
        "mode": "DIRECT_STATE",
        "r_J": canonical["junction"]["position_m"],
        "v_J": canonical["junction"]["velocity_m_per_s"],
        "r_m": canonical["bob"]["center_of_mass_position_m"],
        "v_m": canonical["bob"]["linear_velocity_m_per_s"],
        "branches": branches,
    }
    residuals = {
        "maximum_position_residual_m": float(
            canonical["mapping"]["maximum_forward_position_residual_m"]
        ),
        "maximum_velocity_residual_m_per_s": float(
            canonical["mapping"]["maximum_forward_velocity_residual_m_per_s"]
        ),
    }
    return initial_state, residuals

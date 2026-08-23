"""Canonical resolved-configuration and auxiliary-input identities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import SimulationConfig
from .manifest import load_validation_manifest
from .validation import resolved_config_dict


def canonical_payload_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def resolved_config_sha256(config: SimulationConfig) -> str:
    return canonical_payload_sha256(resolved_config_dict(config))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def auxiliary_input_identities(config: SimulationConfig) -> dict[str, dict[str, Any]]:
    """Return every file whose bytes can affect this resolved trajectory."""

    base = (
        Path(config.source_path).resolve().parent
        if config.source_path is not None
        else Path.cwd().resolve()
    )
    values: list[tuple[str, str | None]] = [
        ("run.validation_manifest", config.run.validation_manifest),
        ("initial_condition.state_file", config.initial_condition.state_file),
        ("initial_condition.positions_file", config.initial_condition.positions_file),
        ("initial_condition.velocities_file", config.initial_condition.velocities_file),
    ]
    for support_name in ("A", "B"):
        motion = getattr(config.supports, support_name).motion
        values.append(
            (
                f"supports.{support_name}.motion.table_file",
                None if motion is None else motion.table_file,
            )
        )
    for branch_name in ("upper_A", "upper_B", "lower"):
        values.append(
            (
                f"cables.{branch_name}.table_file",
                getattr(config.cables, branch_name).table_file,
            )
        )
    if config.run.validation_manifest is not None:
        campaign = load_validation_manifest(
            config.run.validation_manifest,
            config_source=config.source_path,
            requested_claim=config.run.claim_level,
        )
        for collection in ("calibration_runs", "validation_runs"):
            for index, record in enumerate(campaign.payload[collection]):
                for field in ("data_path", "result_manifest_path"):
                    artifact = Path(record[field]).expanduser()
                    if not artifact.is_absolute():
                        artifact = campaign.path.parent / artifact
                    values.append(
                        (
                            f"run.validation_manifest.{collection}[{index}].{field}",
                            str(artifact.resolve()),
                        )
                    )
    result: dict[str, dict[str, Any]] = {}
    for field, value in values:
        if value is None:
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = base / path
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Auxiliary input for {field} does not exist: {path}")
        result[field] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
    return result

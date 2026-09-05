"""Exclusive-create, append-only and fsynced P3R5 one-shot attempt ledger."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def _payload(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("P3R5 attempt ledger write made no progress.")
        remaining = remaining[written:]


@dataclass(frozen=True)
class AttemptLedger:
    path: Path

    @classmethod
    def create(cls, path: Path, startup_record: dict[str, Any]) -> AttemptLedger:
        """Create the first durable record; an existing path permanently refuses."""

        target = Path(path)
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o644,
        )
        try:
            _write_all(descriptor, _payload(startup_record))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(target.parent)
        return cls(path=target)

    def append(self, record: dict[str, Any]) -> None:
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW,
        )
        try:
            _write_all(descriptor, _payload(record))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(self.path.parent)

    def checkpoint(self, event: str, **payload: Any) -> None:
        self.append(
            {
                "event": event,
                "timestamp": datetime.now().astimezone().isoformat(timespec="microseconds"),
                **payload,
            }
        )


def startup_record(
    *,
    started_at: str,
    repository_head: str,
    working_tree_status: str,
    expected_protocol_sha256: str,
    expected_implementation_binding_sha256: str,
    expected_holdout_cards_sha256: str,
    expected_acceptance_manifest_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": "YPS-HFV2-P3R5-ATTEMPT-LEDGER-1.0",
        "event": "ATTEMPT_STARTED_BEFORE_HOLDOUT_FILE_OPEN",
        "started_at": started_at,
        "attempt_number": 1,
        "repository_head": repository_head,
        "working_tree_status_before_ledger_create": working_tree_status,
        "expected_sha256_supplied_before_file_open": {
            "contracts/P3R5_FROZEN_PROTOCOL.md": expected_protocol_sha256,
            "contracts/p3r5_implementation_binding.json": (expected_implementation_binding_sha256),
            "contracts/p3r5_holdout_cards.json": expected_holdout_cards_sha256,
            "contracts/p3r5_acceptance_manifest.json": expected_acceptance_manifest_sha256,
        },
        "run_counts": {
            "holdout_file_open": 0,
            "input_assembly": 0,
            "reference_construction": 0,
            "target_admissibility": 0,
            "second_order": 0,
            "manifold_neighborhood": 0,
            "target_freeze": 0,
            "qualification_seed": 0,
        },
        "exception_interrupt_or_partial_output_preserves_ledger": True,
        "self_rerun_forbidden": True,
    }


def load_records(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        records.append(json.loads(line))
    return records


__all__ = ["AttemptLedger", "load_records", "startup_record"]

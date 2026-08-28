from __future__ import annotations

from pathlib import Path

import pytest

import ypendulum_hfv2_p3r5.attempt_ledger as attempt_ledger
from ypendulum_hfv2_p3r5.attempt_ledger import AttemptLedger, load_records, startup_record


def _startup() -> dict[str, object]:
    return startup_record(
        started_at="2026-08-28T00:00:00+08:00",
        repository_head="a" * 40,
        working_tree_status="",
        expected_protocol_sha256="1" * 64,
        expected_implementation_binding_sha256="2" * 64,
        expected_holdout_cards_sha256="3" * 64,
        expected_acceptance_manifest_sha256="4" * 64,
    )


def test_ledger_is_exclusive_create_and_append_only(tmp_path: Path) -> None:
    path = tmp_path / "attempt.jsonl"
    ledger = AttemptLedger.create(path, _startup())
    original = path.read_bytes()
    ledger.append({"event": "CHECKPOINT", "count": 1})
    assert path.read_bytes().startswith(original)
    assert [item["event"] for item in load_records(path)] == [
        "ATTEMPT_STARTED_BEFORE_HOLDOUT_FILE_OPEN",
        "CHECKPOINT",
    ]
    with pytest.raises(FileExistsError):
        AttemptLedger.create(path, _startup())


def test_startup_record_has_zero_counts_and_preservation_contract() -> None:
    record = _startup()
    assert record["attempt_number"] == 1
    assert all(value == 0 for value in record["run_counts"].values())
    assert record["exception_interrupt_or_partial_output_preserves_ledger"] is True
    assert record["self_rerun_forbidden"] is True


def test_ledger_completes_partial_os_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = attempt_ledger.os.write

    def partial_write(descriptor: int, payload: bytes | memoryview) -> int:
        chunk = max(1, len(payload) // 2)
        return real_write(descriptor, payload[:chunk])

    monkeypatch.setattr(attempt_ledger.os, "write", partial_write)
    path = tmp_path / "partial.jsonl"
    ledger = AttemptLedger.create(path, _startup())
    ledger.append({"event": "CHECKPOINT", "count": 1})
    assert [item["event"] for item in load_records(path)] == [
        "ATTEMPT_STARTED_BEFORE_HOLDOUT_FILE_OPEN",
        "CHECKPOINT",
    ]

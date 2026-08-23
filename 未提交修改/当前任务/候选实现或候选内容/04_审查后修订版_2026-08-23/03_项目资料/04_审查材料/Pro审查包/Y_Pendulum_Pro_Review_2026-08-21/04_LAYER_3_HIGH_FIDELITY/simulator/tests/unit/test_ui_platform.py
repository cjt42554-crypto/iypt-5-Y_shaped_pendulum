from __future__ import annotations

import hashlib
import json
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from ypendulum.ui.platform import (
    AnalysisSchema,
    BackendSchema,
    ConfigurationSectionSchema,
    OutputAssessment,
    PersistentJobManager,
    PluginRegistry,
    ProblemSchema,
    RunPlanItem,
    SweepPoint,
    ViewSchema,
    expand_run_plan,
)

CHILD_SCRIPT = r"""
import hashlib
import json
from pathlib import Path
import signal
import sys
import time

config = Path(sys.argv[1])
output = Path(sys.argv[2])
backend = sys.argv[3]
payload = json.loads(config.read_text(encoding="utf-8"))
behavior = payload["behavior"]
if behavior == "ignore_term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if behavior in {"sleep", "ignore_term"}:
    time.sleep(float(payload.get("delay", 30.0)))
if behavior == "fail":
    raise SystemExit(5)
output.mkdir(parents=True, exist_ok=False)
output.joinpath("result.json").write_text(json.dumps({
    "state": "OUT_OF_SCOPE_PREFIX" if behavior == "prefix" else "COMPLETE",
    "backend": backend,
    "case_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
}), encoding="utf-8")
raise SystemExit(3 if behavior == "prefix" else 0)
"""


class FakeAdapter:
    schema = ProblemSchema(
        identifier="fake_problem",
        title="Fake problem",
        description="Lifecycle test adapter",
        configuration_format="JSON",
        backends=(
            BackendSchema("both", "Both", "L2+L3", "dual"),
            BackendSchema("forward", "Forward", "L3", "forward"),
            BackendSchema("high_fidelity", "HF", "L2", "hf"),
        ),
        configuration_sections=(
            ConfigurationSectionSchema("parameters", "Parameters", "test", ("behavior",)),
        ),
        views=(ViewSchema("result", "Result", "json", "result.json"),),
        analyses=(AnalysisSchema("series", "Series", "generic", "test"),),
    )

    def validate_configuration(self, path: Path) -> Mapping[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if set(payload).difference({"behavior", "delay"}):
            raise ValueError("unexpected configuration field")
        if payload.get("behavior") not in {
            "complete",
            "prefix",
            "fail",
            "sleep",
            "ignore_term",
        }:
            raise ValueError("unsupported fake behavior")
        return {
            "case_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "behavior": payload["behavior"],
        }

    def build_command(
        self, config_path: Path, *, backend: str, output_directory: Path
    ) -> Sequence[str]:
        self.schema.backend(backend)
        return [
            sys.executable,
            "-c",
            CHILD_SCRIPT,
            str(config_path),
            str(output_directory),
            backend,
        ]

    def validate_scan_coordinates(
        self, path: Path, coordinates: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.validate_configuration(path)
        return dict(coordinates)

    def inspect_output(self, output_directory: Path) -> OutputAssessment:
        path = output_directory / "result.json"
        if not path.is_file():
            return OutputAssessment("FAILED", "MISSING", "missing output")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["state"] == "COMPLETE":
            return OutputAssessment(
                "COMPLETED",
                "COMPLETE",
                "complete fake delivery",
                evidence={"backend": payload["backend"]},
                accepted_return_codes=(0,),
                input_identity_binding={"case_sha256": payload["case_sha256"]},
                request_binding={"backend": payload["backend"]},
            )
        return OutputAssessment(
            "OUT_OF_SCOPE_PREFIX",
            "OUT_OF_SCOPE_PREFIX",
            "fake prefix",
            evidence={"backend": payload["backend"]},
            accepted_return_codes=(3,),
            input_identity_binding={"case_sha256": payload["case_sha256"]},
            request_binding={"backend": payload["backend"]},
        )

    def read_configuration(self, path: Path) -> Mapping[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def compare_experiment(
        self,
        run_directory: Path,
        experiment_path: Path,
        *,
        output_directory: Path,
    ) -> Mapping[str, Any]:
        return {}


def _config(tmp_path: Path, name: str, behavior: str, delay: float = 0.0) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(
        json.dumps({"behavior": behavior, "delay": delay}, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _manager(tmp_path: Path, *, timeout: float = 0.2) -> PersistentJobManager:
    return PersistentJobManager(
        tmp_path / "state",
        PluginRegistry((FakeAdapter(),)),
        max_parallel=1,
        stop_timeout_seconds=timeout,
    )


def _wait_terminal(
    manager: PersistentJobManager,
    identifier: str,
    timeout: float = 5.0,
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = manager.get(identifier)
        if record.state in {"COMPLETED", "OUT_OF_SCOPE_PREFIX", "FAILED", "STOPPED"}:
            return record
        time.sleep(0.02)
    raise AssertionError(f"job did not terminate; last state={manager.get(identifier).state}")


def test_real_lifecycle_survives_manager_restart_and_records_controls(tmp_path: Path) -> None:
    config = _config(tmp_path, "slow", "sleep", delay=30.0)
    first = _manager(tmp_path)
    identifier = first.submit_plan(
        "fake_problem",
        (RunPlanItem(config, "forward", "slow"),),
        output_parent=tmp_path / "runs",
        batch_label="lifecycle",
    )[0]
    assert first.get(identifier).state == "RUNNING"
    assert first.pause(identifier).state == "PAUSED"

    # A fresh controller has no Popen object, yet binds to the same process only
    # when PID, process group and Linux start ticks all still match.
    recovered = _manager(tmp_path)
    paused = recovered.get(identifier)
    assert paused.state == "PAUSED"
    assert paused.pid is not None
    assert paused.process_start_ticks is not None
    assert recovered.resume(identifier).state == "RUNNING"
    stopped = recovered.stop(identifier)
    assert stopped.state == "STOPPED"
    actions = [event.action for event in stopped.state_history]
    assert actions == ["SUBMIT", "START", "PAUSE", "RESUME", "STOP"]
    assert Path(stopped.output_directory).exists() is False

    persisted = _manager(tmp_path).get(identifier)
    assert persisted.state == "STOPPED"
    assert persisted.command_sha256
    assert persisted.config_identity_submit["raw_file_sha256"]
    assert persisted.config_identity_submit == persisted.config_identity_launch


def test_same_input_dual_backend_is_one_identity_bound_child_job(tmp_path: Path) -> None:
    config = _config(tmp_path, "dual", "complete")
    plan = expand_run_plan(
        mode="same_input_dual",
        base_config=config,
        backend="forward",
    )
    assert len(plan) == 1
    assert plan[0].backend == "both"
    manager = _manager(tmp_path)
    identifier = manager.submit_plan(
        "fake_problem",
        plan,
        output_parent=tmp_path / "runs",
        batch_label="dual",
    )[0]
    record = _wait_terminal(manager, identifier)
    assert record.state == "COMPLETED"
    assert record.return_code == 0
    assert record.output_assessment is not None
    assert record.output_assessment["evidence"]["backend"] == "both"
    assert record.config_identity_submit == record.config_identity_end
    assert manager.audit_output(identifier).scientific_status == "COMPLETE"

    result = Path(record.output_directory) / "result.json"
    payload = json.loads(result.read_text(encoding="utf-8"))
    payload["backend"] = "forward"
    result.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="request binding"):
        manager.audit_output(identifier)


def test_batch_repeat_and_explicit_sweep_expand_without_hidden_mutation(tmp_path: Path) -> None:
    base = _config(tmp_path, "base", "complete")
    other = _config(tmp_path, "other", "complete")
    batch = expand_run_plan(
        mode="batch",
        base_config=base,
        backend="high_fidelity",
        repetitions=2,
        batch_configs=(base, other),
    )
    assert len(batch) == 4
    assert [item.repetition for item in batch] == [1, 2, 1, 2]
    assert all(item.backend == "high_fidelity" for item in batch)

    scan = expand_run_plan(
        mode="sweep",
        base_config=base,
        backend="both",
        repetitions=2,
        sweep_points=(
            SweepPoint("low", base, {"length_m": 0.2}),
            SweepPoint("high", other, {"length_m": 0.3}),
        ),
    )
    assert len(scan) == 4
    assert scan[0].scan_coordinates == {"length_m": 0.2}
    assert scan[2].scan_coordinates == {"length_m": 0.3}
    assert scan[0].config_path == base.resolve()
    assert scan[2].config_path == other.resolve()

    with pytest.raises(ValueError, match="explicit scan coordinates"):
        expand_run_plan(
            mode="sweep",
            base_config=base,
            backend="both",
            sweep_points=(SweepPoint("not-a-scan", base, {}),),
        )


def test_entire_invalid_batch_fails_before_any_process_or_record(tmp_path: Path) -> None:
    valid = _config(tmp_path, "valid", "complete")
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"behavior":"unknown"}', encoding="utf-8")
    manager = _manager(tmp_path)
    with pytest.raises(ValueError, match="unsupported fake behavior"):
        manager.submit_plan(
            "fake_problem",
            (
                RunPlanItem(valid, "forward", "valid"),
                RunPlanItem(invalid, "forward", "invalid"),
            ),
            output_parent=tmp_path / "runs",
            batch_label="invalid-batch",
        )
    assert manager.list_jobs(refresh=False) == []
    assert list((tmp_path / "runs").iterdir()) == []


def test_serial_queue_rechecks_config_identity_before_launch(tmp_path: Path) -> None:
    first_config = _config(tmp_path, "first", "sleep", delay=30.0)
    second_config = _config(tmp_path, "second", "complete")
    manager = _manager(tmp_path)
    first_id, second_id = manager.submit_plan(
        "fake_problem",
        (
            RunPlanItem(first_config, "forward", "first"),
            RunPlanItem(second_config, "forward", "second"),
        ),
        output_parent=tmp_path / "runs",
        batch_label="serial",
    )
    assert manager.get(first_id, refresh=False).state == "RUNNING"
    assert manager.get(second_id, refresh=False).state == "QUEUED"

    second_config.write_text(json.dumps({"behavior": "prefix", "delay": 0.0}), encoding="utf-8")
    assert manager.stop(first_id).state == "STOPPED"
    second = manager.get(second_id)
    assert second.state == "FAILED"
    assert "drifted between submit and launch" in (second.terminal_reason or "")
    assert [event.action for event in second.state_history] == [
        "SUBMIT",
        "START_FAILED",
    ]
    assert not Path(second.output_directory).exists()


def test_failure_prefix_stop_escalation_and_unique_output_contract(tmp_path: Path) -> None:
    manager = _manager(tmp_path, timeout=0.08)
    prefix_config = _config(tmp_path, "prefix", "prefix")
    prefix_id = manager.submit_plan(
        "fake_problem",
        (RunPlanItem(prefix_config, "forward", "prefix"),),
        output_parent=tmp_path / "runs",
        batch_label="same-label",
    )[0]
    prefix = _wait_terminal(manager, prefix_id)
    assert prefix.state == "OUT_OF_SCOPE_PREFIX"
    assert prefix.return_code == 3

    failure_config = _config(tmp_path, "failure", "fail")
    failure_id = manager.submit_plan(
        "fake_problem",
        (RunPlanItem(failure_config, "forward", "failure"),),
        output_parent=tmp_path / "runs",
        batch_label="same-label",
    )[0]
    failure = _wait_terminal(manager, failure_id)
    assert failure.state == "FAILED"
    assert "result verification failure" in (failure.terminal_reason or "")

    stubborn_config = _config(tmp_path, "stubborn", "ignore_term", delay=30.0)
    stubborn_id = manager.submit_plan(
        "fake_problem",
        (RunPlanItem(stubborn_config, "forward", "stubborn"),),
        output_parent=tmp_path / "runs",
        batch_label="same-label",
    )[0]
    assert manager.get(stubborn_id).state == "RUNNING"
    # Give the child enough time to install its SIGTERM handler.
    time.sleep(0.08)
    stopped = manager.stop(stubborn_id)
    assert stopped.state == "STOPPED"
    assert "SIGKILL" in (stopped.terminal_reason or "")

    outputs = {
        prefix.output_directory,
        failure.output_directory,
        stopped.output_directory,
    }
    assert len(outputs) == 3
    assert all("__" in Path(path).name for path in outputs)


def test_persisted_job_tampering_is_detected(tmp_path: Path) -> None:
    config = _config(tmp_path, "complete", "complete")
    manager = _manager(tmp_path)
    identifier = manager.submit_plan(
        "fake_problem",
        (RunPlanItem(config, "forward", "complete"),),
        output_parent=tmp_path / "runs",
        batch_label="tamper",
    )[0]
    _wait_terminal(manager, identifier)
    path = tmp_path / "state" / "jobs" / f"{identifier}.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["record"]["state"] = "FAILED"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="identity mismatch"):
        _manager(tmp_path).get(identifier, refresh=False)

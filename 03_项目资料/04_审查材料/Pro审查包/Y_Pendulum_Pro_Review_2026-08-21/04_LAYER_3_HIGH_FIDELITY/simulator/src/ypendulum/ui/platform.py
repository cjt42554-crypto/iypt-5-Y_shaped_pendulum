"""Persistent, problem-agnostic execution control for the research UI.

The Streamlit process is deliberately not the simulation process.  This module
owns immutable run requests, starts each backend in its own POSIX process
group, records every state transition, and can recover its view of live jobs
after the UI process is restarted.

Nothing in this module knows what a Y pendulum is.  Problem-specific command
construction, input validation and sealed-output interpretation are supplied
through :class:`ProblemAdapter` implementations.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

PLATFORM_SCHEMA = "YPS-RESEARCH-PLATFORM-JOB-1.0"
PLATFORM_ENVELOPE_SCHEMA = "YPS-RESEARCH-PLATFORM-JOB-ENVELOPE-1.0"

ACTIVE_STATES = frozenset({"RUNNING", "PAUSED"})
TERMINAL_STATES = frozenset({"COMPLETED", "OUT_OF_SCOPE_PREFIX", "FAILED", "STOPPED"})
ALL_STATES = frozenset({"QUEUED", *ACTIVE_STATES, *TERMINAL_STATES})


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256_bytes(encoded)


@dataclass(frozen=True)
class BackendSchema:
    identifier: str
    label: str
    model_level: str
    description: str


@dataclass(frozen=True)
class ConfigurationSectionSchema:
    identifier: str
    label: str
    description: str
    payload_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class ViewSchema:
    identifier: str
    label: str
    kind: str
    source: str
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisSchema:
    identifier: str
    label: str
    kind: str
    description: str


@dataclass(frozen=True)
class ProblemSchema:
    identifier: str
    title: str
    description: str
    configuration_format: str
    backends: tuple[BackendSchema, ...]
    configuration_sections: tuple[ConfigurationSectionSchema, ...]
    views: tuple[ViewSchema, ...]
    analyses: tuple[AnalysisSchema, ...]

    def backend(self, identifier: str) -> BackendSchema:
        for backend in self.backends:
            if backend.identifier == identifier:
                return backend
        raise ValueError(f"Problem {self.identifier!r} does not expose backend {identifier!r}.")


@dataclass(frozen=True)
class OutputAssessment:
    """A plugin's interpretation of an immutable output directory."""

    terminal_state: str
    scientific_status: str
    reason: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    accepted_return_codes: tuple[int, ...] = ()
    input_identity_binding: Mapping[str, Any] = field(default_factory=dict)
    request_binding: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.terminal_state not in {
            "COMPLETED",
            "OUT_OF_SCOPE_PREFIX",
            "FAILED",
        }:
            raise ValueError("OutputAssessment has an invalid terminal state.")


class ProblemAdapter(Protocol):
    """Narrow boundary between the reusable platform and a physics package."""

    schema: ProblemSchema

    def validate_configuration(self, path: Path) -> Mapping[str, Any]:
        """Return a JSON-serialisable, identity-bearing validation record."""

    def build_command(
        self, config_path: Path, *, backend: str, output_directory: Path
    ) -> Sequence[str]:
        """Build the child-process command without starting it."""

    def validate_scan_coordinates(
        self, path: Path, coordinates: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Bind declared scan coordinates to values in this configuration."""

    def inspect_output(self, output_directory: Path) -> OutputAssessment:
        """Validate and classify the backend's sealed output."""

    def read_configuration(self, path: Path) -> Mapping[str, Any]:
        """Return structured content for the generic configuration viewer."""

    def compare_experiment(
        self,
        run_directory: Path,
        experiment_path: Path,
        *,
        output_directory: Path,
    ) -> Mapping[str, Any]:
        """Run the problem's explicit observation-contract comparison."""


class PluginRegistry:
    def __init__(self, adapters: Iterable[ProblemAdapter] = ()) -> None:
        self._adapters: dict[str, ProblemAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: ProblemAdapter) -> None:
        identifier = adapter.schema.identifier
        if not identifier or identifier in self._adapters:
            raise ValueError(f"Duplicate or empty problem plugin identifier: {identifier!r}")
        self._adapters[identifier] = adapter

    def get(self, identifier: str) -> ProblemAdapter:
        try:
            return self._adapters[identifier]
        except KeyError as exc:
            raise KeyError(f"Unknown problem plugin: {identifier}") from exc

    def schemas(self) -> tuple[ProblemSchema, ...]:
        return tuple(adapter.schema for adapter in self._adapters.values())


@dataclass(frozen=True)
class SweepPoint:
    label: str
    config_path: Path
    coordinates: Mapping[str, Any]


@dataclass(frozen=True)
class RunPlanItem:
    config_path: Path
    backend: str
    label: str
    repetition: int = 1
    scan_coordinates: Mapping[str, Any] = field(default_factory=dict)


def expand_run_plan(
    *,
    mode: str,
    base_config: str | Path,
    backend: str,
    repetitions: int = 1,
    batch_configs: Sequence[str | Path] = (),
    sweep_points: Sequence[SweepPoint] = (),
) -> tuple[RunPlanItem, ...]:
    """Expand single, repeat, batch, explicit scan and same-input dual plans.

    A scan point carries an explicit, independently valid configuration.  The
    platform never rewrites a physics input behind the adapter's back merely to
    produce a nominal coordinate value.
    """

    allowed = {"single", "repeat", "batch", "sweep", "same_input_dual"}
    if mode not in allowed:
        raise ValueError(f"mode must be one of {sorted(allowed)}")
    if isinstance(repetitions, bool) or int(repetitions) != repetitions or repetitions < 1:
        raise ValueError("repetitions must be a positive integer.")
    repeat_count = int(repetitions)
    base = Path(base_config).expanduser().resolve()

    cases: list[tuple[str, Path, Mapping[str, Any]]]
    selected_backend = "both" if mode == "same_input_dual" else backend
    if mode in {"single", "repeat", "same_input_dual"}:
        cases = [(base.stem, base, {})]
        if mode in {"single", "same_input_dual"} and repeat_count != 1:
            raise ValueError(f"{mode} mode requires repetitions=1; use repeat mode otherwise.")
    elif mode == "batch":
        if not batch_configs:
            raise ValueError("batch mode requires at least one configuration path.")
        cases = [
            (Path(value).stem, Path(value).expanduser().resolve(), {}) for value in batch_configs
        ]
    else:
        if not sweep_points:
            raise ValueError("sweep mode requires at least one explicit sweep point.")
        cases = []
        for point in sweep_points:
            if not point.label.strip():
                raise ValueError("Every sweep point requires a non-empty label.")
            if not point.coordinates:
                raise ValueError("Every sweep point requires explicit scan coordinates.")
            # Fail early if values cannot be represented in durable state.
            canonical_json_sha256(dict(point.coordinates))
            cases.append(
                (
                    point.label.strip(),
                    Path(point.config_path).expanduser().resolve(),
                    dict(point.coordinates),
                )
            )

    items: list[RunPlanItem] = []
    for case_index, (case_label, path, coordinates) in enumerate(cases, start=1):
        for repetition in range(1, repeat_count + 1):
            label = f"{case_index:03d}-{case_label}-r{repetition:03d}"
            items.append(
                RunPlanItem(
                    config_path=path,
                    backend=selected_backend,
                    label=label,
                    repetition=repetition,
                    scan_coordinates=coordinates,
                )
            )
    return tuple(items)


@dataclass
class StateEvent:
    at_utc: str
    action: str
    previous_state: str | None
    next_state: str
    detail: str


@dataclass
class JobRecord:
    schema_version: str
    identifier: str
    plugin_id: str
    batch_id: str
    label: str
    backend: str
    state: str
    command: list[str]
    command_sha256: str
    config_path: str
    config_identity_submit: dict[str, Any]
    config_identity_launch: dict[str, Any] | None
    config_identity_end: dict[str, Any] | None
    output_directory: str
    log_path: str
    submitted_at_utc: str
    started_at_utc: str | None = None
    ended_at_utc: str | None = None
    last_observed_at_utc: str | None = None
    pid: int | None = None
    process_group_id: int | None = None
    process_start_ticks: int | None = None
    return_code: int | None = None
    terminal_reason: str | None = None
    output_assessment: dict[str, Any] | None = None
    repetition: int = 1
    scan_coordinates: dict[str, Any] = field(default_factory=dict)
    revision: int = 0
    state_history: list[StateEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.schema_version != PLATFORM_SCHEMA:
            raise ValueError("Unsupported platform job schema.")
        if self.state not in ALL_STATES:
            raise ValueError(f"Invalid persisted job state: {self.state}")

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> JobRecord:
        data = dict(payload)
        data["state_history"] = [StateEvent(**item) for item in data["state_history"]]
        return cls(**data)

    def row(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "batch_id": self.batch_id,
            "label": self.label,
            "problem": self.plugin_id,
            "backend": self.backend,
            "state": self.state,
            "return_code": self.return_code,
            "pid": self.pid,
            "submitted_at_utc": self.submitted_at_utc,
            "started_at_utc": self.started_at_utc,
            "ended_at_utc": self.ended_at_utc,
            "output_directory": self.output_directory,
            "log_path": self.log_path,
            "command_sha256": self.command_sha256,
            "config_sha256": self.config_identity_submit.get("raw_file_sha256"),
            "scan_coordinates": dict(self.scan_coordinates),
            "terminal_reason": self.terminal_reason,
        }


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")
    return stem[:80] or "run"


def _proc_identity(pid: int) -> tuple[str, int] | None:
    """Return Linux process state and start ticks, robust to spaces in comm."""

    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    close = raw.rfind(")")
    if close < 0:
        return None
    fields = raw[close + 2 :].split()
    if len(fields) <= 19:
        return None
    return fields[0], int(fields[19])


class PersistentJobManager:
    """Durable serial/memory-bounded process queue for a registry of plugins."""

    def __init__(
        self,
        state_directory: str | Path,
        registry: PluginRegistry,
        *,
        max_parallel: int = 1,
        stop_timeout_seconds: float = 5.0,
    ) -> None:
        if isinstance(max_parallel, bool) or max_parallel < 1:
            raise ValueError("max_parallel must be a positive integer.")
        if not (0.0 < float(stop_timeout_seconds) <= 30.0):
            raise ValueError("stop_timeout_seconds must lie in (0, 30].")
        self.state_directory = Path(state_directory).expanduser().resolve()
        self.jobs_directory = self.state_directory / "jobs"
        self.logs_directory = self.state_directory / "logs"
        self.reservations_directory = self.state_directory / "reservations"
        self.lock_path = self.state_directory / ".manager.lock"
        for directory in (
            self.jobs_directory,
            self.logs_directory,
            self.reservations_directory,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.lock_path.touch(exist_ok=True)
        self.registry = registry
        self.max_parallel = int(max_parallel)
        self.stop_timeout_seconds = float(stop_timeout_seconds)
        self._local_processes: dict[str, subprocess.Popen[bytes]] = {}
        self._local_log_handles: dict[str, Any] = {}

    @contextmanager
    def _locked(self):
        with self.lock_path.open("r+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _job_path(self, identifier: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise ValueError("Invalid job identifier.")
        return self.jobs_directory / f"{identifier}.json"

    def _write_record(self, record: JobRecord) -> None:
        record.revision += 1
        payload = record.to_payload()
        envelope = {
            "schema_version": PLATFORM_ENVELOPE_SCHEMA,
            "record": payload,
            "record_sha256": canonical_json_sha256(payload),
        }
        target = self._job_path(record.identifier)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)

    def _read_record(self, path: Path) -> JobRecord:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if envelope.get("schema_version") != PLATFORM_ENVELOPE_SCHEMA:
            raise ValueError(f"Unsupported job envelope: {path}")
        payload = envelope.get("record")
        if not isinstance(payload, dict):
            raise ValueError(f"Job envelope has no record: {path}")
        if envelope.get("record_sha256") != canonical_json_sha256(payload):
            raise ValueError(f"Persisted job identity mismatch: {path}")
        return JobRecord.from_payload(payload)

    def _records(self) -> list[JobRecord]:
        records = [self._read_record(path) for path in sorted(self.jobs_directory.glob("*.json"))]
        return sorted(records, key=lambda item: (item.submitted_at_utc, item.identifier))

    def _get_locked(self, identifier: str) -> JobRecord:
        path = self._job_path(identifier)
        if not path.is_file():
            raise KeyError(identifier)
        return self._read_record(path)

    @staticmethod
    def _transition(
        record: JobRecord,
        next_state: str,
        *,
        action: str,
        detail: str,
    ) -> None:
        if next_state not in ALL_STATES:
            raise ValueError(f"Invalid next state: {next_state}")
        previous = record.state
        allowed = {
            "QUEUED": {"RUNNING", "FAILED", "STOPPED"},
            "RUNNING": {
                "PAUSED",
                "COMPLETED",
                "OUT_OF_SCOPE_PREFIX",
                "FAILED",
                "STOPPED",
            },
            "PAUSED": {
                "RUNNING",
                "COMPLETED",
                "OUT_OF_SCOPE_PREFIX",
                "FAILED",
                "STOPPED",
            },
        }
        if next_state not in allowed.get(previous, set()):
            raise RuntimeError(f"Forbidden job-state transition: {previous} -> {next_state}")
        record.state = next_state
        record.last_observed_at_utc = utc_now()
        record.state_history.append(
            StateEvent(
                at_utc=record.last_observed_at_utc,
                action=action,
                previous_state=previous,
                next_state=next_state,
                detail=detail,
            )
        )

    @staticmethod
    def _identity_with_raw_file(adapter: ProblemAdapter, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(path)
        identity = dict(adapter.validate_configuration(path))
        identity.update(
            {
                "absolute_path": str(path.resolve()),
                "raw_file_sha256": sha256_file(path),
                "raw_file_bytes": path.stat().st_size,
            }
        )
        canonical_json_sha256(identity)
        return identity

    def _reserve_output(self, output: Path, identifier: str) -> None:
        if output.exists():
            raise FileExistsError(f"Output directory already exists: {output}")
        key = sha256_bytes(str(output).encode("utf-8"))
        reservation = self.reservations_directory / f"{key}.json"
        payload = json.dumps(
            {"job_id": identifier, "output_directory": str(output)},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        descriptor = os.open(
            reservation,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(descriptor, payload)
        finally:
            os.close(descriptor)

    def submit_plan(
        self,
        plugin_id: str,
        items: Sequence[RunPlanItem],
        *,
        output_parent: str | Path,
        batch_label: str,
    ) -> tuple[str, ...]:
        """Validate an entire plan before atomically queueing any of its jobs."""

        if not items:
            raise ValueError("A run plan must contain at least one item.")
        adapter = self.registry.get(plugin_id)
        parent = Path(output_parent).expanduser().resolve()
        parent.mkdir(parents=True, exist_ok=True)
        batch_id = uuid.uuid4().hex
        prepared: list[tuple[JobRecord, Path]] = []

        # Phase 1 is read-only.  One invalid point prevents the whole batch from
        # launching, which is essential for interpretable parameter scans.
        for index, item in enumerate(items, start=1):
            adapter.schema.backend(item.backend)
            path = Path(item.config_path).expanduser().resolve()
            identity = self._identity_with_raw_file(adapter, path)
            verified_coordinates = dict(
                adapter.validate_scan_coordinates(path, item.scan_coordinates)
            )
            if canonical_json_sha256(verified_coordinates) != canonical_json_sha256(
                dict(item.scan_coordinates)
            ):
                raise RuntimeError(
                    "Problem adapter changed rather than verified declared scan coordinates."
                )
            identifier = uuid.uuid4().hex
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            stem = _safe_stem(f"{batch_label}-{index:04d}-{item.label}")
            output = parent / f"{stem}__{timestamp}__{identifier[:10]}"
            command = [
                str(value)
                for value in adapter.build_command(
                    path,
                    backend=item.backend,
                    output_directory=output,
                )
            ]
            if not command or any(not value for value in command):
                raise ValueError("Problem adapter returned an invalid empty command.")
            command_hash = canonical_json_sha256(command)
            now = utc_now()
            record = JobRecord(
                schema_version=PLATFORM_SCHEMA,
                identifier=identifier,
                plugin_id=plugin_id,
                batch_id=batch_id,
                label=item.label,
                backend=item.backend,
                state="QUEUED",
                command=command,
                command_sha256=command_hash,
                config_path=str(path),
                config_identity_submit=identity,
                config_identity_launch=None,
                config_identity_end=None,
                output_directory=str(output),
                log_path=str(self.logs_directory / f"{identifier}.log"),
                submitted_at_utc=now,
                repetition=item.repetition,
                scan_coordinates=verified_coordinates,
                state_history=[
                    StateEvent(
                        at_utc=now,
                        action="SUBMIT",
                        previous_state=None,
                        next_state="QUEUED",
                        detail="Immutable command and configuration identity recorded.",
                    )
                ],
            )
            prepared.append((record, output))

        created_records: list[Path] = []
        created_reservations: list[Path] = []
        with self._locked():
            try:
                for record, output in prepared:
                    key = sha256_bytes(str(output).encode("utf-8"))
                    reservation = self.reservations_directory / f"{key}.json"
                    self._reserve_output(output, record.identifier)
                    created_reservations.append(reservation)
                    self._write_record(record)
                    created_records.append(self._job_path(record.identifier))
            except Exception:
                for path in created_records + created_reservations:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                raise
            self._poll_locked(start_queued=True)
        return tuple(record.identifier for record, _output in prepared)

    def _process_alive(self, record: JobRecord) -> bool:
        if record.pid is None or record.process_start_ticks is None:
            return False
        identity = _proc_identity(record.pid)
        if identity is None:
            return False
        state, ticks = identity
        if state == "Z" or ticks != record.process_start_ticks:
            return False
        try:
            return os.getpgid(record.pid) == record.process_group_id
        except (ProcessLookupError, PermissionError, OSError):
            return False

    def _launch_locked(self, record: JobRecord) -> None:
        adapter = self.registry.get(record.plugin_id)
        config = Path(record.config_path)
        try:
            launch_identity = self._identity_with_raw_file(adapter, config)
            if launch_identity != record.config_identity_submit:
                raise RuntimeError("Configuration identity drifted between submit and launch.")
            if canonical_json_sha256(record.command) != record.command_sha256:
                raise RuntimeError("Persisted command identity is inconsistent.")
            output = Path(record.output_directory)
            if output.exists():
                raise FileExistsError(f"Reserved output appeared before process launch: {output}")
            log_path = Path(record.log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handle = log_path.open("ab", buffering=0)
            try:
                process = subprocess.Popen(
                    record.command,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except Exception:
                handle.close()
                raise
            identity = _proc_identity(process.pid)
            if identity is None:
                process.terminate()
                process.wait(timeout=5.0)
                handle.close()
                raise RuntimeError("Unable to bind child process start identity.")
            _state, ticks = identity
            record.config_identity_launch = launch_identity
            record.pid = int(process.pid)
            record.process_group_id = int(os.getpgid(process.pid))
            record.process_start_ticks = ticks
            record.started_at_utc = utc_now()
            self._local_processes[record.identifier] = process
            self._local_log_handles[record.identifier] = handle
            self._transition(
                record,
                "RUNNING",
                action="START",
                detail=f"Started isolated process group {record.process_group_id}.",
            )
        except Exception as exc:
            record.ended_at_utc = utc_now()
            record.terminal_reason = f"launch failure: {type(exc).__name__}: {exc}"
            self._transition(
                record,
                "FAILED",
                action="START_FAILED",
                detail=record.terminal_reason,
            )
        self._write_record(record)

    def _close_local_handle(self, identifier: str) -> None:
        handle = self._local_log_handles.pop(identifier, None)
        if handle is not None:
            handle.close()
        self._local_processes.pop(identifier, None)

    def _finish_locked(self, record: JobRecord, return_code: int | None) -> None:
        adapter = self.registry.get(record.plugin_id)
        record.return_code = return_code
        try:
            record.config_identity_end = self._identity_with_raw_file(
                adapter, Path(record.config_path)
            )
            if record.config_identity_end != record.config_identity_submit:
                raise RuntimeError("Configuration identity drifted during execution.")
            output_directory = Path(record.output_directory)
            if output_directory.resolve() != output_directory:
                raise RuntimeError("Reserved output path was replaced by a symbolic link.")
            assessment = adapter.inspect_output(output_directory)
            record.output_assessment = {
                "terminal_state": assessment.terminal_state,
                "scientific_status": assessment.scientific_status,
                "reason": assessment.reason,
                "evidence": dict(assessment.evidence),
                "accepted_return_codes": list(assessment.accepted_return_codes),
                "input_identity_binding": dict(assessment.input_identity_binding),
                "request_binding": dict(assessment.request_binding),
            }
            mismatched_bindings = {
                key: {
                    "submitted": record.config_identity_submit.get(key),
                    "output": value,
                }
                for key, value in assessment.input_identity_binding.items()
                if record.config_identity_submit.get(key) != value
            }
            if mismatched_bindings:
                raise RuntimeError(
                    f"Sealed output is bound to a different input identity: {mismatched_bindings}"
                )
            request_values = {
                "plugin_id": record.plugin_id,
                "backend": record.backend,
                "command_sha256": record.command_sha256,
            }
            mismatched_request = {
                key: {"requested": request_values.get(key), "output": value}
                for key, value in assessment.request_binding.items()
                if request_values.get(key) != value
            }
            if mismatched_request:
                raise RuntimeError(
                    f"Sealed output is bound to a different run request: {mismatched_request}"
                )
            if return_code is not None and return_code not in assessment.accepted_return_codes:
                raise RuntimeError(
                    f"Process return code {return_code} conflicts with sealed-output "
                    f"status {assessment.scientific_status}."
                )
            next_state = assessment.terminal_state
            reason = assessment.reason
        except Exception as exc:
            next_state = "FAILED"
            reason = f"result verification failure: {type(exc).__name__}: {exc}"
        record.ended_at_utc = utc_now()
        record.terminal_reason = reason
        self._transition(
            record,
            next_state,
            action="PROCESS_EXIT",
            detail=reason,
        )
        self._close_local_handle(record.identifier)
        self._write_record(record)

    def _poll_locked(self, *, start_queued: bool) -> list[JobRecord]:
        records = self._records()
        for record in records:
            if record.state not in ACTIVE_STATES:
                continue
            local = self._local_processes.get(record.identifier)
            if local is not None:
                code = local.poll()
                if code is not None:
                    self._finish_locked(record, int(code))
                else:
                    record.last_observed_at_utc = utc_now()
                    self._write_record(record)
            elif not self._process_alive(record):
                # After a UI restart the OS exit code is no longer recoverable.
                # A sealed, fully verified delivery may still establish the
                # scientific state; absence or corruption fails closed.
                self._finish_locked(record, None)
            else:
                record.last_observed_at_utc = utc_now()
                self._write_record(record)

        records = self._records()
        active_count = sum(record.state in ACTIVE_STATES for record in records)
        if start_queued:
            for record in records:
                if active_count >= self.max_parallel:
                    break
                if record.state == "QUEUED":
                    self._launch_locked(record)
                    refreshed = self._get_locked(record.identifier)
                    if refreshed.state in ACTIVE_STATES:
                        active_count += 1
        return self._records()

    def poll(self) -> list[JobRecord]:
        with self._locked():
            return self._poll_locked(start_queued=True)

    def list_jobs(self, *, refresh: bool = True) -> list[JobRecord]:
        if refresh:
            return self.poll()
        with self._locked():
            return self._records()

    def get(self, identifier: str, *, refresh: bool = True) -> JobRecord:
        if refresh:
            self.poll()
        with self._locked():
            return self._get_locked(identifier)

    def pause(self, identifier: str) -> JobRecord:
        with self._locked():
            self._poll_locked(start_queued=False)
            record = self._get_locked(identifier)
            if record.state != "RUNNING" or not self._process_alive(record):
                raise RuntimeError("Only an identity-verified running job can be paused.")
            assert record.process_group_id is not None
            os.killpg(record.process_group_id, signal.SIGSTOP)
            self._transition(
                record,
                "PAUSED",
                action="PAUSE",
                detail="Sent SIGSTOP to the identity-verified process group.",
            )
            self._write_record(record)
            return record

    def resume(self, identifier: str) -> JobRecord:
        with self._locked():
            self._poll_locked(start_queued=False)
            record = self._get_locked(identifier)
            if record.state != "PAUSED" or not self._process_alive(record):
                raise RuntimeError("Only an identity-verified paused job can be resumed.")
            assert record.process_group_id is not None
            os.killpg(record.process_group_id, signal.SIGCONT)
            self._transition(
                record,
                "RUNNING",
                action="RESUME",
                detail="Sent SIGCONT to the identity-verified process group.",
            )
            self._write_record(record)
            return record

    def stop(self, identifier: str) -> JobRecord:
        with self._locked():
            self._poll_locked(start_queued=False)
            record = self._get_locked(identifier)
            if record.state == "QUEUED":
                record.ended_at_utc = utc_now()
                record.terminal_reason = "Cancelled before process launch."
                self._transition(
                    record,
                    "STOPPED",
                    action="CANCEL_QUEUED",
                    detail=record.terminal_reason,
                )
                self._write_record(record)
                return record
            if record.state not in ACTIVE_STATES or not self._process_alive(record):
                raise RuntimeError("Only a queued or identity-verified active job can be stopped.")
            assert record.process_group_id is not None
            if record.state == "PAUSED":
                os.killpg(record.process_group_id, signal.SIGCONT)
            os.killpg(record.process_group_id, signal.SIGTERM)
            deadline = time.monotonic() + self.stop_timeout_seconds
            local = self._local_processes.get(identifier)
            while self._process_alive(record) and time.monotonic() < deadline:
                if local is not None and local.poll() is not None:
                    break
                time.sleep(0.02)
            forced = False
            if self._process_alive(record):
                os.killpg(record.process_group_id, signal.SIGKILL)
                forced = True
            if local is not None:
                try:
                    local.wait(timeout=max(1.0, self.stop_timeout_seconds))
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError("Stopped process could not be reaped.") from exc
                record.return_code = int(local.returncode)
            record.ended_at_utc = utc_now()
            record.terminal_reason = (
                "Stopped by operator; SIGKILL was required after SIGTERM timeout."
                if forced
                else "Stopped by operator with SIGTERM."
            )
            self._transition(
                record,
                "STOPPED",
                action="STOP",
                detail=record.terminal_reason,
            )
            self._close_local_handle(identifier)
            self._write_record(record)
            self._poll_locked(start_queued=True)
            return self._get_locked(identifier)

    def tail_log(self, identifier: str, *, maximum_bytes: int = 20_000) -> str:
        if maximum_bytes < 1:
            raise ValueError("maximum_bytes must be positive.")
        record = self.get(identifier, refresh=False)
        path = Path(record.log_path)
        if not path.is_file():
            return ""
        data = path.read_bytes()
        return data[-maximum_bytes:].decode("utf-8", errors="replace")

    def audit_output(self, identifier: str) -> OutputAssessment:
        """Re-verify a terminal delivery against its immutable job request.

        Completion is historical state; this method is the current-integrity
        gate used before a UI displays or exports an artifact.
        """

        with self._locked():
            record = self._get_locked(identifier)
            if record.state not in {"COMPLETED", "OUT_OF_SCOPE_PREFIX"}:
                raise RuntimeError("Only completed or explicit-prefix jobs have auditable output.")
            adapter = self.registry.get(record.plugin_id)
            current_identity = self._identity_with_raw_file(adapter, Path(record.config_path))
            if current_identity != record.config_identity_submit:
                raise RuntimeError("Configuration identity drifted after the run.")
            output = Path(record.output_directory)
            if output.resolve() != output:
                raise RuntimeError("Reserved output path was replaced by a symbolic link.")
            assessment = adapter.inspect_output(output)
            if assessment.terminal_state != record.state:
                raise RuntimeError("Current sealed-output status differs from persisted state.")
            if (
                record.return_code is not None
                and record.return_code not in assessment.accepted_return_codes
            ):
                raise RuntimeError("Persisted return code conflicts with current output.")
            for key, value in assessment.input_identity_binding.items():
                if record.config_identity_submit.get(key) != value:
                    raise RuntimeError(f"Current output input binding differs at {key!r}.")
            request_values = {
                "plugin_id": record.plugin_id,
                "backend": record.backend,
                "command_sha256": record.command_sha256,
            }
            for key, value in assessment.request_binding.items():
                if request_values.get(key) != value:
                    raise RuntimeError(f"Current output request binding differs at {key!r}.")
            current_payload = {
                "terminal_state": assessment.terminal_state,
                "scientific_status": assessment.scientific_status,
                "reason": assessment.reason,
                "evidence": dict(assessment.evidence),
                "accepted_return_codes": list(assessment.accepted_return_codes),
                "input_identity_binding": dict(assessment.input_identity_binding),
                "request_binding": dict(assessment.request_binding),
            }
            if record.output_assessment != current_payload:
                raise RuntimeError("Current output evidence differs from persisted assessment.")
            return assessment

"""Single-host subprocess job queue with real POSIX pause/resume/stop controls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import uuid


@dataclass
class ResearchJob:
    command: list[str]
    log_path: Path
    label: str
    identifier: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = "QUEUED"
    return_code: int | None = None
    started_at_utc: str | None = None
    ended_at_utc: str | None = None
    process: subprocess.Popen | None = field(default=None, repr=False)
    _log_handle: object | None = field(default=None, repr=False)

    def start(self) -> None:
        if self.state != "QUEUED":
            raise RuntimeError("Only a queued job can start.")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.log_path.open("wb")
        try:
            self.process = subprocess.Popen(
                self.command,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception:
            handle.close()
            raise
        self._log_handle = handle
        self.state = "RUNNING"
        self.started_at_utc = datetime.now(timezone.utc).isoformat()

    def poll(self) -> str:
        if self.process is None or self.state in {
            "QUEUED",
            "STOPPED",
            "FAILED",
            "COMPLETED",
            "OUT_OF_SCOPE_PREFIX",
        }:
            return self.state
        code = self.process.poll()
        if code is None:
            return self.state
        self.return_code = int(code)
        self.state = "COMPLETED" if code == 0 else "FAILED"
        if "--output" in self.command:
            index = self.command.index("--output")
            if index + 1 < len(self.command):
                root_path = Path(self.command[index + 1]) / "delivery_root.json"
                if root_path.is_file():
                    try:
                        scientific = json.loads(
                            root_path.read_text(encoding="utf-8")
                        ).get("status")
                    except (OSError, ValueError, TypeError):
                        scientific = None
                    if scientific == "OUT_OF_SCOPE_PREFIX":
                        self.state = "OUT_OF_SCOPE_PREFIX"
                    elif scientific != "COMPLETE" or code != 0:
                        self.state = "FAILED"
        self.ended_at_utc = datetime.now(timezone.utc).isoformat()
        if self._log_handle is not None:
            self._log_handle.close()  # type: ignore[union-attr]
            self._log_handle = None
        return self.state

    def pause(self) -> None:
        if self.process is None or self.state != "RUNNING":
            raise RuntimeError("Only a running job can be paused.")
        os.killpg(self.process.pid, signal.SIGSTOP)
        self.state = "PAUSED"

    def resume(self) -> None:
        if self.process is None or self.state != "PAUSED":
            raise RuntimeError("Only a paused job can be resumed.")
        os.killpg(self.process.pid, signal.SIGCONT)
        self.state = "RUNNING"

    def stop(self) -> None:
        if self.process is None or self.state not in {"RUNNING", "PAUSED"}:
            raise RuntimeError("Only a running or paused job can be stopped.")
        if self.state == "PAUSED":
            os.killpg(self.process.pid, signal.SIGCONT)
        os.killpg(self.process.pid, signal.SIGTERM)
        try:
            self.process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=5.0)
        self.return_code = int(self.process.returncode)
        self.state = "STOPPED"
        self.ended_at_utc = datetime.now(timezone.utc).isoformat()
        if self._log_handle is not None:
            self._log_handle.close()  # type: ignore[union-attr]
            self._log_handle = None

    def as_dict(self) -> dict:
        self.poll()
        return {
            "id": self.identifier,
            "label": self.label,
            "state": self.state,
            "return_code": self.return_code,
            "started_at_utc": self.started_at_utc,
            "ended_at_utc": self.ended_at_utc,
            "log_path": str(self.log_path),
            "command": list(self.command),
        }


class SerialJobQueue:
    """A deliberately serial queue so validation jobs do not compete for RAM/CPU."""

    def __init__(self) -> None:
        self.jobs: list[ResearchJob] = []

    def submit(self, job: ResearchJob) -> str:
        self.jobs.append(job)
        self.poll()
        return job.identifier

    def poll(self) -> list[dict]:
        running = False
        for job in self.jobs:
            state = job.poll()
            if state in {"RUNNING", "PAUSED"}:
                running = True
                break
        if not running:
            next_job = next((job for job in self.jobs if job.state == "QUEUED"), None)
            if next_job is not None:
                next_job.start()
        return [job.as_dict() for job in self.jobs]

    def get(self, identifier: str) -> ResearchJob:
        for job in self.jobs:
            if job.identifier == identifier:
                return job
        raise KeyError(identifier)


def unified_job_command(
    case_path: str | Path,
    *,
    backend: str,
    output_directory: str | Path,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "ypendulum.cli",
        "unified-run",
        str(Path(case_path).resolve()),
        "--backend",
        backend,
        "--output",
        str(Path(output_directory).resolve()),
    ]

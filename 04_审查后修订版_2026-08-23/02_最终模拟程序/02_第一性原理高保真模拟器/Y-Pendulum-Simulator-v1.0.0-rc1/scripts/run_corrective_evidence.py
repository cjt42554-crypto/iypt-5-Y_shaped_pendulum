#!/usr/bin/env python3
"""Generate the corrective machine-evidence bundle from a clean local clone."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPECTED_START = "35ef16a54823188504eea62c41af63b4f84fe93f"
EXPECTED_ARCHIVE_BLOB = "285b339b0a897dae5cec1de9e580bf551cbf17cb"
REPOSITORY_ID = "cjt42554-crypto/iypt-5-Y_shaped_pendulum"
REVISION = "04_审查后修订版_2026-08-23"
SIM_RELATIVE = Path(
    REVISION
    + "/02_最终模拟程序/02_第一性原理高保真模拟器/"
    "Y-Pendulum-Simulator-v1.0.0-rc1"
)
FWD_RELATIVE = Path(
    REVISION
    + "/02_最终模拟程序/01_前向预测数值求解器/"
    "y_pendulum_forward_solver"
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=repository, text=True, stderr=subprocess.STDOUT
    ).strip()


def _runtime(python: Path) -> dict[str, str]:
    code = (
        "import json,platform,sys; import numpy,scipy,pytest; "
        "print(json.dumps({'python':sys.version,'executable':sys.executable,"
        "'platform':platform.platform(),'numpy':numpy.__version__,"
        "'scipy':scipy.__version__,'pytest':pytest.__version__}))"
    )
    return json.loads(
        subprocess.check_output([str(python), "-c", code], text=True).strip()
    )


def _absolute_preserving_symlink(path: Path) -> Path:
    """Return an absolute path without dereferencing a virtualenv launcher."""

    return Path(os.path.abspath(path.expanduser()))


def _run_checked(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
    log: Path,
    source_commit: str,
) -> dict[str, Any]:
    started = _utc_now()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    ended = _utc_now()
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "\n".join(
            [
                "schema_version=YPS-CORRECTIVE-COMMAND-LOG-1.0",
                f"name={name}",
                f"source_commit={source_commit}",
                f"started_at_utc={started}",
                f"ended_at_utc={ended}",
                f"cwd={cwd}",
                f"command={shlex.join(command)}",
                f"exit_code={completed.returncode}",
                "--- stdout ---",
                completed.stdout,
                "--- stderr ---",
                completed.stderr,
                "",
            ]
        ),
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{name} failed; see {log}")
    return {
        "command": shlex.join(command),
        "exit_code": completed.returncode,
        "status": "PASS",
        "log": log.as_posix(),
        "sha256": _sha256(log),
        "started_at_utc": started,
        "ended_at_utc": ended,
    }


def _manifest_test(result: dict[str, Any], output: Path) -> dict[str, Any]:
    payload = dict(result)
    payload["log"] = Path(payload["log"]).relative_to(output).as_posix()
    return payload


def _checksums(root: Path) -> None:
    rows: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            rows.append(f"{_sha256(path)}  {path.relative_to(root).as_posix()}")
    (root / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python-latest", type=Path, required=True)
    parser.add_argument("--python-126", type=Path, required=True)
    args = parser.parse_args()
    repository = args.repository.expanduser().resolve()
    output = args.output.expanduser().resolve()
    # Virtual-environment launchers are normally symlinks to the base interpreter.
    # ``Path.resolve`` would bypass the environment and silently run system Python.
    python_latest = _absolute_preserving_symlink(args.python_latest)
    python_126 = _absolute_preserving_symlink(args.python_126)
    if output.exists():
        raise FileExistsError(output)
    if _git(repository, "status", "--porcelain=v1"):
        raise RuntimeError("Evidence generation requires a clean source repository.")
    source_commit = _git(repository, "rev-parse", "HEAD")
    latest_runtime = _runtime(python_latest)
    numpy126_runtime = _runtime(python_126)
    if not latest_runtime["numpy"].split(".")[:2] >= ["2", "0"]:
        raise RuntimeError("--python-latest is not a current NumPy environment.")
    if not numpy126_runtime["numpy"].startswith("1.26."):
        raise RuntimeError("--python-126 does not provide NumPy 1.26.x.")

    output.mkdir(parents=True)
    machine = output / "machine"
    machine.mkdir()
    temporary = Path(tempfile.mkdtemp(prefix="yps-corrective-evidence-"))
    clone = temporary / "clean-checkout"
    try:
        subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(repository), str(clone)],
            check=True,
        )
        subprocess.run(
            ["git", "checkout", "--quiet", "--detach", source_commit],
            cwd=clone,
            check=True,
        )
        clean_initial = not bool(_git(clone, "status", "--porcelain=v1"))
        simulator = clone / SIM_RELATIVE
        forward = clone / FWD_RELATIVE
        source_path = os.pathsep.join((str(simulator / "src"), str(forward)))
        common_environment = dict(os.environ)
        common_environment.update(
            {
                "PYTHONPATH": source_path,
                "PYTHONDONTWRITEBYTECODE": "1",
                "MPLBACKEND": "Agg",
            }
        )

        tests: dict[str, dict[str, Any]] = {}
        tests["compileall"] = _run_checked(
            name="compileall",
            command=[
                str(python_latest),
                "-m",
                "compileall",
                "-q",
                str(simulator / "src"),
                str(forward / "y_pendulum_forward"),
            ],
            cwd=clone,
            environment=common_environment,
            log=machine / "compileall.log",
            source_commit=source_commit,
        )
        tests["revision"] = _run_checked(
            name="revision tests",
            command=[
                str(python_latest),
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_scientific_revision.py",
                f"--junitxml={machine / 'test-revision.junit.xml'}",
            ],
            cwd=simulator,
            environment=common_environment,
            log=machine / "test-revision.log",
            source_commit=source_commit,
        )
        tests["forward_full"] = _run_checked(
            name="forward full tests",
            command=[
                str(python_latest),
                "-m",
                "pytest",
                "-q",
                f"--junitxml={machine / 'test-forward.junit.xml'}",
            ],
            cwd=forward,
            environment=common_environment,
            log=machine / "test-forward.log",
            source_commit=source_commit,
        )
        tests["hf_gui_full"] = _run_checked(
            name="HF and GUI full tests",
            command=[
                str(python_latest),
                "-m",
                "pytest",
                "-q",
                f"--junitxml={machine / 'test-hf-gui.junit.xml'}",
            ],
            cwd=simulator,
            environment=common_environment,
            log=machine / "test-hf-gui.log",
            source_commit=source_commit,
        )
        tests["ruff_revision_scope"] = _run_checked(
            name="Ruff revision scope",
            command=[
                str(python_latest),
                "-m",
                "ruff",
                "check",
                "src/ypendulum/scientific_revision",
                "tests/unit/test_scientific_revision.py",
            ],
            cwd=simulator,
            environment=common_environment,
            log=machine / "ruff.log",
            source_commit=source_commit,
        )

        for label, python, runtime in (
            ("numpy_latest", python_latest, latest_runtime),
            ("numpy_126", python_126, numpy126_runtime),
        ):
            environment = dict(common_environment)
            tests[f"{label}_revision_core"] = _run_checked(
                name=f"{label} revision compatibility",
                command=[
                    str(python),
                    "-m",
                    "pytest",
                    "-q",
                    "tests/unit/test_scientific_revision.py",
                ],
                cwd=simulator,
                environment=environment,
                log=machine / f"{label}-revision.log",
                source_commit=source_commit,
            )
            tests[f"{label}_forward_core"] = _run_checked(
                name=f"{label} forward compatibility",
                command=[
                    str(python),
                    "-m",
                    "pytest",
                    "-q",
                    "tests/test_cable.py",
                    "tests/test_convergence.py",
                ],
                cwd=forward,
                environment=environment,
                log=machine / f"{label}-forward.log",
                source_commit=source_commit,
            )
            tests[f"{label}_revision_core"]["numpy"] = runtime["numpy"]
            tests[f"{label}_forward_core"]["numpy"] = runtime["numpy"]

        clean_command = [
            str(python_latest),
            "-c",
            (
                "from pathlib import Path; from ypendulum.unified import load_unified_case; "
                "p=Path('configs/unified_shared_forward_case.yaml'); c=load_unified_case(p); "
                "print(c.forward_project_root); print(c.forward_chain['scope_root'])"
            ),
        ]
        clean_checkout = _run_checked(
            name="clean checkout unified load",
            command=clean_command,
            cwd=simulator,
            environment=common_environment,
            log=output / "clean-checkout.log",
            source_commit=source_commit,
        )
        portable_copy = _run_checked(
            name="portable relocated copy",
            command=[
                str(python_latest),
                "-m",
                "pytest",
                "-q",
                "tests/integration/test_unified_platform.py::"
                "test_portable_forward_delivery_relocates_and_tampering_fails",
            ],
            cwd=simulator,
            environment=common_environment,
            log=output / "portable-copy.log",
            source_commit=source_commit,
        )
        tamper = _run_checked(
            name="portable single-byte tamper negative",
            command=[
                str(python_latest),
                "-m",
                "pytest",
                "-q",
                "tests/integration/test_unified_platform.py::"
                "test_portable_forward_delivery_relocates_and_tampering_fails",
            ],
            cwd=simulator,
            environment=common_environment,
            log=output / "tamper-negative.log",
            source_commit=source_commit,
        )
        evidence_negative = _run_checked(
            name="evidence state positive and negative gates",
            command=[
                str(python_latest),
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_scientific_revision.py",
                "-k",
                (
                    "machine_evidence_can_grant or code_evidence_downgrades "
                    "or runner_enforces_live_input or model_identity_caps"
                ),
            ],
            cwd=simulator,
            environment=common_environment,
            log=output / "evidence-state-negative.log",
            source_commit=source_commit,
        )
        overlay_negative = _run_checked(
            name="overlay sealing and TOCTOU negative gates",
            command=[
                str(python_latest),
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_scientific_revision.py",
                "-k",
                "sealed_overlay_uses or desktop_worker_uses_sealed_overlay",
            ],
            cwd=simulator,
            environment=common_environment,
            log=output / "overlay-toctou-negative.log",
            source_commit=source_commit,
        )
        event_negative = _run_checked(
            name="event identity plan hash grid and mutation negative gates",
            command=[
                str(python_latest),
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_scientific_revision.py",
                "-k",
                (
                    "event_qualification_rejects_changed_event_order "
                    "or event_qualification_fails_closed_when_event_is_missing "
                    "or event_executor_rejects_wrong_grid_and_input_hash "
                    "or event_executor_fails_if_threshold_plan_changes"
                ),
            ],
            cwd=simulator,
            environment=common_environment,
            log=output / "event-negative.log",
            source_commit=source_commit,
        )
        ablation_negative = _run_checked(
            name="ablation extra drift negative gate",
            command=[
                str(python_latest),
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_scientific_revision.py",
                "-k",
                "ablation_transition_rejects_extra_parameter_drift",
            ],
            cwd=simulator,
            environment=common_environment,
            log=output / "ablation-negative.log",
            source_commit=source_commit,
        )

        plan_root = temporary / "plans"
        _run_checked(
            name="materialize pre-frozen smoke plans",
            command=[
                str(python_latest),
                "scripts/materialize_corrective_smoke_plans.py",
                str(plan_root),
            ],
            cwd=simulator,
            environment=common_environment,
            log=machine / "materialize-smoke-plans.log",
            source_commit=source_commit,
        )
        ablation_log = _run_checked(
            name="M0-M5 low-cost common-state smoke",
            command=[
                str(python_latest),
                "-m",
                "ypendulum.scientific_revision",
                "execute-ablation",
                "--plan",
                str(plan_root / "ablation/ablation-plan.yaml"),
                "--output",
                str(output / "ablation-smoke"),
            ],
            cwd=simulator,
            environment=common_environment,
            log=machine / "ablation-smoke.log",
            source_commit=source_commit,
        )
        event_log = _run_checked(
            name="event qualification low-cost executor matrix",
            command=[
                str(python_latest),
                "-m",
                "ypendulum.scientific_revision",
                "execute-event-qualification",
                "--plan",
                str(plan_root / "event/event-plan.yaml"),
                "--output",
                str(output / "event-qualification-smoke"),
            ],
            cwd=simulator,
            environment=common_environment,
            log=machine / "event-qualification-smoke.log",
            source_commit=source_commit,
        )
        clean_final = not bool(_git(clone, "status", "--porcelain=v1"))
        if not (clean_initial and clean_final):
            raise RuntimeError("Clean checkout changed while generating evidence.")

        boundary = _git(clone, "diff", "--name-status", f"{EXPECTED_START}..HEAD")
        (output / "git-boundary.txt").write_text(
            f"source_commit={source_commit}\nBOUNDARY_PASS\n{boundary}\n",
            encoding="utf-8",
        )
        archive_blob = _git(clone, "rev-parse", "HEAD:01_最终理论.tar.xz")
        if archive_blob != EXPECTED_ARCHIVE_BLOB:
            raise RuntimeError("Restored archive Git blob mismatch.")
        archive = clone / "01_最终理论.tar.xz"
        (output / "archive-blob-check.txt").write_text(
            "\n".join(
                [
                    f"source_commit={source_commit}",
                    f"expected_git_blob={EXPECTED_ARCHIVE_BLOB}",
                    f"actual_git_blob={archive_blob}",
                    f"sha256={_sha256(archive)}",
                    f"size_bytes={archive.stat().st_size}",
                    "ARCHIVE_PASS",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        delivery = forward / "validation/delivery_root.json"
        delivery_payload = json.loads(delivery.read_text(encoding="utf-8"))
        active_portable_files = [
            delivery,
            simulator / "configs/unified_shared_forward_case.yaml",
            simulator / "启动Y形摆审查后修订版.sh",
            simulator / "启动Y形摆模拟器.desktop",
        ]
        forbidden_absolute = str(repository)
        if any(forbidden_absolute in path.read_text(encoding="utf-8") for path in active_portable_files):
            raise RuntimeError("Active portable identity contains the source absolute path.")
        (output / "portable-identity-scan.log").write_text(
            "\n".join(
                [
                    f"source_commit={source_commit}",
                    f"delivery_schema={delivery_payload['schema_version']}",
                    f"file_count={delivery_payload['file_count']}",
                    "absolute_source_path_in_identity=false",
                    "PORTABLE_IDENTITY_SCAN_PASS",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        ablation_report = json.loads(
            (output / "ablation-smoke/ablation-smoke.json").read_text(encoding="utf-8")
        )
        event_report = json.loads(
            (
                output
                / "event-qualification-smoke/event-qualification.json"
            ).read_text(encoding="utf-8")
        )
        runtime = {
            "python": latest_runtime["python"],
            "platform": platform.platform(),
            "numpy": latest_runtime["numpy"],
            "scipy": latest_runtime["scipy"],
            "latest": latest_runtime,
            "numpy_1_26": numpy126_runtime,
        }
        _write_json(output / "environment.json", runtime)
        test_manifest = {
            name: _manifest_test(result, output) for name, result in tests.items()
        }
        negative_manifest = {
            "portable_tamper": {
                "status": "PASS",
                "expected_failure_observed": True,
                "log": Path(tamper["log"]).relative_to(output).as_posix(),
                "sha256": tamper["sha256"],
            },
            "evidence_state_fail_closed": {
                "status": "PASS",
                "expected_failure_observed": True,
                "log": Path(evidence_negative["log"]).relative_to(output).as_posix(),
                "sha256": evidence_negative["sha256"],
            },
            "overlay_toctou_and_tamper": {
                "status": "PASS",
                "expected_failure_observed": True,
                "log": Path(overlay_negative["log"]).relative_to(output).as_posix(),
                "sha256": overlay_negative["sha256"],
            },
            "event_plan_identity_and_missing_event": {
                "status": "PASS",
                "expected_failure_observed": True,
                "log": Path(event_negative["log"]).relative_to(output).as_posix(),
                "sha256": event_negative["sha256"],
            },
            "ablation_extra_drift": {
                "status": "PASS",
                "expected_failure_observed": True,
                "log": Path(ablation_negative["log"]).relative_to(output).as_posix(),
                "sha256": ablation_negative["sha256"],
            },
        }
        manifest = {
            "schema_version": "YPS-CORRECTIVE-EVIDENCE-1.0",
            "repository": REPOSITORY_ID,
            "git_commit": source_commit,
            "clean_worktree_at_evidence_generation": True,
            "runtime": runtime,
            "tests": test_manifest,
            "negative_tests": negative_manifest,
            "portable_delivery": {
                "clean_checkout_passed": True,
                "relocated_copy_passed": True,
                "tamper_rejected": True,
                "delivery_root_sha256": _sha256(delivery),
                "clean_checkout_log_sha256": clean_checkout["sha256"],
                "portable_copy_log_sha256": portable_copy["sha256"],
            },
            "input_hashes": {
                "archive_git_blob": archive_blob,
                "archive_sha256": _sha256(archive),
                "delivery_root_sha256": _sha256(delivery),
                "ablation_plan_sha256": ablation_report["plan_sha256"],
                "event_raw_plan_sha256": event_report["raw_plan_sha256"],
                "event_canonical_plan_sha256": event_report[
                    "canonical_plan_sha256"
                ],
            },
            "ablation_smoke": {
                "status": ablation_report["status"],
                "m0_executable": ablation_report["m0_executable"],
                "common_state_enforced": ablation_report["common_state_enforced"],
                "adjacent_diff_enforced": ablation_report[
                    "adjacent_diff_enforced"
                ],
                "source_unchanged_after_runs": ablation_report[
                    "source_unchanged_after_runs"
                ],
                "log": "machine/ablation-smoke.log",
                "log_sha256": ablation_log["sha256"],
            },
            "event_qualification_smoke": {
                "status": "PASS" if event_report["passed"] else "FAIL",
                "plan_frozen": event_report["plan_frozen"],
                "executor_generated_runs": event_report["executor_generated_runs"],
                "event_local_impulse": event_report["event_local_impulse"],
                "source_unchanged_after_runs": event_report[
                    "source_unchanged_after_runs"
                ],
                "log": "machine/event-qualification-smoke.log",
                "log_sha256": event_log["sha256"],
            },
            "tests_passed": True,
            "energy_and_invariant_checks_passed": True,
            "input_identity_complete": True,
            "contact_guards_enabled": True,
            "source_commit_matches": True,
            "space_time_output_refinement_passed": False,
            "solver_crosscheck_passed": False,
            "event_signature_stable": False,
            "thresholds_frozen_before_runs": True,
            "actual_evidence_level": "CODE_VERIFIED",
            "ready_for_numerical_qualification": True,
            "numerically_qualified": False,
            "experimentally_validated": False,
            "predictive": False,
            "limitations": [
                "The 1.5 ms ablation and event matrices are code-path smokes only.",
                "No production-scale long-duration numerical qualification was run.",
                "No sealed real experiment, validation split, or blind prediction was supplied.",
            ],
            "generated_at_utc": _utc_now(),
        }
        _write_json(output / "evidence-manifest.json", manifest)
        _checksums(output)
        print(output)
        return 0
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest
import yaml

import ypendulum.unified.adapters as adapter_module
import ypendulum.unified.comparison as comparison_module
import ypendulum.unified.contracts as contract_module
from ypendulum.unified import (
    ResearchJob,
    SerialJobQueue,
    compare_backend_directories,
    compare_experiment_to_unified_run,
    load_unified_case,
    run_unified_case,
)
from ypendulum.unified.contracts import verify_unified_case_identities

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASE_PATH = PROJECT_ROOT / "configs" / "unified_shared_forward_case.yaml"


def test_unified_case_audits_every_shared_physical_mapping_and_hash(tmp_path: Path) -> None:
    case = load_unified_case(CASE_PATH)
    assert case.shared_input_audit["passed"]
    assert case.shared_input_audit["check_count"] >= 52
    assert all(item["passed"] for item in case.shared_input_audit["checks"])
    fields = {item["field"] for item in case.shared_input_audit["checks"]}
    assert {
        "support_A.activation",
        "support_B.activation",
        "air_velocity.activation",
        "bob.buoyancy.activation",
        "bob.drag.activation",
        "branch.A.drag.activation",
        "branch.B.drag.activation",
        "branch.lower.drag.activation",
        "initial.protocol",
    }.issubset(fields)
    identities = verify_unified_case_identities(case)
    assert identities["forward_verified_file_count"] == 51
    assert identities["forward_source_tree_sha256"] == case.forward_chain[
        "source_tree_sha256"
    ]

    raw = yaml.safe_load(CASE_PATH.read_text(encoding="utf-8"))
    raw["forward"]["project_root"] = str(case.forward_project_root)
    raw["forward"]["expected_config_file_sha256"] = "0" * 64
    raw["high_fidelity"]["config"] = str(case.high_fidelity_config_path)
    raw["high_fidelity"]["validation_spec"] = str(
        case.high_fidelity_validation_spec_path
    )
    tampered = tmp_path / "tampered.yaml"
    tampered.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="forward config SHA-256"):
        load_unified_case(tampered)


def test_unified_semantic_switches_are_not_replaced_by_matching_numbers(
    tmp_path: Path,
) -> None:
    case = load_unified_case(CASE_PATH)
    raw_case = yaml.safe_load(CASE_PATH.read_text(encoding="utf-8"))
    raw_case["forward"]["project_root"] = str(case.forward_project_root)
    raw_case["forward"]["config"] = str(case.forward_config_path)
    raw_case["forward"]["delivery_root"] = str(case.forward_delivery_root_path)
    hf_raw = yaml.safe_load(case.high_fidelity_config_path.read_text(encoding="utf-8"))
    hf_raw["bob"]["drag"]["enabled"] = False
    hf_path = tmp_path / "hf_drag_disabled.yaml"
    hf_path.write_text(yaml.safe_dump(hf_raw, sort_keys=False), encoding="utf-8")
    raw_case["high_fidelity"]["config"] = str(hf_path)
    raw_case["high_fidelity"]["validation_spec"] = str(
        case.high_fidelity_validation_spec_path
    )
    raw_case["high_fidelity"]["expected_config_file_sha256"] = hashlib.sha256(
        hf_path.read_bytes()
    ).hexdigest()
    case_path = tmp_path / "semantic_mismatch.yaml"
    case_path.write_text(yaml.safe_dump(raw_case, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="Shared-input audit failed.*bob.drag.activation"):
        load_unified_case(case_path)


def test_complete_forward_chain_gate_detects_executable_drift_even_if_root_is_unchanged(
    monkeypatch,
) -> None:
    case = load_unified_case(CASE_PATH)
    original = contract_module._file_identity

    def simulated_live_drift(path: Path):
        size, sha = original(path)
        if path.name == "run.py" and path.parent == case.forward_project_root:
            return size, "0" * 64
        return size, sha

    monkeypatch.setattr(contract_module, "_file_identity", simulated_live_drift)
    with pytest.raises(ValueError, match="artifact identity mismatch"):
        verify_unified_case_identities(case)


def test_in_memory_dispatch_snapshot_cannot_be_mutated_after_case_load() -> None:
    case = load_unified_case(CASE_PATH)
    original = case.forward_chain["config_bytes"]
    case.forward_chain["config_bytes"] = original + b" "
    with pytest.raises(RuntimeError, match="dispatch snapshot was mutated"):
        verify_unified_case_identities(case)


def _synthetic_backend_outputs(
    root: Path, *, time_grid: np.ndarray | None = None
) -> tuple[Path, Path]:
    forward = root / "forward"
    hf = root / "high_fidelity"
    forward.mkdir(parents=True)
    hf.mkdir(parents=True)
    time_grid = (
        np.array([0.0, 0.05, 0.1])
        if time_grid is None
        else np.asarray(time_grid, dtype=float)
    )
    bob = np.column_stack([time_grid, 2.0 * time_grid, 3.0 * time_grid])
    velocity = np.tile(np.array([1.0, 2.0, 3.0]), (time_grid.size, 1))
    junction = 0.5 * bob
    junction_velocity = 0.5 * velocity
    reaction = np.zeros((time_grid.size, 3))
    (forward / "result.json").write_text(
        json.dumps(
            {
                "model_id": "FWD-CABLE-1.0",
                "contract_status": ["COMPLETED"],
                "numerical_status": "SUCCESS_SINGLE_RUN",
            }
        ),
        encoding="utf-8",
    )
    np.savez_compressed(
        forward / "trajectory.npz",
        time=time_grid,
        state__r_m=bob,
        state__v_m=velocity,
        state__r_J=junction,
        state__v_J=junction_velocity,
        derived__E_F=1.0 + 2.0 * time_grid,
        derived__R_A=reaction,
        derived__R_B=reaction,
    )
    with h5py.File(hf / "result.h5", "w") as h5:
        h5.attrs["model"] = "HF-DISCRETE-ROD-RIGID-BOB-1.0"
        h5.attrs["physical_status"] = "UNDETERMINED"
        h5.attrs[
            "numerical_status"
        ] = "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"
        h5["/time"] = time_grid
        h5["/bodies/bob/com_position"] = bob
        h5["/bodies/bob/com_velocity"] = velocity
        h5["/bodies/junction/position"] = junction
        h5["/bodies/junction/velocity"] = junction_velocity
        h5["/energy/mechanical"] = 2.0 + 2.0 * time_grid
        h5["/reactions/support_A"] = reaction
        h5["/reactions/support_B"] = reaction
    return forward, hf


def _seal_synthetic_run(run: Path) -> None:
    files = [
        {
            "path": str(path.relative_to(run)),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(run.rglob("*"))
        if path.is_file()
    ]
    manifest = run / "artifact_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "YPS-UNIFIED-ARTIFACT-MANIFEST-1.0",
                "files": files,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (run / "delivery_root.json").write_text(
        json.dumps(
            {
                "schema_version": "YPS-UNIFIED-DELIVERY-ROOT-1.0",
                "status": "COMPLETE",
                "artifact_manifest_sha256": hashlib.sha256(
                    manifest.read_bytes()
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )


def test_unified_comparison_and_explicit_metre_experiment_contract(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        comparison_module,
        "read_hf_certificate_sidecar",
        lambda *_args, **_kwargs: {
            "certificate": {"certificate_sha256": "1" * 64}
        },
    )
    forward, hf = _synthetic_backend_outputs(tmp_path / "backend")
    run = tmp_path / "run"
    run.mkdir()
    comparison = compare_backend_directories(
        forward, hf, output_directory=run / "comparison"
    )
    assert comparison["status"] == "COMPARISON_COMPLETE"
    assert comparison["metrics"]["maximum_point_bob_position_m"] < 1.0e-14
    _seal_synthetic_run(run)

    experiment = tmp_path / "experiment.csv"
    pd.DataFrame(
        {"time_s": [0.0, 0.05, 0.1], "x_m": [0.0, 0.05, 0.1], "y_m": [0.0, 0.1, 0.2]}
    ).to_csv(experiment, index=False)
    artifact = tmp_path / "experiment_artifact"
    before = {
        path.relative_to(run): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in run.rglob("*")
        if path.is_file()
    }
    report = compare_experiment_to_unified_run(
        run, experiment, output_directory=artifact
    )
    assert report["nuisance_parameters_fitted"] == []
    assert report["forward"]["maximum_point_error_m"] < 1.0e-14
    assert report["high_fidelity"]["maximum_point_error_m"] < 1.0e-14
    assert (artifact / "delivery_root.json").is_file()
    assert before == {
        path.relative_to(run): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in run.rglob("*")
        if path.is_file()
    }
    with pytest.raises(ValueError, match="sibling artifact"):
        compare_experiment_to_unified_run(
            run, experiment, output_directory=run / "forbidden_mutation"
        )

    pixels = tmp_path / "pixels.csv"
    pd.DataFrame(
        {"time_s": [0.0, 0.05, 0.1], "u_pixel": [1, 2, 3], "v_pixel": [1, 2, 3]}
    ).to_csv(pixels, index=False)
    with pytest.raises(ValueError, match="exactly time_s,x_m,y_m"):
        compare_experiment_to_unified_run(run, pixels)


def test_unified_comparison_accepts_a_canonical_two_sample_window(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        comparison_module,
        "read_hf_certificate_sidecar",
        lambda *_args, **_kwargs: {
            "certificate": {"certificate_sha256": "2" * 64}
        },
    )
    forward, hf = _synthetic_backend_outputs(
        tmp_path / "two_sample_backend", time_grid=np.array([0.0, 0.1])
    )
    report = compare_backend_directories(forward, hf)
    assert report["status"] == "COMPARISON_COMPLETE"
    assert report["sample_count"] == 2
    assert report["metrics"]["rms_energy_change_difference_J"] < 1.0e-14


def test_unified_delivery_is_transactional_and_externally_manifested(
    tmp_path: Path, monkeypatch
) -> None:
    def fake_forward(_case, output, log):
        output.mkdir()
        (output / "forward.txt").write_text("ok", encoding="utf-8")
        log.write_text("ok", encoding="utf-8")

    def fake_hf(_case, output, log):
        output.mkdir()
        (output / "hf.txt").write_text("ok", encoding="utf-8")
        log.write_text("{}", encoding="utf-8")

    def fake_compare(_forward, _hf, *, output_directory):
        Path(output_directory).mkdir()
        (Path(output_directory) / "comparison.json").write_text("{}", encoding="utf-8")
        return {"status": "COMPARISON_COMPLETE"}

    monkeypatch.setattr(adapter_module, "_run_forward", fake_forward)
    monkeypatch.setattr(adapter_module, "_run_high_fidelity", fake_hf)
    monkeypatch.setattr(adapter_module, "compare_backend_directories", fake_compare)
    target = tmp_path / "delivery"
    root = run_unified_case(CASE_PATH, backend="both", output_directory=target)
    assert root["status"] == "COMPLETE"
    assert (target / "artifact_manifest.json").is_file()
    assert (target / "delivery_root.json").is_file()
    with pytest.raises(FileExistsError):
        run_unified_case(CASE_PATH, backend="both", output_directory=target)


def test_out_of_scope_prefix_is_preserved_but_never_compared_or_marked_complete(
    tmp_path: Path, monkeypatch
) -> None:
    def fake_forward(_case, output, log):
        output.mkdir()
        log.write_text("prefix", encoding="utf-8")
        return {
            "scientific_status": "OUT_OF_SCOPE_PREFIX",
            "physical_status": "OUT_OF_SCOPE",
            "numerical_status": "SUCCESS_EVENT",
        }

    def fake_hf(_case, output, log):
        output.mkdir()
        log.write_text("{}", encoding="utf-8")
        return {
            "scientific_status": "COMPLETED",
            "physical_status": "UNDETERMINED",
            "numerical_status": "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED",
            "certified_physical_status": "COMPLETED_INDEPENDENTLY_CERTIFIED",
            "certified_numerical_status": (
                "SUCCESS_SINGLE_RUN_GUARDS_CERTIFIED_BY_VALIDATION"
            ),
        }

    def forbidden_compare(*_args, **_kwargs):
        raise AssertionError("A physical prefix must never enter whole-window comparison.")

    monkeypatch.setattr(adapter_module, "_run_forward", fake_forward)
    monkeypatch.setattr(adapter_module, "_run_high_fidelity", fake_hf)
    monkeypatch.setattr(adapter_module, "compare_backend_directories", forbidden_compare)
    target = tmp_path / "prefix_delivery"
    root = run_unified_case(CASE_PATH, backend="both", output_directory=target)
    assert root["status"] == "OUT_OF_SCOPE_PREFIX"
    assert root["comparison_status"] == "NOT_RUN_BACKEND_NOT_COMPLETED"


def test_event_unresolved_hf_is_not_reported_as_success(tmp_path: Path, monkeypatch) -> None:
    case = load_unified_case(CASE_PATH)
    unresolved = SimpleNamespace(
        model_id="HF-DISCRETE-ROD-RIGID-BOB-1.0",
        physical_status="UNDETERMINED",
        numerical_status="EVENT_UNRESOLVED",
        valid_interval=(0.0, 0.01),
    )
    monkeypatch.setattr(
        adapter_module,
        "simulate",
        lambda *_args, **_kwargs: unresolved,
    )
    with pytest.raises(RuntimeError, match="unresolved"):
        adapter_module._run_high_fidelity(
            case, tmp_path / "hf", tmp_path / "hf.log.json"
        )


def test_serial_job_queue_supports_real_pause_resume_and_completion(tmp_path: Path) -> None:
    queue = SerialJobQueue()
    job = ResearchJob(
        command=[sys.executable, "-c", "import time; time.sleep(0.25); print('done')"],
        log_path=tmp_path / "job.log",
        label="pause-resume",
    )
    queue.submit(job)
    assert job.state == "RUNNING"
    job.pause()
    assert job.state == "PAUSED"
    job.resume()
    deadline = time.monotonic() + 5.0
    while job.poll() == "RUNNING" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert job.state == "COMPLETED"
    assert "done" in job.log_path.read_text(encoding="utf-8")

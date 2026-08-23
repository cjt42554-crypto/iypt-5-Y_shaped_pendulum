from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ypendulum.ui.problem_plugins import YPendulumUnifiedAdapter, default_registry


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sealed_run(tmp_path: Path, *, status: str, backend: str = "forward") -> Path:
    run = tmp_path / "run"
    run.mkdir()
    artifact = run / "forward" / "summary.json"
    artifact.parent.mkdir()
    _write_json(artifact, {"status": "COMPLETED"})
    files = [
        {
            "path": "forward/summary.json",
            "bytes": artifact.stat().st_size,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }
    ]
    if backend == "both" and status == "COMPLETE":
        comparison = run / "comparison"
        comparison.mkdir()
        (comparison / "comparison_series.npz").write_bytes(b"npz-placeholder")
        _write_json(comparison / "comparison.json", {"status": "COMPLETE"})
        for name in ("comparison_series.npz", "comparison.json"):
            path = comparison / name
            files.append(
                {
                    "path": f"comparison/{name}",
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    manifest = run / "artifact_manifest.json"
    _write_json(
        manifest,
        {
            "schema_version": "YPS-UNIFIED-ARTIFACT-MANIFEST-1.0",
            "files": files,
        },
    )
    _write_json(
        run / "delivery_root.json",
        {
            "schema_version": "YPS-UNIFIED-DELIVERY-ROOT-1.0",
            "status": status,
            "backend_selection": backend,
            "case_sha256": "case-hash",
            "source_hash_start_sha256": "source-hash",
            "source_hash_end_sha256": "source-hash",
            "source_stable_during_run": True,
            "input_identity_start": {"input": "hash"},
            "input_identity_end": {"input": "hash"},
            "input_identity_stable_during_run": True,
            "shared_input_audit_passed": True,
            "backend_outcomes": (
                {"forward": {}, "high_fidelity": {}} if backend == "both" else {backend: {}}
            ),
            "comparison_status": "COMPLETE"
            if backend == "both" and status == "COMPLETE"
            else "NOT_REQUESTED",
            "artifact_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        },
    )
    return run


def test_problem_plugin_schema_covers_all_required_generic_capabilities() -> None:
    registry = default_registry()
    schema = registry.get("iypt_2027_y_pendulum").schema
    assert {backend.identifier for backend in schema.backends} == {
        "both",
        "forward",
        "high_fidelity",
    }
    assert {section.identifier for section in schema.configuration_sections} == {
        "problem",
        "model",
        "parameters",
        "initial_conditions",
        "boundary_conditions",
        "external_driving",
        "solver",
        "interval",
    }
    assert {view.kind for view in schema.views} >= {
        "npz_trajectory3d",
        "npz_vector_timeseries",
        "hdf5_polyline_snapshot",
        "hdf5_group_timeseries",
        "json",
    }
    geometry = next(view for view in schema.views if view.identifier == "hf_geometry")
    scalar_templates = geometry.options["scalar_templates"]
    assert scalar_templates["tension"].endswith("/segments/tension")
    assert scalar_templates["signed axial force (compression < 0)"].endswith(
        "/segments/signed_axial_force"
    )
    assert {analysis.identifier for analysis in schema.analyses} == {
        "time_series",
        "phase",
        "spectrum",
        "parameter_dependence",
        "error",
        "conservation",
        "model_difference",
        "experiment",
        "import_export",
    }


def test_generic_controller_source_contains_no_y_pendulum_physics() -> None:
    source = (
        (Path(__file__).resolve().parents[2] / "src" / "ypendulum" / "ui" / "platform.py")
        .read_text(encoding="utf-8")
        .lower()
    )
    for forbidden in (
        "y-pendulum",
        "fwd-cable",
        "discrete-rod",
        "upper_a",
        "junction_position",
        "bob_position",
    ):
        assert forbidden not in source


@pytest.mark.parametrize(
    ("status", "expected_state", "codes"),
    [
        ("COMPLETE", "COMPLETED", (0,)),
        ("OUT_OF_SCOPE_PREFIX", "OUT_OF_SCOPE_PREFIX", (3,)),
    ],
)
def test_y_plugin_verifies_sealed_manifest_and_tri_state(
    tmp_path: Path,
    status: str,
    expected_state: str,
    codes: tuple[int, ...],
) -> None:
    run = _sealed_run(tmp_path, status=status)
    assessment = YPendulumUnifiedAdapter().inspect_output(run)
    assert assessment.terminal_state == expected_state
    assert assessment.accepted_return_codes == codes
    assert assessment.input_identity_binding == {"case_sha256": "case-hash"}
    assert assessment.evidence["artifact_count"] == 1


def test_y_plugin_requires_dual_comparison_and_detects_artifact_tampering(tmp_path: Path) -> None:
    adapter = YPendulumUnifiedAdapter()
    run = _sealed_run(tmp_path, status="COMPLETE", backend="both")
    assert adapter.inspect_output(run).terminal_state == "COMPLETED"
    (run / "comparison" / "comparison.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="identity mismatch"):
        adapter.inspect_output(run)


def test_y_plugin_fails_closed_without_sealed_delivery(tmp_path: Path) -> None:
    assessment = YPendulumUnifiedAdapter().inspect_output(tmp_path / "absent")
    assert assessment.terminal_state == "FAILED"
    assert assessment.accepted_return_codes == ()


def test_y_plugin_binds_scan_coordinate_to_audited_shared_input() -> None:
    project = Path(__file__).resolve().parents[2]
    case = project / "configs" / "unified_shared_forward_case.yaml"
    adapter = YPendulumUnifiedAdapter()
    assert adapter.validate_scan_coordinates(case, {"comparison_horizon": 0.12}) == {
        "comparison_horizon": 0.12
    }
    with pytest.raises(ValueError, match="does not match"):
        adapter.validate_scan_coordinates(case, {"comparison_horizon": 0.13})
    with pytest.raises(ValueError, match="not a verified shared-input field"):
        adapter.validate_scan_coordinates(case, {"invented_parameter": 1.0})

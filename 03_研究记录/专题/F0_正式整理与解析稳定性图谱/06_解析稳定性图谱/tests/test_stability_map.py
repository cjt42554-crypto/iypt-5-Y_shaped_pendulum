from __future__ import annotations

import ast
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from p3r5_stability_map import build_stability_map
from p3r5_stability_map.map import (
    INTERPOLANT_EVIDENCE,
    OBSERVED_EVIDENCE,
    _extract_modes,
    _load_bound_json,
    evaluate_descriptor_at_scale,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[3]
CONFIG = PROJECT_ROOT / "config.json"


def _run(tmp_path: Path):
    return build_stability_map(CONFIG, REPOSITORY_ROOT, tmp_path)


def test_analysis_imports_no_contact_or_p3r_implementation() -> None:
    source = PROJECT_ROOT / "src" / "p3r5_stability_map" / "map.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any("ypendulum" in name for name in imports)
    assert not any("contact" in name for name in imports)
    assert not any("p3r" in name for name in imports)
    text = source.read_text(encoding="utf-8")
    assert text.index('matplotlib.use("Agg"') < text.index("import matplotlib.pyplot")


def test_frozen_modes_have_lateral_translation_roll_negative_direction(
    tmp_path: Path,
) -> None:
    payload = _run(tmp_path)
    assert payload["qualification_run"] is False
    assert payload["new_contact_cards_generated"] == 0
    assert payload["contact_solver_runs"] == 0
    assert len(payload["observed_modes"]) == 4
    assert payload["evidence_layers"]["observed"] == {
        "evidence_class": OBSERVED_EVIDENCE,
        "point_count": 4,
        "geometry_scales": [0.74, 0.86, 0.99, 1.62],
        "interpretation": "directly extracted from four hash-bound frozen cards",
    }
    for row in payload["observed_modes"]:
        assert row["evidence_class"] == OBSERVED_EVIDENCE
        assert row["lambda_negative"] < 0.0
        assert row["lambda_rotation_y"] > 0.0
        assert row["lambda_stiff"] > 0.0
        assert 0.0 < abs(row["negative_y_normalized"]) < 1.0
        assert 0.0 < abs(row["negative_rotation_x"]) < 1.0
        assert (
            abs(row["lambda_negative"] - row["independent_negative_curvature"])
            <= row["curvature_crosscheck_error"]
        )


def test_descriptive_interpolant_has_bounded_signature_as_interpolant_property(
    tmp_path: Path,
) -> None:
    payload = _run(tmp_path)
    parameterization = payload["parameterization"]
    assert parameterization["domain"] == [0.74, 1.62]
    assert parameterization["extrapolation_allowed"] is False
    assert parameterization["evidence_class"] == INTERPOLANT_EVIDENCE
    assert parameterization["zero_crossing_status"] == (
        "INTERPOLANT_HAS_NO_ZERO_CROSSING_ON_OBSERVED_CONVEX_HULL"
    )
    for row in payload["descriptive_interpolant"]:
        assert row["evidence_class"] == INTERPOLANT_EVIDENCE
        matrix = np.asarray(row["H_reduced_descriptor"], dtype=float)
        eigenvalues = np.linalg.eigvalsh(matrix)
        assert eigenvalues[0] < 0.0 < eigenvalues[1]
        assert row["interpolant_spectral_signature"] == "(-,+,+)"
        np.testing.assert_allclose(matrix, matrix.T, rtol=0.0, atol=2.0e-15)


def test_descriptor_rejects_every_extrapolation_request() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    cards = _load_bound_json(REPOSITORY_ROOT, config["source_cards"])
    metrics = _load_bound_json(REPOSITORY_ROOT, config["source_metrics"])
    modes = _extract_modes(config, cards, metrics)
    assert evaluate_descriptor_at_scale(modes, 0.74)["evidence_class"] == INTERPOLANT_EVIDENCE
    assert evaluate_descriptor_at_scale(modes, 1.62)["evidence_class"] == INTERPOLANT_EVIDENCE
    for outside in (0.739999999, 1.620000001, -1.0, float("inf")):
        with pytest.raises(ValueError, match="NO_EXTRAPOLATION|finite"):
            evaluate_descriptor_at_scale(modes, outside)


def test_json_csv_plot_and_report_keep_evidence_layers_distinct(tmp_path: Path) -> None:
    output = tmp_path / "layered"
    payload = _run(output)
    assert OBSERVED_EVIDENCE in {row["evidence_class"] for row in payload["observed_modes"]}
    assert INTERPOLANT_EVIDENCE in {
        row["evidence_class"] for row in payload["descriptive_interpolant"]
    }
    with (output / "observed_modes.csv").open(encoding="utf-8", newline="") as handle:
        observed_rows = list(csv.DictReader(handle))
    with (output / "parameterized_map.csv").open(encoding="utf-8", newline="") as handle:
        interpolant_rows = list(csv.DictReader(handle))
    assert {row["evidence_class"] for row in observed_rows} == {OBSERVED_EVIDENCE}
    assert {row["evidence_class"] for row in interpolant_rows} == {INTERPOLANT_EVIDENCE}
    svg = (output / "reduced_hessian_stability_map.svg").read_text(encoding="utf-8")
    assert "descriptive PCHIP" in svg
    assert "No extrapolation" in svg
    report = (PROJECT_ROOT / "P3R5_NEGATIVE_CURVATURE_AND_REDUCED_HESSIAN_MAP.md").read_text(
        encoding="utf-8"
    )
    assert OBSERVED_EVIDENCE in report
    assert INTERPOLANT_EVIDENCE in report


def test_analysis_source_and_runtime_are_bound(tmp_path: Path) -> None:
    payload = _run(tmp_path)
    source_manifest = payload["analysis_source_manifest"]
    assert source_manifest["schema"] == (
        "YPS-P3R5-STABILITY-MAP-ANALYSIS-SOURCE-MANIFEST-1.0"
    )
    assert {row["path"] for row in source_manifest["entries"]} == {
        "config.json",
        "pyproject.toml",
        "src/p3r5_stability_map/__init__.py",
        "src/p3r5_stability_map/__main__.py",
        "src/p3r5_stability_map/map.py",
    }
    runtime = payload["runtime_identity"]
    assert runtime["schema"] == "YPS-P3R5-STABILITY-MAP-RUNTIME-IDENTITY-1.0"
    assert set(runtime["packages"]) == {"matplotlib", "numpy", "scipy"}
    canonical_runtime = json.dumps(
        runtime,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert payload["runtime_identity_sha256"] == hashlib.sha256(
        canonical_runtime
    ).hexdigest()
    manifest = json.loads(
        (tmp_path / "artifact_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["determinism_scope"] == (
        "BYTE_IDENTICAL_WITHIN_RECORDED_ANALYSIS_SOURCE_CONFIG_AND_RUNTIME"
    )
    assert manifest["runtime_identity_sha256"] == payload["runtime_identity_sha256"]


def test_artifacts_are_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _run(first)
    _run(second)
    for relative in (
        "stability_map.json",
        "observed_modes.csv",
        "parameterized_map.csv",
        "reduced_hessian_stability_map.svg",
        "reduced_hessian_stability_map.png",
        "artifact_manifest.json",
    ):
        assert (first / relative).read_bytes() == (second / relative).read_bytes()

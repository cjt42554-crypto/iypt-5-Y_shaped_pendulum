from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

from p3r5_stability_map import build_stability_map

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


def test_frozen_modes_have_lateral_translation_roll_negative_direction(
    tmp_path: Path,
) -> None:
    payload = _run(tmp_path)
    assert payload["qualification_run"] is False
    assert payload["new_contact_cards_generated"] == 0
    assert payload["contact_solver_runs"] == 0
    assert len(payload["observed_modes"]) == 4
    for row in payload["observed_modes"]:
        assert row["lambda_negative"] < 0.0
        assert row["lambda_rotation_y"] > 0.0
        assert row["lambda_stiff"] > 0.0
        assert 0.0 < abs(row["negative_y_normalized"]) < 1.0
        assert 0.0 < abs(row["negative_rotation_x"]) < 1.0
        assert (
            abs(row["lambda_negative"] - row["independent_negative_curvature"])
            <= row["curvature_crosscheck_error"]
        )


def test_parameterized_reduced_hessian_has_bounded_saddle_signature(
    tmp_path: Path,
) -> None:
    payload = _run(tmp_path)
    parameterization = payload["parameterization"]
    assert parameterization["domain"] == [0.74, 1.62]
    assert parameterization["extrapolation_allowed"] is False
    assert parameterization["zero_crossing_status"] == (
        "NO_ZERO_CROSSING_OBSERVED_IN_FROZEN_DEVELOPMENT_INTERVAL"
    )
    for row in payload["interpolated_map"]:
        matrix = np.asarray(row["H_reduced"], dtype=float)
        eigenvalues = np.linalg.eigvalsh(matrix)
        assert eigenvalues[0] < 0.0 < eigenvalues[1]
        assert row["spectral_signature"] == "(-,+,+)"
        np.testing.assert_allclose(matrix, matrix.T, rtol=0.0, atol=2.0e-15)


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

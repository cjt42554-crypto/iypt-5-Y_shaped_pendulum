from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from ypendulum.ui.desktop_config import DESKTOP_RESULT_SCHEMA
from ypendulum.ui.desktop_results import (
    common_geometry_time_window,
    compare_plot_data,
    endpoint_chord_paths,
    geometry_paths_at_time,
    geometry_scene_cube,
    interpolate_vector_series,
    load_desktop_output,
    load_forward_result,
    load_hf_result,
    trajectory_plane_square,
    write_comparison_artifacts,
)


def _write_forward(root: Path) -> None:
    root.mkdir()
    time = np.linspace(0.0, 0.004, 5)
    bob = np.column_stack((0.01 * time, 0.02 * time, 0.6 + 0.03 * time))
    junction = np.column_stack((np.zeros(5), np.zeros(5), 0.25 + 0.001 * time))
    nodes = np.stack(
        [
            np.array(
                [
                    [-0.15, 0.0, 0.0],
                    [0.15, 0.0, 0.0],
                    junction[index],
                    bob[index],
                ]
            )
            for index in range(5)
        ]
    )
    arrays: dict[str, np.ndarray] = {
        "time": time,
        "state__r_m": bob,
        "state__v_m": np.gradient(bob, time, axis=0),
        "state__r_J": junction,
        "state__v_J": np.gradient(junction, time, axis=0),
        "state__node_positions": nodes,
        "derived__E_F": np.linspace(1.0, 1.01, 5),
        "derived__T_kin": np.linspace(0.0, 0.01, 5),
        "derived__V_g": np.ones(5),
        "derived__V_buoy": np.zeros(5),
        "derived__V_ax": np.linspace(0.0, 1.0e-4, 5),
        "derived__D_ax": np.linspace(0.0, 0.1, 5),
        "derived__P_base": np.zeros(5),
        "diagnostics__sampled_guard_component_series__LAMBDA_MIN:A:element:0": np.ones(5),
    }
    for branch in ("A", "B", "lower"):
        arrays[f"derived__branches__{branch}__N_elastic"] = np.full((5, 1), 2.0)
        arrays[f"derived__branches__{branch}__N_viscous"] = np.full((5, 1), -0.25)
        arrays[f"derived__branches__{branch}__N"] = np.full((5, 1), 1.75)
    np.savez_compressed(root / "trajectory.npz", **arrays)
    (root / "result.json").write_text(
        json.dumps(
            {
                "contract_status": ["COMPLETED"],
                "numerical_status": "SUCCESS_SINGLE_RUN",
                "events": [],
                "metadata": {"branch_nodes": {"A": [0, 2], "B": [1, 2], "lower": [2, 3]}},
            }
        ),
        encoding="utf-8",
    )
    (root / "config.snapshot.json").write_text(
        json.dumps({"physical": {"bob_volume": 4.0 / 3.0 * np.pi * 0.02**3}}),
        encoding="utf-8",
    )


def _write_hf(root: Path) -> None:
    root.mkdir()
    time = np.linspace(0.0, 0.004, 5)
    bob = np.column_stack((0.0105 * time, 0.019 * time, 0.6 + 0.031 * time))
    junction = np.column_stack((np.zeros(5), np.zeros(5), 0.25 + 0.0011 * time))
    with h5py.File(root / "result.h5", "w") as h5:
        h5.create_dataset("time", data=time)
        h5.create_dataset("bodies/bob/com_position", data=bob)
        h5.create_dataset("bodies/bob/com_velocity", data=np.gradient(bob, time, axis=0))
        h5.create_dataset("bodies/junction/position", data=junction)
        h5.create_dataset("bodies/junction/velocity", data=np.gradient(junction, time, axis=0))
        for branch, start, end in (
            ("upper_A", np.array([-0.15, 0.0, 0.0]), junction),
            ("upper_B", np.array([0.15, 0.0, 0.0]), junction),
            ("lower", junction, bob),
        ):
            if start.ndim == 1:
                start = np.repeat(start[None, :], time.size, axis=0)
            path = np.stack(
                [
                    np.column_stack([np.linspace(start[i, j], end[i, j], 4) for j in range(3)])
                    for i in range(time.size)
                ]
            )
            h5.create_dataset(f"cables/{branch}/material_path/position", data=path)
            h5.create_dataset(f"cables/{branch}/material_path/velocity", data=np.zeros_like(path))
            h5.create_dataset(
                f"cables/{branch}/segments/signed_axial_force", data=np.full((5, 3), 1.8)
            )
            h5.create_dataset(f"cables/{branch}/segments/tension", data=np.full((5, 3), 1.8))
        h5.create_dataset("energy/mechanical", data=np.linspace(1.0, 1.01, 5))
        h5.create_dataset("energy/kinetic", data=np.linspace(0.0, 0.01, 5))
        h5.create_dataset("energy/air_work_rate", data=np.zeros(5))
        h5.create_dataset("validity/guard_margin/MINIMUM_SEGMENT_LENGTH", data=np.ones(5))
    (root / "summary.json").write_text(json.dumps({"status": "undetermined"}), encoding="utf-8")
    (root / "events.json").write_text("[]", encoding="utf-8")
    (root / "config_resolved.json").write_text(
        json.dumps({"bob": {"radius": 0.02}}), encoding="utf-8"
    )


def test_result_readers_expose_scientific_fields_and_difference(tmp_path: Path) -> None:
    forward_root = tmp_path / "forward"
    hf_root = tmp_path / "high_fidelity"
    _write_forward(forward_root)
    _write_hf(hf_root)
    forward = load_forward_result(forward_root)
    high_fidelity = load_hf_result(hf_root)
    assert forward.bob_position.shape == (5, 3)
    assert np.isclose(forward.bob_radius_m, 0.02)
    assert high_fidelity.bob_radius_m == 0.02
    assert set(forward.signed_axial_force) == {"A", "B", "lower"}
    assert set(high_fidelity.tension) == {"upper_A", "upper_B", "lower"}
    assert len(forward.guards) == 1
    assert len(high_fidelity.guards) == 1
    difference = compare_plot_data(forward, high_fidelity)
    assert difference["time"].shape == (5,)
    assert np.max(difference["position_difference_norm"]) > 0.0


def test_unbounded_forward_material_sentinels_are_not_plotted(tmp_path: Path) -> None:
    forward_root = tmp_path / "forward"
    _write_forward(forward_root)
    trajectory = forward_root / "trajectory.npz"
    with np.load(trajectory, allow_pickle=False) as archive:
        arrays = {name: np.asarray(archive[name]) for name in archive.files}
    arrays[
        "diagnostics__sampled_guard_component_series__"
        "MATERIAL_DOMAIN:lower:lambda_upper:element:0"
    ] = np.full(5, np.inf)
    arrays[
        "diagnostics__sampled_guard_component_series__"
        "MATERIAL_DOMAIN:lower:rate_upper:element:0"
    ] = np.full(5, np.inf)
    arrays["diagnostics__sampled_guard_series__material_lambda"] = np.full(
        5, np.inf
    )
    arrays["diagnostics__sampled_guard_series__material_rate"] = np.full(
        5, np.inf
    )
    np.savez_compressed(trajectory, **arrays)
    domains = {
        name: {
            "material_domain": {
                "kind": "open_box",
                "lambda_lower": None,
                "lambda_upper": None,
                "rate_lower": None,
                "rate_upper": None,
            }
        }
        for name in ("A", "B", "lower")
    }
    (forward_root / "config.snapshot.json").write_text(
        json.dumps(
            {
                "physical": {
                    "bob_volume": 4.0 / 3.0 * np.pi * 0.02**3,
                    "branches": domains,
                }
            }
        ),
        encoding="utf-8",
    )

    forward = load_forward_result(forward_root)

    assert "material_lambda" not in forward.guards
    assert "material_rate" not in forward.guards
    assert not any(name.startswith("MATERIAL_DOMAIN:") for name in forward.guards)


def test_active_nonfinite_forward_material_guard_still_fails_closed(
    tmp_path: Path,
) -> None:
    forward_root = tmp_path / "forward"
    _write_forward(forward_root)
    trajectory = forward_root / "trajectory.npz"
    with np.load(trajectory, allow_pickle=False) as archive:
        arrays = {name: np.asarray(archive[name]) for name in archive.files}
    arrays[
        "diagnostics__sampled_guard_component_series__"
        "MATERIAL_DOMAIN:lower:lambda_upper:element:0"
    ] = np.full(5, np.inf)
    np.savez_compressed(trajectory, **arrays)
    domains = {
        name: {
            "material_domain": {
                "kind": "open_box",
                "lambda_lower": None,
                "lambda_upper": 1.5 if name == "lower" else None,
                "rate_lower": None,
                "rate_upper": None,
            }
        }
        for name in ("A", "B", "lower")
    }
    (forward_root / "config.snapshot.json").write_text(
        json.dumps(
            {
                "physical": {
                    "bob_volume": 4.0 / 3.0 * np.pi * 0.02**3,
                    "branches": domains,
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="NaN or infinity"):
        load_forward_result(forward_root)


def test_complete_desktop_bundle_and_comparison_artifacts(tmp_path: Path) -> None:
    _write_forward(tmp_path / "forward")
    _write_hf(tmp_path / "high_fidelity")
    (tmp_path / "desktop_result.json").write_text(
        json.dumps(
            {
                "schema_version": DESKTOP_RESULT_SCHEMA,
                "status": "COMPLETE",
                "backend": "both",
            }
        ),
        encoding="utf-8",
    )
    report = write_comparison_artifacts(
        tmp_path / "forward", tmp_path / "high_fidelity", tmp_path / "comparison"
    )
    assert report["status"] == "COMPARISON_COMPLETE"
    assert (tmp_path / "comparison" / "comparison_series.npz").is_file()
    bundle = load_desktop_output(tmp_path)
    assert bundle.forward is not None
    assert bundle.high_fidelity is not None
    assert bundle.comparison["time"].size == 5


def test_geometry_animation_uses_shared_time_interpolation_and_fixed_cube(
    tmp_path: Path,
) -> None:
    forward_root = tmp_path / "forward"
    hf_root = tmp_path / "high_fidelity"
    _write_forward(forward_root)
    _write_hf(hf_root)
    forward = load_forward_result(forward_root)
    high_fidelity = load_hf_result(hf_root)

    # Deliberately use a different output grid for HF.  The viewer must still
    # pair the two models at the same physical instant rather than by index.
    high_fidelity.geometry_time = np.linspace(0.001, 0.003, 5)
    start, stop = common_geometry_time_window([forward, high_fidelity])
    assert (start, stop) == (0.001, 0.003)

    target = 0.00225
    paths = geometry_paths_at_time(high_fidelity, target)
    expected = interpolate_vector_series(
        high_fidelity.geometry_time,
        high_fidelity.geometry_paths["lower"],
        target,
    )
    np.testing.assert_allclose(paths["lower"], expected, rtol=0.0, atol=1.0e-15)

    low, high = geometry_scene_cube([forward, high_fidelity])
    np.testing.assert_allclose(high - low, np.repeat(high[0] - low[0], 3))
    assert np.all(forward.bob_position >= low)
    assert np.all(forward.bob_position <= high)

    trajectory_low, trajectory_high = trajectory_plane_square([forward, high_fidelity])
    np.testing.assert_allclose(
        trajectory_high - trajectory_low,
        np.repeat(trajectory_high[0] - trajectory_low[0], 2),
    )
    for data in (forward, high_fidelity):
        assert np.all(data.bob_position[:, :2] >= trajectory_low)
        assert np.all(data.bob_position[:, :2] <= trajectory_high)


def test_endpoint_chord_view_preserves_endpoints_and_ignores_internal_hinges(
    tmp_path: Path,
) -> None:
    forward_root = tmp_path / "forward"
    _write_forward(forward_root)
    forward = load_forward_result(forward_root)
    raw = forward.geometry_paths["A"]
    midpoint = 0.5 * (raw[:, :1, :] + raw[:, -1:, :])
    hinged = np.concatenate((raw[:, :1, :], midpoint + [0.0, 4.0, 0.0], raw[:, -1:, :]), axis=1)
    forward.geometry_paths["A"] = hinged

    chords = endpoint_chord_paths({"A": hinged})["A"]

    assert chords.shape == (hinged.shape[0], 2, 3)
    np.testing.assert_allclose(chords[:, 0], hinged[:, 0])
    np.testing.assert_allclose(chords[:, 1], hinged[:, -1])
    legacy = endpoint_chord_paths({"all_nodes": hinged})["all_nodes"]
    np.testing.assert_allclose(legacy, hinged)
    raw_low, raw_high = geometry_scene_cube([forward])
    chord_low, chord_high = geometry_scene_cube([forward], endpoint_chords=True)
    assert raw_high[1] - raw_low[1] > 3.0
    assert chord_high[1] - chord_low[1] < 1.0

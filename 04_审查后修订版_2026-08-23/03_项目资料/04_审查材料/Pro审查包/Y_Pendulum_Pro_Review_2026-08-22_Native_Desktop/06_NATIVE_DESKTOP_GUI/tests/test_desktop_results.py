from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from ypendulum.ui.desktop_config import DESKTOP_RESULT_SCHEMA
from ypendulum.ui.desktop_results import (
    compare_plot_data,
    load_desktop_output,
    load_forward_result,
    load_hf_result,
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
                "metadata": {
                    "branch_nodes": {"A": [0, 2], "B": [1, 2], "lower": [2, 3]}
                },
            }
        ),
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
                    np.column_stack(
                        [np.linspace(start[i, j], end[i, j], 4) for j in range(3)]
                    )
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
    assert high_fidelity.bob_radius_m == 0.02
    assert set(forward.signed_axial_force) == {"A", "B", "lower"}
    assert set(high_fidelity.tension) == {"upper_A", "upper_B", "lower"}
    assert len(forward.guards) == 1
    assert len(high_fidelity.guards) == 1
    difference = compare_plot_data(forward, high_fidelity)
    assert difference["time"].shape == (5,)
    assert np.max(difference["position_difference_norm"]) > 0.0


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


"""Read scientific outputs for the native desktop dashboard.

Only plotting/downsampling happens here.  Canonical NPZ/HDF5 artifacts remain
the source of truth and are never rewritten by the viewer.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import h5py
import numpy as np


@dataclass
class BackendPlotData:
    backend: str
    source_directory: Path
    time: np.ndarray
    bob_position: np.ndarray
    bob_velocity: np.ndarray
    junction_position: np.ndarray
    junction_velocity: np.ndarray
    geometry_time: np.ndarray
    geometry_paths: dict[str, np.ndarray]
    bob_radius_m: float | None
    signed_axial_force: dict[str, np.ndarray]
    tension: dict[str, np.ndarray]
    energy: dict[str, np.ndarray]
    power: dict[str, np.ndarray]
    guards: dict[str, np.ndarray]
    events: list[dict[str, Any]]
    summary: dict[str, Any]
    branch_nodes: dict[str, np.ndarray] = field(default_factory=dict)


@dataclass
class DesktopPlotBundle:
    output_directory: Path
    status: str
    forward: BackendPlotData | None
    high_fidelity: BackendPlotData | None
    comparison: dict[str, np.ndarray]
    desktop_result: dict[str, Any]


def common_geometry_time_window(
    backends: list[BackendPlotData] | tuple[BackendPlotData, ...],
) -> tuple[float, float]:
    """Return the physical-time interval shared by every displayed backend.

    A dual-backend animation must compare both models at the same physical
    instant.  Mapping each backend by its own frame fraction can silently pair
    different times when output grids differ, so the desktop viewer uses this
    common interval as its single timeline.
    """

    if not backends:
        raise ValueError("At least one backend is required for a geometry timeline.")
    for data in backends:
        if data.geometry_time.ndim != 1 or data.geometry_time.size < 1:
            raise ValueError(f"{data.backend} geometry timeline is empty or not one-dimensional.")
        if np.any(np.diff(data.geometry_time) <= 0.0):
            raise ValueError(f"{data.backend} geometry timeline is not strictly increasing.")
    start = max(float(data.geometry_time[0]) for data in backends)
    stop = min(float(data.geometry_time[-1]) for data in backends)
    if stop < start:
        raise ValueError("Displayed backends have no common geometry time interval.")
    return start, stop


def interpolate_vector_series(
    times: np.ndarray,
    values: np.ndarray,
    target_time: float,
) -> np.ndarray:
    """Linearly interpolate an arbitrary vector/tensor series in physical time."""

    time_axis = np.asarray(times, dtype=float)
    array = np.asarray(values, dtype=float)
    if time_axis.ndim != 1 or time_axis.size < 1:
        raise ValueError("Interpolation timeline must be a non-empty one-dimensional array.")
    if array.shape[0] != time_axis.size:
        raise ValueError("Interpolation values and timeline have different frame counts.")
    if np.any(np.diff(time_axis) <= 0.0):
        raise ValueError("Interpolation timeline must be strictly increasing.")
    if not math.isfinite(float(target_time)):
        raise ValueError("Interpolation target time must be finite.")
    if target_time <= float(time_axis[0]) or time_axis.size == 1:
        return np.array(array[0], copy=True)
    if target_time >= float(time_axis[-1]):
        return np.array(array[-1], copy=True)
    upper = int(np.searchsorted(time_axis, target_time, side="right"))
    lower = upper - 1
    span = float(time_axis[upper] - time_axis[lower])
    fraction = (float(target_time) - float(time_axis[lower])) / span
    return (1.0 - fraction) * array[lower] + fraction * array[upper]


def geometry_paths_at_time(data: BackendPlotData, target_time: float) -> dict[str, np.ndarray]:
    """Interpolate every material path of one backend at one physical instant."""

    return {
        name: interpolate_vector_series(data.geometry_time, values, target_time)
        for name, values in data.geometry_paths.items()
    }


def endpoint_chord_paths(paths: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Replace each discrete material path by its endpoint chord.

    The forward cable nodes are useful audit fields, but they are not calibrated
    experimental observables.  A coarse tension-only discretisation can also
    form visually sharp hinges whenever a segment unloads.  The apparatus view
    therefore draws the lossless endpoint geometry while retaining the raw
    arrays for the explicit material-path audit view.

    Arrays may be either ``(node, xyz)`` snapshots or ``(time, node, xyz)``
    histories.  All leading dimensions are preserved.
    """

    chords: dict[str, np.ndarray] = {}
    for name, values in paths.items():
        array = np.asarray(values, dtype=float)
        if array.ndim < 2 or array.shape[-1] != 3 or array.shape[-2] < 2:
            raise ValueError(
                f"Geometry path {name!r} has shape {array.shape}; expected "
                "(..., at least two nodes, 3)."
            )
        if name == "all_nodes":
            # A legacy result without branch topology cannot be losslessly
            # separated into three chords.  Preserve it instead of inventing a
            # line from the first global node to the last.
            chords[name] = np.array(array, copy=True)
            continue
        chords[name] = np.take(array, (0, array.shape[-2] - 1), axis=-2)
    return chords


def geometry_scene_cube(
    backends: list[BackendPlotData] | tuple[BackendPlotData, ...],
    *,
    padding_fraction: float = 0.08,
    minimum_radius_m: float = 0.05,
    endpoint_chords: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Return fixed equal-scale scene limits covering every stored frame.

    Fixed limits prevent the camera from breathing or translating during
    playback, which otherwise makes a physically correct trajectory look like
    the apparatus itself is moving.
    """

    if not backends:
        raise ValueError("At least one backend is required for scene bounds.")
    if padding_fraction < 0.0 or minimum_radius_m <= 0.0:
        raise ValueError("Scene padding must be non-negative and minimum radius positive.")
    clouds: list[np.ndarray] = []
    for data in backends:
        geometry_paths = data.geometry_paths
        if endpoint_chords and len(geometry_paths) > 1:
            geometry_paths = {
                name: values
                for name, values in geometry_paths.items()
                if name != "all_nodes"
            }
        paths = (
            endpoint_chord_paths(geometry_paths)
            if endpoint_chords
            else geometry_paths
        )
        clouds.extend(
            np.asarray(values, dtype=float).reshape(-1, 3)
            for values in paths.values()
        )
        clouds.append(np.asarray(data.bob_position, dtype=float).reshape(-1, 3))
        clouds.append(np.asarray(data.junction_position, dtype=float).reshape(-1, 3))
    cloud = np.concatenate(clouds, axis=0)
    if cloud.size == 0 or not np.all(np.isfinite(cloud)):
        raise ValueError("Geometry scene contains no finite points.")
    low = np.min(cloud, axis=0)
    high = np.max(cloud, axis=0)
    centre = 0.5 * (low + high)
    radius = max(0.5 * float(np.max(high - low)) * (1.0 + padding_fraction), minimum_radius_m)
    return centre - radius, centre + radius


def trajectory_plane_square(
    backends: list[BackendPlotData] | tuple[BackendPlotData, ...],
    *,
    padding_fraction: float = 0.08,
    minimum_radius_m: float = 0.01,
) -> tuple[np.ndarray, np.ndarray]:
    """Return fixed equal-scale x-y limits for a top-view Lissajous trace."""

    if not backends:
        raise ValueError("At least one backend is required for trajectory bounds.")
    if padding_fraction < 0.0 or minimum_radius_m <= 0.0:
        raise ValueError("Trajectory padding must be non-negative and minimum radius positive.")
    points = np.concatenate(
        [np.asarray(data.bob_position, dtype=float)[:, :2] for data in backends],
        axis=0,
    )
    if points.size == 0 or not np.all(np.isfinite(points)):
        raise ValueError("Top-view trajectory contains no finite points.")
    low = np.min(points, axis=0)
    high = np.max(points, axis=0)
    centre = 0.5 * (low + high)
    radius = max(0.5 * float(np.max(high - low)) * (1.0 + padding_fraction), minimum_radius_m)
    return centre - radius, centre + radius


def _indices(size: int, maximum: int) -> np.ndarray:
    if size < 1:
        raise ValueError("Result has no samples.")
    if size <= maximum:
        return np.arange(size, dtype=int)
    return np.unique(np.linspace(0, size - 1, maximum, dtype=int))


def _finite(name: str, value: Any, shape_tail: tuple[int, ...] | None = None) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if shape_tail is not None and array.shape[1:] != shape_tail:
        raise ValueError(f"{name} has shape {array.shape}; expected (*,{shape_tail}).")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} contains NaN or infinity.")
    return array


def _force_summary(values: np.ndarray) -> np.ndarray:
    array = _finite("force", values)
    if array.ndim != 2 or array.shape[1] < 1:
        raise ValueError("Axial-force field must be time x segment.")
    return np.column_stack((np.min(array, axis=1), np.mean(array, axis=1), np.max(array, axis=1)))


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _forward_material_boundaries(
    config_snapshot: Any,
) -> dict[str, set[str]] | None:
    """Return explicitly active FWD material bounds, or ``None`` if unknown.

    The frozen Stage-2 solver represents a ``null`` open-box side internally as
    infinity and consequently writes an infinite diagnostic series for that
    inactive side.  Those are absence sentinels, not trajectory values.  The
    desktop reader may omit them only when the immutable input snapshot proves
    that the corresponding side was explicitly unbounded; malformed or legacy
    snapshots stay fail-closed.
    """

    if not isinstance(config_snapshot, dict):
        return None
    physical = config_snapshot.get("physical")
    branches = physical.get("branches") if isinstance(physical, dict) else None
    if not isinstance(branches, dict) or not branches:
        return None
    result: dict[str, set[str]] = {}
    boundary_names = {
        "lambda_lower",
        "lambda_upper",
        "rate_lower",
        "rate_upper",
    }
    for branch_name, branch in branches.items():
        domain = branch.get("material_domain") if isinstance(branch, dict) else None
        if not isinstance(domain, dict):
            return None
        result[str(branch_name)] = {
            name for name in boundary_names if domain.get(name) is not None
        }
    return result


def _inactive_forward_material_guard(
    guard_name: str,
    active_boundaries: dict[str, set[str]] | None,
) -> bool:
    if active_boundaries is None:
        return False
    parts = guard_name.split(":")
    if (
        len(parts) == 5
        and parts[0] == "MATERIAL_DOMAIN"
        and parts[3] == "element"
    ):
        branch, boundary = parts[1], parts[2]
        return (
            branch in active_boundaries
            and boundary not in active_boundaries[branch]
        )
    if guard_name == "material_lambda":
        return not any(
            any(name.startswith("lambda_") for name in boundaries)
            for boundaries in active_boundaries.values()
        )
    if guard_name == "material_rate":
        return not any(
            any(name.startswith("rate_") for name in boundaries)
            for boundaries in active_boundaries.values()
        )
    return False


def load_forward_result(
    directory: str | Path,
    *,
    maximum_plot_samples: int = 4000,
    maximum_geometry_frames: int = 4001,
) -> BackendPlotData:
    root = Path(directory).expanduser().resolve()
    trajectory = root / "trajectory.npz"
    summary_path = root / "result.json"
    if not trajectory.is_file() or not summary_path.is_file():
        raise FileNotFoundError("Forward result requires result.json and trajectory.npz.")
    summary = _load_json(summary_path, {})
    events = summary.get("events", []) if isinstance(summary, dict) else []
    if not isinstance(events, list):
        events = []
    config_snapshot = _load_json(root / "config.snapshot.json", {})
    active_material_boundaries = _forward_material_boundaries(config_snapshot)
    bob_radius = None
    if isinstance(config_snapshot, dict):
        candidate = config_snapshot.get("physical", {}).get("bob_volume")
        if (
            isinstance(candidate, (int, float))
            and not isinstance(candidate, bool)
            and float(candidate) > 0.0
        ):
            bob_radius = (3.0 * float(candidate) / (4.0 * math.pi)) ** (1.0 / 3.0)
    with np.load(trajectory, allow_pickle=False) as archive:
        time_full = _finite("forward time", archive["time"])
        if time_full.ndim != 1 or np.any(np.diff(time_full) <= 0.0):
            raise ValueError("Forward time is not strictly increasing.")
        idx = _indices(time_full.size, maximum_plot_samples)
        geom_idx = _indices(time_full.size, maximum_geometry_frames)
        time = time_full[idx]
        bob_position = _finite("forward bob position", archive["state__r_m"])[idx]
        bob_velocity = _finite("forward bob velocity", archive["state__v_m"])[idx]
        junction_position = _finite("forward junction position", archive["state__r_J"])[idx]
        junction_velocity = _finite("forward junction velocity", archive["state__v_J"])[idx]
        node_positions = _finite("forward node positions", archive["state__node_positions"])
        geometry_paths = {"all_nodes": node_positions[geom_idx]}

        branch_nodes_payload = summary.get("metadata", {}).get("branch_nodes", {})
        branch_nodes: dict[str, np.ndarray] = {}
        if isinstance(branch_nodes_payload, dict):
            for name, values in branch_nodes_payload.items():
                node_index = np.asarray(values, dtype=int)
                if (
                    node_index.ndim == 1
                    and node_index.size >= 2
                    and np.all(node_index >= 0)
                    and np.all(node_index < node_positions.shape[1])
                ):
                    branch_nodes[str(name)] = node_index
                    geometry_paths[str(name)] = node_positions[geom_idx][:, node_index, :]

        signed: dict[str, np.ndarray] = {}
        tension: dict[str, np.ndarray] = {}
        for name in ("A", "B", "lower"):
            prefix = f"derived__branches__{name}__"
            elastic_key = prefix + "N_elastic"
            viscous_key = prefix + "N_viscous"
            tension_key = prefix + "N"
            if elastic_key in archive and viscous_key in archive:
                raw = np.asarray(archive[elastic_key], dtype=float) + np.asarray(
                    archive[viscous_key], dtype=float
                )
                signed[name] = _force_summary(raw[idx])
            if tension_key in archive:
                tension[name] = _force_summary(np.asarray(archive[tension_key], dtype=float)[idx])

        energy_map = {
            "mechanical": "derived__E_F",
            "kinetic": "derived__T_kin",
            "gravitational": "derived__V_g",
            "buoyancy": "derived__V_buoy",
            "elastic_axial": "derived__V_ax",
        }
        power_map = {
            "dissipation_axial": "derived__D_ax",
            "dissipation_string": "derived__D_string",
            "dissipation_bob": "derived__D_b",
            "support_power": "derived__P_base",
            "air_power": "derived__P_air",
            "external_power": "derived__P_ext",
        }
        energy = {
            name: _finite(key, archive[key])[idx]
            for name, key in energy_map.items()
            if key in archive
        }
        power = {
            name: _finite(key, archive[key])[idx]
            for name, key in power_map.items()
            if key in archive
        }
        guards: dict[str, np.ndarray] = {}
        component_prefix = "diagnostics__sampled_guard_component_series__"
        family_prefix = "diagnostics__sampled_guard_series__"
        for key in archive.files:
            if key.startswith(component_prefix):
                name = key[len(component_prefix) :]
                if _inactive_forward_material_guard(
                    name, active_material_boundaries
                ):
                    continue
                guards[name] = _finite(key, archive[key])[idx]
            elif key.startswith(family_prefix):
                name = key[len(family_prefix) :]
                if _inactive_forward_material_guard(
                    name, active_material_boundaries
                ):
                    continue
                guards[name] = _finite(key, archive[key])[idx]

    return BackendPlotData(
        backend="forward",
        source_directory=root,
        time=time,
        bob_position=bob_position,
        bob_velocity=bob_velocity,
        junction_position=junction_position,
        junction_velocity=junction_velocity,
        geometry_time=time_full[geom_idx],
        geometry_paths=geometry_paths,
        bob_radius_m=bob_radius,
        signed_axial_force=signed,
        tension=tension,
        energy=energy,
        power=power,
        guards=guards,
        events=[item for item in events if isinstance(item, dict)],
        summary=summary if isinstance(summary, dict) else {},
        branch_nodes=branch_nodes,
    )


def load_hf_result(
    directory: str | Path,
    *,
    maximum_plot_samples: int = 4000,
    maximum_geometry_frames: int = 4001,
) -> BackendPlotData:
    root = Path(directory).expanduser().resolve()
    result_path = root / "result.h5"
    if not result_path.is_file():
        raise FileNotFoundError("HF result requires result.h5.")
    summary = _load_json(root / "summary.json", {})
    events = _load_json(root / "events.json", [])
    config = _load_json(root / "config_resolved.json", None)
    if config is None:
        try:
            import yaml

            config = yaml.safe_load((root / "config_resolved.yaml").read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            config = {}
    bob_radius = None
    if isinstance(config, dict):
        candidate = config.get("bob", {}).get("radius")
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            bob_radius = float(candidate)

    with h5py.File(result_path, "r") as h5:
        time_full = _finite("HF time", h5["/time"])
        if time_full.ndim != 1 or np.any(np.diff(time_full) <= 0.0):
            raise ValueError("HF time is not strictly increasing.")
        idx = _indices(time_full.size, maximum_plot_samples)
        geom_idx = _indices(time_full.size, maximum_geometry_frames)
        time = time_full[idx]
        bob_position = _finite("HF bob position", h5["/bodies/bob/com_position"])[idx]
        bob_velocity = _finite("HF bob velocity", h5["/bodies/bob/com_velocity"])[idx]
        junction_position = _finite("HF junction position", h5["/bodies/junction/position"])[idx]
        junction_velocity = _finite("HF junction velocity", h5["/bodies/junction/velocity"])[idx]
        geometry_paths = {
            name: _finite(
                f"HF {name} material path",
                h5[f"/cables/{name}/material_path/position"],
            )[geom_idx]
            for name in ("upper_A", "upper_B", "lower")
        }
        signed = {
            name: _force_summary(np.asarray(h5[f"/cables/{name}/segments/signed_axial_force"])[idx])
            for name in ("upper_A", "upper_B", "lower")
        }
        tension = {
            name: _force_summary(np.asarray(h5[f"/cables/{name}/segments/tension"])[idx])
            for name in ("upper_A", "upper_B", "lower")
        }
        energy: dict[str, np.ndarray] = {}
        power: dict[str, np.ndarray] = {}
        for name, dataset in h5["/energy"].items():
            values = _finite(f"HF energy/{name}", dataset)[idx]
            if name.endswith("_rate") or name in {"balance_residual"}:
                power[name] = values
            else:
                energy[name] = values
        guards = {
            str(name): _finite(f"HF guard/{name}", dataset)[idx]
            for name, dataset in h5["/validity/guard_margin"].items()
        }

    return BackendPlotData(
        backend="high_fidelity",
        source_directory=root,
        time=time,
        bob_position=bob_position,
        bob_velocity=bob_velocity,
        junction_position=junction_position,
        junction_velocity=junction_velocity,
        geometry_time=time_full[geom_idx],
        geometry_paths=geometry_paths,
        bob_radius_m=bob_radius,
        signed_axial_force=signed,
        tension=tension,
        energy=energy,
        power=power,
        guards=guards,
        events=[item for item in events if isinstance(item, dict)]
        if isinstance(events, list)
        else [],
        summary=summary if isinstance(summary, dict) else {},
    )


def compare_plot_data(
    forward: BackendPlotData, high_fidelity: BackendPlotData
) -> dict[str, np.ndarray]:
    start = max(float(forward.time[0]), float(high_fidelity.time[0]))
    stop = min(float(forward.time[-1]), float(high_fidelity.time[-1]))
    time = forward.time[(forward.time >= start) & (forward.time <= stop)]
    if time.size < 2:
        raise ValueError("FWD and HF results have no common time interval.")

    def interpolate(source_time: np.ndarray, values: np.ndarray) -> np.ndarray:
        return np.column_stack(
            [np.interp(time, source_time, values[:, component]) for component in range(3)]
        )

    fwd_position = interpolate(forward.time, forward.bob_position)
    hf_position = interpolate(high_fidelity.time, high_fidelity.bob_position)
    fwd_velocity = interpolate(forward.time, forward.bob_velocity)
    hf_velocity = interpolate(high_fidelity.time, high_fidelity.bob_velocity)
    position_difference = hf_position - fwd_position
    velocity_difference = hf_velocity - fwd_velocity
    return {
        "time": time,
        "forward_bob_position": fwd_position,
        "high_fidelity_bob_position": hf_position,
        "position_difference": position_difference,
        "position_difference_norm": np.linalg.norm(position_difference, axis=1),
        "forward_bob_velocity": fwd_velocity,
        "high_fidelity_bob_velocity": hf_velocity,
        "velocity_difference": velocity_difference,
        "velocity_difference_norm": np.linalg.norm(velocity_difference, axis=1),
    }


def load_desktop_output(directory: str | Path) -> DesktopPlotBundle:
    root = Path(directory).expanduser().resolve()
    desktop = _load_json(root / "desktop_result.json", {})
    if not isinstance(desktop, dict):
        raise ValueError("desktop_result.json must contain an object.")
    forward = load_forward_result(root / "forward") if (root / "forward").is_dir() else None
    hf = load_hf_result(root / "high_fidelity") if (root / "high_fidelity").is_dir() else None
    comparison = compare_plot_data(forward, hf) if forward is not None and hf is not None else {}
    return DesktopPlotBundle(
        output_directory=root,
        status=str(desktop.get("status", "UNKNOWN")),
        forward=forward,
        high_fidelity=hf,
        comparison=comparison,
        desktop_result=desktop,
    )


def write_comparison_artifacts(
    forward_directory: str | Path,
    high_fidelity_directory: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    forward = load_forward_result(forward_directory)
    hf = load_hf_result(high_fidelity_directory)
    values = compare_plot_data(forward, hf)
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output / "comparison_series.npz", **values)
    position_norm = values["position_difference_norm"]
    velocity_norm = values["velocity_difference_norm"]
    report = {
        "schema_version": "YPS-DESKTOP-COMPARISON-1.0",
        "status": "COMPARISON_COMPLETE",
        "sample_count": int(values["time"].size),
        "window_s": [float(values["time"][0]), float(values["time"][-1])],
        "rms_bob_position_difference_m": float(np.sqrt(np.mean(position_norm**2))),
        "maximum_bob_position_difference_m": float(np.max(position_norm)),
        "rms_bob_velocity_difference_m_s": float(np.sqrt(np.mean(velocity_norm**2))),
        "maximum_bob_velocity_difference_m_s": float(np.max(velocity_norm)),
        "interpretation": "Model-form difference on the common returned interval; not a convergence error.",
    }
    (output / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report

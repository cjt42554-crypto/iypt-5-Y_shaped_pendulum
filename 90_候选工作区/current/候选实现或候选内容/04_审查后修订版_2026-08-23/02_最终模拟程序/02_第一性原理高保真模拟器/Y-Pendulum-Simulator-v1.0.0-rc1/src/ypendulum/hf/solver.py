"""Static preparation, integration and energy audit for the HF backend."""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from scipy.integrate import BDF, Radau, cumulative_trapezoid
from scipy.optimize import brentq, minimize, root
from scipy.sparse.linalg import ArpackNoConvergence, LinearOperator, eigsh

from ypendulum.config import resolved_config_sha256
from ypendulum.config.models import SimulationConfig
from ypendulum.config.units import as_vector3, to_si
from ypendulum.config.validation import _high_fidelity_resource_estimate

from .model import HighFidelityModel, normalize_quaternion, rotate_body_vector
from .state import HighFidelityResult


def _coalesce_terminal_certificate(
    time: np.ndarray,
    state: np.ndarray,
    *,
    terminal_target: float,
    tolerance: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Merge only machine-indistinguishable accepted points at the endpoint."""

    accepted_time = np.asarray(time, dtype=float)
    accepted_state = np.asarray(state, dtype=float)
    if accepted_time.ndim != 1 or accepted_state.shape[0] != accepted_time.size:
        raise ValueError("Accepted-step certificate time/state shape mismatch.")
    if accepted_time.size < 2 or (
        abs(float(accepted_time[-1]) - terminal_target) > tolerance
    ):
        return accepted_time, accepted_state, 0
    first_terminal = accepted_time.size - 1
    while first_terminal > 0 and float(
        accepted_time[first_terminal] - accepted_time[first_terminal - 1]
    ) <= tolerance:
        first_terminal -= 1
    if first_terminal == accepted_time.size - 1:
        return accepted_time, accepted_state, 0
    keep = np.concatenate(
        [
            np.arange(first_terminal, dtype=int),
            np.array([accepted_time.size - 1], dtype=int),
        ]
    )
    return (
        accepted_time[keep],
        accepted_state[keep],
        int(accepted_time.size - keep.size),
    )


@dataclass(frozen=True)
class PreparationResult:
    state: np.ndarray
    residual_inf_N: float
    iterations: int
    bob_held: bool
    preparation_mode: str
    audit: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _BoundedIntegrationTrace:
    accepted_time: np.ndarray
    accepted_state: np.ndarray
    presentation_state: np.ndarray
    event_time: float | None
    event_state: np.ndarray | None
    event_guard_names: tuple[str, ...]
    nfev: int
    njev: int
    nlu: int


_INTEGRATION_CHECKPOINT_SCHEMA = "YPS-HF-INTEGRATION-CHECKPOINT-1.0"


def _array_sha256(values: np.ndarray) -> str:
    array = np.ascontiguousarray(values)
    digest = hashlib.sha256()
    digest.update(array.dtype.str.encode("ascii"))
    digest.update(json.dumps(array.shape, separators=(",", ":")).encode("ascii"))
    if array.size:
        digest.update(memoryview(array.reshape(-1)).cast("B"))
    return digest.hexdigest()


def _write_integration_checkpoint(
    path: str | Path,
    *,
    cfg: SimulationConfig,
    model: HighFidelityModel,
    preparation: PreparationResult,
    trace: _BoundedIntegrationTrace,
    output_time: np.ndarray,
    integration_wall_seconds: float,
) -> dict[str, Any]:
    """Persist the completed integration before presentation post-processing."""

    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    presentation_time = np.asarray(
        output_time[: trace.presentation_state.shape[0]], dtype=float
    )
    accepted_time = np.asarray(trace.accepted_time, dtype=float)
    accepted_state = np.asarray(trace.accepted_state, dtype=float)
    presentation_state = np.asarray(trace.presentation_state, dtype=float)
    event_state = (
        np.empty((0, model.state_size), dtype=float)
        if trace.event_state is None
        else np.asarray(trace.event_state, dtype=float).reshape(1, model.state_size)
    )
    metadata = {
        "schema": _INTEGRATION_CHECKPOINT_SCHEMA,
        "model_id": model.model_id,
        "state_size": model.state_size,
        "resolved_config_sha256": resolved_config_sha256(cfg),
        "solver_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "model_source_sha256": hashlib.sha256(
            Path(__file__).with_name("model.py").read_bytes()
        ).hexdigest(),
        "integration_wall_seconds": float(integration_wall_seconds),
        "preparation_residual_inf_N": (
            float(preparation.residual_inf_N)
            if np.isfinite(preparation.residual_inf_N)
            else None
        ),
        "preparation_iterations": int(preparation.iterations),
        "preparation_bob_held": bool(preparation.bob_held),
        "preparation_mode": preparation.preparation_mode,
        "event_time": trace.event_time,
        "event_guard_names": list(trace.event_guard_names),
        "nfev": trace.nfev,
        "njev": trace.njev,
        "nlu": trace.nlu,
        "accepted_time_sha256": _array_sha256(accepted_time),
        "accepted_state_sha256": _array_sha256(accepted_state),
        "presentation_time_sha256": _array_sha256(presentation_time),
        "presentation_state_sha256": _array_sha256(presentation_state),
        "event_state_sha256": _array_sha256(event_state),
    }
    temporary = target.with_name(f".{target.name}.writing-{os.getpid()}")
    try:
        with temporary.open("wb") as handle:
            np.savez(
                handle,
                metadata_json=np.asarray(
                    json.dumps(metadata, sort_keys=True, separators=(",", ":"))
                ),
                accepted_time=accepted_time,
                accepted_state=accepted_state,
                presentation_time=presentation_time,
                presentation_state=presentation_state,
                event_state=event_state,
            )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return metadata


def _load_integration_checkpoint(
    path: str | Path,
    *,
    cfg: SimulationConfig,
    model: HighFidelityModel,
    output_time: np.ndarray,
) -> tuple[_BoundedIntegrationTrace, dict[str, Any]]:
    """Load one completed integration and verify its scientific identity."""

    source = Path(path).expanduser().resolve()
    with np.load(source, allow_pickle=False) as payload:
        metadata = json.loads(str(payload["metadata_json"].item()))
        accepted_time = np.asarray(payload["accepted_time"], dtype=float)
        accepted_state = np.asarray(payload["accepted_state"], dtype=float)
        presentation_time = np.asarray(payload["presentation_time"], dtype=float)
        presentation_state = np.asarray(payload["presentation_state"], dtype=float)
        event_state_array = np.asarray(payload["event_state"], dtype=float)
    if metadata.get("schema") != _INTEGRATION_CHECKPOINT_SCHEMA:
        raise ValueError("Unsupported HF integration checkpoint schema.")
    if metadata.get("model_id") != model.model_id:
        raise ValueError("HF checkpoint model_id does not match the requested model.")
    if int(metadata.get("state_size", -1)) != model.state_size:
        raise ValueError("HF checkpoint state size does not match the requested model.")
    if metadata.get("resolved_config_sha256") != resolved_config_sha256(cfg):
        raise ValueError("HF checkpoint configuration identity does not match.")
    expected_shapes = (
        accepted_time.ndim == 1
        and accepted_state.shape == (accepted_time.size, model.state_size)
        and presentation_time.ndim == 1
        and presentation_state.shape == (
            presentation_time.size,
            model.state_size,
        )
        and event_state_array.shape in {(0, model.state_size), (1, model.state_size)}
    )
    if not expected_shapes:
        raise ValueError("HF checkpoint time/state arrays have invalid shapes.")
    if (
        accepted_time.size == 0
        or presentation_time.size == 0
        or np.any(np.diff(accepted_time) <= 0.0)
        or np.any(np.diff(presentation_time) <= 0.0)
        or not np.all(np.isfinite(accepted_time))
        or not np.all(np.isfinite(accepted_state))
        or not np.all(np.isfinite(presentation_time))
        or not np.all(np.isfinite(presentation_state))
        or not np.all(np.isfinite(event_state_array))
    ):
        raise ValueError("HF checkpoint arrays are non-finite or not time ordered.")
    if not np.array_equal(
        presentation_time,
        output_time[: presentation_time.size],
    ):
        raise ValueError("HF checkpoint presentation grid does not match the request.")
    arrays = {
        "accepted_time": accepted_time,
        "accepted_state": accepted_state,
        "presentation_time": presentation_time,
        "presentation_state": presentation_state,
        "event_state": event_state_array,
    }
    for name, values in arrays.items():
        if metadata.get(f"{name}_sha256") != _array_sha256(values):
            raise ValueError(f"HF checkpoint {name} digest mismatch.")
    event_time_value = metadata.get("event_time")
    event_time = None if event_time_value is None else float(event_time_value)
    event_state = (
        None if event_state_array.shape[0] == 0 else event_state_array[0].copy()
    )
    trace = _BoundedIntegrationTrace(
        accepted_time=accepted_time,
        accepted_state=accepted_state,
        presentation_state=presentation_state,
        event_time=event_time,
        event_state=event_state,
        event_guard_names=tuple(str(item) for item in metadata["event_guard_names"]),
        nfev=int(metadata["nfev"]),
        njev=int(metadata["njev"]),
        nlu=int(metadata["nlu"]),
    )
    return trace, metadata


_PRESENTATION_ENERGY_KEYS = (
    "kinetic",
    "kinetic_particles",
    "kinetic_bob_translation",
    "kinetic_bob_rotation",
    "gravitational",
    "elastic_axial",
    "elastic_bending",
    "mechanical",
    "axial_dissipation_rate",
    "aero_dissipation_rate",
    "air_work_rate",
    "support_work_rate",
)
_PRESENTATION_MODEL: HighFidelityModel | None = None
_PRESENTATION_GUARD_METADATA: dict[str, dict[str, float | str]] | None = None
_PRESENTATION_CHECK_GUARDS = True


def _physical_cpu_core_count() -> int:
    """Return the Linux physical-core count without adding a dependency."""

    topology: set[tuple[str, str]] = set()
    cpu_root = "/sys/devices/system/cpu"
    try:
        for entry in os.scandir(cpu_root):
            if not entry.name.startswith("cpu") or not entry.name[3:].isdigit():
                continue
            topology_root = os.path.join(entry.path, "topology")
            with open(
                os.path.join(topology_root, "physical_package_id"),
                encoding="ascii",
            ) as package_handle:
                package = package_handle.read().strip()
            with open(
                os.path.join(topology_root, "core_id"), encoding="ascii"
            ) as core_handle:
                core = core_handle.read().strip()
            topology.add((package, core))
    except OSError:
        topology.clear()
    if topology:
        return len(topology)
    logical = os.cpu_count() or 1
    return max(1, logical // 2)


def _process_tree_cpu_seconds() -> float:
    """CPU seconds consumed by this process and already-reaped workers."""

    times = os.times()
    return float(
        times.user
        + times.system
        + times.children_user
        + times.children_system
    )


def _presentation_worker_count(sample_count: int) -> int:
    requested = os.environ.get("YPS_HF_POSTPROCESS_WORKERS")
    if requested is None or requested.strip().lower() == "auto":
        count = (
            1
            if sample_count < 64
            else min(12, _physical_cpu_core_count())
        )
    else:
        try:
            count = int(requested)
        except ValueError as exc:
            raise ValueError(
                "YPS_HF_POSTPROCESS_WORKERS must be 'auto' or a positive integer."
            ) from exc
    if count < 1:
        raise ValueError("YPS_HF_POSTPROCESS_WORKERS must be at least one.")
    if mp.current_process().daemon:
        # A daemonic outer research worker cannot create children.  Preserve
        # correctness and make the fallback visible in diagnostics.
        count = 1
    return min(count, max(sample_count, 1))


def _fixed_contiguous_chunks(sample_count: int, worker_count: int) -> list[tuple[int, int]]:
    boundaries = np.linspace(0, sample_count, worker_count + 1, dtype=int)
    return [
        (int(left), int(right))
        for left, right in zip(boundaries[:-1], boundaries[1:], strict=True)
        if right > left
    ]


def _initialize_presentation_worker(
    model: HighFidelityModel,
    guard_metadata: dict[str, dict[str, float | str]],
    check_guards: bool,
) -> None:
    """Install immutable worker context without inheriting parent threads."""

    global _PRESENTATION_CHECK_GUARDS
    global _PRESENTATION_GUARD_METADATA
    global _PRESENTATION_MODEL
    _PRESENTATION_MODEL = model
    _PRESENTATION_GUARD_METADATA = guard_metadata
    _PRESENTATION_CHECK_GUARDS = check_guards


def _evaluate_presentation_chunk(
    task: tuple[int, np.ndarray, np.ndarray],
) -> dict[str, Any]:
    """Evaluate one fixed contiguous block and return it with global indices."""

    model = _PRESENTATION_MODEL
    guard_metadata = _PRESENTATION_GUARD_METADATA
    if model is None or guard_metadata is None:
        raise RuntimeError("HF presentation worker was not initialized.")
    start, time, state = task
    count = int(time.size)
    bob_quaternion = np.empty((count, 4))
    bob_attachment = np.empty((count, 3))
    cable_positions = {
        name: np.empty((count, branch.bead_indices.size + 2, 3))
        for name, branch in model.branches.items()
    }
    cable_velocities = {
        name: np.empty_like(values) for name, values in cable_positions.items()
    }
    cable_tension = {
        name: np.empty((count, branch.bead_indices.size + 1))
        for name, branch in model.branches.items()
    }
    cable_axial_force = {
        name: np.empty((count, branch.bead_indices.size + 1))
        for name, branch in model.branches.items()
    }
    reaction_a = np.empty((count, 3))
    reaction_b = np.empty((count, 3))
    energy = {key: np.empty(count) for key in _PRESENTATION_ENERGY_KEYS}
    geometry = {
        "contact_margin": np.empty(count),
        "bob_contact_margin": np.empty(count),
        "rod_self_contact_margin": np.empty(count),
        "minimum_segment": np.empty(count),
        "minimum_bending_turn_clearance": np.empty(count),
        "minimum_aerodynamic_chord_length": np.empty(count),
        "bob_socket_material_extent": np.empty(count),
        "bob_socket_radial_monotonicity": np.empty(count),
        "bob_socket_cut_clearance": np.empty(count),
        "junction_socket_material_extent": np.empty(count),
        "junction_socket_projective_opening": np.empty(count),
        "junction_socket_cut_clearance": np.empty(count),
        "quaternion_norm": np.empty(count),
    }
    unresolved: dict[str, Any] | None = None
    filled = count
    for local_index in range(count):
        global_index = start + local_index
        sample_time = float(time[local_index])
        sample_state = state[local_index]
        (
            particles,
            bob,
            quaternion,
            velocities,
            bob_v,
            omega,
        ) = model.unpack_state(sample_state)
        normalized = normalize_quaternion(quaternion)
        try:
            evaluation = model.evaluate(
                sample_time,
                particles,
                velocities,
                bob,
                bob_v,
                normalized,
                omega,
            )
        except FloatingPointError:
            if not _PRESENTATION_CHECK_GUARDS:
                raise
            components = model.guard_components(sample_time, sample_state)
            if not any(
                value <= float(guard_metadata[name]["tolerance"])
                for name, value in components.items()
            ):
                raise
            unresolved = {
                "index": global_index,
                "time": sample_time,
                "state": sample_state.copy(),
                "components": components,
            }
            filled = local_index
            break
        components = model.guard_components_from_evaluation(evaluation)
        if _PRESENTATION_CHECK_GUARDS and any(
            value <= float(guard_metadata[name]["tolerance"])
            for name, value in components.items()
        ):
            unresolved = {
                "index": global_index,
                "time": sample_time,
                "state": sample_state.copy(),
                "components": components,
            }
            filled = local_index
            break
        bob_quaternion[local_index] = normalized
        bob_attachment[local_index] = bob + rotate_body_vector(
            normalized, model.attachment_body
        )
        for name in model.branches:
            cable_positions[name][local_index] = evaluation.branch_positions[name]
            cable_velocities[name][local_index] = evaluation.branch_velocities[name]
            cable_tension[name][local_index] = evaluation.branch_tension[name]
            cable_axial_force[name][local_index] = evaluation.branch_axial_force[name]
        reaction_a[local_index] = -evaluation.support_force["support_A"]
        reaction_b[local_index] = -evaluation.support_force["support_B"]
        snapshot = model.energy_snapshot(
            sample_time,
            particles,
            velocities,
            bob,
            bob_v,
            normalized,
            omega,
            evaluation,
        )
        for key in _PRESENTATION_ENERGY_KEYS:
            energy[key][local_index] = snapshot[key]
        geometry["contact_margin"][local_index] = evaluation.contact_margin
        geometry["bob_contact_margin"][local_index] = evaluation.bob_contact_margin
        geometry["rod_self_contact_margin"][local_index] = (
            evaluation.rod_self_contact_margin
        )
        geometry["minimum_segment"][local_index] = evaluation.minimum_segment_length
        geometry["minimum_bending_turn_clearance"][local_index] = (
            evaluation.minimum_bending_turn_clearance
        )
        geometry["minimum_aerodynamic_chord_length"][local_index] = (
            evaluation.minimum_aerodynamic_chord_length
        )
        geometry["bob_socket_material_extent"][local_index] = (
            evaluation.bob_socket_material_extent
        )
        geometry["bob_socket_radial_monotonicity"][local_index] = (
            evaluation.bob_socket_radial_monotonicity
        )
        geometry["bob_socket_cut_clearance"][local_index] = (
            evaluation.bob_socket_cut_clearance
        )
        geometry["junction_socket_material_extent"][local_index] = (
            evaluation.junction_socket_material_extent
        )
        geometry["junction_socket_projective_opening"][local_index] = (
            evaluation.junction_socket_projective_opening
        )
        geometry["junction_socket_cut_clearance"][local_index] = (
            evaluation.junction_socket_cut_clearance
        )
        geometry["quaternion_norm"][local_index] = float(np.linalg.norm(quaternion))
    return {
        "start": start,
        "filled": filled,
        "bob_quaternion": bob_quaternion[:filled],
        "bob_attachment": bob_attachment[:filled],
        "cable_positions": {
            name: values[:filled] for name, values in cable_positions.items()
        },
        "cable_velocities": {
            name: values[:filled] for name, values in cable_velocities.items()
        },
        "cable_tension": {
            name: values[:filled] for name, values in cable_tension.items()
        },
        "cable_axial_force": {
            name: values[:filled] for name, values in cable_axial_force.items()
        },
        "reaction_a": reaction_a[:filled],
        "reaction_b": reaction_b[:filled],
        "energy": {name: values[:filled] for name, values in energy.items()},
        "geometry": {name: values[:filled] for name, values in geometry.items()},
        "unresolved": unresolved,
    }


def _presentation_samples(
    model: HighFidelityModel,
    time: np.ndarray,
    state: np.ndarray,
    guard_metadata: dict[str, dict[str, float | str]],
    *,
    check_guards: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None, int]:
    """Evaluate presentation samples in deterministic, index-stable chunks."""

    global _PRESENTATION_CHECK_GUARDS
    global _PRESENTATION_GUARD_METADATA
    global _PRESENTATION_MODEL
    sample_count = int(time.size)
    worker_count = _presentation_worker_count(sample_count)
    ranges = _fixed_contiguous_chunks(sample_count, worker_count)
    tasks = [
        (
            start,
            np.ascontiguousarray(time[start:stop]),
            np.ascontiguousarray(state[start:stop]),
        )
        for start, stop in ranges
    ]
    try:
        if worker_count == 1:
            _initialize_presentation_worker(model, guard_metadata, check_guards)
            chunks = [_evaluate_presentation_chunk(tasks[0])]
        else:
            context = mp.get_context("spawn")
            with ProcessPoolExecutor(
                max_workers=worker_count,
                mp_context=context,
                initializer=_initialize_presentation_worker,
                initargs=(model, guard_metadata, check_guards),
            ) as executor:
                chunks = list(
                    executor.map(
                        _evaluate_presentation_chunk,
                        tasks,
                        chunksize=1,
                    )
                )
    finally:
        _PRESENTATION_MODEL = None
        _PRESENTATION_GUARD_METADATA = None

    unresolved_candidates = [
        chunk["unresolved"]
        for chunk in chunks
        if chunk["unresolved"] is not None
    ]
    unresolved = (
        min(unresolved_candidates, key=lambda item: int(item["index"]))
        if unresolved_candidates
        else None
    )
    valid_count = int(unresolved["index"]) if unresolved is not None else sample_count

    bob_quaternion = np.empty((sample_count, 4))
    bob_attachment = np.empty((sample_count, 3))
    cable_positions = {
        name: np.empty((sample_count, branch.bead_indices.size + 2, 3))
        for name, branch in model.branches.items()
    }
    cable_velocities = {
        name: np.empty_like(values) for name, values in cable_positions.items()
    }
    cable_tension = {
        name: np.empty((sample_count, branch.bead_indices.size + 1))
        for name, branch in model.branches.items()
    }
    cable_axial_force = {
        name: np.empty((sample_count, branch.bead_indices.size + 1))
        for name, branch in model.branches.items()
    }
    reaction_a = np.empty((sample_count, 3))
    reaction_b = np.empty((sample_count, 3))
    energy = {key: np.empty(sample_count) for key in _PRESENTATION_ENERGY_KEYS}
    geometry_names = tuple(chunks[0]["geometry"])
    geometry = {name: np.empty(sample_count) for name in geometry_names}
    for chunk in chunks:
        start = int(chunk["start"])
        stop = start + int(chunk["filled"])
        destination = slice(start, stop)
        bob_quaternion[destination] = chunk["bob_quaternion"]
        bob_attachment[destination] = chunk["bob_attachment"]
        for name in model.branches:
            cable_positions[name][destination] = chunk["cable_positions"][name]
            cable_velocities[name][destination] = chunk["cable_velocities"][name]
            cable_tension[name][destination] = chunk["cable_tension"][name]
            cable_axial_force[name][destination] = chunk["cable_axial_force"][name]
        reaction_a[destination] = chunk["reaction_a"]
        reaction_b[destination] = chunk["reaction_b"]
        for name in _PRESENTATION_ENERGY_KEYS:
            energy[name][destination] = chunk["energy"][name]
        for name in geometry_names:
            geometry[name][destination] = chunk["geometry"][name]
    outputs: dict[str, Any] = {
        "bob_quaternion": bob_quaternion[:valid_count],
        "bob_attachment": bob_attachment[:valid_count],
        "cable_positions": {
            name: values[:valid_count] for name, values in cable_positions.items()
        },
        "cable_velocities": {
            name: values[:valid_count] for name, values in cable_velocities.items()
        },
        "cable_tension": {
            name: values[:valid_count] for name, values in cable_tension.items()
        },
        "cable_axial_force": {
            name: values[:valid_count] for name, values in cable_axial_force.items()
        },
        "reaction_a": reaction_a[:valid_count],
        "reaction_b": reaction_b[:valid_count],
        "energy": {name: values[:valid_count] for name, values in energy.items()},
        "geometry": {
            name: values[:valid_count] for name, values in geometry.items()
        },
    }
    return outputs, unresolved, worker_count


def _integrate_with_accepted_step_cap(
    model: HighFidelityModel,
    initial_state: np.ndarray,
    *,
    t_end: float,
    output_time: np.ndarray,
    method: str,
    rtol: float,
    atol: np.ndarray,
    max_step: float,
    jac_sparsity: Any,
    guard_names: tuple[str, ...],
    guard_metadata: dict[str, dict[str, float | str]],
    guard_components: Callable[[float, np.ndarray], dict[str, float]],
    accepted_step_cap: int,
    terminal_time_tolerance: float,
) -> _BoundedIntegrationTrace:
    """Integrate one HF run while enforcing its accepted-step memory cap.

    ``solve_ivp(dense_output=True)`` retains an interpolation object for every
    accepted step and exposes no callback that can stop before an unbounded
    internal-step list is allocated.  Driving SciPy's public ``Radau``/``BDF``
    solver classes one accepted step at a time makes the configuration resource
    envelope an actual runtime invariant.  Only the current dense interpolant
    is retained; presentation samples are materialised immediately.
    """

    solver_class = {"Radau": Radau, "BDF": BDF}.get(method)
    if solver_class is None:
        raise ValueError(f"Unsupported bounded HF integrator {method!r}.")
    solver = solver_class(
        model.rhs,
        0.0,
        np.asarray(initial_state, dtype=float),
        t_end,
        max_step=max_step,
        rtol=rtol,
        atol=atol,
        jac_sparsity=jac_sparsity,
        vectorized=False,
    )

    accepted_time = [0.0]
    accepted_state = [np.asarray(initial_state, dtype=float).copy()]
    presentation = np.empty(
        (output_time.size, np.asarray(initial_state).size), dtype=float
    )
    presentation_count = 0
    while (
        presentation_count < output_time.size
        and float(output_time[presentation_count]) == 0.0
    ):
        presentation[presentation_count] = initial_state
        presentation_count += 1

    previous_components = guard_components(0.0, np.asarray(initial_state))
    event_time: float | None = None
    event_state: np.ndarray | None = None
    event_guard_names: tuple[str, ...] = ()
    accepted_steps = 0
    while solver.status == "running":
        if accepted_steps >= accepted_step_cap:
            raise RuntimeError(
                "HF_ACCEPTED_STEP_BUDGET_EXCEEDED: the bounded integrator "
                f"reached {accepted_steps} accepted steps (cap={accepted_step_cap}) "
                f"at t={solver.t:.17g} s before t_end={t_end:.17g} s."
            )
        left_time = float(solver.t)
        message = solver.step()
        if solver.status == "failed":
            raise RuntimeError(
                "HF integration failed at "
                f"t={solver.t:.17g} s: {message or 'unknown solver failure'}"
            )
        accepted_steps += 1
        right_time = float(solver.t)
        right_state = np.asarray(solver.y, dtype=float).copy()
        dense = solver.dense_output()
        current_components = guard_components(right_time, right_state)

        root_candidates: list[tuple[float, str]] = []
        for name in guard_names:
            scale = float(guard_metadata[name]["scale"])
            left_value = float(previous_components[name]) / scale
            right_value = float(current_components[name]) / scale
            if left_value > 0.0 and right_value <= 0.0:
                if right_value == 0.0:
                    root_candidates.append((right_time, name))
                    continue

                def normalized_guard(
                    sample_time: float,
                    *,
                    component_name: str = name,
                    dense_output: Any = dense,
                ) -> float:
                    sample_state = np.asarray(
                        dense_output(sample_time), dtype=float
                    )
                    return float(
                        guard_components(sample_time, sample_state)[component_name]
                    ) / float(guard_metadata[component_name]["scale"])

                root_time = float(
                    brentq(
                        normalized_guard,
                        left_time,
                        right_time,
                        xtol=max(
                            terminal_time_tolerance / 1024.0,
                            np.finfo(float).tiny,
                        ),
                        rtol=4.0 * np.finfo(float).eps,
                    )
                )
                root_candidates.append((root_time, name))

        sample_limit = right_time
        sample_side = "right"
        if root_candidates:
            event_time = min(item[0] for item in root_candidates)
            event_guard_names = tuple(
                sorted(
                    name
                    for root_time, name in root_candidates
                    if abs(root_time - event_time) <= terminal_time_tolerance
                )
            )
            event_state = np.asarray(dense(event_time), dtype=float)
            accepted_time.append(event_time)
            accepted_state.append(event_state.copy())
            sample_limit = event_time - (
                32.0
                * np.finfo(float).eps
                * max(1.0, abs(event_time))
            )
            sample_side = "left"
        else:
            accepted_time.append(right_time)
            accepted_state.append(right_state)

        sample_end = int(
            np.searchsorted(output_time, sample_limit, side=sample_side)
        )
        if sample_end > presentation_count:
            sample_times = output_time[presentation_count:sample_end]
            sampled = np.asarray(dense(sample_times), dtype=float)
            if sampled.ndim == 1:
                sampled = sampled[:, None]
            presentation[presentation_count:sample_end] = sampled.T
            presentation_count = sample_end
        if event_time is not None:
            break
        previous_components = current_components

    if event_time is None and solver.status != "finished":
        raise RuntimeError(
            f"HF bounded integrator ended with unexpected status {solver.status!r}."
        )
    if event_time is None and presentation_count != output_time.size:
        raise RuntimeError(
            "HF bounded integrator did not populate the complete presentation grid: "
            f"{presentation_count}/{output_time.size} samples."
        )
    return _BoundedIntegrationTrace(
        accepted_time=np.asarray(accepted_time, dtype=float),
        accepted_state=np.asarray(accepted_state, dtype=float),
        presentation_state=presentation[:presentation_count],
        event_time=event_time,
        event_state=event_state,
        event_guard_names=event_guard_names,
        nfev=int(solver.nfev),
        njev=int(solver.njev),
        nlu=int(solver.nlu),
    )


def _initial_bob_target(cfg: SimulationConfig, model: HighFidelityModel) -> tuple[np.ndarray, bool]:
    mode = cfg.initial_condition.type
    if mode == "cartesian_release":
        if cfg.initial_condition.bob_position is None:
            raise ValueError("cartesian_release requires initial_condition.bob_position.")
        return as_vector3(cfg.initial_condition.bob_position, default_unit="m"), True
    if mode == "static_equilibrium":
        return model.reference_bob_position.copy(), False
    raise ValueError(
        "The independent HF backend currently supports only static_equilibrium "
        "and held cartesian_release preparation.  Other initial-state formats "
        "remain backend-native legacy inputs and are not silently projected."
    )


def _geometric_direct_state(
    cfg: SimulationConfig, model: HighFidelityModel
) -> PreparationResult:
    """Build the explicitly requested non-equilibrium material geometry."""

    if cfg.initial_condition.bob_position is None or cfg.initial_condition.junction_position is None:
        raise ValueError(
            "geometric_direct_release requires bob_position and junction_position."
        )
    bob = as_vector3(cfg.initial_condition.bob_position, default_unit="m")
    junction = as_vector3(cfg.initial_condition.junction_position, default_unit="m")
    bob_velocity = as_vector3(cfg.initial_condition.bob_velocity, default_unit="m/s")
    junction_velocity = as_vector3(
        cfg.initial_condition.junction_velocity, default_unit="m/s"
    )
    angular_velocity = as_vector3(
        cfg.initial_condition.bob_angular_velocity, default_unit="rad/s"
    )
    quaternion = np.array([1.0, 0.0, 0.0, 0.0])
    attachment = bob + model.attachment_body
    attachment_velocity = bob_velocity + np.cross(
        angular_velocity, model.attachment_body
    )
    particles = model.reference_particle_positions.copy()
    particle_velocity = np.zeros_like(particles)
    particles[model.junction_index] = junction
    particle_velocity[model.junction_index] = junction_velocity

    for branch in model.branches.values():
        if branch.start_kind == "support_A":
            start, start_velocity, _ = model.support_motion["support_A"].state(0.0)
        elif branch.start_kind == "support_B":
            start, start_velocity, _ = model.support_motion["support_B"].state(0.0)
        else:
            start, start_velocity = junction, junction_velocity
        if branch.end_kind == "junction":
            end, end_velocity = junction, junction_velocity
        else:
            end, end_velocity = attachment, attachment_velocity
        chord_length = float(np.linalg.norm(end - start))
        material_length = float(np.sum(branch.segment_rest_length))
        geometry_tolerance = (
            128.0
            * np.finfo(float).eps
            * max(model.characteristic_length, material_length, chord_length)
        )
        if chord_length < material_length - geometry_tolerance:
            raise ValueError(
                "geometric_direct_release cannot infer a complete compressed rod "
                f"state for {branch.name}: endpoint chord={chord_length:.16g} m "
                f"is shorter than material rest length={material_length:.16g} m. "
                "Use held_endpoint_equilibrium_release; this HF backend does not "
                "accept an inferred compressed straight material state."
            )
        for local, particle_index in enumerate(branch.bead_indices):
            alpha = (local + 0.5) / branch.bead_indices.size
            particles[particle_index] = (1.0 - alpha) * start + alpha * end
            particle_velocity[particle_index] = (
                (1.0 - alpha) * start_velocity + alpha * end_velocity
            )

    evaluation = model.evaluate(
        0.0,
        particles,
        particle_velocity,
        bob,
        bob_velocity,
        quaternion,
        angular_velocity,
        include_aero=True,
        compute_contact=True,
    )
    initial_force = float(
        max(
            np.max(np.abs(evaluation.particle_force)),
            np.max(np.abs(evaluation.bob_force)),
        )
    )
    return PreparationResult(
        state=model.pack_state(
            particles,
            bob,
            quaternion,
            particle_velocity,
            bob_velocity,
            angular_velocity,
        ),
        residual_inf_N=initial_force,
        iterations=0,
        bob_held=False,
        preparation_mode="geometric_direct_release_non_equilibrium",
    )


def _gravity_plane_arc_seed(
    start: np.ndarray,
    end: np.ndarray,
    material_fractions: np.ndarray,
    material_length: float,
    gravity_direction: np.ndarray,
    fallback_plane_direction: np.ndarray,
) -> np.ndarray:
    """Seed a polygonal bowed rod with its endpoints and material length fixed."""

    first = np.asarray(start, dtype=float)
    second = np.asarray(end, dtype=float)
    fractions = np.asarray(material_fractions, dtype=float)
    chord = second - first
    chord_length = float(np.linalg.norm(chord))
    if chord_length <= 0.0:
        raise ValueError("Held rod endpoints must be distinct.")
    base = first[None, :] + fractions[:, None] * chord[None, :]
    tolerance = 128.0 * np.finfo(float).eps * max(material_length, chord_length)
    if chord_length >= material_length - tolerance:
        return base

    chord_direction = chord / chord_length
    bow_direction = gravity_direction - np.dot(
        gravity_direction, chord_direction
    ) * chord_direction
    bow_norm = float(np.linalg.norm(bow_direction))
    if bow_norm <= 64.0 * np.finfo(float).eps:
        # When gravity and the chord are parallel, the apparatus support axis
        # selects the otherwise degenerate gravity plane.  If it cannot do so,
        # fail closed instead of hiding an arbitrary coordinate-axis imperfection.
        axis = np.asarray(fallback_plane_direction, dtype=float)
        bow_direction = axis - np.dot(axis, chord_direction) * chord_direction
        bow_norm = float(np.linalg.norm(bow_direction))
        if bow_norm <= 64.0 * np.finfo(float).eps:
            raise ValueError(
                "Compressed held rod has no gravity/support plane to select a "
                "deterministic bowed material seed."
            )
    bow_direction /= bow_norm
    shape = np.sin(np.pi * fractions)

    def polygon_length(amplitude: float) -> float:
        internal = base + amplitude * shape[:, None] * bow_direction[None, :]
        points = np.vstack([first, internal, second])
        return float(np.sum(np.linalg.norm(points[1:] - points[:-1], axis=1)))

    upper_amplitude = max(material_length, chord_length)
    while polygon_length(upper_amplitude) < material_length:
        upper_amplitude *= 2.0
        if not np.isfinite(upper_amplitude):
            raise FloatingPointError("Could not bracket a finite bowed-rod seed.")
    amplitude = brentq(
        lambda trial: polygon_length(trial) - material_length,
        0.0,
        upper_amplitude,
        xtol=max(1.0e-14 * material_length, np.finfo(float).tiny),
        rtol=4.0 * np.finfo(float).eps,
    )
    return base + amplitude * shape[:, None] * bow_direction[None, :]


def _held_endpoint_equilibrium_state(
    cfg: SimulationConfig, model: HighFidelityModel
) -> PreparationResult:
    """Prepare a stable bilateral-rod minimum with all endpoint DOFs held."""

    if (
        cfg.initial_condition.bob_position is None
        or cfg.initial_condition.junction_position is None
    ):
        raise ValueError(
            "held_endpoint_equilibrium_release requires bob_position and "
            "junction_position."
        )
    if model.compression_regularization_scale != 1.0:
        raise ValueError(
            "held_endpoint_equilibrium_release requires the bilateral finite-rod "
            "compression_regularization_scale=1."
        )
    if cfg.solver.static.method != "energy_minimize":
        raise ValueError(
            "held_endpoint_equilibrium_release requires static.method=energy_minimize."
        )

    bob = as_vector3(cfg.initial_condition.bob_position, default_unit="m")
    junction = as_vector3(cfg.initial_condition.junction_position, default_unit="m")
    quaternion = np.array([1.0, 0.0, 0.0, 0.0])
    attachment = bob + model.attachment_body
    particles_template = model.reference_particle_positions.copy()
    particles_template[model.junction_index] = junction
    support_a, support_a_velocity, _ = model.support_motion["support_A"].state(0.0)
    support_b, support_b_velocity, _ = model.support_motion["support_B"].state(0.0)
    if np.any(support_a_velocity != 0.0) or np.any(support_b_velocity != 0.0):
        raise ValueError(
            "Held conservative preparation requires zero support velocity at t=0."
        )
    support_axis = support_b - support_a

    branch_seed_data: dict[str, dict[str, np.ndarray]] = {}
    compressed_names: list[str] = []
    for branch in model.branches.values():
        if branch.start_kind == "support_A":
            start = support_a
        elif branch.start_kind == "support_B":
            start = support_b
        else:
            start = junction
        end = junction if branch.end_kind == "junction" else attachment
        material_length = float(np.sum(branch.segment_rest_length))
        fractions = np.cumsum(branch.segment_rest_length)[:-1] / material_length
        straight = start[None, :] + fractions[:, None] * (end - start)[None, :]
        gravity_seed = _gravity_plane_arc_seed(
            start,
            end,
            fractions,
            material_length,
            model.gravity_direction,
            support_axis,
        )
        displacement = gravity_seed - straight
        if float(np.max(np.linalg.norm(displacement, axis=1))) > (
            256.0 * np.finfo(float).eps * model.characteristic_length
        ):
            compressed_names.append(branch.name)

        chord = end - start
        chord_norm = float(np.linalg.norm(chord))
        perturbation = np.zeros_like(gravity_seed)
        if chord_norm > 0.0 and displacement.size:
            largest = int(np.argmax(np.linalg.norm(displacement, axis=1)))
            plane_vector = displacement[largest]
            normal = np.cross(chord / chord_norm, plane_vector)
            normal_norm = float(np.linalg.norm(normal))
            if normal_norm <= 64.0 * np.finfo(float).eps * model.characteristic_length:
                normal = np.cross(chord / chord_norm, support_axis)
                normal_norm = float(np.linalg.norm(normal))
            if normal_norm > 64.0 * np.finfo(float).eps * model.characteristic_length:
                normal /= normal_norm
                amplitude = 0.05 * max(
                    float(np.max(np.linalg.norm(displacement, axis=1))),
                    1.0e-3 * material_length,
                )
                perturbation = (
                    amplitude
                    * np.sin(2.0 * np.pi * fractions)[:, None]
                    * normal[None, :]
                )
        branch_seed_data[branch.name] = {
            "straight": straight,
            "gravity": gravity_seed,
            "perturbation": perturbation,
        }

    seed_definitions: list[tuple[str, frozenset[str], float]] = [
        ("gravity_plane", frozenset(), 0.0),
        ("mirror_all_compressed", frozenset(compressed_names), 0.0),
    ]
    seed_definitions.extend(
        (f"mirror_{name}", frozenset({name}), 0.0)
        for name in compressed_names
    )
    seed_definitions.extend(
        [
            ("gravity_plane_out_of_plane_plus", frozenset(), 1.0),
            ("gravity_plane_out_of_plane_minus", frozenset(), -1.0),
        ]
    )

    free_indices = np.concatenate(
        [branch.bead_indices for branch in model.branches.values()]
    )
    seed_candidates: list[tuple[str, np.ndarray]] = []
    duplicate_tolerance = (
        256.0
        * np.finfo(float).eps
        * model.characteristic_length
        * np.sqrt(3.0 * free_indices.size)
    )
    for label, mirrored, perturbation_sign in seed_definitions:
        seed_particles = particles_template.copy()
        for branch in model.branches.values():
            data = branch_seed_data[branch.name]
            positions = data["gravity"].copy()
            if branch.name in mirrored:
                positions = 2.0 * data["straight"] - positions
            positions += perturbation_sign * data["perturbation"]
            seed_particles[branch.bead_indices] = positions
        candidate = seed_particles[free_indices].reshape(-1)
        if any(
            np.linalg.norm(candidate - existing) <= duplicate_tolerance
            for _, existing in seed_candidates
        ):
            continue
        seed_candidates.append((label, candidate))

    zero_particle_velocity = np.zeros_like(particles_template)
    zero3 = np.zeros(3, dtype=float)
    free_mass_gravity = (
        model.particle_mass[free_indices, None] * model.gravity[None, :]
    )

    def unpack(candidate: np.ndarray) -> np.ndarray:
        particles = particles_template.copy()
        particles[free_indices] = candidate.reshape(free_indices.size, 3)
        return particles

    def objective(
        candidate: np.ndarray, gravity_fraction: float = 1.0
    ) -> tuple[float, np.ndarray]:
        particles = unpack(candidate)
        try:
            evaluation = model.evaluate(
                0.0,
                particles,
                zero_particle_velocity,
                bob,
                zero3,
                quaternion,
                zero3,
                include_aero=False,
                compute_contact=False,
            )
            gravitational_free = -float(
                np.sum(
                    model.particle_mass[free_indices, None]
                    * particles[free_indices]
                    * model.gravity[None, :]
                )
            )
            energy = (
                evaluation.axial_energy
                + evaluation.bending_energy
                + gravity_fraction * gravitational_free
            )
            force = evaluation.particle_force[free_indices] - (
                1.0 - gravity_fraction
            ) * free_mass_gravity
            gradient = -force.reshape(-1)
            if not np.isfinite(energy) or not np.all(np.isfinite(gradient)):
                raise FloatingPointError
            return float(energy), gradient
        except (FloatingPointError, ValueError):
            return 1.0e100, np.zeros_like(candidate)

    requested_tolerance = float(
        to_si(cfg.solver.static.force_tolerance, default_unit="N")
    )
    continuation_steps = int(cfg.solver.static.continuation_steps)
    max_iterations = int(cfg.solver.static.max_iterations)
    line_search_min = float(cfg.solver.static.line_search_min)
    max_line_search_steps = max(
        5, int(np.ceil(-np.log2(line_search_min))) + 1
    )
    gradient_tolerance = min(
        requested_tolerance, 1.0e-10 * model.force_scale
    )

    minimum_rest_length = min(
        float(np.min(branch.segment_rest_length))
        for branch in model.branches.values()
    )
    stiffness_scale = max(
        model.force_scale / model.characteristic_length,
        *(
            branch.ea / float(np.min(branch.segment_rest_length))
            for branch in model.branches.values()
        ),
        *(
            branch.ei / float(np.min(branch.segment_rest_length)) ** 3
            for branch in model.branches.values()
        ),
    )
    hessian_tolerance = 1.0e-7 * stiffness_scale
    hessian_step = max(
        1.0e-6 * model.characteristic_length,
        256.0 * np.finfo(float).eps * model.characteristic_length,
    )
    hessian_worker_count = max(1, min(8, os.cpu_count() or 1))

    def minimum_hessian_eigenpair(
        candidate: np.ndarray,
    ) -> tuple[float, np.ndarray] | None:
        dimension = candidate.size

        def hessian_vector(vector: np.ndarray) -> np.ndarray:
            vector_array = np.asarray(vector, dtype=float)
            vector_norm = float(np.linalg.norm(vector_array))
            if vector_norm == 0.0:
                return np.zeros_like(vector_array)
            direction = vector_array / vector_norm
            plus_gradient = objective(
                candidate + hessian_step * direction
            )[1]
            minus_gradient = objective(
                candidate - hessian_step * direction
            )[1]
            return (
                (plus_gradient - minus_gradient)
                / (2.0 * hessian_step)
                * vector_norm
            )

        try:
            # The production 24/24/32 mesh has 80 free material beads, hence
            # a 240-dimensional held-endpoint Hessian.  ARPACK's smallest-
            # algebraic eigenpair iteration is unreliable for this modest,
            # strongly ill-conditioned rod Hessian (it can return no pair even
            # after the force residual has converged).  A dense symmetric
            # finite-difference Hessian is still small at this size and gives a
            # deterministic PSD audit for the actual research configuration.
            if dimension <= 384:
                def finite_difference_column(column: int) -> np.ndarray:
                    basis = np.zeros(dimension, dtype=float)
                    basis[column] = 1.0
                    return hessian_vector(basis)

                if hessian_worker_count == 1:
                    columns = [
                        finite_difference_column(column)
                        for column in range(dimension)
                    ]
                else:
                    with ThreadPoolExecutor(
                        max_workers=hessian_worker_count,
                        thread_name_prefix="yps-hf-hessian",
                    ) as executor:
                        columns = list(
                            executor.map(
                                finite_difference_column,
                                range(dimension),
                            )
                        )
                hessian = np.column_stack(columns)
                hessian = 0.5 * (hessian + hessian.T)
                eigenvalues, eigenvectors = np.linalg.eigh(hessian)
                return float(eigenvalues[0]), eigenvectors[:, 0]
            operator = LinearOperator(
                (dimension, dimension),
                matvec=hessian_vector,
                dtype=float,
            )
            initial = np.linspace(1.0, 2.0, dimension, dtype=float)
            initial /= np.linalg.norm(initial)
            eigenvalues, eigenvectors = eigsh(
                operator,
                k=1,
                which="SA",
                v0=initial,
                tol=1.0e-3,
                maxiter=80,
            )
            return float(eigenvalues[0]), eigenvectors[:, 0]
        except (ArpackNoConvergence, FloatingPointError, ValueError):
            return None

    total_iterations = 0
    candidate_records: list[dict[str, Any]] = []
    stable_candidates: list[tuple[float, float, int, np.ndarray, dict[str, Any]]] = []
    guard_metadata = model.guard_component_metadata()
    for seed_index, (seed_label, seed) in enumerate(seed_candidates):
        candidate = seed.copy()
        seed_iterations = 0
        optimizer_messages: list[str] = []
        for continuation_index in range(continuation_steps):
            gravity_fraction = (continuation_index + 1) / continuation_steps
            result = minimize(
                lambda trial, load=gravity_fraction: objective(trial, load)[0],
                candidate,
                jac=lambda trial, load=gravity_fraction: objective(trial, load)[1],
                method="L-BFGS-B",
                options={
                    "maxiter": max_iterations,
                    "ftol": 0.0,
                    "gtol": gradient_tolerance,
                    "maxls": max_line_search_steps,
                    "maxcor": 30,
                },
            )
            candidate = np.asarray(result.x, dtype=float)
            seed_iterations += int(result.nit)
            optimizer_messages.append(str(result.message))

        energy, gradient = objective(candidate)
        residual = float(np.max(np.abs(gradient)))
        if np.isfinite(residual) and residual > requested_tolerance:
            force_root = root(
                lambda trial: objective(trial)[1],
                candidate,
                method="krylov",
                options={
                    "maxiter": max(20, 2 * max_iterations),
                    "fatol": 0.2 * requested_tolerance,
                },
            )
            polished = np.asarray(force_root.x, dtype=float)
            polished_energy, polished_gradient = objective(polished)
            polished_residual = float(np.max(np.abs(polished_gradient)))
            energy_tolerance = 1.0e-12 * max(
                abs(energy), model.force_scale * model.characteristic_length
            )
            if (
                np.all(np.isfinite(polished))
                and polished_residual < residual
                and polished_energy <= energy + energy_tolerance
            ):
                candidate = polished
                energy = polished_energy
                gradient = polished_gradient
                residual = polished_residual
                seed_iterations += int(getattr(force_root, "nit", 0))

        # Several deliberately perturbed seeds can converge to the same
        # force-balanced minimum.  Repeating a 240-dimensional Hessian audit
        # for states that differ by less than the finite-difference resolution
        # adds no information.  Only those numerically duplicate states reuse
        # the earlier audit decision; geometrically distinct higher-energy
        # seeds are still audited so a force-balanced saddle cannot be hidden.
        stability_audit_skipped_reason: str | None = None
        duplicate_candidate_tolerance = (
            hessian_step * np.sqrt(float(candidate.size))
        )
        if any(
            np.linalg.norm(candidate - audited_candidate)
            <= duplicate_candidate_tolerance
            for _, _, _, audited_candidate, _ in stable_candidates
        ):
            stability_audit_skipped_reason = (
                "duplicate_of_existing_psd_stable_candidate"
            )
        eigenpair = (
            minimum_hessian_eigenpair(candidate)
            if (
                stability_audit_skipped_reason is None
                and np.isfinite(residual)
                and residual <= requested_tolerance
            )
            else None
        )
        escaped_negative_curvature = False
        if eigenpair is not None and eigenpair[0] < -hessian_tolerance:
            eigenvalue, eigenvector = eigenpair
            base_energy = energy
            energy_tolerance = 1.0e-12 * max(
                abs(base_energy), model.force_scale * model.characteristic_length
            )
            initial_displacement = min(
                0.05 * model.characteristic_length,
                0.25 * minimum_rest_length,
            )
            escaped: np.ndarray | None = None
            fraction = 1.0
            while fraction >= line_search_min:
                for sign in (-1.0, 1.0):
                    trial = (
                        candidate
                        + sign * fraction * initial_displacement * eigenvector
                    )
                    if objective(trial)[0] < base_energy - energy_tolerance:
                        escaped = trial
                        break
                if escaped is not None:
                    break
                fraction *= 0.5
            if escaped is not None:
                escaped_result = minimize(
                    lambda trial: objective(trial)[0],
                    escaped,
                    jac=lambda trial: objective(trial)[1],
                    method="L-BFGS-B",
                    options={
                        "maxiter": max_iterations,
                        "ftol": 0.0,
                        "gtol": gradient_tolerance,
                        "maxls": max_line_search_steps,
                        "maxcor": 30,
                    },
                )
                candidate = np.asarray(escaped_result.x, dtype=float)
                energy, gradient = objective(candidate)
                residual = float(np.max(np.abs(gradient)))
                seed_iterations += int(escaped_result.nit)
                eigenpair = (
                    minimum_hessian_eigenpair(candidate)
                    if residual <= requested_tolerance
                    else None
                )
                escaped_negative_curvature = True

        particles = unpack(candidate)
        guard_state = model.pack_state(
            particles,
            bob,
            quaternion,
            zero_particle_velocity,
            zero3,
            zero3,
        )
        try:
            guard_components = model.guard_components(0.0, guard_state)
            guards_valid = all(
                value > float(guard_metadata[name]["tolerance"])
                for name, value in guard_components.items()
            )
        except (FloatingPointError, ValueError):
            guard_components = {}
            guards_valid = False
        eigenvalue = None if eigenpair is None else float(eigenpair[0])
        stable = (
            np.isfinite(energy)
            and np.isfinite(residual)
            and residual <= requested_tolerance
            and eigenvalue is not None
            and eigenvalue >= -hessian_tolerance
            and guards_valid
        )
        record = {
            "seed": seed_label,
            "iterations": seed_iterations,
            "energy_J": float(energy),
            "free_material_residual_inf_N": residual,
            "minimum_hessian_eigenvalue_N_per_m": eigenvalue,
            "stability_audit_skipped_reason": stability_audit_skipped_reason,
            "escaped_negative_curvature": escaped_negative_curvature,
            "guards_valid": guards_valid,
            "minimum_normalized_guard_margin": (
                min(
                    value
                    / float(guard_metadata[name]["scale"])
                    for name, value in guard_components.items()
                )
                if guard_components
                else None
            ),
            "optimizer_messages": optimizer_messages,
            "accepted_stable_candidate": stable,
        }
        candidate_records.append(record)
        total_iterations += seed_iterations
        if stable:
            stable_candidates.append(
                (float(energy), residual, seed_index, candidate.copy(), record)
            )

    if not stable_candidates:
        raise RuntimeError(
            "HF held-endpoint preparation found no force-balanced, PSD-stable, "
            f"guard-valid conservative minimum: {candidate_records}"
        )
    _, residual, _, candidate, selected_record = min(
        stable_candidates, key=lambda item: (item[0], item[1], item[2])
    )
    particles = unpack(candidate)
    equilibrium = model.evaluate(
        0.0,
        particles,
        zero_particle_velocity,
        bob,
        zero3,
        quaternion,
        zero3,
        include_aero=False,
        compute_contact=False,
    )

    bob_velocity = as_vector3(cfg.initial_condition.bob_velocity, default_unit="m/s")
    junction_velocity = as_vector3(
        cfg.initial_condition.junction_velocity, default_unit="m/s"
    )
    angular_velocity = as_vector3(
        cfg.initial_condition.bob_angular_velocity, default_unit="rad/s"
    )
    attachment_velocity = bob_velocity + np.cross(
        angular_velocity, model.attachment_body
    )
    particle_velocity = np.zeros_like(particles)
    particle_velocity[model.junction_index] = junction_velocity
    for branch in model.branches.values():
        if branch.start_kind == "support_A":
            start_velocity = support_a_velocity
        elif branch.start_kind == "support_B":
            start_velocity = support_b_velocity
        else:
            start_velocity = junction_velocity
        end_velocity = (
            junction_velocity
            if branch.end_kind == "junction"
            else attachment_velocity
        )
        material_length = float(np.sum(branch.segment_rest_length))
        fractions = np.cumsum(branch.segment_rest_length)[:-1] / material_length
        particle_velocity[branch.bead_indices] = (
            (1.0 - fractions[:, None]) * start_velocity[None, :]
            + fractions[:, None] * end_velocity[None, :]
        )

    actual_release = model.evaluate(
        0.0,
        particles,
        particle_velocity,
        bob,
        bob_velocity,
        quaternion,
        angular_velocity,
        include_aero=True,
        compute_contact=False,
    )
    actual_release_free_force = float(
        np.max(np.abs(actual_release.particle_force[free_indices]))
    )
    has_prescribed_release_velocity = any(
        np.any(vector != 0.0)
        for vector in (
            bob_velocity,
            junction_velocity,
            angular_velocity,
            support_a_velocity,
            support_b_velocity,
        )
    )
    audit = {
        "protocol": "HELD_ENDPOINT_STABLE_BILATERAL_EQUILIBRIUM_V1",
        "fixed_dofs": [
            "junction_position",
            "bob_com_position",
            "bob_orientation",
            "bob_attachment_position",
            "support_A_position",
            "support_B_position",
        ],
        "static_free_material_residual_inf_N": residual,
        "static_fixture_reaction_force_world_N": {
            "support_A": (-equilibrium.support_force["support_A"]).tolist(),
            "support_B": (-equilibrium.support_force["support_B"]).tolist(),
            "junction": (
                -equilibrium.particle_force[model.junction_index]
            ).tolist(),
            "bob_com": (-equilibrium.bob_force).tolist(),
        },
        "static_fixture_reaction_torque_world_Nm": {
            "bob": (-equilibrium.bob_torque).tolist(),
        },
        "actual_release_free_material_net_force_inf_N": (
            actual_release_free_force
        ),
        "actual_release_junction_net_force_world_N": actual_release.particle_force[
            model.junction_index
        ].tolist(),
        "actual_release_bob_net_force_world_N": actual_release.bob_force.tolist(),
        "actual_release_bob_net_torque_world_Nm": (
            actual_release.bob_torque.tolist()
        ),
        "minimum_hessian_eigenvalue_N_per_m": selected_record[
            "minimum_hessian_eigenvalue_N_per_m"
        ],
        "hessian_tolerance_N_per_m": hessian_tolerance,
        "hessian_parallel_worker_count": hessian_worker_count,
        "stability_class": "PSD_STABLE_LOCAL_MINIMUM",
        "seed_candidate_count": len(seed_candidates),
        "selected_seed": selected_record["seed"],
        "seed_geometry": {
            name: {
                "compressed_chord": name in compressed_names,
                "gravity_seed_max_offset_m": float(
                    np.max(
                        np.linalg.norm(
                            data["gravity"] - data["straight"], axis=1
                        )
                    )
                ),
                "gravity_seed_direction_world": (
                    (
                        data["gravity"] - data["straight"]
                    )[
                        int(
                            np.argmax(
                                np.linalg.norm(
                                    data["gravity"] - data["straight"], axis=1
                                )
                            )
                        )
                    ]
                    / max(
                        float(
                            np.max(
                                np.linalg.norm(
                                    data["gravity"] - data["straight"], axis=1
                                )
                            )
                        ),
                        np.finfo(float).tiny,
                    )
                ).tolist(),
                "out_of_plane_perturbation_max_m": float(
                    np.max(np.linalg.norm(data["perturbation"], axis=1))
                ),
            }
            for name, data in branch_seed_data.items()
        },
        "candidate_records": candidate_records,
        "gravity_continuation_steps": continuation_steps,
        "negative_curvature_line_search_min_fraction": line_search_min,
        "total_optimizer_iterations": total_iterations,
    }
    return PreparationResult(
        state=model.pack_state(
            particles,
            bob,
            quaternion,
            particle_velocity,
            bob_velocity,
            angular_velocity,
        ),
        residual_inf_N=residual,
        iterations=total_iterations,
        bob_held=True,
        preparation_mode=(
            "held_endpoint_bilateral_stable_equilibrium"
            if not has_prescribed_release_velocity
            else "held_endpoint_stable_equilibrium_with_prescribed_release_velocity"
        ),
        audit=audit,
    )


def prepare_initial_state(cfg: SimulationConfig, model: HighFidelityModel) -> PreparationResult:
    if cfg.initial_condition.type == "geometric_direct_release":
        return _geometric_direct_state(cfg, model)
    if cfg.initial_condition.type == "held_endpoint_equilibrium_release":
        return _held_endpoint_equilibrium_state(cfg, model)
    bob_target, bob_held = _initial_bob_target(cfg, model)
    particles0 = model.reference_particle_positions.copy()
    # Re-seed the lower material beads on the actual held-bob attachment line.
    attachment0 = bob_target + model.attachment_body
    lower = model.branches["lower"]
    junction0 = particles0[model.junction_index]
    for local, particle_index in enumerate(lower.bead_indices):
        alpha = (local + 0.5) / lower.bead_indices.size
        particles0[particle_index] = (1.0 - alpha) * junction0 + alpha * attachment0
    quaternion0 = np.array([1.0, 0.0, 0.0, 0.0])
    zero_particle_velocity = np.zeros_like(particles0)
    zero3 = np.zeros(3, dtype=float)

    if bob_held:
        x0 = particles0.reshape(-1)
    else:
        x0 = np.concatenate([particles0.reshape(-1), bob_target])

    def unpack(candidate: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        particles = candidate[: model.position_size].reshape(model.particle_count, 3)
        bob = bob_target if bob_held else candidate[model.position_size : model.position_size + 3]
        return particles, bob

    def objective(candidate: np.ndarray) -> tuple[float, np.ndarray]:
        particles, bob = unpack(candidate)
        try:
            evaluation = model.evaluate(
                0.0,
                particles,
                zero_particle_velocity,
                bob,
                zero3,
                quaternion0,
                zero3,
                include_aero=False,
                compute_contact=False,
            )
            energy = model.energy_snapshot(
                0.0,
                particles,
                zero_particle_velocity,
                bob,
                zero3,
                quaternion0,
                zero3,
                evaluation,
            )["mechanical"]
            gradient = -evaluation.particle_force.reshape(-1)
            if not bob_held:
                gradient = np.concatenate([gradient, -evaluation.bob_force])
            if not np.isfinite(energy) or not np.all(np.isfinite(gradient)):
                raise FloatingPointError
            return float(energy), gradient
        except FloatingPointError:
            return 1.0e100, np.zeros_like(candidate)

    candidate = x0
    total_iterations = 0
    # L-BFGS-B can stop on the relative energy criterion while the absolute
    # force is still above the user contract, because gravitational potential
    # carries an arbitrary large offset.  Restarting from the accepted point
    # with ftol=0 makes the physical force residual, not that offset, decisive.
    for _ in range(4):
        result = minimize(
            lambda trial: objective(trial)[0],
            candidate,
            jac=lambda trial: objective(trial)[1],
            method="L-BFGS-B",
            options={
                "maxiter": int(cfg.solver.static.max_iterations),
                "ftol": 0.0,
                "gtol": 1.0e-12,
                "maxls": 100,
                "maxcor": 30,
            },
        )
        candidate = np.asarray(result.x, dtype=float)
        total_iterations += int(result.nit)
        _, gradient = objective(candidate)
        if float(np.max(np.abs(gradient))) <= float(
            to_si(cfg.solver.static.force_tolerance, default_unit="N")
        ):
            break

    requested_tolerance = float(
        to_si(cfg.solver.static.force_tolerance, default_unit="N")
    )
    _, gradient = objective(candidate)
    if float(np.max(np.abs(gradient))) > requested_tolerance:
        # Energy minimisation supplies the stable basin; a matrix-free Newton-
        # Krylov force solve then closes the absolute force contract without a
        # dense 3N-by-3N finite-difference Hessian.
        force_root = root(
            lambda trial: -objective(trial)[1],
            candidate,
            method="krylov",
            options={
                "maxiter": max(20, 2 * int(cfg.solver.static.max_iterations)),
                "fatol": 0.2 * requested_tolerance,
            },
        )
        root_candidate = np.asarray(force_root.x, dtype=float)
        _, root_gradient = objective(root_candidate)
        if np.all(np.isfinite(root_candidate)) and np.max(np.abs(root_gradient)) < np.max(
            np.abs(gradient)
        ):
            candidate = root_candidate
            total_iterations += int(getattr(force_root, "nit", 0))
    particles, bob = unpack(candidate)
    evaluation = model.evaluate(
        0.0,
        particles,
        zero_particle_velocity,
        bob,
        zero3,
        quaternion0,
        zero3,
        include_aero=False,
        compute_contact=False,
    )
    residual_values = [np.max(np.abs(evaluation.particle_force))]
    if not bob_held:
        residual_values.append(np.max(np.abs(evaluation.bob_force)))
    residual = float(max(residual_values))
    tolerance = requested_tolerance
    if not np.isfinite(residual) or residual > tolerance:
        raise RuntimeError(
            "HF local static preparation did not reach force balance: "
            f"residual={residual:.6g} N, tolerance={tolerance:.6g} N, "
            f"optimizer={result.message}."
        )

    bob_velocity = as_vector3(cfg.initial_condition.bob_velocity, default_unit="m/s")
    angular_velocity = as_vector3(
        cfg.initial_condition.bob_angular_velocity, default_unit="rad/s"
    )
    attachment_velocity = bob_velocity + np.cross(
        angular_velocity, model.attachment_body
    )
    particle_velocity = np.zeros_like(particles)
    for branch in model.branches.values():
        if branch.start_kind == "support_A":
            _, start_velocity, _ = model.support_motion["support_A"].state(0.0)
        elif branch.start_kind == "support_B":
            _, start_velocity, _ = model.support_motion["support_B"].state(0.0)
        else:
            start_velocity = particle_velocity[model.junction_index]
        end_velocity = (
            particle_velocity[model.junction_index]
            if branch.end_kind == "junction"
            else attachment_velocity
        )
        for local, particle_index in enumerate(branch.bead_indices):
            alpha = (local + 0.5) / branch.bead_indices.size
            particle_velocity[particle_index] = (
                (1.0 - alpha) * start_velocity + alpha * end_velocity
            )

    state = model.pack_state(
        particles,
        bob,
        quaternion0,
        particle_velocity,
        bob_velocity,
        angular_velocity,
    )
    return PreparationResult(
        state=state,
        residual_inf_N=residual,
        iterations=total_iterations,
        bob_held=bob_held,
        preparation_mode=(
            "held_cartesian_static_rod_preparation"
            if bob_held
            else "free_static_equilibrium"
        ),
    )


def _solver_parameters(cfg: SimulationConfig, model: HighFidelityModel) -> dict[str, Any]:
    defaults = {
        "quick": (1.0e-6, 1.0e-8),
        "production": (1.0e-8, 1.0e-10),
        "reference": (1.0e-10, 1.0e-12),
    }
    rtol, position_atol = defaults[cfg.solver.profile]
    if cfg.solver.rtol is not None:
        rtol = float(cfg.solver.rtol)
    if cfg.solver.position_atol is not None:
        position_atol = float(to_si(cfg.solver.position_atol, default_unit="m"))
    gravity_time = np.sqrt(model.characteristic_length / np.linalg.norm(model.gravity))
    velocity_atol = (
        float(to_si(cfg.solver.velocity_atol, default_unit="m/s"))
        if cfg.solver.velocity_atol is not None
        else position_atol / gravity_time
    )
    quaternion_atol = (
        float(cfg.solver.quaternion_atol)
        if cfg.solver.quaternion_atol is not None
        else position_atol / model.characteristic_length
    )
    angular_velocity_atol = (
        float(to_si(cfg.solver.angular_velocity_atol, default_unit="rad/s"))
        if cfg.solver.angular_velocity_atol is not None
        else quaternion_atol / gravity_time
    )
    atol = np.concatenate(
        [
            np.full(model.position_size, position_atol),
            np.full(3, position_atol),
            np.full(4, quaternion_atol),
            np.full(model.position_size, velocity_atol),
            np.full(3, velocity_atol),
            np.full(3, angular_velocity_atol),
        ]
    )
    minimum_cell_time = float("inf")
    for name, branch in model.branches.items():
        cable = getattr(cfg.cables, name)
        young = float(to_si(cable.young_modulus, default_unit="Pa"))
        density = float(to_si(cable.density, default_unit="kg/m^3"))
        minimum_cell_time = min(
            minimum_cell_time, branch.cell_length / np.sqrt(young / density)
        )
    cell_gravity_time = np.sqrt(
        max(branch.cell_length for branch in model.branches.values())
        / np.linalg.norm(model.gravity)
    )
    # The presentation/validation sampling grid is not an integration-step
    # controller.  Keeping those two scales independent is essential for a
    # genuine time-refinement study: the bounded implicit driver samples its
    # current dense interpolant on the presentation grid, while max_step is
    # governed by local rod scales and the explicit numerical contract below.
    max_step = cell_gravity_time / 100.0
    if cfg.solver.resolve_longitudinal_waves:
        max_step = min(max_step, minimum_cell_time / 10.0)
    if cfg.solver.max_step != "auto":
        max_step = min(
            max_step, float(to_si(cfg.solver.max_step, default_unit="s"))
        )
    return {
        "rtol": rtol,
        "atol": atol,
        "position_atol": position_atol,
        "velocity_atol": velocity_atol,
        "quaternion_atol": quaternion_atol,
        "angular_velocity_atol": angular_velocity_atol,
        "max_step": max_step,
        "minimum_cell_wave_time": minimum_cell_time,
    }


def _sampled_axial_events(
    time: np.ndarray,
    cable_tension: dict[str, np.ndarray],
    cable_axial_force: dict[str, np.ndarray],
    *,
    zero_tolerance: float,
    compression_regularization_scale: float,
) -> list[dict[str, Any]]:
    """Report sampled axial regimes without calling compression 'slack'."""

    events: list[dict[str, Any]] = []
    if compression_regularization_scale > 0.0:
        for branch_name, axial_force in cable_axial_force.items():
            signed = np.asarray(axial_force, dtype=float)
            regime = np.full(signed.shape, "NEUTRAL", dtype=object)
            regime[signed > zero_tolerance] = "TENSION"
            regime[signed < -zero_tolerance] = "COMPRESSION"
            for segment_index in range(signed.shape[1]):
                if regime[0, segment_index] != "TENSION":
                    events.append(
                        {
                            "type": "HF_SEGMENT_INITIAL_AXIAL_REGIME",
                            "branch": branch_name,
                            "material_segment": segment_index,
                            "time": float(time[0]),
                            "axial_regime": str(regime[0, segment_index]),
                            "signed_axial_force_N": float(signed[0, segment_index]),
                            "tensile_force_N": float(
                                cable_tension[branch_name][0, segment_index]
                            ),
                            "time_resolution": "sample_exact_at_initial_state",
                        }
                    )
                changes = np.flatnonzero(
                    regime[1:, segment_index] != regime[:-1, segment_index]
                ) + 1
                for sample_index in changes:
                    events.append(
                        {
                            "type": "HF_SEGMENT_AXIAL_REGIME_CHANGE_SAMPLED_BRACKET",
                            "branch": branch_name,
                            "material_segment": segment_index,
                            "time": float(time[sample_index]),
                            "bracket_start_s": float(time[sample_index - 1]),
                            "bracket_end_s": float(time[sample_index]),
                            "axial_regime_before": str(
                                regime[sample_index - 1, segment_index]
                            ),
                            "axial_regime_after": str(
                                regime[sample_index, segment_index]
                            ),
                            "signed_axial_force_before_N": float(
                                signed[sample_index - 1, segment_index]
                            ),
                            "signed_axial_force_after_N": float(
                                signed[sample_index, segment_index]
                            ),
                            "time_resolution": (
                                "bounded_by_output_samples_not_a_solver_root"
                            ),
                        }
                    )
        return events

    # The exact alpha=0 endpoint is the registered unilateral string law; only
    # there do slack/retension words describe the constitutive state.
    for branch_name, tension in cable_tension.items():
        active = np.asarray(tension, dtype=float) > zero_tolerance
        for segment_index in range(active.shape[1]):
            if not active[0, segment_index]:
                events.append(
                    {
                        "type": "HF_SEGMENT_INITIALLY_SLACK",
                        "branch": branch_name,
                        "material_segment": segment_index,
                        "time": float(time[0]),
                        "tension_N": float(tension[0, segment_index]),
                        "time_resolution": "sample_exact_at_initial_state",
                    }
                )
            changes = np.flatnonzero(
                active[1:, segment_index] != active[:-1, segment_index]
            ) + 1
            for sample_index in changes:
                became_active = bool(active[sample_index, segment_index])
                events.append(
                    {
                        "type": (
                            "HF_SEGMENT_RETENSION_SAMPLED_BRACKET"
                            if became_active
                            else "HF_SEGMENT_SLACKENING_SAMPLED_BRACKET"
                        ),
                        "branch": branch_name,
                        "material_segment": segment_index,
                        "time": float(time[sample_index]),
                        "bracket_start_s": float(time[sample_index - 1]),
                        "bracket_end_s": float(time[sample_index]),
                        "tension_before_N": float(tension[sample_index - 1, segment_index]),
                        "tension_after_N": float(tension[sample_index, segment_index]),
                        "time_resolution": "bounded_by_output_samples_not_a_solver_root",
                    }
                )
        fully_active = np.all(active, axis=1)
        fully_slack = ~np.any(active, axis=1)
        for mask, inactive_type, active_type in (
            (fully_active, "HF_BRANCH_NOT_FULLY_TAUT", "HF_BRANCH_FULLY_RETENSIONED"),
            (fully_slack, "HF_BRANCH_LEFT_FULL_SLACK", "HF_BRANCH_FULLY_SLACK"),
        ):
            changes = np.flatnonzero(mask[1:] != mask[:-1]) + 1
            for sample_index in changes:
                events.append(
                    {
                        "type": active_type if mask[sample_index] else inactive_type,
                        "branch": branch_name,
                        "time": float(time[sample_index]),
                        "bracket_start_s": float(time[sample_index - 1]),
                        "bracket_end_s": float(time[sample_index]),
                        "time_resolution": "bounded_by_output_samples_not_a_solver_root",
                    }
                )
    return events


def simulate_high_fidelity(
    cfg: SimulationConfig,
    *,
    model: HighFidelityModel | None = None,
    preparation: PreparationResult | None = None,
    checkpoint_path: str | Path | None = None,
    resume_from_checkpoint: bool = False,
) -> HighFidelityResult:
    t_end = float(to_si(cfg.solver.t_end, default_unit="s"))
    output_dt = float(to_si(cfg.solver.output_dt, default_unit="s"))
    # Repeat the joint resource contract at the public solver boundary before
    # constructing the HF model, preparing a held state, or allocating the
    # presentation grid.  This catches a configuration object that was mutated
    # after ``load_config`` (or supplied by an internal caller that bypassed
    # validation) without first risking the very allocation the cap protects.
    resource_contract = _high_fidelity_resource_estimate(
        cfg,
        t_end=t_end,
        output_dt=output_dt,
    )
    if (
        resource_contract["output_samples"]
        > resource_contract["output_sample_limit"]
        or resource_contract["accepted_step_budget"]
        > resource_contract["accepted_step_limit"]
        or resource_contract["estimated_peak_memory_bytes"]
        > resource_contract["peak_memory_limit_bytes"]
        or resource_contract["estimated_result_bytes"]
        > resource_contract["result_limit_bytes"]
    ):
        raise RuntimeError(
            "HF_RESOURCE_BUDGET_EXCEEDED_AT_SOLVER_ENTRY: configuration was "
            "mutated or bypassed after validation."
        )

    if resume_from_checkpoint and checkpoint_path is None:
        raise ValueError("resume_from_checkpoint requires checkpoint_path.")
    model = HighFidelityModel(cfg) if model is None else model
    count = int(np.floor(t_end / output_dt + 1.0e-12))
    output_time = np.arange(count + 1, dtype=float) * output_dt
    if output_time[-1] < t_end - 1.0e-12:
        output_time = np.append(output_time, t_end)
    parameters = _solver_parameters(cfg, model)
    method = cfg.solver.method
    if method == "Newmark":
        raise ValueError(
            "The independent HF rigid-bob state currently uses Radau or BDF; "
            "legacy Newmark is not silently applied to quaternion dynamics."
        )

    checkpoint_metadata: dict[str, Any] | None = None
    checkpoint_reused = False
    if resume_from_checkpoint:
        trace, checkpoint_metadata = _load_integration_checkpoint(
            checkpoint_path,
            cfg=cfg,
            model=model,
            output_time=output_time,
        )
        checkpoint_reused = True
        if preparation is None:
            residual = checkpoint_metadata.get("preparation_residual_inf_N")
            preparation = PreparationResult(
                state=trace.accepted_state[0].copy(),
                residual_inf_N=float("nan") if residual is None else float(residual),
                iterations=int(checkpoint_metadata["preparation_iterations"]),
                bob_held=bool(checkpoint_metadata["preparation_bob_held"]),
                preparation_mode=str(checkpoint_metadata["preparation_mode"]),
                audit={
                    "resumed_from_integration_checkpoint": str(
                        Path(checkpoint_path).expanduser().resolve()
                    ),
                    "checkpoint_solver_source_sha256": checkpoint_metadata[
                        "solver_source_sha256"
                    ],
                    "checkpoint_model_source_sha256": checkpoint_metadata[
                        "model_source_sha256"
                    ],
                },
            )
    elif preparation is None:
        preparation = prepare_initial_state(cfg, model)
    assert preparation is not None

    initial_guards = model.guard_components(0.0, preparation.state)
    guard_metadata = model.guard_component_metadata()
    if initial_guards.keys() != guard_metadata.keys():
        raise AssertionError("HF guard values and metadata have different vocabularies.")
    failed_initial_guards = {
        name: value
        for name, value in initial_guards.items()
        if value <= float(guard_metadata[name]["tolerance"])
    }
    if failed_initial_guards:
        raise ValueError(
            "HF initial state is outside the registered validity domain: "
            f"{failed_initial_guards}"
        )

    guard_cache_time: float | None = None
    guard_cache_state: np.ndarray | None = None
    guard_cache_components: dict[str, float] | None = None

    def cached_guard_components(t: float, state: np.ndarray) -> dict[str, float]:
        nonlocal guard_cache_time, guard_cache_state, guard_cache_components
        candidate_state = np.asarray(state, dtype=float)
        if (
            guard_cache_components is not None
            and guard_cache_time == float(t)
            and guard_cache_state is not None
            and np.array_equal(guard_cache_state, candidate_state)
        ):
            return guard_cache_components
        guard_cache_time = float(t)
        guard_cache_state = candidate_state.copy()
        guard_cache_components = model.guard_components(float(t), candidate_state)
        return guard_cache_components

    guard_names = tuple(initial_guards)
    characteristic_time = np.sqrt(
        model.characteristic_length / float(np.linalg.norm(model.gravity))
    )
    terminal_time_tolerance = (
        1024.0
        * np.finfo(float).eps
        * max(characteristic_time, t_end)
    )
    if resume_from_checkpoint:
        runtime = 0.0
    else:
        start = perf_counter()
        trace = _integrate_with_accepted_step_cap(
            model,
            preparation.state,
            t_end=t_end,
            output_time=output_time,
            method=method,
            rtol=parameters["rtol"],
            atol=parameters["atol"],
            max_step=parameters["max_step"],
            jac_sparsity=(
                model.jacobian_sparsity()
                if cfg.solver.analytic_jacobian
                else None
            ),
            guard_names=guard_names,
            guard_metadata=guard_metadata,
            guard_components=cached_guard_components,
            accepted_step_cap=int(resource_contract["accepted_step_budget"]),
            terminal_time_tolerance=terminal_time_tolerance,
        )
        runtime = perf_counter() - start
        if checkpoint_path is not None:
            checkpoint_metadata = _write_integration_checkpoint(
                checkpoint_path,
                cfg=cfg,
                model=model,
                preparation=preparation,
                trace=trace,
                output_time=output_time,
                integration_wall_seconds=runtime,
            )
    event_time = trace.event_time
    event_state = trace.event_state
    integration_time = trace.accepted_time
    integration_state = trace.accepted_state
    # An implicit driver can append a final point only a few ulps after an
    # already accepted endpoint (for example a 6e-17 s tail on a 2e-3 s run). Such a
    # pair carries no resolvable time interval and makes any rate-normalized
    # defect meaningless.  Retain the exact terminal state and remove only
    # immediately preceding machine-scale terminal duplicates.
    terminal_target = event_time if event_time is not None else t_end
    integration_time, integration_state, coalesced_terminal_steps = (
        _coalesce_terminal_certificate(
            integration_time,
            integration_state,
            terminal_target=terminal_target,
            tolerance=terminal_time_tolerance,
        )
    )

    if event_time is not None:
        # The public trajectory and accepted-step certificate both obey the
        # valid half-open interval [0,tau); the root state is retained solely
        # in the event evidence below.
        cutoff = event_time - terminal_time_tolerance
        integration_keep = integration_time < cutoff
        integration_time = integration_time[integration_keep]
        integration_state = integration_state[integration_keep]

    time = output_time[: trace.presentation_state.shape[0]]
    state = trace.presentation_state

    unresolved_time: float | None = None
    unresolved_state: np.ndarray | None = None
    unresolved_components: dict[str, float] | None = None

    n_position = model.position_size
    velocity_offset = n_position + 7
    integration_particle_positions = integration_state[:, :n_position].reshape(
        integration_time.size, model.particle_count, 3
    )
    integration_bob_position = integration_state[:, n_position : n_position + 3]
    integration_bob_quaternion = integration_state[
        :, n_position + 3 : n_position + 7
    ]
    integration_particle_velocities = integration_state[
        :, velocity_offset : velocity_offset + n_position
    ].reshape(integration_time.size, model.particle_count, 3)
    integration_bob_velocity = integration_state[
        :, velocity_offset + n_position : velocity_offset + n_position + 3
    ]
    integration_bob_angular_velocity = integration_state[
        :, velocity_offset + n_position + 3 : velocity_offset + n_position + 6
    ]

    postprocess_started = perf_counter()
    postprocess_cpu_started = _process_tree_cpu_seconds()
    sample_evaluation_started = perf_counter()
    presentation, unresolved, postprocess_worker_count = _presentation_samples(
        model,
        time,
        state,
        guard_metadata,
        check_guards=event_time is None,
    )
    sample_evaluation_wall = perf_counter() - sample_evaluation_started
    valid_sample_count = int(time.size) if unresolved is None else int(unresolved["index"])
    if unresolved is not None:
        unresolved_time = float(unresolved["time"])
        unresolved_state = np.asarray(unresolved["state"], dtype=float)
        unresolved_components = dict(unresolved["components"])
        cutoff = unresolved_time - terminal_time_tolerance
        integration_keep = integration_time < cutoff
        integration_time = integration_time[integration_keep]
        integration_state = integration_state[integration_keep]
        integration_particle_positions = integration_particle_positions[
            integration_keep
        ]
        integration_bob_position = integration_bob_position[integration_keep]
        integration_bob_quaternion = integration_bob_quaternion[integration_keep]
        integration_particle_velocities = integration_particle_velocities[
            integration_keep
        ]
        integration_bob_velocity = integration_bob_velocity[integration_keep]
        integration_bob_angular_velocity = integration_bob_angular_velocity[
            integration_keep
        ]
    time = time[:valid_sample_count]
    state = state[:valid_sample_count]
    if time.size == 0:
        raise RuntimeError(
            "HF validity could not be certified beyond the initial state; no valid interval returned."
        )
    particle_positions = state[:, :n_position].reshape(
        time.size, model.particle_count, 3
    )
    bob_position = state[:, n_position : n_position + 3]
    particle_velocities = state[
        :, velocity_offset : velocity_offset + n_position
    ].reshape(time.size, model.particle_count, 3)
    bob_velocity = state[
        :, velocity_offset + n_position : velocity_offset + n_position + 3
    ]
    bob_angular_velocity = state[
        :, velocity_offset + n_position + 3 : velocity_offset + n_position + 6
    ]
    bob_quaternion = presentation["bob_quaternion"]
    bob_attachment = presentation["bob_attachment"]
    cable_positions = presentation["cable_positions"]
    cable_velocities = presentation["cable_velocities"]
    cable_tension = presentation["cable_tension"]
    cable_axial_force = presentation["cable_axial_force"]
    reaction_a = presentation["reaction_a"]
    reaction_b = presentation["reaction_b"]
    energy = presentation["energy"]
    geometry = presentation["geometry"]
    contact_margin = geometry["contact_margin"]
    bob_contact_margin = geometry["bob_contact_margin"]
    rod_self_contact_margin = geometry["rod_self_contact_margin"]
    minimum_segment = geometry["minimum_segment"]
    minimum_bending_turn_clearance = geometry[
        "minimum_bending_turn_clearance"
    ]
    minimum_aerodynamic_chord_length = geometry[
        "minimum_aerodynamic_chord_length"
    ]
    bob_socket_material_extent = geometry["bob_socket_material_extent"]
    bob_socket_radial_monotonicity = geometry[
        "bob_socket_radial_monotonicity"
    ]
    bob_socket_cut_clearance = geometry["bob_socket_cut_clearance"]
    junction_socket_material_extent = geometry[
        "junction_socket_material_extent"
    ]
    junction_socket_projective_opening = geometry[
        "junction_socket_projective_opening"
    ]
    junction_socket_cut_clearance = geometry["junction_socket_cut_clearance"]
    quaternion_norm = geometry["quaternion_norm"]

    dissipation_axial = np.concatenate(
        [[0.0], cumulative_trapezoid(energy["axial_dissipation_rate"], time)]
    )
    dissipation_aero = np.concatenate(
        [[0.0], cumulative_trapezoid(energy["aero_dissipation_rate"], time)]
    )
    work_air = np.concatenate(
        [[0.0], cumulative_trapezoid(energy["air_work_rate"], time)]
    )
    work_support = np.concatenate(
        [[0.0], cumulative_trapezoid(energy["support_work_rate"], time)]
    )
    mechanical = energy["mechanical"]
    scale = max(
        model.force_scale * model.characteristic_length,
        1.0e-12,
    )
    balance = (
        mechanical
        - mechanical[0]
        + dissipation_axial
        + dissipation_aero
        - work_air
        - work_support
    ) / scale
    energy.update(
        {
            "dissipation_axial": dissipation_axial,
            "dissipation_aero": dissipation_aero,
            "work_air": work_air,
            "work_support": work_support,
            "balance_residual": balance,
        }
    )

    guard_margins = {
        "MINIMUM_SEGMENT_LENGTH": minimum_segment - model.length_guard,
        "BENDING_TURN_CLEARANCE": (
            minimum_bending_turn_clearance
            - model.bending_turn_clearance_floor
        ),
        "AERODYNAMIC_CHORD_LENGTH": (
            minimum_aerodynamic_chord_length
            - model.aerodynamic_chord_guard
        ),
    }
    if model.contact_guard_enabled:
        guard_margins.update(
            {
                "BOB_ROD_CLEARANCE": bob_contact_margin - model.minimum_clearance,
                "ROD_SELF_CLEARANCE": rod_self_contact_margin - model.minimum_clearance,
                "BOB_SOCKET_MATERIAL_EXTENT": bob_socket_material_extent,
                "BOB_SOCKET_RADIAL_MONOTONICITY": (
                    bob_socket_radial_monotonicity
                ),
                "BOB_SOCKET_CUT_CLEARANCE": bob_socket_cut_clearance,
                "JUNCTION_SOCKET_MATERIAL_EXTENT": (
                    junction_socket_material_extent
                ),
                "JUNCTION_SOCKET_PROJECTIVE_OPENING": (
                    junction_socket_projective_opening
                ),
                "JUNCTION_SOCKET_CUT_CLEARANCE": (
                    junction_socket_cut_clearance
                ),
            }
        )

    events: list[dict[str, Any]] = []
    # The bounded driver locates sign-changing roots, but a public raw run does not own
    # the independent accepted-step enclosure needed to exclude tangential or
    # positive-negative-positive guard excursions.  Preserve the full trace,
    # but never overstate it as physically complete.  Formal validation may
    # certify this exact provisional pair without mutating the raw result.
    physical_status = "UNDETERMINED"
    numerical_status = "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"
    valid_end = t_end
    evidence_time = event_time if event_time is not None else unresolved_time
    evidence_state = event_state if event_state is not None else unresolved_state
    evidence_components = (
        model.guard_components(evidence_time, evidence_state)
        if evidence_time is not None and evidence_state is not None
        else unresolved_components
    )
    if event_time is not None:
        physical_status = "OUT_OF_SCOPE"
        numerical_status = "SUCCESS_EVENT"
        valid_end = event_time
    elif unresolved_time is not None:
        physical_status = "UNDETERMINED"
        numerical_status = "EVENT_UNRESOLVED"
        valid_end = unresolved_time
    if evidence_time is not None and evidence_state is not None and evidence_components is not None:
        (
            evidence_particles,
            evidence_bob,
            evidence_quaternion,
            evidence_velocities,
            evidence_bob_velocity,
            evidence_omega,
        ) = model.unpack_state(evidence_state)
        evidence_evaluation = model.evaluate(
            evidence_time,
            evidence_particles,
            evidence_velocities,
            evidence_bob,
            evidence_bob_velocity,
            normalize_quaternion(evidence_quaternion),
            evidence_omega,
        )
        tolerance_reasons = {
            name
            for name, value in evidence_components.items()
            if value <= float(guard_metadata[name]["tolerance"])
        }
        if event_time is not None:
            # A steep guard can leave a positive raw residual at Brent's
            # time-accurate root.  The sign-bracket identity is authoritative;
            # the root-state values remain separate numerical evidence.
            tolerance_reasons.update(trace.event_guard_names)
        event_reasons = sorted(tolerance_reasons)
        events.append(
            {
                "type": (
                    "HF_VALIDITY_GUARD"
                    if event_time is not None
                    else "HF_EVENT_UNRESOLVED_AT_SAMPLED_GUARD"
                ),
                "time": evidence_time,
                "guard_components": evidence_components,
                "guard_component_metadata": guard_metadata,
                "bracketed_guard_names": list(trace.event_guard_names),
                "state_left": evidence_state.tolist(),
                "derived_left": {
                    "bob_position_m": evidence_bob.tolist(),
                    "bob_velocity_m_s": evidence_bob_velocity.tolist(),
                    "junction_position_m": evidence_particles[
                        model.junction_index
                    ].tolist(),
                    "branch_tension_N": {
                        name: values.tolist()
                        for name, values in evidence_evaluation.branch_tension.items()
                    },
                    "branch_signed_axial_force_N": {
                        name: values.tolist()
                        for name, values in evidence_evaluation.branch_axial_force.items()
                    },
                },
                "reasons": event_reasons,
            }
        )
    events.extend(
        _sampled_axial_events(
            time,
            cable_tension,
            cable_axial_force,
            zero_tolerance=model.tension_zero_tolerance,
            compression_regularization_scale=(
                model.compression_regularization_scale
            ),
        )
    )

    all_tension = np.concatenate(list(cable_tension.values()), axis=1)
    all_axial_force = np.concatenate(list(cable_axial_force.values()), axis=1)
    postprocess_wall = perf_counter() - postprocess_started
    postprocess_cpu_seconds = max(
        0.0, _process_tree_cpu_seconds() - postprocess_cpu_started
    )
    diagnostics: dict[str, Any] = {
        **model.diagnostics(),
        "runtime_seconds": runtime,
        "integration_wall_seconds": runtime,
        "integration_checkpoint_schema": (
            checkpoint_metadata.get("schema")
            if checkpoint_metadata is not None
            else None
        ),
        "integration_checkpoint_path": (
            str(Path(checkpoint_path).expanduser().resolve())
            if checkpoint_path is not None
            else None
        ),
        "integration_checkpoint_reused": checkpoint_reused,
        "checkpoint_original_integration_wall_seconds": (
            float(checkpoint_metadata["integration_wall_seconds"])
            if checkpoint_metadata is not None
            else None
        ),
        "presentation_sample_evaluation_wall_seconds": sample_evaluation_wall,
        "postprocess_wall_seconds": postprocess_wall,
        "postprocess_process_tree_cpu_seconds": postprocess_cpu_seconds,
        "postprocess_average_equivalent_cpu_cores": (
            postprocess_cpu_seconds
            / max(postprocess_wall, np.finfo(float).tiny)
        ),
        "postprocess_average_cpu_utilization_percent": (
            100.0
            * postprocess_cpu_seconds
            / max(postprocess_wall, np.finfo(float).tiny)
        ),
        "postprocess_worker_count": postprocess_worker_count,
        "postprocess_physical_core_count": _physical_cpu_core_count(),
        "postprocess_parallel_backend": (
            "DETERMINISTIC_FIXED_CONTIGUOUS_SPAWN_PROCESS_POOL_V1"
            if postprocess_worker_count > 1
            else "DETERMINISTIC_SERIAL_V1"
        ),
        "solver_method": method,
        "rtol": parameters["rtol"],
        "position_atol_m": parameters["position_atol"],
        "velocity_atol_m_s": parameters["velocity_atol"],
        "quaternion_atol": parameters["quaternion_atol"],
        "angular_velocity_atol_rad_s": parameters["angular_velocity_atol"],
        "max_step_s": parameters["max_step"],
        "minimum_cell_wave_time_s": parameters["minimum_cell_wave_time"],
        "jacobian_kind": (
            "colored_finite_difference_from_local_HF_dependency_graph"
            if cfg.solver.analytic_jacobian
            else "unstructured_finite_difference"
        ),
        "jacobian_sparsity_nnz": (
            int(model.jacobian_sparsity().nnz) if cfg.solver.analytic_jacobian else None
        ),
        "nfev": trace.nfev,
        "njev": trace.njev,
        "nlu": trace.nlu,
        "accepted_integration_step_count": int(max(integration_time.size - 1, 0)),
        "accepted_integration_step_hard_cap": int(
            resource_contract["accepted_step_budget"]
        ),
        "resource_upper_bound": resource_contract,
        "resource_runtime_enforcement": (
            "MANUAL_SCIPY_RADAU_BDF_ACCEPTED_STEP_CAP_V1"
        ),
        "machine_scale_terminal_steps_coalesced": coalesced_terminal_steps,
        "terminal_time_coalescing_tolerance_s": terminal_time_tolerance,
        "minimum_accepted_integration_step_s": (
            float(np.min(np.diff(integration_time)))
            if integration_time.size >= 2
            else None
        ),
        "maximum_accepted_integration_step_s": (
            float(np.max(np.diff(integration_time)))
            if integration_time.size >= 2
            else None
        ),
        "preparation_force_residual_inf_N": preparation.residual_inf_N,
        "preparation_iterations": preparation.iterations,
        "preparation_bob_held": preparation.bob_held,
        "preparation_mode": preparation.preparation_mode,
        "preparation_audit": preparation.audit,
        "raw_guard_certification_status": "ACCEPTED_STEP_CONTINUOUS_CERTIFICATE_REQUIRED",
        "energy_balance_scale_J": scale,
        "energy_balance_scale_definition": (
            "total_gravitational_force_scale_times_characteristic_length"
        ),
        "max_abs_energy_balance_residual": float(np.max(np.abs(balance))),
        "minimum_tension_N": float(np.min(all_tension)),
        "maximum_tension_N": float(np.max(all_tension)),
        "minimum_signed_axial_force_N": float(np.min(all_axial_force)),
        "maximum_signed_axial_force_N": float(np.max(all_axial_force)),
        "minimum_contact_margin_m": float(np.min(contact_margin)),
        "minimum_bob_contact_margin_m": float(np.min(bob_contact_margin)),
        "minimum_rod_self_contact_margin_m": float(
            np.min(rod_self_contact_margin)
        ),
        "guard_component_metadata": guard_metadata,
        "minimum_segment_length_m": float(np.min(minimum_segment)),
        "minimum_bending_turn_clearance": float(
            np.min(minimum_bending_turn_clearance)
        ),
        "minimum_aerodynamic_chord_length_m": float(
            np.min(minimum_aerodynamic_chord_length)
        ),
        "minimum_bob_socket_material_extent_m": float(
            np.min(bob_socket_material_extent)
        ),
        "minimum_bob_socket_radial_monotonicity_m2": float(
            np.min(bob_socket_radial_monotonicity)
        ),
        "minimum_bob_socket_cut_clearance_m": float(
            np.min(bob_socket_cut_clearance)
        ),
        "minimum_junction_socket_material_extent_m": float(
            np.min(junction_socket_material_extent)
        ),
        "minimum_junction_socket_projective_opening": float(
            np.min(junction_socket_projective_opening)
        ),
        "minimum_junction_socket_cut_clearance_m": float(
            np.min(junction_socket_cut_clearance)
        ),
        "maximum_quaternion_norm_error": float(np.max(np.abs(quaternion_norm - 1.0))),
        "bending_energy_fraction_peak": float(
            np.max(
                energy["elastic_bending"]
                / np.maximum(
                    energy["elastic_axial"] + energy["elastic_bending"], 1.0e-30
                )
            )
        ),
    }
    return HighFidelityResult(
        time=time,
        integration_time=integration_time,
        integration_particle_positions=integration_particle_positions,
        integration_particle_velocities=integration_particle_velocities,
        integration_bob_position=integration_bob_position,
        integration_bob_velocity=integration_bob_velocity,
        integration_bob_quaternion=integration_bob_quaternion,
        integration_bob_angular_velocity=integration_bob_angular_velocity,
        particle_positions=particle_positions,
        particle_velocities=particle_velocities,
        junction_position=particle_positions[:, model.junction_index],
        junction_velocity=particle_velocities[:, model.junction_index],
        bob_position=bob_position,
        bob_velocity=bob_velocity,
        bob_quaternion=bob_quaternion,
        bob_angular_velocity=bob_angular_velocity,
        bob_attachment_position=bob_attachment,
        cable_positions=cable_positions,
        cable_velocities=cable_velocities,
        cable_axial_force=cable_axial_force,
        cable_tension=cable_tension,
        guard_margins=guard_margins,
        energy=energy,
        reactions={"support_A": reaction_a, "support_B": reaction_b},
        events=events,
        diagnostics=diagnostics,
        physical_status=physical_status,
        numerical_status=numerical_status,
        valid_interval=(0.0, valid_end),
    )

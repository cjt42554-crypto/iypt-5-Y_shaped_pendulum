"""HDF5 run format with units and descriptions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import h5py
import numpy as np

from ypendulum.hf.state import HighFidelityResult
from ypendulum.models.state import SimulationResult


def _dataset(
    h5: h5py.File,
    name: str,
    data: Any,
    *,
    unit: str,
    description: str,
    compression: bool = True,
):
    arr = np.asarray(data)
    kwargs = {"compression": "gzip", "shuffle": True} if compression and arr.size > 32 else {}
    ds = h5.create_dataset(name, data=arr, **kwargs)
    ds.attrs["unit"] = unit
    ds.attrs["description"] = description
    return ds


def write_h1_result(
    path: str | Path,
    result: SimulationResult,
    model,
    observer_pixels=None,
    observer_time=None,
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(target, "w") as h5:
        h5.attrs["format"] = "YP-FPSim H1 result"
        h5.attrs["format_version"] = "1.0"
        h5.attrs["model"] = result.model_name
        h5.attrs["claim_level"] = result.claim_level
        _dataset(h5, "/time", result.time, unit="s", description="Absolute simulation time")
        _dataset(
            h5,
            "/state/positions",
            result.positions,
            unit="m",
            description="All mesh-node world positions; shape (time,node,xyz)",
        )
        _dataset(
            h5,
            "/state/velocities",
            result.velocities,
            unit="m/s",
            description="All mesh-node world velocities",
        )
        string_type = h5py.string_dtype(encoding="utf-8")
        labels = h5.create_dataset(
            "/mesh/node_labels",
            data=np.asarray(model.topology.node_labels, dtype=object),
            dtype=string_type,
        )
        labels.attrs["unit"] = "1"
        labels.attrs["description"] = "Stable mesh-node labels"
        _dataset(
            h5,
            "/mesh/elements/node_i",
            model.topology.elements.node_i,
            unit="1",
            description="Element first-node indices",
        )
        _dataset(
            h5,
            "/mesh/elements/node_j",
            model.topology.elements.node_j,
            unit="1",
            description="Element second-node indices",
        )
        _dataset(
            h5,
            "/mesh/elements/rest_length",
            model.topology.elements.rest_length,
            unit="m",
            description="Element natural lengths",
        )
        j = model.topology.junction_node
        b = model.topology.bob_node
        _dataset(h5, "/bodies/junction/position", result.positions[:, j], unit="m", description="Junction position")
        _dataset(h5, "/bodies/junction/velocity", result.velocities[:, j], unit="m/s", description="Junction velocity")
        _dataset(h5, "/bodies/bob/position", result.positions[:, b], unit="m", description="Bob centre-of-mass position")
        _dataset(h5, "/bodies/bob/velocity", result.velocities[:, b], unit="m/s", description="Bob centre-of-mass velocity")
        for name, sl in model.topology.cable_slices.items():
            path_nodes = model.topology.cable_node_paths[name]
            _dataset(
                h5,
                f"/cables/{name}/nodes/position",
                result.positions[:, path_nodes],
                unit="m",
                description=f"{name} cable node positions",
            )
            _dataset(
                h5,
                f"/cables/{name}/nodes/velocity",
                result.velocities[:, path_nodes],
                unit="m/s",
                description=f"{name} cable node velocities",
            )
            _dataset(
                h5,
                f"/cables/{name}/elements/tension",
                result.tension[:, sl],
                unit="N",
                description=f"{name} element axial tension; never negative",
            )
            _dataset(
                h5,
                f"/cables/{name}/elements/stretch",
                result.stretch[:, sl],
                unit="m",
                description=f"{name} current length minus rest length",
            )
            _dataset(
                h5,
                f"/cables/{name}/elements/active",
                result.active[:, sl].astype(np.uint8),
                unit="1",
                description=f"{name} unilateral tensile active flag",
            )
        _dataset(h5, "/reactions/support_A", result.reactions["support_A"], unit="N", description="Reaction exerted by support A on the system")
        _dataset(h5, "/reactions/support_B", result.reactions["support_B"], unit="N", description="Reaction exerted by support B on the system")
        energy_units = {
            "kinetic": "J",
            "gravitational": "J",
            "elastic": "J",
            "mechanical": "J",
            "material_dissipation_rate": "W",
            "aero_relative_dissipation_rate": "W",
            "aero_work_rate": "W",
            "support_work_rate": "W",
            "dissipation_material": "J",
            "dissipation_aero_relative": "J",
            "aero_work": "J",
            "support_work": "J",
            "balance_residual": "1",
        }
        for key, values in result.energy.items():
            _dataset(
                h5,
                f"/energy/{key}",
                values,
                unit=energy_units.get(key, "1"),
                description=key.replace("_", " "),
            )
        if "dissipation_aero_relative" in result.energy:
            _dataset(
                h5,
                "/energy/dissipation_aero",
                result.energy["dissipation_aero_relative"],
                unit="J",
                description="Cumulative aerodynamic dissipation relative to the air",
            )
        if observer_pixels is not None:
            _dataset(h5, "/observer/pixels", observer_pixels, unit="pixel", description="Predicted camera pixels")
            if observer_time is None:
                raise ValueError("observer_time is required whenever observer_pixels are written.")
            _dataset(
                h5,
                "/observer/time",
                observer_time,
                unit="s",
                description="Observer sample mid-exposure times",
            )


def read_h1_result(path: str | Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    with h5py.File(path, "r") as h5:
        out["time"] = np.asarray(h5["/time"])
        out["positions"] = np.asarray(h5["/state/positions"])
        out["velocities"] = np.asarray(h5["/state/velocities"])
        out["bob_position"] = np.asarray(h5["/bodies/bob/position"])
        out["junction_position"] = np.asarray(h5["/bodies/junction/position"])
        out["energy_balance_residual"] = np.asarray(h5["/energy/balance_residual"])
        out["model"] = h5.attrs.get("model", "H1")
        out["claim_level"] = h5.attrs.get("claim_level", "VERIFIED")
    return out


def write_hf_result(path: str | Path, result: HighFidelityResult, model) -> None:
    """Write the complete independent-HF state with explicit SI identity."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(target, "w") as h5:
        h5.attrs["format"] = "Y-Pendulum independent HF result"
        h5.attrs["format_version"] = "1.0"
        h5.attrs["model"] = result.model_id
        h5.attrs["units"] = "SI"
        h5.attrs["physical_status"] = result.physical_status
        h5.attrs["numerical_status"] = result.numerical_status
        h5.attrs["valid_interval_start_s"] = result.valid_interval[0]
        h5.attrs["valid_interval_end_s"] = result.valid_interval[1]
        _dataset(h5, "/time", result.time, unit="s", description="Accepted simulation time")
        _dataset(
            h5,
            "/numerical_certificate/accepted_step_time",
            result.integration_time,
            unit="s",
            description=(
                "Adaptive integrator accepted-step times used for the independent "
                "ODE defect certificate; distinct from the presentation grid"
            ),
        )
        _dataset(
            h5,
            "/numerical_certificate/material_particles/position",
            result.integration_particle_positions,
            unit="m",
            description="Raw accepted-step material-particle positions",
        )
        _dataset(
            h5,
            "/numerical_certificate/material_particles/velocity",
            result.integration_particle_velocities,
            unit="m/s",
            description="Raw accepted-step material-particle velocities",
        )
        _dataset(
            h5,
            "/numerical_certificate/bob/com_position",
            result.integration_bob_position,
            unit="m",
            description="Raw accepted-step rigid-bob centre position",
        )
        _dataset(
            h5,
            "/numerical_certificate/bob/com_velocity",
            result.integration_bob_velocity,
            unit="m/s",
            description="Raw accepted-step rigid-bob centre velocity",
        )
        _dataset(
            h5,
            "/numerical_certificate/bob/quaternion_body_to_world",
            result.integration_bob_quaternion,
            unit="1",
            description="Raw accepted-step scalar-first orientation quaternion",
        )
        _dataset(
            h5,
            "/numerical_certificate/bob/angular_velocity_world",
            result.integration_bob_angular_velocity,
            unit="rad/s",
            description="Raw accepted-step bob angular velocity",
        )
        _dataset(
            h5,
            "/state/material_particles/position",
            result.particle_positions,
            unit="m",
            description="World positions of all material beads and the finite-mass junction",
        )
        _dataset(
            h5,
            "/state/material_particles/velocity",
            result.particle_velocities,
            unit="m/s",
            description="World velocities of all material beads and the junction",
        )
        string_type = h5py.string_dtype(encoding="utf-8")
        labels = h5.create_dataset(
            "/state/material_particles/labels",
            data=np.asarray(model.particle_labels, dtype=object),
            dtype=string_type,
        )
        labels.attrs["unit"] = "1"
        labels.attrs["description"] = "Stable HF material-particle labels"
        _dataset(
            h5,
            "/state/material_particles/mass",
            model.particle_mass,
            unit="kg",
            description="Lumped physical mass assigned to each material particle",
        )
        _dataset(h5, "/bodies/junction/position", result.junction_position, unit="m", description="Finite-mass junction position")
        _dataset(h5, "/bodies/junction/velocity", result.junction_velocity, unit="m/s", description="Finite-mass junction velocity")
        _dataset(h5, "/bodies/bob/com_position", result.bob_position, unit="m", description="Rigid-bob centre-of-mass position")
        _dataset(h5, "/bodies/bob/com_velocity", result.bob_velocity, unit="m/s", description="Rigid-bob centre-of-mass velocity")
        _dataset(h5, "/bodies/bob/quaternion_body_to_world", result.bob_quaternion, unit="1", description="Scalar-first rigid-bob orientation quaternion")
        _dataset(h5, "/bodies/bob/angular_velocity_world", result.bob_angular_velocity, unit="rad/s", description="Rigid-bob angular velocity in world coordinates")
        _dataset(h5, "/bodies/bob/attachment_position", result.bob_attachment_position, unit="m", description="Eccentric lower-rod attachment point")
        h5["/bodies/bob"].attrs["radius_m"] = model.bob_radius
        h5["/bodies/bob"].attrs["mass_kg"] = model.bob_mass
        h5["/bodies/bob"].attrs["scalar_inertia_kg_m2"] = model.bob_inertia
        h5["/bodies/bob"].attrs["attachment_body_m"] = model.attachment_body
        for name, branch in model.branches.items():
            _dataset(
                h5,
                f"/cables/{name}/material_path/position",
                result.cable_positions[name],
                unit="m",
                description=f"{name} endpoint-plus-bead material path",
            )
            _dataset(
                h5,
                f"/cables/{name}/material_path/velocity",
                result.cable_velocities[name],
                unit="m/s",
                description=f"{name} endpoint-plus-bead material velocities",
            )
            _dataset(
                h5,
                f"/cables/{name}/segments/signed_axial_force",
                result.cable_axial_force[name],
                unit="N",
                description=(
                    f"{name} signed local axial force; tension is positive and "
                    "compression is negative"
                ),
            )
            _dataset(
                h5,
                f"/cables/{name}/segments/tension",
                result.cable_tension[name],
                unit="N",
                description=(
                    f"{name} non-negative tensile part of signed axial force; "
                    "used by tension-state event observables"
                ),
            )
            _dataset(
                h5,
                f"/cables/{name}/segments/rest_length",
                branch.segment_rest_length,
                unit="m",
                description=f"{name} local axial-link natural length",
            )
            h5[f"/cables/{name}"].attrs["bending_stiffness_N_m2"] = branch.ei
        _dataset(h5, "/reactions/support_A", result.reactions["support_A"], unit="N", description="Force exerted by support A on the simulated system")
        _dataset(h5, "/reactions/support_B", result.reactions["support_B"], unit="N", description="Force exerted by support B on the simulated system")
        energy_units = {
            "kinetic": "J",
            "kinetic_particles": "J",
            "kinetic_bob_translation": "J",
            "kinetic_bob_rotation": "J",
            "gravitational": "J",
            "elastic_axial": "J",
            "elastic_bending": "J",
            "mechanical": "J",
            "axial_dissipation_rate": "W",
            "aero_dissipation_rate": "W",
            "air_work_rate": "W",
            "support_work_rate": "W",
            "dissipation_axial": "J",
            "dissipation_aero": "J",
            "work_air": "J",
            "work_support": "J",
            "balance_residual": "1",
        }
        for key, values in result.energy.items():
            _dataset(
                h5,
                f"/energy/{key}",
                values,
                unit=energy_units.get(key, "1"),
                description=key.replace("_", " "),
            )
        guard_metadata = model.guard_component_metadata()
        if set(result.guard_margins) != set(guard_metadata):
            raise ValueError(
                "HF result guard vocabulary does not match the model metadata."
            )
        for key, values in result.guard_margins.items():
            dataset = _dataset(
                h5,
                f"/validity/guard_margin/{key}",
                values,
                unit=str(guard_metadata[key]["unit"]),
                description=f"Positive-inside validity margin for {key}",
            )
            dataset.attrs["normalization_scale"] = float(
                guard_metadata[key]["scale"]
            )
            dataset.attrs["raw_machine_tolerance"] = float(
                guard_metadata[key]["tolerance"]
            )

"""H1 finite-mass, finite-stiffness, tension-only 3-D cable model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import sparse
from scipy.sparse.linalg import splu

from ypendulum.config.models import SimulationConfig
from ypendulum.config.units import as_vector3, to_si
from ypendulum.elements import (
    assemble_element_forces,
    assemble_element_tangent,
    assemble_mass_matrix,
    evaluate_cable_elements,
)
from ypendulum.forces import bob_buoyancy_force, bob_drag, cable_normal_drag, gravity_load
from ypendulum.geometry import MeshTopology, build_topology
from ypendulum.materials import TabulatedTensionMaterial

Array = npt.NDArray[np.float64]


@dataclass(frozen=True)
class ForceEvaluation:
    full_positions: Array
    full_velocities: Array
    boundary_acceleration: Array
    full_force: Array
    free_force: Array
    internal_force: Array
    aero_force: Array
    tension: Array
    stretch: Array
    active: npt.NDArray[np.bool_]
    elastic_energy: float
    material_dissipation_rate: float
    aero_relative_dissipation_rate: float
    aero_work_rate: float
    tangent_position: sparse.csr_matrix | None
    tangent_velocity: sparse.csr_matrix | None


class FullCableModel:
    """First-principles H1 model with constant translational mass matrix."""

    def __init__(self, cfg: SimulationConfig):
        self.cfg = cfg
        self.topology: MeshTopology = build_topology(cfg)
        self.gravity = as_vector3(cfg.environment.gravity, default_unit="m/s^2")
        self.air_density = float(to_si(cfg.environment.air_density, default_unit="kg/m^3"))
        self.air_velocity = as_vector3(cfg.environment.air_velocity, default_unit="m/s")
        self.junction_mass = float(to_si(cfg.junction.mass, default_unit="kg"))
        self.junction_drag_linear = float(
            to_si(cfg.junction.drag_linear, default_unit="N*s/m")
        )
        self.bob_mass = float(to_si(cfg.bob.mass, default_unit="kg"))
        self.bob_radius = float(to_si(cfg.bob.radius, default_unit="m"))
        self.bob_cd = float(to_si(cfg.bob.drag.cd, default_unit="dimensionless"))
        self.bob_linear_drag = float(
            to_si(cfg.bob.drag.linear_coefficient, default_unit="N*s/m")
        )
        if cfg.bob.drag.model == "linear":
            self.bob_cd = 0.0
        elif cfg.bob.drag.model == "quadratic":
            self.bob_linear_drag = 0.0
        self.point_masses = {
            self.topology.junction_node: self.junction_mass,
            self.topology.bob_node: self.bob_mass,
        }
        self.mass_full = assemble_mass_matrix(
            self.topology.node_count,
            self.topology.elements,
            self.point_masses,
            kind=cfg.solver.mass_matrix,
        ).tocsr()
        fd = self.topology.free_dofs
        cd = self.topology.constrained_dofs
        self.mass_ff = self.mass_full[fd][:, fd].tocsr()
        self.mass_fc = self.mass_full[fd][:, cd].tocsr()
        self.mass_cf = self.mass_full[cd][:, fd].tocsr()
        self.mass_cc = self.mass_full[cd][:, cd].tocsr()
        diag = self.mass_ff.diagonal()
        self._mass_is_diagonal = self.mass_ff.nnz == diag.size and np.all(diag > 0)
        self._mass_diag = diag if self._mass_is_diagonal else None
        self._mass_lu = None if self._mass_is_diagonal else splu(self.mass_ff.tocsc())
        self.gravity_force_full = gravity_load(
            self.mass_full, self.gravity, self.topology.node_count
        ).reshape(self.topology.node_count, 3)
        self.buoyancy = bob_buoyancy_force(
            self.air_density, self.bob_radius, self.gravity, cfg.bob.buoyancy
        )
        self.length_guard = 1e-12 * max(self.topology.characteristic_length, 1.0)
        self._cable_drag_enabled = np.zeros(self.topology.elements.count, dtype=bool)
        self.material_overrides: dict[int, TabulatedTensionMaterial] = {}
        self._material_name_by_id: dict[int, str] = {}
        self.material_extrapolation_seen: set[str] = set()
        for cable_id, name in enumerate(("upper_A", "upper_B", "lower")):
            cable = getattr(cfg.cables, name)
            self._cable_drag_enabled[self.topology.cable_slices[name]] = cable.drag_enabled
            if cable.material_model == "tabulated_tension_extension":
                assert cable.table_file is not None
                table_path = Path(cable.table_file).expanduser()
                if not table_path.is_absolute() and cfg.source_path is not None:
                    table_path = cfg.source_path.parent / table_path
                if not table_path.exists():
                    raise FileNotFoundError(
                        f"Tabulated material file for cables.{name} not found: {table_path}"
                    )
                eta_a = float(to_si(cable.axial_viscosity, default_unit="Pa*s")) * (
                    np.pi * float(to_si(cable.diameter, default_unit="m")) ** 2 / 4.0
                )
                self._material_name_by_id[cable_id] = name
                self.material_overrides[cable_id] = TabulatedTensionMaterial.from_csv(
                    table_path,
                    calibration_length=float(
                        to_si(
                            cable.rest_length
                            if cable.table_calibration_length is None
                            else cable.table_calibration_length,
                            default_unit="m",
                        )
                    ),
                    viscosity=eta_a,
                )

    @property
    def position_dof_count(self) -> int:
        return int(self.topology.free_dofs.size)

    @property
    def state_size(self) -> int:
        return 2 * self.position_dof_count

    def mass_solve(self, rhs: Array) -> Array:
        arr = np.asarray(rhs, dtype=float)
        if self._mass_is_diagonal:
            assert self._mass_diag is not None
            if arr.ndim == 1:
                return arr / self._mass_diag
            return arr / self._mass_diag[:, None]
        assert self._mass_lu is not None
        return np.asarray(self._mass_lu.solve(arr), dtype=float)

    def split_state(self, y: Array) -> tuple[Array, Array]:
        n = self.position_dof_count
        state = np.asarray(y, dtype=float)
        if state.shape != (2 * n,):
            raise ValueError(f"Expected state shape {(2*n,)}, got {state.shape}.")
        return state[:n], state[n:]

    def pack_state(self, positions: Array, velocities: Array) -> Array:
        return np.concatenate(
            [self.topology.pack_free(positions), self.topology.pack_free(velocities)]
        )

    def evaluate(
        self,
        t: float,
        q_free: Array,
        v_free: Array,
        *,
        compute_tangent: bool = False,
        gravity_scale: float = 1.0,
        include_aero: bool = True,
    ) -> ForceEvaluation:
        q, v, a_boundary = self.topology.expand_free(t, q_free, v_free)
        response = evaluate_cable_elements(
            q,
            v,
            self.topology.elements,
            length_guard=self.length_guard,
            compute_tangent=compute_tangent,
            material_overrides=self.material_overrides,
        )
        for cable_id, material in self.material_overrides.items():
            if material.extrapolated_last_call:
                self.material_extrapolation_seen.add(self._material_name_by_id[cable_id])
        internal = assemble_element_forces(
            self.topology.node_count, self.topology.elements, response
        )
        total = internal + gravity_scale * self.gravity_force_full
        total[self.topology.bob_node] += gravity_scale * self.buoyancy
        aero = np.zeros_like(total)
        tangent_v_extra = sparse.csr_matrix(
            (3 * self.topology.node_count, 3 * self.topology.node_count)
        )
        aero_relative_diss = 0.0

        if include_aero:
            bf, bj, bd = bob_drag(
                v[self.topology.bob_node],
                self.air_velocity,
                air_density=self.air_density,
                radius=self.bob_radius,
                cd=self.bob_cd,
                linear_coefficient=self.bob_linear_drag,
                enabled=self.cfg.bob.drag.enabled,
            )
            aero[self.topology.bob_node] += bf
            aero_relative_diss += bd
            if compute_tangent and np.any(bj):
                idx = np.arange(
                    3 * self.topology.bob_node, 3 * self.topology.bob_node + 3
                )
                tangent_v_extra = tangent_v_extra + sparse.coo_matrix(
                    (bj.ravel(), (np.repeat(idx, 3), np.tile(idx, 3))),
                    shape=tangent_v_extra.shape,
                ).tocsr()

            if self.junction_drag_linear > 0:
                rel = v[self.topology.junction_node] - self.air_velocity
                jf = -self.junction_drag_linear * rel
                aero[self.topology.junction_node] += jf
                aero_relative_diss += self.junction_drag_linear * float(np.dot(rel, rel))
                if compute_tangent:
                    idx = np.arange(
                        3 * self.topology.junction_node,
                        3 * self.topology.junction_node + 3,
                    )
                    block = -self.junction_drag_linear * np.eye(3)
                    tangent_v_extra = tangent_v_extra + sparse.coo_matrix(
                        (block.ravel(), (np.repeat(idx, 3), np.tile(idx, 3))),
                        shape=tangent_v_extra.shape,
                    ).tocsr()

            if np.any(self._cable_drag_enabled):
                ca = cable_normal_drag(
                    q,
                    v,
                    response.kinematics,
                    self.topology.elements,
                    air_velocity=self.air_velocity,
                    air_density=self.air_density,
                    enabled_mask=self._cable_drag_enabled,
                    node_count=self.topology.node_count,
                )
                aero += ca.nodal_forces
                tangent_v_extra = tangent_v_extra + ca.velocity_tangent
                aero_relative_diss += ca.dissipation_rate

        total += aero
        full_flat = total.reshape(-1)
        fd = self.topology.free_dofs
        boundary_acc_flat = a_boundary.reshape(-1)[self.topology.constrained_dofs]
        free_force = full_flat[fd] - np.asarray(self.mass_fc @ boundary_acc_flat).reshape(-1)

        tangent_x = None
        tangent_v = None
        if compute_tangent:
            tangent_x = assemble_element_tangent(
                self.topology.node_count,
                self.topology.elements,
                response.tangent_position,
            )
            tangent_v = assemble_element_tangent(
                self.topology.node_count,
                self.topology.elements,
                response.tangent_velocity,
            ) + tangent_v_extra

        # The mechanical power of aerodynamic forces decomposes exactly as
        #
        #   sum(F_aero . v) = -D_relative + sum(F_aero . u_air).
        #
        # The second term is the power supplied by the prescribed, spatially
        # uniform air field.  Storing total mechanical power here would count
        # relative drag twice (and make the energy audit self-cancelling).
        aero_work = float(np.sum(aero * self.air_velocity[None, :]))
        return ForceEvaluation(
            full_positions=q,
            full_velocities=v,
            boundary_acceleration=a_boundary,
            full_force=total,
            free_force=free_force,
            internal_force=internal,
            aero_force=aero,
            tension=response.tension,
            stretch=response.kinematics.delta,
            active=response.active,
            elastic_energy=float(np.sum(response.elastic_energy)),
            material_dissipation_rate=float(np.sum(response.dissipation_rate)),
            aero_relative_dissipation_rate=float(aero_relative_diss),
            aero_work_rate=aero_work,
            tangent_position=tangent_x,
            tangent_velocity=tangent_v,
        )

    def acceleration(self, t: float, q_free: Array, v_free: Array) -> Array:
        evaluation = self.evaluate(t, q_free, v_free, compute_tangent=False)
        return self.mass_solve(evaluation.free_force)

    def rhs(self, t: float, y: Array) -> Array:
        qf, vf = self.split_state(y)
        af = self.acceleration(t, qf, vf)
        return np.concatenate([vf, af])

    def jacobian(self, t: float, y: Array) -> Array | sparse.csr_matrix:
        qf, vf = self.split_state(y)
        ev = self.evaluate(t, qf, vf, compute_tangent=True)
        assert ev.tangent_position is not None and ev.tangent_velocity is not None
        fd = self.topology.free_dofs
        kff = ev.tangent_position[fd][:, fd].tocsr()
        cff = ev.tangent_velocity[fd][:, fd].tocsr()
        n = self.position_dof_count
        if self._mass_is_diagonal:
            assert self._mass_diag is not None
            aq = sparse.diags(1.0 / self._mass_diag) @ kff
            av = sparse.diags(1.0 / self._mass_diag) @ cff
            zero = sparse.csr_matrix((n, n))
            eye = sparse.eye(n, format="csr")
            return sparse.bmat([[zero, eye], [aq, av]], format="csr")
        aq = self.mass_solve(kff.toarray())
        av = self.mass_solve(cff.toarray())
        out = np.zeros((2 * n, 2 * n), dtype=float)
        out[:n, n:] = np.eye(n)
        out[n:, :n] = aq
        out[n:, n:] = av
        return out

    def full_acceleration(
        self, t: float, q_free: Array, v_free: Array, evaluation: ForceEvaluation | None = None
    ) -> Array:
        ev = evaluation or self.evaluate(t, q_free, v_free)
        af = self.mass_solve(ev.free_force)
        full = ev.boundary_acceleration.copy()
        full[self.topology.free_nodes] = af.reshape(-1, 3)
        return full

    def support_reactions(
        self, t: float, q_free: Array, v_free: Array, evaluation: ForceEvaluation | None = None
    ) -> tuple[Array, Array]:
        ev = evaluation or self.evaluate(t, q_free, v_free)
        acc = self.full_acceleration(t, q_free, v_free, ev).reshape(-1)
        residual = np.asarray(self.mass_full @ acc).reshape(-1) - ev.full_force.reshape(-1)
        r = residual[self.topology.constrained_dofs].reshape(2, 3)
        return r[0], r[1]

    def energy_snapshot(
        self, t: float, q_free: Array, v_free: Array, evaluation: ForceEvaluation | None = None
    ) -> dict[str, float]:
        ev = evaluation or self.evaluate(t, q_free, v_free)
        qflat = ev.full_positions.reshape(-1)
        vflat = ev.full_velocities.reshape(-1)
        kinetic = 0.5 * float(vflat @ (self.mass_full @ vflat))
        gravitational = -float(qflat @ self.gravity_force_full.reshape(-1))
        buoyancy_potential = -float(
            np.dot(ev.full_positions[self.topology.bob_node], self.buoyancy)
        )
        elastic = ev.elastic_energy
        ra, rb = self.support_reactions(t, q_free, v_free, ev)
        _, va, _ = self.topology.support_motion_a.state(t)
        _, vb, _ = self.topology.support_motion_b.state(t)
        support_power = float(np.dot(ra, va) + np.dot(rb, vb))
        return {
            "kinetic": kinetic,
            "gravitational": gravitational + buoyancy_potential,
            "elastic": elastic,
            "mechanical": kinetic + gravitational + buoyancy_potential + elastic,
            "material_dissipation_rate": ev.material_dissipation_rate,
            "aero_relative_dissipation_rate": ev.aero_relative_dissipation_rate,
            "aero_work_rate": ev.aero_work_rate,
            "support_work_rate": support_power,
        }

    def characteristic_times(self) -> dict[str, float]:
        gmag = max(float(np.linalg.norm(self.gravity)), 1e-12)
        total_lengths = [
            float(np.sum(self.topology.elements.rest_length[self.topology.cable_slices[name]]))
            for name in ("upper_A", "upper_B", "lower")
        ]
        pendulum = 2.0 * np.pi * np.sqrt(min(total_lengths) / gmag)
        E = self.topology.elements.ea / self.topology.elements.area
        c = np.sqrt(E / self.topology.elements.density)
        crossing = self.topology.elements.rest_length / c
        return {
            "pendulum_period_estimate": float(pendulum),
            "minimum_element_wave_crossing": float(np.min(crossing)),
            "maximum_longitudinal_angular_frequency_estimate": float(
                np.pi / np.min(crossing)
            ),
        }

    def diagnostics(self) -> dict[str, Any]:
        cable_mass = float(np.sum(self.topology.elements.element_mass))
        times = self.characteristic_times()
        max_tension_est = self.bob_mass * float(np.linalg.norm(self.gravity)) * 4.0
        min_ea = float(np.min(self.topology.elements.ea))
        return {
            "node_count": self.topology.node_count,
            "free_position_dofs": self.position_dof_count,
            "state_size": self.state_size,
            "element_count": self.topology.elements.count,
            "mass_matrix_kind": self.cfg.solver.mass_matrix,
            "mass_matrix_nnz": int(self.mass_full.nnz),
            "epsilon_junction": self.junction_mass / self.bob_mass,
            "epsilon_string_mass": cable_mass / self.bob_mass,
            "epsilon_extension_estimate": max_tension_est / min_ea,
            "tabulated_material_extrapolated_cables": sorted(
                self.material_extrapolation_seen
            ),
            **times,
        }

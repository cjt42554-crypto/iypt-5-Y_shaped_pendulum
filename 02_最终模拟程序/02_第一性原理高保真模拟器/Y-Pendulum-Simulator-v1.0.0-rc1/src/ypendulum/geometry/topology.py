"""Fixed-knot Y topology and finite-element mesh construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np
import numpy.typing as npt
from scipy.optimize import least_squares

from ypendulum.config.models import SimulationConfig
from ypendulum.config.units import as_vector3, to_si
from ypendulum.elements.cable3d import CableElementBatch

from .reduced_geometry import fixed_knot_upper_geometry, unit
from .supports import SupportMotion

Array = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

CABLE_NAMES = ("upper_A", "upper_B", "lower")


@dataclass(frozen=True)
class MeshTopology:
    node_count: int
    reference_positions: Array
    node_labels: tuple[str, ...]
    elements: CableElementBatch
    cable_slices: dict[str, slice]
    cable_node_paths: dict[str, IntArray]
    support_nodes: IntArray
    free_nodes: IntArray
    free_dofs: IntArray
    constrained_dofs: IntArray
    junction_node: int
    bob_node: int
    support_motion_a: SupportMotion
    support_motion_b: SupportMotion
    characteristic_length: float

    def boundary_state(self, t: float) -> tuple[Array, Array, Array]:
        positions = np.zeros((self.node_count, 3), dtype=float)
        velocities = np.zeros_like(positions)
        accelerations = np.zeros_like(positions)
        for node, motion in zip(
            self.support_nodes,
            (self.support_motion_a, self.support_motion_b),
            strict=True,
        ):
            p, v, a = motion.state(t)
            positions[node], velocities[node], accelerations[node] = p, v, a
        return positions, velocities, accelerations

    def expand_free(self, t: float, q_free: Array, v_free: Array) -> tuple[Array, Array, Array]:
        q = np.empty((self.node_count, 3), dtype=float)
        v = np.empty_like(q)
        a_boundary = np.zeros_like(q)
        bp, bv, ba = self.boundary_state(t)
        q[self.support_nodes] = bp[self.support_nodes]
        v[self.support_nodes] = bv[self.support_nodes]
        a_boundary[self.support_nodes] = ba[self.support_nodes]
        q[self.free_nodes] = np.asarray(q_free, dtype=float).reshape(-1, 3)
        v[self.free_nodes] = np.asarray(v_free, dtype=float).reshape(-1, 3)
        return q, v, a_boundary

    def pack_free(self, full: Array) -> Array:
        return np.asarray(full[self.free_nodes], dtype=float).reshape(-1)


def _cable_properties(cfg) -> tuple[float, float, float, float, float, float]:
    length = float(to_si(cfg.rest_length, default_unit="m"))
    diameter = float(to_si(cfg.diameter, default_unit="m"))
    density = float(to_si(cfg.density, default_unit="kg/m^3"))
    young = float(to_si(cfg.young_modulus, default_unit="Pa"))
    viscosity = float(to_si(cfg.axial_viscosity, default_unit="Pa*s"))
    area = np.pi * diameter**2 / 4.0
    return length, diameter, density, young, viscosity, area


def _approximate_loaded_geometry(cfg: SimulationConfig) -> tuple[Array, Array]:
    """Return a mechanically informed initial guess for the loaded Y geometry.

    The junction is obtained from the tension-only axial constitutive law and
    point-force equilibrium in the plane spanned by the support axis and
    gravity. This supports physically valid prestressed installations for which
    the two *natural-length* spheres do not intersect. The full cable FE static
    solver subsequently resolves distributed weight, sag and all mesh nodes.
    """

    A = as_vector3(cfg.supports.A.position, default_unit="m")
    B = as_vector3(cfg.supports.B.position, default_unit="m")
    g = as_vector3(cfg.environment.gravity, default_unit="m/s^2")
    gmag = float(np.linalg.norm(g))
    ghat = unit(g, name="gravity")

    ua = _cable_properties(cfg.cables.upper_A)
    ub = _cable_properties(cfg.cables.upper_B)
    ll = _cable_properties(cfg.cables.lower)
    La, _, rhoa, Ea, _, Aa = ua
    Lb, _, rhob, Eb, _, Ab = ub
    Ll, _, rhol, El, _, Al = ll
    ea_a, ea_b, ea_l = Ea * Aa, Eb * Ab, El * Al
    m_a, m_b, m_l = rhoa * Aa * La, rhob * Ab * Lb, rhol * Al * Ll
    m_j = float(to_si(cfg.junction.mass, default_unit="kg"))
    m_bob = float(to_si(cfg.bob.mass, default_unit="kg"))

    axis_vector = B - A
    d = float(np.linalg.norm(axis_vector))
    ex = axis_vector / d
    g_perp = ghat - float(np.dot(ghat, ex)) * ex
    if np.linalg.norm(g_perp) <= 1e-12:
        trial = np.array([0.0, 0.0, 1.0])
        if abs(float(np.dot(trial, ex))) > 0.9:
            trial = np.array([0.0, 1.0, 0.0])
        g_perp = trial - float(np.dot(trial, ex)) * ex
    er = unit(g_perp, name="gravity plane direction")

    t_lower = (m_bob + 0.5 * m_l) * gmag
    downward_force = (t_lower + (m_j + 0.5 * (m_a + m_b)) * gmag) * ghat

    scale = max(1.0001, 1.0001 * d / max(La + Lb, 1e-15))
    guess_a, guess_b = scale * La, scale * Lb
    lower_bound = abs(guess_a - guess_b)
    if d <= lower_bound:
        x0 = d * La / (La + Lb)
        y0 = 0.05 * max(La, Lb, d)
    else:
        x0 = (guess_a**2 - guess_b**2 + d**2) / (2.0 * d)
        y0 = np.sqrt(max(guess_a**2 - x0**2, (1e-4 * max(d, La, Lb)) ** 2))

    def state(xy: np.ndarray) -> tuple[np.ndarray, float, float, np.ndarray]:
        J = A + float(xy[0]) * ex + float(xy[1]) * er
        da = A - J
        db = B - J
        ra = float(np.linalg.norm(da))
        rb = float(np.linalg.norm(db))
        if min(ra, rb) <= 1e-14:
            return J, 0.0, 0.0, np.full(3, 1e30)
        ta = max(ea_a * (ra - La) / La, 0.0)
        tb = max(ea_b * (rb - Lb) / Lb, 0.0)
        force = ta * da / ra + tb * db / rb + downward_force
        return J, ta, tb, force

    def residual(xy: np.ndarray) -> np.ndarray:
        _J, _ta, _tb, force = state(xy)
        return np.array([np.dot(force, ex), np.dot(force, er)], dtype=float)

    length_scale = max(La, Lb, d, 1e-6)
    solution = least_squares(
        residual,
        np.array([x0, y0], dtype=float),
        bounds=(
            np.array([-2.0 * length_scale, 1e-10 * length_scale]),
            np.array([d + 2.0 * length_scale, 5.0 * length_scale]),
        ),
        xtol=1e-12,
        ftol=1e-12,
        gtol=1e-12,
        max_nfev=500,
        x_scale=np.array([length_scale, length_scale]),
    )
    J, tension_a, tension_b, force = state(solution.x)
    force_scale = max(float(np.linalg.norm(downward_force)), 1.0)
    if (
        not solution.success
        or float(np.linalg.norm(force)) > 1e-7 * force_scale
        or tension_a <= 0.0
        or tension_b <= 0.0
    ):
        raise ValueError(
            "Could not construct a two-upper-cable tensile equilibrium initial guess. "
            f"residual={np.linalg.norm(force):.3e} N, "
            f"T_A={tension_a:.3e} N, T_B={tension_b:.3e} N. "
            "Check support spacing, natural lengths, EA and suspended load."
        )

    loaded_l = Ll * (1.0 + t_lower / ea_l)
    P = J + loaded_l * ghat
    return J, P


def _append_chain(
    positions: list[Array],
    labels: list[str],
    start_node: int,
    end_position: Array,
    end_label: str,
    elements_count: int,
    end_existing: int | None = None,
) -> tuple[list[int], int]:
    start = positions[start_node]
    path = [start_node]
    for k in range(1, elements_count):
        alpha = k / elements_count
        positions.append((1.0 - alpha) * start + alpha * end_position)
        labels.append(f"{end_label}_internal_{k}")
        path.append(len(positions) - 1)
    if end_existing is None:
        positions.append(np.asarray(end_position, dtype=float))
        labels.append(end_label)
        end_node = len(positions) - 1
    else:
        end_node = int(end_existing)
    path.append(end_node)
    return path, end_node


def build_topology(cfg: SimulationConfig) -> MeshTopology:
    base_directory = None if cfg.source_path is None else cfg.source_path.parent
    support_a = SupportMotion.from_config(cfg.supports.A, base_directory=base_directory)
    support_b = SupportMotion.from_config(cfg.supports.B, base_directory=base_directory)
    A, _, _ = support_a.state(0.0)
    B, _, _ = support_b.state(0.0)
    J, P = _approximate_loaded_geometry(cfg)

    positions: list[Array] = [A.copy(), B.copy()]
    labels = ["support_A", "support_B"]
    path_a, junction = _append_chain(
        positions, labels, 0, J, "junction", cfg.cables.upper_A.elements
    )
    path_b, _ = _append_chain(
        positions,
        labels,
        1,
        J,
        "junction",
        cfg.cables.upper_B.elements,
        end_existing=junction,
    )
    path_l, bob = _append_chain(
        positions, labels, junction, P, "bob", cfg.cables.lower.elements
    )

    node_i: list[int] = []
    node_j: list[int] = []
    rest_lengths: list[float] = []
    ea: list[float] = []
    eta_a: list[float] = []
    area: list[float] = []
    density: list[float] = []
    diameter: list[float] = []
    cd: list[float] = []
    cable_ids: list[int] = []
    slices: dict[str, slice] = {}
    node_paths: dict[str, IntArray] = {}

    for cid, (name, path, cable_cfg) in enumerate(
        (
            ("upper_A", path_a, cfg.cables.upper_A),
            ("upper_B", path_b, cfg.cables.upper_B),
            ("lower", path_l, cfg.cables.lower),
        )
    ):
        start_idx = len(node_i)
        L, dia, rho, E, eta, Aarea = _cable_properties(cable_cfg)
        le = L / cable_cfg.elements
        for i, j in zip(path[:-1], path[1:], strict=True):
            node_i.append(i)
            node_j.append(j)
            rest_lengths.append(le)
            ea.append(E * Aarea)
            eta_a.append(eta * Aarea)
            area.append(Aarea)
            density.append(rho)
            diameter.append(dia)
            cd.append(float(cable_cfg.drag_cd_normal))
            cable_ids.append(cid)
        slices[name] = slice(start_idx, len(node_i))
        node_paths[name] = np.asarray(path, dtype=np.int64)

    batch = CableElementBatch(
        node_i=np.asarray(node_i, dtype=np.int64),
        node_j=np.asarray(node_j, dtype=np.int64),
        rest_length=np.asarray(rest_lengths, dtype=float),
        ea=np.asarray(ea, dtype=float),
        eta_a=np.asarray(eta_a, dtype=float),
        area=np.asarray(area, dtype=float),
        density=np.asarray(density, dtype=float),
        diameter=np.asarray(diameter, dtype=float),
        drag_cd_normal=np.asarray(cd, dtype=float),
        cable_id=np.asarray(cable_ids, dtype=np.int64),
    )
    node_count = len(positions)
    support_nodes = np.asarray([0, 1], dtype=np.int64)
    free_nodes = np.asarray([i for i in range(node_count) if i not in {0, 1}], dtype=np.int64)
    free_dofs = np.concatenate([np.arange(3 * i, 3 * i + 3) for i in free_nodes]).astype(np.int64)
    constrained_dofs = np.arange(6, dtype=np.int64)
    characteristic_length = max(
        float(to_si(cfg.cables.upper_A.rest_length, default_unit="m")),
        float(to_si(cfg.cables.upper_B.rest_length, default_unit="m")),
        float(to_si(cfg.cables.lower.rest_length, default_unit="m")),
    )
    return MeshTopology(
        node_count=node_count,
        reference_positions=np.asarray(positions, dtype=float),
        node_labels=tuple(labels),
        elements=batch,
        cable_slices=slices,
        cable_node_paths=node_paths,
        support_nodes=support_nodes,
        free_nodes=free_nodes,
        free_dofs=free_dofs,
        constrained_dofs=constrained_dofs,
        junction_node=junction,
        bob_node=bob,
        support_motion_a=support_a,
        support_motion_b=support_b,
        characteristic_length=characteristic_length,
    )

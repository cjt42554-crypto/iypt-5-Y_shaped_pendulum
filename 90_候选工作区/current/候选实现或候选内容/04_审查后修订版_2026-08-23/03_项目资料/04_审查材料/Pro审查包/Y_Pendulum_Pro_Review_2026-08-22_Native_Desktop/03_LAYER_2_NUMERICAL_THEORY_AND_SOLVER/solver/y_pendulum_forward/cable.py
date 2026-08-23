"""Material-coordinate P1 finite-element backend for FWD-CABLE-1.0.

The implementation is a conforming approximation of the frozen weak form
(F.22).  It intentionally contains no bending stiffness, rotational frame,
added mass, junction drag, compression penalty, or tangent regularization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
import warnings

import numpy as np
from scipy.integrate import cumulative_trapezoid, solve_ivp
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize

from .activation import activation_primitive, tension_components
from .contracts import (
    MAX_ELEMENTS_PER_BRANCH,
    MAX_STATIC_ITERATIONS,
    MAX_STATIC_MULTISTART,
    MAX_TOTAL_CABLE_ELEMENTS,
    SimulationResult,
    MIN_SOLVER_RTOL,
    ValidationIssue,
    as_vector3,
    base_validation,
    is_finite_number,
    numerical_time_resource_issues,
    reject_unknown_keys,
    require_number,
)
from .initial_fields import PolynomialField, build_polynomial_field
from .observations import evaluate_observations
from .providers import (
    AirVelocity,
    MaterialForce,
    PointForce,
    PrescribedMotion,
    build_air,
    build_material_force,
    build_motion,
    build_point_force,
    validate_air_window,
    validate_force_window,
    validate_motion_window,
)
from .torus import _output_times


BRANCHES = ("A", "B", "lower")
CABLE_NUMERICAL_FIELDS = {
    "elements",
    "quadrature_order",
    "method",
    "rtol",
    "atol",
    "atol_position",
    "atol_velocity",
    "max_step",
    "output_dt",
    "event_cluster_tolerance",
    "static_multistart",
    "static_maxiter",
    "static_gradient_tolerance",
    "static_energy_tolerance",
    "static_uniqueness_tolerance",
}


@dataclass(frozen=True)
class OpenBoxMaterialDomain:
    lambda_lower: float
    lambda_upper: float
    rate_lower: float
    rate_upper: float

    def component_margins(self, stretch, rate) -> dict[str, np.ndarray]:
        stretch = np.asarray(stretch, dtype=float)
        rate = np.asarray(rate, dtype=float)
        return {
            "lambda_lower": stretch - self.lambda_lower,
            "lambda_upper": self.lambda_upper - stretch,
            "rate_lower": rate - self.rate_lower,
            "rate_upper": self.rate_upper - rate,
        }

    def margin(self, stretch, rate) -> float:
        values = self.component_margins(stretch, rate)
        return float(min(np.min(value) for value in values.values()))


@dataclass(frozen=True)
class BranchParameters:
    name: str
    L0: float
    mu: float
    EA: float
    Ca: float
    delta: float
    c_parallel: float
    c_perp: float
    d_parallel: float
    d_perp: float
    material_domain: OpenBoxMaterialDomain


@dataclass(frozen=True)
class InitialBranch:
    position: PolynomialField
    velocity: PolynomialField


@dataclass(frozen=True)
class CableGuard:
    name: str
    evaluate_fn: Callable[[np.ndarray, float, dict[str, int]], float]
    length_scale: float
    description: dict[str, Any]

    def evaluate(self, positions: np.ndarray, t: float, node_index: dict[str, int]) -> float:
        return float(self.evaluate_fn(positions, float(t), node_index))


@dataclass(frozen=True)
class CablePhysicalInput:
    g: float
    e_z: np.ndarray
    branches: dict[str, BranchParameters]
    junction_mass: float
    bob_mass: float
    rho_air: float
    bob_volume: float
    bob_c1: float
    bob_c2: float
    lambda_min: float
    T: float
    support_A: PrescribedMotion
    support_B: PrescribedMotion
    air: AirVelocity
    distributed_forces: dict[str, MaterialForce]
    junction_force: PointForce
    bob_force: PointForce
    guards: list[CableGuard]
    initial_mode: str
    initial_branches: dict[str, InitialBranch]
    hold_fixed_nodes: dict[str, np.ndarray]
    r_J0: np.ndarray
    v_J0: np.ndarray
    r_m0: np.ndarray
    v_m0: np.ndarray


def _bound(value: Any, *, lower: bool, path: str, issues: list[ValidationIssue]) -> float:
    if value is None:
        return -np.inf if lower else np.inf
    if not is_finite_number(value):
        issues.append(ValidationIssue("MATERIAL_DOMAIN", path, value, "finite real or null"))
        return -np.inf if lower else np.inf
    return float(value)


def _material_domain(spec: Any, path: str, issues: list[ValidationIssue]) -> OpenBoxMaterialDomain:
    if not isinstance(spec, dict) or spec.get("kind") != "open_box":
        issues.append(
            ValidationIssue(
                "MATERIAL_DOMAIN",
                path,
                spec,
                "{kind:'open_box', lambda_lower, lambda_upper, rate_lower, rate_upper}",
            )
        )
        spec = {"kind": "open_box"}
    reject_unknown_keys(
        spec,
        {"kind", "lambda_lower", "lambda_upper", "rate_lower", "rate_upper"},
        path,
        issues,
    )
    lo = _bound(spec.get("lambda_lower"), lower=True, path=f"{path}.lambda_lower", issues=issues)
    hi = _bound(spec.get("lambda_upper"), lower=False, path=f"{path}.lambda_upper", issues=issues)
    rlo = _bound(spec.get("rate_lower"), lower=True, path=f"{path}.rate_lower", issues=issues)
    rhi = _bound(spec.get("rate_upper"), lower=False, path=f"{path}.rate_upper", issues=issues)
    if not lo < hi:
        issues.append(ValidationIssue("MATERIAL_DOMAIN", path, [lo, hi], "lambda_lower < lambda_upper"))
    if not rlo < rhi:
        issues.append(ValidationIssue("MATERIAL_DOMAIN", path, [rlo, rhi], "rate_lower < rate_upper"))
    return OpenBoxMaterialDomain(lo, hi, rlo, rhi)


def _build_guard(
    spec: Any,
    path: str,
    issues: list[ValidationIssue],
    default_length_scale: float,
) -> CableGuard:
    if not isinstance(spec, dict):
        issues.append(ValidationIssue("GUARD", path, spec, "guard object"))
        spec = {"kind": "bob_plane", "name": path, "normal": [0, 0, 1], "offset": 1}
    kind = spec.get("kind")
    kind_key = kind if isinstance(kind, str) else None
    name = spec.get("name")
    if not isinstance(name, str) or not name:
        issues.append(ValidationIssue("GUARD", f"{path}.name", name, "nonempty string"))
        name = path
    guard_allowed = {
        "bob_plane": {"kind", "name", "normal", "offset"},
        "bob_sphere_inside": {"kind", "name", "center", "radius"},
        "bob_sphere_outside": {"kind", "name", "center", "radius"},
        "node_distance": {"kind", "name", "node_1", "node_2", "minimum"},
    }.get(kind_key, {"kind", "name"})
    reject_unknown_keys(spec, guard_allowed, path, issues)
    if kind == "bob_plane":
        normal = as_vector3(spec.get("normal"), f"{path}.normal", issues)
        offset = spec.get("offset")
        if (
            not is_finite_number(offset)
            or abs(float(np.linalg.norm(normal)) - 1.0) > 1e-10
        ):
            issues.append(
                ValidationIssue(
                    "GUARD",
                    path,
                    spec,
                    "unit normal and finite SI length offset",
                )
            )
            offset = 0.0
        fn = lambda positions, _t, nodes: float(normal @ positions[nodes["bob"]] + float(offset))
        length_scale = max(default_length_scale, abs(float(offset)))
    elif kind in ("bob_sphere_inside", "bob_sphere_outside"):
        center = as_vector3(spec.get("center"), f"{path}.center", issues)
        radius = spec.get("radius")
        if not is_finite_number(radius) or float(radius) <= 0:
            issues.append(ValidationIssue("GUARD", f"{path}.radius", radius, "> 0"))
            radius = 1.0
        if kind == "bob_sphere_inside":
            fn = lambda positions, _t, nodes: float(float(radius) - np.linalg.norm(positions[nodes["bob"]] - center))
        else:
            fn = lambda positions, _t, nodes: float(np.linalg.norm(positions[nodes["bob"]] - center) - float(radius))
        length_scale = float(radius)
    elif kind == "node_distance":
        node_1, node_2 = spec.get("node_1"), spec.get("node_2")
        minimum = spec.get("minimum")
        valid_names = {"support_A", "support_B", "junction", "bob"}
        if node_1 not in tuple(valid_names) or node_2 not in tuple(valid_names):
            issues.append(ValidationIssue("GUARD", path, spec, f"node names in {sorted(valid_names)}"))
            node_1, node_2 = "junction", "bob"
        if not is_finite_number(minimum) or float(minimum) < 0:
            issues.append(ValidationIssue("GUARD", f"{path}.minimum", minimum, ">= 0"))
            minimum = 0.0
        fn = lambda positions, _t, nodes: float(np.linalg.norm(positions[nodes[node_1]] - positions[nodes[node_2]]) - float(minimum))
        length_scale = max(default_length_scale, float(minimum))
    else:
        issues.append(
            ValidationIssue(
                "GUARD_KIND",
                f"{path}.kind",
                kind,
                "bob_plane, bob_sphere_inside, bob_sphere_outside, or node_distance",
            )
        )
        fn = lambda _positions, _t, _nodes: 1.0
        length_scale = default_length_scale
    return CableGuard(str(name), fn, float(length_scale), dict(spec))


def parse_cable_physical(config: dict[str, Any]) -> tuple[list[ValidationIssue], CablePhysicalInput | None]:
    issues = base_validation(config, "FWD-CABLE-1.0")
    reject_unknown_keys(
        config,
        {
            "schema_version",
            "model_id",
            "theory_sha256",
            "units",
            "physical",
            "inputs",
            "initial_state",
            "numerics",
            "observation",
            "validation",
            "metadata",
        },
        "",
        issues,
    )
    if config.get("units") != "SI":
        issues.append(ValidationIssue("UNITS", "units", config.get("units"), "SI"))
    physical = config.get("physical")
    if not isinstance(physical, dict):
        issues.append(ValidationIssue("TYPE", "physical", physical, "object"))
        physical = {}
    reject_unknown_keys(
        physical,
        {
            "g",
            "e_z",
            "junction_mass",
            "bob_mass",
            "rho_air",
            "bob_volume",
            "bob_c1",
            "bob_c2",
            "lambda_min",
            "T",
            "branches",
        },
        "physical",
        issues,
    )
    g = require_number(physical, "g", "physical", issues, positive=True)
    e_z = as_vector3(physical.get("e_z"), "physical.e_z", issues)
    if abs(np.linalg.norm(e_z) - 1.0) > 1e-10:
        issues.append(ValidationIssue("COORDINATE", "physical.e_z", e_z, "unit downward vector"))
    junction_mass = require_number(physical, "junction_mass", "physical", issues, positive=True)
    bob_mass = require_number(physical, "bob_mass", "physical", issues, positive=True)
    rho_air = require_number(physical, "rho_air", "physical", issues, nonnegative=True)
    bob_volume = require_number(physical, "bob_volume", "physical", issues, nonnegative=True)
    bob_c1 = require_number(physical, "bob_c1", "physical", issues, nonnegative=True)
    bob_c2 = require_number(physical, "bob_c2", "physical", issues, nonnegative=True)
    lambda_min = require_number(physical, "lambda_min", "physical", issues, positive=True)
    T = require_number(physical, "T", "physical", issues, positive=True)

    branch_specs = physical.get("branches")
    if not isinstance(branch_specs, dict):
        issues.append(ValidationIssue("TYPE", "physical.branches", branch_specs, "object with A, B, lower"))
        branch_specs = {}
    if set(branch_specs) != set(BRANCHES):
        issues.append(ValidationIssue("BRANCH_SET", "physical.branches", sorted(branch_specs), str(BRANCHES)))
    branches: dict[str, BranchParameters] = {}
    for name in BRANCHES:
        spec = branch_specs.get(name, {})
        if not isinstance(spec, dict):
            issues.append(ValidationIssue("TYPE", f"physical.branches.{name}", spec, "object"))
            spec = {}
        reject_unknown_keys(
            spec,
            {
                "L0",
                "mu",
                "EA",
                "Ca",
                "delta",
                "c_parallel",
                "c_perp",
                "d_parallel",
                "d_perp",
                "material_domain",
            },
            f"physical.branches.{name}",
            issues,
        )
        branches[name] = BranchParameters(
            name=name,
            L0=require_number(spec, "L0", f"physical.branches.{name}", issues, positive=True),
            mu=require_number(spec, "mu", f"physical.branches.{name}", issues, positive=True),
            EA=require_number(spec, "EA", f"physical.branches.{name}", issues, positive=True),
            Ca=require_number(spec, "Ca", f"physical.branches.{name}", issues, nonnegative=True),
            delta=require_number(spec, "delta", f"physical.branches.{name}", issues, positive=True),
            c_parallel=require_number(spec, "c_parallel", f"physical.branches.{name}", issues, nonnegative=True),
            c_perp=require_number(spec, "c_perp", f"physical.branches.{name}", issues, nonnegative=True),
            d_parallel=require_number(spec, "d_parallel", f"physical.branches.{name}", issues, nonnegative=True),
            d_perp=require_number(spec, "d_perp", f"physical.branches.{name}", issues, nonnegative=True),
            material_domain=_material_domain(spec.get("material_domain"), f"physical.branches.{name}.material_domain", issues),
        )

    inputs = config.get("inputs")
    if not isinstance(inputs, dict):
        issues.append(ValidationIssue("TYPE", "inputs", inputs, "object"))
        inputs = {}
    reject_unknown_keys(
        inputs,
        {
            "support_A",
            "support_B",
            "air_velocity",
            "distributed_forces",
            "junction_force",
            "bob_force",
            "exit_guards",
        },
        "inputs",
        issues,
    )
    support_A = build_motion(inputs.get("support_A"), "inputs.support_A", issues)
    support_B = build_motion(inputs.get("support_B"), "inputs.support_B", issues)
    validate_motion_window(support_A, T, "inputs.support_A", issues)
    validate_motion_window(support_B, T, "inputs.support_B", issues)
    air = build_air(inputs.get("air_velocity"), "inputs.air_velocity", issues)
    distributed_specs = inputs.get("distributed_forces")
    if not isinstance(distributed_specs, dict) or set(distributed_specs) != set(BRANCHES):
        issues.append(ValidationIssue("BRANCH_SET", "inputs.distributed_forces", distributed_specs, str(BRANCHES)))
        distributed_specs = distributed_specs if isinstance(distributed_specs, dict) else {}
    distributed = {
        name: build_material_force(distributed_specs.get(name), f"inputs.distributed_forces.{name}", issues)
        for name in BRANCHES
    }
    junction_force = build_point_force(inputs.get("junction_force"), "inputs.junction_force", issues)
    bob_force = build_point_force(inputs.get("bob_force"), "inputs.bob_force", issues)
    for name in BRANCHES:
        validate_force_window(
            distributed[name],
            T,
            f"inputs.distributed_forces.{name}",
            issues,
        )
    validate_force_window(
        junction_force, T, "inputs.junction_force", issues
    )
    validate_force_window(bob_force, T, "inputs.bob_force", issues)
    guard_specs = inputs.get("exit_guards")
    if not isinstance(guard_specs, list):
        issues.append(ValidationIssue("TYPE", "inputs.exit_guards", guard_specs, "list (possibly empty)"))
        guard_specs = []
    guard_length_scale = max(branch.L0 for branch in branches.values())
    guards = [
        _build_guard(
            spec,
            f"inputs.exit_guards[{index}]",
            issues,
            guard_length_scale,
        )
        for index, spec in enumerate(guard_specs)
    ]
    names = [guard.name for guard in guards]
    if len(names) != len(set(names)):
        issues.append(ValidationIssue("GUARD_NAME", "inputs.exit_guards", names, "unique names"))

    initial = config.get("initial_state")
    if not isinstance(initial, dict):
        issues.append(ValidationIssue("TYPE", "initial_state", initial, "object"))
        initial = {}
    initial_mode = initial.get("mode")
    if initial_mode not in ("DIRECT_STATE", "STATIC_HOLD_RELEASE"):
        issues.append(ValidationIssue("INITIAL_MODE", "initial_state.mode", initial_mode, "DIRECT_STATE or STATIC_HOLD_RELEASE"))
        initial_mode = "DIRECT_STATE"
    reject_unknown_keys(
        initial,
        (
            {"mode", "r_J", "v_J", "r_m", "v_m", "branches"}
            if initial_mode == "DIRECT_STATE"
            else {"mode", "hold", "seed"}
        ),
        "initial_state",
        issues,
    )
    r_J0 = np.zeros(3)
    v_J0 = np.zeros(3)
    r_m0 = np.zeros(3)
    v_m0 = np.zeros(3)
    initial_branches: dict[str, InitialBranch] = {}
    hold_fixed_nodes: dict[str, np.ndarray] = {}
    if initial_mode == "DIRECT_STATE":
        r_J0 = as_vector3(initial.get("r_J"), "initial_state.r_J", issues)
        v_J0 = as_vector3(initial.get("v_J"), "initial_state.v_J", issues)
        r_m0 = as_vector3(initial.get("r_m"), "initial_state.r_m", issues)
        v_m0 = as_vector3(initial.get("v_m"), "initial_state.v_m", issues)
        initial_branch_specs = initial.get("branches")
        if not isinstance(initial_branch_specs, dict) or set(initial_branch_specs) != set(BRANCHES):
            issues.append(ValidationIssue("BRANCH_SET", "initial_state.branches", initial_branch_specs, str(BRANCHES)))
            initial_branch_specs = initial_branch_specs if isinstance(initial_branch_specs, dict) else {}
        for name in BRANCHES:
            spec = initial_branch_specs.get(name, {})
            if not isinstance(spec, dict):
                issues.append(ValidationIssue("TYPE", f"initial_state.branches.{name}", spec, "object"))
                spec = {}
            reject_unknown_keys(
                spec,
                {"position", "velocity"},
                f"initial_state.branches.{name}",
                issues,
            )
            initial_branches[name] = InitialBranch(
                build_polynomial_field(spec.get("position"), f"initial_state.branches.{name}.position", issues),
                build_polynomial_field(spec.get("velocity"), f"initial_state.branches.{name}.velocity", issues),
            )
    else:
        hold = initial.get("hold")
        if not isinstance(hold, dict):
            issues.append(ValidationIssue("STATIC_HOLD", "initial_state.hold", hold, "object"))
            hold = {}
        reject_unknown_keys(hold, {"fixed_nodes"}, "initial_state.hold", issues)
        fixed = hold.get("fixed_nodes")
        if not isinstance(fixed, dict) or not fixed:
            issues.append(ValidationIssue("STATIC_HOLD", "initial_state.hold.fixed_nodes", fixed, "nonempty object using junction and/or bob"))
            fixed = {}
        for node_name, value in fixed.items():
            if node_name not in ("junction", "bob"):
                issues.append(ValidationIssue("STATIC_HOLD", f"initial_state.hold.fixed_nodes.{node_name}", value, "junction or bob"))
                continue
            hold_fixed_nodes[node_name] = as_vector3(value, f"initial_state.hold.fixed_nodes.{node_name}", issues)
        # Seed coordinates are numerical initial guesses only.  They are not a
        # replacement for the hold constraints and do not enter the final state.
        seed = initial.get("seed", {})
        if not isinstance(seed, dict):
            issues.append(ValidationIssue("STATIC_SEED", "initial_state.seed", seed, "object"))
            seed = {}
        reject_unknown_keys(seed, {"r_J", "r_m"}, "initial_state.seed", issues)
        support_mid = 0.5 * (support_A.position(0) + support_B.position(0))
        default_J = support_mid + e_z * 0.7 * min(branches["A"].L0, branches["B"].L0)
        r_J0 = as_vector3(seed.get("r_J", hold_fixed_nodes.get("junction", default_J)), "initial_state.seed.r_J", issues)
        r_m0 = as_vector3(seed.get("r_m", hold_fixed_nodes.get("bob", r_J0 + e_z * branches["lower"].L0)), "initial_state.seed.r_m", issues)
        v_J0 = np.zeros(3)
        v_m0 = np.zeros(3)
        if support_A.description.get("kind") != "constant" or support_B.description.get("kind") != "constant":
            issues.append(ValidationIssue("STATIC_HOLD", "inputs.support_A/B", [support_A.description, support_B.description], "fixed constant supports"))
        if air.description.get("kind") != "zero":
            issues.append(ValidationIssue("STATIC_HOLD", "inputs.air_velocity", air.description, "zero"))
        force_descriptions = [distributed[name].description for name in BRANCHES] + [junction_force.description, bob_force.description]
        if any(description.get("kind") != "zero" for description in force_descriptions):
            issues.append(ValidationIssue("STATIC_HOLD", "inputs forces", force_descriptions, "all zero during static preparation"))

    validate_air_window(
        air,
        T,
        [
            support_A.position(0.0),
            support_B.position(0.0),
            r_J0,
            r_m0,
        ],
        "inputs.air_velocity",
        issues,
    )

    candidate = CablePhysicalInput(
        g, e_z, branches, junction_mass, bob_mass, rho_air, bob_volume,
        bob_c1, bob_c2, lambda_min, T, support_A, support_B, air, distributed,
        junction_force, bob_force, guards, initial_mode, initial_branches,
        hold_fixed_nodes, r_J0, v_J0, r_m0, v_m0,
    )
    if initial_mode == "DIRECT_STATE":
        _validate_initial_continuous(candidate, issues)
        _validate_initial_guards(candidate, issues)
    return issues, candidate if not issues else None


def _validate_initial_continuous(data: CablePhysicalInput, issues: list[ValidationIssue]) -> None:
    tolerance = 1e-9
    endpoints = {
        "A": (data.support_A.position(0), data.r_J0, data.support_A.velocity(0), data.v_J0),
        "B": (data.support_B.position(0), data.r_J0, data.support_B.velocity(0), data.v_J0),
        "lower": (data.r_J0, data.r_m0, data.v_J0, data.v_m0),
    }
    for name, (r0, r1, v0, v1) in endpoints.items():
        branch = data.initial_branches[name]
        actual = (branch.position.value(0.0), branch.position.value(1.0), branch.velocity.value(0.0), branch.velocity.value(1.0))
        expected = (r0, r1, v0, v1)
        labels = ("position_start", "position_end", "velocity_start", "velocity_end")
        for label, observed, target in zip(labels, actual, expected):
            if np.linalg.norm(observed - target) > tolerance:
                issues.append(ValidationIssue("INITIAL_COMPATIBILITY", f"initial_state.branches.{name}.{label}", observed, f"equal {target.tolist()} within {tolerance}"))
        xi = np.linspace(0.0, 1.0, 2049)
        r_xi = branch.position.derivative_xi(xi)
        v_xi = branch.velocity.derivative_xi(xi)
        norm = np.linalg.norm(r_xi, axis=1)
        stretch = norm / data.branches[name].L0
        rate = np.divide(np.sum(r_xi * v_xi, axis=1), norm * data.branches[name].L0, out=np.full_like(norm, np.nan), where=norm > 0)
        if not np.all(np.isfinite(stretch)) or np.min(stretch) <= data.lambda_min:
            issues.append(ValidationIssue("INITIAL_LAMBDA", f"initial_state.branches.{name}", float(np.nanmin(stretch)), f"> lambda_min={data.lambda_min}"))
        margin = data.branches[name].material_domain.margin(stretch, rate)
        if not margin > 0:
            issues.append(ValidationIssue("INITIAL_MATERIAL_DOMAIN", f"initial_state.branches.{name}", margin, "strictly inside open material domain on dense polynomial check"))


def _validate_initial_guards(
    data: CablePhysicalInput, issues: list[ValidationIssue]
) -> None:
    """Apply the frozen initial guard predicate before numerical projection."""

    positions = np.vstack(
        (
            data.support_A.position(0.0),
            data.support_B.position(0.0),
            data.r_J0,
            data.r_m0,
        )
    )
    node_index = {"support_A": 0, "support_B": 1, "junction": 2, "bob": 3}
    for guard in data.guards:
        value = guard.evaluate(positions, 0.0, node_index)
        if not np.isfinite(value) or not value > 0.0:
            issues.append(
                ValidationIssue(
                    "INITIAL_GUARD",
                    f"inputs.exit_guards.{guard.name}",
                    value,
                    "> 0 at the physical initial state",
                )
            )


def _validate_cable_numerics(numerics: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    reject_unknown_keys(
        numerics, CABLE_NUMERICAL_FIELDS, "numerics", issues
    )
    mesh = numerics.get("elements")
    if not isinstance(mesh, dict) or set(mesh) != set(BRANCHES):
        issues.append(
            ValidationIssue(
                "MESH", "numerics.elements", mesh, "object with exact keys A, B, lower"
            )
        )
    else:
        for name in BRANCHES:
            value = mesh[name]
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
                or value > MAX_ELEMENTS_PER_BRANCH
            ):
                issues.append(
                    ValidationIssue(
                        "MESH",
                        f"numerics.elements.{name}",
                        value,
                        f"integer in [1,{MAX_ELEMENTS_PER_BRANCH}]",
                    )
                )
        if all(
            isinstance(mesh.get(name), int)
            and not isinstance(mesh.get(name), bool)
            for name in BRANCHES
        ) and sum(int(mesh[name]) for name in BRANCHES) > MAX_TOTAL_CABLE_ELEMENTS:
            issues.append(
                ValidationIssue(
                    "MESH",
                    "numerics.elements",
                    mesh,
                    f"total elements <= {MAX_TOTAL_CABLE_ELEMENTS}",
                )
            )
    quadrature = numerics.get("quadrature_order", 3)
    if (
        not isinstance(quadrature, int)
        or isinstance(quadrature, bool)
        or not 1 <= quadrature <= 8
    ):
        issues.append(
            ValidationIssue(
                "QUADRATURE", "numerics.quadrature_order", quadrature, "integer 1..8"
            )
        )
    method = numerics.get("method", "Radau")
    if method not in ("Radau", "BDF", "DOP853"):
        issues.append(
            ValidationIssue(
                "INTEGRATOR", "numerics.method", method, "Radau, BDF, or DOP853"
            )
        )
    positive_fields = {
        "rtol": 1e-7,
        "atol": 1e-9,
        "atol_position": numerics.get("atol", 1e-9),
        "atol_velocity": numerics.get("atol", 1e-9),
        "max_step": None,
        "output_dt": None,
        "event_cluster_tolerance": 1e-8,
    }
    for field, default in positive_fields.items():
        value = numerics.get(field, default)
        # max_step/output_dt defaults depend on T and are supplied later.
        if value is None:
            continue
        if not is_finite_number(value) or float(value) <= 0.0:
            issues.append(
                ValidationIssue(
                    "NUMERICAL_CONFIG",
                    f"numerics.{field}",
                    value,
                    "positive finite real",
                )
            )
    rtol = numerics.get("rtol", 1e-7)
    if is_finite_number(rtol) and 0.0 < float(rtol) < MIN_SOLVER_RTOL:
        issues.append(
            ValidationIssue(
                "NUMERICAL_CONFIG",
                "numerics.rtol",
                rtol,
                f">= SciPy machine floor {MIN_SOLVER_RTOL:.17g}",
            )
        )
    for field, lower, upper in (
        ("static_multistart", 3, MAX_STATIC_MULTISTART),
        ("static_maxiter", 100, MAX_STATIC_ITERATIONS),
    ):
        if field in numerics:
            value = numerics[field]
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < lower
                or value > upper
            ):
                issues.append(
                    ValidationIssue(
                        "NUMERICAL_CONFIG",
                        f"numerics.{field}",
                        value,
                        f"integer in [{lower},{upper}]",
                    )
                )
    for field in (
        "static_gradient_tolerance",
        "static_energy_tolerance",
        "static_uniqueness_tolerance",
    ):
        if field in numerics:
            value = numerics[field]
            if not is_finite_number(value) or float(value) <= 0.0:
                issues.append(
                    ValidationIssue(
                        "NUMERICAL_CONFIG",
                        f"numerics.{field}",
                        value,
                        "positive finite real",
                    )
                )
    return issues


class CableFEM:
    """Assemble and evaluate the P1 semidiscrete weak-form system."""

    def __init__(self, physical: CablePhysicalInput, numerics: dict[str, Any]):
        self.p = physical
        self.numerics = numerics
        self.numerical_issues: list[ValidationIssue] = []
        mesh = numerics.get("elements")
        if not isinstance(mesh, dict) or set(mesh) != set(BRANCHES):
            self.numerical_issues.append(ValidationIssue("MESH", "numerics.elements", mesh, str(BRANCHES)))
            mesh = {}
        self.element_count: dict[str, int] = {}
        for name in BRANCHES:
            value = mesh.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                self.numerical_issues.append(ValidationIssue("MESH", f"numerics.elements.{name}", value, "integer >= 1"))
                value = 1
            self.element_count[name] = value
        quadrature_order = numerics.get("quadrature_order", 3)
        if not isinstance(quadrature_order, int) or isinstance(quadrature_order, bool) or not 1 <= quadrature_order <= 8:
            self.numerical_issues.append(ValidationIssue("QUADRATURE", "numerics.quadrature_order", quadrature_order, "integer 1..8"))
            quadrature_order = 3
        self.quadrature_order = quadrature_order
        points, weights = np.polynomial.legendre.leggauss(quadrature_order)
        self.gauss_xi = 0.5 * (points + 1.0)
        self.gauss_weights = 0.5 * weights
        self._build_topology()
        self._assemble_mass()
        self._initialize_state()

    def _build_topology(self):
        self.node_ids = ["support_A", "support_B", "junction", "bob"]
        self.node_index = {name: index for index, name in enumerate(self.node_ids)}
        self.branch_nodes: dict[str, np.ndarray] = {}
        for name in BRANCHES:
            count = self.element_count[name]
            if name == "A":
                start, end = self.node_index["support_A"], self.node_index["junction"]
            elif name == "B":
                start, end = self.node_index["support_B"], self.node_index["junction"]
            else:
                start, end = self.node_index["junction"], self.node_index["bob"]
            internal = []
            for local in range(1, count):
                label = f"{name}:node:{local}"
                self.node_index[label] = len(self.node_ids)
                self.node_ids.append(label)
                internal.append(self.node_index[label])
            self.branch_nodes[name] = np.asarray([start, *internal, end], dtype=int)
        self.prescribed = np.array([self.node_index["support_A"], self.node_index["support_B"]], dtype=int)
        self.free = np.array([index for index in range(len(self.node_ids)) if index not in set(self.prescribed)], dtype=int)
        self.free_lookup = {global_index: local for local, global_index in enumerate(self.free)}

    def _assemble_mass(self):
        node_count = len(self.node_ids)
        self.mass = np.zeros((node_count, node_count))
        self.gravity_weights = np.zeros(node_count)
        for name in BRANCHES:
            branch = self.p.branches[name]
            h = branch.L0 / self.element_count[name]
            local_mass = branch.mu * h / 6.0 * np.array([[2.0, 1.0], [1.0, 2.0]])
            for left, right in zip(self.branch_nodes[name][:-1], self.branch_nodes[name][1:]):
                indices = np.array([left, right])
                self.mass[np.ix_(indices, indices)] += local_mass
                self.gravity_weights[indices] += branch.mu * h / 2.0
        junction = self.node_index["junction"]
        bob = self.node_index["bob"]
        self.mass[junction, junction] += self.p.junction_mass
        self.mass[bob, bob] += self.p.bob_mass
        self.gravity_weights[junction] += self.p.junction_mass
        self.gravity_weights[bob] += self.p.bob_mass
        self.M_ff = self.mass[np.ix_(self.free, self.free)]
        self.M_fp = self.mass[np.ix_(self.free, self.prescribed)]
        symmetry = np.linalg.norm(self.M_ff - self.M_ff.T, ord=np.inf)
        try:
            self.mass_factor = cho_factor(self.M_ff, lower=True, check_finite=True)
            minimum_eigenvalue = float(np.linalg.eigvalsh(self.M_ff)[0])
        except Exception as exc:
            self.numerical_issues.append(ValidationIssue("MASS_MATRIX", "assembled.M_ff", repr(exc), "symmetric positive definite"))
            self.mass_factor = None
            minimum_eigenvalue = float("nan")
        self.mass_diagnostics = {
            "symmetry_inf_norm": float(symmetry),
            "minimum_eigenvalue": minimum_eigenvalue,
            "condition_number": float(np.linalg.cond(self.M_ff)) if self.M_ff.size else float("nan"),
        }

    def _initialize_state(self):
        self.preparation_diagnostics: dict[str, Any] = {"mode": self.p.initial_mode}
        if self.p.initial_mode == "STATIC_HOLD_RELEASE":
            self._prepare_static_hold_release()
            return
        positions = np.full((len(self.node_ids), 3), np.nan)
        velocities = np.full((len(self.node_ids), 3), np.nan)
        for name in BRANCHES:
            nodes = self.branch_nodes[name]
            xi = np.linspace(0.0, 1.0, nodes.size)
            r_values = self.p.initial_branches[name].position.value(xi)
            v_values = self.p.initial_branches[name].velocity.value(xi)
            for node, r_value, v_value in zip(nodes, r_values, v_values):
                if np.all(np.isfinite(positions[node])):
                    if np.linalg.norm(positions[node] - r_value) > 1e-9 or np.linalg.norm(velocities[node] - v_value) > 1e-9:
                        self.numerical_issues.append(ValidationIssue("INITIAL_PROJECTION", f"node.{self.node_ids[node]}", [positions[node], r_value], "shared values identical"))
                positions[node] = r_value
                velocities[node] = v_value
        if not np.all(np.isfinite(positions)) or not np.all(np.isfinite(velocities)):
            self.numerical_issues.append(ValidationIssue("INITIAL_PROJECTION", "initial_state", None, "all global nodes assigned finite state"))
        positions[self.node_index["junction"]] = self.p.r_J0
        velocities[self.node_index["junction"]] = self.p.v_J0
        positions[self.node_index["bob"]] = self.p.r_m0
        velocities[self.node_index["bob"]] = self.p.v_m0
        positions[self.node_index["support_A"]] = self.p.support_A.position(0)
        velocities[self.node_index["support_A"]] = self.p.support_A.velocity(0)
        positions[self.node_index["support_B"]] = self.p.support_B.position(0)
        velocities[self.node_index["support_B"]] = self.p.support_B.velocity(0)
        self._finalize_initial_state(positions, velocities)

    def _finalize_initial_state(self, positions: np.ndarray, velocities: np.ndarray):
        self.initial_positions = positions
        self.initial_velocities = velocities
        stretch, rate, _tangent = self.element_kinematics(positions, velocities)
        minimum = min(float(np.min(stretch[name])) for name in BRANCHES)
        if not minimum > self.p.lambda_min:
            self.numerical_issues.append(ValidationIssue("INITIAL_PROJECTION", "projected.lambda", minimum, f"> {self.p.lambda_min}"))
        for name in BRANCHES:
            margin = self.p.branches[name].material_domain.margin(stretch[name], rate[name])
            if not margin > 0:
                self.numerical_issues.append(ValidationIssue("INITIAL_PROJECTION", f"projected.material_domain.{name}", margin, "> 0"))
        for guard in self.p.guards:
            value = guard.evaluate(positions, 0.0, self.node_index)
            if not value > 0:
                self.numerical_issues.append(ValidationIssue("INITIAL_GUARD", f"inputs.exit_guards.{guard.name}", value, "> 0"))
        self.y0 = np.concatenate((positions[self.free].ravel(), velocities[self.free].ravel()))

    def _prepare_static_hold_release(self):
        positions = np.empty((len(self.node_ids), 3))
        positions[self.node_index["support_A"]] = self.p.support_A.position(0.0)
        positions[self.node_index["support_B"]] = self.p.support_B.position(0.0)
        positions[self.node_index["junction"]] = self.p.hold_fixed_nodes.get("junction", self.p.r_J0)
        positions[self.node_index["bob"]] = self.p.hold_fixed_nodes.get("bob", self.p.r_m0)
        for name in BRANCHES:
            nodes = self.branch_nodes[name]
            xi = np.linspace(0.0, 1.0, nodes.size)
            positions[nodes] = ((1.0 - xi[:, None]) * positions[nodes[0]] + xi[:, None] * positions[nodes[-1]])
        fixed_global = set(self.prescribed.tolist())
        for node_name, value in self.p.hold_fixed_nodes.items():
            index = self.node_index[node_name]
            fixed_global.add(index)
            positions[index] = value
        optimization_nodes = np.asarray([index for index in range(len(self.node_ids)) if index not in fixed_global], dtype=int)
        multistart = self.numerics.get("static_multistart", 5)
        maxiter = self.numerics.get("static_maxiter", 3000)
        gradient_tolerance = self.numerics.get("static_gradient_tolerance", 1e-8)
        if not isinstance(multistart, int) or isinstance(multistart, bool) or multistart < 3:
            self.numerical_issues.append(ValidationIssue("STATIC_PREPARATION", "numerics.static_multistart", multistart, "integer >= 3"))
            multistart = 3
        if not isinstance(maxiter, int) or isinstance(maxiter, bool) or maxiter < 100:
            self.numerical_issues.append(ValidationIssue("STATIC_PREPARATION", "numerics.static_maxiter", maxiter, "integer >= 100"))
            maxiter = 100
        if not is_finite_number(gradient_tolerance) or float(gradient_tolerance) <= 0:
            self.numerical_issues.append(ValidationIssue("STATIC_PREPARATION", "numerics.static_gradient_tolerance", gradient_tolerance, "positive finite"))
            gradient_tolerance = 1e-8
        rng = np.random.default_rng(20270821)
        amplitude = 0.08 * min(branch.L0 for branch in self.p.branches.values())
        seeds = [positions.copy()]
        for _index in range(multistart - 1):
            seed = positions.copy()
            seed[optimization_nodes] += amplitude * rng.normal(size=(optimization_nodes.size, 3))
            seeds.append(seed)
        candidates = []

        def objective(flat):
            candidate = positions.copy()
            candidate[optimization_nodes] = np.asarray(flat).reshape((-1, 3))
            try:
                energy, gradient = self._static_potential_gradient(candidate)
            except (FloatingPointError, ValueError):
                return 1e100, np.zeros_like(flat)
            return energy, gradient[optimization_nodes].ravel()

        for seed in seeds:
            if optimization_nodes.size:
                result = minimize(objective, seed[optimization_nodes].ravel(), method="L-BFGS-B", jac=True, options={"maxiter": maxiter, "gtol": float(gradient_tolerance), "ftol": 1e-14, "maxls": 50})
                candidate = positions.copy()
                candidate[optimization_nodes] = result.x.reshape((-1, 3))
                _energy, gradient = self._static_potential_gradient(candidate)
                gradient_norm = float(np.linalg.norm(gradient[optimization_nodes].ravel(), ord=np.inf))
                candidates.append(
                    (
                        float(result.fun),
                        candidate,
                        gradient_norm,
                        int(result.nit),
                        bool(
                            np.isfinite(gradient_norm)
                            and gradient_norm <= float(gradient_tolerance)
                        ),
                    )
                )
            else:
                candidates.append((self._static_potential_gradient(seed)[0], seed, 0.0, 0, True))
        accepted = [candidate for candidate in candidates if candidate[4] and np.isfinite(candidate[0])]
        static_energy_scale: float | None = None
        if not accepted:
            self.numerical_issues.append(ValidationIssue("STATIC_PREPARATION_FAILED", "initial_state.hold", [{"energy": item[0], "gradient_inf": item[2], "iterations": item[3]} for item in candidates], "at least one converged discrete minimizer"))
            selected = min(candidates, key=lambda item: item[0])
        else:
            selected = min(accepted, key=lambda item: item[0])
            static_energy_scale = max(
                abs(float(selected[0])),
                float(np.sum(self.gravity_weights))
                * self.p.g
                * sum(branch.L0 for branch in self.p.branches.values()),
                np.finfo(float).tiny,
            )
            energy_tolerance = float(
                self.numerics.get(
                    "static_energy_tolerance",
                    1e-9 * static_energy_scale,
                )
            )
            uniqueness_tolerance = float(self.numerics.get("static_uniqueness_tolerance", 1e-5))
            near = [item for item in accepted if item[0] <= selected[0] + energy_tolerance]
            separation = max((float(np.max(np.linalg.norm(item[1] - selected[1], axis=1))) for item in near), default=0.0)
            if separation > uniqueness_tolerance:
                self.numerical_issues.append(ValidationIssue("PREPARATION_NONUNIQUE", "initial_state.hold", separation, f"equal-energy multistart candidates within {uniqueness_tolerance} m"))
        self.preparation_diagnostics = {
            "mode": "STATIC_HOLD_RELEASE",
            "candidate_count": len(candidates),
            "accepted_candidate_count": len(accepted),
            "selected_energy": float(selected[0]),
            "static_energy_scale": static_energy_scale,
            "selected_gradient_inf": float(selected[2]),
            "required_gradient_inf": float(gradient_tolerance),
            "selected_iterations": int(selected[3]),
            "uniqueness_scope": "deterministic multistart discrete check; not a global mathematical proof",
        }
        self.initial_positions = selected[1]
        self.initial_velocities = np.zeros_like(self.initial_positions)
        blocking = {"STATIC_PREPARATION_FAILED", "PREPARATION_NONUNIQUE"}
        if not any(issue.code in blocking for issue in self.numerical_issues):
            self._finalize_initial_state(self.initial_positions, self.initial_velocities)
        else:
            self.y0 = np.concatenate((self.initial_positions[self.free].ravel(), self.initial_velocities[self.free].ravel()))

    def _static_potential_gradient(self, positions: np.ndarray):
        velocities = np.zeros_like(positions)
        applied, internal, details = self.assemble(0.0, positions, velocities, diagnostics=True)
        potential = (
            -self.p.g * float(np.sum(self.gravity_weights * (positions @ self.p.e_z)))
            + self.p.rho_air * self.p.bob_volume * self.p.g * float(self.p.e_z @ positions[self.node_index["bob"]])
            + details["V_ax"]
        )
        return float(potential), internal - applied

    @property
    def free_vector_size(self) -> int:
        return 3 * self.free.size

    def full_state(self, t: float, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        n = self.free_vector_size
        positions = np.empty((len(self.node_ids), 3))
        velocities = np.empty_like(positions)
        positions[self.free] = np.asarray(y[:n]).reshape((-1, 3))
        velocities[self.free] = np.asarray(y[n:]).reshape((-1, 3))
        positions[self.node_index["support_A"]] = self.p.support_A.position(t)
        velocities[self.node_index["support_A"]] = self.p.support_A.velocity(t)
        positions[self.node_index["support_B"]] = self.p.support_B.position(t)
        velocities[self.node_index["support_B"]] = self.p.support_B.velocity(t)
        return positions, velocities

    def support_acceleration(self, t: float) -> np.ndarray:
        return np.vstack((self.p.support_A.acceleration(t), self.p.support_B.acceleration(t)))

    def element_kinematics(self, positions, velocities):
        stretches: dict[str, np.ndarray] = {}
        rates: dict[str, np.ndarray] = {}
        tangents: dict[str, np.ndarray] = {}
        for name in BRANCHES:
            nodes = self.branch_nodes[name]
            delta_r = positions[nodes[1:]] - positions[nodes[:-1]]
            delta_v = velocities[nodes[1:]] - velocities[nodes[:-1]]
            h = self.p.branches[name].L0 / self.element_count[name]
            lengths = np.linalg.norm(delta_r, axis=1)
            if np.any(lengths <= 100 * np.finfo(float).tiny):
                raise FloatingPointError(f"zero material tangent in branch {name}")
            tangent = delta_r / lengths[:, None]
            stretches[name] = lengths / h
            rates[name] = np.sum(tangent * delta_v, axis=1) / h
            tangents[name] = tangent
        return stretches, rates, tangents

    def assemble(self, t: float, positions: np.ndarray, velocities: np.ndarray, *, diagnostics: bool = False):
        """Return applied load, internal residual, and optional field details."""

        node_count = len(self.node_ids)
        applied = self.gravity_weights[:, None] * self.p.g * self.p.e_z
        # Bob buoyancy is the only buoyancy retained by FWD-CABLE-1.0.
        applied[self.node_index["bob"]] -= (
            self.p.rho_air * self.p.bob_volume * self.p.g * self.p.e_z
        )
        internal = np.zeros((node_count, 3))
        stretches, rates, tangents = self.element_kinematics(positions, velocities)
        details: dict[str, Any] = {"branches": {}}
        total_D_ax = 0.0
        total_D_string = 0.0
        total_P_air_string = 0.0
        total_P_ext_string = 0.0
        total_V_ax = 0.0

        for name in BRANCHES:
            branch = self.p.branches[name]
            nodes = self.branch_nodes[name]
            element_count = self.element_count[name]
            h = branch.L0 / element_count
            stretch = stretches[name]
            rate = rates[name]
            tangent = tangents[name]
            N_elastic, N_viscous, tension = tension_components(
                stretch,
                rate,
                EA=branch.EA,
                Ca=branch.Ca,
                delta=branch.delta,
            )
            f_drag_center = np.zeros((element_count, 3))
            for element, (left, right) in enumerate(zip(nodes[:-1], nodes[1:])):
                force = tension[element] * tangent[element]
                internal[left] -= force
                internal[right] += force
                xi_global_left = element / element_count
                for xi_local, weight in zip(self.gauss_xi, self.gauss_weights):
                    shape = np.array([1.0 - xi_local, xi_local])
                    r_q = shape[0] * positions[left] + shape[1] * positions[right]
                    v_q = shape[0] * velocities[left] + shape[1] * velocities[right]
                    air_q = self.p.air.value(r_q, t)
                    u = v_q - air_q
                    u_parallel = tangent[element] * float(tangent[element] @ u)
                    u_perp = u - u_parallel
                    drag = (
                        -branch.c_parallel * u_parallel
                        -branch.c_perp * u_perp
                        -branch.d_parallel * np.linalg.norm(u_parallel) * u_parallel
                        -branch.d_perp * np.linalg.norm(u_perp) * u_perp
                    )
                    xi_global = xi_global_left + xi_local / element_count
                    external = self.p.distributed_forces[name].value(xi_global, t)
                    nodal = h * weight * shape
                    applied[left] += nodal[0] * (drag + external)
                    applied[right] += nodal[1] * (drag + external)
                    if diagnostics:
                        total_D_string += h * weight * (-float(drag @ u))
                        total_P_air_string += h * weight * float(drag @ air_q)
                        total_P_ext_string += h * weight * float(external @ v_q)
                if diagnostics:
                    r_center = 0.5 * (positions[left] + positions[right])
                    v_center = 0.5 * (velocities[left] + velocities[right])
                    air_center = self.p.air.value(r_center, t)
                    u_center = v_center - air_center
                    u_parallel_center = tangent[element] * float(
                        tangent[element] @ u_center
                    )
                    u_perp_center = u_center - u_parallel_center
                    f_drag_center[element] = (
                        -branch.c_parallel * u_parallel_center
                        -branch.c_perp * u_perp_center
                        -branch.d_parallel
                        * np.linalg.norm(u_parallel_center)
                        * u_parallel_center
                        -branch.d_perp
                        * np.linalg.norm(u_perp_center)
                        * u_perp_center
                    )
            if diagnostics:
                total_D_ax += float(np.sum(h * (tension - N_elastic) * rate))
                total_V_ax += float(
                    np.sum(branch.EA * h * activation_primitive(stretch - 1.0, branch.delta))
                )
                details["branches"][name] = {
                    "lambda": stretch,
                    "lambda_dot": rate,
                    "tangent": tangent,
                    "N_elastic": N_elastic,
                    "N_viscous": N_viscous,
                    "N": tension,
                    "active": tension > 0.0,
                    "slack": tension == 0.0,
                    "loaded_length": float(np.sum(h * stretch)),
                    "f_drag_center": f_drag_center,
                }

        junction = self.node_index["junction"]
        bob = self.node_index["bob"]
        F_ext_J = self.p.junction_force.value(t)
        F_ext_b = self.p.bob_force.value(t)
        applied[junction] += F_ext_J
        applied[bob] += F_ext_b
        air_b = self.p.air.value(positions[bob], t)
        u_b = velocities[bob] - air_b
        F_drag_b = -self.p.bob_c1 * u_b - self.p.bob_c2 * np.linalg.norm(u_b) * u_b
        applied[bob] += F_drag_b

        if diagnostics:
            details.update(
                F_drag_b=F_drag_b,
                D_ax=float(total_D_ax),
                D_string=float(total_D_string),
                D_b=float(-F_drag_b @ u_b),
                P_air=float(total_P_air_string + F_drag_b @ air_b),
                P_ext=float(
                    total_P_ext_string
                    + F_ext_J @ velocities[junction]
                    + F_ext_b @ velocities[bob]
                ),
                V_ax=float(total_V_ax),
            )
        return applied, internal, details

    def acceleration(self, t: float, positions: np.ndarray, velocities: np.ndarray, *, diagnostics: bool = False):
        applied, internal, details = self.assemble(t, positions, velocities, diagnostics=diagnostics)
        prescribed_acceleration = self.support_acceleration(t)
        free_rhs = applied[self.free] - internal[self.free] - self.M_fp @ prescribed_acceleration
        free_acceleration = np.column_stack(
            [cho_solve(self.mass_factor, free_rhs[:, coordinate]) for coordinate in range(3)]
        )
        acceleration = np.empty_like(positions)
        acceleration[self.free] = free_acceleration
        acceleration[self.prescribed] = prescribed_acceleration
        if diagnostics:
            algebraic_reaction = (
                self.mass @ acceleration + internal - applied
            )[self.prescribed]
            details["algebraic_reaction"] = algebraic_reaction
        return acceleration, details

    def rhs(self, t: float, y: np.ndarray) -> np.ndarray:
        positions, velocities = self.full_state(t, y)
        acceleration, _details = self.acceleration(t, positions, velocities)
        return np.concatenate((velocities[self.free].ravel(), acceleration[self.free].ravel()))

    def physical_guard_components(self, t: float, y: np.ndarray) -> dict[str, Any]:
        positions, velocities = self.full_state(t, y)
        stretches, rates, _tangents = self.element_kinematics(positions, velocities)
        lambda_components: dict[str, np.ndarray] = {
            name: stretches[name] - self.p.lambda_min for name in BRANCHES
        }
        material_components: dict[str, dict[str, np.ndarray]] = {
            name: self.p.branches[name].material_domain.component_margins(
                stretches[name], rates[name]
            )
            for name in BRANCHES
        }
        custom = {
            guard.name: guard.evaluate(positions, t, self.node_index) for guard in self.p.guards
        }
        return {
            "lambda": lambda_components,
            "material": material_components,
            "custom": custom,
        }

    def guard_component_scales(self) -> dict[str, Any]:
        """Frozen per-component physical scales for event normalization."""

        characteristic_rate = np.sqrt(
            self.p.g
            / min(branch.L0 for branch in self.p.branches.values())
        )
        lambda_scales: dict[str, float] = {}
        material_scales: dict[str, dict[str, float]] = {}
        for name, branch in self.p.branches.items():
            domain = branch.material_domain
            finite_lambda = [
                value
                for value in (domain.lambda_lower, domain.lambda_upper)
                if np.isfinite(value)
            ]
            if len(finite_lambda) == 2:
                finite_lambda.append(abs(finite_lambda[1] - finite_lambda[0]))
            lambda_scale = max(
                1.0,
                self.p.lambda_min,
                *(abs(value) for value in finite_lambda),
            )
            finite_rate = [
                value
                for value in (domain.rate_lower, domain.rate_upper)
                if np.isfinite(value)
            ]
            if len(finite_rate) == 2:
                finite_rate.append(abs(finite_rate[1] - finite_rate[0]))
            rate_scale = max(
                [
                    characteristic_rate,
                    *(abs(value) for value in finite_rate),
                ]
            )
            lambda_scales[name] = max(1.0, self.p.lambda_min)
            material_scales[name] = {
                "lambda_lower": lambda_scale,
                "lambda_upper": lambda_scale,
                "rate_lower": rate_scale,
                "rate_upper": rate_scale,
            }
        return {
            "lambda": lambda_scales,
            "material": material_scales,
            "custom": {
                guard.name: guard.length_scale for guard in self.p.guards
            },
        }

    def event_functions(self):
        events = []
        names = []
        scales = self.guard_component_scales()

        def lambda_event(t, y):
            components = self.physical_guard_components(t, y)["lambda"]
            return min(
                float(np.min(value)) / scales["lambda"][name]
                for name, value in components.items()
            )

        lambda_event.terminal = True
        lambda_event.direction = 0
        events.append(lambda_event)
        names.append("LAMBDA_MIN")

        def material_event(t, y):
            components = self.physical_guard_components(t, y)["material"]
            return min(
                float(np.min(value)) / scales["material"][branch][boundary]
                for branch, branch_values in components.items()
                for boundary, value in branch_values.items()
            )

        material_event.terminal = True
        material_event.direction = 0
        events.append(material_event)
        names.append("MATERIAL_DOMAIN")

        for guard in self.p.guards:
            def event(t, y, guard=guard):
                positions, _velocities = self.full_state(t, y)
                return guard.evaluate(positions, t, self.node_index)

            event.terminal = True
            event.direction = 0
            events.append(event)
            names.append(f"EXIT_GUARD:{guard.name}")
        return names, events

    def diagnostic_snapshot(self, t: float, y: np.ndarray) -> dict[str, Any]:
        positions, velocities = self.full_state(t, y)
        acceleration, details = self.acceleration(t, positions, velocities, diagnostics=True)
        kinetic = 0.5 * sum(
            velocities[:, coordinate] @ self.mass @ velocities[:, coordinate]
            for coordinate in range(3)
        )
        V_g = -self.p.g * float(
            np.sum(self.gravity_weights * (positions @ self.p.e_z))
        )
        V_buoy = (
            self.p.rho_air
            * self.p.bob_volume
            * self.p.g
            * float(self.p.e_z @ positions[self.node_index["bob"]])
        )
        theory_reaction_A = -details["branches"]["A"]["N"][0] * details["branches"]["A"]["tangent"][0]
        theory_reaction_B = -details["branches"]["B"]["N"][0] * details["branches"]["B"]["tangent"][0]
        support_velocity = velocities[self.prescribed]
        P_base = float(theory_reaction_A @ support_velocity[0] + theory_reaction_B @ support_velocity[1])
        P_base_algebraic = float(np.sum(details["algebraic_reaction"] * support_velocity))
        details.update(
            positions=positions,
            velocities=velocities,
            acceleration=acceleration,
            T_kin=float(kinetic),
            V_g=float(V_g),
            V_buoy=float(V_buoy),
            E_F=float(kinetic + V_g + V_buoy + details["V_ax"]),
            R_A=theory_reaction_A,
            R_B=theory_reaction_B,
            P_base=P_base,
            P_base_algebraic=P_base_algebraic,
        )
        return details


def run_cable(
    config: dict[str, Any], *, identity: dict[str, Any]
) -> SimulationResult:
    physical_issues, physical = parse_cable_physical(config)
    if physical_issues or physical is None:
        return SimulationResult(
            model_id="FWD-CABLE-1.0",
            contract_status=["INVALID_INPUT"],
            numerical_status="INPUT_REJECTED",
            tau=0.0,
            returned_interval="empty",
            time=np.empty(0),
            events=[{"kind": "input", "failures": [issue.as_dict() for issue in physical_issues]}],
            metadata=identity,
        )
    numerics = config.get("numerics")
    if not isinstance(numerics, dict):
        return _invalid_numerics(config, "numerics", numerics, "object", identity)
    numerical_schema_issues = _validate_cable_numerics(numerics)
    if numerical_schema_issues:
        return _invalid_numerical_issues(config, numerical_schema_issues, identity)
    model = CableFEM(physical, numerics)
    if model.numerical_issues:
        issue_codes = {issue.code for issue in model.numerical_issues}
        if "INITIAL_GUARD" in issue_codes:
            return SimulationResult(
                model_id="FWD-CABLE-1.0",
                contract_status=["INVALID_INPUT"],
                numerical_status="INPUT_REJECTED",
                tau=0.0,
                returned_interval="empty",
                time=np.empty(0),
                events=[
                    {
                        "kind": "input",
                        "failures": [
                            issue.as_dict() for issue in model.numerical_issues
                        ],
                    }
                ],
                diagnostics={
                    "mass_matrix": model.mass_diagnostics,
                    "preparation": model.preparation_diagnostics,
                },
                metadata=identity,
            )
        if "PREPARATION_NONUNIQUE" in issue_codes:
            setup_status = "PREPARATION_NONUNIQUE"
        elif "STATIC_PREPARATION_FAILED" in issue_codes:
            setup_status = "NUMERICAL_SETUP_UNRESOLVED"
        else:
            setup_status = "INVALID_NUMERICAL_CONFIG"
        return SimulationResult(
            model_id="FWD-CABLE-1.0",
            contract_status=[],
            numerical_status=setup_status,
            tau=0.0,
            returned_interval="empty",
            time=np.empty(0),
            events=[{"kind": "numerical_input", "failures": [issue.as_dict() for issue in model.numerical_issues]}],
            diagnostics={
                "mass_matrix": model.mass_diagnostics,
                "preparation": model.preparation_diagnostics,
            },
            metadata=identity,
        )
    method = str(numerics.get("method", "Radau"))
    if method not in ("Radau", "BDF", "DOP853"):
        return _invalid_numerics(
            config,
            "numerics.method",
            method,
            "Radau, BDF, or DOP853",
            identity,
        )
    numeric_values = {
        "rtol": numerics.get("rtol", 1e-7),
        "atol": numerics.get("atol", 1e-9),
        "atol_position": numerics.get("atol_position", numerics.get("atol", 1e-9)),
        "atol_velocity": numerics.get("atol_velocity", numerics.get("atol", 1e-9)),
        "max_step": numerics.get("max_step", physical.T / 200),
        "output_dt": numerics.get("output_dt", physical.T / 500),
        "event_cluster_tolerance": numerics.get("event_cluster_tolerance", 1e-8),
    }
    bad = [key for key, value in numeric_values.items() if not is_finite_number(value) or float(value) <= 0]
    if bad:
        return _invalid_numerics(
            config,
            "numerics",
            {key: numeric_values[key] for key in bad},
            "positive finite values",
            identity,
        )
    numeric_values = {key: float(value) for key, value in numeric_values.items()}
    resource_issues = numerical_time_resource_issues(
        physical.T,
        numeric_values["max_step"],
        numeric_values["output_dt"],
    )
    if resource_issues:
        return _invalid_numerical_issues(config, resource_issues, identity)
    atol_vector = np.concatenate(
        (
            np.full(model.free_vector_size, numeric_values["atol_position"]),
            np.full(model.free_vector_size, numeric_values["atol_velocity"]),
        )
    )
    event_names, event_functions = model.event_functions()
    try:
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always")
            sol = solve_ivp(
                model.rhs,
                (0.0, physical.T),
                model.y0,
                method=method,
                rtol=numeric_values["rtol"],
                atol=atol_vector,
                max_step=numeric_values["max_step"],
                dense_output=True,
                events=event_functions,
            )
    except Exception as exc:
        return SimulationResult(
            model_id="FWD-CABLE-1.0",
            contract_status=[],
            numerical_status="SOLVER_FAILURE",
            tau=0.0,
            returned_interval="unresolved",
            time=np.empty(0),
            events=[{"kind": "numerical_failure", "message": repr(exc)}],
            diagnostics={"mass_matrix": model.mass_diagnostics},
            metadata=identity,
        )
    solver_warnings = [
        {"category": item.category.__name__, "message": str(item.message)}
        for item in caught_warnings
    ]
    event_times = [float(values[0]) for values in sol.t_events if len(values)]
    event_tau = min(event_times) if event_times else np.inf
    cluster_tolerance = numeric_values["event_cluster_tolerance"]
    if solver_warnings:
        tau = float(sol.t[-1]) if sol.t.size else 0.0
        completed = False
        contract_status = []
        numerical_status = "SOLVER_WARNING"
        returned_interval = f"[0,{tau}] candidate only; warning made status unresolved"
        events = [{"kind": "numerical_warning", "warnings": solver_warnings}]
    elif not sol.success:
        tau = float(sol.t[-1]) if sol.t.size else 0.0
        completed = False
        contract_status: list[str] = []
        numerical_status = "SOLVER_FAILURE"
        returned_interval = f"[0,{tau}] last accepted; physical status unresolved"
        events = [{"kind": "numerical_failure", "message": sol.message}]
    elif np.isfinite(event_tau) and event_tau <= physical.T + cluster_tolerance:
        tau = min(event_tau, physical.T)
        completed = False
        contract_status = ["OUT_OF_SCOPE"]
        numerical_status = "SUCCESS_EVENT"
        returned_interval = f"[0,{tau})"
        y_event = np.asarray(sol.sol(tau), dtype=float)
        components = model.physical_guard_components(tau, y_event)
        rooted_names = [
            name
            for name, values in zip(event_names, sol.t_events)
            if len(values) and abs(float(values[0]) - event_tau) <= cluster_tolerance
        ]
        guard_component_scales = model.guard_component_scales()
        triggers = _collect_rooted_guard_triggers(
            components, rooted_names, guard_component_scales
        )
        event_snapshot = model.diagnostic_snapshot(tau, y_event)
        events = [{
            "kind": "physical_exit",
            "time": tau,
            "triggers": triggers,
            "state_left": {
                "positions": event_snapshot["positions"],
                "velocities": event_snapshot["velocities"],
            },
            "derived_left": _physical_derived_snapshot(event_snapshot),
            "guard_components": components,
            "guard_zero_tolerances": {
                trigger: (
                    1024.0
                    * np.finfo(float).eps
                    * _guard_scale_for_trigger(
                        trigger, guard_component_scales
                    )
                )
                for trigger in triggers
            },
        }]
    else:
        tau = physical.T
        completed = True
        contract_status = ["COMPLETED"]
        numerical_status = "SUCCESS_SINGLE_RUN"
        returned_interval = f"[0,{physical.T}]"
        events = []

    include_end = completed or not contract_status
    time = _output_times(tau, numeric_values["output_dt"], include_end=include_end)
    y_samples = np.asarray(sol.sol(time), dtype=float).T if time.size else np.empty((0, model.y0.size))
    try:
        state, derived, diagnostics = _sample_cable(model, time, y_samples)
    except Exception as exc:
        return SimulationResult(
            model_id="FWD-CABLE-1.0",
            contract_status=[],
            numerical_status="DIAGNOSTIC_FAILURE",
            tau=float(tau),
            returned_interval="candidate only; physical derived output unresolved",
            time=time,
            events=[
                {
                    "kind": "numerical_diagnostic_failure",
                    "message": repr(exc),
                    "discarded_events": events,
                }
            ],
            state={"candidate_solver_state": y_samples},
            diagnostics={
                "solver_message": sol.message,
                "solver_warnings": solver_warnings,
            },
            metadata=identity,
        )
    solver_diagnostic_fields = dict(
        solver_message=sol.message,
        nfev=int(sol.nfev),
        njev=int(getattr(sol, "njev", 0)),
        nlu=int(getattr(sol, "nlu", 0)),
        mass_matrix=model.mass_diagnostics,
        preparation=model.preparation_diagnostics,
        refinement_qualification="SINGLE_RUN_CANDIDATE",
        solver_warnings=solver_warnings,
    )
    diagnostics.update(solver_diagnostic_fields)
    sampled_violation = diagnostics.get("sampled_guard_violation")
    nonfinite_violation = _first_nonfinite_sample(time, state, derived)
    numerical_sample_failure: dict[str, Any] | None = None
    if completed and sampled_violation is not None:
        numerical_sample_failure = {
            "kind": "numerical_event_unresolved",
            "numerical_status": "EVENT_UNRESOLVED",
            "time": float(sampled_violation["time"]),
            "sample_index": int(sampled_violation["sample_index"]),
            "triggers": sampled_violation["triggers"],
        }
    if completed and nonfinite_violation is not None and (
        numerical_sample_failure is None
        or nonfinite_violation["time"] <= numerical_sample_failure["time"]
    ):
        numerical_sample_failure = {
            "kind": "numerical_nonfinite_state",
            "numerical_status": "NONFINITE_STATE",
            **nonfinite_violation,
        }
    if numerical_sample_failure is not None:
        failure_index = int(numerical_sample_failure.get("sample_index", 0))
        numerical_sample_failure["detected_sample_state"] = (
            _snapshot_time_index(state, failure_index)
        )
        numerical_sample_failure["detected_sample_derived"] = (
            _snapshot_time_index(derived, failure_index)
        )
        completed = False
        contract_status = []
        numerical_status = numerical_sample_failure["numerical_status"]
        tau = float(numerical_sample_failure["time"])
        returned_interval = (
            "candidate samples only; completed physical contract could not be "
            f"certified at or before {tau}"
        )
        events = [numerical_sample_failure]
        time = time[:failure_index]
        y_samples = y_samples[:failure_index]
        state, derived, diagnostics = _sample_cable(model, time, y_samples)
        diagnostics.update(solver_diagnostic_fields)
        diagnostics["postrun_failure"] = numerical_sample_failure

    def position_at(times):
        query = np.asarray(sol.sol(times), dtype=float).T
        positions = np.empty((query.shape[0], 3))
        for index, (t_value, y_value) in enumerate(zip(np.asarray(times), query)):
            full_positions, _velocities = model.full_state(float(t_value), y_value)
            positions[index] = full_positions[model.node_index["bob"]]
        return positions

    observations = (
        {
            "status": ["OBSERVATION_UNRESOLVED_DUE_TO_NUMERICS"],
            "errors": [
                {
                    "code": numerical_status,
                    "detected_at_sample": tau,
                }
            ],
        }
        if numerical_sample_failure is not None
        and config.get("observation") is not None
        else evaluate_observations(
            config.get("observation"),
            position_at=position_at,
            interval_end=tau,
            completed=completed,
            e_z=physical.e_z,
            event_time_tolerance=cluster_tolerance,
        )
    )
    return SimulationResult(
        model_id="FWD-CABLE-1.0",
        contract_status=contract_status,
        numerical_status=numerical_status,
        tau=tau,
        returned_interval=returned_interval,
        time=time,
        state=state,
        derived=derived,
        events=events,
        diagnostics=diagnostics,
        observations=observations,
        metadata={
            **identity,
            "integrator": method,
            "rtol": numeric_values["rtol"],
            "effective_rtol": numeric_values["rtol"],
            "atol": numeric_values["atol"],
            "atol_position": numeric_values["atol_position"],
            "atol_velocity": numeric_values["atol_velocity"],
            "effective_atol_vector": {
                "position": numeric_values["atol_position"],
                "velocity": numeric_values["atol_velocity"],
            },
            "max_step": numeric_values["max_step"],
            "event_cluster_tolerance": cluster_tolerance,
            "quadrature_order": model.quadrature_order,
            "elements": model.element_count,
            "node_ids": model.node_ids,
            "branch_nodes": {name: nodes.tolist() for name, nodes in model.branch_nodes.items()},
            "initial_regularization": "none",
            "constitutive_positive_part": "exact max(candidate,0)",
            "initial_trace_check": (
                "analytic polynomial schema plus 2049-point material-domain audit; not an H2 proof"
                if physical.initial_mode == "DIRECT_STATE"
                else "discrete multistart static minimization; local uniqueness evidence only"
            ),
        },
    )


def _physical_derived_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Extract exactly the frozen physical derived schema at one left limit."""

    scalar_names = (
        "T_kin",
        "V_g",
        "V_buoy",
        "V_ax",
        "E_F",
        "D_ax",
        "D_string",
        "D_b",
        "P_base",
        "P_air",
        "P_ext",
    )
    vector_names = ("F_drag_b", "R_A", "R_B")
    branch_names = (
        "lambda",
        "lambda_dot",
        "tangent",
        "N_elastic",
        "N_viscous",
        "N",
        "active",
        "slack",
        "loaded_length",
        "f_drag_center",
    )
    return {
        "branches": {
            branch: {
                name: snapshot["branches"][branch][name]
                for name in branch_names
            }
            for branch in BRANCHES
        },
        **{name: snapshot[name] for name in scalar_names},
        **{name: snapshot[name] for name in vector_names},
    }


def _sample_cable(model: CableFEM, time: np.ndarray, y_samples: np.ndarray):
    sample_count = time.size
    node_count = len(model.node_ids)
    positions = np.empty((sample_count, node_count, 3))
    velocities = np.empty_like(positions)
    scalar_names = (
        "T_kin", "V_g", "V_buoy", "V_ax", "E_F", "D_ax", "D_string",
        "D_b", "P_base", "P_air", "P_ext",
    )
    scalar = {name: np.empty(sample_count) for name in scalar_names}
    algebraic_base_power = np.empty(sample_count)
    vector = {
        "F_drag_b": np.empty((sample_count, 3)),
        "R_A": np.empty((sample_count, 3)),
        "R_B": np.empty((sample_count, 3)),
    }
    algebraic_reaction_A = np.empty((sample_count, 3))
    algebraic_reaction_B = np.empty((sample_count, 3))
    branch_output: dict[str, dict[str, np.ndarray]] = {}
    sampled_guard_minima: dict[str, float] = {}
    sampled_guard_series: dict[str, np.ndarray] = {
        "lambda": np.empty(sample_count),
        "material_lambda": np.empty(sample_count),
        "material_rate": np.empty(sample_count),
        **{
            f"custom:{guard.name}": np.empty(sample_count)
            for guard in model.p.guards
        },
    }
    component_scale_tree = model.guard_component_scales()
    sampled_guard_component_series: dict[str, np.ndarray] = {}
    guard_component_scales: dict[str, float] = {}
    for branch_name in BRANCHES:
        for element in range(model.element_count[branch_name]):
            trigger = f"LAMBDA_MIN:{branch_name}:element:{element}"
            sampled_guard_component_series[trigger] = np.empty(sample_count)
            guard_component_scales[trigger] = float(
                component_scale_tree["lambda"][branch_name]
            )
            for boundary in (
                "lambda_lower",
                "lambda_upper",
                "rate_lower",
                "rate_upper",
            ):
                trigger = (
                    "MATERIAL_DOMAIN:"
                    f"{branch_name}:{boundary}:element:{element}"
                )
                sampled_guard_component_series[trigger] = np.empty(
                    sample_count
                )
                guard_component_scales[trigger] = float(
                    component_scale_tree["material"][branch_name][boundary]
                )
    for guard in model.p.guards:
        trigger = f"EXIT_GUARD:{guard.name}"
        sampled_guard_component_series[trigger] = np.empty(sample_count)
        guard_component_scales[trigger] = float(guard.length_scale)
    sampled_guard_violation: dict[str, Any] | None = None
    for name in BRANCHES:
        count = model.element_count[name]
        branch_output[name] = {
            "lambda": np.empty((sample_count, count)),
            "lambda_dot": np.empty((sample_count, count)),
            "tangent": np.empty((sample_count, count, 3)),
            "N_elastic": np.empty((sample_count, count)),
            "N_viscous": np.empty((sample_count, count)),
            "N": np.empty((sample_count, count)),
            "active": np.empty((sample_count, count), dtype=bool),
            "slack": np.empty((sample_count, count), dtype=bool),
            "loaded_length": np.empty(sample_count),
            "f_drag_center": np.empty((sample_count, count, 3)),
        }
    for index, (t_value, y_value) in enumerate(zip(time, y_samples)):
        snapshot = model.diagnostic_snapshot(float(t_value), y_value)
        positions[index] = snapshot["positions"]
        velocities[index] = snapshot["velocities"]
        for name in scalar_names:
            scalar[name][index] = snapshot[name]
        algebraic_base_power[index] = snapshot["P_base_algebraic"]
        vector["F_drag_b"][index] = snapshot["F_drag_b"]
        vector["R_A"][index] = snapshot["R_A"]
        vector["R_B"][index] = snapshot["R_B"]
        algebraic_reaction_A[index] = snapshot["algebraic_reaction"][0]
        algebraic_reaction_B[index] = snapshot["algebraic_reaction"][1]
        for branch_name in BRANCHES:
            for field_name in branch_output[branch_name]:
                branch_output[branch_name][field_name][index] = snapshot["branches"][branch_name][field_name]
        guard_components = model.physical_guard_components(float(t_value), y_value)
        sampled_guard_series["lambda"][index] = min(
            float(np.min(values))
            for values in guard_components["lambda"].values()
        )
        sampled_guard_series["material_lambda"][index] = min(
            float(np.min(values))
            for boundaries in guard_components["material"].values()
            for boundary, values in boundaries.items()
            if boundary.startswith("lambda_")
        )
        sampled_guard_series["material_rate"][index] = min(
            float(np.min(values))
            for boundaries in guard_components["material"].values()
            for boundary, values in boundaries.items()
            if boundary.startswith("rate_")
        )
        for guard_name, value in guard_components["custom"].items():
            sampled_guard_series[f"custom:{guard_name}"][index] = float(value)
        for branch_name, values in guard_components["lambda"].items():
            for element, value in enumerate(np.asarray(values)):
                sampled_guard_component_series[
                    f"LAMBDA_MIN:{branch_name}:element:{element}"
                ][index] = float(value)
        for branch_name, boundaries in guard_components["material"].items():
            for boundary, values in boundaries.items():
                for element, value in enumerate(np.asarray(values)):
                    sampled_guard_component_series[
                        "MATERIAL_DOMAIN:"
                        f"{branch_name}:{boundary}:element:{element}"
                    ][index] = float(value)
        for guard_name, value in guard_components["custom"].items():
            sampled_guard_component_series[
                f"EXIT_GUARD:{guard_name}"
            ][index] = float(value)
        for branch_name, values in guard_components["lambda"].items():
            key = f"lambda_min:{branch_name}"
            sampled_guard_minima[key] = min(
                sampled_guard_minima.get(key, np.inf), float(np.min(values))
            )
        for branch_name, boundaries in guard_components["material"].items():
            for boundary, values in boundaries.items():
                key = f"material:{branch_name}:{boundary}"
                sampled_guard_minima[key] = min(
                    sampled_guard_minima.get(key, np.inf), float(np.min(values))
                )
        for guard_name, value in guard_components["custom"].items():
            key = f"custom:{guard_name}"
            sampled_guard_minima[key] = min(
                sampled_guard_minima.get(key, np.inf), float(value)
            )
        violation_triggers = _nonpositive_guard_triggers(
            guard_components,
            model.guard_component_scales(),
        )
        if sampled_guard_violation is None and violation_triggers:
            sampled_guard_violation = {
                "time": float(t_value),
                "sample_index": int(index),
                "triggers": violation_triggers,
            }
    derived: dict[str, Any] = {"branches": branch_output, **scalar, **vector}
    if sample_count >= 2:
        physical_power = -scalar["D_ax"] - scalar["D_string"] - scalar["D_b"] + scalar["P_air"] + scalar["P_base"] + scalar["P_ext"]
        algebraic_power = -scalar["D_ax"] - scalar["D_string"] - scalar["D_b"] + scalar["P_air"] + algebraic_base_power + scalar["P_ext"]
        physical_integral = cumulative_trapezoid(physical_power, time, initial=0.0)
        algebraic_integral = cumulative_trapezoid(algebraic_power, time, initial=0.0)
        physical_residual = scalar["E_F"] - scalar["E_F"][0] - physical_integral
        algebraic_residual = scalar["E_F"] - scalar["E_F"][0] - algebraic_integral
        work_scale = max(
            float(np.trapz(np.abs(physical_power), time)),
            float(np.trapz(np.abs(algebraic_power), time)),
        )
    else:
        physical_residual = np.zeros(sample_count)
        algebraic_residual = np.zeros(sample_count)
        work_scale = 0.0
    total_mass = (
        model.p.junction_mass
        + model.p.bob_mass
        + sum(
            branch.mu * branch.L0 for branch in model.p.branches.values()
        )
    )
    characteristic_length = sum(
        branch.L0 for branch in model.p.branches.values()
    )
    gravitational_scale = total_mass * model.p.g * characteristic_length
    energy_variation = (
        float(np.max(np.abs(scalar["E_F"] - scalar["E_F"][0])))
        if sample_count
        else 0.0
    )
    stored_scale = (
        max(
            float(np.max(np.abs(scalar["T_kin"]))),
            float(np.max(np.abs(scalar["V_ax"]))),
        )
        if sample_count
        else 0.0
    )
    energy_scale = max(
        gravitational_scale,
        energy_variation,
        stored_scale,
        work_scale,
        np.finfo(float).tiny,
    )
    max_physical_residual = (
        float(np.max(np.abs(physical_residual))) if sample_count else None
    )
    max_algebraic_residual = (
        float(np.max(np.abs(algebraic_residual))) if sample_count else None
    )
    diagnostics = {
        "energy_scale": float(energy_scale),
        "energy_scale_components": {
            "gravitational": float(gravitational_scale),
            "energy_variation": float(energy_variation),
            "stored": float(stored_scale),
            "absolute_work_integral": float(work_scale),
        },
        "max_absolute_energy_power_residual_physical_traction": max_physical_residual,
        "max_absolute_energy_power_residual_algebraic_reaction": max_algebraic_residual,
        "max_relative_energy_power_residual_physical_traction": float(max_physical_residual / energy_scale) if sample_count else None,
        "max_relative_energy_power_residual_algebraic_reaction": float(max_algebraic_residual / energy_scale) if sample_count else None,
        "min_D_ax": float(np.min(scalar["D_ax"])) if sample_count else None,
        "min_D_string": float(np.min(scalar["D_string"])) if sample_count else None,
        "min_D_b": float(np.min(scalar["D_b"])) if sample_count else None,
        "max_boundary_reaction_difference": float(np.max(np.linalg.norm(np.stack((vector["R_A"] - algebraic_reaction_A, vector["R_B"] - algebraic_reaction_B), axis=1), axis=2))) if sample_count else None,
        "sampled_guard_minima": sampled_guard_minima,
        "sampled_guard_series": sampled_guard_series,
        "sampled_guard_component_series": sampled_guard_component_series,
        "guard_component_scales": guard_component_scales,
        "custom_guard_length_scales": {
            guard.name: guard.length_scale for guard in model.p.guards
        },
        "sampled_guard_violation": sampled_guard_violation,
        "reaction_algebraic": {
            "A": algebraic_reaction_A,
            "B": algebraic_reaction_B,
        },
        "P_base_algebraic": algebraic_base_power,
    }
    state = {
        "node_positions": positions,
        "node_velocities": velocities,
        "r_J": positions[:, model.node_index["junction"]],
        "v_J": velocities[:, model.node_index["junction"]],
        "r_m": positions[:, model.node_index["bob"]],
        "v_m": velocities[:, model.node_index["bob"]],
    }
    return state, derived, diagnostics


def _nonpositive_guard_triggers(
    components: dict[str, Any], component_scales: dict[str, Any]
) -> list[str]:
    triggers: list[str] = []
    for branch, values in components["lambda"].items():
        array = np.asarray(values, dtype=float)
        tolerance = (
            1024.0
            * np.finfo(float).eps
            * component_scales["lambda"][branch]
        )
        for element in np.flatnonzero(array <= tolerance):
            triggers.append(f"LAMBDA_MIN:{branch}:element:{int(element)}")
    for branch, branch_values in components["material"].items():
        for boundary, values in branch_values.items():
            array = np.asarray(values, dtype=float)
            tolerance = (
                1024.0
                * np.finfo(float).eps
                * component_scales["material"][branch][boundary]
            )
            for element in np.flatnonzero(array <= tolerance):
                triggers.append(
                    f"MATERIAL_DOMAIN:{branch}:{boundary}:element:{int(element)}"
                )
    for name, value in components["custom"].items():
        tolerance = (
            1024.0
            * np.finfo(float).eps
            * component_scales["custom"][name]
        )
        if float(value) <= tolerance:
            triggers.append(f"EXIT_GUARD:{name}")
    return sorted(triggers)


def _first_nonfinite_sample(
    time: np.ndarray,
    state: dict[str, Any],
    derived: dict[str, Any],
) -> dict[str, Any] | None:
    """Locate the earliest non-finite returned physical state/derived sample."""

    failures: list[tuple[int, str]] = []

    def inspect(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for name, child in value.items():
                inspect(f"{prefix}.{name}" if prefix else str(name), child)
            return
        array = np.asarray(value)
        if array.dtype == object:
            failures.append((0, prefix))
            return
        if array.ndim == 0 or array.shape[0] != time.size:
            if not np.all(np.isfinite(array)):
                failures.append((0, prefix))
            return
        rows = np.reshape(np.isfinite(array), (time.size, -1)).all(axis=1)
        bad = np.flatnonzero(~rows)
        if bad.size:
            failures.append((int(bad[0]), prefix))

    inspect("state", state)
    inspect("derived", derived)
    if not failures:
        return None
    index = min(item[0] for item in failures)
    return {
        "time": float(time[index]) if time.size else 0.0,
        "sample_index": index,
        "fields": sorted(name for row, name in failures if row == index),
    }


def _snapshot_time_index(value: Any, index: int) -> Any:
    """Extract one evidence sample from a nested time-indexed result tree."""

    if isinstance(value, dict):
        return {
            name: _snapshot_time_index(child, index)
            for name, child in value.items()
        }
    array = np.asarray(value)
    if array.ndim and index < array.shape[0]:
        return array[index]
    return value


def _collect_rooted_guard_triggers(
    components: dict[str, Any],
    rooted_names: list[str],
    component_scales: dict[str, Any],
) -> list[str]:
    """Resolve the event set from root-time evidence, not a mixed-unit cutoff."""

    triggers: list[str] = []
    rooted = set(rooted_names)
    lambda_records: list[tuple[float, str]] = []
    for branch, values in components["lambda"].items():
        scale = component_scales["lambda"][branch]
        array = np.asarray(values, dtype=float)
        for element, value in enumerate(array):
            name = f"LAMBDA_MIN:{branch}:element:{element}"
            normalized = abs(float(value)) / scale
            lambda_records.append((normalized, name))
            if normalized <= 1024.0 * np.finfo(float).eps:
                triggers.append(name)
    if "LAMBDA_MIN" in rooted and not any(
        name.startswith("LAMBDA_MIN:") for name in triggers
    ) and lambda_records:
        triggers.append(min(lambda_records)[1])

    material_records: list[tuple[float, str]] = []
    for branch, branch_values in components["material"].items():
        for boundary, values in branch_values.items():
            scale = component_scales["material"][branch][boundary]
            array = np.asarray(values, dtype=float)
            for element, value in enumerate(array):
                name = (
                    "MATERIAL_DOMAIN:"
                    f"{branch}:{boundary}:element:{element}"
                )
                normalized = abs(float(value)) / scale
                material_records.append((normalized, name))
                if normalized <= 1024.0 * np.finfo(float).eps:
                    triggers.append(name)
    if "MATERIAL_DOMAIN" in rooted and not any(
        name.startswith("MATERIAL_DOMAIN:") for name in triggers
    ) and material_records:
        triggers.append(min(material_records)[1])

    for rooted_name in rooted:
        if rooted_name.startswith("EXIT_GUARD:"):
            # Each registered custom guard has its own solve_ivp event function;
            # membership therefore comes from a root time, not from its value
            # being merely small in unrelated physical units.
            triggers.append(rooted_name)
    # solve_ivp truncates its event table at the first terminal root, so two
    # distinct custom guards with the same mathematical zero may leave only
    # the first root time recorded.  Re-evaluate all registered guards at the
    # rooted state and add only machine-scale zeros.  This captures identical
    # simultaneous guards while excluding merely small positive margins.
    custom = components["custom"]
    if custom:
        for name, value in custom.items():
            magnitude = abs(float(value))
            local_zero_tolerance = (
                1024.0
                * np.finfo(float).eps
                * component_scales["custom"][name]
            )
            if magnitude <= local_zero_tolerance:
                triggers.append(f"EXIT_GUARD:{name}")
    return sorted(set(triggers))


def _guard_scale_for_trigger(
    trigger: str, component_scales: dict[str, Any]
) -> float:
    if trigger.startswith("LAMBDA_MIN:"):
        _kind, branch, _label, _element = trigger.split(":")
        return float(component_scales["lambda"][branch])
    if trigger.startswith("MATERIAL_DOMAIN:"):
        _kind, branch, boundary, _label, _element = trigger.split(":")
        return float(component_scales["material"][branch][boundary])
    if trigger.startswith("EXIT_GUARD:"):
        return float(
            component_scales["custom"][trigger.split(":", 1)[1]]
        )
    raise ValueError(f"unknown guard trigger: {trigger}")


def _invalid_numerics(config, path, actual, expected, identity):
    return SimulationResult(
        model_id="FWD-CABLE-1.0",
        contract_status=[],
        numerical_status="INVALID_NUMERICAL_CONFIG",
        tau=0.0,
        returned_interval="empty",
        time=np.empty(0),
        events=[{"kind": "numerical_input", "failures": [ValidationIssue("NUMERICAL_CONFIG", path, actual, expected).as_dict()]}],
        metadata=identity,
    )


def _invalid_numerical_issues(
    config: dict[str, Any],
    issues: list[ValidationIssue],
    identity: dict[str, Any],
) -> SimulationResult:
    return SimulationResult(
        model_id="FWD-CABLE-1.0",
        contract_status=[],
        numerical_status="INVALID_NUMERICAL_CONFIG",
        tau=0.0,
        returned_interval="empty",
        time=np.empty(0),
        events=[
            {
                "kind": "numerical_input",
                "failures": [issue.as_dict() for issue in issues],
            }
        ],
        metadata=identity,
    )

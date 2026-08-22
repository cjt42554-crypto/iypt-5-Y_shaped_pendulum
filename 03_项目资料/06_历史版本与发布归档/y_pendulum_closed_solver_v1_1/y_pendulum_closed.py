#!/usr/bin/env python3
"""Theory-driven closed solver for the IYPT 2027 Y-shaped pendulum.

This program implements the fixed-support, point-bob, 15-generalized-coordinate
quadratic Ritz closure in Section 13 of
``IYPT_2027_Y_Pendulum_Unified_Closed_Predictive_Theory_v3.md``.

It is deliberately *not* a many-particle first-principles string simulation.
Each physical string is represented by exactly one quadratic Ritz internal node.
The state is

    q = (c_A, c_B, r_J, c_lower, r_m) in R^15,
    X = (q, q_dot) in R^30,

and the code integrates the closed theory equation

    M q_ddot = F(q, q_dot; parameters).

Implemented terms from the theory:
- quadratic Ritz centerlines and analytic consistent string mass matrix;
- concentrated junction and bob masses, optional isotropic added mass;
- gravity and optional buoyancy;
- unilateral C1 strain activation and unilateral Kelvin-Voigt axial force;
- analytic generalized axial force;
- optional distributed bending energy and endpoint tangent springs;
- anisotropic linear/quadratic string drag and bob/junction drag;
- optional Coriolis/centrifugal terms;
- static-potential initialization and minimum-kinetic velocity lift;
- full-state, string-shape, local-stretch, local-tension and energy outputs;
- top-view 3D-scene animation with selectable orthographic or pinhole projection.

Not included in this fixed-support base implementation:
- the optional moving-support extension;
- the optional rigid-body bob attitude/torsion extension;
- additional contacts such as string-string, string-support or bob-paper contact.
Those extensions require extra constitutive data beyond the base Eq. (13.18).

SI units are used throughout.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import solve_ivp
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize

Array = NDArray[np.float64]

# =============================================================================
# 用户只需要修改这里：统一输入参数区
# =============================================================================
# 直接运行 ``python y_pendulum_closed.py`` 时，程序读取下面这一份配置。
# 仍可额外传入 JSON 文件覆盖它，但不再需要在程序后文寻找任何物理、
# 初始条件、积分、输出或动画参数。
USER_INPUTS: dict[str, Any] = {
    "model": {
        # 坐标约定：z 轴竖直向下；长度 m，质量 kg，时间 s。
        "supports": {
            "A": [-0.1500000000, 0.0, 0.0],
            "B": [ 0.1500000000, 0.0, 0.0],
        },
        "gravity": 9.81,
        "air_density": 1.20,
        "junction_mass": 0.002,
        "bob": {
            "mass": 0.200,
            "volume": 4.1887902048e-6,
            "added_mass_coefficient": 0.0,
            "drag": {
                "linear": 0.001,
                "quadratic": 0.015,
            },
        },
        "strings": {
            "A": {
                "rest_length": 0.4024786851371079,
                "mass": 0.005,
                "EA": 300.0,
                "etaA": 0.20,
                "EI": 0.0,
                "drag": {
                    "c_parallel": 0.0,
                    "c_perpendicular": 0.0008,
                    "d_parallel": 0.0,
                    "d_perpendicular": 0.002,
                },
                "end_bending": [],
            },
            "B": {
                "rest_length": 0.4024786851371079,
                "mass": 0.005,
                "EA": 300.0,
                "etaA": 0.20,
                "EI": 0.0,
                "drag": {
                    "c_parallel": 0.0,
                    "c_perpendicular": 0.0008,
                    "d_parallel": 0.0,
                    "d_perpendicular": 0.002,
                },
                "end_bending": [],
            },
            "lower": {
                "rest_length": 0.29791459781529295,
                "mass": 0.004,
                "EA": 300.0,
                "etaA": 0.20,
                "EI": 0.0,
                "drag": {
                    "c_parallel": 0.0,
                    "c_perpendicular": 0.0008,
                    "d_parallel": 0.0,
                    "d_perpendicular": 0.002,
                },
                "end_bending": [],
            },
        },
        "regularization": {
            "delta_strain": 2.0e-4,
            "epsilon_tangent": 1.0e-8,
            "epsilon_curvature": 1.0e-8,
        },
        "junction_drag": {
            "linear": 0.0002,
            "quadratic": 0.0,
        },
        "external_forces": {
            "junction": [0.0, 0.0, 0.0],
            "bob": [0.0, 0.0, 0.0],
        },
        "rotation": {
            "omega": [0.0, 0.0, 0.0],
            "include_centrifugal": False,
        },
    },
    "initial_condition": {
        "mode": "ideal_torus_release",
        "angle_unit": "deg",
        "working_lengths": {
            "A": 0.4038873605350878,
            "B": 0.4038873605350878,
            "lower": 0.300,
        },
        "phi": 5.0,
        "theta": 3.0,
        "phi_dot": 0.0,
        "theta_dot": 0.0,
        "relax_internal_nodes": True,
        "internal_velocity": "minimum_kinetic",
        "relax_tolerance": 1.0e-10,
        "relax_max_iterations": 3000,
    },
    "integration": {
        "t_end": 1.0,
        "output_dt": 0.005,
        "method": "BDF",
        "rtol": 1.0e-8,
        "atol": 1.0e-10,
        "max_step": 0.003,
        "max_strain": 0.08,
        "max_coordinate_radius": None,
        "quadrature_order": 10,
    },
    "output": {
        "directory": "y_pendulum_results",
        "string_samples": 31,
        "plots": True,
        "modal_reference": {
            "s_A": 0.4038873605350878,
            "s_B": 0.4038873605350878,
            "ell": 0.300,
        },
        # 由三维 Ritz 状态渲染的俯视动画。
        "animation_3d": {
            "enabled": True,
            "filename": "y_pendulum_3d_top_view.mp4",
            "format": "mp4",             # mp4 或 gif
            "fps": 30,
            "playback_speed": 1.0,        # 1.0=实时；2.0=二倍速
            "dpi": 150,
            "figure_size_inches": [7.0, 7.0],
            "max_frames": 900,
            "trail_seconds": 1.0,         # 摆球投影轨迹尾迹长度（模拟时间）
            "margin_fraction": 0.08,
            "show_time": True,
            "show_principal_point": True,
            "line_width": 2.2,
            "support_marker_size": 7.0,
            "junction_marker_size": 6.0,
            "bob_marker_size": 10.0,
            "fallback_to_gif": True,
            "fail_on_error": False,
            "perspective": {
                # 只需改这一项即可切换：True=针孔透视，False=正交俯视。
                "enabled": True,
                # 相机位于两个上支点中点的正上方。因 z 轴向下，程序内部
                # 使用 C_camera = (A+B)/2 - camera_distance * e_z。
                "camera_distance": 1.50,
                # 光轴在装置中的落点（图像主点）固定为两个上支点的中点。
                "principal_point": "support_midpoint",
            },
        },
    },
}
# =============================================================================
# 用户输入参数区结束；下方均为理论求解与输出实现，通常不需要修改。
# =============================================================================

PROGRAM_VERSION = "1.1.0"
N_BLOCKS = 5
BLOCK_SIZE = 3
NQ = N_BLOCKS * BLOCK_SIZE
NX = 2 * NQ

BLOCK_NAMES = ("c_A", "c_B", "r_J", "c_lower", "r_m")
BLOCK_INDEX = {name: i for i, name in enumerate(BLOCK_NAMES)}
INTERNAL_BLOCKS = (0, 1, 3)
ENDPOINT_BLOCKS = (2, 4)
E_Z = np.array([0.0, 0.0, 1.0], dtype=float)  # z is positive downward


def block_slice(block: int) -> slice:
    return slice(3 * block, 3 * block + 3)


def _array3(value: Sequence[float], name: str) -> Array:
    arr = np.asarray(value, dtype=float)
    if arr.shape != (3,):
        raise ValueError(f"{name} must contain exactly three numbers; got shape {arr.shape}.")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} contains a non-finite number.")
    return arr


def _nonnegative(value: Any, name: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite nonnegative number; got {value!r}.") from exc
    if not math.isfinite(x) or x < 0.0:
        raise ValueError(f"{name} must be finite and nonnegative; got {value!r}.")
    return x


def _positive(value: Any, name: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite positive number; got {value!r}.") from exc
    if not math.isfinite(x) or x <= 0.0:
        raise ValueError(f"{name} must be finite and positive; got {value!r}.")
    return x


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Configuration file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in {path} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(obj, dict):
        raise ValueError("The configuration root must be a JSON object.")
    return obj


def _json_dump(path: Path, obj: Any) -> None:
    def default(x: Any) -> Any:
        if isinstance(x, np.ndarray):
            return x.tolist()
        if isinstance(x, (np.floating, np.integer)):
            return x.item()
        if isinstance(x, Path):
            return str(x)
        raise TypeError(f"Object of type {type(x).__name__} is not JSON serializable")

    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=default)
        f.write("\n")


def shape_functions(xi: Array | float) -> tuple[Array, Array, Array]:
    """Quadratic Lagrange shape functions and first/second xi derivatives."""
    x = np.asarray(xi, dtype=float)
    n0 = 2.0 * x**2 - 3.0 * x + 1.0
    n1 = 4.0 * x - 4.0 * x**2
    n2 = 2.0 * x**2 - x
    dn0 = 4.0 * x - 3.0
    dn1 = 4.0 - 8.0 * x
    dn2 = 4.0 * x - 1.0
    ddn0 = np.full_like(x, 4.0)
    ddn1 = np.full_like(x, -8.0)
    ddn2 = np.full_like(x, 4.0)
    return (
        np.stack((n0, n1, n2), axis=-1),
        np.stack((dn0, dn1, dn2), axis=-1),
        np.stack((ddn0, ddn1, ddn2), axis=-1),
    )


def activation_p(x: Array | float, delta: float) -> Array:
    """C1 unilateral activation P_delta from Eq. (13.10)."""
    arr = np.asarray(x, dtype=float)
    out = np.zeros_like(arr)
    middle = (arr > 0.0) & (arr < delta)
    high = arr >= delta
    xm = arr[middle]
    out[middle] = xm**2 * (2.0 * delta - xm) / delta**2
    out[high] = arr[high]
    return out


def activation_dp(x: Array | float, delta: float) -> Array:
    """Derivative P'_delta from Eq. (13.10)."""
    arr = np.asarray(x, dtype=float)
    out = np.zeros_like(arr)
    middle = (arr > 0.0) & (arr < delta)
    high = arr >= delta
    xm = arr[middle]
    out[middle] = 4.0 * xm / delta - 3.0 * xm**2 / delta**2
    out[high] = 1.0
    return out


def activation_integral(x: Array | float, delta: float) -> Array:
    """Phi_delta(x) = integral_0^x P_delta(u) du, with Phi_delta(0)=0."""
    arr = np.asarray(x, dtype=float)
    out = np.zeros_like(arr)
    middle = (arr > 0.0) & (arr < delta)
    high = arr >= delta
    xm = arr[middle]
    out[middle] = (2.0 / 3.0) * xm**3 / delta - 0.25 * xm**4 / delta**2
    out[high] = 0.5 * arr[high] ** 2 - delta**2 / 12.0
    return out


@dataclass(frozen=True)
class DragParameters:
    c_parallel: float = 0.0
    c_perpendicular: float = 0.0
    d_parallel: float = 0.0
    d_perpendicular: float = 0.0

    @staticmethod
    def from_mapping(cfg: Mapping[str, Any] | None, prefix: str) -> "DragParameters":
        c = cfg or {}
        return DragParameters(
            c_parallel=_nonnegative(c.get("c_parallel", 0.0), f"{prefix}.c_parallel"),
            c_perpendicular=_nonnegative(
                c.get("c_perpendicular", c.get("c_perp", 0.0)),
                f"{prefix}.c_perpendicular",
            ),
            d_parallel=_nonnegative(c.get("d_parallel", 0.0), f"{prefix}.d_parallel"),
            d_perpendicular=_nonnegative(
                c.get("d_perpendicular", c.get("d_perp", 0.0)),
                f"{prefix}.d_perpendicular",
            ),
        )


@dataclass(frozen=True)
class PointDragParameters:
    linear: float = 0.0
    quadratic: float = 0.0

    @staticmethod
    def from_mapping(cfg: Mapping[str, Any] | None, prefix: str) -> "PointDragParameters":
        c = cfg or {}
        return PointDragParameters(
            linear=_nonnegative(c.get("linear", c.get("c1", 0.0)), f"{prefix}.linear"),
            quadratic=_nonnegative(
                c.get("quadratic", c.get("c2", 0.0)), f"{prefix}.quadratic"
            ),
        )


@dataclass(frozen=True)
class EndBendingSpring:
    end: int
    stiffness: float
    target_tangent: tuple[float, float, float]

    @staticmethod
    def from_mapping(cfg: Mapping[str, Any], prefix: str) -> "EndBendingSpring":
        end = int(cfg.get("end", 0))
        if end not in (0, 1):
            raise ValueError(f"{prefix}.end must be 0 or 1.")
        k = _nonnegative(cfg.get("stiffness", cfg.get("K_alpha", 0.0)), f"{prefix}.stiffness")
        target = _array3(cfg.get("target_tangent", [0.0, 0.0, 1.0]), f"{prefix}.target_tangent")
        norm = float(np.linalg.norm(target))
        if norm <= 0.0:
            raise ValueError(f"{prefix}.target_tangent must be nonzero.")
        target = target / norm
        return EndBendingSpring(end=end, stiffness=k, target_tangent=tuple(target.tolist()))


@dataclass(frozen=True)
class StringParameters:
    rest_length: float
    mass: float
    EA: float
    etaA: float = 0.0
    EI: float = 0.0
    drag: DragParameters = field(default_factory=DragParameters)
    end_bending: tuple[EndBendingSpring, ...] = ()

    @staticmethod
    def from_mapping(cfg: Mapping[str, Any], prefix: str) -> "StringParameters":
        springs_cfg = cfg.get("end_bending", [])
        if springs_cfg is None:
            springs_cfg = []
        if not isinstance(springs_cfg, list):
            raise ValueError(f"{prefix}.end_bending must be a list.")
        springs = tuple(
            EndBendingSpring.from_mapping(item, f"{prefix}.end_bending[{i}]")
            for i, item in enumerate(springs_cfg)
        )
        return StringParameters(
            rest_length=_positive(
                cfg.get("rest_length", cfg.get("L0")), f"{prefix}.rest_length"
            ),
            mass=_nonnegative(cfg.get("mass", 0.0), f"{prefix}.mass"),
            EA=_nonnegative(cfg.get("EA", 0.0), f"{prefix}.EA"),
            etaA=_nonnegative(cfg.get("etaA", cfg.get("eta_A", 0.0)), f"{prefix}.etaA"),
            EI=_nonnegative(cfg.get("EI", 0.0), f"{prefix}.EI"),
            drag=DragParameters.from_mapping(cfg.get("drag"), f"{prefix}.drag"),
            end_bending=springs,
        )


@dataclass(frozen=True)
class BobParameters:
    mass: float
    volume: float = 0.0
    added_mass_coefficient: float = 0.0
    drag: PointDragParameters = field(default_factory=PointDragParameters)

    @staticmethod
    def from_mapping(cfg: Mapping[str, Any], prefix: str = "model.bob") -> "BobParameters":
        return BobParameters(
            mass=_positive(cfg.get("mass"), f"{prefix}.mass"),
            volume=_nonnegative(cfg.get("volume", 0.0), f"{prefix}.volume"),
            added_mass_coefficient=_nonnegative(
                cfg.get("added_mass_coefficient", cfg.get("C_a", 0.0)),
                f"{prefix}.added_mass_coefficient",
            ),
            drag=PointDragParameters.from_mapping(cfg.get("drag"), f"{prefix}.drag"),
        )


@dataclass(frozen=True)
class RegularizationParameters:
    delta_strain: float
    epsilon_tangent: float
    epsilon_curvature: float

    @staticmethod
    def from_mapping(cfg: Mapping[str, Any] | None) -> "RegularizationParameters":
        c = cfg or {}
        return RegularizationParameters(
            delta_strain=_positive(
                c.get("delta_strain", c.get("delta_epsilon", 1.0e-4)),
                "model.regularization.delta_strain",
            ),
            epsilon_tangent=_positive(
                c.get("epsilon_tangent", c.get("epsilon_t", 1.0e-9)),
                "model.regularization.epsilon_tangent",
            ),
            epsilon_curvature=_positive(
                c.get("epsilon_curvature", c.get("epsilon_kappa", 1.0e-9)),
                "model.regularization.epsilon_curvature",
            ),
        )


@dataclass(frozen=True)
class RotationParameters:
    omega: tuple[float, float, float] = (0.0, 0.0, 0.0)
    include_centrifugal: bool = False

    @staticmethod
    def from_mapping(cfg: Mapping[str, Any] | None) -> "RotationParameters":
        c = cfg or {}
        omega = _array3(c.get("omega", [0.0, 0.0, 0.0]), "model.rotation.omega")
        return RotationParameters(
            omega=tuple(omega.tolist()),
            include_centrifugal=bool(c.get("include_centrifugal", False)),
        )


@dataclass(frozen=True)
class ModelParameters:
    support_A: tuple[float, float, float]
    support_B: tuple[float, float, float]
    strings: dict[str, StringParameters]
    junction_mass: float
    bob: BobParameters
    gravity: float = 9.81
    air_density: float = 1.225
    regularization: RegularizationParameters = field(
        default_factory=lambda: RegularizationParameters(1.0e-4, 1.0e-9, 1.0e-9)
    )
    junction_drag: PointDragParameters = field(default_factory=PointDragParameters)
    external_force_junction: tuple[float, float, float] = (0.0, 0.0, 0.0)
    external_force_bob: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: RotationParameters = field(default_factory=RotationParameters)

    @staticmethod
    def from_config(root: Mapping[str, Any]) -> "ModelParameters":
        model = root.get("model", root)
        if not isinstance(model, Mapping):
            raise ValueError("model must be a JSON object.")
        supports = model.get("supports", {})
        if not isinstance(supports, Mapping):
            raise ValueError("model.supports must be a JSON object.")
        A = _array3(supports.get("A"), "model.supports.A")
        B = _array3(supports.get("B"), "model.supports.B")
        if np.linalg.norm(B - A) <= 0.0:
            raise ValueError("The two support positions must be distinct.")

        string_cfg = model.get("strings")
        if not isinstance(string_cfg, Mapping):
            raise ValueError("model.strings must be a JSON object with A, B and lower entries.")
        lower_cfg = string_cfg.get("lower", string_cfg.get("ell"))
        if lower_cfg is None:
            raise ValueError("model.strings must contain a lower entry.")
        strings = {
            "A": StringParameters.from_mapping(string_cfg.get("A", {}), "model.strings.A"),
            "B": StringParameters.from_mapping(string_cfg.get("B", {}), "model.strings.B"),
            "lower": StringParameters.from_mapping(lower_cfg, "model.strings.lower"),
        }
        external = model.get("external_forces", {}) or {}
        if not isinstance(external, Mapping):
            raise ValueError("model.external_forces must be a JSON object.")
        return ModelParameters(
            support_A=tuple(A.tolist()),
            support_B=tuple(B.tolist()),
            strings=strings,
            junction_mass=_nonnegative(
                model.get("junction_mass", model.get("m_J", 0.0)), "model.junction_mass"
            ),
            bob=BobParameters.from_mapping(model.get("bob", {})),
            gravity=_positive(model.get("gravity", 9.81), "model.gravity"),
            air_density=_nonnegative(model.get("air_density", 1.225), "model.air_density"),
            regularization=RegularizationParameters.from_mapping(model.get("regularization")),
            junction_drag=PointDragParameters.from_mapping(
                model.get("junction_drag"), "model.junction_drag"
            ),
            external_force_junction=tuple(
                _array3(external.get("junction", [0.0, 0.0, 0.0]),
                        "model.external_forces.junction").tolist()
            ),
            external_force_bob=tuple(
                _array3(external.get("bob", [0.0, 0.0, 0.0]),
                        "model.external_forces.bob").tolist()
            ),
            rotation=RotationParameters.from_mapping(model.get("rotation")),
        )


@dataclass
class BranchOperators:
    name: str
    params: StringParameters
    nodes: tuple[Array | int, Array | int, Array | int]
    xi: Array
    weights: Array
    B: Array
    B_xi: Array
    B_xixi: Array
    a: Array
    a_xi: Array
    a_xixi: Array

    @staticmethod
    def build(
        name: str,
        params: StringParameters,
        nodes: tuple[Array | int, Array | int, Array | int],
        xi: Array,
        weights: Array,
    ) -> "BranchOperators":
        B, Bx, Bxx, a, ax, axx = build_operators(nodes, xi)
        return BranchOperators(name, params, nodes, xi, weights, B, Bx, Bxx, a, ax, axx)

    def operators_at(self, xi: Array) -> tuple[Array, Array, Array, Array, Array, Array]:
        return build_operators(self.nodes, xi)


def build_operators(
    nodes: tuple[Array | int, Array | int, Array | int], xi: Array | Sequence[float]
) -> tuple[Array, Array, Array, Array, Array, Array]:
    x = np.atleast_1d(np.asarray(xi, dtype=float))
    N, dN, ddN = shape_functions(x)
    n = len(x)
    B = np.zeros((n, 3, NQ), dtype=float)
    Bx = np.zeros_like(B)
    Bxx = np.zeros_like(B)
    a = np.zeros((n, 3), dtype=float)
    ax = np.zeros_like(a)
    axx = np.zeros_like(a)
    I3 = np.eye(3)
    for local_index, node in enumerate(nodes):
        if isinstance(node, (int, np.integer)):
            sl = block_slice(int(node))
            B[:, :, sl] += N[:, local_index, None, None] * I3
            Bx[:, :, sl] += dN[:, local_index, None, None] * I3
            Bxx[:, :, sl] += ddN[:, local_index, None, None] * I3
        else:
            fixed = np.asarray(node, dtype=float)
            a += N[:, local_index, None] * fixed[None, :]
            ax += dN[:, local_index, None] * fixed[None, :]
            axx += ddN[:, local_index, None] * fixed[None, :]
    return B, Bx, Bxx, a, ax, axx


class ClosedYModel:
    """Fixed-support 15-coordinate quadratic Ritz closure."""

    def __init__(self, params: ModelParameters, quadrature_order: int = 10):
        self.params = params
        if quadrature_order < 3:
            raise ValueError("quadrature_order must be at least 3.")
        xg, wg = np.polynomial.legendre.leggauss(quadrature_order)
        self.xi = 0.5 * (xg + 1.0)
        self.weights = 0.5 * wg
        A = np.asarray(params.support_A, dtype=float)
        B = np.asarray(params.support_B, dtype=float)
        self.support_A = A
        self.support_B = B
        self.branches: dict[str, BranchOperators] = {
            "A": BranchOperators.build(
                "A", params.strings["A"], (A, 0, 2), self.xi, self.weights
            ),
            "B": BranchOperators.build(
                "B", params.strings["B"], (B, 1, 2), self.xi, self.weights
            ),
            "lower": BranchOperators.build(
                "lower", params.strings["lower"], (2, 3, 4), self.xi, self.weights
            ),
        }
        self.mass_matrix = self._assemble_mass_matrix()
        eig = np.linalg.eigvalsh(self.mass_matrix)
        self.mass_eigenvalues = eig
        scale = max(float(np.max(eig)), 1.0)
        if float(np.min(eig)) <= 1.0e-14 * scale:
            raise ValueError(
                "The assembled 15x15 mass matrix is not positive definite. "
                "The closed theory requires positive inertia in every retained Ritz direction. "
                "Use positive physical string masses and sufficient junction/bob mass; do not set "
                "all eliminated masses to zero inside the mother equation. "
                f"Eigenvalue range: [{eig.min():.3e}, {eig.max():.3e}]."
            )
        self._mass_factor = cho_factor(self.mass_matrix, overwrite_a=False, check_finite=True)
        self.gravity_force = self._assemble_gravity_force()
        self.buoyancy_force = np.zeros(NQ, dtype=float)
        self.buoyancy_force[block_slice(4)] = (
            -params.air_density * params.bob.volume * params.gravity * E_Z
        )
        self.external_force = np.zeros(NQ, dtype=float)
        self.external_force[block_slice(2)] = np.asarray(
            params.external_force_junction, dtype=float
        )
        self.external_force[block_slice(4)] = np.asarray(params.external_force_bob, dtype=float)

    def _assemble_mass_matrix(self) -> Array:
        p = self.params
        MA = p.strings["A"].mass
        MB = p.strings["B"].mass
        ML = p.strings["lower"].mass
        mJ = p.junction_mass
        m = p.bob.mass
        m_scal = np.array(
            [
                [8.0 * MA / 15.0, 0.0, MA / 15.0, 0.0, 0.0],
                [0.0, 8.0 * MB / 15.0, MB / 15.0, 0.0, 0.0],
                [
                    MA / 15.0,
                    MB / 15.0,
                    mJ + 2.0 * (MA + MB + ML) / 15.0,
                    ML / 15.0,
                    -ML / 30.0,
                ],
                [0.0, 0.0, ML / 15.0, 8.0 * ML / 15.0, ML / 15.0],
                [0.0, 0.0, -ML / 30.0, ML / 15.0, m + 2.0 * ML / 15.0],
            ],
            dtype=float,
        )
        M = np.kron(m_scal, np.eye(3))
        added = p.bob.added_mass_coefficient * p.air_density * p.bob.volume
        if added > 0.0:
            M[block_slice(4), block_slice(4)] += added * np.eye(3)
        return M

    def _assemble_gravity_force(self) -> Array:
        p = self.params
        g = p.gravity
        MA = p.strings["A"].mass
        MB = p.strings["B"].mass
        ML = p.strings["lower"].mass
        f = np.zeros(NQ, dtype=float)
        f[block_slice(0)] += (2.0 / 3.0) * MA * g * E_Z
        f[block_slice(1)] += (2.0 / 3.0) * MB * g * E_Z
        f[block_slice(2)] += (
            p.junction_mass + (MA + MB + ML) / 6.0
        ) * g * E_Z
        f[block_slice(3)] += (2.0 / 3.0) * ML * g * E_Z
        f[block_slice(4)] += (p.bob.mass + ML / 6.0) * g * E_Z
        return f

    @staticmethod
    def _eval_ops(B: Array, a: Array, q: Array) -> Array:
        return np.einsum("kij,j->ki", B, q) + a

    def branch_kinematics(
        self, branch: BranchOperators, q: Array, v: Array
    ) -> tuple[Array, Array, Array, Array, Array]:
        r = self._eval_ops(branch.B, branch.a, q)
        rxi = self._eval_ops(branch.B_xi, branch.a_xi, q)
        rxxi = self._eval_ops(branch.B_xixi, branch.a_xixi, q)
        vel = np.einsum("kij,j->ki", branch.B, v)
        vel_xi = np.einsum("kij,j->ki", branch.B_xi, v)
        return r, rxi, rxxi, vel, vel_xi

    def _stretch_quantities(
        self, branch: BranchOperators, q: Array, v: Array
    ) -> dict[str, Array]:
        _, rxi, _, _, vxi = self.branch_kinematics(branch, q, v)
        eps_t = self.params.regularization.epsilon_tangent
        L0 = branch.params.rest_length
        bar_L0 = math.sqrt(L0**2 + eps_t**2)
        s = np.sqrt(np.einsum("ki,ki->k", rxi, rxi) + eps_t**2)
        tangent = rxi / s[:, None]
        lam = s / bar_L0
        lam_dot = np.einsum("ki,ki->k", tangent, vxi) / bar_L0
        strain = lam - 1.0
        delta = self.params.regularization.delta_strain
        Ne = branch.params.EA * activation_p(strain, delta)
        Nv = branch.params.etaA * activation_dp(strain, delta) * lam_dot
        N = np.maximum(0.0, Ne + Nv)
        return {
            "rxi": rxi,
            "vxi": vxi,
            "tangent": tangent,
            "lambda": lam,
            "lambda_dot": lam_dot,
            "strain": strain,
            "N_elastic": Ne,
            "N_viscous_candidate": Nv,
            "N": N,
            "bar_L0": np.full_like(lam, bar_L0),
        }

    def axial_force(self, q: Array, v: Array, elastic_only: bool = False) -> Array:
        force = np.zeros(NQ, dtype=float)
        for branch in self.branches.values():
            info = self._stretch_quantities(branch, q, v)
            N = info["N_elastic"] if elastic_only else info["N"]
            Bt_t = np.einsum("kij,ki->kj", branch.B_xi, info["tangent"])
            factor = branch.params.rest_length / float(info["bar_L0"][0])
            force -= factor * np.sum(
                branch.weights[:, None] * N[:, None] * Bt_t, axis=0
            )
        return force

    def axial_energy(self, q: Array) -> float:
        v0 = np.zeros(NQ, dtype=float)
        total = 0.0
        delta = self.params.regularization.delta_strain
        for branch in self.branches.values():
            info = self._stretch_quantities(branch, q, v0)
            total += (
                branch.params.EA
                * branch.params.rest_length
                * float(np.sum(branch.weights * activation_integral(info["strain"], delta)))
            )
        return total

    def bending_force(self, q: Array) -> Array:
        """Analytic -grad(V_bend) for Eq. (13.15)."""
        force = np.zeros(NQ, dtype=float)
        eps_k = self.params.regularization.epsilon_curvature
        eps_t = self.params.regularization.epsilon_tangent
        for branch in self.branches.values():
            EI = branch.params.EI
            if EI > 0.0:
                _, a, b, _, _ = self.branch_kinematics(branch, q, np.zeros(NQ))
                a2 = np.einsum("ki,ki->k", a, a)
                b2 = np.einsum("ki,ki->k", b, b)
                ab = np.einsum("ki,ki->k", a, b)
                cross = np.cross(a, b)
                U = np.einsum("ki,ki->k", cross, cross)
                S = a2 + eps_k**2
                grad_a = (
                    2.0 * (b2[:, None] * a - ab[:, None] * b) / S[:, None] ** 3
                    - 6.0 * U[:, None] * a / S[:, None] ** 4
                )
                grad_b = 2.0 * (a2[:, None] * b - ab[:, None] * a) / S[:, None] ** 3
                grad_q_density = (
                    np.einsum("kij,ki->kj", branch.B_xi, grad_a)
                    + np.einsum("kij,ki->kj", branch.B_xixi, grad_b)
                )
                grad = (
                    0.5
                    * EI
                    * branch.params.rest_length
                    * np.sum(branch.weights[:, None] * grad_q_density, axis=0)
                )
                force -= grad

            for spring in branch.params.end_bending:
                if spring.stiffness <= 0.0:
                    continue
                x = np.array([float(spring.end)], dtype=float)
                _, Bx, _, _, ax, _ = branch.operators_at(x)
                tangent_raw = self._eval_ops(Bx, ax, q)[0]
                s = math.sqrt(float(np.dot(tangent_raw, tangent_raw)) + eps_t**2)
                t_hat = tangent_raw / s
                target = np.asarray(spring.target_tangent, dtype=float)
                err = t_hat - target
                jac_t = np.eye(3) / s - np.outer(tangent_raw, tangent_raw) / s**3
                grad = spring.stiffness * Bx[0].T @ (jac_t @ err)
                force -= grad
        return force

    def bending_energy(self, q: Array) -> float:
        total = 0.0
        eps_k = self.params.regularization.epsilon_curvature
        eps_t = self.params.regularization.epsilon_tangent
        v0 = np.zeros(NQ, dtype=float)
        for branch in self.branches.values():
            if branch.params.EI > 0.0:
                _, a, b, _, _ = self.branch_kinematics(branch, q, v0)
                cross = np.cross(a, b)
                numerator = np.einsum("ki,ki->k", cross, cross)
                denom = (np.einsum("ki,ki->k", a, a) + eps_k**2) ** 3
                kappa2 = numerator / denom
                total += (
                    0.5
                    * branch.params.EI
                    * branch.params.rest_length
                    * float(np.sum(branch.weights * kappa2))
                )
            for spring in branch.params.end_bending:
                if spring.stiffness <= 0.0:
                    continue
                x = np.array([float(spring.end)], dtype=float)
                _, Bx, _, _, ax, _ = branch.operators_at(x)
                tangent_raw = self._eval_ops(Bx, ax, q)[0]
                s = math.sqrt(float(np.dot(tangent_raw, tangent_raw)) + eps_t**2)
                t_hat = tangent_raw / s
                err = t_hat - np.asarray(spring.target_tangent, dtype=float)
                total += 0.5 * spring.stiffness * float(np.dot(err, err))
        return total

    def string_drag_force(self, q: Array, v: Array) -> Array:
        force = np.zeros(NQ, dtype=float)
        eps_t = self.params.regularization.epsilon_tangent
        for branch in self.branches.values():
            drag = branch.params.drag
            if (
                drag.c_parallel == 0.0
                and drag.c_perpendicular == 0.0
                and drag.d_parallel == 0.0
                and drag.d_perpendicular == 0.0
            ):
                continue
            _, rxi, _, vel, _ = self.branch_kinematics(branch, q, v)
            s = np.sqrt(np.einsum("ki,ki->k", rxi, rxi) + eps_t**2)
            t_hat = rxi / s[:, None]
            vpar = np.einsum("ki,ki->k", vel, t_hat)[:, None] * t_hat
            vperp = vel - vpar
            norm_par = np.linalg.norm(vpar, axis=1)
            norm_perp = np.linalg.norm(vperp, axis=1)
            density = (
                -drag.c_parallel * vpar
                -drag.c_perpendicular * vperp
                -drag.d_parallel * norm_par[:, None] * vpar
                -drag.d_perpendicular * norm_perp[:, None] * vperp
            )
            Bt_f = np.einsum("kij,ki->kj", branch.B, density)
            force += branch.params.rest_length * np.sum(
                branch.weights[:, None] * Bt_f, axis=0
            )
        return force

    def point_drag_force(self, v: Array) -> Array:
        force = np.zeros(NQ, dtype=float)
        vb = v[block_slice(4)]
        db = self.params.bob.drag
        force[block_slice(4)] += -db.linear * vb - db.quadratic * np.linalg.norm(vb) * vb
        vj = v[block_slice(2)]
        dj = self.params.junction_drag
        force[block_slice(2)] += -dj.linear * vj - dj.quadratic * np.linalg.norm(vj) * vj
        return force

    def rotation_force(self, q: Array, v: Array, include_coriolis: bool = True) -> Array:
        omega = np.asarray(self.params.rotation.omega, dtype=float)
        if np.linalg.norm(omega) == 0.0:
            return np.zeros(NQ, dtype=float)
        include_cent = self.params.rotation.include_centrifugal
        force = np.zeros(NQ, dtype=float)
        for branch in self.branches.values():
            r, _, _, vel, _ = self.branch_kinematics(branch, q, v)
            acc = np.zeros_like(r)
            if include_coriolis:
                acc += -2.0 * np.cross(omega[None, :], vel)
            if include_cent:
                acc += -np.cross(omega[None, :], np.cross(omega[None, :], r))
            Bt = np.einsum("kij,ki->kj", branch.B, acc)
            force += branch.params.mass * np.sum(branch.weights[:, None] * Bt, axis=0)
        for block, mass in ((2, self.params.junction_mass), (4, self.params.bob.mass)):
            r = q[block_slice(block)]
            vel = v[block_slice(block)]
            acc = np.zeros(3)
            if include_coriolis:
                acc += -2.0 * np.cross(omega, vel)
            if include_cent:
                acc += -np.cross(omega, np.cross(omega, r))
            force[block_slice(block)] += mass * acc
        return force

    def total_force(self, q: Array, v: Array) -> Array:
        return (
            self.gravity_force
            + self.buoyancy_force
            + self.external_force
            + self.axial_force(q, v, elastic_only=False)
            + self.bending_force(q)
            + self.string_drag_force(q, v)
            + self.point_drag_force(v)
            + self.rotation_force(q, v, include_coriolis=True)
        )

    def conservative_force(self, q: Array) -> Array:
        zero = np.zeros(NQ, dtype=float)
        cent = self.rotation_force(q, zero, include_coriolis=False)
        return (
            self.gravity_force
            + self.buoyancy_force
            + self.external_force
            + self.axial_force(q, zero, elastic_only=True)
            + self.bending_force(q)
            + cent
        )

    def acceleration(self, q: Array, v: Array) -> Array:
        return cho_solve(self._mass_factor, self.total_force(q, v), check_finite=False)

    def rhs(self, _t: float, X: Array) -> Array:
        if X.shape != (NX,):
            raise ValueError(f"State must have shape ({NX},); got {X.shape}.")
        q = X[:NQ]
        v = X[NQ:]
        if not np.all(np.isfinite(X)):
            raise FloatingPointError("State contains NaN or infinity.")
        a = self.acceleration(q, v)
        if not np.all(np.isfinite(a)):
            raise FloatingPointError("Acceleration contains NaN or infinity.")
        return np.concatenate((v, a))

    def gravity_potential(self, q: Array) -> float:
        p = self.params
        cA, cB, rJ, cL, rM = unpack_q(q)
        A = self.support_A
        B = self.support_B
        MA = p.strings["A"].mass
        MB = p.strings["B"].mass
        ML = p.strings["lower"].mass
        weighted_z = (
            p.junction_mass * rJ[2]
            + p.bob.mass * rM[2]
            + MA * (A[2] / 6.0 + 2.0 * cA[2] / 3.0 + rJ[2] / 6.0)
            + MB * (B[2] / 6.0 + 2.0 * cB[2] / 3.0 + rJ[2] / 6.0)
            + ML * (rJ[2] / 6.0 + 2.0 * cL[2] / 3.0 + rM[2] / 6.0)
        )
        return -p.gravity * float(weighted_z)

    def buoyancy_potential(self, q: Array) -> float:
        return (
            self.params.air_density
            * self.params.bob.volume
            * self.params.gravity
            * float(q[block_slice(4)][2])
        )

    def external_potential(self, q: Array) -> float:
        rJ = q[block_slice(2)]
        rM = q[block_slice(4)]
        return -float(
            np.dot(np.asarray(self.params.external_force_junction), rJ)
            + np.dot(np.asarray(self.params.external_force_bob), rM)
        )

    def centrifugal_potential(self, q: Array) -> float:
        if not self.params.rotation.include_centrifugal:
            return 0.0
        omega = np.asarray(self.params.rotation.omega, dtype=float)
        if np.linalg.norm(omega) == 0.0:
            return 0.0
        total = 0.0
        zero = np.zeros(NQ)
        for branch in self.branches.values():
            r, _, _, _, _ = self.branch_kinematics(branch, q, zero)
            cross = np.cross(omega[None, :], r)
            total += -0.5 * branch.params.mass * float(
                np.sum(branch.weights * np.einsum("ki,ki->k", cross, cross))
            )
        for block, mass in ((2, self.params.junction_mass), (4, self.params.bob.mass)):
            cross = np.cross(omega, q[block_slice(block)])
            total += -0.5 * mass * float(np.dot(cross, cross))
        return total

    def potential_components(self, q: Array) -> dict[str, float]:
        values = {
            "gravity": self.gravity_potential(q),
            "axial": self.axial_energy(q),
            "bending": self.bending_energy(q),
            "buoyancy": self.buoyancy_potential(q),
            "external": self.external_potential(q),
            "centrifugal": self.centrifugal_potential(q),
        }
        values["total"] = float(sum(values.values()))
        return values

    def total_potential(self, q: Array) -> float:
        return self.potential_components(q)["total"]

    def energy_components(self, q: Array, v: Array) -> dict[str, float]:
        potential = self.potential_components(q)
        kinetic = 0.5 * float(v @ self.mass_matrix @ v)
        return {
            "kinetic": kinetic,
            **{f"potential_{k}": val for k, val in potential.items() if k != "total"},
            "potential_total": potential["total"],
            "mechanical_total": kinetic + potential["total"],
        }

    def nonconservative_power(self, q: Array, v: Array) -> float:
        residual = self.total_force(q, v) - self.conservative_force(q)
        return float(v @ residual)

    def sample_branch(
        self, name: str, q: Array, v: Array, xi: Array
    ) -> dict[str, Array]:
        branch = self.branches[name]
        B, Bx, Bxx, a, ax, axx = branch.operators_at(xi)
        r = self._eval_ops(B, a, q)
        rxi = self._eval_ops(Bx, ax, q)
        rxxi = self._eval_ops(Bxx, axx, q)
        vel = np.einsum("kij,j->ki", B, v)
        vxi = np.einsum("kij,j->ki", Bx, v)
        eps_t = self.params.regularization.epsilon_tangent
        L0 = branch.params.rest_length
        bar = math.sqrt(L0**2 + eps_t**2)
        s = np.sqrt(np.einsum("ki,ki->k", rxi, rxi) + eps_t**2)
        t_hat = rxi / s[:, None]
        lam = s / bar
        lam_dot = np.einsum("ki,ki->k", t_hat, vxi) / bar
        strain = lam - 1.0
        delta = self.params.regularization.delta_strain
        Ne = branch.params.EA * activation_p(strain, delta)
        Nv = branch.params.etaA * activation_dp(strain, delta) * lam_dot
        tension = np.maximum(0.0, Ne + Nv)
        eps_k = self.params.regularization.epsilon_curvature
        cross = np.cross(rxi, rxxi)
        kappa = np.sqrt(np.einsum("ki,ki->k", cross, cross)) / (
            np.einsum("ki,ki->k", rxi, rxi) + eps_k**2
        ) ** 1.5
        return {
            "position": r,
            "velocity": vel,
            "stretch": lam,
            "strain": strain,
            "stretch_rate": lam_dot,
            "tension": tension,
            "elastic_tension": Ne,
            "viscous_candidate": Nv,
            "curvature": kappa,
            "tangent": t_hat,
        }

    def max_quadrature_strain(self, q: Array) -> float:
        zero = np.zeros(NQ)
        return max(
            float(np.max(self._stretch_quantities(branch, q, zero)["strain"]))
            for branch in self.branches.values()
        )


def unpack_q(q: Array) -> tuple[Array, Array, Array, Array, Array]:
    arr = np.asarray(q, dtype=float)
    if arr.shape != (NQ,):
        raise ValueError(f"q must have shape ({NQ},).")
    return tuple(arr[block_slice(i)] for i in range(N_BLOCKS))  # type: ignore[return-value]


def pack_blocks(mapping: Mapping[str, Sequence[float]], name: str) -> Array:
    q = np.zeros(NQ, dtype=float)
    aliases = {
        "cA": "c_A",
        "cB": "c_B",
        "J": "r_J",
        "junction": "r_J",
        "cL": "c_lower",
        "c_ell": "c_lower",
        "bob": "r_m",
        "m": "r_m",
    }
    normalized: dict[str, Any] = {}
    for key, value in mapping.items():
        normalized[aliases.get(key, key)] = value
    missing = [key for key in BLOCK_NAMES if key not in normalized]
    if missing:
        raise ValueError(f"{name} is missing blocks: {', '.join(missing)}")
    for i, key in enumerate(BLOCK_NAMES):
        q[block_slice(i)] = _array3(normalized[key], f"{name}.{key}")
    return q


def straight_node_guess(A: Array, B: Array, rJ: Array, rM: Array) -> Array:
    q = np.zeros(NQ, dtype=float)
    q[block_slice(0)] = 0.5 * (A + rJ)
    q[block_slice(1)] = 0.5 * (B + rJ)
    q[block_slice(2)] = rJ
    q[block_slice(3)] = 0.5 * (rJ + rM)
    q[block_slice(4)] = rM
    return q


def default_hanging_guess(model: ClosedYModel) -> Array:
    A = model.support_A
    B = model.support_B
    axis = B - A
    d = float(np.linalg.norm(axis))
    ex = axis / d
    down = E_Z - float(np.dot(E_Z, ex)) * ex
    norm_down = float(np.linalg.norm(down))
    if norm_down < 1.0e-8:
        raise ValueError(
            "Cannot construct a default hanging guess because the support axis is nearly vertical. "
            "Provide initial_condition.initial_guess explicitly."
        )
    down /= norm_down
    LA = model.params.strings["A"].rest_length
    LB = model.params.strings["B"].rest_length
    aA = (LA**2 - LB**2 + d**2) / (2.0 * d)
    center = A + aA * ex
    h2 = LA**2 - aA**2
    if h2 > 0.0:
        h = math.sqrt(h2)
    else:
        h = max(0.25 * min(LA, LB), 0.05 * d)
    rJ = center + h * down
    rM = rJ + model.params.strings["lower"].rest_length * E_Z
    return straight_node_guess(A, B, rJ, rM)


def minimize_potential(
    model: ClosedYModel,
    q_guess: Array,
    free_indices: Array,
    *,
    tolerance: float = 1.0e-10,
    max_iterations: int = 3000,
) -> tuple[Array, dict[str, Any]]:
    q_base = np.asarray(q_guess, dtype=float).copy()
    free = np.asarray(free_indices, dtype=int)
    if free.ndim != 1 or len(np.unique(free)) != len(free):
        raise ValueError("free_indices must be a one-dimensional array of unique indices.")

    def unpack(x: Array) -> Array:
        q = q_base.copy()
        q[free] = x
        return q

    def fun(x: Array) -> float:
        return model.total_potential(unpack(x))

    def jac(x: Array) -> Array:
        q = unpack(x)
        return -model.conservative_force(q)[free]

    result = minimize(
        fun,
        q_base[free],
        jac=jac,
        method="L-BFGS-B",
        options={"ftol": min(tolerance, 1.0e-15), "gtol": tolerance, "maxiter": max_iterations, "maxls": 50},
    )
    q = unpack(np.asarray(result.x, dtype=float))
    grad_inf = float(np.max(np.abs(jac(result.x)))) if len(free) else 0.0
    info = {
        "success": bool(result.success),
        "status": int(result.status),
        "message": str(result.message),
        "iterations": int(getattr(result, "nit", -1)),
        "function_evaluations": int(getattr(result, "nfev", -1)),
        "potential": float(result.fun),
        "free_gradient_inf_norm": grad_inf,
    }
    if not result.success and grad_inf > max(1.0e-6, 100.0 * tolerance):
        raise RuntimeError(
            "Static initialization failed to converge. "
            f"Optimizer message: {result.message}; free-gradient infinity norm={grad_inf:.3e}. "
            "Provide a better initial guess or measured initial string shape."
        )
    return q, info


def minimum_kinetic_velocity_lift(model: ClosedYModel, vJ: Array, vM: Array) -> Array:
    """Eq. (13.21): minimize total Ritz kinetic energy for known endpoint velocities."""
    known = np.concatenate(
        (
            np.arange(block_slice(2).start, block_slice(2).stop),
            np.arange(block_slice(4).start, block_slice(4).stop),
        )
    )
    unknown = np.array(
        [
            idx
            for block in INTERNAL_BLOCKS
            for idx in range(block_slice(block).start, block_slice(block).stop)
        ],
        dtype=int,
    )
    v = np.zeros(NQ, dtype=float)
    v[block_slice(2)] = vJ
    v[block_slice(4)] = vM
    Muu = model.mass_matrix[np.ix_(unknown, unknown)]
    Muk = model.mass_matrix[np.ix_(unknown, known)]
    v[unknown] = -np.linalg.solve(Muu, Muk @ v[known])
    return v


def ideal_torus_macro_state(
    model: ClosedYModel,
    cfg: Mapping[str, Any],
) -> tuple[Array, Array, dict[str, float]]:
    lengths = cfg.get("working_lengths", {})
    if not isinstance(lengths, Mapping):
        raise ValueError("initial_condition.working_lengths must be an object.")
    sA = _positive(lengths.get("A"), "initial_condition.working_lengths.A")
    sB = _positive(lengths.get("B"), "initial_condition.working_lengths.B")
    ell = _positive(
        lengths.get("lower", lengths.get("ell")),
        "initial_condition.working_lengths.lower",
    )
    A = model.support_A
    B = model.support_B
    axis = B - A
    d = float(np.linalg.norm(axis))
    ex = axis / d
    if abs(float(np.dot(ex, E_Z))) > 1.0e-7:
        raise ValueError(
            "ideal_torus_release requires equal-height supports (support axis horizontal). "
            "For a tilted axis, provide r_J and r_m directly."
        )
    if not abs(sA - sB) < d < sA + sB:
        raise ValueError("working upper lengths violate the strict triangle inequality.")
    aA = (sA**2 - sB**2 + d**2) / (2.0 * d)
    aB = d - aA
    h2 = sA**2 - aA**2
    if h2 <= 0.0:
        raise ValueError("working upper lengths do not produce a positive junction-circle radius.")
    h = math.sqrt(h2)
    C = A + aA * ex
    ey = np.cross(E_Z, ex)
    ey /= np.linalg.norm(ey)
    unit = str(cfg.get("angle_unit", "rad")).lower()
    factor = math.pi / 180.0 if unit in ("deg", "degree", "degrees") else 1.0
    phi = float(cfg.get("phi", 0.0)) * factor
    theta = float(cfg.get("theta", 0.0)) * factor
    phi_dot = float(cfg.get("phi_dot", 0.0)) * factor
    theta_dot = float(cfg.get("theta_dot", 0.0)) * factor
    er = math.sin(theta) * ey + math.cos(theta) * E_Z
    etheta = math.cos(theta) * ey - math.sin(theta) * E_Z
    rJ = C + h * er
    rM = C + ell * math.sin(phi) * ex + (h + ell * math.cos(phi)) * er
    vJ = h * theta_dot * etheta
    vM = (
        ell * math.cos(phi) * phi_dot * ex
        - ell * math.sin(phi) * phi_dot * er
        + (h + ell * math.cos(phi)) * theta_dot * etheta
    )
    reference = {"s_A": sA, "s_B": sB, "ell": ell, "h": h, "a_A": aA, "a_B": aB}
    return np.vstack((rJ, rM)), np.vstack((vJ, vM)), reference


def initialize_state(
    model: ClosedYModel, root: Mapping[str, Any]
) -> tuple[Array, dict[str, Any], dict[str, float] | None]:
    cfg = root.get("initial_condition", {})
    if not isinstance(cfg, Mapping):
        raise ValueError("initial_condition must be a JSON object.")
    mode = str(cfg.get("mode", "ideal_torus_release"))
    init_info: dict[str, Any] = {"mode": mode}
    modal_reference: dict[str, float] | None = None

    if mode == "full_state":
        if "q0" not in cfg or "v0" not in cfg:
            raise ValueError("full_state mode requires q0 and v0.")
        qraw = cfg["q0"]
        vraw = cfg["v0"]
        if isinstance(qraw, Mapping):
            q0 = pack_blocks(qraw, "initial_condition.q0")
        else:
            q0 = np.asarray(qraw, dtype=float).reshape(-1)
        if isinstance(vraw, Mapping):
            v0 = pack_blocks(vraw, "initial_condition.v0")
        else:
            v0 = np.asarray(vraw, dtype=float).reshape(-1)
        if q0.shape != (NQ,) or v0.shape != (NQ,):
            raise ValueError(f"q0 and v0 must each contain {NQ} values.")
        X0 = np.concatenate((q0, v0))
        return X0, init_info, modal_reference

    if mode == "ideal_torus_release":
        macro_pos, macro_vel, modal_reference = ideal_torus_macro_state(model, cfg)
        rJ, rM = macro_pos
        vJ, vM = macro_vel
    elif mode == "fixed_endpoints_static":
        rJ = _array3(cfg.get("junction_position"), "initial_condition.junction_position")
        rM = _array3(cfg.get("bob_position"), "initial_condition.bob_position")
        vJ = _array3(cfg.get("junction_velocity", [0.0, 0.0, 0.0]),
                     "initial_condition.junction_velocity")
        vM = _array3(cfg.get("bob_velocity", [0.0, 0.0, 0.0]),
                     "initial_condition.bob_velocity")
    elif mode == "static_equilibrium":
        guess_cfg = cfg.get("initial_guess")
        if isinstance(guess_cfg, Mapping):
            q_guess = pack_blocks(guess_cfg, "initial_condition.initial_guess")
        else:
            q_guess = default_hanging_guess(model)
        free = np.arange(NQ, dtype=int)
        q0, opt_info = minimize_potential(
            model,
            q_guess,
            free,
            tolerance=float(cfg.get("relax_tolerance", 1.0e-10)),
            max_iterations=int(cfg.get("relax_max_iterations", 4000)),
        )
        init_info["relaxation"] = opt_info
        v0 = np.zeros(NQ, dtype=float)
        return np.concatenate((q0, v0)), init_info, modal_reference
    else:
        raise ValueError(
            "Unknown initial_condition.mode. Supported modes: full_state, "
            "ideal_torus_release, fixed_endpoints_static, static_equilibrium."
        )

    q_guess = straight_node_guess(model.support_A, model.support_B, rJ, rM)
    if bool(cfg.get("relax_internal_nodes", True)):
        free = np.array(
            [
                idx
                for block in INTERNAL_BLOCKS
                for idx in range(block_slice(block).start, block_slice(block).stop)
            ],
            dtype=int,
        )
        q0, opt_info = minimize_potential(
            model,
            q_guess,
            free,
            tolerance=float(cfg.get("relax_tolerance", 1.0e-10)),
            max_iterations=int(cfg.get("relax_max_iterations", 3000)),
        )
        init_info["relaxation"] = opt_info
    else:
        q0 = q_guess
        init_info["relaxation"] = {"performed": False}

    velocity_mode = str(cfg.get("internal_velocity", "minimum_kinetic"))
    if velocity_mode == "minimum_kinetic":
        v0 = minimum_kinetic_velocity_lift(model, vJ, vM)
    elif velocity_mode == "affine":
        v0 = np.zeros(NQ)
        v0[block_slice(0)] = 0.5 * vJ
        v0[block_slice(1)] = 0.5 * vJ
        v0[block_slice(2)] = vJ
        v0[block_slice(3)] = 0.5 * (vJ + vM)
        v0[block_slice(4)] = vM
    else:
        raise ValueError("internal_velocity must be 'minimum_kinetic' or 'affine'.")
    return np.concatenate((q0, v0)), init_info, modal_reference


def integrate_model(
    model: ClosedYModel,
    X0: Array,
    root: Mapping[str, Any],
) -> tuple[Any, dict[str, Any]]:
    cfg = root.get("integration", {})
    if not isinstance(cfg, Mapping):
        raise ValueError("integration must be a JSON object.")
    t_end = _positive(cfg.get("t_end", 10.0), "integration.t_end")
    output_dt = _positive(cfg.get("output_dt", 0.01), "integration.output_dt")
    n = int(math.floor(t_end / output_dt + 1.0e-12))
    t_eval = output_dt * np.arange(n + 1, dtype=float)
    if t_eval[-1] < t_end - 1.0e-12:
        t_eval = np.append(t_eval, t_end)
    else:
        t_eval[-1] = t_end
    method = str(cfg.get("method", "Radau"))
    rtol = _positive(cfg.get("rtol", 1.0e-8), "integration.rtol")
    atol = _positive(cfg.get("atol", 1.0e-10), "integration.atol")
    max_step = float(cfg.get("max_step", np.inf))
    if not (math.isfinite(max_step) and max_step > 0.0):
        max_step = np.inf

    events: list[Any] = []
    event_names: list[str] = []
    max_strain = cfg.get("max_strain")
    if max_strain is not None:
        limit = _positive(max_strain, "integration.max_strain")

        def strain_event(_t: float, X: Array, limit: float = limit) -> float:
            return limit - model.max_quadrature_strain(X[:NQ])

        strain_event.terminal = True
        strain_event.direction = -1.0
        events.append(strain_event)
        event_names.append("maximum_strain_limit")

    max_radius = cfg.get("max_coordinate_radius")
    if max_radius is not None:
        radius_limit = _positive(max_radius, "integration.max_coordinate_radius")

        def radius_event(_t: float, X: Array, limit: float = radius_limit) -> float:
            q = X[:NQ]
            blocks = q.reshape(N_BLOCKS, 3)
            return limit - float(np.max(np.linalg.norm(blocks, axis=1)))

        radius_event.terminal = True
        radius_event.direction = -1.0
        events.append(radius_event)
        event_names.append("coordinate_radius_limit")

    sol = solve_ivp(
        model.rhs,
        (0.0, t_end),
        np.asarray(X0, dtype=float),
        method=method,
        t_eval=t_eval,
        rtol=rtol,
        atol=atol,
        max_step=max_step,
        events=events if events else None,
        dense_output=False,
        vectorized=False,
    )
    event_records: list[dict[str, Any]] = []
    if events:
        for name, times in zip(event_names, sol.t_events):
            if len(times):
                event_records.append({"name": name, "time": float(times[0])})
    info = {
        "success": bool(sol.success),
        "status": int(sol.status),
        "message": str(sol.message),
        "method": method,
        "rtol": rtol,
        "atol": atol,
        "max_step": None if not math.isfinite(max_step) else max_step,
        "requested_t_end": t_end,
        "actual_t_end": float(sol.t[-1]) if len(sol.t) else 0.0,
        "n_output": int(len(sol.t)),
        "nfev": int(sol.nfev),
        "njev": int(getattr(sol, "njev", 0)),
        "nlu": int(getattr(sol, "nlu", 0)),
        "events": event_records,
    }
    if not sol.success:
        raise RuntimeError(f"ODE integration failed: {sol.message}")
    return sol, info


def modal_reference_geometry(model: ClosedYModel, ref: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if ref is None:
        return None
    try:
        sA = float(ref.get("s_A", ref.get("A")))
        sB = float(ref.get("s_B", ref.get("B")))
        ell = float(ref.get("ell", ref.get("lower")))
    except (TypeError, ValueError):
        return None
    A = model.support_A
    B = model.support_B
    axis = B - A
    d = float(np.linalg.norm(axis))
    ex = axis / d
    if abs(float(np.dot(ex, E_Z))) > 1.0e-6:
        return None
    aA = (sA**2 - sB**2 + d**2) / (2.0 * d)
    h2 = sA**2 - aA**2
    if h2 <= 0.0:
        return None
    h = math.sqrt(h2)
    C = A + aA * ex
    ey = np.cross(E_Z, ex)
    ey /= np.linalg.norm(ey)
    return {"s_A": sA, "s_B": sB, "ell": ell, "h": h, "C": C, "e_x": ex, "e_y": ey}


def extract_modal_coordinates(rM: Array, geom: Mapping[str, Any] | None) -> tuple[float, float]:
    if geom is None:
        return math.nan, math.nan
    rel = rM - np.asarray(geom["C"], dtype=float)
    ex = np.asarray(geom["e_x"], dtype=float)
    ey = np.asarray(geom["e_y"], dtype=float)
    X = float(np.dot(rel, ex))
    radial = rel - X * ex
    radial_norm = float(np.linalg.norm(radial))
    phi = math.atan2(X, radial_norm - float(geom["h"]))
    theta = math.atan2(float(np.dot(radial, ey)), float(np.dot(radial, E_Z)))
    return phi, theta


def compute_outputs(
    model: ClosedYModel,
    sol: Any,
    root: Mapping[str, Any],
    modal_ref: Mapping[str, Any] | None,
) -> dict[str, Any]:
    output_cfg = root.get("output", {})
    if not isinstance(output_cfg, Mapping):
        raise ValueError("output must be a JSON object.")
    n_samples = int(output_cfg.get("string_samples", 31))
    if n_samples < 3:
        raise ValueError("output.string_samples must be at least 3.")
    xi = np.linspace(0.0, 1.0, n_samples)
    t = np.asarray(sol.t, dtype=float)
    states = np.asarray(sol.y.T, dtype=float)
    q_hist = states[:, :NQ]
    v_hist = states[:, NQ:]
    nt = len(t)
    a_hist = np.empty_like(q_hist)
    energy_keys = (
        "kinetic",
        "potential_gravity",
        "potential_axial",
        "potential_bending",
        "potential_buoyancy",
        "potential_external",
        "potential_centrifugal",
        "potential_total",
        "mechanical_total",
    )
    energy = {key: np.empty(nt, dtype=float) for key in energy_keys}
    noncons_power = np.empty(nt, dtype=float)
    branch_data: dict[str, dict[str, Array]] = {}
    for name in model.branches:
        branch_data[name] = {
            "position": np.empty((nt, n_samples, 3), dtype=float),
            "velocity": np.empty((nt, n_samples, 3), dtype=float),
            "stretch": np.empty((nt, n_samples), dtype=float),
            "strain": np.empty((nt, n_samples), dtype=float),
            "stretch_rate": np.empty((nt, n_samples), dtype=float),
            "tension": np.empty((nt, n_samples), dtype=float),
            "curvature": np.empty((nt, n_samples), dtype=float),
        }
    phi = np.full(nt, np.nan)
    theta = np.full(nt, np.nan)
    geom = modal_reference_geometry(model, modal_ref)
    for k in range(nt):
        q = q_hist[k]
        v = v_hist[k]
        a_hist[k] = model.acceleration(q, v)
        ec = model.energy_components(q, v)
        for key in energy_keys:
            energy[key][k] = ec[key]
        noncons_power[k] = model.nonconservative_power(q, v)
        for name in model.branches:
            sampled = model.sample_branch(name, q, v, xi)
            for key in branch_data[name]:
                branch_data[name][key][k] = sampled[key]
        phi[k], theta[k] = extract_modal_coordinates(q[block_slice(4)], geom)
    return {
        "time": t,
        "state": states,
        "q": q_hist,
        "v": v_hist,
        "a": a_hist,
        "xi": xi,
        "branches": branch_data,
        "energy": energy,
        "nonconservative_power": noncons_power,
        "phi": phi,
        "theta": theta,
        "modal_reference": geom,
    }


def _state_component_names(prefix: str = "") -> list[str]:
    axes = ("x", "y", "z")
    names: list[str] = []
    for block in BLOCK_NAMES:
        for axis in axes:
            names.append(f"{prefix}{block}_{axis}")
    return names


def write_results(
    model: ClosedYModel,
    outputs: Mapping[str, Any],
    root: Mapping[str, Any],
    output_dir: Path,
    input_source: str,
    initialization_info: Mapping[str, Any],
    integration_info: Mapping[str, Any],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    _json_dump(output_dir / "input_config.json", root)
    t = outputs["time"]
    q = outputs["q"]
    v = outputs["v"]
    a = outputs["a"]
    energy = outputs["energy"]
    branches = outputs["branches"]
    phi = outputs["phi"]
    theta = outputs["theta"]

    npz_payload: dict[str, Any] = {
        "time": t,
        "q": q,
        "v": v,
        "a": a,
        "state": outputs["state"],
        "xi": outputs["xi"],
        "phi": phi,
        "theta": theta,
        "nonconservative_power": outputs["nonconservative_power"],
        "mass_matrix": model.mass_matrix,
    }
    for key, arr in energy.items():
        npz_payload[f"energy_{key}"] = arr
    for branch_name, data in branches.items():
        for key, arr in data.items():
            npz_payload[f"{branch_name}_{key}"] = arr
    np.savez_compressed(output_dir / "full_motion_state.npz", **npz_payload)

    header = ["time"] + _state_component_names() + _state_component_names("v_") + _state_component_names("a_")
    header += [
        "phi",
        "theta",
        "energy_kinetic",
        "energy_potential_total",
        "energy_mechanical_total",
        "nonconservative_power",
    ]
    for branch_name in ("A", "B", "lower"):
        header += [
            f"{branch_name}_tension_min",
            f"{branch_name}_tension_max",
            f"{branch_name}_taut_fraction",
            f"{branch_name}_strain_min",
            f"{branch_name}_strain_max",
        ]

    csv_path = output_dir / "state_summary.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for k in range(len(t)):
            row: list[float] = [float(t[k])]
            row.extend(q[k].tolist())
            row.extend(v[k].tolist())
            row.extend(a[k].tolist())
            row.extend(
                [
                    float(phi[k]),
                    float(theta[k]),
                    float(energy["kinetic"][k]),
                    float(energy["potential_total"][k]),
                    float(energy["mechanical_total"][k]),
                    float(outputs["nonconservative_power"][k]),
                ]
            )
            for branch_name in ("A", "B", "lower"):
                tension = branches[branch_name]["tension"][k]
                strain = branches[branch_name]["strain"][k]
                row.extend(
                    [
                        float(np.min(tension)),
                        float(np.max(tension)),
                        float(np.mean(tension > 0.0)),
                        float(np.min(strain)),
                        float(np.max(strain)),
                    ]
                )
            writer.writerow(row)

    e0 = float(energy["mechanical_total"][0])
    ef = float(energy["mechanical_total"][-1])
    scale = max(abs(e0), 1.0e-12)
    branch_summary: dict[str, Any] = {}
    for name in ("A", "B", "lower"):
        tension = branches[name]["tension"]
        strain = branches[name]["strain"]
        branch_summary[name] = {
            "tension_min": float(np.min(tension)),
            "tension_max": float(np.max(tension)),
            "strain_min": float(np.min(strain)),
            "strain_max": float(np.max(strain)),
            "minimum_taut_fraction": float(np.min(np.mean(tension > 0.0, axis=1))),
            "ever_fully_slack_on_sample_grid": bool(np.any(np.all(tension <= 0.0, axis=1))),
        }

    summary = {
        "program": {
            "name": "Y-Pendulum quadratic Ritz closed-theory solver",
            "version": PROGRAM_VERSION,
            "implemented_theory": "Section 13, Eqs. (13.2)-(13.18), fixed supports and point bob",
            "state_dimension": NX,
            "generalized_coordinate_dimension": NQ,
            "input_source": input_source,
        },
        "initialization": dict(initialization_info),
        "integration": dict(integration_info),
        "mass_matrix": {
            "minimum_eigenvalue": float(np.min(model.mass_eigenvalues)),
            "maximum_eigenvalue": float(np.max(model.mass_eigenvalues)),
            "condition_number": float(np.linalg.cond(model.mass_matrix)),
        },
        "energy": {
            "initial": e0,
            "final": ef,
            "relative_change": (ef - e0) / scale,
            "minimum_nonconservative_power": float(np.min(outputs["nonconservative_power"])),
            "maximum_nonconservative_power": float(np.max(outputs["nonconservative_power"])),
        },
        "branches": branch_summary,
        "files": {
            "full_state": "full_motion_state.npz",
            "summary_csv": "state_summary.csv",
            "configuration": "input_config.json",
        },
    }
    _json_dump(output_dir / "run_summary.json", summary)

    output_cfg = root.get("output", {}) or {}
    if bool(output_cfg.get("plots", True)):
        try:
            write_plots(outputs, output_dir)
            summary["files"]["plots"] = [
                "trajectory_xy.png",
                "bob_coordinates.png",
                "tension_envelopes.png",
                "energy_balance.png",
            ]
            _json_dump(output_dir / "run_summary.json", summary)
        except ImportError:
            summary["plot_warning"] = "matplotlib is not installed; numerical outputs were written."
            _json_dump(output_dir / "run_summary.json", summary)

    animation_cfg = output_cfg.get("animation_3d", {}) or {}
    if not isinstance(animation_cfg, Mapping):
        raise ValueError("output.animation_3d must be a JSON/Python object.")
    if bool(animation_cfg.get("enabled", False)):
        try:
            animation_info = write_top_view_animation(
                model, outputs, output_dir, animation_cfg
            )
            summary["animation_3d"] = animation_info
            summary["files"]["animation_3d"] = animation_info["filename"]
            _json_dump(output_dir / "run_summary.json", summary)
        except Exception as exc:
            if bool(animation_cfg.get("fail_on_error", False)):
                raise
            summary["animation_warning"] = f"Animation was not written: {type(exc).__name__}: {exc}"
            _json_dump(output_dir / "run_summary.json", summary)
    return summary


def write_plots(outputs: Mapping[str, Any], output_dir: Path) -> None:
    import matplotlib.pyplot as plt

    t = outputs["time"]
    q = outputs["q"]
    rM = q[:, block_slice(4)]
    branches = outputs["branches"]
    energy = outputs["energy"]

    plt.figure()
    plt.plot(rM[:, 0], rM[:, 1])
    plt.xlabel("bob x [m]")
    plt.ylabel("bob y [m]")
    plt.axis("equal")
    plt.tight_layout()
    plt.savefig(output_dir / "trajectory_xy.png", dpi=180)
    plt.close()

    plt.figure()
    plt.plot(t, rM[:, 0], label="x")
    plt.plot(t, rM[:, 1], label="y")
    plt.plot(t, rM[:, 2], label="z (down)")
    plt.xlabel("time [s]")
    plt.ylabel("bob coordinate [m]")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "bob_coordinates.png", dpi=180)
    plt.close()

    plt.figure()
    for name in ("A", "B", "lower"):
        tension = branches[name]["tension"]
        plt.plot(t, np.max(tension, axis=1), label=f"{name}: max")
        plt.plot(t, np.min(tension, axis=1), linestyle="--", label=f"{name}: min")
    plt.xlabel("time [s]")
    plt.ylabel("local axial tension [N]")
    plt.legend(ncol=2)
    plt.tight_layout()
    plt.savefig(output_dir / "tension_envelopes.png", dpi=180)
    plt.close()

    plt.figure()
    plt.plot(t, energy["mechanical_total"], label="mechanical energy")
    plt.plot(t, energy["kinetic"], label="kinetic")
    plt.plot(t, energy["potential_total"], label="potential")
    plt.xlabel("time [s]")
    plt.ylabel("energy [J]")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "energy_balance.png", dpi=180)
    plt.close()


def _interpolate_history(time: Array, values: Array, target_time: Array) -> Array:
    """Linearly interpolate an arbitrary time-first array onto target_time."""
    t = np.asarray(time, dtype=float)
    y = np.asarray(values, dtype=float)
    target = np.asarray(target_time, dtype=float)
    if y.shape[0] != len(t):
        raise ValueError("The first axis of an animation history must match the time array.")
    flat = y.reshape(len(t), -1)
    out = np.empty((len(target), flat.shape[1]), dtype=float)
    for j in range(flat.shape[1]):
        out[:, j] = np.interp(target, t, flat[:, j])
    return out.reshape((len(target),) + y.shape[1:])


def _top_camera_basis(model: ClosedYModel, camera_distance: float) -> dict[str, Array | float]:
    """Build the physically consistent top camera requested by the user.

    z is positive downward.  The optical centre is camera_distance above the
    midpoint of the two supports, and the optical axis intersects the apparatus
    at that midpoint.  Thus the midpoint is the image principal point, not the
    optical centre itself.
    """
    distance = _positive(camera_distance, "output.animation_3d.perspective.camera_distance")
    A = np.asarray(model.support_A, dtype=float)
    B = np.asarray(model.support_B, dtype=float)
    principal = 0.5 * (A + B)
    support_axis = B - A
    horizontal_axis = support_axis - float(np.dot(support_axis, E_Z)) * E_Z
    norm = float(np.linalg.norm(horizontal_axis))
    if norm <= 1.0e-12:
        horizontal_axis = np.array([1.0, 0.0, 0.0], dtype=float)
    else:
        horizontal_axis /= norm
    transverse_axis = np.cross(E_Z, horizontal_axis)
    transverse_axis /= np.linalg.norm(transverse_axis)
    camera_center = principal - distance * E_Z
    return {
        "principal": principal,
        "camera_center": camera_center,
        "u": horizontal_axis,
        "v": transverse_axis,
        "view": E_Z.copy(),
        "distance": distance,
    }


def _project_top_camera(
    points: Array,
    camera: Mapping[str, Any],
    perspective_enabled: bool,
) -> tuple[Array, Array, Array]:
    """Project 3D points through the top camera.

    In perspective mode the image plane is chosen through the support midpoint,
    so points in the support-midpoint plane retain unit scale.  Depth below that
    plane produces the physically correct pinhole contraction toward the
    principal point.
    """
    pts = np.asarray(points, dtype=float)
    if pts.shape[-1] != 3:
        raise ValueError("Camera projection expects the last array dimension to be 3.")
    principal = np.asarray(camera["principal"], dtype=float)
    u = np.asarray(camera["u"], dtype=float)
    v = np.asarray(camera["v"], dtype=float)
    distance = float(camera["distance"])
    rel = pts - principal
    x = np.einsum("...i,i->...", rel, u)
    y = np.einsum("...i,i->...", rel, v)
    depth = distance + np.einsum("...i,i->...", rel, E_Z)
    if perspective_enabled:
        minimum_depth = float(np.min(depth))
        if minimum_depth <= max(1.0e-9, 1.0e-8 * distance):
            raise ValueError(
                "At least one animated point lies on or behind the top camera. "
                "Increase output.animation_3d.perspective.camera_distance. "
                f"Minimum camera depth={minimum_depth:.6g} m."
            )
        scale = distance / depth
        x = x * scale
        y = y * scale
    else:
        scale = np.ones_like(depth)
    return np.stack((x, y), axis=-1), depth, scale


def write_top_view_animation(
    model: ClosedYModel,
    outputs: Mapping[str, Any],
    output_dir: Path,
    animation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    """Render a top-view animation from the solved 3D Ritz state.

    This is a camera rendering of the already solved 15-coordinate closed
    theory.  It does not introduce any additional mechanical simulation.
    """
    import matplotlib.pyplot as plt
    from matplotlib.animation import FFMpegWriter, FuncAnimation, PillowWriter

    fps = int(animation_cfg.get("fps", 30))
    if fps <= 0:
        raise ValueError("output.animation_3d.fps must be a positive integer.")
    playback_speed = _positive(
        animation_cfg.get("playback_speed", 1.0),
        "output.animation_3d.playback_speed",
    )
    dpi = int(animation_cfg.get("dpi", 150))
    if dpi <= 0:
        raise ValueError("output.animation_3d.dpi must be positive.")
    figure_size = np.asarray(
        animation_cfg.get("figure_size_inches", [7.0, 7.0]), dtype=float
    )
    if figure_size.shape != (2,) or np.any(figure_size <= 0.0):
        raise ValueError("output.animation_3d.figure_size_inches must contain two positive values.")
    max_frames = int(animation_cfg.get("max_frames", 900))
    if max_frames < 2:
        raise ValueError("output.animation_3d.max_frames must be at least 2.")
    trail_seconds = _nonnegative(
        animation_cfg.get("trail_seconds", 1.0),
        "output.animation_3d.trail_seconds",
    )
    margin_fraction = _nonnegative(
        animation_cfg.get("margin_fraction", 0.08),
        "output.animation_3d.margin_fraction",
    )
    line_width = _positive(
        animation_cfg.get("line_width", 2.2), "output.animation_3d.line_width"
    )
    support_marker_size = _positive(
        animation_cfg.get("support_marker_size", 7.0),
        "output.animation_3d.support_marker_size",
    )
    junction_marker_size = _positive(
        animation_cfg.get("junction_marker_size", 6.0),
        "output.animation_3d.junction_marker_size",
    )
    bob_marker_size = _positive(
        animation_cfg.get("bob_marker_size", 10.0),
        "output.animation_3d.bob_marker_size",
    )

    perspective_cfg = animation_cfg.get("perspective", {}) or {}
    if not isinstance(perspective_cfg, Mapping):
        raise ValueError("output.animation_3d.perspective must be an object.")
    perspective_enabled = bool(perspective_cfg.get("enabled", False))
    principal_spec = str(perspective_cfg.get("principal_point", "support_midpoint"))
    if principal_spec != "support_midpoint":
        raise ValueError(
            "The current top-camera closure fixes perspective.principal_point to "
            "'support_midpoint', as required by the model contract."
        )
    camera = _top_camera_basis(
        model, float(perspective_cfg.get("camera_distance", 1.5))
    )

    time = np.asarray(outputs["time"], dtype=float)
    if len(time) < 2 or not np.all(np.diff(time) > 0.0):
        raise ValueError("Animation requires at least two strictly increasing output times.")
    duration = float(time[-1] - time[0])
    requested_frames = max(2, int(math.ceil(duration * fps / playback_speed)) + 1)
    frame_count = min(requested_frames, max_frames)
    frame_time = np.linspace(time[0], time[-1], frame_count)
    video_duration = (frame_count - 1) / fps
    actual_playback_speed = duration / video_duration if video_duration > 0.0 else math.inf

    branch_world: dict[str, Array] = {}
    branch_image: dict[str, Array] = {}
    branch_depth: dict[str, Array] = {}
    for name in ("A", "B", "lower"):
        world = _interpolate_history(
            time, np.asarray(outputs["branches"][name]["position"], dtype=float), frame_time
        )
        image, depth, _ = _project_top_camera(world, camera, perspective_enabled)
        branch_world[name] = world
        branch_image[name] = image
        branch_depth[name] = depth

    q_frame = _interpolate_history(time, np.asarray(outputs["q"], dtype=float), frame_time)
    rJ_world = q_frame[:, block_slice(2)]
    rM_world = q_frame[:, block_slice(4)]
    rJ_image, rJ_depth, rJ_scale = _project_top_camera(
        rJ_world, camera, perspective_enabled
    )
    rM_image, rM_depth, rM_scale = _project_top_camera(
        rM_world, camera, perspective_enabled
    )
    support_world = np.vstack((model.support_A, model.support_B))
    support_image, _, _ = _project_top_camera(
        support_world, camera, perspective_enabled
    )

    all_image_points = [support_image, rJ_image, rM_image]
    all_image_points.extend(branch_image[name].reshape(-1, 2) for name in ("A", "B", "lower"))
    all_points = np.concatenate(all_image_points, axis=0)
    if not np.all(np.isfinite(all_points)):
        raise FloatingPointError("Animation projection produced a non-finite coordinate.")
    xmin, ymin = np.min(all_points, axis=0)
    xmax, ymax = np.max(all_points, axis=0)
    span = max(float(xmax - xmin), float(ymax - ymin), 1.0e-6)
    margin = max(margin_fraction * span, 1.0e-4)
    xmid = 0.5 * float(xmin + xmax)
    ymid = 0.5 * float(ymin + ymax)
    half = 0.5 * span + margin

    fig, ax = plt.subplots(figsize=tuple(figure_size.tolist()))
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(xmid - half, xmid + half)
    ax.set_ylim(ymid - half, ymid + half)
    ax.set_xlabel("coordinate along upper-support axis [m]")
    ax.set_ylabel("horizontal transverse coordinate [m]")
    ax.grid(True, alpha=0.25)
    projection_name = "pinhole perspective" if perspective_enabled else "orthographic"
    ax.set_title(f"Y-pendulum 3D state: top camera ({projection_name})")

    line_A, = ax.plot([], [], linewidth=line_width, label="upper A")
    line_B, = ax.plot([], [], linewidth=line_width, label="upper B")
    line_lower, = ax.plot([], [], linewidth=line_width, label="lower")
    trail_line, = ax.plot([], [], linewidth=1.0, alpha=0.55, label="bob trail")
    support_points, = ax.plot(
        support_image[:, 0], support_image[:, 1], "o", markersize=support_marker_size,
        linestyle="None", label="supports"
    )
    junction_point, = ax.plot(
        [], [], "o", markersize=junction_marker_size, linestyle="None", label="junction"
    )
    bob_point, = ax.plot(
        [], [], "o", markersize=bob_marker_size, linestyle="None", label="bob"
    )
    if bool(animation_cfg.get("show_principal_point", True)):
        ax.plot([0.0], [0.0], marker="+", markersize=8.0, linestyle="None", label="principal point")
    show_time = bool(animation_cfg.get("show_time", True))
    time_text = ax.text(0.02, 0.97, "", transform=ax.transAxes, va="top")
    ax.legend(loc="upper right", fontsize="small", ncol=2)

    def update(frame: int) -> tuple[Any, ...]:
        line_A.set_data(branch_image["A"][frame, :, 0], branch_image["A"][frame, :, 1])
        line_B.set_data(branch_image["B"][frame, :, 0], branch_image["B"][frame, :, 1])
        line_lower.set_data(
            branch_image["lower"][frame, :, 0], branch_image["lower"][frame, :, 1]
        )
        junction_point.set_data([rJ_image[frame, 0]], [rJ_image[frame, 1]])
        bob_point.set_data([rM_image[frame, 0]], [rM_image[frame, 1]])
        junction_point.set_markersize(
            junction_marker_size * float(np.clip(rJ_scale[frame], 0.35, 3.0))
        )
        bob_point.set_markersize(
            bob_marker_size * float(np.clip(rM_scale[frame], 0.35, 3.0))
        )
        if trail_seconds > 0.0:
            start = int(np.searchsorted(frame_time, frame_time[frame] - trail_seconds, side="left"))
            trail_line.set_data(
                rM_image[start : frame + 1, 0], rM_image[start : frame + 1, 1]
            )
        else:
            trail_line.set_data([], [])
        time_text.set_text(f"t = {frame_time[frame]:.3f} s" if show_time else "")
        return (
            line_A,
            line_B,
            line_lower,
            trail_line,
            support_points,
            junction_point,
            bob_point,
            time_text,
        )

    animation = FuncAnimation(
        fig,
        update,
        frames=frame_count,
        interval=1000.0 / fps,
        blit=False,
        repeat=False,
    )

    requested_format = str(animation_cfg.get("format", "mp4")).lower().lstrip(".")
    if requested_format not in ("mp4", "gif"):
        raise ValueError("output.animation_3d.format must be 'mp4' or 'gif'.")
    filename = str(
        animation_cfg.get(
            "filename", f"y_pendulum_3d_top_view.{requested_format}"
        )
    )
    output_path = output_dir / filename
    if output_path.suffix.lower() != f".{requested_format}":
        output_path = output_path.with_suffix(f".{requested_format}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    actual_format = requested_format
    try:
        if requested_format == "mp4":
            if not FFMpegWriter.isAvailable() and shutil.which("ffmpeg") is None:
                if not bool(animation_cfg.get("fallback_to_gif", True)):
                    raise RuntimeError(
                        "FFmpeg is not available, so MP4 animation cannot be written."
                    )
                actual_format = "gif"
                output_path = output_path.with_suffix(".gif")
                writer = PillowWriter(fps=fps)
            else:
                bitrate = int(animation_cfg.get("bitrate_kbps", 2400))
                writer = FFMpegWriter(
                    fps=fps,
                    bitrate=bitrate,
                    metadata={
                        "title": "Y-pendulum closed-theory top-view 3D animation",
                        "artist": "y_pendulum_closed.py",
                    },
                )
        else:
            writer = PillowWriter(fps=fps)
        animation.save(output_path, writer=writer, dpi=dpi)
    finally:
        plt.close(fig)

    return {
        "filename": output_path.name,
        "format": actual_format,
        "projection": projection_name,
        "perspective_enabled": perspective_enabled,
        "principal_point_world": np.asarray(camera["principal"], dtype=float).tolist(),
        "camera_center_world": np.asarray(camera["camera_center"], dtype=float).tolist(),
        "camera_distance": float(camera["distance"]),
        "fps": fps,
        "frame_count": frame_count,
        "simulation_duration": duration,
        "video_duration": video_duration,
        "requested_playback_speed": playback_speed,
        "actual_playback_speed": actual_playback_speed,
        "maximum_bob_camera_depth": float(np.max(rM_depth)),
        "minimum_bob_camera_depth": float(np.min(rM_depth)),
    }


def self_test(verbose: bool = True) -> dict[str, float]:
    """Deterministic mathematical checks of the theory implementation."""
    cfg = example_configuration()
    # Use nonzero bending to exercise its analytic gradient.
    for key in ("A", "B", "lower"):
        cfg["model"]["strings"][key]["EI"] = 2.0e-6
        cfg["model"]["strings"][key]["etaA"] = 0.0
        cfg["model"]["strings"][key]["drag"] = {}
    cfg["model"]["bob"]["drag"] = {}
    cfg["model"]["junction_drag"] = {}
    params = ModelParameters.from_config(cfg)
    model = ClosedYModel(params, quadrature_order=12)

    # Check the analytic local consistent mass matrix.
    xg, wg = np.polynomial.legendre.leggauss(20)
    xi = 0.5 * (xg + 1.0)
    w = 0.5 * wg
    N, _, _ = shape_functions(xi)
    numeric = np.einsum("k,ka,kb->ab", w, N, N)
    exact = np.array([[4, 2, -1], [2, 16, 2], [-1, 2, 4]], dtype=float) / 30.0
    mass_shape_error = float(np.max(np.abs(numeric - exact)))

    # Check explicit global mass matrix against generic B^T B assembly.
    generic = np.zeros((NQ, NQ), dtype=float)
    for branch in model.branches.values():
        generic += branch.params.mass * np.einsum(
            "k,kij,kil->jl", branch.weights, branch.B, branch.B
        )
    generic[block_slice(2), block_slice(2)] += params.junction_mass * np.eye(3)
    generic[block_slice(4), block_slice(4)] += params.bob.mass * np.eye(3)
    added = params.bob.added_mass_coefficient * params.air_density * params.bob.volume
    generic[block_slice(4), block_slice(4)] += added * np.eye(3)
    global_mass_error = float(np.max(np.abs(generic - model.mass_matrix)))

    # Build a smooth, taut, slightly curved test state.
    macro_pos, _, _ = ideal_torus_macro_state(model, cfg["initial_condition"])
    rJ, rM = macro_pos
    q = straight_node_guess(model.support_A, model.support_B, rJ, rM)
    q[block_slice(0)] += np.array([0.001, 0.0015, -0.0005])
    q[block_slice(1)] += np.array([-0.001, -0.001, 0.0007])
    q[block_slice(3)] += np.array([0.0005, -0.0012, 0.0008])

    # Finite-difference check: conservative force = -grad total potential.
    h = 2.0e-7
    grad_fd = np.empty(NQ)
    for j in range(NQ):
        dq = np.zeros(NQ)
        dq[j] = h
        grad_fd[j] = (model.total_potential(q + dq) - model.total_potential(q - dq)) / (2.0 * h)
    force = model.conservative_force(q)
    force_gradient_error = float(
        np.linalg.norm(force + grad_fd) / max(np.linalg.norm(grad_fd), 1.0)
    )

    # Dissipative power must not be positive for a random velocity when no external drive exists.
    rng = np.random.default_rng(20260818)
    v = 0.03 * rng.standard_normal(NQ)
    # Restore axial viscosity and point drag in a separate model.
    dissipative_cfg = example_configuration()
    dissipative_model = ClosedYModel(ModelParameters.from_config(dissipative_cfg), 10)
    dissipative_power = dissipative_model.nonconservative_power(q, v)

    # Check the top-camera geometry used by the 3D-scene animation.
    camera = _top_camera_basis(model, 1.5)
    principal = np.asarray(camera["principal"], dtype=float)
    projected_principal, _, _ = _project_top_camera(
        principal[None, :], camera, perspective_enabled=True
    )
    principal_point_error = float(np.linalg.norm(projected_principal[0]))
    test_point = principal + 0.1 * np.asarray(camera["u"]) + 0.2 * E_Z
    projected_test, _, _ = _project_top_camera(
        test_point[None, :], camera, perspective_enabled=True
    )
    expected_test_x = 0.1 * 1.5 / (1.5 + 0.2)
    perspective_projection_error = abs(float(projected_test[0, 0]) - expected_test_x)

    results = {
        "mass_shape_integral_max_error": mass_shape_error,
        "global_mass_assembly_max_error": global_mass_error,
        "conservative_force_relative_gradient_error": force_gradient_error,
        "sample_nonconservative_power": float(dissipative_power),
        "minimum_mass_eigenvalue": float(np.min(model.mass_eigenvalues)),
        "camera_principal_point_projection_error": principal_point_error,
        "camera_perspective_projection_error": perspective_projection_error,
    }
    if mass_shape_error > 1.0e-13:
        raise AssertionError(f"Shape mass integration test failed: {mass_shape_error:.3e}")
    if global_mass_error > 1.0e-13:
        raise AssertionError(f"Global mass assembly test failed: {global_mass_error:.3e}")
    if force_gradient_error > 3.0e-5:
        raise AssertionError(
            f"Conservative force/potential gradient test failed: {force_gradient_error:.3e}"
        )
    if dissipative_power > 1.0e-10:
        raise AssertionError(f"Dissipation test failed: power={dissipative_power:.3e}")
    if principal_point_error > 1.0e-14:
        raise AssertionError(
            f"Camera principal-point test failed: {principal_point_error:.3e}"
        )
    if perspective_projection_error > 1.0e-14:
        raise AssertionError(
            f"Camera perspective-projection test failed: {perspective_projection_error:.3e}"
        )
    if verbose:
        print(json.dumps(results, indent=2))
        print("Self-test passed.")
    return results


def example_configuration() -> dict[str, Any]:
    """Return an independent copy of the single user-editable input block."""
    return copy.deepcopy(USER_INPUTS)


def run_from_mapping(
    root: Mapping[str, Any],
    *,
    base_directory: Path,
    input_source: str,
    output_override: Path | None = None,
) -> dict[str, Any]:
    """Run the solver from an already assembled configuration mapping."""
    root_copy = copy.deepcopy(dict(root))
    params = ModelParameters.from_config(root_copy)
    integration_cfg = root_copy.get("integration", {}) or {}
    quadrature_order = int(integration_cfg.get("quadrature_order", 10))
    model = ClosedYModel(params, quadrature_order=quadrature_order)
    X0, init_info, init_modal_ref = initialize_state(model, root_copy)
    sol, integ_info = integrate_model(model, X0, root_copy)
    output_cfg = root_copy.get("output", {}) or {}
    configured_ref = output_cfg.get("modal_reference") if isinstance(output_cfg, Mapping) else None
    modal_ref = configured_ref or init_modal_ref
    outputs = compute_outputs(model, sol, root_copy, modal_ref)
    if output_override is not None:
        output_dir = output_override
    else:
        output_dir = Path(str(output_cfg.get("directory", "y_pendulum_results")))
        if not output_dir.is_absolute():
            output_dir = base_directory / output_dir
    summary = write_results(
        model,
        outputs,
        root_copy,
        output_dir,
        input_source,
        init_info,
        integ_info,
    )
    return {"output_directory": str(output_dir.resolve()), "summary": summary}


def run_from_config(config_path: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = _read_json(config_path)
    return run_from_mapping(
        root,
        base_directory=config_path.parent,
        input_source=str(config_path.resolve()),
        output_override=output_override,
    )


def run_from_embedded_inputs(output_override: Path | None = None) -> dict[str, Any]:
    return run_from_mapping(
        USER_INPUTS,
        base_directory=Path.cwd(),
        input_source="USER_INPUTS block at the top of y_pendulum_closed.py",
        output_override=output_override,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Integrate the Section-13 quadratic Ritz closed Y-pendulum theory. "
            "With no config argument, the single USER_INPUTS block at the top of this file is used."
        )
    )
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        help="Optional JSON configuration; omit it to use the USER_INPUTS block at the top",
    )
    parser.add_argument("--output", type=Path, help="Override output directory")
    parser.add_argument(
        "--make-example",
        type=Path,
        metavar="PATH",
        help="Write the current USER_INPUTS block as a JSON configuration and exit",
    )
    parser.add_argument("--self-test", action="store_true", help="Run deterministic theory checks")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.make_example is not None:
            args.make_example.parent.mkdir(parents=True, exist_ok=True)
            _json_dump(args.make_example, example_configuration())
            print(f"Wrote current USER_INPUTS to: {args.make_example}")
            return 0
        if args.self_test:
            self_test(verbose=True)
            return 0
        if args.config is None:
            result = run_from_embedded_inputs(args.output)
        else:
            result = run_from_config(args.config, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, FloatingPointError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

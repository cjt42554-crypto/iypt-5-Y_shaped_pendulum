"""Configuration and job adapter for the offline Tk desktop application.

The desktop UI edits complete in-memory FWD/HF configuration snapshots.  YAML
and JSON remain reproducibility formats written by the application; they are
not the normal parameter-entry surface.  No physics is implemented here.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ypendulum.config import load_config, resolved_config_dict
from ypendulum.geometry.reduced_geometry import fixed_knot_upper_geometry
from ypendulum.ui.platform import (
    AnalysisSchema,
    BackendSchema,
    ConfigurationSectionSchema,
    OutputAssessment,
    ProblemSchema,
    ViewSchema,
)

DESKTOP_REQUEST_SCHEMA = "YPS-DESKTOP-RUN-1.0"
DESKTOP_RESULT_SCHEMA = "YPS-DESKTOP-RESULT-1.0"
DESKTOP_PLUGIN_ID = "iypt_2027_y_pendulum_desktop"

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROGRAMS_ROOT = PROJECT_ROOT.parents[1]
FORWARD_ROOT = (
    PROGRAMS_ROOT
    / "01_前向预测数值求解器"
    / "y_pendulum_forward_solver"
)
DEFAULT_FORWARD_CONFIG = FORWARD_ROOT / "configs" / "cable_example.json"
DEFAULT_HF_CONFIG = (
    PROJECT_ROOT / "configs" / "examples" / "high_fidelity_shared_forward_window.yaml"
)
DEFAULT_RESEARCH_HORIZON_S = 8.0
DEFAULT_RESEARCH_OUTPUT_DT_S = 0.005
DEFAULT_RESEARCH_OBSERVATION_DT_S = 0.01


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Configuration root must be an object: {path}")
    return value


def load_forward_profile(path: str | Path = DEFAULT_FORWARD_CONFIG) -> dict[str, Any]:
    return _load_json(Path(path).expanduser().resolve())


def load_hf_profile(path: str | Path = DEFAULT_HF_CONFIG) -> dict[str, Any]:
    return resolved_config_dict(load_config(Path(path).expanduser().resolve()))


def _set_path(root: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor: Any = root
    for part in parts[:-1]:
        if not isinstance(cursor, dict) or part not in cursor:
            raise KeyError(path)
        cursor = cursor[part]
    if not isinstance(cursor, dict) or parts[-1] not in cursor:
        raise KeyError(path)
    cursor[parts[-1]] = value


def get_path(root: dict[str, Any], path: str) -> Any:
    cursor: Any = root
    for part in path.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            raise KeyError(path)
        cursor = cursor[part]
    return cursor


def _numeric_array(value: Any, *, length: int | None = None) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if length is not None and array.shape != (length,):
        raise ValueError(f"Expected a vector of length {length}; received shape {array.shape}.")
    if not np.all(np.isfinite(array)):
        raise ValueError("Numeric parameter contains NaN or infinity.")
    return array


def _straight_branch(start: Any, end: Any) -> list[list[float]]:
    first = _numeric_array(start, length=3)
    last = _numeric_array(end, length=3)
    return [first.tolist(), (last - first).tolist()]


@dataclass(frozen=True)
class InitialReleaseParameters:
    """User-facing length/angle representation of the complete endpoint state.

    Positions are expressed in a support/gravity frame.  Rates provide a
    complete local representation of the junction and bob translational
    velocities, while the three final rates retain the HF rigid-bob spin.
    Angles are deliberately stored in degrees because this is a desktop input
    contract; solver snapshots remain SI Cartesian arrays.
    """

    upper_a_length_m: float
    upper_b_length_m: float
    junction_roll_deg: float
    lower_branch_length_m: float
    lower_polar_deg: float
    lower_azimuth_deg: float
    upper_a_length_rate_m_s: float = 0.0
    upper_b_length_rate_m_s: float = 0.0
    junction_roll_rate_deg_s: float = 0.0
    lower_length_rate_m_s: float = 0.0
    lower_polar_rate_deg_s: float = 0.0
    lower_azimuth_rate_deg_s: float = 0.0
    bob_spin_support_deg_s: float = 0.0
    bob_spin_radial_deg_s: float = 0.0
    bob_spin_tangent_deg_s: float = 0.0


INITIAL_RELEASE_FIELD_NAMES = tuple(InitialReleaseParameters.__dataclass_fields__)


def _finite_release_parameters(parameters: InitialReleaseParameters) -> None:
    for name in INITIAL_RELEASE_FIELD_NAMES:
        value = float(getattr(parameters, name))
        if not math.isfinite(value):
            raise ValueError(f"初始状态参数 {name} 必须是有限实数。")
    if parameters.upper_a_length_m <= 0.0:
        raise ValueError("上支 A 初始几何长度必须大于 0。")
    if parameters.upper_b_length_m <= 0.0:
        raise ValueError("上支 B 初始几何长度必须大于 0。")
    if parameters.lower_branch_length_m <= 0.0:
        raise ValueError("下支初始几何长度必须大于 0。")
    if not 0.0 <= parameters.lower_polar_deg <= 180.0:
        raise ValueError("摆球偏角必须满足 0° ≤ 偏角 ≤ 180°。")


def _release_cartesian_state(
    parameters: InitialReleaseParameters,
    support_a: Any,
    support_b: Any,
    gravity: Any,
) -> dict[str, list[float]]:
    """Convert the desktop length/angle state into Cartesian SI endpoint data."""

    _finite_release_parameters(parameters)
    a = _numeric_array(support_a, length=3)
    b = _numeric_array(support_b, length=3)
    g = _numeric_array(gravity, length=3)
    if float(np.linalg.norm(g)) <= 0.0:
        raise ValueError("长度/角度初始状态需要非零重力向量来定义‘向下’。")
    try:
        geometry = fixed_knot_upper_geometry(
            a,
            b,
            float(parameters.upper_a_length_m),
            float(parameters.upper_b_length_m),
            g,
        )
    except ValueError as exc:
        raise ValueError(
            "两条上支初始几何长度与支点间距不能形成非退化 Y 形三角形。"
        ) from exc

    psi = math.radians(parameters.junction_roll_deg)
    alpha = math.radians(parameters.lower_polar_deg)
    beta = math.radians(parameters.lower_azimuth_deg)
    psi_dot = math.radians(parameters.junction_roll_rate_deg_s)
    alpha_dot = math.radians(parameters.lower_polar_rate_deg_s)
    beta_dot = math.radians(parameters.lower_azimuth_rate_deg_s)

    axis = geometry.axis
    radial = math.cos(psi) * geometry.radial_down + math.sin(psi) * geometry.azimuth
    tangent = -math.sin(psi) * geometry.radial_down + math.cos(psi) * geometry.azimuth
    junction = geometry.center + geometry.h * radial

    horizontal = math.cos(beta) * axis + math.sin(beta) * tangent
    lower_direction = math.cos(alpha) * radial + math.sin(alpha) * horizontal
    bob = junction + parameters.lower_branch_length_m * lower_direction

    a_dot = (
        parameters.upper_a_length_m * parameters.upper_a_length_rate_m_s
        - parameters.upper_b_length_m * parameters.upper_b_length_rate_m_s
    ) / geometry.distance
    h_dot = (
        parameters.upper_a_length_m * parameters.upper_a_length_rate_m_s
        - geometry.a_a * a_dot
    ) / geometry.h
    junction_velocity = (
        a_dot * axis + h_dot * radial + geometry.h * psi_dot * tangent
    )

    d_alpha = -math.sin(alpha) * radial + math.cos(alpha) * horizontal
    d_beta = math.sin(alpha) * (
        -math.sin(beta) * axis + math.cos(beta) * tangent
    )
    d_psi = math.cos(alpha) * tangent - math.sin(alpha) * math.sin(beta) * radial
    lower_velocity = (
        parameters.lower_length_rate_m_s * lower_direction
        + parameters.lower_branch_length_m
        * (alpha_dot * d_alpha + beta_dot * d_beta + psi_dot * d_psi)
    )
    bob_velocity = junction_velocity + lower_velocity

    bob_angular_velocity = (
        math.radians(parameters.bob_spin_support_deg_s) * axis
        + math.radians(parameters.bob_spin_radial_deg_s) * radial
        + math.radians(parameters.bob_spin_tangent_deg_s) * tangent
    )
    return {
        "junction_position": junction.tolist(),
        "bob_position": bob.tolist(),
        "junction_velocity": junction_velocity.tolist(),
        "bob_velocity": bob_velocity.tolist(),
        "bob_angular_velocity": bob_angular_velocity.tolist(),
    }


def _release_parameters_from_cartesian(
    *,
    support_a: Any,
    support_b: Any,
    gravity: Any,
    junction_position: Any,
    bob_position: Any,
    junction_velocity: Any,
    bob_velocity: Any,
    bob_angular_velocity: Any | None = None,
) -> InitialReleaseParameters:
    """Recover the desktop representation from a complete Cartesian state."""

    a = _numeric_array(support_a, length=3)
    b = _numeric_array(support_b, length=3)
    g = _numeric_array(gravity, length=3)
    junction = _numeric_array(junction_position, length=3)
    bob = _numeric_array(bob_position, length=3)
    junction_v = _numeric_array(junction_velocity, length=3)
    bob_v = _numeric_array(bob_velocity, length=3)
    omega = (
        np.zeros(3, dtype=float)
        if bob_angular_velocity is None
        else _numeric_array(bob_angular_velocity, length=3)
    )

    upper_a = float(np.linalg.norm(junction - a))
    upper_b = float(np.linalg.norm(junction - b))
    lower = float(np.linalg.norm(bob - junction))
    if min(upper_a, upper_b, lower) <= 0.0:
        raise ValueError("坐标初态含零长度支路，无法转换成长度/角度参数。")
    geometry = fixed_knot_upper_geometry(a, b, upper_a, upper_b, g)
    radial_vector = junction - geometry.center
    radial_norm = float(np.linalg.norm(radial_vector))
    if radial_norm <= 1.0e-14 * max(geometry.distance, 1.0):
        raise ValueError("结点位于支点轴上，绕轴角没有定义。")
    radial = radial_vector / radial_norm
    junction_roll = math.atan2(
        float(np.dot(radial, geometry.azimuth)),
        float(np.dot(radial, geometry.radial_down)),
    )
    tangent = np.cross(geometry.axis, radial)
    tangent /= np.linalg.norm(tangent)

    lower_direction = (bob - junction) / lower
    cos_alpha = float(np.clip(np.dot(lower_direction, radial), -1.0, 1.0))
    alpha = math.acos(cos_alpha)
    sin_alpha = math.sin(alpha)
    if sin_alpha <= 1.0e-12:
        beta = 0.0
    else:
        beta = math.atan2(
            float(np.dot(lower_direction, tangent)),
            float(np.dot(lower_direction, geometry.axis)),
        )

    upper_a_rate = float(np.dot((junction - a) / upper_a, junction_v))
    upper_b_rate = float(np.dot((junction - b) / upper_b, junction_v))
    psi_dot = float(np.dot(junction_v, tangent)) / radial_norm
    relative_velocity = bob_v - junction_v
    lower_rate = float(np.dot(relative_velocity, lower_direction))
    angular_velocity = (relative_velocity - lower_rate * lower_direction) / lower
    horizontal = math.cos(beta) * geometry.axis + math.sin(beta) * tangent
    d_alpha = -math.sin(alpha) * radial + math.cos(alpha) * horizontal
    d_psi = math.cos(alpha) * tangent - math.sin(alpha) * math.sin(beta) * radial
    residual = angular_velocity - psi_dot * d_psi
    alpha_dot = float(np.dot(residual, d_alpha))
    beta_direction = -math.sin(beta) * geometry.axis + math.cos(beta) * tangent
    beta_dot = (
        0.0
        if sin_alpha <= 1.0e-12
        else float(np.dot(residual, beta_direction)) / sin_alpha
    )

    return InitialReleaseParameters(
        upper_a_length_m=upper_a,
        upper_b_length_m=upper_b,
        junction_roll_deg=math.degrees(junction_roll),
        lower_branch_length_m=lower,
        lower_polar_deg=math.degrees(alpha),
        lower_azimuth_deg=math.degrees(beta),
        upper_a_length_rate_m_s=upper_a_rate,
        upper_b_length_rate_m_s=upper_b_rate,
        junction_roll_rate_deg_s=math.degrees(psi_dot),
        lower_length_rate_m_s=lower_rate,
        lower_polar_rate_deg_s=math.degrees(alpha_dot),
        lower_azimuth_rate_deg_s=math.degrees(beta_dot),
        bob_spin_support_deg_s=math.degrees(float(np.dot(omega, geometry.axis))),
        bob_spin_radial_deg_s=math.degrees(float(np.dot(omega, radial))),
        bob_spin_tangent_deg_s=math.degrees(float(np.dot(omega, tangent))),
    )


def initial_release_from_forward(config: dict[str, Any]) -> InitialReleaseParameters:
    physical = config["physical"]
    inputs = config["inputs"]
    initial = config["initial_state"]
    gravity = float(physical["g"]) * _numeric_array(physical["e_z"], length=3)
    return _release_parameters_from_cartesian(
        support_a=inputs["support_A"]["value"],
        support_b=inputs["support_B"]["value"],
        gravity=gravity,
        junction_position=initial["r_J"],
        bob_position=initial["r_m"],
        junction_velocity=initial["v_J"],
        bob_velocity=initial["v_m"],
    )


def initial_release_from_hf(config: dict[str, Any]) -> InitialReleaseParameters:
    initial = config["initial_condition"]
    required = ("junction_position", "bob_position")
    if any(initial.get(name) is None for name in required):
        raise ValueError("当前 HF 初态没有结点和摆球坐标，无法恢复长度/角度输入。")
    return _release_parameters_from_cartesian(
        support_a=config["supports"]["A"]["position"],
        support_b=config["supports"]["B"]["position"],
        gravity=config["environment"]["gravity"],
        junction_position=initial["junction_position"],
        bob_position=initial["bob_position"],
        junction_velocity=initial["junction_velocity"],
        bob_velocity=initial["bob_velocity"],
        bob_angular_velocity=initial["bob_angular_velocity"],
    )


def apply_initial_release_to_forward(
    config: dict[str, Any], parameters: InitialReleaseParameters
) -> dict[str, Any]:
    result = deepcopy(config)
    physical = result["physical"]
    inputs = result["inputs"]
    gravity = float(physical["g"]) * _numeric_array(physical["e_z"], length=3)
    state = _release_cartesian_state(
        parameters,
        inputs["support_A"]["value"],
        inputs["support_B"]["value"],
        gravity,
    )
    initial = result["initial_state"]
    initial["r_J"] = state["junction_position"]
    initial["r_m"] = state["bob_position"]
    initial["v_J"] = state["junction_velocity"]
    initial["v_m"] = state["bob_velocity"]
    zero = [0.0, 0.0, 0.0]
    initial["branches"]["A"]["position"]["coefficients"] = _straight_branch(
        inputs["support_A"]["value"], initial["r_J"]
    )
    initial["branches"]["B"]["position"]["coefficients"] = _straight_branch(
        inputs["support_B"]["value"], initial["r_J"]
    )
    initial["branches"]["lower"]["position"]["coefficients"] = _straight_branch(
        initial["r_J"], initial["r_m"]
    )
    initial["branches"]["A"]["velocity"]["coefficients"] = _straight_branch(
        zero, initial["v_J"]
    )
    initial["branches"]["B"]["velocity"]["coefficients"] = _straight_branch(
        zero, initial["v_J"]
    )
    initial["branches"]["lower"]["velocity"]["coefficients"] = _straight_branch(
        initial["v_J"], initial["v_m"]
    )
    return result


def apply_initial_release_to_hf(
    config: dict[str, Any], parameters: InitialReleaseParameters
) -> dict[str, Any]:
    result = deepcopy(config)
    state = _release_cartesian_state(
        parameters,
        result["supports"]["A"]["position"],
        result["supports"]["B"]["position"],
        result["environment"]["gravity"],
    )
    initial = result["initial_condition"]
    initial["junction_position"] = state["junction_position"]
    initial["bob_position"] = state["bob_position"]
    initial["junction_velocity"] = state["junction_velocity"]
    initial["bob_velocity"] = state["bob_velocity"]
    initial["bob_angular_velocity"] = state["bob_angular_velocity"]
    return result


def synchronize_shared_forward_to_hf(
    forward: dict[str, Any], hf: dict[str, Any]
) -> dict[str, Any]:
    """Map the complete shared physical subset from FWD to HF in place.

    HF-only diameter, bending, finite-bob and contact parameters remain the HF
    document's independent inputs.  Densities/moduli and drag coefficients are
    recomputed so the resulting mass/EA/Ca/drag values equal the FWD document.
    """

    physical = forward["physical"]
    inputs = forward["inputs"]
    initial = forward["initial_state"]
    gravity = float(physical["g"]) * _numeric_array(physical["e_z"], length=3)
    hf["environment"]["gravity"] = gravity.tolist()
    hf["environment"]["air_density"] = float(physical["rho_air"])
    hf["environment"]["air_velocity"] = [0.0, 0.0, 0.0]
    hf["supports"]["A"]["type"] = "fixed"
    hf["supports"]["A"]["position"] = deepcopy(inputs["support_A"]["value"])
    hf["supports"]["A"]["motion"] = None
    hf["supports"]["B"]["type"] = "fixed"
    hf["supports"]["B"]["position"] = deepcopy(inputs["support_B"]["value"])
    hf["supports"]["B"]["motion"] = None
    hf["junction"]["mass"] = float(physical["junction_mass"])
    hf["bob"]["mass"] = float(physical["bob_mass"])
    volume = float(physical["bob_volume"])
    if volume <= 0.0:
        raise ValueError("Dual-backend bob_volume must be positive.")
    radius = (3.0 * volume / (4.0 * math.pi)) ** (1.0 / 3.0)
    hf["bob"]["radius"] = radius
    hf["bob"]["buoyancy"] = True
    c1 = float(physical["bob_c1"])
    c2 = float(physical["bob_c2"])
    hf["bob"]["drag"]["enabled"] = c1 > 0.0 or c2 > 0.0
    hf["bob"]["drag"]["model"] = (
        "quadratic_plus_linear"
        if c1 > 0.0 and c2 > 0.0
        else ("linear" if c1 > 0.0 else "quadratic")
    )
    hf["bob"]["drag"]["linear_coefficient"] = c1
    bob_area = math.pi * radius**2
    rho_air = float(physical["rho_air"])
    hf["bob"]["drag"]["cd"] = 0.0 if c2 == 0.0 else 2.0 * c2 / (rho_air * bob_area)

    branch_map = {"A": "upper_A", "B": "upper_B", "lower": "lower"}
    for forward_name, hf_name in branch_map.items():
        source = physical["branches"][forward_name]
        target = hf["cables"][hf_name]
        diameter = float(target["diameter"])
        area = math.pi * diameter**2 / 4.0
        target["rest_length"] = float(source["L0"])
        target["density"] = float(source["mu"]) / area
        target["young_modulus"] = float(source["EA"]) / area
        target["axial_viscosity"] = float(source["Ca"]) / area
        target["drag_linear_tangent_per_length"] = float(source["c_parallel"])
        target["drag_linear_normal_per_length"] = float(source["c_perp"])
        target["drag_cd_tangent"] = (
            0.0
            if float(source["d_parallel"]) == 0.0
            else 2.0 * float(source["d_parallel"]) / (rho_air * diameter)
        )
        target["drag_cd_normal"] = (
            0.0
            if float(source["d_perp"]) == 0.0
            else 2.0 * float(source["d_perp"]) / (rho_air * diameter)
        )
        target["drag_enabled"] = any(
            float(source[name]) > 0.0
            for name in ("c_parallel", "c_perp", "d_parallel", "d_perp")
        )

    hf["initial_condition"]["junction_position"] = deepcopy(initial["r_J"])
    hf["initial_condition"]["junction_velocity"] = deepcopy(initial["v_J"])
    hf["initial_condition"]["bob_position"] = deepcopy(initial["r_m"])
    hf["initial_condition"]["bob_velocity"] = deepcopy(initial["v_m"])
    hf["solver"]["t_end"] = float(physical["T"])

    # Direct-state endpoint polynomials are regenerated whenever shared
    # supports/J/bob positions change, so the FWD configuration remains a
    # complete compatible state rather than four disconnected point values.
    r_a = inputs["support_A"]["value"]
    r_b = inputs["support_B"]["value"]
    r_j = initial["r_J"]
    r_m = initial["r_m"]
    initial["branches"]["A"]["position"]["coefficients"] = _straight_branch(r_a, r_j)
    initial["branches"]["B"]["position"]["coefficients"] = _straight_branch(r_b, r_j)
    initial["branches"]["lower"]["position"]["coefficients"] = _straight_branch(r_j, r_m)
    zero = [0.0, 0.0, 0.0]
    initial["branches"]["A"]["velocity"]["coefficients"] = _straight_branch(
        zero, initial["v_J"]
    )
    initial["branches"]["B"]["velocity"]["coefficients"] = _straight_branch(
        zero, initial["v_J"]
    )
    initial["branches"]["lower"]["velocity"]["coefficients"] = _straight_branch(
        initial["v_J"], initial["v_m"]
    )
    return hf


def estimate_reference_periods(forward: dict[str, Any]) -> dict[str, float]:
    """Estimate the two low-frequency periods from the displayed release geometry.

    These are planning estimates for choosing an informative time window, not
    fitted frequencies or a replacement for the returned numerical spectrum.
    The fast length is the junction-to-bob distance; the slow length is that
    distance plus the junction offset from the fixed-support axis.
    """

    inputs = forward["inputs"]
    initial = forward["initial_state"]
    physical = forward["physical"]
    support_a = _numeric_array(inputs["support_A"]["value"], length=3)
    support_b = _numeric_array(inputs["support_B"]["value"], length=3)
    junction = _numeric_array(initial["r_J"], length=3)
    bob = _numeric_array(initial["r_m"], length=3)
    support_delta = support_b - support_a
    support_span = float(np.linalg.norm(support_delta))
    gravity = float(physical["g"])
    if not math.isfinite(gravity) or gravity <= 0.0 or support_span <= 0.0:
        raise ValueError("Reference periods require positive gravity and distinct supports.")
    support_axis = support_delta / support_span
    support_midpoint = 0.5 * (support_a + support_b)
    junction_relative = junction - support_midpoint
    junction_height = float(
        np.linalg.norm(junction_relative - np.dot(junction_relative, support_axis) * support_axis)
    )
    lower_length = float(np.linalg.norm(bob - junction))
    if lower_length <= 0.0:
        raise ValueError("Reference periods require a non-zero junction-to-bob distance.")
    fast_period = 2.0 * math.pi * math.sqrt(lower_length / gravity)
    slow_period = 2.0 * math.pi * math.sqrt((junction_height + lower_length) / gravity)
    horizon = float(physical["T"])
    return {
        "fast_period_s": fast_period,
        "slow_period_s": slow_period,
        "fast_cycles": horizon / fast_period,
        "slow_cycles": horizon / slow_period,
    }


def default_desktop_configuration() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return an immediately runnable multi-cycle interactive research preview."""

    forward = load_forward_profile()
    hf = load_hf_profile()
    # The example solver profile carries a conservative open-box material
    # domain, but those four numbers are not calibrated failure limits for the
    # desktop experiment.  Do not reject an otherwise defined initial state on
    # their account.  The independent physical.lambda_min guard remains active
    # because the cable tangent is undefined at a collapsed element.  Imported
    # configurations retain any bounds that their author explicitly supplied.
    for branch in forward["physical"]["branches"].values():
        domain = branch["material_domain"]
        domain["lambda_lower"] = None
        domain["lambda_upper"] = None
        domain["rate_lower"] = None
        domain["rate_upper"] = None
    # The default must be long enough to show the horizontal Lissajous trace,
    # not merely prove that a solver process can start.  For the bundled
    # geometry, 8 s covers about 6.9 fast and 5.2 slow small-amplitude periods.
    # The meshes are intentionally interactive preview meshes.  They do not
    # replace the explicit mesh/time refinement required for a formal claim.
    forward["physical"]["T"] = DEFAULT_RESEARCH_HORIZON_S
    forward["initial_state"]["r_m"] = [0.035, 0.02, 0.60]
    forward["numerics"]["elements"] = {"A": 2, "B": 2, "lower": 3}
    forward["numerics"]["method"] = "BDF"
    forward["numerics"]["rtol"] = 1.0e-7
    forward["numerics"]["atol"] = 1.0e-9
    forward["numerics"]["max_step"] = DEFAULT_RESEARCH_OUTPUT_DT_S
    forward["numerics"]["output_dt"] = DEFAULT_RESEARCH_OUTPUT_DT_S
    forward["observation"]["record_times"] = {
        "kind": "uniform",
        "start": 0.0,
        "stop": DEFAULT_RESEARCH_HORIZON_S,
        "step": DEFAULT_RESEARCH_OBSERVATION_DT_S,
    }
    hf["run"]["name"] = "desktop_multicycle_preview"
    hf["run"]["output_directory"] = "runs/desktop_managed"
    hf["run"]["claim_level"] = "DERIVED"
    hf["solver"]["profile"] = "quick"
    hf["solver"]["method"] = "BDF"
    hf["solver"]["t_end"] = DEFAULT_RESEARCH_HORIZON_S
    hf["solver"]["output_dt"] = DEFAULT_RESEARCH_OUTPUT_DT_S
    hf["solver"]["max_step"] = DEFAULT_RESEARCH_OUTPUT_DT_S
    hf["solver"]["rtol"] = 1.0e-7
    hf["solver"]["position_atol"] = 1.0e-9
    hf["solver"]["velocity_atol"] = 1.0e-8
    hf["solver"]["quaternion_atol"] = 1.0e-9
    hf["solver"]["resolve_longitudinal_waves"] = False
    hf["solver"]["allow_subminimum_mesh"] = True
    hf["solver"]["static"]["max_iterations"] = 200
    hf["solver"]["static"]["continuation_steps"] = 6
    hf["cables"]["upper_A"]["elements"] = 1
    hf["cables"]["upper_B"]["elements"] = 1
    hf["cables"]["lower"]["elements"] = 1
    hf["analysis"]["slow_period_count"] = 5
    synchronize_shared_forward_to_hf(forward, hf)
    return forward, hf


_TRANSLATIONS = {
    "schema_version": "配置版本",
    "model_id": "模型标识",
    "theory_sha256": "理论 SHA-256",
    "units": "单位制",
    "g": "重力加速度",
    "e_z": "向下单位向量",
    "junction_mass": "结点质量",
    "bob_mass": "摆球质量",
    "rho_air": "空气密度",
    "bob_volume": "摆球排水体积",
    "bob_c1": "摆球线性阻力系数",
    "bob_c2": "摆球二次阻力系数",
    "lambda_min": "最小伸长比",
    "T": "仿真时长",
    "L0": "材料静长",
    "mu": "线密度",
    "EA": "轴向刚度",
    "Ca": "轴向黏性",
    "delta": "张力激活平滑宽度",
    "c_parallel": "切向线性阻力",
    "c_perp": "法向线性阻力",
    "d_parallel": "切向二次阻力",
    "d_perp": "法向二次阻力",
    "r_J": "结点初始位置",
    "v_J": "结点初始速度",
    "r_m": "摆球初始位置",
    "v_m": "摆球初始速度",
    "elements": "单元数",
    "quadrature_order": "求积阶数",
    "rtol": "相对容差",
    "atol": "绝对容差",
    "max_step": "最大积分步",
    "output_dt": "输出时间步",
    "event_cluster_tolerance": "同刻事件时间容差",
    "gravity": "重力向量",
    "air_density": "空气密度",
    "air_velocity": "空气速度",
    "mass": "质量",
    "radius": "半径",
    "rest_length": "材料静长",
    "diameter": "直径",
    "density": "体密度",
    "young_modulus": "杨氏模量",
    "axial_viscosity": "轴向黏度",
    "drag_cd_normal": "法向阻力系数",
    "drag_cd_tangent": "切向阻力系数",
    "drag_enabled": "启用柔索气动阻力",
    "bob_position": "摆球质心初始位置",
    "junction_position": "结点初始位置",
    "bob_velocity": "摆球初始速度",
    "junction_velocity": "结点初始速度",
    "bob_angular_velocity": "摆球初始角速度",
    "profile": "求解配置档",
    "t_end": "仿真时长",
    "position_atol": "位置绝对容差",
    "velocity_atol": "速度绝对容差",
    "quaternion_atol": "四元数绝对容差",
    "angular_velocity_atol": "角速度绝对容差",
    "force_tolerance": "静力残差容差",
    "max_iterations": "最大迭代数",
    "continuation_steps": "延续步数",
    "line_search_min": "最小线搜索步长",
    "target_ratio": "目标频率比",
    "phase_tolerance": "相位容差",
    "slow_period_count": "慢周期数",
    "bending_stiffness_scale": "弯曲刚度倍率",
    "compression_regularization_scale": "压缩正则倍率",
    "bob_inertia_factor": "摆球惯量因子",
    "bob_attachment_radius_fraction": "附件偏心半径比例",
    "bob_contact_radius_fraction": "摆球接触半径比例",
    "quaternion_stabilization_rate": "四元数稳定率",
    "contact_guard_enabled": "启用接触守卫",
    "minimum_clearance": "最小接触间隙",
}


_CHOICES_BY_SUFFIX: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("run.claim_level", ("DERIVED", "VERIFIED", "OUT_OF_SCOPE")),
    ("solver.profile", ("quick", "production", "reference")),
    ("solver.method", ("Radau", "BDF", "Newmark")),
    ("numerics.method", ("Radau", "BDF", "DOP853")),
    ("solver.mass_matrix", ("lumped", "consistent")),
    ("initial_condition.type", ("static_equilibrium", "cartesian_release", "geometric_direct_release", "held_endpoint_equilibrium_release", "restart")),
    ("initial_state.mode", ("DIRECT_STATE", "STATIC_HOLD_RELEASE")),
    ("observer.type", ("orthographic_xy", "pinhole")),
    ("observation.type", ("orthographic", "camera")),
    ("bob.drag.model", ("quadratic", "linear", "quadratic_plus_linear")),
    ("material_model", ("linear_kelvin_voigt_tension_only", "tabulated_tension_extension")),
    ("material_domain.kind", ("open_box",)),
    ("record_times.kind", ("uniform", "explicit")),
    ("solver.static.method", ("energy_minimize", "continuation_newton")),
)


_UNIT_BY_SUFFIX: tuple[tuple[str, str], ...] = (
    ("physical.g", "m/s²"),
    ("physical.T", "s"),
    ("junction_mass", "kg"),
    ("bob_mass", "kg"),
    ("rho_air", "kg/m³"),
    ("bob_volume", "m³"),
    ("bob_c1", "N·s/m"),
    ("bob_c2", "kg/m"),
    (".L0", "m"),
    (".mu", "kg/m"),
    (".EA", "N"),
    (".Ca", "N·s"),
    (".c_parallel", "N·s/m²"),
    (".c_perp", "N·s/m²"),
    (".d_parallel", "kg/m²"),
    (".d_perp", "kg/m²"),
    ("r_J", "m"),
    ("r_m", "m"),
    ("v_J", "m/s"),
    ("v_m", "m/s"),
    ("support_A.value", "m"),
    ("support_B.value", "m"),
    ("environment.gravity", "m/s²"),
    ("environment.air_density", "kg/m³"),
    ("environment.air_velocity", "m/s"),
    ("supports.A.position", "m"),
    ("supports.B.position", "m"),
    ("junction.mass", "kg"),
    ("junction.drag_linear", "N·s/m"),
    ("bob.mass", "kg"),
    ("bob.radius", "m"),
    ("linear_coefficient", "N·s/m"),
    ("rest_length", "m"),
    ("diameter", "m"),
    ("density", "kg/m³"),
    ("young_modulus", "Pa"),
    ("axial_viscosity", "Pa·s"),
    ("drag_linear_normal_per_length", "N·s/m²"),
    ("drag_linear_tangent_per_length", "N·s/m²"),
    ("bob_position", "m"),
    ("junction_position", "m"),
    ("bob_velocity", "m/s"),
    ("junction_velocity", "m/s"),
    ("bob_angular_velocity", "rad/s"),
    ("solver.t_end", "s"),
    ("solver.output_dt", "s"),
    ("solver.max_step", "s"),
    ("position_atol", "m"),
    ("velocity_atol", "m/s"),
    ("angular_velocity_atol", "rad/s"),
    ("force_tolerance", "N"),
    ("phase_tolerance", "rad"),
    ("quaternion_stabilization_rate", "1/s"),
    ("minimum_clearance", "m"),
)


_POSITIVE_TOKENS = {
    "g",
    "T",
    "mass",
    "junction_mass",
    "bob_mass",
    "radius",
    "rest_length",
    "L0",
    "mu",
    "EA",
    "diameter",
    "density",
    "young_modulus",
    "elements",
    "quadrature_order",
    "rtol",
    "atol",
    "max_step",
    "output_dt",
    "t_end",
    "position_atol",
    "velocity_atol",
    "quaternion_atol",
    "angular_velocity_atol",
    "force_tolerance",
    "max_iterations",
    "continuation_steps",
}


@dataclass(frozen=True)
class ParameterField:
    backend: str
    path: str
    section: str
    label: str
    value: Any
    kind: str
    unit: str
    description: str
    legal_range: str
    choices: tuple[str, ...] = ()
    editable: bool = True


def _section(backend: str, path: str) -> str:
    root = path.split(".", 1)[0]
    forward = {
        "schema_version": "身份与单位",
        "model_id": "身份与单位",
        "theory_sha256": "身份与单位",
        "units": "身份与单位",
        "physical": "几何、质量与本构",
        "inputs": "支点、外力与守卫",
        "initial_state": "初始状态",
        "numerics": "数值求解",
        "observation": "观测器",
        "validation": "收敛研究阈值",
        "metadata": "研究说明",
    }
    hf = {
        "schema_version": "身份与单位",
        "run": "运行身份",
        "environment": "重力与空气",
        "supports": "支点边界",
        "junction": "有限质量结点",
        "bob": "有限刚体摆球",
        "cables": "离散杆材料与网格",
        "initial_condition": "初始状态",
        "solver": "数值求解",
        "analysis": "后处理",
        "observer": "观测器",
        "high_fidelity": "HF 独立局部机制",
    }
    return (forward if backend == "forward" else hf).get(root, "其他")


def _unit(path: str) -> str:
    for suffix, unit in _UNIT_BY_SUFFIX:
        if path.endswith(suffix):
            return unit
    return "—"


def _choices(path: str) -> tuple[str, ...]:
    for suffix, values in _CHOICES_BY_SUFFIX:
        if path.endswith(suffix):
            return values
    if path.endswith(".kind"):
        if "support" in path:
            return ("constant", "harmonic", "polynomial", "table")
        if "force" in path:
            return ("zero", "constant", "harmonic", "polynomial")
        return ("zero", "constant", "affine", "harmonic", "polynomial", "uniform")
    return ()


def _description(path: str, unit: str) -> str:
    tail = path.split(".")[-1]
    name = _TRANSLATIONS.get(tail, tail.replace("_", " "))
    suffix = "后端将在提交前完整验证。"
    return f"{name}；配置路径 {path}。单位 {unit}。{suffix}"


def _legal_range(path: str, value: Any, choices: tuple[str, ...]) -> str:
    if choices:
        return "可选：" + " / ".join(choices)
    if isinstance(value, bool):
        return "开启 / 关闭"
    token = path.split(".")[-1]
    if token in _POSITIVE_TOKENS:
        return "> 0；还需满足后端资源与物理合同"
    if any(word in token for word in ("drag", "viscosity", "clearance", "delta")):
        return "≥ 0；还需满足后端合同"
    if isinstance(value, list):
        return f"有限实数数组；当前形状 {np.asarray(value, dtype=object).shape}"
    return "有限值；具体关联限制由后端验证器就地提示"


def _kind(value: Any, path: str) -> str:
    if path.endswith("inputs.exit_guards"):
        return "guards"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        if value and all(isinstance(item, str) for item in value):
            return "string_list"
        return "matrix" if value and isinstance(value[0], list) else "vector"
    if value is None:
        return "nullable"
    return "str"


def _editable(backend: str, path: str) -> bool:
    locked = {
        "schema_version",
        "model_id",
        "theory_sha256",
        "units",
        "run.mode",
        "run.output_directory",
        "high_fidelity.model_id",
    }
    if path in locked:
        return False
    if backend == "forward" and path.startswith("validation."):
        # Validation thresholds do not participate in a single trajectory;
        # they remain visible and are editable for explicit convergence work.
        return True
    return True


def parameter_fields(config: dict[str, Any], backend: str) -> tuple[ParameterField, ...]:
    fields: list[ParameterField] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{path}.{key}" if path else key)
            return
        choices = _choices(path)
        unit = _unit(path)
        tail = path.split(".")[-1]
        fields.append(
            ParameterField(
                backend=backend,
                path=path,
                section=_section(backend, path),
                label=_TRANSLATIONS.get(tail, tail.replace("_", " ")),
                value=deepcopy(value),
                kind=_kind(value, path),
                unit=unit,
                description=_description(path, unit),
                legal_range=_legal_range(path, value, choices),
                choices=choices,
                editable=_editable(backend, path),
            )
        )

    visit(config, "")
    return tuple(fields)


def leaf_paths(config: dict[str, Any]) -> set[str]:
    return {field.path for field in parameter_fields(config, "forward")}


def format_parameter_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        if value and all(isinstance(item, str) for item in value):
            return ", ".join(value)
        if value and isinstance(value[0], list):
            return "; ".join(", ".join(f"{float(item):.16g}" for item in row) for row in value)
        return ", ".join(f"{float(item):.16g}" for item in value)
    if isinstance(value, float):
        return f"{value:.16g}"
    return str(value)


def parse_parameter_text(field: ParameterField, text: str) -> Any:
    value = text.strip()
    if field.kind == "str":
        if not value:
            raise ValueError("文本参数不能为空。")
        return value
    if field.kind == "nullable":
        return None if not value else value
    if field.kind == "bool":
        lowered = value.lower()
        if lowered not in {"true", "false", "1", "0", "yes", "no"}:
            raise ValueError("布尔值必须是 true/false。")
        return lowered in {"true", "1", "yes"}
    if field.kind == "int":
        parsed = int(value)
        if str(parsed) != value and value not in {f"+{parsed}", f"-{abs(parsed)}"}:
            # int("01") is safe, but make accidental floating text explicit.
            float_value = float(value)
            if not float_value.is_integer():
                raise ValueError("需要整数。")
        return parsed
    if field.kind == "float":
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("数值必须有限。")
        return parsed
    if field.kind in {"vector", "matrix"}:
        if not value and field.kind == "vector" and field.value == []:
            return []
        rows = [part.strip() for part in value.split(";")]
        parsed_rows: list[list[float]] = []
        for row in rows:
            tokens = [item for item in re.split(r"[\s,]+", row) if item]
            parsed = [float(item) for item in tokens]
            if not parsed or not all(math.isfinite(item) for item in parsed):
                raise ValueError("数组必须由有限实数组成。")
            parsed_rows.append(parsed)
        if field.kind == "vector":
            expected = len(field.value)
            if len(parsed_rows) != 1 or len(parsed_rows[0]) != expected:
                raise ValueError(f"需要 {expected} 个分量。")
            return parsed_rows[0]
        expected_shape = np.asarray(field.value, dtype=object).shape
        result: Any = parsed_rows
        if np.asarray(result, dtype=object).shape != expected_shape:
            raise ValueError(f"矩阵形状必须为 {expected_shape}。")
        return result
    if field.kind == "string_list":
        items = [item.strip() for item in value.split(",") if item.strip()]
        if not items:
            raise ValueError("文本列表至少需要一项。")
        return items
    if field.kind == "guards":
        if isinstance(field.value, list):
            return deepcopy(field.value)
        raise ValueError("守卫编辑器返回了非列表。")
    raise ValueError(f"未知参数类型：{field.kind}")


def apply_parameter_values(
    config: dict[str, Any], values: dict[str, Any]
) -> dict[str, Any]:
    result = deepcopy(config)
    for path, value in values.items():
        _set_path(result, path, deepcopy(value))
    return result


def _ensure_forward_imports() -> None:
    value = str(FORWARD_ROOT)
    if value not in sys.path:
        sys.path.insert(0, value)


def validate_forward_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    _ensure_forward_imports()
    from y_pendulum_forward.convergence import _preflight_base_config

    return list(_preflight_base_config(config, str(config.get("model_id"))))


def validate_hf_config(config: dict[str, Any]) -> Any:
    return load_config(deepcopy(config))


def shared_input_audit(forward: dict[str, Any], hf: dict[str, Any]) -> dict[str, Any]:
    _ensure_forward_imports()
    from ypendulum.unified.contracts import _shared_input_audit

    return _shared_input_audit(deepcopy(forward), validate_hf_config(hf))


def validate_desktop_request(request: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "label",
        "backend",
        "forward_config",
        "high_fidelity_config",
        "scan_coordinates",
    }
    if not isinstance(request, dict) or set(request) != required:
        raise ValueError("桌面运行请求字段不完整。")
    if request["schema_version"] != DESKTOP_REQUEST_SCHEMA:
        raise ValueError("不支持的桌面运行请求版本。")
    backend = request["backend"]
    if backend not in {"forward", "high_fidelity", "both"}:
        raise ValueError("后端必须是 forward、high_fidelity 或 both。")
    if not isinstance(request["label"], str) or not request["label"].strip():
        raise ValueError("运行标签不能为空。")
    errors: dict[str, Any] = {}
    if backend in {"forward", "both"}:
        forward = request["forward_config"]
        if not isinstance(forward, dict):
            raise ValueError("前向后端缺少完整配置。")
        forward_errors = validate_forward_config(forward)
        if forward_errors:
            errors["forward"] = forward_errors
    if backend in {"high_fidelity", "both"}:
        hf = request["high_fidelity_config"]
        if not isinstance(hf, dict):
            raise ValueError("HF 后端缺少完整配置。")
        try:
            validate_hf_config(hf)
        except Exception as exc:
            errors["high_fidelity"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
    audit: dict[str, Any] | None = None
    if backend == "both" and not errors:
        audit = shared_input_audit(request["forward_config"], request["high_fidelity_config"])
        if not audit["passed"]:
            errors["shared_input"] = [
                item for item in audit["checks"] if item.get("passed") is not True
            ]
    if errors:
        raise ValueError(json.dumps(errors, ensure_ascii=False, indent=2, allow_nan=False))
    coordinates = request["scan_coordinates"]
    if not isinstance(coordinates, dict):
        raise ValueError("scan_coordinates 必须是字典。")
    canonical_json_sha256(coordinates)
    return {
        "request_sha256": canonical_json_sha256(request),
        "backend": backend,
        "label": request["label"],
        "shared_input_audit": audit,
        "scan_coordinates": deepcopy(coordinates),
    }


def make_desktop_request(
    *,
    label: str,
    backend: str,
    forward_config: dict[str, Any] | None,
    high_fidelity_config: dict[str, Any] | None,
    scan_coordinates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = {
        "schema_version": DESKTOP_REQUEST_SCHEMA,
        "label": label.strip(),
        "backend": backend,
        "forward_config": deepcopy(forward_config),
        "high_fidelity_config": deepcopy(high_fidelity_config),
        "scan_coordinates": deepcopy(scan_coordinates or {}),
    }
    validate_desktop_request(request)
    return request


def write_desktop_request(path: str | Path, request: dict[str, Any]) -> Path:
    validate_desktop_request(request)
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    return target


def load_desktop_request(path: str | Path) -> dict[str, Any]:
    request = _load_json(Path(path).expanduser().resolve())
    validate_desktop_request(request)
    return request


DESKTOP_SCHEMA = ProblemSchema(
    identifier=DESKTOP_PLUGIN_ID,
    title="IYPT 2027 第 5 题：Y 形摆原生研究平台",
    description="本地 Tk 桌面界面管理的 FWD、HF 与同输入双后端运行。",
    configuration_format="YPS-DESKTOP-RUN-1.0 JSON (GUI managed)",
    backends=(
        BackendSchema("forward", "前向预测", "FWD-CABLE-1.0", "阶段 2 前向数值后端。"),
        BackendSchema("high_fidelity", "高保真", "HF-DISCRETE-ROD-RIGID-BOB-1.0", "阶段 3 高保真后端。"),
        BackendSchema("both", "同输入双后端", "FWD + HF", "共享物理输入验证后依次运行并比较。"),
    ),
    configuration_sections=(
        ConfigurationSectionSchema("forward", "FWD 完整参数", "所有当前 FWD 配置叶子字段。"),
        ConfigurationSectionSchema("high_fidelity", "HF 完整参数", "所有当前 HF 解析配置叶子字段。"),
        ConfigurationSectionSchema("workflow", "运行计划", "单次、重复、批量与扫描。"),
    ),
    views=(
        ViewSchema("geometry", "三维几何", "matplotlib_3d", "result files"),
        ViewSchema(
            "trajectory",
            "俯视轨迹 / 李萨如",
            "matplotlib_xy_equal_scale",
            "result files",
        ),
        ViewSchema("state", "位移速度", "matplotlib", "result files"),
        ViewSchema("force", "轴力与张力", "matplotlib", "result files"),
        ViewSchema("energy", "能量与功率", "matplotlib", "result files"),
        ViewSchema("guard", "守卫与事件", "matplotlib+table", "result files"),
        ViewSchema("analysis", "频谱与相图", "matplotlib", "result files"),
        ViewSchema("difference", "双后端差异", "matplotlib", "result files"),
    ),
    analyses=(
        AnalysisSchema("single", "单次", "desktop", "运行一个完整参数快照。"),
        AnalysisSchema("repeat", "重复", "desktop", "重复同一快照。"),
        AnalysisSchema("batch", "批量", "desktop", "执行界面中的多个案例快照。"),
        AnalysisSchema("sweep", "参数扫描", "desktop", "界面生成显式参数点。"),
        AnalysisSchema(
            "same_input_dual",
            "同输入双后端",
            "desktop",
            "共享输入同步后串行运行 FWD 与 HF 并比较。",
        ),
    ),
)


class DesktopYPendulumAdapter:
    """Adapter used by :class:`PersistentJobManager` for GUI-managed runs."""

    schema = DESKTOP_SCHEMA

    def validate_configuration(self, path: Path) -> dict[str, Any]:
        request = _load_json(path)
        return validate_desktop_request(request)

    def build_command(
        self, config_path: Path, *, backend: str, output_directory: Path
    ) -> list[str]:
        request = _load_json(config_path)
        identity = validate_desktop_request(request)
        if identity["backend"] != backend:
            raise ValueError(
                f"Run-plan backend {backend!r} differs from request backend "
                f"{identity['backend']!r}."
            )
        return [
            sys.executable,
            "-m",
            "ypendulum.ui.desktop_worker",
            str(config_path.resolve()),
            "--backend",
            backend,
            "--output",
            str(output_directory.resolve()),
        ]

    def validate_scan_coordinates(
        self, path: Path, coordinates: dict[str, Any]
    ) -> dict[str, Any]:
        request = _load_json(path)
        validate_desktop_request(request)
        if canonical_json_sha256(request["scan_coordinates"]) != canonical_json_sha256(
            coordinates
        ):
            raise ValueError("扫描坐标与 GUI 生成的运行请求不一致。")
        return deepcopy(coordinates)

    def inspect_output(self, output_directory: Path) -> OutputAssessment:
        path = output_directory / "desktop_result.json"
        if not path.is_file():
            return OutputAssessment(
                "FAILED",
                "NO_DESKTOP_RESULT",
                "子进程未写出 desktop_result.json。",
                accepted_return_codes=(),
            )
        payload = _load_json(path)
        if payload.get("schema_version") != DESKTOP_RESULT_SCHEMA:
            raise ValueError("桌面结果版本不支持。")
        request_sha = payload.get("request_sha256")
        backend = payload.get("backend")
        binding = {"request_sha256": request_sha, "backend": backend}
        evidence = {
            "desktop_result": str(path),
            "backend_outcomes": payload.get("backend_outcomes", {}),
            "comparison": payload.get("comparison"),
        }
        status = payload.get("status")
        if status == "COMPLETE":
            return OutputAssessment(
                "COMPLETED",
                status,
                "请求的后端已产生可读科学结果。",
                evidence=evidence,
                accepted_return_codes=(0,),
                input_identity_binding=binding,
                request_binding={"backend": backend},
            )
        if status == "OUT_OF_SCOPE_PREFIX":
            return OutputAssessment(
                "OUT_OF_SCOPE_PREFIX",
                status,
                "运行在物理有效域边界返回可读前缀。",
                evidence=evidence,
                accepted_return_codes=(0,),
                input_identity_binding=binding,
                request_binding={"backend": backend},
            )
        return OutputAssessment(
            "FAILED",
            str(status or "FAILED"),
            str(payload.get("message") or "后端运行失败。"),
            evidence=evidence,
            accepted_return_codes=(2,),
            input_identity_binding=binding,
            request_binding={"backend": backend},
        )

    def read_configuration(self, path: Path) -> dict[str, Any]:
        return load_desktop_request(path)

    def compare_experiment(
        self,
        run_directory: Path,
        experiment_path: Path,
        *,
        output_directory: Path,
    ) -> dict[str, Any]:
        raise NotImplementedError("原生桌面原型尚未接入实验 CSV 拟合界面。")


def numeric_sweep_values(start: float, stop: float, count: int) -> tuple[float, ...]:
    if not all(math.isfinite(value) for value in (start, stop)):
        raise ValueError("扫描端点必须有限。")
    if isinstance(count, bool) or count < 2:
        raise ValueError("扫描点数必须至少为 2。")
    return tuple(float(value) for value in np.linspace(start, stop, int(count)))

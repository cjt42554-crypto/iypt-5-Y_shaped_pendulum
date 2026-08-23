"""Configuration loading, inheritance and physical validation."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .manifest import load_validation_manifest
from .models import SimulationConfig
from .units import as_vector3, source_of, to_si


class ConfigurationError(ValueError):
    """A physically invalid or incomplete simulation configuration."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = {} if details is None else details


_HF_MAX_ESTIMATED_PEAK_MEMORY_BYTES = 8 * 1024**3
_HF_MAX_ESTIMATED_RESULT_BYTES = 8 * 1024**3
_HF_MAX_OUTPUT_SAMPLES = 2_000_001
_HF_MAX_ACCEPTED_STEP_BUDGET = 2_000_001
_HF_MAX_RUNTIME_BRANCH_ELEMENTS = 4096
_HF_MAX_RUNTIME_TOTAL_ELEMENTS = 8192
_HF_ACCEPTED_STEP_SAFETY_FACTOR = 4
_HF_HELD_SEED_UPPER_BOUND = 7
_HF_MAX_HELD_OPTIMIZER_ITERATION_BUDGET = 100_000
_HF_MIN_LINE_SEARCH_FRACTION = 2.0**-40
_HF_MIN_CONTROLLED_LIMIT_SCALE = 1.0e-6
_HF_MIN_BOB_INERTIA_FACTOR = 1.0e-6
_HF_INITIAL_CONDITION_CONSUMED_FIELDS = {
    "static_equilibrium": frozenset(
        {"type", "bob_velocity", "bob_angular_velocity"}
    ),
    "cartesian_release": frozenset(
        {"type", "bob_position", "bob_velocity", "bob_angular_velocity"}
    ),
    "geometric_direct_release": frozenset(
        {
            "type",
            "bob_position",
            "junction_position",
            "bob_velocity",
            "junction_velocity",
            "bob_angular_velocity",
        }
    ),
    "held_endpoint_equilibrium_release": frozenset(
        {
            "type",
            "bob_position",
            "junction_position",
            "bob_velocity",
            "junction_velocity",
            "bob_angular_velocity",
        }
    ),
}


def _float_product(*factors: float) -> float:
    """Multiply finite inputs with IEEE overflow/underflow sentinels."""

    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        return float(np.prod(np.asarray(factors, dtype=float), dtype=float))


def _hf_resource_over_budget_sentinel(
    *,
    branch_elements: tuple[Any, ...],
    total_elements: int | None,
    reason: str,
) -> dict[str, Any]:
    """Return the complete resource schema without evaluating unsafe products."""

    saturated_elements = (
        _HF_MAX_RUNTIME_TOTAL_ELEMENTS + 1
        if total_elements is None
        else total_elements
    )
    saturated_state_size = 6 * (_HF_MAX_RUNTIME_TOTAL_ELEMENTS + 2) + 13
    over_memory_float_count = _HF_MAX_ESTIMATED_PEAK_MEMORY_BYTES // 8 + 1
    over_result_float_count = _HF_MAX_ESTIMATED_RESULT_BYTES // 8 + 1
    return {
        "estimate_id": "HF_SINGLE_RUN_RESOURCE_HARD_CAP_V1",
        "runtime_enforcement_id": "MANUAL_SCIPY_RADAU_BDF_ACCEPTED_STEP_CAP_V1",
        "failure_reason": reason,
        "branch_elements": tuple(
            count if type(count) is int else None for count in branch_elements
        ),
        "branch_element_limit": _HF_MAX_RUNTIME_BRANCH_ELEMENTS,
        "total_element_limit": _HF_MAX_RUNTIME_TOTAL_ELEMENTS,
        "total_elements": saturated_elements,
        "state_size": saturated_state_size,
        "output_samples": _HF_MAX_OUTPUT_SAMPLES + 1,
        "output_sample_limit": _HF_MAX_OUTPUT_SAMPLES,
        "nominal_accepted_steps": _HF_MAX_ACCEPTED_STEP_BUDGET + 1,
        "accepted_step_budget": _HF_MAX_ACCEPTED_STEP_BUDGET + 1,
        "accepted_step_hard_cap": _HF_MAX_ACCEPTED_STEP_BUDGET + 1,
        "presentation_float_budget": over_memory_float_count,
        "accepted_trace_float_budget": over_memory_float_count,
        "implicit_workspace_float_budget": over_memory_float_count,
        "serialized_result_float_budget": over_result_float_count,
        "estimated_peak_memory_bytes": _HF_MAX_ESTIMATED_PEAK_MEMORY_BYTES + 1,
        "peak_memory_limit_bytes": _HF_MAX_ESTIMATED_PEAK_MEMORY_BYTES,
        "estimated_result_bytes": _HF_MAX_ESTIMATED_RESULT_BYTES + 1,
        "result_limit_bytes": _HF_MAX_ESTIMATED_RESULT_BYTES,
        "accepted_step_limit": _HF_MAX_ACCEPTED_STEP_BUDGET,
    }


def _high_fidelity_resource_estimate(
    cfg: SimulationConfig,
    *,
    t_end: float,
    output_dt: float,
) -> dict[str, Any]:
    """Hard joint state/sampling envelope for one in-memory HF run."""

    cables = (cfg.cables.upper_A, cfg.cables.upper_B, cfg.cables.lower)
    element_counts = tuple(cable.elements for cable in cables)
    if (
        not math.isfinite(t_end)
        or t_end <= 0.0
        or not math.isfinite(output_dt)
        or output_dt <= 0.0
    ):
        return _hf_resource_over_budget_sentinel(
            branch_elements=element_counts,
            total_elements=None,
            reason="HF_TIME_GRID_RUNTIME_INVALID",
        )
    if any(
        type(count) is not int
        or count <= 0
        or count > _HF_MAX_RUNTIME_BRANCH_ELEMENTS
        for count in element_counts
    ):
        # Assignment validation is intentionally not relied on at this public
        # runtime boundary.  Return a complete over-budget sentinel before a
        # mutated huge integer can enter state-size powers or array shapes.
        return _hf_resource_over_budget_sentinel(
            branch_elements=element_counts,
            total_elements=None,
            reason="HF_MESH_RUNTIME_LIMIT_EXCEEDED",
        )
    total_elements = sum(element_counts)
    if total_elements > _HF_MAX_RUNTIME_TOTAL_ELEMENTS:
        # Each count is already small, so reuse the same safe sentinel path by
        # making the over-limit condition explicit without any large product.
        return _hf_resource_over_budget_sentinel(
            branch_elements=element_counts,
            total_elements=total_elements,
            reason="HF_MESH_RUNTIME_LIMIT_EXCEEDED",
        )
    particle_count = total_elements + 1
    state_size = 6 * particle_count + 13
    output_ratio = (
        t_end / output_dt
        if t_end > 0.0 and output_dt > 0.0
        else float("inf")
    )
    output_samples = (
        _HF_MAX_OUTPUT_SAMPLES + 1
        if (
            not math.isfinite(output_ratio)
            or output_ratio > _HF_MAX_OUTPUT_SAMPLES - 1
        )
        else max(2, int(math.ceil(output_ratio - 1.0e-12)) + 1)
    )

    gravity_norm = float(
        np.linalg.norm(as_vector3(cfg.environment.gravity, default_unit="m/s^2"))
    )
    cell_lengths = [
        float(to_si(cable.rest_length, default_unit="m")) / cable.elements
        for cable in cables
    ]
    effective_max_step = (
        math.sqrt(max(cell_lengths) / gravity_norm) / 100.0
        if gravity_norm > 0.0
        else float("inf")
    )
    if cfg.solver.resolve_longitudinal_waves:
        wave_steps: list[float] = []
        for cable, cell_length in zip(cables, cell_lengths, strict=True):
            wave_speed_squared = (
                float(to_si(cable.young_modulus, default_unit="Pa"))
                / float(to_si(cable.density, default_unit="kg/m^3"))
            )
            if (
                not math.isfinite(wave_speed_squared)
                or wave_speed_squared <= 0.0
                or cell_length <= 0.0
            ):
                # A zero/overflowed wave time is conservatively over budget;
                # never let extreme but finite inputs escape as ZeroDivisionError.
                wave_steps.append(0.0)
            else:
                wave_steps.append(
                    cell_length / math.sqrt(wave_speed_squared) / 10.0
                )
        effective_max_step = min(effective_max_step, *wave_steps)
    if cfg.solver.max_step != "auto":
        configured_max_step = float(
            to_si(cfg.solver.max_step, default_unit="s")
        )
        effective_max_step = min(
            effective_max_step,
            configured_max_step,
        )
    accepted_ratio = (
        t_end / effective_max_step
        if t_end > 0.0 and effective_max_step > 0.0
        else float("inf")
    )
    nominal_accepted_steps = (
        _HF_MAX_ACCEPTED_STEP_BUDGET + 1
        if (
            not math.isfinite(accepted_ratio)
            or accepted_ratio >= _HF_MAX_ACCEPTED_STEP_BUDGET
        )
        else max(2, int(math.ceil(accepted_ratio)) + 1)
    )
    accepted_step_budget = (
        _HF_MAX_ACCEPTED_STEP_BUDGET + 1
        if nominal_accepted_steps
        > _HF_MAX_ACCEPTED_STEP_BUDGET // _HF_ACCEPTED_STEP_SAFETY_FACTOR
        else max(
            1024,
            _HF_ACCEPTED_STEP_SAFETY_FACTOR * nominal_accepted_steps,
        )
    )

    # Presentation-grid state, duplicated cable paths/velocities, signed axial
    # force plus tensile force, energy, every guard, reactions and working
    # arrays.  The manually driven integrator enforces ``accepted_step_budget``
    # before taking another step and retains only its current interpolant;
    # accepted-step certificates are nevertheless budgeted at ten state
    # vectors per step.  Six dense state-size-squared arrays cover
    # worst-case implicit Jacobian/factorisation work even though the current
    # sparsity path normally uses much less.
    presentation_float_count = output_samples * (24 * total_elements + 192)
    accepted_float_count = accepted_step_budget * (10 * state_size)
    implicit_workspace_float_count = 6 * state_size**2
    peak_memory_bytes = math.ceil(
        1.25
        * 8
        * (
            presentation_float_count
            + accepted_float_count
            + implicit_workspace_float_count
        )
    )

    # Serialized HDF5 stores sampled state/path/signed-force/tension/ledger/
    # guard/reaction arrays plus one full accepted-step state certificate.  The
    # factor covers metadata and conservative no-compression overhead.
    result_float_count = (
        output_samples * (20 * total_elements + 160)
        + accepted_step_budget * (2 * state_size + 8)
    )
    result_bytes = math.ceil(1.25 * 8 * result_float_count)
    return {
        "estimate_id": "HF_SINGLE_RUN_RESOURCE_HARD_CAP_V1",
        "runtime_enforcement_id": (
            "MANUAL_SCIPY_RADAU_BDF_ACCEPTED_STEP_CAP_V1"
        ),
        "total_elements": total_elements,
        "state_size": state_size,
        "output_samples": output_samples,
        "output_sample_limit": _HF_MAX_OUTPUT_SAMPLES,
        "nominal_accepted_steps": nominal_accepted_steps,
        "accepted_step_budget": accepted_step_budget,
        "accepted_step_hard_cap": accepted_step_budget,
        "presentation_float_budget": presentation_float_count,
        "accepted_trace_float_budget": accepted_float_count,
        "implicit_workspace_float_budget": implicit_workspace_float_count,
        "serialized_result_float_budget": result_float_count,
        "estimated_peak_memory_bytes": peak_memory_bytes,
        "peak_memory_limit_bytes": _HF_MAX_ESTIMATED_PEAK_MEMORY_BYTES,
        "estimated_result_bytes": result_bytes,
        "result_limit_bytes": _HF_MAX_ESTIMATED_RESULT_BYTES,
        "accepted_step_limit": _HF_MAX_ACCEPTED_STEP_BUDGET,
    }


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that refuses last-key-wins ambiguity."""


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConfigurationError("YAML mapping keys must be scalar/hashable.") from exc
        if duplicate:
            raise ConfigurationError(f"Duplicate YAML mapping key: {key!r}.")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_unique_yaml(path: str | Path) -> Any:
    with Path(path).expanduser().resolve().open("r", encoding="utf-8") as stream:
        return yaml.load(stream, Loader=_UniqueKeySafeLoader)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if key == "inherit":
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _resolve_cable_inheritance(raw: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(raw)
    cables = data.get("cables", {})
    resolved: dict[str, Any] = {}
    visiting: set[str] = set()

    def resolve(name: str) -> dict[str, Any]:
        if name in resolved:
            return resolved[name]
        if name in visiting:
            raise ConfigurationError(f"Circular cable inheritance involving {name!r}.")
        if name not in cables:
            raise ConfigurationError(f"Unknown inherited cable {name!r}.")
        visiting.add(name)
        item = copy.deepcopy(cables[name])
        parent = item.get("inherit")
        if parent:
            item = _deep_merge(resolve(str(parent)), item)
        visiting.remove(name)
        resolved[name] = item
        return item

    for required in ("upper_A", "upper_B", "lower"):
        resolve(required)
    data["cables"] = resolved
    # JSON/YAML has no tuple type.  This is a schema-level container
    # normalization only; strict item validation below still rejects booleans,
    # strings and numeric coercion.
    target_ratio = data.get("analysis", {}).get("target_ratio")
    if isinstance(target_ratio, list):
        data["analysis"]["target_ratio"] = tuple(target_ratio)
    return data


def load_config(path_or_mapping: str | Path | dict[str, Any]) -> SimulationConfig:
    if isinstance(path_or_mapping, (str, Path)):
        path = Path(path_or_mapping).expanduser().resolve()
        raw = load_unique_yaml(path)
        if not isinstance(raw, dict):
            raise ConfigurationError("Configuration root must be a mapping.")
        cfg = SimulationConfig.model_validate(
            _resolve_cable_inheritance(raw), strict=True
        )
        cfg.source_path = path
    else:
        if not isinstance(path_or_mapping, dict):
            raise ConfigurationError("Configuration root must be a mapping.")
        cfg = SimulationConfig.model_validate(
            _resolve_cable_inheritance(path_or_mapping), strict=True
        )
    validate_physical_config(cfg)
    return cfg


def validate_physical_config(cfg: SimulationConfig) -> None:
    def finite_scalar(value: Any, *, unit: str, name: str) -> float:
        scalar = float(to_si(value, default_unit=unit))
        if not math.isfinite(scalar):
            raise ConfigurationError(f"{name} must be finite.")
        return scalar

    A = as_vector3(cfg.supports.A.position, default_unit="m")
    B = as_vector3(cfg.supports.B.position, default_unit="m")
    d = float(np.linalg.norm(B - A))
    if not np.isfinite(d) or d <= 0:
        raise ConfigurationError("The two support points must be distinct finite positions.")

    lengths = [
        float(to_si(cfg.cables.upper_A.rest_length, default_unit="m")),
        float(to_si(cfg.cables.upper_B.rest_length, default_unit="m")),
        float(to_si(cfg.cables.lower.rest_length, default_unit="m")),
    ]
    if min(lengths) <= 0:
        raise ConfigurationError("All cable rest lengths must be positive.")
    if not abs(lengths[0] - lengths[1]) < d < lengths[0] + lengths[1]:
        # Elasticity may rescue a slightly infeasible rest geometry, but a gross violation is not a
        # meaningful default start.  Allow up to 2% tensile accommodation.
        if not abs(lengths[0] - lengths[1]) < d < 1.02 * (lengths[0] + lengths[1]):
            raise ConfigurationError(
                "Upper-cable rest lengths and support spacing cannot form a viable fixed-knot Y geometry."
            )

    positive_fields = {
        "junction.mass": finite_scalar(cfg.junction.mass, unit="kg", name="junction.mass"),
        "bob.mass": finite_scalar(cfg.bob.mass, unit="kg", name="bob.mass"),
        "bob.radius": finite_scalar(cfg.bob.radius, unit="m", name="bob.radius"),
    }
    for name, val in positive_fields.items():
        if float(val) <= 0:
            raise ConfigurationError(f"{name} must be strictly positive.")

    for name, cable in (
        ("upper_A", cfg.cables.upper_A),
        ("upper_B", cfg.cables.upper_B),
        ("lower", cfg.cables.lower),
    ):
        vals = {
            "diameter": finite_scalar(cable.diameter, unit="m", name=f"cables.{name}.diameter"),
            "density": finite_scalar(cable.density, unit="kg/m^3", name=f"cables.{name}.density"),
            "young_modulus": finite_scalar(cable.young_modulus, unit="Pa", name=f"cables.{name}.young_modulus"),
        }
        for field, val in vals.items():
            if float(val) <= 0:
                raise ConfigurationError(f"cables.{name}.{field} must be positive.")
        if float(to_si(cable.axial_viscosity, default_unit="Pa*s")) < 0:
            raise ConfigurationError(f"cables.{name}.axial_viscosity cannot be negative.")
        if not math.isfinite(float(cable.drag_cd_normal)) or cable.drag_cd_normal < 0.0:
            raise ConfigurationError(f"cables.{name}.drag_cd_normal must be finite/non-negative.")
        if not math.isfinite(float(cable.drag_cd_tangent)) or cable.drag_cd_tangent < 0.0:
            raise ConfigurationError(f"cables.{name}.drag_cd_tangent must be finite/non-negative.")
        for drag_field in (
            "drag_linear_normal_per_length",
            "drag_linear_tangent_per_length",
        ):
            coefficient = finite_scalar(
                getattr(cable, drag_field),
                unit="N*s/m^2",
                name=f"cables.{name}.{drag_field}",
            )
            if coefficient < 0.0:
                raise ConfigurationError(
                    f"cables.{name}.{drag_field} must be non-negative."
                )
        if cable.material_model == "tabulated_tension_extension":
            calibration_length = (
                cable.rest_length
                if cable.table_calibration_length is None
                else cable.table_calibration_length
            )
            if float(to_si(calibration_length, default_unit="m")) <= 0.0:
                raise ConfigurationError(
                    f"cables.{name}.table_calibration_length must be positive."
                )

    passive_fields = {
        "environment.air_density": finite_scalar(
            cfg.environment.air_density,
            unit="kg/m^3",
            name="environment.air_density",
        ),
        "junction.drag_linear": finite_scalar(
            cfg.junction.drag_linear,
            unit="N*s/m",
            name="junction.drag_linear",
        ),
        "bob.drag.cd": finite_scalar(
            cfg.bob.drag.cd,
            unit="dimensionless",
            name="bob.drag.cd",
        ),
        "bob.drag.linear_coefficient": finite_scalar(
            cfg.bob.drag.linear_coefficient,
            unit="N*s/m",
            name="bob.drag.linear_coefficient",
        ),
    }
    for name, value in passive_fields.items():
        if value < 0.0:
            raise ConfigurationError(f"{name} must be non-negative for passive aerodynamics.")

    if cfg.initial_condition.type in {"static_equilibrium", "cartesian_release"}:
        moving_support = False
        for support in (cfg.supports.A, cfg.supports.B):
            if support.type == "prescribed" and support.motion is not None:
                amplitude = as_vector3(support.motion.amplitude, default_unit="m")
                frequency = finite_scalar(
                    support.motion.frequency,
                    unit="Hz",
                    name="support.motion.frequency",
                )
                moving_support |= bool(np.linalg.norm(amplitude) > 0.0 and frequency > 0.0)
                moving_support |= support.motion.model == "table"
        if moving_support and cfg.run.mode == "high_fidelity":
            raise ConfigurationError(
                f"HF {cfg.initial_condition.type} uses conservative rod preparation "
                "and requires stationary supports; use a direct endpoint protocol "
                "for prescribed support motion."
            )
        air_speed = float(np.linalg.norm(as_vector3(cfg.environment.air_velocity, default_unit="m/s")))
        aerodynamic_coupling = (
            cfg.bob.drag.enabled
            or passive_fields["junction.drag_linear"] > 0.0
            or any(
                cable.drag_enabled
                for cable in (cfg.cables.upper_A, cfg.cables.upper_B, cfg.cables.lower)
            )
        )
        if air_speed > 0.0 and aerodynamic_coupling:
            raise ConfigurationError(
                f"{cfg.initial_condition.type} currently means a gravity-only conservative "
                "rod preparation and therefore rejects non-zero wind with active drag. "
                "Use a direct endpoint protocol or disable wind."
            )

    if cfg.run.mode in {"full", "high_fidelity"}:
        minimum = (12, 12, 20) if cfg.solver.profile == "quick" else (20, 20, 30)
        actual = (
            cfg.cables.upper_A.elements,
            cfg.cables.upper_B.elements,
            cfg.cables.lower.elements,
        )
        if any(
            value < required
            for value, required in zip(actual, minimum, strict=True)
        ):
            if not cfg.solver.allow_subminimum_mesh:
                raise ConfigurationError(
                    "H1 mesh is below the frozen minimum "
                    f"{minimum[0]}/{minimum[1]}/{minimum[2]} for profile="
                    f"{cfg.solver.profile}; got {actual[0]}/{actual[1]}/{actual[2]}. "
                    "Use a compliant mesh for scientific runs.  "
                    "Set solver.allow_subminimum_mesh=true only for explicit smoke/unit tests."
                )
            if cfg.run.claim_level not in {"DERIVED", "VERIFIED"}:
                raise ConfigurationError(
                    "A subminimum mesh override cannot be used for CALIBRATED, VALIDATED, "
                    "PREDICTIVE or OUT_OF_SCOPE claims."
                )

    total_elements = sum(
        cable.elements for cable in (cfg.cables.upper_A, cfg.cables.upper_B, cfg.cables.lower)
    )
    if any(
        cable.elements > _HF_MAX_RUNTIME_BRANCH_ELEMENTS
        for cable in (cfg.cables.upper_A, cfg.cables.upper_B, cfg.cables.lower)
    ) or total_elements > _HF_MAX_RUNTIME_TOTAL_ELEMENTS:
        raise ConfigurationError(
            "Cable mesh exceeds the research-program resource contract "
            f"({_HF_MAX_RUNTIME_BRANCH_ELEMENTS} per branch, "
            f"{_HF_MAX_RUNTIME_TOTAL_ELEMENTS} total)."
        )
    if cfg.run.mode == "high_fidelity":
        supported_initial_conditions = {
            "static_equilibrium",
            "cartesian_release",
            "geometric_direct_release",
            "held_endpoint_equilibrium_release",
        }
        if cfg.initial_condition.type not in supported_initial_conditions:
            code = "HF_INITIAL_CONDITION_PROTOCOL_UNSUPPORTED"
            details = {
                "requested": cfg.initial_condition.type,
                "supported": sorted(supported_initial_conditions),
            }
            raise ConfigurationError(
                f"{code}: {json.dumps(details, sort_keys=True)}",
                code=code,
                details=details,
            )
        consumed_initial_fields = _HF_INITIAL_CONDITION_CONSUMED_FIELDS[
            cfg.initial_condition.type
        ]
        unconsumed_initial_fields = sorted(
            cfg.initial_condition.model_fields_set - consumed_initial_fields
        )
        if unconsumed_initial_fields:
            code = "HF_INITIAL_CONDITION_FIELDS_UNCONSUMED"
            details = {
                "protocol": cfg.initial_condition.type,
                "unconsumed_explicit_fields": unconsumed_initial_fields,
                "consumed_fields": sorted(consumed_initial_fields),
            }
            raise ConfigurationError(
                f"{code}: {json.dumps(details, sort_keys=True)}",
                code=code,
                details=details,
            )
        initial_vector_units = {
            "bob_position": "m",
            "junction_position": "m",
            "bob_velocity": "m/s",
            "junction_velocity": "m/s",
            "bob_angular_velocity": "rad/s",
        }
        for field in consumed_initial_fields & initial_vector_units.keys():
            value = getattr(cfg.initial_condition, field)
            if value is not None:
                as_vector3(value, default_unit=initial_vector_units[field])
        if cfg.initial_condition.type in {
            "static_equilibrium",
            "cartesian_release",
        } and np.linalg.norm(
            as_vector3(
                cfg.initial_condition.junction_velocity,
                default_unit="m/s",
            )
        ) > 0.0:
            raise ConfigurationError(
                f"HF {cfg.initial_condition.type} does not consume a non-zero "
                "junction_velocity; use a direct/held endpoint protocol."
            )
        if (
            cfg.initial_condition.type == "held_endpoint_equilibrium_release"
            and cfg.solver.static.method != "energy_minimize"
        ):
            raise ConfigurationError(
                "HF held_endpoint_equilibrium_release requires "
                "solver.static.method=energy_minimize; continuation_newton is not "
                "silently substituted."
            )
        if cfg.initial_condition.type == "held_endpoint_equilibrium_release":
            if cfg.supports.A.type != "fixed" or cfg.supports.B.type != "fixed":
                raise ConfigurationError(
                    "HF held_endpoint_equilibrium_release currently requires fixed "
                    "supports so its conservative energy gradient matches force."
                )
            held_aerodynamic_coupling = (
                cfg.bob.drag.enabled
                or finite_scalar(
                    cfg.junction.drag_linear,
                    unit="N*s/m",
                    name="junction.drag_linear",
                )
                > 0.0
                or any(
                    cable.drag_enabled
                    for cable in (
                        cfg.cables.upper_A,
                        cfg.cables.upper_B,
                        cfg.cables.lower,
                    )
                )
            )
            if (
                np.linalg.norm(
                    as_vector3(
                        cfg.environment.air_velocity,
                        default_unit="m/s",
                    )
                )
                > 0.0
                and held_aerodynamic_coupling
            ):
                raise ConfigurationError(
                    "HF held endpoint equilibrium is conservative and rejects "
                    "non-zero wind with active aerodynamic coupling."
                )
            held_major_iterations_per_seed = (
                cfg.solver.static.continuation_steps
                * cfg.solver.static.max_iterations
                + max(20, 2 * cfg.solver.static.max_iterations)
                + cfg.solver.static.max_iterations
            )
            held_iteration_budget = (
                _HF_HELD_SEED_UPPER_BOUND
                * held_major_iterations_per_seed
            )
            if held_iteration_budget > _HF_MAX_HELD_OPTIMIZER_ITERATION_BUDGET:
                code = "HF_STATIC_PREPARATION_BUDGET_EXCEEDED"
                details = {
                    "seed_upper_bound": _HF_HELD_SEED_UPPER_BOUND,
                    "gravity_continuation_steps": (
                        cfg.solver.static.continuation_steps
                    ),
                    "max_iterations_per_minimize": (
                        cfg.solver.static.max_iterations
                    ),
                    "krylov_polish_iteration_bound_per_seed": max(
                        20, 2 * cfg.solver.static.max_iterations
                    ),
                    "negative_curvature_escape_iteration_bound_per_seed": (
                        cfg.solver.static.max_iterations
                    ),
                    "major_iterations_per_seed": (
                        held_major_iterations_per_seed
                    ),
                    "optimizer_iteration_budget": held_iteration_budget,
                    "optimizer_iteration_limit": (
                        _HF_MAX_HELD_OPTIMIZER_ITERATION_BUDGET
                    ),
                }
                raise ConfigurationError(
                    f"{code}: {json.dumps(details, sort_keys=True)}",
                    code=code,
                    details=details,
                )
        if total_elements > 384:
            raise ConfigurationError(
                "The current dense-Jacobian HF integrator is limited to 384 material beads."
            )
        if cfg.solver.method == "Newmark":
            raise ConfigurationError(
                "HF rigid-bob quaternion dynamics support Radau or BDF, not legacy Newmark."
            )
        if any(
            cable.material_model != "linear_kelvin_voigt_tension_only"
            for cable in (cfg.cables.upper_A, cfg.cables.upper_B, cfg.cables.lower)
        ):
            raise ConfigurationError(
                "HF-DISCRETE-ROD-RIGID-BOB-1.0 currently supports only its registered "
                "local Kelvin-Voigt parameter source; tabulated FWD materials are not "
                "reused.  In HF, high_fidelity.axial_material_model owns the actual "
                "passive unilateral/bilateral constitutive branch."
            )
        if cfg.run.claim_level not in {"DERIVED", "VERIFIED", "OUT_OF_SCOPE"}:
            raise ConfigurationError(
                "The independent HF backend has no sealed experimental campaign yet; "
                "its claim level is capped at VERIFIED."
            )
        clearance = finite_scalar(
            cfg.high_fidelity.minimum_clearance,
            unit="m",
            name="high_fidelity.minimum_clearance",
        )
        if clearance < 0.0:
            raise ConfigurationError("high_fidelity.minimum_clearance must be non-negative.")
        quaternion_stabilization_rate = finite_scalar(
            cfg.high_fidelity.quaternion_stabilization_rate,
            unit="1/s",
            name="high_fidelity.quaternion_stabilization_rate",
        )
        if not 0.0 <= quaternion_stabilization_rate <= 1.0e6:
            raise ConfigurationError(
                "high_fidelity.quaternion_stabilization_rate must lie in [0,1e6] 1/s."
            )
        controlled_limit_scales = {
            "bending_stiffness_scale": (
                cfg.high_fidelity.bending_stiffness_scale
            ),
            "compression_regularization_scale": (
                cfg.high_fidelity.compression_regularization_scale
            ),
            "bob_attachment_radius_fraction": (
                cfg.high_fidelity.bob_attachment_radius_fraction
            ),
            "bob_contact_radius_fraction": (
                cfg.high_fidelity.bob_contact_radius_fraction
            ),
        }
        nonproduction_scales = {
            name: value
            for name, value in controlled_limit_scales.items()
            if value != 1.0
        }
        if (
            not cfg.high_fidelity.controlled_limit_study
            and nonproduction_scales
        ):
            code = "HF_PRODUCTION_SCALE_IDENTITY_MISMATCH"
            details = {
                "required_value": 1.0,
                "nonproduction_scales": nonproduction_scales,
            }
            raise ConfigurationError(
                f"{code}: Formal HF runs freeze compression_regularization_scale=1 "
                "and every other controlled-limit physics scale/fraction=1; "
                "non-production limits require controlled_limit_study=true. "
                f"Observed {json.dumps(details, sort_keys=True)}",
                code=code,
                details=details,
            )
        if (
            cfg.high_fidelity.controlled_limit_study
            and cfg.run.claim_level != "OUT_OF_SCOPE"
        ):
            raise ConfigurationError(
                "A high_fidelity.controlled_limit_study must use "
                "run.claim_level=OUT_OF_SCOPE; it is not a production HF candidate."
            )
        invalid_controlled_scales = {
            name: value
            for name, value in controlled_limit_scales.items()
            if not _HF_MIN_CONTROLLED_LIMIT_SCALE <= value <= 1.0
        }
        if cfg.high_fidelity.controlled_limit_study and invalid_controlled_scales:
            raise ConfigurationError(
                "A controlled HF limit candidate requires every registered physics "
                "scale/fraction in "
                f"[{_HF_MIN_CONTROLLED_LIMIT_SCALE:.1e},1]; smaller/exact-zero "
                "values are mathematical endpoints, not representable formal "
                "candidates. Invalid values: "
                f"{json.dumps(invalid_controlled_scales, sort_keys=True)}"
            )
        if not (
            _HF_MIN_BOB_INERTIA_FACTOR
            <= cfg.high_fidelity.bob_inertia_factor
            <= 2.0 / 3.0
        ):
            code = "HF_BOB_INERTIA_FACTOR_OUT_OF_EXECUTABLE_RANGE"
            details = {
                "value": cfg.high_fidelity.bob_inertia_factor,
                "minimum": _HF_MIN_BOB_INERTIA_FACTOR,
                "maximum": 2.0 / 3.0,
            }
            raise ConfigurationError(
                f"{code}: {json.dumps(details, sort_keys=True)}",
                code=code,
                details=details,
            )
        bob_mass = float(to_si(cfg.bob.mass, default_unit="kg"))
        bob_radius = float(to_si(cfg.bob.radius, default_unit="m"))
        derived_hf_values = {
            "bob_inertia_kg_m2": _float_product(
                cfg.high_fidelity.bob_inertia_factor,
                bob_mass,
                bob_radius,
                bob_radius,
            ),
            "bob_attachment_radius_m": _float_product(
                cfg.high_fidelity.bob_attachment_radius_fraction,
                bob_radius,
            ),
            "bob_contact_radius_m": _float_product(
                cfg.high_fidelity.bob_contact_radius_fraction,
                bob_radius,
            ),
        }
        for name, cable in (
            ("upper_A", cfg.cables.upper_A),
            ("upper_B", cfg.cables.upper_B),
            ("lower", cfg.cables.lower),
        ):
            diameter = float(to_si(cable.diameter, default_unit="m"))
            density = float(to_si(cable.density, default_unit="kg/m^3"))
            young = float(to_si(cable.young_modulus, default_unit="Pa"))
            length = float(to_si(cable.rest_length, default_unit="m"))
            area = _float_product(math.pi / 4.0, diameter, diameter)
            second_moment = _float_product(
                math.pi / 64.0,
                diameter,
                diameter,
                diameter,
                diameter,
            )
            derived_hf_values.update(
                {
                    f"{name}.area_m2": area,
                    f"{name}.EA_N": _float_product(young, area),
                    f"{name}.EI_N_m2": _float_product(
                        cfg.high_fidelity.bending_stiffness_scale,
                        young,
                        second_moment,
                    ),
                    f"{name}.material_bead_mass_kg": _float_product(
                        density,
                        area,
                        length,
                        1.0 / cable.elements,
                    ),
                }
            )
        invalid_derived_hf_values = {
            name: value
            for name, value in derived_hf_values.items()
            if not math.isfinite(value) or value <= 0.0
        }
        if invalid_derived_hf_values:
            code = "HF_DERIVED_PHYSICS_NOT_REPRESENTABLE"
            details = {"invalid_derived_values": invalid_derived_hf_values}
            raise ConfigurationError(
                f"{code}: {json.dumps(details, sort_keys=True)}",
                code=code,
                details=details,
            )
        if (
            cfg.initial_condition.type == "held_endpoint_equilibrium_release"
            and cfg.high_fidelity.compression_regularization_scale != 1.0
        ):
            code = "HF_HELD_PREPARATION_REQUIRES_BILATERAL_ROD"
            details = {
                "compression_regularization_scale": (
                    cfg.high_fidelity.compression_regularization_scale
                ),
                "required": 1.0,
            }
            raise ConfigurationError(
                f"{code}: held endpoint equilibrium preparation is registered only "
                "for the full bilateral rod (compression_regularization_scale=1).",
                code=code,
                details=details,
            )
        if not cfg.high_fidelity.contact_guard_enabled:
            raise ConfigurationError(
                "Formal HF runs require high_fidelity.contact_guard_enabled=true."
            )
        if np.linalg.norm(
            as_vector3(cfg.environment.gravity, default_unit="m/s^2")
        ) <= 0.0:
            code = "HF_NONZERO_GRAVITY_REQUIRED"
            raise ConfigurationError(
                f"{code}: the gravitational HF pendulum requires non-zero gravity.",
                code=code,
                details={"gravity_norm_m_s2": 0.0},
            )
        resource_estimate = _high_fidelity_resource_estimate(
            cfg,
            t_end=finite_scalar(cfg.solver.t_end, unit="s", name="solver.t_end"),
            output_dt=finite_scalar(
                cfg.solver.output_dt, unit="s", name="solver.output_dt"
            ),
        )
        if (
            resource_estimate["output_samples"]
            > resource_estimate["output_sample_limit"]
            or resource_estimate["accepted_step_budget"]
            > resource_estimate["accepted_step_limit"]
            or resource_estimate["estimated_peak_memory_bytes"]
            > resource_estimate["peak_memory_limit_bytes"]
            or resource_estimate["estimated_result_bytes"]
            > resource_estimate["result_limit_bytes"]
        ):
            code = "HF_RESOURCE_BUDGET_EXCEEDED"
            raise ConfigurationError(
                f"{code}: {json.dumps(resource_estimate, sort_keys=True)}",
                code=code,
                details=resource_estimate,
            )

    newmark_force_tol = float(
        to_si(cfg.solver.newmark_force_tolerance, default_unit="N")
    )
    if newmark_force_tol <= 0:
        raise ConfigurationError("solver.newmark_force_tolerance must be positive.")

    t_end = finite_scalar(cfg.solver.t_end, unit="s", name="solver.t_end")
    output_dt = finite_scalar(cfg.solver.output_dt, unit="s", name="solver.output_dt")
    if t_end <= 0 or output_dt <= 0 or output_dt > t_end:
        raise ConfigurationError("Require 0 < output_dt <= t_end.")
    sample_count = t_end / output_dt
    if (
        not math.isfinite(sample_count)
        or sample_count > _HF_MAX_OUTPUT_SAMPLES - 1
    ):
        raise ConfigurationError(
            "Requested output grid exceeds the frozen limit of "
            f"{_HF_MAX_OUTPUT_SAMPLES:,} samples."
        )
    if cfg.solver.max_step != "auto":
        max_step = finite_scalar(cfg.solver.max_step, unit="s", name="solver.max_step")
        if max_step <= 0.0 or t_end / max_step > 20_000_000:
            raise ConfigurationError(
                "Require positive max_step and at most 20,000,000 nominal time steps."
            )
    if cfg.solver.rtol is not None:
        if not math.isfinite(cfg.solver.rtol) or not 2.3e-14 <= cfg.solver.rtol < 1.0:
            raise ConfigurationError("solver.rtol must lie in [2.3e-14, 1).")
    for field, unit in (
        ("position_atol", "m"),
        ("velocity_atol", "m/s"),
        ("angular_velocity_atol", "rad/s"),
    ):
        value = getattr(cfg.solver, field)
        if value is not None and finite_scalar(value, unit=unit, name=f"solver.{field}") <= 0.0:
            raise ConfigurationError(f"solver.{field} must be strictly positive.")
    if cfg.solver.quaternion_atol is not None and (
        not math.isfinite(cfg.solver.quaternion_atol)
        or cfg.solver.quaternion_atol <= 0.0
    ):
        raise ConfigurationError("solver.quaternion_atol must be finite and positive.")
    if not 1 <= cfg.solver.static.max_iterations <= 10_000:
        raise ConfigurationError("solver.static.max_iterations must lie in [1,10000].")
    if not 2 <= cfg.solver.static.continuation_steps <= 8:
        raise ConfigurationError(
            "solver.static.continuation_steps must lie in [2,8]; HF held preparation "
            "uses it as the conservative gravity-load continuation count."
        )
    minimum_line_search_fraction = (
        _HF_MIN_LINE_SEARCH_FRACTION
        if cfg.run.mode == "high_fidelity"
        else 0.0
    )
    if not minimum_line_search_fraction < cfg.solver.static.line_search_min <= 1.0:
        raise ConfigurationError(
            "solver.static.line_search_min must lie in (0,1]"
            + (
                " and exceed the HF executable lower bound "
                f"{_HF_MIN_LINE_SEARCH_FRACTION:.17g}."
                if cfg.run.mode == "high_fidelity"
                else "."
            )
        )
    static_force_tolerance = finite_scalar(
        cfg.solver.static.force_tolerance,
        unit="N",
        name="solver.static.force_tolerance",
    )
    if static_force_tolerance <= 0.0:
        raise ConfigurationError(
            "solver.static.force_tolerance must be finite and strictly positive."
        )

    p, q = cfg.analysis.target_ratio
    if math.gcd(p, q) != 1:
        raise ConfigurationError("target_ratio must contain coprime integers.")

    if cfg.run.claim_level in {"VALIDATED", "PREDICTIVE"}:
        if not cfg.run.validation_manifest:
            raise ConfigurationError(
                f"claim_level={cfg.run.claim_level} requires a validation_manifest."
            )
        try:
            load_validation_manifest(
                cfg.run.validation_manifest,
                config_source=cfg.source_path,
                requested_claim=cfg.run.claim_level,
            )
        except ValueError as exc:
            raise ConfigurationError(f"Invalid validation_manifest: {exc}") from exc
    if cfg.run.claim_level == "PREDICTIVE":
        suspect: list[str] = []
        physical_values = [
            ("junction.mass", cfg.junction.mass),
            ("bob.mass", cfg.bob.mass),
            ("bob.radius", cfg.bob.radius),
            ("upper_A.E", cfg.cables.upper_A.young_modulus),
            ("upper_B.E", cfg.cables.upper_B.young_modulus),
            ("lower.E", cfg.cables.lower.young_modulus),
        ]
        for name, value in physical_values:
            src = source_of(value)
            if src in {None, "assumed", "fitted_target"}:
                suspect.append(name)
        if suspect:
            raise ConfigurationError(
                "PREDICTIVE claim rejected because parameters lack independent provenance: "
                + ", ".join(suspect)
            )


def resolved_config_dict(cfg: SimulationConfig) -> dict[str, Any]:
    """Return a JSON/YAML-safe SI representation used for run provenance."""

    def q(v: Any, unit: str) -> Any:
        x = to_si(v, default_unit=unit)
        return np.asarray(x).tolist() if isinstance(x, np.ndarray) else float(x)

    out = cfg.model_dump(mode="python", exclude={"source_path"})
    out["environment"]["gravity"] = q(cfg.environment.gravity, "m/s^2")
    out["environment"]["air_density"] = q(cfg.environment.air_density, "kg/m^3")
    out["environment"]["air_velocity"] = q(cfg.environment.air_velocity, "m/s")
    for key, support in (("A", cfg.supports.A), ("B", cfg.supports.B)):
        out["supports"][key]["position"] = q(support.position, "m")
        if support.motion:
            out["supports"][key]["motion"]["amplitude"] = q(support.motion.amplitude, "m")
            out["supports"][key]["motion"]["frequency"] = q(support.motion.frequency, "Hz")
            out["supports"][key]["motion"]["phase"] = q(support.motion.phase, "rad")
    out["junction"]["mass"] = q(cfg.junction.mass, "kg")
    out["junction"]["drag_linear"] = q(cfg.junction.drag_linear, "N*s/m")
    out["bob"]["mass"] = q(cfg.bob.mass, "kg")
    out["bob"]["radius"] = q(cfg.bob.radius, "m")
    out["bob"]["drag"]["cd"] = q(cfg.bob.drag.cd, "dimensionless")
    out["bob"]["drag"]["linear_coefficient"] = q(
        cfg.bob.drag.linear_coefficient, "N*s/m"
    )
    for name in ("upper_A", "upper_B", "lower"):
        cable = getattr(cfg.cables, name)
        target = out["cables"][name]
        target["rest_length"] = q(cable.rest_length, "m")
        target["diameter"] = q(cable.diameter, "m")
        target["density"] = q(cable.density, "kg/m^3")
        target["young_modulus"] = q(cable.young_modulus, "Pa")
        target["axial_viscosity"] = q(cable.axial_viscosity, "Pa*s")
        target["drag_linear_normal_per_length"] = q(
            cable.drag_linear_normal_per_length, "N*s/m^2"
        )
        target["drag_linear_tangent_per_length"] = q(
            cable.drag_linear_tangent_per_length, "N*s/m^2"
        )
        if cable.table_calibration_length is not None:
            target["table_calibration_length"] = q(
                cable.table_calibration_length, "m"
            )
    out["initial_condition"]["phi"] = q(cfg.initial_condition.phi, "rad")
    out["initial_condition"]["theta"] = q(cfg.initial_condition.theta, "rad")
    out["initial_condition"]["phi_dot"] = q(cfg.initial_condition.phi_dot, "rad/s")
    out["initial_condition"]["theta_dot"] = q(cfg.initial_condition.theta_dot, "rad/s")
    out["initial_condition"]["bob_velocity"] = q(cfg.initial_condition.bob_velocity, "m/s")
    out["initial_condition"]["junction_velocity"] = q(
        cfg.initial_condition.junction_velocity, "m/s"
    )
    out["initial_condition"]["bob_angular_velocity"] = q(
        cfg.initial_condition.bob_angular_velocity, "rad/s"
    )
    if cfg.initial_condition.bob_position is not None:
        out["initial_condition"]["bob_position"] = q(
            cfg.initial_condition.bob_position, "m"
        )
    if cfg.initial_condition.junction_position is not None:
        out["initial_condition"]["junction_position"] = q(
            cfg.initial_condition.junction_position, "m"
        )
    if cfg.run.mode == "high_fidelity":
        hf_initial_fields = _HF_INITIAL_CONDITION_CONSUMED_FIELDS[
            cfg.initial_condition.type
        ]
        out["initial_condition"] = {
            name: value
            for name, value in out["initial_condition"].items()
            if name in hf_initial_fields
        }
    out["solver"]["t_end"] = q(cfg.solver.t_end, "s")
    out["solver"]["output_dt"] = q(cfg.solver.output_dt, "s")
    if cfg.solver.max_step != "auto":
        out["solver"]["max_step"] = q(cfg.solver.max_step, "s")
    if cfg.solver.position_atol is not None:
        out["solver"]["position_atol"] = q(cfg.solver.position_atol, "m")
    if cfg.solver.velocity_atol is not None:
        out["solver"]["velocity_atol"] = q(cfg.solver.velocity_atol, "m/s")
    if cfg.solver.angular_velocity_atol is not None:
        out["solver"]["angular_velocity_atol"] = q(
            cfg.solver.angular_velocity_atol, "rad/s"
        )
    out["solver"]["static"]["force_tolerance"] = q(
        cfg.solver.static.force_tolerance, "N"
    )
    out["solver"]["newmark_force_tolerance"] = q(
        cfg.solver.newmark_force_tolerance, "N"
    )
    out["analysis"]["phase_tolerance"] = q(cfg.analysis.phase_tolerance, "rad")
    out["high_fidelity"]["minimum_clearance"] = q(
        cfg.high_fidelity.minimum_clearance, "m"
    )
    out["high_fidelity"]["quaternion_stabilization_rate"] = q(
        cfg.high_fidelity.quaternion_stabilization_rate, "1/s"
    )
    return out

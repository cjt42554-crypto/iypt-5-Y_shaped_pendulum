"""Scale analysis, scope checks and scientific-claim readiness.

The diagnostics in this module are deliberately conservative.  They do not
replace a convergence study or an experimental validation; they identify when
an apparently precise run cannot support the requested observable or claim.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

import numpy as np

from ypendulum.config.models import SimulationConfig
from ypendulum.config.units import as_vector3, source_of, to_si
from ypendulum.geometry import reduced_geometry_from_loaded_state
from ypendulum.models.full_cable import FullCableModel
from ypendulum.models.state import SimulationResult, StaticEquilibrium


_INDEPENDENT_SOURCES = {
    "measured",
    "calibrated_independent",
    "independent_test",
    "datasheet",
    "literature_prior",
    "standard",
    "balance",
    "caliper",
}
_SUSPECT_SOURCES = {None, "assumed", "fitted_target"}
_CLAIM_ORDER = {
    "DERIVED": 0,
    "VERIFIED": 1,
    "CALIBRATED": 2,
    "VALIDATED": 3,
    "PREDICTIVE": 4,
    "OUT_OF_SCOPE": -1,
}


def _quantity_source_rows(cfg: SimulationConfig) -> list[dict[str, Any]]:
    """Return the physically consequential scalar/vector inputs and provenance."""

    rows: list[tuple[str, Any, bool, bool]] = [
        ("environment.gravity", cfg.environment.gravity, True, True),
        ("environment.air_density", cfg.environment.air_density, False, False),
        ("environment.air_velocity", cfg.environment.air_velocity, False, False),
        ("supports.A.position", cfg.supports.A.position, True, True),
        ("supports.B.position", cfg.supports.B.position, True, True),
        ("junction.mass", cfg.junction.mass, True, True),
        ("junction.drag_linear", cfg.junction.drag_linear, False, False),
        ("bob.mass", cfg.bob.mass, True, True),
        ("bob.radius", cfg.bob.radius, bool(cfg.bob.drag.enabled or cfg.bob.buoyancy), True),
        ("bob.drag.cd", cfg.bob.drag.cd, bool(cfg.bob.drag.enabled), False),
        (
            "bob.drag.linear_coefficient",
            cfg.bob.drag.linear_coefficient,
            bool(cfg.bob.drag.enabled),
            False,
        ),
    ]
    for name in ("upper_A", "upper_B", "lower"):
        cable = getattr(cfg.cables, name)
        rows.extend(
            [
                (f"cables.{name}.rest_length", cable.rest_length, True, True),
                (f"cables.{name}.diameter", cable.diameter, True, True),
                (f"cables.{name}.density", cable.density, True, True),
                (f"cables.{name}.young_modulus", cable.young_modulus, True, True),
                (
                    f"cables.{name}.axial_viscosity",
                    cable.axial_viscosity,
                    bool(float(to_si(cable.axial_viscosity, default_unit="Pa*s")) > 0.0),
                    False,
                ),
            ]
        )
        if cable.drag_enabled:
            # drag_cd_normal is a bare dimensionless scalar in the frozen schema.
            rows.append((f"cables.{name}.drag_cd_normal", None, True, False))
    if cfg.observer.type == "pinhole" and cfg.observer.camera is not None:
        camera = cfg.observer.camera
        rows.extend(
            [
                ("observer.camera.intrinsic_matrix", None, True, False),
                ("observer.camera.rotation_world_to_camera", None, True, False),
                (
                    "observer.camera.translation_world_to_camera",
                    camera.translation_world_to_camera,
                    True,
                    False,
                ),
                ("observer.camera.frame_rate", camera.frame_rate, True, False),
                ("observer.camera.exposure_time", camera.exposure_time, True, False),
            ]
        )
    return [
        {
            "parameter": name,
            "source": source_of(value),
            "active": active,
            "critical_for_low_frequency": critical,
        }
        for name, value, active, critical in rows
    ]


def parameter_provenance_audit(cfg: SimulationConfig) -> dict[str, Any]:
    rows = _quantity_source_rows(cfg)
    active = [row for row in rows if row["active"]]
    counts = Counter("missing" if row["source"] is None else row["source"] for row in active)
    missing = [row["parameter"] for row in active if row["source"] is None]
    assumed = [row["parameter"] for row in active if row["source"] == "assumed"]
    fitted_target = [row["parameter"] for row in active if row["source"] == "fitted_target"]
    critical_suspect = [
        row["parameter"]
        for row in active
        if row["critical_for_low_frequency"] and row["source"] in _SUSPECT_SOURCES
    ]
    independently_sourced = [
        row["parameter"] for row in active if row["source"] in _INDEPENDENT_SOURCES
    ]
    return {
        "active_parameter_count": len(active),
        "source_counts": dict(sorted(counts.items())),
        "missing_source": missing,
        "assumed": assumed,
        "fitted_target": fitted_target,
        "critical_suspect": critical_suspect,
        "independently_sourced": independently_sourced,
        "rows": active,
    }


def _effective_step(cfg: SimulationConfig, model: FullCableModel) -> float:
    times = model.characteristic_times()
    output_dt = float(to_si(cfg.solver.output_dt, default_unit="s"))
    step = times["pendulum_period_estimate"] / 200.0
    if cfg.solver.resolve_longitudinal_waves:
        step = min(step, times["minimum_element_wave_crossing"] / 20.0)
    if cfg.solver.max_step != "auto":
        step = float(to_si(cfg.solver.max_step, default_unit="s"))
    return min(step, output_dt)


def _initial_amplitude(cfg: SimulationConfig) -> tuple[float | None, float | None, str]:
    if cfg.initial_condition.type == "reduced_angles_release":
        phi = abs(float(to_si(cfg.initial_condition.phi, default_unit="rad")))
        theta = abs(float(to_si(cfg.initial_condition.theta, default_unit="rad")))
        return phi, theta, "configured_reduced_angles"
    if cfg.initial_condition.type == "static_equilibrium":
        return 0.0, 0.0, "static_equilibrium"
    return None, None, f"unknown_for_{cfg.initial_condition.type}"


def _classify(value: float | None, epsilon_required: float, *, structural: bool = False) -> str:
    if structural:
        return "structural_required"
    if value is None or not np.isfinite(value):
        return "unknown"
    if value >= 3.0 * epsilon_required:
        return "retain"
    if value >= 0.3 * epsilon_required:
        return "borderline"
    return "negligible"


def _claim_readiness(
    cfg: SimulationConfig,
    provenance: dict[str, Any],
    *,
    numerical_warnings: list[str],
    scope_findings: list[str],
) -> dict[str, Any]:
    requested = cfg.run.claim_level
    reasons: list[str] = []
    cap = "PREDICTIVE"
    if scope_findings:
        cap = "OUT_OF_SCOPE"
        reasons.extend(scope_findings)
    else:
        if provenance["critical_suspect"]:
            cap = "VERIFIED"
            reasons.append(
                "Critical geometry/mass/material parameters lack independent provenance: "
                + ", ".join(provenance["critical_suspect"])
            )
        elif provenance["assumed"] or provenance["fitted_target"] or provenance["missing_source"]:
            cap = "CALIBRATED"
            reasons.append(
                "Some active parameters are missing, assumed, or fitted on the target run."
            )
        if not cfg.run.validation_manifest and _CLAIM_ORDER[cap] > _CLAIM_ORDER["CALIBRATED"]:
            cap = "CALIBRATED"
            reasons.append("No frozen validation manifest is attached.")
        if cfg.solver.allow_subminimum_mesh and _CLAIM_ORDER[cap] > _CLAIM_ORDER["VERIFIED"]:
            cap = "VERIFIED"
            reasons.append("Subminimum H1 mesh is enabled.")
        if numerical_warnings and _CLAIM_ORDER[cap] > _CLAIM_ORDER["VERIFIED"]:
            cap = "VERIFIED"
            reasons.append("Numerical-observable resolution warnings remain unresolved.")

    if cap == "OUT_OF_SCOPE":
        requested_supported = requested == "OUT_OF_SCOPE"
    elif requested == "OUT_OF_SCOPE":
        requested_supported = False
        reasons.append("Configuration is not automatically identified as out of scope.")
    else:
        requested_supported = _CLAIM_ORDER[requested] <= _CLAIM_ORDER[cap]
        if not requested_supported:
            reasons.append(f"Requested {requested} exceeds configuration cap {cap}.")
    return {
        "requested_claim": requested,
        "configuration_claim_cap": cap,
        "requested_claim_supported": requested_supported,
        "reasons": reasons or ["No configuration-level blocker identified."],
        "note": (
            "This is a configuration and numerical-readiness cap, not an automatic upgrade. "
            "VALIDATED/PREDICTIVE still require sealed experimental evidence."
        ),
    }


def automatic_scale_diagnostics(
    cfg: SimulationConfig,
    model: FullCableModel | None = None,
    equilibrium: StaticEquilibrium | None = None,
    loaded_positions: np.ndarray | None = None,
) -> dict[str, Any]:
    """Return run-specific scale, scope, observability and claim diagnostics.

    ``equilibrium`` is optional because UI previews may call this before a full
    static solve.  In that case the mechanically informed H1 reference geometry
    is used and the report states that it is only an estimate.
    """

    model = FullCableModel(cfg) if model is None else model
    raw = model.diagnostics()
    p, _q = cfg.analysis.target_ratio
    phase_tol = float(to_si(cfg.analysis.phase_tolerance, default_unit="rad"))
    epsilon_req = phase_tol / (2.0 * math.pi * p * max(cfg.analysis.slow_period_count, 1))

    if loaded_positions is not None:
        positions = np.asarray(loaded_positions, dtype=float)
        geometry_state = "provided_loaded_state"
    elif equilibrium is not None:
        positions = np.asarray(equilibrium.positions, dtype=float)
        geometry_state = "static_equilibrium"
    else:
        positions = np.asarray(model.topology.reference_positions, dtype=float)
        geometry_state = "mechanically_informed_reference_guess"
    if positions.shape != (model.topology.node_count, 3):
        raise ValueError(
            f"loaded_positions must have shape {(model.topology.node_count, 3)}, got {positions.shape}."
        )
    element_vector = (
        positions[model.topology.elements.node_j]
        - positions[model.topology.elements.node_i]
    )
    element_length = np.linalg.norm(element_vector, axis=1)
    loaded_strain = np.maximum(
        element_length / model.topology.elements.rest_length - 1.0,
        0.0,
    )
    if geometry_state in {"static_equilibrium", "provided_loaded_state"}:
        extension_estimate = float(np.max(loaded_strain))
        extension_estimate_source = geometry_state
    else:
        extension_estimate = float(raw["epsilon_extension_estimate"])
        extension_estimate_source = "conservative_force_scale_bound"
    A = positions[model.topology.support_nodes[0]]
    B = positions[model.topology.support_nodes[1]]
    J = positions[model.topology.junction_node]
    P = positions[model.topology.bob_node]
    loaded_geometry = reduced_geometry_from_loaded_state(A, B, J, model.gravity)
    lower_loaded = float(np.linalg.norm(P - J))
    slow_length = max(loaded_geometry.h + lower_loaded, 1e-15)
    gmag = float(np.linalg.norm(model.gravity))
    omega_fast = math.sqrt(gmag / max(lower_loaded, 1e-15))
    omega_slow = math.sqrt(gmag / slow_length)
    frequency_fast = omega_fast / (2.0 * math.pi)
    frequency_slow = omega_slow / (2.0 * math.pi)
    characteristic_length = slow_length

    phi, theta, amplitude_source = _initial_amplitude(cfg)
    if phi is None or theta is None:
        amplitude = None
        finite_amplitude = None
    else:
        amplitude = max(phi, theta)
        # Conservative order-of-magnitude bound including cross-frequency terms.
        finite_amplitude = max(phi * phi, theta * theta) * 3.0 / 16.0

    cable_mass = float(np.sum(model.topology.elements.element_mass))
    bob_mass = model.bob_mass
    junction_ratio = model.junction_mass / bob_mass
    string_ratio = cable_mass / bob_mass
    radius = float(to_si(cfg.bob.radius, default_unit="m"))
    radius_ratio = radius / characteristic_length

    times = model.characteristic_times()
    output_dt = float(to_si(cfg.solver.output_dt, default_unit="s"))
    t_end = float(to_si(cfg.solver.t_end, default_unit="s"))
    internal_max_step = _effective_step(cfg, model)
    minimum_crossing = times["minimum_element_wave_crossing"]
    output_samples_fast_period = 1.0 / max(frequency_fast * output_dt, 1e-30)
    output_samples_slow_period = 1.0 / max(frequency_slow * output_dt, 1e-30)
    slow_cycles = t_end * frequency_slow
    internal_steps_crossing = minimum_crossing / max(internal_max_step, 1e-30)
    output_samples_crossing = minimum_crossing / max(output_dt, 1e-30)
    low_frequency_sampling_ok = output_samples_fast_period >= 20.0
    stationary_frequency_window_ok = slow_cycles >= 3.0
    wave_internal_ok = cfg.solver.resolve_longitudinal_waves and internal_steps_crossing >= 20.0
    wave_output_ok = output_samples_crossing >= 2.0
    retension_peak_ready = wave_internal_ok and wave_output_ok

    E = model.topology.elements.ea / model.topology.elements.area
    c_longitudinal = np.sqrt(E / model.topology.elements.density)
    cable_wave_eps: dict[str, float] = {}
    cable_loss_factor: dict[str, float] = {}
    for name, sl in model.topology.cable_slices.items():
        length = float(np.sum(model.topology.elements.rest_length[sl]))
        c_min = float(np.min(c_longitudinal[sl]))
        cable_wave_eps[name] = omega_fast * length / max(c_min, 1e-30)
        eta = model.topology.elements.eta_a[sl] / model.topology.elements.area[sl]
        young = E[sl]
        cable_loss_factor[name] = float(np.max(omega_fast * eta / young))

    support_amplitudes: list[float] = []
    for support in (cfg.supports.A, cfg.supports.B):
        if support.type == "prescribed" and support.motion is not None:
            support_amplitudes.append(
                float(np.linalg.norm(as_vector3(support.motion.amplitude, default_unit="m")))
            )
    support_ratio = max(support_amplitudes, default=0.0) / characteristic_length

    air_density = float(to_si(cfg.environment.air_density, default_unit="kg/m^3"))
    velocity_scale = (
        omega_fast * characteristic_length * amplitude
        if amplitude is not None
        else float("nan")
    )
    bob_drag_ratio: float | None = None
    string_drag_ratio: float | None = None
    if cfg.bob.drag.enabled and np.isfinite(velocity_scale):
        cd = float(to_si(cfg.bob.drag.cd, default_unit="dimensionless"))
        linear = float(to_si(cfg.bob.drag.linear_coefficient, default_unit="N*s/m"))
        drag = 0.5 * air_density * cd * math.pi * radius**2 * velocity_scale**2 + linear * velocity_scale
        bob_drag_ratio = drag / max(bob_mass * gmag, 1e-30)
    if any(getattr(cfg.cables, name).drag_enabled for name in ("upper_A", "upper_B", "lower")) and np.isfinite(velocity_scale):
        force = 0.0
        for name in ("upper_A", "upper_B", "lower"):
            cable = getattr(cfg.cables, name)
            if cable.drag_enabled:
                length = float(to_si(cable.rest_length, default_unit="m"))
                diameter = float(to_si(cable.diameter, default_unit="m"))
                force += 0.5 * air_density * cable.drag_cd_normal * diameter * length * velocity_scale**2
        string_drag_ratio = force / max(bob_mass * gmag, 1e-30)
    buoyancy_ratio = (
        air_density * (4.0 / 3.0) * math.pi * radius**3 / bob_mass if cfg.bob.buoyancy else 0.0
    )

    a_a = loaded_geometry.a_a
    a_b = loaded_geometry.a_b
    h = loaded_geometry.h
    if h > 1e-15 and min(a_a, a_b) > 0.0:
        fast_slack_limit = min(math.atan(a_a / h), math.atan(a_b / h))
    else:
        fast_slack_limit = 0.0
    slack_margin = None if phi is None else fast_slack_limit - phi

    natural_a = float(to_si(cfg.cables.upper_A.rest_length, default_unit="m"))
    natural_b = float(to_si(cfg.cables.upper_B.rest_length, default_unit="m"))
    support_spacing = float(np.linalg.norm(B - A))
    prestretch_geometry_fraction = max(support_spacing / (natural_a + natural_b) - 1.0, 0.0)

    effects = {
        "unilateral_tension_and_slack": {
            "estimate": None,
            "classification": "structural_required",
            "reason": "A loss of a serial tensile path changes the active mechanical topology.",
        },
        "finite_amplitude": {
            "estimate_relative_frequency_upper_scale": finite_amplitude,
            "classification": _classify(finite_amplitude, epsilon_req),
            "source": amplitude_source,
        },
        "junction_mass": {
            "estimate_mass_ratio": junction_ratio,
            "classification": _classify(junction_ratio, epsilon_req),
        },
        "string_mass": {
            "estimate_frequency_scale": string_ratio / 12.0,
            "mass_ratio": string_ratio,
            "classification": _classify(string_ratio / 12.0, epsilon_req),
        },
        "axial_extension": {
            "estimate_strain_scale": extension_estimate,
            "estimate_source": extension_estimate_source,
            "classification": _classify(extension_estimate, epsilon_req),
            "small_strain_assumption_warning": bool(extension_estimate > 0.02),
        },
        "longitudinal_wave_dynamics": {
            "estimate_omega_L_over_c": max(cable_wave_eps.values()),
            "per_cable": cable_wave_eps,
            "classification": (
                "retain"
                if cfg.solver.resolve_longitudinal_waves
                else _classify(max(cable_wave_eps.values()), epsilon_req)
            ),
        },
        "material_axial_loss": {
            "estimate_loss_factor": max(cable_loss_factor.values()),
            "per_cable": cable_loss_factor,
            "classification": _classify(max(cable_loss_factor.values()), epsilon_req),
        },
        "bob_finite_size": {
            "estimate_radius_over_length": radius_ratio,
            "classification": "negligible",
            "reason": (
                "The frozen core connects the cable force through the bob centre of mass. "
                "Radius affects aerodynamic area and buoyancy, not rigid-body inertia."
            ),
        },
        "bob_aerodynamics": {
            "estimate_force_over_weight": bob_drag_ratio,
            "classification": (
                "negligible"
                if not cfg.bob.drag.enabled
                else _classify(bob_drag_ratio, epsilon_req)
            ),
        },
        "string_aerodynamics": {
            "estimate_force_over_weight": string_drag_ratio,
            "classification": (
                "negligible"
                if not any(getattr(cfg.cables, name).drag_enabled for name in ("upper_A", "upper_B", "lower"))
                else _classify(string_drag_ratio, epsilon_req)
            ),
        },
        "buoyancy": {
            "estimate_displaced_air_mass_over_bob_mass": buoyancy_ratio,
            "classification": _classify(buoyancy_ratio, epsilon_req),
        },
        "prescribed_support_motion": {
            "estimate_amplitude_over_length": support_ratio,
            "classification": (
                "negligible" if support_ratio == 0.0 else _classify(support_ratio, epsilon_req)
            ),
        },
        "bending_and_torsion": {
            "estimate": None,
            "classification": "unknown",
            "reason": (
                "EI/GJ and connection moment transfer are outside the v1.0 input contract. "
                "The run is high-fidelity only within the axial-cable scope."
            ),
        },
    }

    numerical_warnings: list[str] = []
    if not low_frequency_sampling_ok:
        numerical_warnings.append(
            f"Only {output_samples_fast_period:.2f} stored samples per estimated fast period; low-frequency trajectory analysis is under-sampled."
        )
    if not stationary_frequency_window_ok:
        numerical_warnings.append(
            f"Only {slow_cycles:.2f} estimated slow cycles are simulated; stationary frequency/closure fitting is not supportable."
        )
    if cfg.solver.resolve_longitudinal_waves and not wave_internal_ok:
        numerical_warnings.append(
            f"Internal step resolves the fastest element wave crossing with only {internal_steps_crossing:.2f} steps (<20)."
        )
    if cfg.solver.resolve_longitudinal_waves and not wave_output_ok:
        numerical_warnings.append(
            f"Stored output has only {output_samples_crossing:.3g} samples per fastest wave crossing; retension peak output is aliased."
        )
    if not cfg.solver.resolve_longitudinal_waves:
        numerical_warnings.append(
            "Longitudinal-wave resolution is disabled; low-frequency motion may be studied after convergence, but retension peak and cable-wave claims are not resolved."
        )

    if extension_estimate > 0.02:
        numerical_warnings.append(
            f"Estimated tensile strain reaches {extension_estimate:.3%}; the default small-strain linear axial law requires independent calibration over this range or a tabulated material curve."
        )

    scope_findings: list[str] = []
    # The current schema cannot express eccentric attachment, bending stiffness,
    # self-contact or sliding.  We therefore avoid inventing an out-of-scope
    # finding unless a measurable geometric proxy already contradicts the core.
    gravity_axis_cosine = abs(
        float(np.dot((B - A) / np.linalg.norm(B - A), model.gravity / gmag))
    )
    if gravity_axis_cosine > 0.98:
        scope_findings.append(
            "Support axis is almost parallel to gravity; the conventional suspended Y branch and modal interpretation are ill-conditioned."
        )

    provenance = parameter_provenance_audit(cfg)
    claim = _claim_readiness(
        cfg,
        provenance,
        numerical_warnings=numerical_warnings,
        scope_findings=scope_findings,
    )

    return {
        "diagnostic_version": "1.1",
        "geometry_state": geometry_state,
        "epsilon_required_for_phase_budget": epsilon_req,
        "estimated_low_frequency": {
            "fast_hz": frequency_fast,
            "slow_hz": frequency_slow,
            "ratio": frequency_fast / frequency_slow,
            "fast_period_s": 1.0 / frequency_fast,
            "slow_period_s": 1.0 / frequency_slow,
        },
        "geometry": {
            "support_spacing_m": support_spacing,
            "loaded_upper_drop_m": h,
            "loaded_lower_length_m": lower_loaded,
            "characteristic_length_m": characteristic_length,
            "fast_slack_limit_rad_estimate": fast_slack_limit,
            "configured_fast_amplitude_rad": phi,
            "fast_slack_margin_rad_estimate": slack_margin,
            "natural_geometry_prestretch_fraction": prestretch_geometry_fraction,
            "gravity_support_axis_absolute_cosine": gravity_axis_cosine,
        },
        "dimensionless": {
            "epsilon_junction": junction_ratio,
            "epsilon_string_mass": string_ratio,
            "epsilon_extension_estimate": extension_estimate,
            "epsilon_extension_estimate_source": extension_estimate_source,
            "epsilon_amplitude_rad": amplitude,
            "epsilon_bob_radius": radius_ratio,
            "epsilon_support_motion": support_ratio,
            "epsilon_wave_max": max(cable_wave_eps.values()),
        },
        "effects": effects,
        "observability_and_resolution": {
            "simulation_duration_s": t_end,
            "stored_output_dt_s": output_dt,
            "effective_internal_max_step_s": internal_max_step,
            "estimated_slow_cycles": slow_cycles,
            "stored_samples_per_fast_period": output_samples_fast_period,
            "stored_samples_per_slow_period": output_samples_slow_period,
            "internal_steps_per_fastest_element_wave_crossing": internal_steps_crossing,
            "stored_samples_per_fastest_element_wave_crossing": output_samples_crossing,
            "low_frequency_sampling_ready": low_frequency_sampling_ok,
            "stationary_frequency_window_ready": stationary_frequency_window_ok,
            "longitudinal_wave_internal_ready": wave_internal_ok,
            "longitudinal_wave_output_ready": wave_output_ok,
            "retension_peak_prediction_ready": retension_peak_ready,
            "warnings": numerical_warnings,
        },
        "parameter_provenance": provenance,
        "scope_findings": scope_findings,
        "claim_readiness": claim,
        "raw_model_diagnostics": raw,
    }


def assess_result_validity(
    cfg: SimulationConfig,
    model: FullCableModel,
    result: SimulationResult,
    *,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess whether a completed H1 run supports its requested observables."""

    preflight = automatic_scale_diagnostics(cfg, model) if preflight is None else preflight
    findings: list[dict[str, Any]] = []
    max_energy = float(np.max(np.abs(result.energy["balance_residual"])))
    max_strain = float(np.max(np.maximum(result.stretch / model.topology.elements.rest_length[None, :], 0.0)))
    structural_events = [
        event
        for event in result.events
        if event.get("type")
        in {
            "cable_slack",
            "cable_retension",
            "cable_initially_not_fully_taut",
            "cable_fully_unloaded",
            "cable_first_local_retension",
            "upper_branch_switch",
        }
    ]
    if max_energy > (1e-6 if cfg.solver.profile == "reference" else 1e-4):
        findings.append(
            {
                "severity": "error",
                "code": "energy_balance_not_accepted",
                "value": max_energy,
            }
        )
    if max_strain > 0.02:
        findings.append(
            {
                "severity": "warning",
                "code": "small_axial_strain_assumption_stressed",
                "value": max_strain,
            }
        )
    if model.material_extrapolation_seen:
        findings.append(
            {
                "severity": "error",
                "code": "material_curve_extrapolated",
                "cables": sorted(model.material_extrapolation_seen),
            }
        )
    if structural_events:
        findings.append(
            {
                "severity": "info",
                "code": "structural_switching_present",
                "event_count": len(structural_events),
                "meaning": "A stationary two-frequency Lissajous fit is not globally valid.",
            }
        )
    if not preflight["observability_and_resolution"]["retension_peak_prediction_ready"] and any(
        event.get("type") in {"cable_retension", "cable_first_local_retension", "element_retension"}
        for event in result.events
    ):
        findings.append(
            {
                "severity": "error",
                "code": "retension_detected_but_peak_not_resolved",
            }
        )
    status = "pass"
    if any(item["severity"] == "error" for item in findings):
        status = "fail"
    elif findings:
        status = "conditional"
    return {
        "status": status,
        "max_abs_energy_balance_residual": max_energy,
        "maximum_tensile_strain": max_strain,
        "structural_event_count": len(structural_events),
        "findings": findings,
        "observable_support": {
            "low_frequency_motion": bool(
                preflight["observability_and_resolution"]["low_frequency_sampling_ready"]
            ),
            "stationary_two_frequency_fit": bool(
                preflight["observability_and_resolution"]["stationary_frequency_window_ready"]
                and not structural_events
            ),
            "cable_waveform": bool(
                preflight["observability_and_resolution"]["longitudinal_wave_internal_ready"]
                and preflight["observability_and_resolution"]["longitudinal_wave_output_ready"]
            ),
            "retension_peak": bool(
                preflight["observability_and_resolution"]["retension_peak_prediction_ready"]
            ),
        },
    }

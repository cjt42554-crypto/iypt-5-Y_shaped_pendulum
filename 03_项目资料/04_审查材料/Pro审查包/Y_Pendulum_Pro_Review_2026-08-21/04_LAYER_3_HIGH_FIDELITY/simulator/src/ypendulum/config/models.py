"""Pydantic configuration contract for YP-FPSim."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, strict=True)


class RunConfig(StrictModel):
    name: str = "ypendulum_run"
    mode: Literal["analytic", "torus", "full", "high_fidelity"] = "high_fidelity"
    seed: int = 20260818
    output_directory: str = "runs/ypendulum_run"
    claim_level: Literal[
        "DERIVED", "VERIFIED", "CALIBRATED", "VALIDATED", "PREDICTIVE", "OUT_OF_SCOPE"
    ] = "VERIFIED"
    validation_manifest: str | None = None


class EnvironmentConfig(StrictModel):
    gravity: Any = Field(default_factory=lambda: {"value": [0, 0, -9.80665], "unit": "m/s^2"})
    air_density: Any = Field(default_factory=lambda: {"value": 1.20, "unit": "kg/m^3"})
    air_velocity: Any = Field(default_factory=lambda: {"value": [0, 0, 0], "unit": "m/s"})


class PrescribedMotionConfig(StrictModel):
    model: Literal["stationary", "sinusoidal", "table"] = "stationary"
    amplitude: Any = Field(default_factory=lambda: {"value": [0, 0, 0], "unit": "m"})
    frequency: Any = Field(default_factory=lambda: {"value": 0.0, "unit": "Hz"})
    phase: Any = Field(default_factory=lambda: {"value": 0.0, "unit": "rad"})
    table_file: str | None = None
    table_calibration_length: Any | None = None


class SupportConfig(StrictModel):
    type: Literal["fixed", "prescribed"] = "fixed"
    position: Any
    motion: PrescribedMotionConfig | None = None

    @model_validator(mode="after")
    def prescribed_needs_motion(self) -> "SupportConfig":
        if self.type == "prescribed" and self.motion is None:
            raise ValueError("A prescribed support requires a motion block.")
        return self


class SupportsConfig(StrictModel):
    A: SupportConfig
    B: SupportConfig


class JunctionConfig(StrictModel):
    mass: Any
    drag_linear: Any = Field(default_factory=lambda: {"value": 0.0, "unit": "N*s/m"})


class DragConfig(StrictModel):
    enabled: bool = False
    model: Literal["quadratic", "linear", "quadratic_plus_linear"] = "quadratic_plus_linear"
    cd: Any = Field(default_factory=lambda: {"value": 0.47, "unit": "dimensionless"})
    linear_coefficient: Any = Field(default_factory=lambda: {"value": 0.0, "unit": "N*s/m"})


class BobConfig(StrictModel):
    mass: Any
    radius: Any
    drag: DragConfig = Field(default_factory=DragConfig)
    buoyancy: bool = False


class CableConfig(StrictModel):
    rest_length: Any
    diameter: Any
    density: Any
    young_modulus: Any
    axial_viscosity: Any = Field(default_factory=lambda: {"value": 0.0, "unit": "Pa*s"})
    elements: int = 12
    drag_cd_normal: float = 1.2
    drag_cd_tangent: float = 0.0
    drag_linear_normal_per_length: Any = Field(
        default_factory=lambda: {"value": 0.0, "unit": "N*s/m^2"}
    )
    drag_linear_tangent_per_length: Any = Field(
        default_factory=lambda: {"value": 0.0, "unit": "N*s/m^2"}
    )
    drag_enabled: bool = False
    material_model: Literal["linear_kelvin_voigt_tension_only", "tabulated_tension_extension"] = (
        "linear_kelvin_voigt_tension_only"
    )
    table_file: str | None = None
    table_calibration_length: Any | None = None

    @model_validator(mode="after")
    def validate_elements(self) -> "CableConfig":
        if self.elements < 1:
            raise ValueError("Cable element count must be at least one.")
        if self.material_model == "tabulated_tension_extension" and not self.table_file:
            raise ValueError("Tabulated cable material requires table_file.")
        return self


class CablesConfig(StrictModel):
    upper_A: CableConfig
    upper_B: CableConfig
    lower: CableConfig


class InitialConditionConfig(StrictModel):
    type: Literal[
        "static_equilibrium",
        "reduced_angles_release",
        "cartesian_release",
        "geometric_direct_release",
        "held_endpoint_equilibrium_release",
        "direct_state",
        "restart",
    ] = "static_equilibrium"
    phi: Any = Field(default_factory=lambda: {"value": 0.0, "unit": "rad"})
    theta: Any = Field(default_factory=lambda: {"value": 0.0, "unit": "rad"})
    phi_dot: Any = Field(default_factory=lambda: {"value": 0.0, "unit": "rad/s"})
    theta_dot: Any = Field(default_factory=lambda: {"value": 0.0, "unit": "rad/s"})
    bob_position: Any | None = None
    junction_position: Any | None = None
    bob_velocity: Any = Field(default_factory=lambda: {"value": [0, 0, 0], "unit": "m/s"})
    junction_velocity: Any = Field(
        default_factory=lambda: {"value": [0, 0, 0], "unit": "m/s"}
    )
    bob_angular_velocity: Any = Field(
        default_factory=lambda: {"value": [0, 0, 0], "unit": "rad/s"}
    )
    state_file: str | None = None
    positions_file: str | None = None
    velocities_file: str | None = None

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "InitialConditionConfig":
        if self.type == "restart" and self.state_file is None:
            raise ValueError("restart initial condition requires state_file.")
        if self.type == "cartesian_release" and self.bob_position is None:
            raise ValueError("cartesian_release requires bob_position.")
        if self.type == "geometric_direct_release" and (
            self.bob_position is None or self.junction_position is None
        ):
            raise ValueError(
                "geometric_direct_release requires bob_position and junction_position."
            )
        if self.type == "held_endpoint_equilibrium_release" and (
            self.bob_position is None or self.junction_position is None
        ):
            raise ValueError(
                "held_endpoint_equilibrium_release requires bob_position and "
                "junction_position."
            )
        if self.type == "direct_state" and self.positions_file is None:
            raise ValueError("direct_state requires positions_file.")
        return self


class StaticSolverConfig(StrictModel):
    method: Literal["continuation_newton", "energy_minimize"] = "continuation_newton"
    force_tolerance: Any = Field(default_factory=lambda: {"value": 1e-8, "unit": "N"})
    max_iterations: int = 80
    continuation_steps: int = 6
    line_search_min: float = 1e-5


class SolverConfig(StrictModel):
    profile: Literal["quick", "production", "reference"] = "quick"
    t_end: Any = Field(default_factory=lambda: {"value": 10.0, "unit": "s"})
    output_dt: Any = Field(default_factory=lambda: {"value": 0.005, "unit": "s"})
    max_step: Any | Literal["auto"] = "auto"
    mass_matrix: Literal["consistent", "lumped"] = "consistent"
    method: Literal["Radau", "BDF", "Newmark"] = "Radau"
    resolve_longitudinal_waves: bool = False
    analytic_jacobian: bool = True
    allow_subminimum_mesh: bool = False
    static: StaticSolverConfig = Field(default_factory=StaticSolverConfig)
    rtol: float | None = None
    position_atol: Any | None = None
    velocity_atol: Any | None = None
    quaternion_atol: float | None = None
    angular_velocity_atol: Any | None = None
    newmark_beta: float = 0.25
    newmark_gamma: float = 0.5
    newmark_max_iterations: int = 24
    newmark_force_tolerance: Any = Field(
        default_factory=lambda: {"value": 1e-8, "unit": "N"}
    )
    newmark_line_search_min: float = 1e-5

    @model_validator(mode="after")
    def validate_newmark(self) -> "SolverConfig":
        if self.newmark_beta <= 0.0 or self.newmark_gamma <= 0.0:
            raise ValueError("Newmark beta and gamma must be positive.")
        if self.newmark_beta + 1e-15 < 0.5 * self.newmark_gamma:
            raise ValueError("Require newmark_beta >= newmark_gamma/2.")
        if self.newmark_max_iterations < 2:
            raise ValueError("newmark_max_iterations must be at least two.")
        if not 0.0 < self.newmark_line_search_min <= 1.0:
            raise ValueError("newmark_line_search_min must lie in (0,1].")
        return self


class AnalysisConfig(StrictModel):
    target_ratio: tuple[int, int] = (3, 2)
    phase_tolerance: Any = Field(default_factory=lambda: {"value": 0.20, "unit": "rad"})
    slow_period_count: int = 30
    compute_spectrum: bool = True
    compute_uncertainty: bool = False

    @model_validator(mode="after")
    def validate_ratio(self) -> "AnalysisConfig":
        p, q = self.target_ratio
        if p <= 0 or q <= 0:
            raise ValueError("target_ratio entries must be positive.")
        return self


class CameraConfig(StrictModel):
    intrinsic_matrix: list[list[float]] | None = None
    rotation_world_to_camera: list[list[float]] | None = None
    translation_world_to_camera: Any = Field(
        default_factory=lambda: {"value": [0, 0, 0], "unit": "m"}
    )
    distortion: list[float] = Field(default_factory=lambda: [0, 0, 0, 0, 0])
    frame_rate: Any = Field(default_factory=lambda: {"value": 240.0, "unit": "Hz"})
    exposure_time: Any = Field(default_factory=lambda: {"value": 0.0, "unit": "s"})


class ObserverConfig(StrictModel):
    type: Literal["orthographic_xy", "pinhole"] = "orthographic_xy"
    camera: CameraConfig | None = None

    @model_validator(mode="after")
    def validate_camera(self) -> "ObserverConfig":
        if self.type == "pinhole" and self.camera is None:
            raise ValueError("pinhole observer requires camera configuration.")
        return self


class HighFidelityConfig(StrictModel):
    """Parameters unique to the independent local discrete-rod backend.

    These fields are deliberately absent from FWD-CABLE: cable bending and a
    finite rigid bob with an eccentric material attachment are the additional
    local physics that make this backend more than another discretisation of
    the forward axial-flexible-string equations.
    """

    model_id: Literal["HF-DISCRETE-ROD-RIGID-BOB-1.0"] = (
        "HF-DISCRETE-ROD-RIGID-BOB-1.0"
    )
    axial_material_model: Literal[
        "passive_unilateral_bilateral_kelvin_voigt_blend"
    ] = "passive_unilateral_bilateral_kelvin_voigt_blend"
    bending_stiffness_scale: float = 1.0
    compression_regularization_scale: float = 1.0
    controlled_limit_study: bool = False
    bob_inertia_factor: float = 0.4
    bob_attachment_radius_fraction: float = 1.0
    bob_contact_radius_fraction: float = 1.0
    quaternion_stabilization_rate: Any = Field(
        default_factory=lambda: {"value": 1.0, "unit": "1/s"}
    )
    contact_guard_enabled: bool = True
    minimum_clearance: Any = Field(
        default_factory=lambda: {"value": 1.0e-5, "unit": "m"}
    )

    @model_validator(mode="after")
    def validate_local_physics(self) -> "HighFidelityConfig":
        if not 0.0 < self.bending_stiffness_scale <= 1.0e6:
            raise ValueError("high_fidelity.bending_stiffness_scale must lie in (0,1e6].")
        if not 0.0 <= self.compression_regularization_scale <= 1.0:
            raise ValueError(
                "high_fidelity.compression_regularization_scale must lie in [0,1]."
            )
        if not 0.0 < self.bob_inertia_factor <= 2.0 / 3.0:
            raise ValueError("high_fidelity.bob_inertia_factor must lie in (0,2/3].")
        if not 0.0 < self.bob_attachment_radius_fraction <= 1.0:
            raise ValueError(
                "high_fidelity.bob_attachment_radius_fraction must lie in (0,1]."
            )
        if not 0.0 < self.bob_contact_radius_fraction <= 1.0:
            raise ValueError(
                "high_fidelity.bob_contact_radius_fraction must lie in (0,1]."
            )
        return self


class SimulationConfig(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run: RunConfig
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    supports: SupportsConfig
    junction: JunctionConfig
    bob: BobConfig
    cables: CablesConfig
    initial_condition: InitialConditionConfig = Field(default_factory=InitialConditionConfig)
    solver: SolverConfig = Field(default_factory=SolverConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    observer: ObserverConfig = Field(default_factory=ObserverConfig)
    high_fidelity: HighFidelityConfig = Field(default_factory=HighFidelityConfig)
    source_path: Path | None = Field(default=None, exclude=True)

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from ypendulum.config import load_config


def q(value: Any, unit: str, source: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"value": value, "unit": unit}
    if source is not None:
        out["source"] = source
    return out


def minimal_config_dict() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "run": {"name": "pytest", "mode": "full", "seed": 1234, "output_directory": "/tmp/ypendulum_pytest", "claim_level": "VERIFIED"},
        "environment": {"gravity": q([0.0, 0.0, -9.80665], "m/s^2"), "air_density": q(1.2, "kg/m^3"), "air_velocity": q([0.0, 0.0, 0.0], "m/s")},
        "supports": {"A": {"type": "fixed", "position": q([-0.15, 0.0, 0.0], "m")}, "B": {"type": "fixed", "position": q([0.15, 0.0, 0.0], "m")}},
        "junction": {"mass": q(0.001, "kg"), "drag_linear": q(0.0, "N*s/m")},
        "bob": {"mass": q(0.2, "kg"), "radius": q(0.01, "m"), "drag": {"enabled": False, "model": "quadratic_plus_linear", "cd": q(0.47, "dimensionless"), "linear_coefficient": q(0.0, "N*s/m")}, "buoyancy": False},
        "cables": {
            "upper_A": {"rest_length": q(0.403887, "m"), "diameter": q(0.001, "m"), "density": q(100.0, "kg/m^3"), "young_modulus": q(2.0e7, "Pa"), "axial_viscosity": q(1.0e4, "Pa*s"), "elements": 2, "drag_cd_normal": 1.2, "drag_enabled": False, "material_model": "linear_kelvin_voigt_tension_only"},
            "upper_B": {"inherit": "upper_A"},
            "lower": {"rest_length": q(0.3, "m"), "diameter": q(0.001, "m"), "density": q(100.0, "kg/m^3"), "young_modulus": q(2.0e7, "Pa"), "axial_viscosity": q(1.0e4, "Pa*s"), "elements": 3, "drag_cd_normal": 1.2, "drag_enabled": False, "material_model": "linear_kelvin_voigt_tension_only"}},
        "initial_condition": {"type": "reduced_angles_release", "phi": q(0.2, "degree"), "theta": q(0.1, "degree"), "phi_dot": q(0.0, "rad/s"), "theta_dot": q(0.0, "rad/s"), "bob_velocity": q([0.0, 0.0, 0.0], "m/s")},
        "solver": {"profile": "quick", "t_end": q(0.02, "s"), "output_dt": q(0.001, "s"), "max_step": q(0.0005, "s"), "mass_matrix": "lumped", "method": "Radau", "resolve_longitudinal_waves": False, "analytic_jacobian": True, "allow_subminimum_mesh": True, "static": {"method": "continuation_newton", "force_tolerance": q(1e-8, "N"), "max_iterations": 100, "continuation_steps": 5, "line_search_min": 1e-5}, "newmark_beta": 0.25, "newmark_gamma": 0.5, "newmark_max_iterations": 24, "newmark_force_tolerance": q(1e-7, "N"), "newmark_line_search_min": 1e-5},
        "analysis": {"target_ratio": [3, 2], "phase_tolerance": q(0.2, "rad"), "slow_period_count": 10, "compute_spectrum": True, "compute_uncertainty": False},
        "observer": {"type": "orthographic_xy"},
    }


@pytest.fixture
def config_dict() -> dict[str, Any]:
    return copy.deepcopy(minimal_config_dict())


@pytest.fixture
def config(config_dict):
    return load_config(config_dict)


@pytest.fixture
def tmp_config_path(tmp_path: Path, config_dict):
    import yaml
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config_dict, sort_keys=False), encoding="utf-8")
    return path

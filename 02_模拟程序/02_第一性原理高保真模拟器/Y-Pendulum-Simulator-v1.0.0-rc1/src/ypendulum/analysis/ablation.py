"""Same-parameter model ablations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ypendulum.api import simulate
from ypendulum.config import SimulationConfig, load_config
from ypendulum.config.units import to_si
from ypendulum.io import write_json
from ypendulum.models.state import SimulationResult, TorusResult


def _summary(result) -> dict[str, Any]:
    if isinstance(result, SimulationResult):
        return {
            "model": result.model_name,
            "max_tension": float(result.tension.max()),
            "min_tension": float(result.tension.min()),
            "max_energy_residual": float(abs(result.energy["balance_residual"]).max()),
            "event_count": len(result.events),
            "bob_final": result.positions[-1, -1].tolist(),
        }
    if isinstance(result, TorusResult):
        return {
            "model": result.model_name,
            "max_tension": float(result.tensions.max()),
            "min_tension": float(result.tensions.min()),
            "event_count": 0 if result.event is None else 1,
            "bob_final": result.position[-1].tolist(),
        }
    return {"model": "A0"}


def run_ablation(
    config: SimulationConfig | str | Path | dict[str, Any], *, write_output: bool = True
) -> dict[str, Any]:
    cfg = config if isinstance(config, SimulationConfig) else load_config(config)
    variants: dict[str, SimulationConfig] = {}

    full = cfg.model_copy(deep=True)
    variants["full"] = full

    no_aero = cfg.model_copy(deep=True)
    no_aero.bob.drag.enabled = False
    for name in ("upper_A", "upper_B", "lower"):
        getattr(no_aero.cables, name).drag_enabled = False
    variants["no_aero"] = no_aero

    no_visc = cfg.model_copy(deep=True)
    for name in ("upper_A", "upper_B", "lower"):
        getattr(no_visc.cables, name).axial_viscosity = {"value": 0.0, "unit": "Pa*s"}
    variants["no_material_viscosity"] = no_visc

    light_string = cfg.model_copy(deep=True)
    for name in ("upper_A", "upper_B", "lower"):
        cable = getattr(light_string.cables, name)
        rho = float(to_si(cable.density, default_unit="kg/m^3"))
        cable.density = {"value": rho * 1e-3, "unit": "kg/m^3", "source": "ablation"}
    variants["near_massless_string"] = light_string

    light_junction = cfg.model_copy(deep=True)
    mj = float(to_si(light_junction.junction.mass, default_unit="kg"))
    light_junction.junction.mass = {"value": mj * 1e-3, "unit": "kg", "source": "ablation"}
    variants["near_massless_junction"] = light_junction

    stiff = cfg.model_copy(deep=True)
    for name in ("upper_A", "upper_B", "lower"):
        cable = getattr(stiff.cables, name)
        E = float(to_si(cable.young_modulus, default_unit="Pa"))
        cable.young_modulus = {"value": E * 100.0, "unit": "Pa", "source": "ablation"}
    variants["high_stiffness"] = stiff

    torus = cfg.model_copy(deep=True)
    torus.run.mode = "torus"
    variants["A1_torus"] = torus

    output: dict[str, Any] = {}
    for name, variant in variants.items():
        variant.run.name = cfg.run.name + "_" + name
        variant.run.output_directory = str(Path(cfg.run.output_directory).with_name(variant.run.name))
        output[name] = _summary(simulate(variant, write_output=write_output))
    if write_output:
        write_json(Path(cfg.run.output_directory).parent / f"{cfg.run.name}_ablation.json", output)
    return output

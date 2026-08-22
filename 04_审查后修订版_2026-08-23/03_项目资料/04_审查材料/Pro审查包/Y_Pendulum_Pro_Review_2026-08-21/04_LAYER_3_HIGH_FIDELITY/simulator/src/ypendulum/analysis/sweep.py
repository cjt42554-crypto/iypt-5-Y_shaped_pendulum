"""Cartesian parameter sweeps without hidden refitting."""

from __future__ import annotations

import copy
import itertools
from pathlib import Path
from typing import Any

import yaml

from ypendulum.api import simulate
from ypendulum.config import load_config
from ypendulum.io import write_json
from ypendulum.models.state import SimulationResult


def _set_path(mapping: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    obj = mapping
    for part in parts[:-1]:
        obj = obj[part]
    target = obj[parts[-1]]
    if isinstance(target, dict) and "value" in target:
        target["value"] = value
    else:
        obj[parts[-1]] = value


def run_sweep(path: str | Path) -> dict[str, Any]:
    spec_path = Path(path)
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    base_path = (spec_path.parent / spec["base_config"]).resolve()
    base = load_config(base_path).model_dump(mode="python", exclude={"source_path"})
    parameters: dict[str, list[Any]] = spec["parameters"]
    keys = list(parameters)
    rows: list[dict[str, Any]] = []
    root = Path(spec.get("output_directory", "runs/sweep")).resolve()
    for index, values in enumerate(itertools.product(*(parameters[key] for key in keys))):
        raw = copy.deepcopy(base)
        setting = dict(zip(keys, values, strict=True))
        for key, value in setting.items():
            _set_path(raw, key, value)
        raw["run"]["name"] = f"sweep_{index:04d}"
        raw["run"]["output_directory"] = str(root / raw["run"]["name"])
        result = simulate(raw)
        row = {"index": index, **setting}
        if isinstance(result, SimulationResult):
            row.update(
                {
                    "max_tension": float(result.tension.max()),
                    "min_tension": float(result.tension.min()),
                    "event_count": len(result.events),
                    "bob_final": result.positions[-1, -1].tolist(),
                }
            )
        rows.append(row)
    report = {"base_config": str(base_path), "parameters": parameters, "rows": rows}
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "sweep_summary.json", report)
    return report

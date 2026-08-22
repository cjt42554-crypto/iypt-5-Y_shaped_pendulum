"""Reproducible Monte Carlo uncertainty propagation."""

from __future__ import annotations

import copy
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ypendulum.api import simulate
from ypendulum.config import SimulationConfig, load_config
from ypendulum.io import write_json
from ypendulum.models.state import SimulationResult


@dataclass(frozen=True)
class Distribution:
    kind: str
    parameters: dict[str, Any]


def sample_distribution(spec: dict[str, Any], rng: np.random.Generator) -> float:
    kind = spec["distribution"]
    if kind == "normal":
        return float(rng.normal(spec["mean"], spec["std"]))
    if kind == "truncated_normal":
        for _ in range(10000):
            value = float(rng.normal(spec["mean"], spec["std"]))
            if spec["low"] <= value <= spec["high"]:
                return value
        raise RuntimeError("Could not sample truncated normal within 10000 attempts.")
    if kind == "uniform":
        return float(rng.uniform(spec["low"], spec["high"]))
    if kind == "lognormal":
        return float(rng.lognormal(spec["mean_log"], spec["std_log"]))
    if kind == "discrete":
        values = spec["values"]
        probabilities = spec.get("probabilities")
        return float(rng.choice(values, p=probabilities))
    raise ValueError(f"Unknown distribution {kind!r}.")


def _set_path(mapping: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    obj = mapping
    for part in parts[:-1]:
        obj = obj[part]
    target = obj[parts[-1]]
    if isinstance(target, dict) and "value" in target:
        target["value"] = value
        target["source"] = "uncertainty_sample"
    else:
        obj[parts[-1]] = value


def _run_sample(payload: tuple[dict[str, Any], int, dict[str, Any]]) -> dict[str, Any]:
    cfg_dict, seed, distributions = payload
    try:
        rng = np.random.default_rng(seed)
        sample = copy.deepcopy(cfg_dict)
        for path, spec in distributions.items():
            _set_path(sample, path, sample_distribution(spec, rng))
        sample["run"]["output_directory"] = f"/tmp/ypendulum_mc_{seed}"
        result = simulate(sample, write_output=False)
        if not isinstance(result, SimulationResult):
            raise ValueError("Uncertainty propagation currently requires full H1 mode.")
        return {
            "seed": seed,
            "bob_final": result.positions[-1, -1].tolist(),
            "max_tension": float(result.tension.max()),
            "slack_event": any(e["type"] == "cable_slack" for e in result.events),
            "energy_residual": float(np.max(np.abs(result.energy["balance_residual"]))),
        }
    except Exception as exc:
        return {
            "seed": seed,
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_uncertainty(
    config: SimulationConfig | str | Path | dict[str, Any],
    distributions: dict[str, Any],
    *,
    samples: int,
    workers: int = 1,
    write_output: bool = True,
) -> dict[str, Any]:
    cfg = config if isinstance(config, SimulationConfig) else load_config(config)
    base = cfg.model_dump(mode="python", exclude={"source_path"})
    seed_sequence = np.random.SeedSequence(cfg.run.seed)
    child_seeds = [int(s.generate_state(1)[0]) for s in seed_sequence.spawn(samples)]
    payloads = [(base, seed, distributions) for seed in child_seeds]
    if workers == 1:
        rows = [_run_sample(p) for p in payloads]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_run_sample, payloads))
    failures = [row for row in rows if "error" in row]
    finals = np.asarray([row["bob_final"] for row in rows if "bob_final" in row], dtype=float)
    tensions = np.asarray([row["max_tension"] for row in rows if "max_tension" in row])
    successful = len(rows) - len(failures)
    report: dict[str, Any] = {
        "samples": samples,
        "successful_samples": successful,
        "failed_samples": len(failures),
        "failure_fraction": float(len(failures) / max(samples, 1)),
        "rows": rows,
    }
    successful_rows = [row for row in rows if "error" not in row]
    if successful:
        report.update(
            {
                "bob_final_median": np.median(finals, axis=0).tolist(),
                "bob_final_p05": np.quantile(finals, 0.05, axis=0).tolist(),
                "bob_final_p95": np.quantile(finals, 0.95, axis=0).tolist(),
                "max_tension_median": float(np.median(tensions)),
                "max_tension_p05": float(np.quantile(tensions, 0.05)),
                "max_tension_p95": float(np.quantile(tensions, 0.95)),
                "slack_probability_conditional_on_success": float(
                    np.mean([row["slack_event"] for row in successful_rows])
                ),
            }
        )
    if write_output:
        write_json(Path(cfg.run.output_directory).parent / f"{cfg.run.name}_uncertainty.json", report)
    return report

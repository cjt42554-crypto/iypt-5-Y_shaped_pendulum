"""Human-readable run report generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def write_run_report(path: str | Path, summary: dict[str, Any], diagnostics: dict[str, Any]) -> None:
    lines = [
        f"# YP-FPSim run report: {summary.get('run_name', 'unnamed')}",
        "",
        f"- Model: `{summary.get('model')}`",
        f"- Scientific claim: `{summary.get('claim_level')}`",
        f"- Status: `{summary.get('status', 'unknown')}`",
        f"- Simulated duration: `{summary.get('duration_s')}` s",
        "",
        "## Principal outputs",
        "",
    ]
    for key in (
        "frequency_fast_hz",
        "frequency_slow_hz",
        "frequency_ratio",
        "phase_drift_rad_s",
        "minimum_tension_N",
        "maximum_tension_N",
        "max_abs_energy_balance_residual",
    ):
        if key in summary:
            lines.append(f"- {key}: `{summary[key]}`")
    lines += ["", "## Numerical diagnostics", ""]
    for key, value in diagnostics.items():
        lines.append(f"- {key}: `{value}`")
    lines += [
        "",
        "## Interpretation boundary",
        "",
        "This report verifies a numerical run. It is not experimental validation. "
        "`VALIDATED` or `PREDICTIVE` claims require an independent frozen validation manifest.",
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

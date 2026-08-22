"""Audit finite-window structural results without overstating locking or proof."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

STRUCTURAL_AUDIT_SCHEMA = "YPS-STRUCTURAL-EVIDENCE-AUDIT-1.1"


def _finite(value: Any) -> float | None:
    try:
        scalar = float(value)
    except (TypeError, ValueError):
        return None
    return scalar if np.isfinite(scalar) else None


def _case_audit(name: str, case: Mapping[str, Any]) -> dict[str, Any]:
    slow_cycles = _finite(case.get("slow_cycles"))
    closure_error = _finite(case.get("normalized_state_closure_error"))
    phi_residual = _finite(case.get("phi_phase_residual_rms_rad"))
    theta_residual = _finite(case.get("theta_phase_residual_rms_rad"))
    phi_r2 = _finite(case.get("phi_phase_fit_r2"))
    theta_r2 = _finite(case.get("theta_phase_fit_r2"))
    guards = case.get("minimum_normalized_guards", {})
    minimum_guard = None
    if isinstance(guards, dict) and guards:
        finite_guards = [
            value for item in guards.values() if (value := _finite(item)) is not None
        ]
        if finite_guards:
            minimum_guard = min(finite_guards)
    checks = {
        "at_least_10_slow_cycles": slow_cycles is not None and slow_cycles >= 10.0,
        "phase_fit_r2": (
            phi_r2 is not None
            and theta_r2 is not None
            and phi_r2 >= 0.999
            and theta_r2 >= 0.999
        ),
        "phase_residual_bounded": (
            phi_residual is not None
            and theta_residual is not None
            and max(phi_residual, theta_residual) <= 0.02
        ),
        "taut_guard_positive": minimum_guard is not None and minimum_guard > 0.0,
        "closure_error_reported": closure_error is not None,
    }
    supported = all(checks.values()) and closure_error is not None
    classification = (
        "NUMERICALLY_SUPPORTED_FINITE_WINDOW_CLOSURE"
        if supported and closure_error <= 1.0e-3
        else "FINITE_WINDOW_DIAGNOSTIC_ONLY"
    )
    return {
        "case": name,
        "classification": classification,
        "checks": checks,
        "slow_cycles": slow_cycles,
        "normalized_state_closure_error": closure_error,
        "minimum_normalized_guard": minimum_guard,
        "locking_proven": False,
        "invariant_torus_proven": False,
        "continuous_amplitude_domain_proven": False,
        "warning": "有限窗相位回归与闭合误差不能单独证明锁频、不变环面或连续参数域定理。",
    }


def audit_structural_results(input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    source = Path(input_path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("结构性结果根节点必须是 JSON 对象。")
    compensation = payload.get("finite_amplitude_compensation", {})
    cases = compensation.get("cases", {}) if isinstance(compensation, dict) else {}
    audits = [
        _case_audit(str(name), case)
        for name, case in cases.items()
        if isinstance(case, dict)
    ]
    report = {
        "schema_version": STRUCTURAL_AUDIT_SCHEMA,
        "source": str(source),
        "case_count": len(audits),
        "cases": audits,
        "global_claims": {
            "quartic_normal_form_can_predict_frequency_shift": True,
            "quartic_normal_form_proves_3_to_2_locking": False,
            "finite_grid_taut_scan_is_continuous_proof": False,
            "hf_0p12s_supports_long_term_structure": False,
        },
    }
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report

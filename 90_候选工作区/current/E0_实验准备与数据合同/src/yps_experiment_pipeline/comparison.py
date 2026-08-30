"""Uncertainty-aware comparison without validation claim inflation."""

from __future__ import annotations

import math

ALLOWED_STATUSES = {
    "CONSISTENT_WITH_CURRENT_UNCERTAINTY",
    "SYSTEMATIC_DISCREPANCY",
    "INCONCLUSIVE",
    "OUT_OF_MODEL_DOMAIN",
}


def combined_standard_uncertainty(
    experimental: float,
    model_input: float,
    numerical: float,
) -> float:
    components = [float(experimental), float(model_input), float(numerical)]
    if any(not math.isfinite(value) or value < 0 for value in components):
        raise ValueError("uncertainty components must be finite and non-negative")
    return math.sqrt(sum(value * value for value in components))


def compare_scalar(
    *,
    data_origin: str,
    observable: str,
    experimental_value: float,
    model_value: float,
    experimental_uncertainty: float,
    model_input_uncertainty: float,
    numerical_uncertainty: float,
    model_domain_status: str = "IN_DOMAIN",
    decision_sigma: float = 2.0,
) -> dict:
    values = [experimental_value, model_value, decision_sigma]
    if any(not math.isfinite(float(value)) for value in values) or decision_sigma <= 0:
        raise ValueError("values must be finite and decision_sigma positive")
    combined = combined_standard_uncertainty(
        experimental_uncertainty,
        model_input_uncertainty,
        numerical_uncertainty,
    )
    normalized = None if combined == 0 else abs(experimental_value - model_value) / combined
    if model_domain_status != "IN_DOMAIN":
        status = "OUT_OF_MODEL_DOMAIN"
    elif normalized is None:
        status = "INCONCLUSIVE"
    elif normalized <= decision_sigma:
        status = "CONSISTENT_WITH_CURRENT_UNCERTAINTY"
    else:
        status = "SYSTEMATIC_DISCREPANCY"
    return {
        "schema_id": "YPS-E0-COMPARISON-RESULT-1.0",
        "data_origin": data_origin,
        "observable": observable,
        "experimental_value": float(experimental_value),
        "model_value": float(model_value),
        "uncertainty_components": {
            "experimental": float(experimental_uncertainty),
            "model_input": float(model_input_uncertainty),
            "numerical": float(numerical_uncertainty),
        },
        "combined_uncertainty": combined,
        "normalized_discrepancy": normalized,
        "status": status,
        "claim_ceiling": "NOT_A_PHYSICAL_OR_EXPERIMENTAL_VALIDATION_CLAIM",
    }

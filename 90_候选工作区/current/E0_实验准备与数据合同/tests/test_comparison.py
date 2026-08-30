import math

import pytest

from yps_experiment_pipeline.comparison import combined_standard_uncertainty, compare_scalar
from yps_experiment_pipeline.contracts import validate_document


def test_combined_uncertainty_and_consistency_state():
    combined = combined_standard_uncertainty(3.0, 4.0, 0.0)
    assert combined == 5.0
    result = compare_scalar(
        data_origin="SYNTHETIC",
        observable="frequency_ratio",
        experimental_value=1.5,
        model_value=1.49,
        experimental_uncertainty=0.01,
        model_input_uncertainty=0.01,
        numerical_uncertainty=0.001,
    )
    validate_document("comparison_result.schema.json", result)
    assert result["status"] == "CONSISTENT_WITH_CURRENT_UNCERTAINTY"
    assert math.isfinite(result["normalized_discrepancy"])


def test_domain_exit_overrides_small_residual():
    result = compare_scalar(
        data_origin="SYNTHETIC",
        observable="frequency_ratio",
        experimental_value=1.5,
        model_value=1.5,
        experimental_uncertainty=0.01,
        model_input_uncertainty=0.01,
        numerical_uncertainty=0.0,
        model_domain_status="SLACK_EVENT",
    )
    assert result["status"] == "OUT_OF_MODEL_DOMAIN"


def test_zero_uncertainty_is_inconclusive_not_a_pass():
    result = compare_scalar(
        data_origin="SYNTHETIC",
        observable="frequency_ratio",
        experimental_value=1.5,
        model_value=1.5,
        experimental_uncertainty=0.0,
        model_input_uncertainty=0.0,
        numerical_uncertainty=0.0,
    )
    assert result["status"] == "INCONCLUSIVE"
    assert "VALIDATION_CLAIM" in result["claim_ceiling"]


def test_negative_uncertainty_rejected():
    with pytest.raises(ValueError):
        combined_standard_uncertainty(-1.0, 0.0, 0.0)

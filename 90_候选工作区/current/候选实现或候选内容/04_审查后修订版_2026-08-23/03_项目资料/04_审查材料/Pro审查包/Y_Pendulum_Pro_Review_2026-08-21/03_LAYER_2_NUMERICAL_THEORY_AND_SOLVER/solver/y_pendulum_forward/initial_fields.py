"""Analytic initial-field representations used by the JSON interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .contracts import ValidationIssue, reject_unknown_keys, strict_finite_array


@dataclass(frozen=True)
class PolynomialField:
    """Vector polynomial in normalized material coordinate ``xi=S/L0``."""

    coefficients: np.ndarray

    def value(self, xi):
        xi_arr = np.asarray(xi, dtype=float)
        result = np.zeros(xi_arr.shape + (3,), dtype=float)
        for power, coefficient in enumerate(self.coefficients):
            result += xi_arr[..., None] ** power * coefficient
        return result

    def derivative_xi(self, xi):
        xi_arr = np.asarray(xi, dtype=float)
        result = np.zeros(xi_arr.shape + (3,), dtype=float)
        for power in range(1, self.coefficients.shape[0]):
            result += (
                power
                * xi_arr[..., None] ** (power - 1)
                * self.coefficients[power]
            )
        return result


def build_polynomial_field(
    spec: Any,
    path: str,
    issues: list[ValidationIssue],
    *,
    max_degree: int = 8,
) -> PolynomialField:
    if not isinstance(spec, dict) or spec.get("kind") != "polynomial":
        issues.append(
            ValidationIssue(
                "INITIAL_FIELD_KIND",
                path,
                spec,
                "object with kind='polynomial'",
            )
        )
        return PolynomialField(np.zeros((1, 3)))
    reject_unknown_keys(spec, {"kind", "coefficients"}, path, issues)
    raw = spec.get("coefficients")
    coefficients = strict_finite_array(raw)
    conversion_ok = coefficients is not None
    if coefficients is None:
        coefficients = np.zeros((1, 3))
    valid = (
        conversion_ok
        and coefficients.ndim == 2
        and coefficients.shape[1] == 3
        and 1 <= coefficients.shape[0] <= max_degree + 1
    )
    if not valid:
        issues.append(
            ValidationIssue(
                "INITIAL_FIELD_TYPE",
                f"{path}.coefficients",
                raw,
                f"finite [power, xyz] array with degree <= {max_degree}",
            )
        )
        coefficients = np.zeros((1, 3))
    return PolynomialField(coefficients)


def straight_polynomial(start, end) -> dict[str, Any]:
    """Return a JSON-ready degree-one field; useful to construct configs."""

    start_arr = np.asarray(start, dtype=float)
    end_arr = np.asarray(end, dtype=float)
    return {
        "kind": "polynomial",
        "coefficients": [start_arr.tolist(), (end_arr - start_arr).tolist()],
    }

"""Independent axial-stiffness and tension-extension calibration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from scipy.stats import t as student_t


@dataclass(frozen=True)
class AxialCalibration:
    ea: float
    compliance_m_per_n: float
    intercept_extension: float
    rms_extension_residual: float
    r_squared: float
    ea_standard_error: float
    ea_confidence_interval_95: tuple[float, float]
    point_count: int
    force_range_n: tuple[float, float]
    rest_length_m: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validated(force: np.ndarray, extension: np.ndarray, rest_length: float) -> tuple[np.ndarray, np.ndarray]:
    F = np.asarray(force, dtype=float)
    dL = np.asarray(extension, dtype=float)
    if F.shape != dL.shape or F.ndim != 1 or F.size < 3:
        raise ValueError("force and extension must be one-dimensional arrays with at least 3 points.")
    if not np.all(np.isfinite(F)) or not np.all(np.isfinite(dL)):
        raise ValueError("Calibration data contain NaN or infinity.")
    if rest_length <= 0.0 or not np.isfinite(rest_length):
        raise ValueError("rest_length must be a positive finite SI length.")
    if float(np.ptp(F)) <= 0.0:
        raise ValueError("Calibration force must span a nonzero range.")
    return F, dL


def fit_axial_stiffness(
    force: np.ndarray,
    extension: np.ndarray,
    rest_length: float,
) -> AxialCalibration:
    """Fit ``ΔL = F L0 / EA + intercept`` with an uncertainty audit.

    The confidence interval describes ordinary least-squares repeatability only;
    it does not include force-gauge calibration, length-scale systematic error,
    hysteresis, temperature drift or model inadequacy.
    """

    F, dL = _validated(force, extension, rest_length)
    design = np.column_stack([F, np.ones_like(F)])
    coefficients, *_ = np.linalg.lstsq(design, dL, rcond=None)
    compliance, intercept = map(float, coefficients)
    if compliance <= 0:
        raise ValueError("Fitted compliance is non-positive.")
    fitted = design @ coefficients
    residual = dL - fitted
    ss_res = float(np.sum(residual**2))
    ss_tot = float(np.sum((dL - np.mean(dL)) ** 2))
    dof = F.size - 2
    covariance = np.linalg.inv(design.T @ design) * (ss_res / dof)
    compliance_se = float(np.sqrt(max(covariance[0, 0], 0.0)))
    ea = float(rest_length / compliance)
    ea_se = float(rest_length * compliance_se / compliance**2)
    critical = float(student_t.ppf(0.975, dof))
    # Transform the compliance interval rather than using only a symmetric EA
    # interval because EA=1/compliance is nonlinear.
    c_low = compliance - critical * compliance_se
    c_high = compliance + critical * compliance_se
    if c_low > 0.0:
        ea_ci = (float(rest_length / c_high), float(rest_length / c_low))
    else:
        ea_ci = (float(rest_length / c_high), float("inf"))
    return AxialCalibration(
        ea=ea,
        compliance_m_per_n=compliance,
        intercept_extension=float(intercept),
        rms_extension_residual=float(np.sqrt(np.mean(residual**2))),
        r_squared=1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0,
        ea_standard_error=ea_se,
        ea_confidence_interval_95=ea_ci,
        point_count=int(F.size),
        force_range_n=(float(np.min(F)), float(np.max(F))),
        rest_length_m=float(rest_length),
    )


def build_tabulated_tension_extension(
    force: np.ndarray,
    extension: np.ndarray,
    rest_length: float,
    *,
    require_monotone: bool = True,
) -> dict[str, np.ndarray | float]:
    """Prepare an independently measured loading curve for the H1 material plugin.

    Duplicate extension values are averaged.  No smoothing or extrapolation is
    silently introduced.  A non-monotone loading curve is rejected by default;
    hysteresis requires a different stateful material model and must not be
    disguised as a single-valued table.
    """

    F, dL = _validated(force, extension, rest_length)
    order = np.argsort(dL)
    x = dL[order]
    y = F[order]
    unique, inverse = np.unique(x, return_inverse=True)
    averaged = np.array([np.mean(y[inverse == idx]) for idx in range(unique.size)])
    if unique.size < 2:
        raise ValueError("Tabulated material curve needs at least two distinct extensions.")
    if unique[0] > 0.0:
        unique = np.concatenate([[0.0], unique])
        averaged = np.concatenate([[0.0], averaged])
    elif unique[0] == 0.0 and averaged[0] != 0.0:
        raise ValueError("A tension-only loading curve must have zero tension at zero extension.")
    if np.any(unique < 0.0):
        raise ValueError("Tabulated tension-only extension data cannot contain negative extension.")
    if np.any(averaged < 0.0):
        raise ValueError("Tabulated tension cannot be negative.")
    if require_monotone and np.any(np.diff(averaged) < -1e-12 * max(np.max(averaged), 1.0)):
        raise ValueError(
            "Measured loading curve is non-monotone.  Separate loading/unloading branches or use a stateful hysteretic model."
        )
    return {
        "extension_m": unique,
        "tension_n": averaged,
        "calibration_length_m": float(rest_length),
    }

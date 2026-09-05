"""Inherited centered dual behavior with separated component-KKT finiteness."""

from __future__ import annotations

import numpy as np

from ypendulum_hfv2_p3r4.dual_certification import (
    DualBackendCall,
    P3R4DualCertificate,
    P3R4KKTAudit,
    P3R4KKTThresholds,
    audit_contact_kkt,
    certify_centered_dual,
    component_allowed_raw,
    thresholds_from_manifest,
)

P3R5DualCertificate = P3R4DualCertificate
P3R5KKTAudit = P3R4KKTAudit
P3R5KKTThresholds = P3R4KKTThresholds


def component_kkt_finite(kkt: object, evaluation: object | None = None) -> bool:
    """Check only component-KKT fields, excluding obsolete dual intervals."""

    arrays = (
        kkt.canonical_multipliers_N,
        kkt.stationarity_vector_N,
        kkt.translation_force_residual_N,
        kkt.rotation_torque_residual_N_m,
        kkt.dimensionless_stationarity,
        kkt.component_allowed_raw,
    )
    scalars = (
        kkt.primal_violation_m,
        kkt.dual_violation_N,
        kkt.stationarity_residual_N,
        kkt.stationarity_limit_N,
        kkt.translation_force_infinity_N,
        kkt.rotation_torque_infinity_N_m,
        kkt.dimensionless_stationarity_infinity,
        kkt.complementarity_residual_N_m,
        kkt.complementarity_limit_N_m,
    )
    finite = bool(
        all(np.all(np.isfinite(np.asarray(value, dtype=float))) for value in arrays)
        and np.all(np.isfinite(np.asarray(scalars, dtype=float)))
    )
    if evaluation is not None:
        finite = bool(
            finite
            and np.all(np.isfinite(evaluation.coordinates.values))
            and np.all(np.isfinite(evaluation.contact.gaps_m))
            and np.all(np.isfinite(evaluation.validity.normalized_residuals))
        )
    return finite


def component_kkt_passed(
    kkt: object,
    thresholds: object,
    evaluation: object | None = None,
) -> bool:
    return bool(
        component_kkt_finite(kkt, evaluation)
        and kkt.primal_violation_m <= thresholds.primal_penetration_max_m
        and kkt.dual_violation_N <= thresholds.dual_negative_max_N
        and kkt.legacy_stationarity_passed
        and kkt.translation_stationarity_passed
        and kkt.rotation_stationarity_passed
        and kkt.dimensionless_stationarity_passed
        and kkt.complementarity_residual_N_m <= kkt.complementarity_limit_N_m
        and kkt.supported_rank == kkt.supported_indices.size
    )


__all__ = [
    "DualBackendCall",
    "P3R5DualCertificate",
    "P3R5KKTAudit",
    "P3R5KKTThresholds",
    "audit_contact_kkt",
    "certify_centered_dual",
    "component_allowed_raw",
    "component_kkt_finite",
    "component_kkt_passed",
    "thresholds_from_manifest",
]

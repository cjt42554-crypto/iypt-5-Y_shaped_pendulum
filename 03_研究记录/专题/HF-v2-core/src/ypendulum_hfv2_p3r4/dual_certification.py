"""Read-only P3R3 centered dual behavior under the P3R4 audit namespace."""

from ypendulum_hfv2_p3r3.dual_certification import (
    DualBackendCall,
    P3R3DualCertificate,
    P3R3KKTAudit,
    P3R3KKTThresholds,
    audit_contact_kkt,
    certify_centered_dual,
    component_allowed_raw,
    thresholds_from_manifest,
)

P3R4DualCertificate = P3R3DualCertificate
P3R4KKTAudit = P3R3KKTAudit
P3R4KKTThresholds = P3R3KKTThresholds

__all__ = [
    "DualBackendCall",
    "P3R4DualCertificate",
    "P3R4KKTAudit",
    "P3R4KKTThresholds",
    "audit_contact_kkt",
    "certify_centered_dual",
    "component_allowed_raw",
    "thresholds_from_manifest",
]

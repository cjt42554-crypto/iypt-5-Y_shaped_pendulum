"""Independent local audits that depend on, but are not imported by, the physics core."""

from .architecture import ArchitectureAudit, audit_physical_core
from .energy_gradient import GradientSample, central_difference_gradient, force_gradient_samples
from .evidence import build_g1r_evidence, canonical_evidence_text, strict_decrease_interval
from .invariance import InternalBalance, ObjectivityAudit, internal_balance, objectivity_audit
from .passivity import AxialPassivityAudit, audit_axial_passivity

__all__ = [
    "ArchitectureAudit",
    "AxialPassivityAudit",
    "GradientSample",
    "InternalBalance",
    "ObjectivityAudit",
    "audit_axial_passivity",
    "audit_physical_core",
    "build_g1r_evidence",
    "canonical_evidence_text",
    "central_difference_gradient",
    "force_gradient_samples",
    "internal_balance",
    "objectivity_audit",
    "strict_decrease_interval",
]

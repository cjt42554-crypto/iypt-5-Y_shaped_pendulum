"""Compatibility re-export for the split candidate rigid-contact primitives."""

from .kkt import (
    audit_projected_hessian,
    audit_static_kkt,
    estimate_nonnegative_multipliers,
)
from .parameter_domain import full_parameter_polygon, material_separation_polygon
from .static_solver import solve_static_contact_problem
from .types import (
    ContactConstraint,
    ContactWitness,
    DegenerateContactGeometry,
    KKTAudit,
    KKTThresholds,
    ProjectedHessianAudit,
    StaticContactResult,
)
from .assembly import assemble_gap_system
from .witness import closest_segment_pair_witness

__all__ = [
    "ContactConstraint",
    "ContactWitness",
    "DegenerateContactGeometry",
    "KKTAudit",
    "KKTThresholds",
    "ProjectedHessianAudit",
    "StaticContactResult",
    "assemble_gap_system",
    "audit_projected_hessian",
    "audit_static_kkt",
    "closest_segment_pair_witness",
    "estimate_nonnegative_multipliers",
    "full_parameter_polygon",
    "material_separation_polygon",
    "solve_static_contact_problem",
]

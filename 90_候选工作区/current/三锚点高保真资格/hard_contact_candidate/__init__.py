"""Candidate-only frictionless rigid-contact primitives for the Y-pendulum HF model."""

from .geometry_kkt import (
    ContactConstraint,
    ContactWitness,
    DegenerateContactGeometry,
    KKTAudit,
    KKTThresholds,
    ProjectedHessianAudit,
    StaticContactResult,
    assemble_gap_system,
    audit_projected_hessian,
    audit_static_kkt,
    closest_segment_pair_witness,
    estimate_nonnegative_multipliers,
    full_parameter_polygon,
    material_separation_polygon,
    solve_static_contact_problem,
)

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

"""Formal no-contact conservative static-reference package."""

from .constitutive import (
    AxialMaterial,
    AxialResponse,
    BendingGeometryError,
    BendingResponse,
    axial_segment_response,
    bending_energy,
    bending_energy_forces,
)
from .identity import (
    CAPABILITY,
    CLAIM_CEILING,
    EXPLICIT_EXCLUSIONS,
    MODEL_ID,
    QUALIFICATION_STATUS,
)
from .interface import (
    StaticReferenceAuditThresholds,
    StaticReferenceBatchResult,
    StaticReferencePostAudit,
    solve_no_contact_static_reference,
)
from .loads import StaticPointLoadResponse, point_static_load
from .mass import StaticMassDistribution
from .rigid import (
    attachment_action_reaction,
    attachment_geometry,
    exp_so3,
)
from .state import StaticReferenceState
from .topology import MaterialNode, MaterialSegment, StaticReferenceTopology

__all__ = [
    "CAPABILITY",
    "CLAIM_CEILING",
    "EXPLICIT_EXCLUSIONS",
    "MODEL_ID",
    "QUALIFICATION_STATUS",
    "AxialMaterial",
    "AxialResponse",
    "BendingGeometryError",
    "BendingResponse",
    "MaterialNode",
    "MaterialSegment",
    "StaticMassDistribution",
    "StaticPointLoadResponse",
    "StaticReferenceAuditThresholds",
    "StaticReferenceBatchResult",
    "StaticReferencePostAudit",
    "StaticReferenceState",
    "StaticReferenceTopology",
    "attachment_action_reaction",
    "attachment_geometry",
    "axial_segment_response",
    "bending_energy",
    "bending_energy_forces",
    "exp_so3",
    "point_static_load",
    "solve_no_contact_static_reference",
]

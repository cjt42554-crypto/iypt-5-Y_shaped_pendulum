"""Pure-physics candidate kernel for the HF-v2 Y-pendulum backend."""

from .constitutive import (
    AxialMaterial,
    AxialResponse,
    BendingGeometryError,
    BendingResponse,
    axial_segment_response,
    bending_energy,
    bending_energy_forces,
)
from .loads import IsotropicDragLaw, PointLoadResponse, point_external_load
from .mass import MassProperties
from .rigid import (
    advance_rotation_body,
    attachment_action_reaction,
    attachment_kinematics,
    exp_so3,
)
from .state import HFV2State
from .topology import HFV2Topology, MaterialNode, MaterialSegment

MODEL_ID = "HFV2-DISCRETE-CORD-RIGID-BOB-0.2-CANDIDATE"
CONTACT_MODEL_ID = "HFV2-DISCRETE-CORD-RIGID-BOB-0.3-CONTACT-CANDIDATE"

__all__ = [
    "CONTACT_MODEL_ID",
    "MODEL_ID",
    "AxialMaterial",
    "AxialResponse",
    "BendingGeometryError",
    "BendingResponse",
    "HFV2State",
    "HFV2Topology",
    "IsotropicDragLaw",
    "MassProperties",
    "MaterialNode",
    "MaterialSegment",
    "PointLoadResponse",
    "advance_rotation_body",
    "attachment_action_reaction",
    "attachment_kinematics",
    "axial_segment_response",
    "bending_energy",
    "bending_energy_forces",
    "exp_so3",
    "point_external_load",
]

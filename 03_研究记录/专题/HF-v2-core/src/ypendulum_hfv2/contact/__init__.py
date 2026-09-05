"""Internal static-contact geometry and registration namespace."""

from .contracts import (
    BobSegmentConstraint,
    BobSocketRegistration,
    ContactGeometryError,
    ContactRegistry,
    ContactSurfaceSpec,
    ContactWitness,
    ConvexParameterPolygon,
    DegenerateContactGeometry,
    GeometryTolerances,
    JunctionSocketRegistration,
    MaterialSocketRegistration,
    SegmentPairConstraint,
)
from .geometry import (
    clip_parameter_polygon,
    closest_bob_segment_witness,
    closest_segment_pair_witness,
    full_parameter_polygon,
)
from .registration import build_contact_registry

__all__ = [
    "BobSegmentConstraint",
    "BobSocketRegistration",
    "ContactGeometryError",
    "ContactRegistry",
    "ContactSurfaceSpec",
    "ContactWitness",
    "ConvexParameterPolygon",
    "DegenerateContactGeometry",
    "GeometryTolerances",
    "JunctionSocketRegistration",
    "MaterialSocketRegistration",
    "SegmentPairConstraint",
    "build_contact_registry",
    "clip_parameter_polygon",
    "closest_bob_segment_witness",
    "closest_segment_pair_witness",
    "full_parameter_polygon",
]

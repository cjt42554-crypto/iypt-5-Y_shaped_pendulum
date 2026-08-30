"""Candidate-only experiment preparation and synthetic readiness tools."""

from .camera import project_points, triangulate_two_view
from .comparison import compare_scalar
from .contracts import validate_document
from .forward_adapter import cable_compatibility, formal_identity, torus_compatibility
from .observables import estimate_damped_mode
from .synchronization import estimate_event_offset

__all__ = [
    "cable_compatibility",
    "compare_scalar",
    "estimate_damped_mode",
    "estimate_event_offset",
    "formal_identity",
    "project_points",
    "torus_compatibility",
    "triangulate_two_view",
    "validate_document",
]

__version__ = "0.1.0"

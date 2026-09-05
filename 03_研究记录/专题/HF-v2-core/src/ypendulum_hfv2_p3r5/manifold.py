"""P3R5 identity wrapper over inherited active-manifold behavior."""

from dataclasses import replace

from ypendulum_hfv2_p3r4.manifold import (
    ManifoldNeighborhoodAudit,
    ManifoldRetractionResult,
    ManifoldRetractionSettings,
    retract_to_manifold,
    settings_from_manifest,
)
from ypendulum_hfv2_p3r4.manifold import (
    audit_manifold_neighborhood as _audit_manifold_neighborhood,
)

from . import P3R5_MANIFOLD_RETRACTION_ID


def audit_manifold_neighborhood(*args: object, **kwargs: object) -> ManifoldNeighborhoodAudit:
    result = _audit_manifold_neighborhood(*args, **kwargs)
    return replace(result, identity=P3R5_MANIFOLD_RETRACTION_ID)


__all__ = [
    "ManifoldNeighborhoodAudit",
    "ManifoldRetractionResult",
    "ManifoldRetractionSettings",
    "audit_manifold_neighborhood",
    "retract_to_manifold",
    "settings_from_manifest",
]

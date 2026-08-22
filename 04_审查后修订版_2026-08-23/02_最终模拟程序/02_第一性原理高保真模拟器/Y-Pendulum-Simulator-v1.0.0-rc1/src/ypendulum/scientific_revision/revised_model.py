"""HF model subclass with explicit independent EI and declared model identity."""

from __future__ import annotations

from typing import Any

from ypendulum.hf.model import HighFidelityModel

from .overlay import RevisionOverlay, apply_overlay_to_model


class RevisedHighFidelityModel(HighFidelityModel):
    """Apply one immutable scientific overlay immediately after base assembly."""

    def __init__(self, cfg: Any, overlay: RevisionOverlay):
        super().__init__(cfg)
        self.revision_overlay = overlay
        self.revision_manifest = apply_overlay_to_model(self, overlay)

    def diagnostics(self) -> dict[str, Any]:
        payload = super().diagnostics()
        payload["scientific_revision"] = self.revision_manifest
        payload["model_id"] = self.model_id
        payload["branch_bending_stiffness_N_m2"] = {
            name: float(branch.ei) for name, branch in self.branches.items()
        }
        payload["compression_regularization_scale"] = float(
            self.compression_regularization_scale
        )
        return payload

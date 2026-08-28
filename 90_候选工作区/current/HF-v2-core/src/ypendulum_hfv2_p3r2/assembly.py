"""P3R2 assembly identity over the byte-frozen P3R physical contact domain."""

from __future__ import annotations

import hashlib
import json

from ypendulum_hfv2_p3r import P3R_CONTACT_MODEL_ID
from ypendulum_hfv2_p3r.assembly import P3RContactAssembly

from . import (
    P3R2_COMPONENT_SCALE_ID,
    P3R2_COMPOSITE_ALGORITHM_ID,
    P3R2_CONTACT_ASSEMBLY_IDENTITY_SCHEMA,
    P3R2_CONTACT_MODEL_ID,
)


class P3R2ContactAssembly(P3RContactAssembly):
    """Keep P3R geometry exact while assigning the P3R2 algorithm identity."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        binding = json.loads(
            json.dumps(
                self.identity_binding,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        binding.update(
            {
                "identity_schema": P3R2_CONTACT_ASSEMBLY_IDENTITY_SCHEMA,
                "contact_model_id": P3R2_CONTACT_MODEL_ID,
                "physical_domain_predecessor_model_id": P3R_CONTACT_MODEL_ID,
                "physical_domain_change_from_predecessor": False,
                "composite_algorithm_identity": P3R2_COMPOSITE_ALGORITHM_ID,
                "component_scale_identity": P3R2_COMPONENT_SCALE_ID,
            }
        )
        token = hashlib.sha256(
            json.dumps(
                binding,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.identity_binding = binding
        self.contact_assembly_token = token

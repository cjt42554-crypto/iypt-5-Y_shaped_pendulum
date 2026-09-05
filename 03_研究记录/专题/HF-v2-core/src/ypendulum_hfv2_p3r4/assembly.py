"""P3R4 identity over the byte-frozen P3R3 physical contact domain."""

from __future__ import annotations

import hashlib
import json

from ypendulum_hfv2_p3r3 import P3R3_CONTACT_MODEL_ID
from ypendulum_hfv2_p3r3.assembly import P3R3ContactAssembly

from . import (
    P3R4_ACTUAL_MULTISEED_ID,
    P3R4_COMPONENT_SCALE_ID,
    P3R4_COMPOSITE_ALGORITHM_ID,
    P3R4_CONTACT_ASSEMBLY_IDENTITY_SCHEMA,
    P3R4_CONTACT_MODEL_ID,
    P3R4_DUAL_CERTIFIER_ID,
    P3R4_MANIFOLD_RETRACTION_ID,
    P3R4_RESTORATION_JACOBIAN_ID,
    P3R4_SECOND_ORDER_ID,
    P3R4_TARGET_ADMISSIBILITY_ID,
)


class P3R4ContactAssembly(P3R3ContactAssembly):
    """Keep P3R3 physics exact while assigning the P3R4 audit identity."""

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
                "identity_schema": P3R4_CONTACT_ASSEMBLY_IDENTITY_SCHEMA,
                "contact_model_id": P3R4_CONTACT_MODEL_ID,
                "physical_domain_predecessor_model_id": P3R3_CONTACT_MODEL_ID,
                "physical_domain_change_from_predecessor": False,
                "composite_algorithm_identity": P3R4_COMPOSITE_ALGORITHM_ID,
                "component_scale_identity": P3R4_COMPONENT_SCALE_ID,
                "target_admissibility_identity": P3R4_TARGET_ADMISSIBILITY_ID,
                "dual_certifier_identity": P3R4_DUAL_CERTIFIER_ID,
                "second_order_identity": P3R4_SECOND_ORDER_ID,
                "manifold_retraction_identity": P3R4_MANIFOLD_RETRACTION_ID,
                "actual_multiseed_attraction_identity": P3R4_ACTUAL_MULTISEED_ID,
                "restoration_jacobian_identity": P3R4_RESTORATION_JACOBIAN_ID,
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

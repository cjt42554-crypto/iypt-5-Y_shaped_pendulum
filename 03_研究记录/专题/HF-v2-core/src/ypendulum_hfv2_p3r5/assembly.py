"""P3R5 identity over the byte-frozen P3R4 physical contact domain."""

from __future__ import annotations

import hashlib
import json

from ypendulum_hfv2_p3r4 import P3R4_CONTACT_MODEL_ID
from ypendulum_hfv2_p3r4.assembly import P3R4ContactAssembly

from . import (
    P3R5_ACTUAL_MULTISEED_ID,
    P3R5_COMPONENT_SCALE_ID,
    P3R5_CONTACT_ASSEMBLY_IDENTITY_SCHEMA,
    P3R5_CONTACT_MODEL_ID,
    P3R5_DUAL_CERTIFIER_ID,
    P3R5_MANIFOLD_RETRACTION_ID,
    P3R5_PURE_INPUT_CONSTRUCTIBILITY_ID,
    P3R5_QUALIFICATION_ALGORITHM_ID,
    P3R5_REFERENCE_CONSTRUCTOR_ID,
    P3R5_RESTORATION_JACOBIAN_ID,
    P3R5_SECOND_ORDER_ID,
    P3R5_TARGET_ADMISSIBILITY_ID,
)


class P3R5ContactAssembly(P3R4ContactAssembly):
    """Keep P3R4 physics exact while assigning the P3R5 audit identity."""

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
                "identity_schema": P3R5_CONTACT_ASSEMBLY_IDENTITY_SCHEMA,
                "contact_model_id": P3R5_CONTACT_MODEL_ID,
                "physical_domain_predecessor_model_id": P3R4_CONTACT_MODEL_ID,
                "physical_domain_change_from_predecessor": False,
                "reference_constructor_identity": P3R5_REFERENCE_CONSTRUCTOR_ID,
                "qualification_algorithm_identity": P3R5_QUALIFICATION_ALGORITHM_ID,
                "component_scale_identity": P3R5_COMPONENT_SCALE_ID,
                "target_admissibility_identity": P3R5_TARGET_ADMISSIBILITY_ID,
                "dual_certifier_identity": P3R5_DUAL_CERTIFIER_ID,
                "second_order_identity": P3R5_SECOND_ORDER_ID,
                "manifold_retraction_identity": P3R5_MANIFOLD_RETRACTION_ID,
                "actual_multiseed_attraction_identity": P3R5_ACTUAL_MULTISEED_ID,
                "restoration_jacobian_identity": P3R5_RESTORATION_JACOBIAN_ID,
                "pure_input_constructibility_identity": (P3R5_PURE_INPUT_CONSTRUCTIBILITY_ID),
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


__all__ = ["P3R5ContactAssembly"]

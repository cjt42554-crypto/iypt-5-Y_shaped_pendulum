"""P3R5 identity wrapper over inherited Richardson second-order behavior."""

from dataclasses import replace

from ypendulum_hfv2_p3r4.second_order import (
    RichardsonDirectionAudit,
    SecondOrderAudit,
    richardson_direction_audit,
    tangent_directions,
)
from ypendulum_hfv2_p3r4.second_order import (
    audit_reference_second_order as _audit_reference_second_order,
)

from . import P3R5_SECOND_ORDER_ID


def audit_reference_second_order(*args: object, **kwargs: object) -> SecondOrderAudit:
    result = _audit_reference_second_order(*args, **kwargs)
    return replace(result, identity=P3R5_SECOND_ORDER_ID)


__all__ = [
    "RichardsonDirectionAudit",
    "SecondOrderAudit",
    "audit_reference_second_order",
    "richardson_direction_audit",
    "tangent_directions",
]

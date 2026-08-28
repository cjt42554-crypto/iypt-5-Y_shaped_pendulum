"""Passivity audit for the unilateral axial response."""

from __future__ import annotations

from dataclasses import dataclass

from ypendulum_static_reference.constitutive.axial import AxialResponse


@dataclass(frozen=True)
class AxialPassivityAudit:
    tension_nonnegative: bool
    viscous_dissipation_nonnegative: bool
    unilateral_release_dissipation_nonnegative: bool
    scaled_power_balance_residual: float

    @property
    def passed(self) -> bool:
        return (
            self.tension_nonnegative
            and self.viscous_dissipation_nonnegative
            and self.unilateral_release_dissipation_nonnegative
            and self.scaled_power_balance_residual <= 2.0e-14
        )


def audit_axial_passivity(response: AxialResponse, *, power_scale: float) -> AxialPassivityAudit:
    if power_scale <= 0.0:
        raise ValueError("power_scale must be positive.")
    return AxialPassivityAudit(
        tension_nonnegative=response.tension >= 0.0,
        viscous_dissipation_nonnegative=response.viscous_dissipation_rate >= 0.0,
        unilateral_release_dissipation_nonnegative=(
            response.unilateral_release_dissipation_rate >= 0.0
        ),
        scaled_power_balance_residual=abs(response.power_balance_residual) / power_scale,
    )

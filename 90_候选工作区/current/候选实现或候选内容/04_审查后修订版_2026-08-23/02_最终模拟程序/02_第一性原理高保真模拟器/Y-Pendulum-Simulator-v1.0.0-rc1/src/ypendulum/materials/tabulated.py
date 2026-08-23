"""Mesh-objective monotone tabulated tension--extension material.

The default CSV contract is a whole-cable calibration curve with columns
``extension,tension`` in metres and newtons.  ``calibration_length`` is the
natural length of the calibrated cable specimen.  During finite-element use,
each element is evaluated at the equivalent whole-cable extension

    x = (delta / element_rest_length) * calibration_length.

This makes the constitutive response independent of the number of cable
elements.  Elastic energy is scaled so that its derivative with respect to the
local element extension is exactly the interpolated tension.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.interpolate import PchipInterpolator

from .base import AxialResponse


@dataclass
class TabulatedTensionMaterial:
    """Monotone, tension-only whole-cable calibration law.

    Parameters
    ----------
    extension:
        Extension of the calibrated specimen in metres.
    tension:
        Measured tensile force in newtons.
    calibration_length:
        Natural length of the calibrated specimen in metres.  The same curve
        can therefore be used with any finite-element subdivision of that
        specimen without changing the macroscopic cable stiffness.
    viscosity:
        Axial Kelvin--Voigt coefficient ``eta*A`` in N s.  Its local
        contribution is ``viscosity * delta_dot / element_rest_length``.
    """

    extension: np.ndarray
    tension: np.ndarray
    calibration_length: float = 1.0
    viscosity: float = 0.0
    _interp: PchipInterpolator = field(init=False, repr=False)
    _antiderivative: PchipInterpolator = field(init=False, repr=False)
    extrapolated_last_call: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        x = np.asarray(self.extension, dtype=float)
        y = np.asarray(self.tension, dtype=float)
        if x.ndim != 1 or y.shape != x.shape or x.size < 2:
            raise ValueError("Tabulated material needs at least two one-dimensional points.")
        if not np.isclose(x[0], 0.0) or not np.isclose(y[0], 0.0):
            raise ValueError("Tabulated tension-extension curve must start at (0,0).")
        if np.any(np.diff(x) <= 0) or np.any(np.diff(y) < 0):
            raise ValueError("Tabulated tension-extension curve must be monotone.")
        if not np.isfinite(self.calibration_length) or self.calibration_length <= 0:
            raise ValueError("Tabulated material calibration_length must be positive.")
        if not np.isfinite(self.viscosity) or self.viscosity < 0:
            raise ValueError("Tabulated material viscosity cannot be negative.")
        object.__setattr__(self, "extension", x)
        object.__setattr__(self, "tension", y)
        interp = PchipInterpolator(x, y, extrapolate=False)
        object.__setattr__(self, "_interp", interp)
        object.__setattr__(self, "_antiderivative", interp.antiderivative())

    @classmethod
    def from_csv(
        cls,
        path: str | Path,
        *,
        calibration_length: float,
        viscosity: float = 0.0,
    ) -> "TabulatedTensionMaterial":
        data = np.genfromtxt(path, delimiter=",", names=True)
        if not {"extension", "tension"}.issubset(data.dtype.names or ()):
            raise ValueError("Material table needs extension,tension columns in SI units.")
        x = np.asarray(data["extension"], dtype=float)
        y = np.asarray(data["tension"], dtype=float)
        return cls(x, y, calibration_length=calibration_length, viscosity=viscosity)

    def evaluate(self, delta, delta_dot, rest_length) -> AxialResponse:
        delta = np.asarray(delta, dtype=float)
        delta_dot = np.asarray(delta_dot, dtype=float)
        rest_length = np.asarray(rest_length, dtype=float)
        if np.any(rest_length <= 0):
            raise ValueError("Element rest lengths must be positive.")

        positive = np.maximum(delta, 0.0)
        length_scale = self.calibration_length / rest_length
        equivalent_extension = positive * length_scale
        x_max = float(self.extension[-1])
        clipped = np.minimum(equivalent_extension, x_max)

        elastic = np.asarray(self._interp(clipped), dtype=float)
        tangent_curve = np.asarray(self._interp.derivative()(clipped), dtype=float)
        high = equivalent_extension > x_max
        object.__setattr__(self, "extrapolated_last_call", bool(np.any(high)))
        terminal_slope = float(
            max(
                self._interp.derivative()(x_max),
                (self.tension[-1] - self.tension[-2])
                / (self.extension[-1] - self.extension[-2]),
                0.0,
            )
        )
        if np.any(high):
            elastic = np.where(
                high,
                self.tension[-1]
                + terminal_slope * (equivalent_extension - x_max),
                elastic,
            )
            tangent_curve = np.where(high, terminal_slope, tangent_curve)

        viscous_tension = self.viscosity * delta_dot / rest_length
        trial = elastic + viscous_tension
        active = (delta > 0.0) & (trial > 0.0)
        tension = np.where(active, trial, 0.0)

        # The curve antiderivative is energy for the calibrated specimen.
        # Multiplying by L_e/L_cal makes dU_e/d(delta_e) = T.
        energy_calibrated = np.asarray(
            self._antiderivative(clipped) - self._antiderivative(0.0),
            dtype=float,
        )
        if np.any(high):
            extra = equivalent_extension - x_max
            energy_calibrated = np.where(
                high,
                float(self._antiderivative(x_max) - self._antiderivative(0.0))
                + self.tension[-1] * extra
                + 0.5 * terminal_slope * extra**2,
                energy_calibrated,
            )
        elastic_energy = energy_calibrated / length_scale

        viscous = np.where(active, self.viscosity * delta_dot**2 / rest_length, 0.0)
        # When unloading clips a negative Kelvin--Voigt trial force, no tensile
        # force is transmitted.  The stored-energy decrease is recorded as
        # release dissipation so that the work--energy ledger remains closed.
        release = np.where(
            (delta > 0.0) & ~active,
            np.maximum(-elastic * delta_dot, 0.0),
            0.0,
        )
        return AxialResponse(
            tension=tension,
            active=active,
            elastic_energy=elastic_energy,
            dissipation_rate=viscous + release,
            d_tension_d_delta=np.where(active, tangent_curve * length_scale, 0.0),
            d_tension_d_delta_dot=np.where(
                active, self.viscosity / rest_length, 0.0
            ),
        )

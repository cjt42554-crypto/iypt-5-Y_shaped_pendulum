"""Dimension-checked unit parsing with Pint and a deterministic SI fallback.

The public configuration accepts bare SI values or mappings such as
``{"value": 10, "unit": "cm", "source": "measured"}``.  Formal installs use
one process-wide Pint registry.  The fallback is deliberately small but still
checks physical dimensions; it is intended for restricted diagnostic
environments rather than as a second, looser unit system.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Any

import numpy as np
import numpy.typing as npt

try:  # pragma: no cover - exercised in release-install testing when available
    import pint
except ImportError:  # pragma: no cover - fallback is exercised in this container
    pint = None


class UnitError(ValueError):
    """Raised when a configuration quantity has an unsupported/incompatible unit."""


@dataclass(frozen=True)
class QuantityMeta:
    value_si: Any
    unit_input: str
    source: str | None = None
    uncertainty_si: Any | None = None


# factor to the SI unit used by the API, plus a conservative dimension label.
_FALLBACK_UNITS: dict[str, tuple[float, str]] = {
    "": (1.0, "dimensionless"),
    "1": (1.0, "dimensionless"),
    "dimensionless": (1.0, "dimensionless"),
    "m": (1.0, "length"),
    "meter": (1.0, "length"),
    "metre": (1.0, "length"),
    "cm": (1e-2, "length"),
    "mm": (1e-3, "length"),
    "um": (1e-6, "length"),
    "µm": (1e-6, "length"),
    "km": (1e3, "length"),
    "m^2": (1.0, "area"),
    "cm^2": (1e-4, "area"),
    "mm^2": (1e-6, "area"),
    "m^3": (1.0, "volume"),
    "cm^3": (1e-6, "volume"),
    "s": (1.0, "time"),
    "ms": (1e-3, "time"),
    "us": (1e-6, "time"),
    "min": (60.0, "time"),
    "hz": (1.0, "frequency"),
    "rad/s": (1.0, "frequency"),
    "1/s": (1.0, "frequency"),
    "m/s": (1.0, "velocity"),
    "cm/s": (1e-2, "velocity"),
    "mm/s": (1e-3, "velocity"),
    "m/s^2": (1.0, "acceleration"),
    "cm/s^2": (1e-2, "acceleration"),
    "kg": (1.0, "mass"),
    "g": (1e-3, "mass"),
    "mg": (1e-6, "mass"),
    "kg/m": (1.0, "linear_density"),
    "kg/m^3": (1.0, "density"),
    "g/cm^3": (1e3, "density"),
    "n": (1.0, "force"),
    "kn": (1e3, "force"),
    "pa": (1.0, "pressure"),
    "kpa": (1e3, "pressure"),
    "mpa": (1e6, "pressure"),
    "gpa": (1e9, "pressure"),
    "pa*s": (1.0, "dynamic_viscosity"),
    "n*s/m": (1.0, "linear_damping"),
    "kg/s": (1.0, "linear_damping"),
    "n*s/m^2": (1.0, "damping_per_length"),
    "kg/(m*s)": (1.0, "damping_per_length"),
    "rad": (1.0, "angle"),
    "degree": (np.pi / 180.0, "angle"),
    "degrees": (np.pi / 180.0, "angle"),
    "deg": (np.pi / 180.0, "angle"),
}


def _normalise_unit(unit: str | None) -> str:
    if unit is None:
        return ""
    return unit.strip().lower().replace("**", "^").replace(" ", "")


def _validate_numeric_payload(value: Any, *, allow_scalar_string: bool = False) -> None:
    """Reject Python values that NumPy/Pint would otherwise coerce silently."""

    if isinstance(value, (bool, np.bool_)):
        raise UnitError("Boolean values are not physical numbers.")
    if isinstance(value, str):
        if allow_scalar_string:
            return
        raise UnitError("String entries are not allowed inside numeric arrays.")
    if isinstance(value, np.ndarray):
        for item in value.reshape(-1).tolist():
            _validate_numeric_payload(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_numeric_payload(item)
        return
    if not isinstance(value, Real):
        raise UnitError(f"Expected a real physical number, got {type(value).__name__}.")


def _fallback_convert(value: Any, unit: str, *, expected_unit: str = "") -> Any:
    _validate_numeric_payload(value)
    key = _normalise_unit(unit)
    expected_key = _normalise_unit(expected_unit)
    if key not in _FALLBACK_UNITS:
        raise UnitError(
            f"Unsupported unit {unit!r}. Install Pint for broader unit support or use SI."
        )
    factor, dimension = _FALLBACK_UNITS[key]
    if expected_key:
        if expected_key not in _FALLBACK_UNITS:
            raise UnitError(
                f"Internal expected unit {expected_unit!r} is unavailable in the fallback parser."
            )
        expected_dimension = _FALLBACK_UNITS[expected_key][1]
        if dimension != expected_dimension:
            raise UnitError(
                f"Unit {unit!r} has dimension {dimension}, but {expected_unit!r} "
                f"({expected_dimension}) is required."
            )
    arr = np.asarray(value, dtype=float) * factor
    if not np.all(np.isfinite(arr)):
        raise UnitError("Quantity contains NaN or infinity.")
    return float(arr) if arr.ndim == 0 else arr


_UREG = pint.UnitRegistry() if pint is not None else None


def _validate_quantity_mapping(value: dict[str, Any]) -> None:
    allowed = {"value", "unit", "source", "uncertainty"}
    extra = set(value).difference(allowed)
    if extra:
        raise UnitError(f"Unknown quantity metadata fields: {sorted(extra)}")
    if "value" not in value:
        raise UnitError("A quantity mapping must contain a value field.")
    if "source" in value and not (
        isinstance(value["source"], str) and value["source"].strip()
    ):
        raise UnitError("Quantity source must be a non-empty string when present.")


def _pint_convert(raw: Any, unit: str, default_unit: str) -> Any:
    assert _UREG is not None
    try:
        if isinstance(raw, str):
            text = raw.strip()
            try:
                numeric_only = float(text)
            except ValueError:
                quantity = _UREG.Quantity(text)
            else:
                quantity = numeric_only * _UREG(unit or default_unit or "dimensionless")
        else:
            _validate_numeric_payload(raw)
            quantity = np.asarray(raw, dtype=float) * _UREG(unit or default_unit or "dimensionless")
        converted = quantity.to(default_unit) if default_unit else quantity.to_base_units()
    except Exception as exc:  # Pint exposes several unit-specific exception classes
        raise UnitError(
            f"Quantity {raw!r} {unit!r} is incompatible with expected unit {default_unit!r}: {exc}"
        ) from exc
    magnitude = np.asarray(converted.magnitude, dtype=float)
    if not np.all(np.isfinite(magnitude)):
        raise UnitError("Quantity contains NaN or infinity.")
    return float(magnitude) if magnitude.ndim == 0 else magnitude


def to_si(value: Any, *, default_unit: str = "") -> Any:
    """Convert a scalar/vector quantity to the SI unit stated by ``default_unit``.

    Bare numeric values are interpreted as already expressed in that SI unit.
    An explicitly supplied unit is dimension-checked against ``default_unit``.
    """

    if isinstance(value, dict) and "value" in value:
        _validate_quantity_mapping(value)
        raw = value["value"]
        supplied_unit = value.get("unit", default_unit)
        if not isinstance(supplied_unit, str):
            raise UnitError("Quantity unit must be a string.")
        unit = supplied_unit
        if isinstance(raw, str):
            parts = raw.strip().split(maxsplit=1)
            if len(parts) == 2 and "unit" in value:
                raise UnitError(
                    "Do not supply both an embedded unit in value and a separate unit field."
                )
    else:
        raw = value
        unit = default_unit

    _validate_numeric_payload(raw, allow_scalar_string=True)

    if _UREG is not None:
        return _pint_convert(raw, unit, default_unit)

    if isinstance(raw, str):
        parts = raw.strip().split(maxsplit=1)
        if len(parts) == 1:
            try:
                numeric = float(parts[0])
            except ValueError as exc:
                raise UnitError(f"Could not parse quantity string {raw!r}.") from exc
            return _fallback_convert(numeric, unit, expected_unit=default_unit)
        try:
            numeric = float(parts[0])
        except ValueError as exc:
            raise UnitError(f"Could not parse quantity string {raw!r}.") from exc
        return _fallback_convert(numeric, parts[1], expected_unit=default_unit)

    return _fallback_convert(raw, unit, expected_unit=default_unit)


def quantity_meta(value: Any, *, default_unit: str = "") -> QuantityMeta:
    if isinstance(value, dict) and "value" in value:
        _validate_quantity_mapping(value)
        unit = str(value.get("unit", default_unit))
        source = value.get("source")
        uncertainty = value.get("uncertainty")
        return QuantityMeta(
            value_si=to_si(value, default_unit=default_unit),
            unit_input=unit,
            source=None if source is None else str(source),
            uncertainty_si=None
            if uncertainty is None
            else to_si({"value": uncertainty, "unit": unit}, default_unit=default_unit),
        )
    return QuantityMeta(value_si=to_si(value, default_unit=default_unit), unit_input=default_unit)


def as_vector3(value: Any, *, default_unit: str = "") -> npt.NDArray[np.float64]:
    arr = np.asarray(to_si(value, default_unit=default_unit), dtype=float)
    if arr.shape != (3,):
        raise UnitError(f"Expected a three-component vector, got shape {arr.shape}.")
    if not np.all(np.isfinite(arr)):
        raise UnitError("Vector contains NaN or infinity.")
    return arr


def source_of(value: Any) -> str | None:
    if isinstance(value, dict):
        source = value.get("source")
        return None if source is None else str(source)
    return None

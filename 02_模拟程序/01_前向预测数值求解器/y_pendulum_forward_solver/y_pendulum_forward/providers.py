"""Registered, auditable input providers for JSON configurations.

Library users may add provider factories to the registries before constructing
a model.  This is the deliberate extension seam for future theory revisions;
unknown provider kinds fail closed instead of silently becoming zero inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .contracts import (
    ValidationIssue,
    as_vector3,
    is_finite_number,
    reject_unknown_keys,
    strict_finite_array,
)


HOLD_RELEASE_PROTOCOL_ID = "YP-HOLD-RELEASE-1.0"
HOLD_RELEASE_EXTENSION_THEORY_SHA256 = (
    "073ce907b4adcb9daca9bb41d9e275bc6c683472a326d113a1ee04eb9a634dcd"
)
HOLD_RELEASE_THEORY_SECTIONS = ("7.4", "7.5")


@dataclass(frozen=True)
class PrescribedMotion:
    position_fn: Callable[[float], np.ndarray]
    velocity_fn: Callable[[float], np.ndarray]
    acceleration_fn: Callable[[float], np.ndarray]
    description: dict[str, Any]

    def position(self, t: float) -> np.ndarray:
        return np.asarray(self.position_fn(float(t)), dtype=float)

    def velocity(self, t: float) -> np.ndarray:
        return np.asarray(self.velocity_fn(float(t)), dtype=float)

    def acceleration(self, t: float) -> np.ndarray:
        return np.asarray(self.acceleration_fn(float(t)), dtype=float)


@dataclass(frozen=True)
class AirVelocity:
    value_fn: Callable[[np.ndarray, float], np.ndarray]
    description: dict[str, Any]

    def value(self, position: np.ndarray, t: float) -> np.ndarray:
        return np.asarray(self.value_fn(np.asarray(position, dtype=float), float(t)), dtype=float)


@dataclass(frozen=True)
class MaterialForce:
    value_fn: Callable[[float, float], np.ndarray]
    description: dict[str, Any]

    def value(self, xi: float, t: float) -> np.ndarray:
        return np.asarray(self.value_fn(float(xi), float(t)), dtype=float)


@dataclass(frozen=True)
class PointForce:
    value_fn: Callable[[float], np.ndarray]
    description: dict[str, Any]

    def value(self, t: float) -> np.ndarray:
        return np.asarray(self.value_fn(float(t)), dtype=float)


@dataclass(frozen=True)
class HoldingForceRelease:
    """Prescribed multiplier for releasing a statically determined hold force.

    The force vector itself is the constraint reaction required by the prepared
    static state.  This provider only prescribes when and how that known force
    is withdrawn, so solver tolerances cannot move the release times.
    """

    source: str
    start: float
    duration: float
    history: str
    description: dict[str, Any]

    @property
    def end(self) -> float:
        return self.start + self.duration

    def multiplier(self, t: float) -> float:
        time = float(t)
        if self.history == "instantaneous":
            return 1.0 if time < self.start else 0.0
        if time <= self.start:
            return 1.0
        if time >= self.end:
            return 0.0
        phase = (time - self.start) / self.duration
        # C1 cubic smoothstep from one to zero.  The zero end slopes avoid a
        # force-rate jump without introducing any extra damping term.
        return float(1.0 - 3.0 * phase**2 + 2.0 * phase**3)


MOTION_FACTORIES: dict[str, Callable[..., PrescribedMotion]] = {}
AIR_FACTORIES: dict[str, Callable[..., AirVelocity]] = {}
MATERIAL_FORCE_FACTORIES: dict[str, Callable[..., MaterialForce]] = {}
POINT_FORCE_FACTORIES: dict[str, Callable[..., PointForce]] = {}


def _motion_constant(spec, path, issues):
    value = as_vector3(spec.get("value"), f"{path}.value", issues)
    zero = np.zeros(3)
    return PrescribedMotion(
        lambda _t, value=value: value.copy(),
        lambda _t, zero=zero: zero.copy(),
        lambda _t, zero=zero: zero.copy(),
        dict(spec),
    )


def _motion_harmonic(spec, path, issues):
    offset = as_vector3(spec.get("offset"), f"{path}.offset", issues)
    amplitude = as_vector3(spec.get("amplitude"), f"{path}.amplitude", issues)
    omega = spec.get("omega")
    phase = spec.get("phase", 0.0)
    if not is_finite_number(omega):
        issues.append(ValidationIssue("TYPE", f"{path}.omega", omega, "finite real number"))
        omega = 0.0
    if not is_finite_number(phase):
        issues.append(ValidationIssue("TYPE", f"{path}.phase", phase, "finite real number"))
        phase = 0.0
    omega = float(omega)
    phase = float(phase)
    with np.errstate(over="ignore", invalid="ignore"):
        velocity_amplitude = amplitude * omega
        acceleration_amplitude = velocity_amplitude * omega
    if not (
        np.all(np.isfinite(velocity_amplitude))
        and np.all(np.isfinite(acceleration_amplitude))
    ):
        issues.append(
            ValidationIssue(
                "PROVIDER_DERIVATIVE",
                path,
                {
                    "amplitude": spec.get("amplitude"),
                    "omega": spec.get("omega"),
                },
                "finite amplitude*omega and amplitude*omega^2",
            )
        )
        # Preserve aggregate validation without letting later compatibility
        # checks evaluate an already-known overflowing provider.
        velocity_amplitude = np.zeros(3)
        acceleration_amplitude = np.zeros(3)
    return PrescribedMotion(
        lambda t: offset + amplitude * np.sin(omega * t + phase),
        lambda t: velocity_amplitude * np.cos(omega * t + phase),
        lambda t: -acceleration_amplitude * np.sin(omega * t + phase),
        dict(spec),
    )


def _motion_polynomial(spec, path, issues):
    raw = spec.get("coefficients")
    coefficients = strict_finite_array(raw)
    conversion_ok = coefficients is not None
    if coefficients is None:
        coefficients = np.zeros((1, 3))
    if (
        not conversion_ok
        or coefficients.ndim != 2
        or coefficients.shape[1] != 3
        or coefficients.shape[0] < 1
    ):
        issues.append(
            ValidationIssue(
                "TYPE",
                f"{path}.coefficients",
                raw,
                "nonempty finite array [power, xyz] for sum c_k t^k",
            )
        )
        coefficients = np.zeros((1, 3))

    def evaluate(t, derivative):
        out = np.zeros(3)
        for power in range(derivative, coefficients.shape[0]):
            factor = 1.0
            for k in range(derivative):
                factor *= power - k
            out += factor * coefficients[power] * t ** (power - derivative)
        return out

    return PrescribedMotion(
        lambda t: evaluate(t, 0),
        lambda t: evaluate(t, 1),
        lambda t: evaluate(t, 2),
        dict(spec),
    )


def _air_zero(spec, _path, _issues):
    return AirVelocity(lambda _r, _t: np.zeros(3), dict(spec))


def _air_constant(spec, path, issues):
    value = as_vector3(spec.get("value"), f"{path}.value", issues)
    return AirVelocity(lambda _r, _t: value.copy(), dict(spec))


def _air_affine(spec, path, issues):
    offset = as_vector3(spec.get("offset"), f"{path}.offset", issues)
    time_rate = as_vector3(spec.get("time_rate", [0, 0, 0]), f"{path}.time_rate", issues)
    raw = spec.get("matrix")
    matrix = strict_finite_array(raw)
    conversion_ok = matrix is not None
    if matrix is None:
        matrix = np.zeros((3, 3))
    if not conversion_ok or matrix.shape != (3, 3):
        issues.append(
            ValidationIssue("TYPE", f"{path}.matrix", raw, "finite 3x3 matrix")
        )
        matrix = np.zeros((3, 3))
    return AirVelocity(lambda r, t: offset + matrix @ r + time_rate * t, dict(spec))


def _time_vector(spec, path, issues) -> Callable[[float], np.ndarray]:
    kind = spec.get("kind")
    if kind == "zero":
        return lambda _t: np.zeros(3)
    if kind == "constant":
        value = as_vector3(spec.get("value"), f"{path}.value", issues)
        return lambda _t: value.copy()
    if kind == "harmonic":
        offset = as_vector3(spec.get("offset", [0, 0, 0]), f"{path}.offset", issues)
        amplitude = as_vector3(spec.get("amplitude"), f"{path}.amplitude", issues)
        omega = spec.get("omega")
        phase = spec.get("phase", 0.0)
        if not is_finite_number(omega):
            issues.append(ValidationIssue("TYPE", f"{path}.omega", omega, "finite real number"))
            omega = 0.0
        if not is_finite_number(phase):
            issues.append(ValidationIssue("TYPE", f"{path}.phase", phase, "finite real number"))
            phase = 0.0
        return lambda t: offset + amplitude * np.sin(float(omega) * t + float(phase))
    issues.append(
        ValidationIssue(
            "PROVIDER_KIND",
            f"{path}.kind",
            kind,
            "one of zero, constant, harmonic",
        )
    )
    return lambda _t: np.zeros(3)


def _point_registered(spec, path, issues):
    fn = _time_vector(spec, path, issues)
    return PointForce(fn, dict(spec))


def _material_registered(spec, path, issues):
    time_fn = _time_vector(spec, path, issues)
    spatial_raw = spec.get("spatial_coefficients", [1.0])
    spatial = strict_finite_array(spatial_raw)
    conversion_ok = spatial is not None
    if spatial is None:
        spatial = np.ones(1)
    if not conversion_ok or spatial.ndim != 1 or spatial.size < 1:
        issues.append(
            ValidationIssue(
                "TYPE",
                f"{path}.spatial_coefficients",
                spatial_raw,
                "finite coefficients for sum a_k xi^k",
            )
        )
        spatial = np.ones(1)

    def value(xi, t):
        factor = sum(coef * xi**power for power, coef in enumerate(spatial))
        return factor * time_fn(t)

    return MaterialForce(value, dict(spec))


MOTION_FACTORIES.update(
    constant=_motion_constant,
    harmonic=_motion_harmonic,
    polynomial=_motion_polynomial,
)
AIR_FACTORIES.update(zero=_air_zero, constant=_air_constant, affine=_air_affine)
for _kind in ("zero", "constant", "harmonic"):
    POINT_FORCE_FACTORIES[_kind] = _point_registered
    MATERIAL_FORCE_FACTORIES[_kind] = _material_registered


def build_motion(spec: Any, path: str, issues: list[ValidationIssue]) -> PrescribedMotion:
    if not isinstance(spec, dict):
        issues.append(ValidationIssue("TYPE", path, spec, "provider object"))
        spec = {"kind": "constant", "value": [0, 0, 0]}
    kind = spec.get("kind")
    kind_key = kind if isinstance(kind, str) else None
    allowed = {
        "constant": {"kind", "value"},
        "harmonic": {"kind", "offset", "amplitude", "omega", "phase"},
        "polynomial": {"kind", "coefficients"},
    }.get(kind_key, {"kind"})
    reject_unknown_keys(spec, allowed, path, issues)
    factory = MOTION_FACTORIES.get(kind_key)
    if factory is None:
        issues.append(
            ValidationIssue(
                "PROVIDER_KIND",
                f"{path}.kind",
                spec.get("kind"),
                f"registered motion kind: {sorted(MOTION_FACTORIES)}",
            )
        )
        factory = _motion_constant
        spec = {"kind": "constant", "value": [0, 0, 0]}
    return factory(spec, path, issues)


def validate_motion_window(
    motion: PrescribedMotion,
    T: float,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    """Prove registered motion formulas stay finite on the frozen time window.

    The registered harmonic and polynomial families admit a direct envelope
    check.  This rejects finite JSON scalars whose products (for example
    ``omega*T`` or ``c_k*T**k``) overflow before the ODE solver is called.
    """

    if not is_finite_number(T) or float(T) < 0.0:
        return
    duration = float(T)
    description = motion.description
    kind = description.get("kind")
    finite_envelope = True
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        if kind == "harmonic":
            omega = description.get("omega")
            phase = description.get("phase", 0.0)
            offset = strict_finite_array(description.get("offset"))
            amplitude = strict_finite_array(description.get("amplitude"))
            phase_end = np.add(
                np.multiply(float(omega), duration), float(phase)
            ) if is_finite_number(omega) and is_finite_number(phase) else np.inf
            finite_envelope = bool(
                is_finite_number(omega)
                and is_finite_number(phase)
                and np.isfinite(phase_end)
                and offset is not None
                and offset.shape == (3,)
                and amplitude is not None
                and amplitude.shape == (3,)
                and np.all(np.isfinite(np.abs(offset) + np.abs(amplitude)))
            )
        elif kind == "polynomial":
            coefficients = strict_finite_array(description.get("coefficients"))
            finite_envelope = coefficients is not None
            if finite_envelope:
                assert coefficients is not None
                for derivative in (0, 1, 2):
                    envelope = np.zeros(3)
                    for power in range(derivative, coefficients.shape[0]):
                        factor = 1.0
                        for offset in range(derivative):
                            factor *= power - offset
                        try:
                            time_power = np.power(
                                duration, power - derivative
                            )
                            term = (
                                np.abs(coefficients[power])
                                * factor
                                * time_power
                            )
                            envelope = envelope + term
                        except (FloatingPointError, OverflowError, ValueError):
                            finite_envelope = False
                            break
                        if not (
                            np.all(np.isfinite(term))
                            and np.all(np.isfinite(envelope))
                        ):
                            finite_envelope = False
                            break
                    if not finite_envelope:
                        break
    sampled_finite = True
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        for t_value in (0.0, 0.5 * duration, duration):
            try:
                values = (
                    motion.position(t_value),
                    motion.velocity(t_value),
                    motion.acceleration(t_value),
                )
            except Exception:
                sampled_finite = False
                break
            if any(
                np.asarray(value).shape != (3,)
                or not np.all(np.isfinite(value))
                for value in values
            ):
                sampled_finite = False
                break
    if not finite_envelope or not sampled_finite:
        issues.append(
            ValidationIssue(
                "PROVIDER_WINDOW",
                path,
                description,
                "finite C2 registered motion on every t in [0,T]",
            )
        )


def validate_force_window(
    force: PointForce | MaterialForce,
    T: float,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    """Validate time phase and spatial envelope for registered force providers."""

    if not is_finite_number(T) or float(T) < 0.0:
        return
    duration = float(T)
    description = force.description
    valid = True
    temporal_envelope = np.zeros(3)
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        kind = description.get("kind")
        if kind == "harmonic":
            omega = description.get("omega")
            phase = description.get("phase", 0.0)
            offset = strict_finite_array(description.get("offset", [0, 0, 0]))
            amplitude = strict_finite_array(description.get("amplitude"))
            if not (
                is_finite_number(omega)
                and is_finite_number(phase)
                and offset is not None
                and offset.shape == (3,)
                and amplitude is not None
                and amplitude.shape == (3,)
            ):
                valid = False
            else:
                phase_end = np.add(
                    np.multiply(float(omega), duration), float(phase)
                )
                temporal_envelope = np.abs(offset) + np.abs(amplitude)
                valid = bool(
                    np.isfinite(phase_end)
                    and np.all(np.isfinite(temporal_envelope))
                )
        elif kind == "constant":
            constant = strict_finite_array(description.get("value"))
            if constant is None or constant.shape != (3,):
                valid = False
            else:
                temporal_envelope = np.abs(constant)
        if isinstance(force, MaterialForce):
            coefficients = strict_finite_array(
                description.get("spatial_coefficients", [1.0])
            )
            if coefficients is None or coefficients.ndim != 1:
                valid = False
            else:
                spatial_envelope = np.sum(np.abs(coefficients))
                if not (
                    np.isfinite(spatial_envelope)
                    and np.all(
                        np.isfinite(spatial_envelope * temporal_envelope)
                    )
                ):
                    valid = False
        times = (0.0, 0.5 * duration, duration)
        try:
            if isinstance(force, MaterialForce):
                samples = [
                    force.value(xi, t_value)
                    for xi in (0.0, 0.5, 1.0)
                    for t_value in times
                ]
            else:
                samples = [force.value(t_value) for t_value in times]
        except Exception:
            valid = False
            samples = []
    if not valid or any(
        np.asarray(value).shape != (3,)
        or not np.all(np.isfinite(value))
        for value in samples
    ):
        issues.append(
            ValidationIssue(
                "PROVIDER_WINDOW",
                path,
                description,
                "finite registered force on its full [0,T] input domain",
            )
        )


def validate_air_window(
    air: AirVelocity,
    T: float,
    reference_positions: list[np.ndarray],
    path: str,
    issues: list[ValidationIssue],
) -> None:
    """Validate affine time terms and representative finite-state evaluations."""

    if not is_finite_number(T) or float(T) < 0.0:
        return
    duration = float(T)
    description = air.description
    valid = True
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        if description.get("kind") == "affine":
            offset = strict_finite_array(description.get("offset"))
            time_rate = strict_finite_array(
                description.get("time_rate", [0.0, 0.0, 0.0])
            )
            matrix = strict_finite_array(description.get("matrix"))
            if (
                offset is None
                or offset.shape != (3,)
                or time_rate is None
                or time_rate.shape != (3,)
                or matrix is None
                or matrix.shape != (3, 3)
            ):
                valid = False
            else:
                temporal_envelope = (
                    np.abs(offset) + np.abs(time_rate) * duration
                )
                valid = bool(np.all(np.isfinite(temporal_envelope)))
                for position in reference_positions:
                    position_array = strict_finite_array(position)
                    if position_array is None or position_array.shape != (3,):
                        valid = False
                        break
                    state_envelope = (
                        temporal_envelope
                        + np.abs(matrix) @ np.abs(position_array)
                    )
                    if not np.all(np.isfinite(state_envelope)):
                        valid = False
                        break
        try:
            samples = [
                air.value(position, t_value)
                for position in reference_positions
                for t_value in (0.0, 0.5 * duration, duration)
            ]
        except Exception:
            valid = False
            samples = []
    if not valid or any(
        np.asarray(value).shape != (3,)
        or not np.all(np.isfinite(value))
        for value in samples
    ):
        issues.append(
            ValidationIssue(
                "PROVIDER_WINDOW",
                path,
                description,
                "finite registered air velocity over [0,T] at finite reference states",
            )
        )


def build_air(spec: Any, path: str, issues: list[ValidationIssue]) -> AirVelocity:
    if not isinstance(spec, dict):
        issues.append(ValidationIssue("TYPE", path, spec, "provider object"))
        spec = {"kind": "zero"}
    kind = spec.get("kind")
    kind_key = kind if isinstance(kind, str) else None
    allowed = {
        "zero": {"kind"},
        "constant": {"kind", "value"},
        "affine": {"kind", "offset", "matrix", "time_rate"},
    }.get(kind_key, {"kind"})
    reject_unknown_keys(spec, allowed, path, issues)
    factory = AIR_FACTORIES.get(kind_key)
    if factory is None:
        issues.append(
            ValidationIssue(
                "PROVIDER_KIND",
                f"{path}.kind",
                spec.get("kind"),
                f"registered air kind: {sorted(AIR_FACTORIES)}",
            )
        )
        factory = _air_zero
        spec = {"kind": "zero"}
    return factory(spec, path, issues)


def build_point_force(spec: Any, path: str, issues: list[ValidationIssue]) -> PointForce:
    if not isinstance(spec, dict):
        issues.append(ValidationIssue("TYPE", path, spec, "provider object"))
        spec = {"kind": "zero"}
    kind = spec.get("kind")
    kind_key = kind if isinstance(kind, str) else None
    allowed = {
        "zero": {"kind"},
        "constant": {"kind", "value"},
        "harmonic": {"kind", "offset", "amplitude", "omega", "phase"},
    }.get(kind_key, {"kind"})
    reject_unknown_keys(spec, allowed, path, issues)
    factory = POINT_FORCE_FACTORIES.get(kind_key)
    if factory is None:
        issues.append(
            ValidationIssue(
                "PROVIDER_KIND",
                f"{path}.kind",
                spec.get("kind"),
                f"registered point-force kind: {sorted(POINT_FORCE_FACTORIES)}",
            )
        )
        factory = _point_registered
        spec = {"kind": "zero"}
    return factory(spec, path, issues)


def build_holding_force_release(
    spec: Any,
    path: str,
    issues: list[ValidationIssue],
) -> HoldingForceRelease:
    """Build the explicit static-reaction withdrawal protocol.

    ``None`` retains the original ``STATIC_HOLD_RELEASE`` input semantics: the
    compatible held state is released instantaneously at ``t=0``.  New inputs
    should spell out all four fields so their provenance is present in the
    exported configuration and diagnostics.
    """

    implicit_legacy = spec is None
    if implicit_legacy:
        spec = {
            "source": "initial_static_reaction",
            "start": 0.0,
            "duration": 0.0,
            "history": "instantaneous",
        }
    if not isinstance(spec, dict):
        issues.append(ValidationIssue("TYPE", path, spec, "release protocol object"))
        spec = {
            "source": "initial_static_reaction",
            "start": 0.0,
            "duration": 0.0,
            "history": "instantaneous",
        }
    reject_unknown_keys(
        spec,
        {"source", "start", "duration", "history"},
        path,
        issues,
    )
    source = spec.get("source")
    if source != "initial_static_reaction":
        issues.append(
            ValidationIssue(
                "HOLD_RELEASE_SOURCE",
                f"{path}.source",
                source,
                "initial_static_reaction",
            )
        )
        source = "initial_static_reaction"
    history = spec.get("history")
    if history not in ("instantaneous", "smoothstep_c1"):
        issues.append(
            ValidationIssue(
                "HOLD_RELEASE_HISTORY",
                f"{path}.history",
                history,
                "instantaneous or smoothstep_c1",
            )
        )
        history = "instantaneous"
    start = spec.get("start")
    duration = spec.get("duration")
    if not is_finite_number(start) or float(start) < 0.0:
        issues.append(
            ValidationIssue(
                "HOLD_RELEASE_TIME", f"{path}.start", start, "finite and >= 0 s"
            )
        )
        start = 0.0
    if not is_finite_number(duration) or float(duration) < 0.0:
        issues.append(
            ValidationIssue(
                "HOLD_RELEASE_TIME",
                f"{path}.duration",
                duration,
                "finite and >= 0 s",
            )
        )
        duration = 0.0
    start = float(start)
    duration = float(duration)
    if history == "instantaneous" and duration != 0.0:
        issues.append(
            ValidationIssue(
                "HOLD_RELEASE_TIME",
                f"{path}.duration",
                duration,
                "exactly 0 s for instantaneous history",
            )
        )
    if history == "smoothstep_c1" and duration <= 0.0:
        issues.append(
            ValidationIssue(
                "HOLD_RELEASE_TIME",
                f"{path}.duration",
                duration,
                "> 0 s for smoothstep_c1 history",
            )
        )
        duration = 1.0
    description = {
        "protocol_id": HOLD_RELEASE_PROTOCOL_ID,
        "extension_theory_sha256": HOLD_RELEASE_EXTENSION_THEORY_SHA256,
        "theory_sections": list(HOLD_RELEASE_THEORY_SECTIONS),
        "source": source,
        "start": start,
        "duration": duration,
        "history": history,
        "implicit_legacy_default": implicit_legacy,
    }
    return HoldingForceRelease(source, start, duration, history, description)


def build_material_force(spec: Any, path: str, issues: list[ValidationIssue]) -> MaterialForce:
    if not isinstance(spec, dict):
        issues.append(ValidationIssue("TYPE", path, spec, "provider object"))
        spec = {"kind": "zero"}
    kind = spec.get("kind")
    kind_key = kind if isinstance(kind, str) else None
    allowed = {
        "zero": {"kind", "spatial_coefficients"},
        "constant": {"kind", "value", "spatial_coefficients"},
        "harmonic": {
            "kind",
            "offset",
            "amplitude",
            "omega",
            "phase",
            "spatial_coefficients",
        },
    }.get(kind_key, {"kind"})
    reject_unknown_keys(spec, allowed, path, issues)
    factory = MATERIAL_FORCE_FACTORIES.get(kind_key)
    if factory is None:
        issues.append(
            ValidationIssue(
                "PROVIDER_KIND",
                f"{path}.kind",
                spec.get("kind"),
                f"registered material-force kind: {sorted(MATERIAL_FORCE_FACTORIES)}",
            )
        )
        factory = _material_registered
        spec = {"kind": "zero"}
    return factory(spec, path, issues)

"""Fixed and prescribed support kinematics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
from scipy.interpolate import CubicSpline

from ypendulum.config.models import SupportConfig
from ypendulum.config.units import as_vector3, to_si

Array = npt.NDArray[np.float64]


@dataclass
class SupportMotion:
    kind: str
    base_position: Array
    amplitude: Array | None = None
    angular_frequency: float = 0.0
    phase: float = 0.0
    spline: CubicSpline | None = None
    time_bounds: tuple[float, float] | None = None

    @classmethod
    def from_config(
        cls, cfg: SupportConfig, *, base_directory: str | Path | None = None
    ) -> "SupportMotion":
        base = as_vector3(cfg.position, default_unit="m")
        if cfg.type == "fixed":
            return cls("fixed", base)
        assert cfg.motion is not None
        motion = cfg.motion
        if motion.model == "stationary":
            return cls("fixed", base)
        if motion.model == "sinusoidal":
            amplitude = as_vector3(motion.amplitude, default_unit="m")
            frequency = float(to_si(motion.frequency, default_unit="Hz"))
            phase = float(to_si(motion.phase, default_unit="rad"))
            return cls(
                "sinusoidal",
                base,
                amplitude=amplitude,
                angular_frequency=2.0 * np.pi * frequency,
                phase=phase,
            )
        if motion.model == "table":
            if not motion.table_file:
                raise ValueError("Table support motion requires table_file.")
            path = Path(motion.table_file).expanduser()
            if not path.is_absolute() and base_directory is not None:
                path = Path(base_directory) / path
            data = np.genfromtxt(path, delimiter=",", names=True)
            required = {"time", "x", "y", "z"}
            if not required.issubset(data.dtype.names or ()):
                raise ValueError(f"Support motion CSV must contain {sorted(required)}.")
            t = np.asarray(data["time"], dtype=float)
            xyz = np.column_stack([data["x"], data["y"], data["z"]])
            if np.any(np.diff(t) <= 0):
                raise ValueError("Support motion times must be strictly increasing.")
            spline = CubicSpline(t, xyz, axis=0, extrapolate=False)
            return cls("table", base, spline=spline, time_bounds=(float(t[0]), float(t[-1])))
        raise ValueError(f"Unsupported support motion model {motion.model!r}.")

    def state(self, t: float) -> tuple[Array, Array, Array]:
        if self.kind == "fixed":
            zero = np.zeros(3, dtype=float)
            return self.base_position.copy(), zero.copy(), zero.copy()
        if self.kind == "sinusoidal":
            assert self.amplitude is not None
            arg = self.angular_frequency * t + self.phase
            pos = self.base_position + self.amplitude * np.sin(arg)
            vel = self.amplitude * self.angular_frequency * np.cos(arg)
            acc = -self.amplitude * self.angular_frequency**2 * np.sin(arg)
            return pos, vel, acc
        assert self.spline is not None and self.time_bounds is not None
        if not self.time_bounds[0] <= t <= self.time_bounds[1]:
            raise ValueError(
                f"Prescribed support time {t:g} s lies outside table interval {self.time_bounds}."
            )
        return (
            self.base_position + np.asarray(self.spline(t), dtype=float),
            np.asarray(self.spline(t, 1), dtype=float),
            np.asarray(self.spline(t, 2), dtype=float),
        )

"""Numerical compatibility helpers shared by every revision entry point."""

from __future__ import annotations

from typing import Any

import numpy as np


def trapezoid_integral(
    values: Any,
    coordinates: Any | None = None,
    *,
    axis: int = -1,
) -> np.ndarray | np.floating[Any]:
    """Integrate without depending on either version-specific NumPy alias.

    The project supports NumPy 1.26, where ``numpy.trapezoid`` is absent, and
    current NumPy releases, where ``numpy.trapz`` is absent.  The short local
    implementation is the ordinary composite trapezoid rule and therefore
    also works with SciPy versions whose own compatibility wrapper still calls
    the removed NumPy name.  It is shared by CLI, tests and child processes;
    no runtime monkeypatch is needed.
    """

    y = np.asarray(values)
    moved = np.moveaxis(y, axis, -1)
    if coordinates is None:
        widths: Any = 1.0
    else:
        x = np.asarray(coordinates)
        if x.ndim == 1:
            widths = np.diff(x)
        else:
            widths = np.diff(np.moveaxis(x, axis, -1), axis=-1)
    panels = 0.5 * (moved[..., 1:] + moved[..., :-1]) * widths
    return np.sum(panels, axis=-1)

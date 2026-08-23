"""Spectrum computation with explicit metadata."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.signal import welch


def power_spectrum(time: np.ndarray, signal: np.ndarray) -> dict[str, Any]:
    t = np.asarray(time, dtype=float)
    x = np.asarray(signal, dtype=float)
    dt = float(np.median(np.diff(t)))
    fs = 1.0 / dt
    nperseg = min(len(t), max(32, 2 ** int(np.floor(np.log2(max(len(t) // 2, 2))))))
    f, p = welch(x - np.mean(x), fs=fs, nperseg=nperseg, detrend="linear", window="hann")
    return {
        "frequency_hz": f,
        "power": p,
        "sample_rate_hz": fs,
        "nperseg": nperseg,
        "window": "hann",
    }

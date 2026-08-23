"""State and trajectory closure metrics."""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree


def state_closure_error(
    time: np.ndarray,
    state: np.ndarray,
    period: float,
    *,
    scale: np.ndarray | None = None,
) -> float:
    t = np.asarray(time, dtype=float)
    y = np.asarray(state, dtype=float)
    if period <= 0 or t[-1] - t[0] < period:
        return float("nan")
    shifted_t = t[t <= t[-1] - period]
    if shifted_t.size < 2:
        return float("nan")
    shifted = np.column_stack(
        [np.interp(shifted_t + period, t, y[:, j]) for j in range(y.shape[1])]
    )
    base = np.column_stack([np.interp(shifted_t, t, y[:, j]) for j in range(y.shape[1])])
    if scale is None:
        scale = np.sqrt(np.mean((y - np.mean(y, axis=0)) ** 2, axis=0))
        scale = np.where(scale > 1e-15, scale, 1.0)
    diff = (shifted - base) / np.asarray(scale)
    return float(np.sqrt(np.mean(diff**2)))


def chamfer_distance(curve_a: np.ndarray, curve_b: np.ndarray) -> float:
    a = np.asarray(curve_a, dtype=float)
    b = np.asarray(curve_b, dtype=float)
    ta, tb = cKDTree(a), cKDTree(b)
    da = tb.query(a)[0]
    db = ta.query(b)[0]
    return float(0.5 * (np.mean(da) + np.mean(db)))


def hausdorff_distance(curve_a: np.ndarray, curve_b: np.ndarray) -> float:
    a = np.asarray(curve_a, dtype=float)
    b = np.asarray(curve_b, dtype=float)
    ta, tb = cKDTree(a), cKDTree(b)
    return float(max(np.max(tb.query(a)[0]), np.max(ta.query(b)[0])))

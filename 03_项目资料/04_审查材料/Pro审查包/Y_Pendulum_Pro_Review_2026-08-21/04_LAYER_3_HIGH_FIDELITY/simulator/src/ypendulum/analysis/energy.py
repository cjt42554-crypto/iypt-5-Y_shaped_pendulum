"""Energy-ledger diagnostics."""

from __future__ import annotations

import numpy as np


def energy_audit(energy: dict[str, np.ndarray]) -> dict[str, float | bool]:
    residual = np.asarray(energy["balance_residual"], dtype=float)
    return {
        "max_abs_balance_residual": float(np.max(np.abs(residual))),
        "final_balance_residual": float(residual[-1]),
        "finite": bool(np.all(np.isfinite(residual))),
    }

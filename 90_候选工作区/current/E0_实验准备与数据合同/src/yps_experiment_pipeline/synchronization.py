"""Common-event camera synchronization with explicit uncertainty."""

from __future__ import annotations

import numpy as np


class SynchronizationError(ValueError):
    pass


def estimate_event_offset(
    reference_event_times_s: np.ndarray,
    shifted_event_times_s: np.ndarray,
) -> dict[str, float | int]:
    """Estimate ``shifted - reference`` from paired common events."""

    reference = np.asarray(reference_event_times_s, dtype=float)
    shifted = np.asarray(shifted_event_times_s, dtype=float)
    if reference.ndim != 1 or shifted.shape != reference.shape or reference.size < 2:
        raise SynchronizationError(
            "paired event arrays must be one-dimensional with at least two events"
        )
    if not (np.all(np.isfinite(reference)) and np.all(np.isfinite(shifted))):
        raise SynchronizationError("event times must be finite")
    if not (np.all(np.diff(reference) > 0) and np.all(np.diff(shifted) > 0)):
        raise SynchronizationError("event times must be strictly increasing")
    differences = shifted - reference
    offset = float(np.median(differences))
    mad = float(np.median(np.abs(differences - offset)))
    robust_sigma = 1.4826 * mad
    uncertainty = robust_sigma / np.sqrt(reference.size)
    return {
        "paired_event_count": int(reference.size),
        "offset_s": offset,
        "standard_uncertainty_s": float(uncertainty),
        "maximum_residual_s": float(np.max(np.abs(differences - offset))),
    }


def align_timestamps(raw_timestamps_s: np.ndarray, offset_s: float) -> np.ndarray:
    """Map shifted-camera timestamps onto the reference clock."""

    raw = np.asarray(raw_timestamps_s, dtype=float)
    if raw.ndim != 1 or not np.all(np.isfinite(raw)) or not np.isfinite(offset_s):
        raise SynchronizationError("timestamps and offset must be finite")
    return raw - float(offset_s)

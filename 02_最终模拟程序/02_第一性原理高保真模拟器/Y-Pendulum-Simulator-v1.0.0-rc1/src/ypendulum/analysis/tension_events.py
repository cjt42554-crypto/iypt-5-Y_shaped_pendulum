"""Robust event extraction from continuous H1 output samples."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.integrate import trapezoid


def detect_tension_events(
    time: np.ndarray,
    tension: np.ndarray,
    active: np.ndarray,
    cable_slices: dict[str, slice],
    *,
    tension_tolerance: float | None = None,
    minimum_duration: float | None = None,
) -> list[dict[str, Any]]:
    t = np.asarray(time, dtype=float)
    T = np.asarray(tension, dtype=float)
    A = np.asarray(active, dtype=bool)
    if t.ndim != 1 or T.shape != A.shape or T.shape[0] != t.size:
        raise ValueError("Incompatible time/tension/active arrays.")
    scale = max(float(np.nanmax(T)) if T.size else 0.0, 1.0)
    tol = 1e-8 * scale if tension_tolerance is None else float(tension_tolerance)
    dt = float(np.median(np.diff(t))) if t.size > 1 else 0.0
    min_duration = max(2.0 * dt, 0.0) if minimum_duration is None else minimum_duration
    events: list[dict[str, Any]] = []

    for name, sl in cable_slices.items():
        element_active = A[:, sl] & (T[:, sl] > tol)
        # Element-level activation is part of the frozen output contract.  A
        # distributed cable can develop a local slack pocket before the whole
        # branch becomes inactive, so cable-level events alone lose useful
        # wave and re-tension information.
        for local in range(element_active.shape[1]):
            trace = element_active[:, local]
            transitions_local = np.diff(trace.astype(np.int8))
            if not trace[0]:
                events.append(
                    {
                        "type": "element_initially_slack",
                        "cable": name,
                        "element_local_index": int(local),
                        "time": float(t[0]),
                    }
                )
            for idx in np.where(transitions_local == -1)[0]:
                start = idx + 1
                next_active = np.where(trace[start:])[0]
                end = t.size - 1 if next_active.size == 0 else start + int(next_active[0])
                duration = float(t[end] - t[start])
                if duration + 1e-15 >= min_duration:
                    events.append(
                        {
                            "type": "element_slack",
                            "cable": name,
                            "element_local_index": int(local),
                            "time": float(t[start]),
                            "duration": duration,
                        }
                    )
            for idx in np.where(transitions_local == 1)[0]:
                k = idx + 1
                events.append(
                    {
                        "type": "element_retension",
                        "cable": name,
                        "element_local_index": int(local),
                        "time": float(t[k]),
                        "value": float(T[k, sl.start + local]),
                    }
                )

        # A serial cable transmits force end-to-end only if every element on
        # the path is tensile. A local slack pocket already disconnects the
        # branch, even when other elements remain stretched.
        cable_active = np.all(element_active, axis=1)
        cable_any_tension = np.any(element_active, axis=1)
        full_active_count = np.sum(element_active, axis=1)
        minimum_count = int(np.min(full_active_count))
        if minimum_count < element_active.shape[1]:
            k = int(np.argmin(full_active_count))
            events.append(
                {
                    "type": "cable_minimum_active_elements",
                    "cable": name,
                    "time": float(t[k]),
                    "value": minimum_count,
                    "total_elements": int(element_active.shape[1]),
                }
            )
        if not cable_active[0]:
            events.append(
                {
                    "type": "cable_initially_not_fully_taut",
                    "cable": name,
                    "time": float(t[0]),
                    "active_elements": int(full_active_count[0]),
                    "total_elements": int(element_active.shape[1]),
                }
            )
        transitions = np.diff(cable_active.astype(np.int8))
        for idx in np.where(transitions == -1)[0]:
            start = idx + 1
            end_candidates = np.where(cable_active[start:])[0]
            end = t.size - 1 if end_candidates.size == 0 else start + int(end_candidates[0])
            duration = float(t[end] - t[start])
            if duration + 1e-15 >= min_duration:
                events.append(
                    {
                        "type": "cable_slack",
                        "cable": name,
                        "time": float(t[start]),
                        "duration": duration,
                    }
                )
        for idx in np.where(transitions == 1)[0]:
            k = idx + 1
            window_samples = max(3, int(round(0.02 / max(dt, 1e-12))))
            stop = min(k + window_samples, t.size)
            trace = np.max(T[k:stop, sl], axis=1)
            local_time = t[k:stop]
            peak = float(np.max(trace)) if trace.size else 0.0
            peak_index = int(np.argmax(trace)) if trace.size else 0
            impulse = float(trapezoid(trace, local_time)) if trace.size >= 2 else 0.0
            half = 0.5 * peak
            above = np.flatnonzero(trace >= half) if peak > 0.0 else np.array([], dtype=int)
            fwhm = (
                float(local_time[above[-1]] - local_time[above[0]] + dt)
                if above.size
                else 0.0
            )
            events.append(
                {
                    "type": "cable_retension",
                    "cable": name,
                    "time": float(t[k]),
                    "peak_tension_near_event": peak,
                    "peak_time_near_event": float(local_time[peak_index]) if trace.size else float(t[k]),
                    "tension_impulse_window_Ns": impulse,
                    "pulse_fwhm_s": fwhm,
                    "analysis_window_s": float(local_time[-1] - local_time[0]) if trace.size >= 2 else 0.0,
                    "output_dt_s": dt,
                    "peak_samples_above_half": int(above.size),
                    "peak_resolution_warning": bool(above.size < 3),
                }
            )
        fully_unloaded = ~cable_any_tension
        full_transitions = np.diff(fully_unloaded.astype(np.int8))
        if fully_unloaded[0]:
            events.append(
                {"type": "cable_initially_fully_unloaded", "cable": name, "time": float(t[0])}
            )
        for idx in np.where(full_transitions == 1)[0]:
            events.append(
                {"type": "cable_fully_unloaded", "cable": name, "time": float(t[idx + 1])}
            )
        for idx in np.where(full_transitions == -1)[0]:
            events.append(
                {"type": "cable_first_local_retension", "cable": name, "time": float(t[idx + 1])}
            )

        cable_tension = T[:, sl]
        if cable_tension.size:
            max_index = np.unravel_index(np.argmax(cable_tension), cable_tension.shape)
            events.append(
                {
                    "type": "cable_peak_tension",
                    "cable": name,
                    "time": float(t[max_index[0]]),
                    "value": float(cable_tension[max_index]),
                    "element_local_index": int(max_index[1]),
                }
            )

    # A Y-branch switch is a release of one upper cable while the other remains active.
    if "upper_A" in cable_slices and "upper_B" in cable_slices:
        aa = np.all(
            A[:, cable_slices["upper_A"]]
            & (T[:, cable_slices["upper_A"]] > tol),
            axis=1,
        )
        ab = np.all(
            A[:, cable_slices["upper_B"]]
            & (T[:, cable_slices["upper_B"]] > tol),
            axis=1,
        )
        one = aa ^ ab
        starts = np.where(np.diff(one.astype(np.int8)) == 1)[0] + 1
        for k in starts:
            events.append(
                {
                    "type": "upper_branch_switch",
                    "active_upper": "upper_A" if aa[k] else "upper_B",
                    "time": float(t[k]),
                }
            )
    events.sort(key=lambda item: (float(item.get("time", 0.0)), str(item.get("type", ""))))
    return events

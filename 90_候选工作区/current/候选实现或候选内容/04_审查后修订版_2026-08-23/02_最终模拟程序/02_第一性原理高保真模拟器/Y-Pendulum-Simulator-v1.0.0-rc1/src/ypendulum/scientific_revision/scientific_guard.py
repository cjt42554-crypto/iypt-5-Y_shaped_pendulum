"""Scientific display guards for finite-window trajectories and model mechanisms."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class FrequencyPreview:
    status: str
    frequency_hz: float | None
    observed_cycles: float
    window_frequency_spread_relative: float | None
    reason: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reason"] = list(self.reason)
        return payload


def _validated_series(time: np.ndarray, signal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    t = np.asarray(time, dtype=float).reshape(-1)
    y = np.asarray(signal, dtype=float).reshape(-1)
    if t.size != y.size or t.size < 4:
        raise ValueError("频率预览至少需要四个等长时间/信号样本。")
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(y)):
        raise ValueError("频率预览拒绝非有限样本。")
    if np.any(np.diff(t) <= 0.0):
        raise ValueError("时间轴必须严格递增。")
    return t, y


def detrended_signal(time: np.ndarray, signal: np.ndarray) -> np.ndarray:
    t, y = _validated_series(time, signal)
    centered_t = t - np.mean(t)
    matrix = np.column_stack((centered_t, np.ones_like(centered_t)))
    coefficients, *_ = np.linalg.lstsq(matrix, y, rcond=None)
    return y - matrix @ coefficients


def observed_cycle_count(time: np.ndarray, signal: np.ndarray) -> float:
    t, y = _validated_series(time, signal)
    residual = detrended_signal(t, y)
    scale = float(np.max(np.abs(residual)))
    if scale <= 64.0 * np.finfo(float).eps:
        return 0.0
    deadband = 1.0e-6 * scale
    values = residual.copy()
    values[np.abs(values) < deadband] = 0.0
    upward = np.flatnonzero((values[:-1] <= 0.0) & (values[1:] > 0.0))
    if upward.size < 2:
        return 0.0
    crossing_time: list[float] = []
    for index in upward:
        left, right = values[index], values[index + 1]
        fraction = 0.0 if right == left else float(-left / (right - left))
        crossing_time.append(float(t[index] + fraction * (t[index + 1] - t[index])))
    periods = np.diff(crossing_time)
    if periods.size == 0 or np.any(periods <= 0.0):
        return 0.0
    return float((t[-1] - t[0]) / np.median(periods))


def preview_spectrum(
    time: np.ndarray,
    signal: np.ndarray,
    *,
    minimum_samples: int = 256,
    maximum_samples: int = 8192,
) -> tuple[np.ndarray, np.ndarray, int]:
    t, y = _validated_series(time, signal)
    count = min(maximum_samples, max(minimum_samples, t.size))
    uniform_time = np.linspace(t[0], t[-1], count)
    uniform_signal = np.interp(uniform_time, t, detrended_signal(t, y))
    window = np.hanning(count)
    normalization = max(float(np.sum(window)), np.finfo(float).tiny)
    amplitude = 2.0 * np.abs(np.fft.rfft(uniform_signal * window)) / normalization
    frequency = np.fft.rfftfreq(count, float(uniform_time[1] - uniform_time[0]))
    if frequency.size <= 3:
        raise ValueError("频谱网格过短。")
    peak_index = int(np.argmax(amplitude[1:]) + 1)
    return frequency, amplitude, peak_index


def _window_peak_frequency(time: np.ndarray, signal: np.ndarray, fraction: float) -> float | None:
    t, y = _validated_series(time, signal)
    start = int(np.floor((1.0 - fraction) * t.size))
    start = min(max(start, 0), t.size - 4)
    sliced_t = t[start:]
    sliced_y = y[start:]
    if observed_cycle_count(sliced_t, sliced_y) < 1.5:
        return None
    frequency, _, peak = preview_spectrum(sliced_t, sliced_y)
    return float(frequency[peak])


def frequency_preview(
    time: np.ndarray,
    signal: np.ndarray,
    *,
    minimum_cycles: float = 3.0,
    maximum_window_spread_relative: float = 0.02,
) -> FrequencyPreview:
    t, y = _validated_series(time, signal)
    cycles = observed_cycle_count(t, y)
    reasons: list[str] = []
    if cycles < minimum_cycles:
        reasons.append(f"only_{cycles:.3g}_cycles_observed")
        return FrequencyPreview("UNAVAILABLE", None, cycles, None, tuple(reasons))
    frequency, _, peak = preview_spectrum(t, y)
    if peak <= 1 or peak >= frequency.size - 2:
        reasons.append("frequency_at_search_boundary")
    window_peaks = [
        value
        for fraction in (0.6, 0.8, 1.0)
        if (value := _window_peak_frequency(t, y, fraction)) is not None
    ]
    spread: float | None = None
    if len(window_peaks) >= 2:
        denominator = max(float(np.mean(window_peaks)), np.finfo(float).tiny)
        spread = float((max(window_peaks) - min(window_peaks)) / denominator)
        if spread > maximum_window_spread_relative:
            reasons.append("window_frequency_not_stable")
    else:
        reasons.append("insufficient_subwindow_cycles")
    status = "PREVIEW_STABLE" if not reasons else "PREVIEW_UNRELIABLE"
    return FrequencyPreview(
        status=status,
        frequency_hz=float(frequency[peak]),
        observed_cycles=cycles,
        window_frequency_spread_relative=spread,
        reason=tuple(reasons),
    )


def mechanism_audit(
    *,
    minimum_signed_axial_force_N: float,
    bending_energy_fraction_peak: float,
    compression_tolerance_N: float = 1.0e-10,
    significant_bending_fraction: float = 0.05,
) -> dict[str, Any]:
    compression_active = minimum_signed_axial_force_N < -abs(compression_tolerance_N)
    bending_significant = bending_energy_fraction_peak > significant_bending_fraction
    warnings: list[str] = []
    if compression_active:
        warnings.append("HF 轨迹实际激活了承压分支；它不是仅受拉绳的更细网格版本。")
    if bending_significant:
        warnings.append("弯曲能占比不可忽略；EI 的独立测量误差可能主导宏观轨迹。")
    return {
        "compression_active": compression_active,
        "bending_significant": bending_significant,
        "recommended_geometry_view": (
            "RAW_MATERIAL_PATH" if compression_active or bending_significant else "ENDPOINT_CHORD"
        ),
        "warnings": warnings,
    }


def audit_summary_mapping(summary: Mapping[str, Any]) -> dict[str, Any]:
    minimum_signed = float(summary.get("minimum_signed_axial_force_N", 0.0))
    bending_fraction = float(summary.get("bending_energy_fraction_peak", 0.0))
    audit = mechanism_audit(
        minimum_signed_axial_force_N=minimum_signed,
        bending_energy_fraction_peak=bending_fraction,
    )
    audit["raw_status"] = str(summary.get("numerical_status", summary.get("status", "UNKNOWN")))
    audit["physical_status"] = str(summary.get("physical_status", "UNKNOWN"))
    audit["formal_frequency_allowed"] = bool(
        summary.get("frequency_claim_level") == "FORMAL_CERTIFIED"
        and summary.get("frequency_analysis_reliable", False)
    )
    if not audit["formal_frequency_allowed"]:
        audit["warnings"].append("当前结果不得显示为正式频率、频率比或锁频结论。")
    return audit

"""Low-frequency modal coordinates and frequency estimation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.linalg import eigh
from scipy.optimize import minimize_scalar
from scipy.signal import welch


@dataclass(frozen=True)
class HorizontalBasis:
    fast: np.ndarray
    slow: np.ndarray
    vertical_up: np.ndarray


@dataclass(frozen=True)
class FrequencyEstimate:
    frequency_hz: float
    amplitude: float
    fit_r2: float
    observed_cycles: float
    sample_time_jitter: float
    reliable: bool
    reason: str


def horizontal_basis(
    support_a: np.ndarray, support_b: np.ndarray, gravity: np.ndarray
) -> HorizontalBasis:
    g = np.asarray(gravity, dtype=float)
    vertical_down = g / np.linalg.norm(g)
    up = -vertical_down
    support_axis = np.asarray(support_b, dtype=float) - np.asarray(support_a, dtype=float)
    projected = support_axis - np.dot(support_axis, vertical_down) * vertical_down
    if np.linalg.norm(projected) < 1e-12:
        trial = np.array([1.0, 0.0, 0.0])
        if abs(np.dot(trial, vertical_down)) > 0.9:
            trial = np.array([0.0, 1.0, 0.0])
        projected = trial - np.dot(trial, vertical_down) * vertical_down
    fast = projected / np.linalg.norm(projected)
    slow = np.cross(vertical_down, fast)
    slow /= np.linalg.norm(slow)
    return HorizontalBasis(fast, slow, up)


def modal_coordinates(
    bob_position: np.ndarray,
    support_a: np.ndarray,
    support_b: np.ndarray,
    gravity: np.ndarray,
    *,
    origin: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, HorizontalBasis]:
    pos = np.asarray(bob_position, dtype=float)
    basis = horizontal_basis(support_a, support_b, gravity)
    if origin is None:
        origin = np.mean(pos, axis=0)
    delta = pos - np.asarray(origin, dtype=float)
    return delta @ basis.fast, delta @ basis.slow, basis


def _sinusoid_fit_score(time: np.ndarray, signal: np.ndarray, frequency: float) -> tuple[float, np.ndarray]:
    """Return residual sum of squares and linear coefficients at a trial frequency."""

    centered_t = time - float(np.mean(time))
    angle = 2.0 * np.pi * frequency * centered_t
    design = np.column_stack(
        [np.cos(angle), np.sin(angle), np.ones_like(centered_t), centered_t]
    )
    coefficients, *_ = np.linalg.lstsq(design, signal, rcond=None)
    residual = signal - design @ coefficients
    return float(np.dot(residual, residual)), coefficients


def estimate_dominant_frequency(
    time: np.ndarray,
    signal: np.ndarray,
    *,
    maximum_frequency: float | None = None,
    minimum_cycles: float = 3.0,
    minimum_fit_r2: float = 0.5,
) -> FrequencyEstimate:
    """Estimate a nearly periodic dominant frequency without FFT-bin quantisation.

    A full-record Hann spectrum provides a local basin. The frequency is then
    refined continuously by minimising the residual of a sinusoid plus offset
    and linear trend. The function reports reliability rather than turning a
    fraction of a cycle into a precise-looking frequency.
    """

    t = np.asarray(time, dtype=float)
    x = np.asarray(signal, dtype=float)
    if t.ndim != 1 or x.shape != t.shape or t.size < 12:
        return FrequencyEstimate(float("nan"), 0.0, float("nan"), 0.0, float("inf"), False, "insufficient_samples")
    dt_values = np.diff(t)
    if np.any(dt_values <= 0) or not np.all(np.isfinite(dt_values)):
        return FrequencyEstimate(float("nan"), 0.0, float("nan"), 0.0, float("inf"), False, "invalid_time_axis")
    dt = float(np.median(dt_values))
    duration = float(t[-1] - t[0])
    jitter = float(np.max(np.abs(dt_values - dt)) / max(dt, 1e-15))
    if duration <= 0.0:
        return FrequencyEstimate(float("nan"), 0.0, float("nan"), 0.0, jitter, False, "zero_duration")

    centered_t = t - float(np.mean(t))
    trend_design = np.column_stack([np.ones_like(centered_t), centered_t])
    trend, *_ = np.linalg.lstsq(trend_design, x, rcond=None)
    detrended = x - trend_design @ trend
    signal_rms = float(np.sqrt(np.mean(detrended**2)))
    if not np.isfinite(signal_rms) or signal_rms <= 1e-14:
        return FrequencyEstimate(float("nan"), 0.0, float("nan"), 0.0, jitter, False, "modal_amplitude_too_small")

    nyquist = 0.5 / dt
    upper = min(0.45 / dt, nyquist * 0.95)
    if maximum_frequency is not None:
        upper = min(upper, float(maximum_frequency))
    lower = max(0.25 / duration, 1e-12)
    if not lower < upper:
        return FrequencyEstimate(float("nan"), 0.0, float("nan"), 0.0, jitter, False, "no_frequency_band")

    nfft_target = max(256, 16 * t.size)
    nfft = 1 << int(np.ceil(np.log2(nfft_target)))
    window = np.hanning(t.size)
    spectrum = np.abs(np.fft.rfft(detrended * window, n=nfft)) ** 2
    frequencies = np.fft.rfftfreq(nfft, dt)
    mask = (frequencies >= lower) & (frequencies <= upper)
    if not np.any(mask):
        return FrequencyEstimate(float("nan"), 0.0, float("nan"), 0.0, jitter, False, "empty_frequency_band")
    masked_indices = np.flatnonzero(mask)
    peak_index = int(masked_indices[np.argmax(spectrum[mask])])
    coarse = float(frequencies[peak_index])

    half_width = max(1.5 / duration, 3.0 * (frequencies[1] - frequencies[0]))
    bracket_low = max(lower, coarse - half_width)
    bracket_high = min(upper, coarse + half_width)
    if not bracket_low < bracket_high:
        bracket_low, bracket_high = lower, upper

    objective = lambda f: _sinusoid_fit_score(t, x, float(f))[0]
    optimum = minimize_scalar(
        objective,
        bounds=(bracket_low, bracket_high),
        method="bounded",
        options={"xatol": max(1e-12, 1e-9 / duration)},
    )
    frequency = float(optimum.x if optimum.success else coarse)
    sse, coefficients = _sinusoid_fit_score(t, x, frequency)
    centered = x - float(np.mean(x))
    sst = float(np.dot(centered, centered))
    r2 = float(1.0 - sse / max(sst, 1e-30))
    amplitude = float(np.hypot(coefficients[0], coefficients[1]))
    cycles = frequency * duration

    reasons: list[str] = []
    if cycles < minimum_cycles:
        reasons.append(f"only_{cycles:.3g}_cycles_observed")
    if r2 < minimum_fit_r2:
        reasons.append(f"sinusoid_fit_r2_{r2:.3g}")
    if jitter > 1e-3:
        reasons.append(f"sample_time_jitter_{jitter:.3g}")
    if frequency <= lower * 1.01 or frequency >= upper * 0.99:
        reasons.append("frequency_at_search_boundary")
    reliable = not reasons
    return FrequencyEstimate(
        frequency_hz=frequency,
        amplitude=amplitude,
        fit_r2=r2,
        observed_cycles=cycles,
        sample_time_jitter=jitter,
        reliable=reliable,
        reason="ok" if reliable else ";".join(reasons),
    )


def dominant_frequencies(
    time: np.ndarray,
    signals: np.ndarray,
    *,
    maximum_frequency: float | None = None,
) -> list[float]:
    """Compatibility wrapper returning refined frequency candidates."""

    x = np.asarray(signals, dtype=float)
    if x.ndim == 1:
        x = x[:, None]
    return [
        estimate_dominant_frequency(
            np.asarray(time, dtype=float), column, maximum_frequency=maximum_frequency
        ).frequency_hz
        for column in x.T
    ]


def dominant_frequency_estimates(
    time: np.ndarray,
    signals: np.ndarray,
    *,
    maximum_frequency: float | None = None,
    minimum_cycles: float = 3.0,
) -> list[FrequencyEstimate]:
    x = np.asarray(signals, dtype=float)
    if x.ndim == 1:
        x = x[:, None]
    return [
        estimate_dominant_frequency(
            np.asarray(time, dtype=float),
            column,
            maximum_frequency=maximum_frequency,
            minimum_cycles=minimum_cycles,
        )
        for column in x.T
    ]


def linearised_modes(model, positions: np.ndarray, *, count: int = 2) -> dict[str, np.ndarray]:
    """Return bob-dominated small-vibration modes about a taut equilibrium.

    The tangent is obtained from the same element implementation used by the
    nonlinear solver.  Candidate modes are ranked by frequency after requiring
    non-negligible bob kinetic participation; this prevents internal cable or
    junction modes from being mistaken for the two pendulum modes on refined
    or unusually light meshes.
    """

    qf = model.topology.pack_free(np.asarray(positions, dtype=float))
    evaluation = model.evaluate(
        0.0,
        qf,
        np.zeros_like(qf),
        compute_tangent=True,
        include_aero=False,
    )
    if evaluation.tangent_position is None:
        raise RuntimeError("Model did not provide a position tangent.")
    fd = model.topology.free_dofs
    stiffness = -evaluation.tangent_position[fd][:, fd].toarray()
    mass = model.mass_ff.toarray()
    stiffness = 0.5 * (stiffness + stiffness.T)
    mass = 0.5 * (mass + mass.T)
    eigenvalues, eigenvectors = eigh(stiffness, mass, check_finite=True)
    positive = np.where(eigenvalues > max(1.0e-10, 1.0e-12 * np.max(np.abs(eigenvalues))))[0]

    node_to_offset = {
        int(node): 3 * idx for idx, node in enumerate(model.topology.free_nodes.tolist())
    }
    bob_base = node_to_offset[int(model.topology.bob_node)]
    bob_dofs = np.arange(bob_base, bob_base + 3)
    m_bb = mass[np.ix_(bob_dofs, bob_dofs)]
    participations: list[tuple[int, float]] = []
    for index in positive:
        vector = eigenvectors[:, index]
        bob_fraction = float(vector[bob_dofs] @ m_bb @ vector[bob_dofs])
        participations.append((int(index), bob_fraction))

    selected = [index for index, fraction in participations if fraction >= 0.05]
    if len(selected) < count:
        selected = [index for index, _fraction in participations]
    selected = selected[:count]
    if len(selected) < count:
        raise RuntimeError(f"Only {len(selected)} positive modes were found; requested {count}.")

    values = eigenvalues[selected]
    vectors = eigenvectors[:, selected]
    participation_by_index = dict(participations)
    fractions = np.asarray([participation_by_index[index] for index in selected])
    return {
        "angular_frequency": np.sqrt(values),
        "frequency_hz": np.sqrt(values) / (2.0 * np.pi),
        "eigenvalue": values,
        "eigenvector": vectors,
        "bob_kinetic_participation": fractions,
    }


def linearised_mode_summary(model, positions: np.ndarray, *, count: int = 2) -> list[dict[str, object]]:
    """Return interpretable summaries of bob-participating H1 modes."""

    result = linearised_modes(model, positions, count=count)
    vectors = np.asarray(result["eigenvector"], dtype=float)
    supports = np.asarray(positions, dtype=float)[model.topology.support_nodes]
    basis = horizontal_basis(supports[0], supports[1], model.gravity)
    node_to_offset = {
        int(node): 3 * idx for idx, node in enumerate(model.topology.free_nodes.tolist())
    }
    bob_base = node_to_offset[int(model.topology.bob_node)]
    junction_base = node_to_offset[int(model.topology.junction_node)]
    summaries: list[dict[str, object]] = []
    for mode_index in range(vectors.shape[1]):
        vector = vectors[:, mode_index]
        bob = vector[bob_base : bob_base + 3]
        junction = vector[junction_base : junction_base + 3]
        bob_norm = float(np.linalg.norm(bob))
        bob_direction = bob / bob_norm if bob_norm > 1e-15 else np.zeros(3)
        projections = {
            "support_axis_fast": float(abs(np.dot(bob_direction, basis.fast))),
            "transverse_slow": float(abs(np.dot(bob_direction, basis.slow))),
            "vertical": float(abs(np.dot(bob_direction, basis.vertical_up))),
        }
        label = max(projections, key=projections.get)
        summaries.append(
            {
                "index": mode_index,
                "angular_frequency_rad_s": float(result["angular_frequency"][mode_index]),
                "frequency_hz": float(result["frequency_hz"][mode_index]),
                "bob_kinetic_participation": float(result["bob_kinetic_participation"][mode_index]),
                "bob_direction_world": bob_direction.tolist(),
                "junction_to_bob_displacement_ratio": float(np.linalg.norm(junction) / max(bob_norm, 1e-30)),
                "direction_projections": projections,
                "descriptive_label": label,
            }
        )
    return summaries

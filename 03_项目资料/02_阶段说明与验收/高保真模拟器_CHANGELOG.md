# Changelog

## Unreleased — 2026-08-22

### Native desktop GUI

- Renamed the ambiguous junction-to-COM input to the effective lower-branch
  length, made the finite-bob attachment offset an explicit HF-only detail,
  and removed the uncalibrated default material stretch/rate box while keeping
  the nondegenerate geometry and `lambda_min` guards.
- Replaced routine Cartesian initial-state editing with a reversible
  support/gravity-frame length-and-angle editor covering release geometry,
  endpoint rates and HF rigid-bob spin.  Both backend coordinate states and
  FWD branch position/velocity polynomials are generated consistently, while
  a deliberate expert Cartesian fallback preserves moving-support and legacy
  snapshot states that the compact basis cannot represent losslessly.
- Restyled the native dashboard after the current vortex-pendulum research UI:
  monochrome hierarchy, narrow configuration sidebar, auditable summary cards,
  and a result-first workspace.
- Added real 3D trajectory playback with play/pause, stop, stepping, scrubbing,
  speed and loop controls.
- Fixed pre-result playback state handling: clicking Play while the selected job
  is queued, running or paused now reserves autoplay, clears the false
  "no playable result" diagnostic, loads that exact job at completion and then
  starts the animation; the waiting request remains explicitly cancellable.
- Synchronized FWD/HF geometry on a shared physical-time interval with linear
  interpolation, fixed whole-run scene bounds and persistent camera view.
- Corrected the visual coordinate convention so the solver's positive-down
  `z` axis is displayed downward, and rendered the FWD equivalent-volume bob
  radius alongside the finite HF bob.
- Kept the complete parameter tree usable by showing repeat, batch and sweep
  controls only in their corresponding workflow modes.
- Added a fresh 0.12 s, exact-grid FWD/HF comparison and a self-contained Pro
  review handoff that preserves the unresolved experiment-selection boundary.
- Replaced the installation-only 0.2 ms default with an 8 s multi-cycle
  interactive preview, using explicitly labelled preview meshes and live
  fast/slow reference-cycle coverage in the configuration panel.
- Added an equal-scale full-window x-y Lissajous tab plus a persistent animated
  top-view trajectory beside the 3D apparatus.
- Made the auditable summary and job queue independently collapsible and
  auto-collapsed both after result loading, increasing the result-notebook
  height from 358 px to 704 px in the validated 1600 x 900 window.
- Reworked every scientific legend: equal-scale plots use their natural side
  whitespace, state/force/analysis use compact semantic keys, and the large
  energy/guard indexes live outside the axes with zero measured data overlap.
- Bounded long inline diagnostics, pinned the action row above a scrollable
  workflow field area in every run mode at the 1180 x 720 minimum window, and
  exposed complete scrollable/copyable error details in a separate window.
- Routed background result-reader completions through a main-thread queue so
  Tk widgets are never mutated from the reader thread.
- Completed a real 8 s dual-backend desktop run and wrote a standalone Pro
  handoff for the unresolved centimetre-scale model-form difference.

## 1.0.0rc1 — 2026-08-18

### Physics and numerical core

- Added finite-mass, geometric nonlinear, tension-only three-cable H1 model with consistent/lumped mass matrices.
- Added fixed and prescribed moving supports, boundary inertial coupling, support reactions/work, bob/string aerodynamics and buoyancy.
- Added exact piecewise Kelvin–Voigt and mesh-objective tabulated tension-extension laws.
- Separated tabulated calibration specimen length from installed cable length.
- Added finite-mass junction, prestressed elastic initial geometry and loaded static equilibrium.
- Added local generalized-stiffness stability audit after force equilibrium.
- Added a mass-weighted taut-compatibility projection for constructed initial velocities, preserving the requested bob velocity while avoiding mesh-interpolation axial pulses.
- Added Radau/BDF paths and sparse second-order implicit Newmark cross-solver.
- Corrected element stiffness to use `EA/L_element` and corrected serial-cable branch activity: one local slack element disconnects the tensile path.
- Added output-derived retension peak, impulse-window and pulse-width metrics plus convergence gates.

### Prediction and validation

- Replaced coarse Welch-bin frequency declaration with full-record spectral seeding plus continuous sinusoid/trend refinement.
- Added reliability refusal for records with too few cycles, poor fit or boundary-limited frequency estimates.
- Added H1 static linear mode analysis from the same mass matrix and nonlinear tangent.
- Added comprehensive preflight scale/scope/observability/provenance diagnostics and configuration claim cap.
- Added run validity audit distinguishing low-frequency, stationary two-frequency, cable-wave and retension-peak support.
- Added direct experiment CSV comparison with no nuisance fitting by default and explicit constant alignment options.
- Added structural validation-manifest contract for `VALIDATED`/`PREDICTIVE` claims.
- Added independent axial calibration with uncertainty and monotone table export, plus damping-envelope model diagnostics.

### Software delivery

- Added config and validation-manifest JSON schemas, example configurations, experimental templates, numeric regression manifest, user/API/calibration documentation, ADRs, CI/Docker/release scripts and Codex handoff document.

### Known release-candidate limitations

- Streamlit/Pint/dev extras could not all be installed in the current restricted environment; browser-level UI and clean dependency installation remain to be completed externally.
- High-stiffness long-duration production H1 performance remains a documented engineering limitation.
- No sealed physical experiment dataset is included, so the software is `VERIFIED`, not experimentally `VALIDATED` or `PREDICTIVE`.

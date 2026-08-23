# Changelog

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

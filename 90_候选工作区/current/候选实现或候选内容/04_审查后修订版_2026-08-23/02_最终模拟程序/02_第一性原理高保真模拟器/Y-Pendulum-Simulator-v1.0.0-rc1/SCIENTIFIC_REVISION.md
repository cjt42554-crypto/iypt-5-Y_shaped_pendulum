# Scientific revision layer

The inherited simulator remains intact inside this copied project. The
corrective implementation is isolated under `src/ypendulum/scientific_revision/`
and does not modify the original repository-root simulator or theory trees.

The scientific identities are deliberately distinct:

- FWD is a unilateral tension-cable / point-bob forward model;
- revised HF is a discrete flexible-rod / finite-rigid-bob model;
- the unilateral HF limit is an ablation identity, not a production certificate;
- structural torus statements remain separate from experiment-facing predictions.

HF does not mean automatically closer to experiment. Changing compression,
branch EI, bob inertia/attachment, contact or external mechanisms changes the
model form and forbids inheritance of the original HF certificate.

Key modules:

- `numerics.py`: NumPy-1.26/current trapezoid compatibility without monkeypatching;
- `overlay.py`: per-branch EI, model identity and immutable raw/canonical sealing;
- `model_identity.py`: machine-derived evidence state transitions;
- `runner.py`: sealed config/overlay/common-state inputs and conservative reports;
- `common_state.py`: exact HF material-state bytes plus deterministic FWD mapping;
- `ablation.py`: executable M0–M5 chain with adjacent-change whitelists;
- `event_qualification.py`: pre-frozen matrix executor and separate diagnostics;
- `revised_desktop_worker.py`: GUI dispatch through the sealed overlay copy;
- `scientific_guard.py` and `structural_audit.py`: finite-window claim guards.

Every revised run reports these separately:

```text
model_claim_ceiling
requested_analysis_level
actual_evidence_level
evidence_bundle_sha256
downgrade_reasons
```

An overlay never grants evidence. Without a matching machine evidence bundle,
the actual level is `MODEL_CONSISTENT`. A short event matrix or M0–M5 smoke may
support code-path verification, but it is explicitly not
`NUMERICALLY_QUALIFIED`, `EXPERIMENTALLY_VALIDATED` or `PREDICTIVE`.

See `configs/revision/README.md` for reproducible commands and boundaries.

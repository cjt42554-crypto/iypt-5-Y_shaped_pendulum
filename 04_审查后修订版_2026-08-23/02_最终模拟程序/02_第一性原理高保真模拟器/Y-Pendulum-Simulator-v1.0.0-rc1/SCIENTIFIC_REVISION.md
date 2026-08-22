# Scientific revision layer

The inherited simulator remains intact inside this copied project. New code is under:

```text
src/ypendulum/scientific_revision/
```

The revision layer intentionally does not overwrite the original HF validation vocabulary. Runs that change compression, EI or the bob limit receive a new model identity and a separate result bundle.

Key modules:

- `overlay.py`: explicit per-branch EI and model identity;
- `revised_model.py`: injects the overlay into a freshly assembled HF model;
- `runner.py`: revised run output in the inherited HDF5 display layout, without inheriting the original certificate;
- `ablation.py`: M0--M5 model ladder;
- `event_qualification.py`: event-rich refinement matrix;
- `scientific_guard.py`: finite-window frequency and mechanism display guard;
- `revised_desktop.py`: overlay selector, corrected labels and conservative interpretation;
- `revised_desktop_adapter.py` / `revised_desktop_worker.py`: route GUI HF tasks through the explicit-EI runner and bind the overlay hash;
- `structural_audit.py`: finite-window structural evidence audit.

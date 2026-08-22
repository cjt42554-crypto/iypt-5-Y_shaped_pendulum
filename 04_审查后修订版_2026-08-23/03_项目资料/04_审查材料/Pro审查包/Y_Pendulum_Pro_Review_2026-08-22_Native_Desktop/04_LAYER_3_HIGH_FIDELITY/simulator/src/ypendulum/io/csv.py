"""CSV experiment and event I/O."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pandas as pd


def read_experiment_csv(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if "time" not in frame.columns:
        raise ValueError("Experiment CSV requires a time column.")
    spatial = {"x", "y", "z"}.issubset(frame.columns)
    pixels = {"u_pixel", "v_pixel"}.issubset(frame.columns)
    if not spatial and not pixels:
        raise ValueError("Experiment CSV needs either x,y,z or u_pixel,v_pixel columns.")
    return frame


def write_events(path: str | Path, events: list[dict[str, Any]]) -> None:
    target = Path(path)
    keys = sorted({key for event in events for key in event})
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        for event in events:
            writer.writerow(event)

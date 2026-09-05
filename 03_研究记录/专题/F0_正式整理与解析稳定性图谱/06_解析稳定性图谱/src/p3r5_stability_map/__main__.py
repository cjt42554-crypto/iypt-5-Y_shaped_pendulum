from __future__ import annotations

import argparse
import json
from pathlib import Path

from .map import build_stability_map

parser = argparse.ArgumentParser()
parser.add_argument("--config", type=Path, required=True)
parser.add_argument("--repository-root", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
arguments = parser.parse_args()
payload = build_stability_map(
    arguments.config.resolve(),
    arguments.repository_root.resolve(),
    arguments.output.resolve(),
)
print(
    json.dumps(
        {
            "schema": payload["schema"],
            "observed_mode_count": len(payload["observed_modes"]),
            "zero_crossing_status": payload["parameterization"]["zero_crossing_status"],
            "qualification_run": payload["qualification_run"],
        },
        indent=2,
        sort_keys=True,
    )
)

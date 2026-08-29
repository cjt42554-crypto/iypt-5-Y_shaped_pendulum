"""Command-line interface for the repository-bound formal atlas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .atlas import run_atlas
from .source_manifest import ContractViolation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--smoke", action="store_true")
    arguments = parser.parse_args()
    try:
        payload = run_atlas(
            arguments.config,
            arguments.output,
            repository_root=arguments.repository_root,
            smoke=arguments.smoke,
        )
    except (ContractViolation, FileNotFoundError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "schema": payload["schema"],
                "case_count": len(payload["cases"]),
                "aggregate_gates": payload["validation"]["aggregate_gates"],
                "claim_limit": payload["claim_limit"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )

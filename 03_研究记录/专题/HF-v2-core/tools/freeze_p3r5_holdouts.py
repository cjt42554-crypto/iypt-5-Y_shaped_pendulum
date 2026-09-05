#!/usr/bin/env python3
"""Freeze P3R5 holdout cards without opening an assembly or numerical solver."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ypendulum_hfv2_p3r5.domain import (  # noqa: E402
    build_holdout_freeze,
    observed_signature_set,
)
from ypendulum_hfv2_p3r5.evidence_support import (  # noqa: E402
    contract_binding,
    git_head,
    load_json,
    sha256,
)

OUTPUT = ROOT / "contracts/p3r5_holdout_cards.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--check", action="store_true")
    return parser.parse_args()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _repository_clean() -> bool:
    output = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return not output.strip()


def _remote_main() -> str:
    output = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", "refs/heads/main"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    fields = output.split()
    if len(fields) != 2:
        raise RuntimeError("P3R5 could not resolve exactly one remote main head.")
    return fields[0]


def _inputs() -> tuple[dict[str, object], dict[str, object], set[str]]:
    manifest = load_json(ROOT / "contracts/p3r5_acceptance_manifest.json")
    domain = load_json(ROOT / "contracts/p3r5_holdout_domain.json")
    p3r3 = load_json(ROOT / "contracts/p3r3_design_cards.json")
    p3r4 = load_json(ROOT / "contracts/p3r4_design_cards.json")
    return manifest, domain, observed_signature_set(p3r3, p3r4)


def _freeze() -> int:
    if OUTPUT.exists():
        raise RuntimeError("P3R5 holdout freeze already exists; refusing to regenerate.")
    if not _repository_clean():
        raise RuntimeError("P3R5 holdout freeze requires a clean committed tree.")
    manifest, domain, observed = _inputs()
    binding = contract_binding(ROOT, manifest, required_stage="implementation")
    if binding["status"] != "PASS":
        raise RuntimeError("P3R5 implementation binding is not a closed predecessor.")
    head = git_head(REPOSITORY_ROOT)
    if head != binding["implementation_commit"] or _remote_main() != head:
        raise RuntimeError("P3R5 implementation commit must be the exact remote main head.")
    result = build_holdout_freeze(
        domain,
        head,
        observed,
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        domain_sha256=sha256(ROOT / "contracts/p3r5_holdout_domain.json"),
    )
    _atomic_write(OUTPUT, _json_bytes(result))
    return 0


def _check() -> int:
    if not OUTPUT.exists():
        return 1
    manifest, domain, observed = _inputs()
    stored = load_json(OUTPUT)
    expected = build_holdout_freeze(
        domain,
        str(stored["implementation_commit"]),
        observed,
        generated_at=str(stored["generated_at"]),
        domain_sha256=sha256(ROOT / "contracts/p3r5_holdout_domain.json"),
    )
    zero = all(
        stored[key] == 0
        for key in (
            "input_assembly_run_count_before_holdout_freeze",
            "reference_construction_run_count_before_holdout_freeze",
            "target_admissibility_run_count_before_holdout_freeze",
            "second_order_run_count_before_holdout_freeze",
            "manifold_neighborhood_run_count_before_holdout_freeze",
            "target_freeze_run_count_before_holdout_freeze",
            "qualification_seed_run_count_before_holdout_freeze",
        )
    )
    return int(
        stored != expected
        or not zero
        or len(stored["holdout_cards"]) != 8
        or manifest["holdout_cards"] != OUTPUT.name
    )


def main() -> int:
    arguments = _arguments()
    return _freeze() if arguments.freeze else _check()


if __name__ == "__main__":
    raise SystemExit(main())

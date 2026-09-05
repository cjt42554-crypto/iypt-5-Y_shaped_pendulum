"""Regenerate the candidate atlas source/runtime lock after an authorized edit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from y_pendulum_pattern_atlas.source_manifest import (  # noqa: E402
    LOCK_RELATIVE_TO_PROJECT,
    build_source_lock,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    lock_path = PROJECT_ROOT / LOCK_RELATIVE_TO_PROJECT
    payload = build_source_lock(PROJECT_ROOT, REPOSITORY_ROOT)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if arguments.check:
        if not lock_path.is_file() or lock_path.read_text(encoding="utf-8") != serialized:
            print("source manifest lock is stale", file=sys.stderr)
            return 2
        print("source manifest lock is current")
        return 0
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(serialized, encoding="utf-8")
    print(lock_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

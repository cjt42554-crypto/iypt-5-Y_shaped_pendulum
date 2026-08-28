"""Generate and verify the per-file source binding for the migration draft."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SOURCE_ROOT = Path("90_候选工作区/current/HF-v2-core/src/ypendulum_hfv2")
TARGET_ROOT = Path(
    "90_候选工作区/current/F0_正式整理与解析稳定性图谱/"
    "03_无接触静态参考迁移稿/src/ypendulum_static_reference"
)
MIGRATED = (
    "topology.py",
    "state.py",
    "mass.py",
    "loads.py",
    "constitutive/__init__.py",
    "constitutive/axial.py",
    "constitutive/bending.py",
    "rigid/__init__.py",
    "rigid/attachment.py",
    "rigid/rotation.py",
    "statics/assembly.py",
    "statics/contracts.py",
    "statics/solver.py",
    "audit/energy_gradient.py",
    "audit/invariance.py",
    "audit/passivity.py",
    "audit/statics.py",
    "audit/g2_cases.py",
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def build(repository_root: Path) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for relative in MIGRATED:
        source = repository_root / SOURCE_ROOT / relative
        target = repository_root / TARGET_ROOT / relative
        source_bytes = source.read_bytes()
        target_bytes = target.read_bytes()
        expected = source_bytes.replace(b"ypendulum_hfv2", b"ypendulum_static_reference")
        transform_verified = (
            target_bytes.rstrip(b"\n") == expected.rstrip(b"\n")
            and target_bytes.endswith(b"\n")
        )
        rows.append(
            {
                "source": source.relative_to(repository_root).as_posix(),
                "target": target.relative_to(repository_root).as_posix(),
                "source_sha256": _sha256(source_bytes),
                "target_sha256": _sha256(target_bytes),
                "transform": "package_namespace_replace_and_terminal_newline_normalization",
                "transform_verified": transform_verified,
            }
        )
    if not all(bool(row["transform_verified"]) for row in rows):
        failures = [row["target"] for row in rows if not row["transform_verified"]]
        raise RuntimeError(f"Migration transform mismatch: {failures}")
    return {
        "schema": "YPS-NO-CONTACT-STATIC-MIGRATION-PROVENANCE-1.0",
        "model_id": ("YPS-DISCRETE-ROD-RIGID-BOB-NO-CONTACT-STATIC-REFERENCE-DRAFT-1.0"),
        "formal_promotion_status": "NOT_PROMOTED_CANDIDATE_DRAFT",
        "source_namespace": "ypendulum_hfv2",
        "target_namespace": "ypendulum_static_reference",
        "migrated_files": rows,
        "excluded_source_prefixes": [
            "contact/",
            "statics/contact_assembly.py",
            "statics/contact_solver.py",
            "ypendulum_hfv2_p3r*",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    payload = build(arguments.repository_root.resolve())
    arguments.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

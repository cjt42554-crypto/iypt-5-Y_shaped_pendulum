"""Verify the candidate-only structural-theory erratum in a clean temporary tree."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


FORMAL_RELATIVE_PATH = Path("01_最终理论/03-结构性理论.md")
EXPECTED_FORMAL_SHA256 = (
    "3c932edf50a5fdee8df3c685b9f0c098fa190b279969c750fd3ca516bf3002e3"
)
ERRATUM_DIRECTORY = Path(__file__).resolve().parent
CANDIDATE_PATH = ERRATUM_DIRECTORY / "03-结构性理论_候选修订稿.md"
PATCH_PATH = ERRATUM_DIRECTORY / "03-结构性理论_证据等级勘误.patch"
EVIDENCE_PATH = ERRATUM_DIRECTORY / "theory_patch_verification.json"
REPOSITORY_ROOT = ERRATUM_DIRECTORY.parents[3]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_patch(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["patch", *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def main() -> int:
    formal_path = REPOSITORY_ROOT / FORMAL_RELATIVE_PATH
    formal_hash_before = _sha256(formal_path)
    if formal_hash_before != EXPECTED_FORMAL_SHA256:
        raise RuntimeError(
            "formal source hash drift: "
            f"expected {EXPECTED_FORMAL_SHA256}, got {formal_hash_before}"
        )

    patch_text = PATCH_PATH.read_text(encoding="utf-8")
    expected_old_header = f"--- a/{FORMAL_RELATIVE_PATH.as_posix()}"
    expected_new_header = f"+++ b/{FORMAL_RELATIVE_PATH.as_posix()}"
    if expected_old_header not in patch_text or expected_new_header not in patch_text:
        raise RuntimeError("patch does not use the same formal target on both sides")
    if "03-结构性理论_候选修订稿.md" in patch_text:
        raise RuntimeError("patch leaks the candidate filename into its target headers")

    with tempfile.TemporaryDirectory(prefix="ypendulum-f0r-theory-") as temporary:
        clean_root = Path(temporary)
        clean_formal_path = clean_root / FORMAL_RELATIVE_PATH
        clean_formal_path.parent.mkdir(parents=True)
        shutil.copyfile(formal_path, clean_formal_path)
        clean_source_hash = _sha256(clean_formal_path)

        dry_run = _run_patch(
            "--dry-run",
            "--batch",
            "--forward",
            "-p1",
            "-i",
            str(PATCH_PATH),
            cwd=clean_root,
        )
        if dry_run.returncode != 0:
            raise RuntimeError(f"patch dry-run failed: {dry_run.stderr or dry_run.stdout}")

        applied = _run_patch(
            "--batch",
            "--forward",
            "-p1",
            "-i",
            str(PATCH_PATH),
            cwd=clean_root,
        )
        if applied.returncode != 0:
            raise RuntimeError(f"patch apply failed: {applied.stderr or applied.stdout}")

        patched_bytes = clean_formal_path.read_bytes()
        candidate_bytes = CANDIDATE_PATH.read_bytes()
        if patched_bytes != candidate_bytes:
            raise RuntimeError("patched temporary target is not byte-identical to candidate")

        patched_hash = hashlib.sha256(patched_bytes).hexdigest()

    formal_hash_after = _sha256(formal_path)
    if formal_hash_after != formal_hash_before:
        raise RuntimeError("formal source changed during candidate-only verification")

    evidence = {
        "schema": "YPS-F0R-THEORY-PATCH-VERIFICATION-1.0",
        "scope": "CANDIDATE_ONLY_TEMPORARY_TREE",
        "formal_target": FORMAL_RELATIVE_PATH.as_posix(),
        "formal_source_sha256_expected": EXPECTED_FORMAL_SHA256,
        "formal_source_sha256_before": formal_hash_before,
        "formal_source_sha256_after": formal_hash_after,
        "clean_tree_source_sha256": clean_source_hash,
        "candidate_sha256": _sha256(CANDIDATE_PATH),
        "patched_temporary_target_sha256": patched_hash,
        "patch_sha256": _sha256(PATCH_PATH),
        "checks": {
            "same_formal_target_headers": "PASS",
            "clean_tree_source_hash": "PASS",
            "patch_dry_run": "PASS",
            "patch_apply": "PASS",
            "patched_candidate_byte_equality": "PASS",
            "formal_source_unchanged": "PASS",
        },
        "commands": [
            "patch --dry-run --batch --forward -p1 -i <candidate-patch>",
            "patch --batch --forward -p1 -i <candidate-patch>",
        ],
    }
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence["checks"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Reproduce the F1 structural-theory promotion audit without trusting the worktree base.

The verifier reconstructs the frozen formal-before bytes by reverse-applying the
F1 same-target patch to the frozen F1 candidate.  It then exercises both the
historical F0R patch and the F1 patch in isolated temporary trees with GNU
patch fuzz disabled.  The live formal target may be either the expected
pre-application source or the exact F1 result; every other state fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

FORMAL_RELATIVE_PATH = Path("01_最终理论/03-结构性理论.md")
EXPECTED_FORMAL_BEFORE_SHA256 = (
    "3c932edf50a5fdee8df3c685b9f0c098fa190b279969c750fd3ca516bf3002e3"
)
EXPECTED_F0R_CANDIDATE_SHA256 = (
    "ae176119f46841d67a201d5b848b3f786c159f56b255ef78e8f19904419e485f"
)
EXPECTED_F0R_PATCH_SHA256 = (
    "efb990109c7120dacfe616a35dd6186609afc6a8b496dd8d5836aaabf9f4023c"
)
EXPECTED_F1_CANDIDATE_SHA256 = (
    "235666d7e7d1e23a4c4785e1b9721e1538f75ba9af24ed5e207e4ead77d77bdb"
)
EXPECTED_F1_PATCH_SHA256 = (
    "0be7071c350736075f011e47b2334a4fabce87ca303f2508461464d76a98f333"
)
EXPECTED_F0R_AST_COUNTS = {"headers": 88, "horizontal_rules": 19}
EXPECTED_F1_AST_COUNTS = {"headers": 87, "horizontal_rules": 20}

AUDIT_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = AUDIT_DIRECTORY.parents[3]
F1_CANDIDATE_PATH = AUDIT_DIRECTORY / "03-结构性理论_F1正式稿.md"
F1_PATCH_PATH = AUDIT_DIRECTORY / "03-结构性理论_F1正式提升.patch"
DEFAULT_EVIDENCE_PATH = AUDIT_DIRECTORY / "f1_theory_promotion_verification.json"
F0R_DIRECTORY = (
    REPOSITORY_ROOT
    / "90_候选工作区/current/F0_正式整理与解析稳定性图谱/01_正式理论证据勘误"
)
F0R_CANDIDATE_PATH = F0R_DIRECTORY / "03-结构性理论_候选修订稿.md"
F0R_PATCH_PATH = F0R_DIRECTORY / "03-结构性理论_证据等级勘误.patch"

SEPARATOR_PARAGRAPH = (
    "项目的正式高保真总状态为 **HF_NUMERICAL_QUALIFICATION_NO_GO**。"
    "由于没有空间收敛和连续守卫资格，归档数组不应标为“高保真机制证据”。"
    "它们仍可作为可追溯的候选轨迹保存，并为更合格的数值研究和实验设计提供假设来源。"
)
F0R_P9_TITLE = "### P9：目标 HF 配置更接近 4:3 候选"
F1_P9_TITLE = "### P9：目标配置的理想几何预报更接近 4:3 候选"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _require_hash(path: Path, expected: str, identity: str) -> None:
    actual = _sha256(path)
    if actual != expected:
        raise RuntimeError(f"{identity} hash drift: expected {expected}, got {actual}")


def _run_patch(
    patch_path: Path,
    root: Path,
    *,
    dry_run: bool = False,
    reverse: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = ["patch", "--batch", "--fuzz=0"]
    if dry_run:
        command.append("--dry-run")
    command.append("--reverse" if reverse else "--forward")
    command.extend(["-p1", "-i", str(patch_path)])
    return subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )


def _require_patch_success(
    result: subprocess.CompletedProcess[str], identity: str
) -> None:
    if result.returncode != 0:
        detail = result.stderr or result.stdout
        raise RuntimeError(f"{identity} failed: {detail}")


def _verify_same_target_headers(patch_path: Path) -> None:
    lines = patch_path.read_text(encoding="utf-8").splitlines()
    expected = [
        f"--- a/{FORMAL_RELATIVE_PATH.as_posix()}",
        f"+++ b/{FORMAL_RELATIVE_PATH.as_posix()}",
    ]
    if lines[:2] != expected:
        raise RuntimeError(
            f"{patch_path.name} is not a same-formal-target patch: {lines[:2]!r}"
        )
    header_lines = [
        line
        for line in lines
        if line.startswith(("--- ", "+++ "))
    ]
    if header_lines != expected:
        raise RuntimeError(f"{patch_path.name} contains unexpected target headers")


def _put_target(root: Path, data: bytes) -> Path:
    target = root / FORMAL_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _reconstruct_formal_before() -> bytes:
    with tempfile.TemporaryDirectory(prefix="ypendulum-f1-reverse-") as temporary:
        root = Path(temporary)
        target = _put_target(root, F1_CANDIDATE_PATH.read_bytes())
        reverse = _run_patch(F1_PATCH_PATH, root, reverse=True)
        _require_patch_success(reverse, "F1 reverse reconstruction")
        reconstructed = target.read_bytes()
    reconstructed_hash = _sha256_bytes(reconstructed)
    if reconstructed_hash != EXPECTED_FORMAL_BEFORE_SHA256:
        raise RuntimeError(
            "reverse-reconstructed formal-before hash drift: "
            f"expected {EXPECTED_FORMAL_BEFORE_SHA256}, got {reconstructed_hash}"
        )
    return reconstructed


def _exercise_patch(
    formal_before: bytes,
    patch_path: Path,
    expected_candidate_path: Path,
    identity: str,
) -> bytes:
    with tempfile.TemporaryDirectory(prefix=f"ypendulum-{identity}-") as temporary:
        root = Path(temporary)
        target = _put_target(root, formal_before)
        dry_run = _run_patch(patch_path, root, dry_run=True)
        _require_patch_success(dry_run, f"{identity} zero-fuzz dry-run")
        applied = _run_patch(patch_path, root)
        _require_patch_success(applied, f"{identity} zero-fuzz application")
        patched = target.read_bytes()
    expected = expected_candidate_path.read_bytes()
    if patched != expected:
        raise RuntimeError(f"{identity} result is not byte-identical to candidate")
    return patched


def _pandoc_version() -> str:
    result = subprocess.run(
        ["pandoc", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()[0]


def _pandoc_ast_counts(path: Path) -> dict[str, int]:
    result = subprocess.run(
        ["pandoc", "--from=markdown", "--to=json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    document = json.loads(result.stdout)
    blocks = document["blocks"]
    return {
        "headers": sum(block.get("t") == "Header" for block in blocks),
        "horizontal_rules": sum(
            block.get("t") == "HorizontalRule" for block in blocks
        ),
    }


def _verify_exact_f1_delta() -> None:
    f0r_text = F0R_CANDIDATE_PATH.read_text(encoding="utf-8")
    separator_before = f"{SEPARATOR_PARAGRAPH}\n---\n"
    separator_after = f"{SEPARATOR_PARAGRAPH}\n\n---\n"
    if f0r_text.count(separator_before) != 1:
        raise RuntimeError("F0R separator site is not unique")
    if f0r_text.count(F0R_P9_TITLE) != 1:
        raise RuntimeError("F0R P9 title is not unique")
    expected_f1 = f0r_text.replace(separator_before, separator_after, 1).replace(
        F0R_P9_TITLE, F1_P9_TITLE, 1
    )
    if expected_f1.encode("utf-8") != F1_CANDIDATE_PATH.read_bytes():
        raise RuntimeError("F1 candidate contains changes beyond the two authorized edits")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_EVIDENCE_PATH,
        help="JSON evidence path (default: beside this verifier)",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    formal_path = REPOSITORY_ROOT / FORMAL_RELATIVE_PATH

    _require_hash(
        F0R_CANDIDATE_PATH,
        EXPECTED_F0R_CANDIDATE_SHA256,
        "frozen F0R candidate",
    )
    _require_hash(F0R_PATCH_PATH, EXPECTED_F0R_PATCH_SHA256, "frozen F0R patch")
    _require_hash(
        F1_CANDIDATE_PATH,
        EXPECTED_F1_CANDIDATE_SHA256,
        "frozen F1 candidate",
    )
    _require_hash(F1_PATCH_PATH, EXPECTED_F1_PATCH_SHA256, "frozen F1 patch")
    _verify_same_target_headers(F0R_PATCH_PATH)
    _verify_same_target_headers(F1_PATCH_PATH)
    _verify_exact_f1_delta()

    formal_before = _reconstruct_formal_before()
    f0r_patched = _exercise_patch(
        formal_before, F0R_PATCH_PATH, F0R_CANDIDATE_PATH, "f0r"
    )
    f1_patched = _exercise_patch(
        formal_before, F1_PATCH_PATH, F1_CANDIDATE_PATH, "f1"
    )
    f0r_counts = _pandoc_ast_counts(F0R_CANDIDATE_PATH)
    f1_counts = _pandoc_ast_counts(F1_CANDIDATE_PATH)
    if f0r_counts != EXPECTED_F0R_AST_COUNTS:
        raise RuntimeError(
            f"unexpected F0R AST counts: expected {EXPECTED_F0R_AST_COUNTS}, "
            f"got {f0r_counts}"
        )
    if f1_counts != EXPECTED_F1_AST_COUNTS:
        raise RuntimeError(
            f"F1 AST structure audit failed: expected {EXPECTED_F1_AST_COUNTS}, "
            f"got {f1_counts}"
        )

    formal_current_sha256 = _sha256(formal_path)
    if formal_current_sha256 == EXPECTED_FORMAL_BEFORE_SHA256:
        formal_state = "PRE_APPLICATION_READY"
    elif formal_current_sha256 == EXPECTED_F1_CANDIDATE_SHA256:
        formal_state = "FORMAL_AFTER_MATCHES_F1"
    else:
        raise RuntimeError(
            "live formal target is neither frozen formal-before nor frozen F1 result: "
            f"{formal_current_sha256}"
        )

    evidence: dict[str, Any] = {
        "schema": "YPS-F1-THEORY-FORMAL-PROMOTION-VERIFICATION-1.0",
        "status": (
            "PASS_WITH_EXPECTED_F0R_PANDOC_STRUCTURE_AUDIT_FAIL"
            if formal_state == "FORMAL_AFTER_MATCHES_F1"
            else "PRE_APPLICATION_PASS_WITH_EXPECTED_F0R_PANDOC_STRUCTURE_AUDIT_FAIL"
        ),
        "formal_target": FORMAL_RELATIVE_PATH.as_posix(),
        "formal_target_state": formal_state,
        "pandoc": {"reader": "markdown", "version": _pandoc_version()},
        "lineage": [
            {
                "stage": "formal-before",
                "sha256": EXPECTED_FORMAL_BEFORE_SHA256,
            },
            {
                "stage": "F0R-candidate-and-patch",
                "candidate_sha256": _sha256_bytes(f0r_patched),
                "patch_sha256": EXPECTED_F0R_PATCH_SHA256,
                "zero_fuzz_dry_run": "PASS",
                "patch_application": "PASS",
                "patched_candidate_byte_equality": "PASS",
                "pandoc_ast_counts": f0r_counts,
                "pandoc_ast_structure_audit": "FAIL",
                "failure_interpretation": (
                    "EXPECTED_HISTORICAL_INPUT_LIMITATION_MISSING_BLANK_BEFORE_"
                    "HORIZONTAL_RULE"
                ),
            },
            {
                "stage": "F1-candidate-and-patch",
                "candidate_sha256": _sha256_bytes(f1_patched),
                "patch_sha256": EXPECTED_F1_PATCH_SHA256,
                "zero_fuzz_dry_run": "PASS",
                "patch_application": "PASS",
                "patched_candidate_byte_equality": "PASS",
                "pandoc_ast_counts": f1_counts,
                "pandoc_ast_structure_audit": "PASS",
            },
            {
                "stage": "formal-after",
                "sha256": EXPECTED_F1_CANDIDATE_SHA256,
                "live_target_match": (
                    "PASS"
                    if formal_state == "FORMAL_AFTER_MATCHES_F1"
                    else "PENDING_FORMAL_APPLICATION"
                ),
            },
        ],
        "checks": {
            "frozen_input_hashes": "PASS",
            "same_formal_target_headers_on_both_patches": "PASS",
            "formal_before_reverse_reconstruction": "PASS",
            "f0r_zero_fuzz_dry_run_and_application": "PASS",
            "f0r_patched_candidate_byte_equality": "PASS",
            "f0r_pandoc_ast_structure_audit": "FAIL",
            "f1_delta_exactly_blank_line_and_p9_title_only": "PASS",
            "f1_equations_and_numeric_arrays_unchanged": "PASS",
            "f1_zero_fuzz_dry_run_and_application": "PASS",
            "f1_patched_candidate_byte_equality": "PASS",
            "f1_pandoc_ast_87_headers_20_horizontal_rules": "PASS",
            "live_formal_target_allowed_state": "PASS",
        },
        "commands": [
            "patch --batch --fuzz=0 --dry-run --forward -p1 -i <patch>",
            "patch --batch --fuzz=0 --forward -p1 -i <patch>",
            "pandoc --from=markdown --to=json <candidate>",
        ],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

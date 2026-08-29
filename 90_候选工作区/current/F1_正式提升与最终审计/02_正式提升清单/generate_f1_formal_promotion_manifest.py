#!/usr/bin/env python3
"""Generate the F1 formal-promotion audit manifest without writing formal trees.

The allowlist is derived from the immutable F0R map, narrowed to the explicitly
authorized T/A/S/R scope and the F1-specific exclusions.  The script reads the
working tree and the frozen pre-promotion commit, then writes only the sibling
candidate audit JSON file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

BASELINE_HEAD = "3ea4892ab56b47d9aa6d61bc717bc242717c76be"
F0R_MAP = PurePosixPath(
    "90_候选工作区/current/F0_正式整理与解析稳定性图谱/"
    "05_正式提升清单/formal_promotion_file_map.json"
)
F0R_MAP_SHA256 = "c49cd03ef809bf66691ba787477eb63574abd605561fb2db72bda506a1fe8ddf"
F1_THEORY_CANDIDATE = PurePosixPath(
    "90_候选工作区/current/F1_正式提升与最终审计/"
    "01_结构性理论/03-结构性理论_F1正式稿.md"
)
OUTPUT = PurePosixPath(
    "90_候选工作区/current/F1_正式提升与最终审计/"
    "02_正式提升清单/f1_formal_promotion_manifest.json"
)

THEORY_TARGET = "01_最终理论/03-结构性理论.md"
ATLAS_ROOT = "02_模拟程序/03_结构性理论分析程序/pattern_atlas"
STATIC_ROOT = "02_模拟程序/04_离散杆刚体无接触静态参考模型"
STATUS_TARGET = (
    "02_模拟程序/02_第一性原理高保真模拟器/"
    "Y-Pendulum-Simulator-v1.0.0-rc1/STATUS.md"
)

STATIC_EXCLUDED_TARGETS = {
    f"{STATIC_ROOT}/outputs/canonical_static_run_evidence.json",
    f"{STATIC_ROOT}/runtime_matrix.json",
    f"{STATIC_ROOT}/migration_provenance.json",
}
STATIC_MIGRATION_GENERATOR = (
    "90_候选工作区/current/F0_正式整理与解析稳定性图谱/"
    "03_无接触静态参考迁移稿/tools/generate_migration_provenance.py"
)

BATCH_REASONS = {
    "T": (
        "Apply the F1 same-target evidence-taxonomy correction; equations and "
        "numerical values are not promoted as new results."
    ),
    "A": (
        "Publish the repository-bound ideal-torus pattern-atlas implementation "
        "while excluding generated outputs."
    ),
    "S": (
        "Publish the static-only, no-contact reference implementation and its "
        "supported runtime probe without carrying historical qualification."
    ),
    "R": (
        "Add a status notice to the frozen RC1 reference without changing RC1 "
        "physics or numerical artifacts."
    ),
}

IGNORED_WORKTREE_PARTS = {
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
}


class ManifestError(RuntimeError):
    """Raised when the F1 manifest cannot be generated fail-closed."""


def find_repo_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / ".git").exists() and (path / "AGENTS.md").is_file():
            return path
    raise ManifestError("repository root containing .git and AGENTS.md was not found")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_file(root: Path, relative: str | PurePosixPath) -> bytes:
    path = root / Path(relative)
    if not path.is_file():
        raise ManifestError(f"required file is absent: {relative}")
    return path.read_bytes()


def git_bytes(root: Path, commit: str, relative: str) -> bytes | None:
    spec = f"{commit}:{relative}"
    probe = subprocess.run(
        ["git", "cat-file", "-e", spec],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if probe.returncode != 0:
        return None
    result = subprocess.run(
        ["git", "show", spec],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ManifestError(
            f"git show failed for {spec}: {result.stderr.decode(errors='replace')}"
        )
    return result.stdout


def batch_for_target(target: str) -> str:
    if target == THEORY_TARGET:
        return "T"
    if target.startswith(f"{ATLAS_ROOT}/"):
        return "A"
    if target.startswith(f"{STATIC_ROOT}/"):
        return "S"
    if target == STATUS_TARGET:
        return "R"
    raise ManifestError(f"target is outside the T/A/S/R authorization: {target}")


def is_ignored_residue(relative: Path) -> bool:
    if any(part in IGNORED_WORKTREE_PARTS for part in relative.parts):
        return True
    if relative.suffix in {".pyc", ".pyo"}:
        return True
    if any(part.endswith(".egg-info") for part in relative.parts):
        return True
    return relative.name in {".coverage"}


def audit_release_roots(root: Path, selected_targets: set[str]) -> None:
    actual: set[str] = set()
    for release_root in (ATLAS_ROOT, STATIC_ROOT):
        base = root / release_root
        if not base.is_dir():
            raise ManifestError(f"formal release root is absent: {release_root}")
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            relative_to_release = path.relative_to(base)
            if is_ignored_residue(relative_to_release):
                continue
            actual.add(path.relative_to(root).as_posix())
    expected = {
        target
        for target in selected_targets
        if target.startswith((f"{ATLAS_ROOT}/", f"{STATIC_ROOT}/"))
    }
    if actual != expected:
        unexpected = sorted(actual - expected)
        missing = sorted(expected - actual)
        raise ManifestError(
            "formal release-root closure failed; "
            f"unexpected={unexpected}, missing={missing}"
        )


def select_entries(f0r: dict[str, Any]) -> list[dict[str, Any]]:
    if f0r.get("formal_write_authorized") is not False:
        raise ManifestError("F0R map no longer has its historical unauthorized state")
    if f0r.get("formal_directories_modified") is not False:
        raise ManifestError("F0R map no longer records untouched formal directories")

    selected: list[dict[str, Any]] = []
    for old in f0r.get("entries", []):
        target = old.get("formal_target")
        if not target or target in STATIC_EXCLUDED_TARGETS:
            continue
        try:
            batch_for_target(target)
        except ManifestError:
            continue
        selected.append(old)

    counts = Counter(batch_for_target(entry["formal_target"]) for entry in selected)
    expected = Counter({"T": 1, "A": 17, "S": 41, "R": 1})
    if counts != expected or len(selected) != 60:
        raise ManifestError(
            f"allowlist cardinality drift: got {dict(counts)} / {len(selected)}, "
            f"expected {dict(expected)} / 60"
        )
    targets = [entry["formal_target"] for entry in selected]
    if len(targets) != len(set(targets)):
        raise ManifestError("F0R map contains duplicate selected formal targets")
    return selected


def source_for_entry(old: dict[str, Any], batch: str) -> str:
    if batch == "T":
        return F1_THEORY_CANDIDATE.as_posix()
    return str(old["candidate"])


def transfer_mode(batch: str, candidate_hash: str, post_hash: str) -> str:
    if batch == "T":
        if candidate_hash != post_hash:
            raise ManifestError(
                "formal theory does not byte-match the verified F1 same-target patch result"
            )
        return "SAME_TARGET_PATCH_RESULT_BYTE_MATCHES_F1_CANDIDATE"
    if candidate_hash == post_hash:
        return "BYTE_IDENTICAL_COPY_FROM_F0R_CANDIDATE"
    return "FORMAL_RELEASE_TRANSFORMATION_FROM_F0R_CANDIDATE"


def make_entry(root: Path, old: dict[str, Any]) -> dict[str, Any]:
    target = str(old["formal_target"])
    batch = batch_for_target(target)
    candidate = source_for_entry(old, batch)
    candidate_data = read_file(root, candidate)
    historical_candidate_data = read_file(root, str(old["candidate"]))
    historical_candidate_hash = sha256_bytes(historical_candidate_data)
    if historical_candidate_hash != old["candidate_sha256"]:
        raise ManifestError(
            "historical F0R candidate drift: "
            f"{old['candidate']} expected {old['candidate_sha256']}, "
            f"got {historical_candidate_hash}"
        )
    if len(historical_candidate_data) != old["bytes"]:
        raise ManifestError(
            "historical F0R candidate byte-count drift: "
            f"{old['candidate']} expected {old['bytes']}, "
            f"got {len(historical_candidate_data)}"
        )
    pre_data = git_bytes(root, BASELINE_HEAD, target)
    post_data = read_file(root, target)
    candidate_hash = sha256_bytes(candidate_data)
    post_hash = sha256_bytes(post_data)
    mode = transfer_mode(batch, candidate_hash, post_hash)
    operation = "MODIFY" if pre_data is not None else "ADD"
    expected_pre_hash = old.get("formal_target_current_sha256")
    actual_pre_hash = sha256_bytes(pre_data) if pre_data is not None else None
    if actual_pre_hash != expected_pre_hash:
        raise ManifestError(
            f"formal prestate drift for {target}: F0R recorded "
            f"{expected_pre_hash}, frozen baseline has {actual_pre_hash}"
        )

    return {
        "batch": batch,
        "formal_target": target,
        "operation": operation,
        "source_candidate": candidate,
        "source_candidate_sha256": candidate_hash,
        "source_candidate_bytes": len(candidate_data),
        "lineage": {
            "historical_f0r_candidate": old["candidate"],
            "historical_f0r_candidate_sha256": historical_candidate_hash,
            "historical_f0r_candidate_bytes": len(historical_candidate_data),
            "historical_f0r_decision": old["decision"],
            "historical_f0r_formal_write_authorized": old[
                "formal_write_authorized"
            ],
        },
        "formal_target_pre_exists": pre_data is not None,
        "formal_target_pre_sha256": (
            actual_pre_hash
        ),
        "formal_target_pre_bytes": len(pre_data) if pre_data is not None else None,
        "formal_target_post_sha256": post_hash,
        "formal_target_post_bytes": len(post_data),
        "transfer_mode": mode,
        "byte_identity_verified": candidate_hash == post_hash,
        "reason": BATCH_REASONS[batch],
    }


def exclusion_records(f0r: dict[str, Any]) -> list[dict[str, Any]]:
    atlas_prefix = (
        "90_候选工作区/current/F0_正式整理与解析稳定性图谱/"
        "02_参数图谱正式化迁移稿/outputs/"
    )
    records: list[dict[str, Any]] = []
    for old in f0r["entries"]:
        candidate = str(old["candidate"])
        target = old.get("formal_target")
        if candidate.startswith(atlas_prefix):
            records.append(
                {
                    "item": candidate,
                    "kind": "A_GENERATED_OUTPUT",
                    "decision": "KEEP_CANDIDATE_ONLY",
                    "reason": "Generated atlas outputs are reproducibility evidence, not formal source.",
                }
            )
        elif target in STATIC_EXCLUDED_TARGETS:
            records.append(
                {
                    "item": target,
                    "source_candidate": candidate,
                    "kind": "S_GENERATED_OR_REVIEW_EVIDENCE",
                    "decision": "KEEP_CANDIDATE_ONLY",
                    "reason": "Runtime/migration evidence must be regenerated in the F1 audit area.",
                }
            )
        elif candidate == STATIC_MIGRATION_GENERATOR:
            records.append(
                {
                    "item": candidate,
                    "kind": "S_CANDIDATE_MIGRATION_GENERATOR",
                    "decision": "KEEP_CANDIDATE_ONLY",
                    "reason": "One-time candidate migration tooling is not a supported formal tool.",
                }
            )

    records.extend(
        [
            {
                "item": (
                    "90_候选工作区/current/F0_正式整理与解析稳定性图谱/"
                    "06_解析稳定性图谱/**"
                ),
                "kind": "M_INTERPOLATION_ARTIFACTS",
                "decision": "KEEP_CANDIDATE_ONLY",
                "reason": "Path F did not authorize promotion of the four-point descriptive map.",
            },
            {
                "item": (
                    "90_候选工作区/current/F0_正式整理与解析稳定性图谱/"
                    "07_实验门最小测量清单/**"
                ),
                "kind": "E_EXPERIMENT_GATE_MATERIAL",
                "decision": "KEEP_CANDIDATE_ONLY",
                "reason": "Experiment-gate material is outside the T/A/S/R formal allowlist.",
            },
            {
                "item": (
                    "90_候选工作区/current/F0_正式整理与解析稳定性图谱/"
                    "{05_正式提升清单/**,F0_COMPLETION_REPORT.md,README.md,f0_machine_status.json}"
                ),
                "kind": "F0R_GOVERNANCE_AND_REVIEW_EVIDENCE",
                "decision": "KEEP_HISTORICAL_CANDIDATE_SNAPSHOT",
                "reason": "F0R governance remains an immutable historical unauthorized snapshot.",
            },
            {
                "item": "P3-P3R5 contact packages and frozen evidence",
                "kind": "CONTACT_QUALIFICATION_SCOPE",
                "decision": "EXCLUDED_UNCHANGED",
                "reason": "Path F is formal consolidation, not a contact-qualification retry.",
            },
        ]
    )
    return sorted(records, key=lambda record: (record["kind"], record["item"]))


def build_manifest(root: Path) -> dict[str, Any]:
    baseline_probe = subprocess.run(
        ["git", "cat-file", "-e", f"{BASELINE_HEAD}^{{commit}}"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if baseline_probe.returncode != 0:
        raise ManifestError(f"frozen baseline commit is unavailable: {BASELINE_HEAD}")

    f0r_bytes = read_file(root, F0R_MAP)
    f0r_hash = sha256_bytes(f0r_bytes)
    if f0r_hash != F0R_MAP_SHA256:
        raise ManifestError(
            f"historical F0R map drift: expected {F0R_MAP_SHA256}, got {f0r_hash}"
        )
    f0r = json.loads(f0r_bytes)
    selected = select_entries(f0r)
    selected_targets = {str(entry["formal_target"]) for entry in selected}
    audit_release_roots(root, selected_targets)
    entries = [make_entry(root, old) for old in selected]
    entries.sort(key=lambda entry: (entry["batch"], entry["formal_target"]))

    counts = Counter(entry["batch"] for entry in entries)
    transfer_counts = Counter(entry["transfer_mode"] for entry in entries)
    return {
        "schema": "YPS-F1-FORMAL-PROMOTION-MANIFEST-1.0",
        "phase": "F1_EXPLICIT_FORMAL_PROMOTION_AND_FINAL_AUDIT_PREPARATION",
        "baseline_head": BASELINE_HEAD,
        "authorization": {
            "user_statement": "我明确选择并批准路径F，去工作吧。",
            "interpretation": (
                "The explicit approval of full path F authorizes all four named "
                "formal batches T, A, S, and R, and no other formal scope."
            ),
            "authorized_batches": ["T", "A", "S", "R"],
            "authorized_targets": {
                "T": THEORY_TARGET,
                "A": f"{ATLAS_ROOT}/** (17-file source allowlist; outputs excluded)",
                "S": (
                    f"{STATIC_ROOT}/** (41-file source allowlist; supported "
                    "runtime_probe retained; generated/review evidence excluded)"
                ),
                "R": STATUS_TARGET,
            },
            "formal_write_authorized": True,
        },
        "historical_f0r_map": {
            "path": F0R_MAP.as_posix(),
            "sha256": f0r_hash,
            "phase": f0r["phase"],
            "entry_count": len(f0r["entries"]),
            "formal_write_authorized": False,
            "formal_directories_modified": False,
            "required_review_before_any_formal_write": f0r[
                "required_review_before_any_formal_write"
            ],
            "interpretation": (
                "Immutable historical unauthorized snapshot; it supplies lineage "
                "but is not rewritten into an authorization record."
            ),
        },
        "allowlist": {
            "entry_count": len(entries),
            "batch_counts": {key: counts[key] for key in ("T", "A", "S", "R")},
            "expected_batch_counts": {"T": 1, "A": 17, "S": 41, "R": 1},
            "closure_pass": counts == Counter({"T": 1, "A": 17, "S": 41, "R": 1}),
        },
        "entries": entries,
        "transfer_mode_counts": dict(sorted(transfer_counts.items())),
        "explicit_exclusions": exclusion_records(f0r),
        "formal_directory_write_policy": (
            "This generator is audit-only: it reads formal files and the frozen "
            "baseline but writes only the candidate manifest beside itself."
        ),
        "total_status": "HF_NUMERICAL_QUALIFICATION_NO_GO",
        "conclusion_ceiling": (
            "Formal source/release consolidation with implementation and bounded "
            "runtime evidence only; no high-fidelity numerical, physical, apparatus, "
            "or experimental qualification is conferred."
        ),
        "stop_gate": "F1_FINAL_PRO_REVIEW",
    }


def canonical_json(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the generated bytes with the existing candidate manifest",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = find_repo_root(Path(__file__).resolve().parent)
    manifest = build_manifest(root)
    rendered = canonical_json(manifest)
    destination = root / Path(OUTPUT)

    if args.check:
        if not destination.is_file():
            raise ManifestError(f"candidate manifest is absent: {OUTPUT}")
        current = destination.read_bytes()
        if current != rendered:
            raise ManifestError(
                "candidate manifest is stale; rerun without --check after F1 files freeze"
            )
        print(
            f"PASS: {OUTPUT} is current; entries={len(manifest['entries'])}; "
            f"sha256={sha256_bytes(rendered)}"
        )
        return 0

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_bytes(rendered)
    temporary.replace(destination)
    print(
        f"WROTE: {OUTPUT}; entries={len(manifest['entries'])}; "
        f"sha256={sha256_bytes(rendered)}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ManifestError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)

"""Generate the F0 per-file formal-promotion candidate map."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

F0 = Path("90_候选工作区/current/F0_正式整理与解析稳定性图谱")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row(
    repository_root: Path,
    candidate: Path,
    *,
    decision: str,
    formal_target: Path | None,
    rationale: str,
) -> dict[str, object]:
    target_path = repository_root / formal_target if formal_target is not None else None
    return {
        "candidate": candidate.relative_to(repository_root).as_posix(),
        "candidate_sha256": _sha256(candidate),
        "bytes": candidate.stat().st_size,
        "decision": decision,
        "formal_target": formal_target.as_posix()
        if formal_target is not None
        else None,
        "formal_target_exists": bool(target_path and target_path.exists()),
        "formal_target_current_sha256": (
            _sha256(target_path)
            if target_path is not None and target_path.is_file()
            else None
        ),
        "rationale": rationale,
        "formal_write_authorized": False,
    }


def _is_delivery_file(path: Path, base: Path) -> bool:
    relative = path.relative_to(base)
    return path.is_file() and all(
        part != "__pycache__" and not part.startswith(".") for part in relative.parts
    )


def build(repository_root: Path) -> dict[str, object]:
    root = repository_root.resolve()
    f0 = root / F0
    rows: list[dict[str, object]] = []

    theory = f0 / "01_正式理论证据勘误/03-结构性理论_候选修订稿.md"
    rows.append(
        _row(
            root,
            theory,
            decision="MODIFY_AFTER_EXPLICIT_HUMAN_AUTHORIZATION",
            formal_target=Path("01_最终理论/03-结构性理论.md"),
            rationale="Downgrade archived RC1 short-window evidence language only.",
        )
    )
    for name in (
        "01_正式理论证据勘误/03-结构性理论_证据等级勘误.patch",
        "01_正式理论证据勘误/ERRATUM_README.md",
        "01_正式理论证据勘误/theory_patch_verification.json",
        "01_正式理论证据勘误/verify_theory_erratum.py",
    ):
        rows.append(
            _row(
                root,
                f0 / name,
                decision="KEEP_CANDIDATE_REVIEW_EVIDENCE",
                formal_target=None,
                rationale="Review/apply aid, not a formal source file.",
            )
        )

    atlas = f0 / "02_参数图谱正式化迁移稿"
    atlas_target = Path("02_模拟程序/03_结构性理论分析程序/pattern_atlas")
    for candidate in sorted(
        path
        for path in atlas.rglob("*")
        if _is_delivery_file(path, atlas)
        and "outputs" not in path.relative_to(atlas).parts
    ):
        relative = candidate.relative_to(atlas)
        rows.append(
            _row(
                root,
                candidate,
                decision="ADD_AFTER_EXPLICIT_HUMAN_AUTHORIZATION",
                formal_target=atlas_target / relative,
                rationale=(
                    "Configuration-driven consumer of the existing formal torus backend; "
                    "model-internal atlas only."
                ),
            )
        )
    for candidate in sorted(
        path
        for path in (atlas / "outputs/full").rglob("*")
        if _is_delivery_file(path, atlas / "outputs/full")
    ):
        rows.append(
            _row(
                root,
                candidate,
                decision="KEEP_CANDIDATE_NUMERICAL_EVIDENCE",
                formal_target=None,
                rationale="Generated reproducibility artifact; regenerate in CI before promotion.",
            )
        )
    rows.append(
        _row(
            root,
            atlas / "outputs/full_repeat_verification.json",
            decision="KEEP_CANDIDATE_NUMERICAL_EVIDENCE",
            formal_target=None,
            rationale=(
                "Machine evidence for three byte-identical full 16-case/48-trajectory runs."
            ),
        )
    )

    static = f0 / "03_无接触静态参考迁移稿"
    static_target = Path("02_模拟程序/04_离散杆刚体无接触静态参考模型")
    for candidate in sorted(
        path
        for path in static.rglob("*")
        if _is_delivery_file(path, static)
        and path.name != "generate_migration_provenance.py"
    ):
        relative = candidate.relative_to(static)
        if relative == Path("contracts/g1r_acceptance_manifest.json"):
            target = static_target / "tests/data/source_g1r_acceptance_manifest.json"
        elif relative == Path("contracts/g2_acceptance_manifest.json"):
            target = static_target / "tests/data/source_g2_acceptance_manifest.json"
        else:
            target = static_target / relative
        rows.append(
            _row(
                root,
                candidate,
                decision="ADD_AFTER_CLEAN_MIGRATION_REVIEW_AND_HUMAN_AUTHORIZATION",
                formal_target=target,
                rationale=(
                    "New no-contact static reference model identity; contact, P3R and "
                    "dynamics remain excluded."
                ),
            )
        )
    rows.append(
        _row(
            root,
            static / "tools/generate_migration_provenance.py",
            decision="KEEP_CANDIDATE_MIGRATION_TOOL",
            formal_target=None,
            rationale="Candidate-only source-binding generator.",
        )
    )

    rc1 = f0 / "04_RC1正式状态说明草案/RC1_STATUS_NOTE_DRAFT.md"
    rows.append(
        _row(
            root,
            rc1,
            decision="ADD_AFTER_EXPLICIT_HUMAN_AUTHORIZATION",
            formal_target=Path(
                "02_模拟程序/02_第一性原理高保真模拟器/"
                "Y-Pendulum-Simulator-v1.0.0-rc1/STATUS.md"
            ),
            rationale="Visible frozen-reference and HF_NUMERICAL_QUALIFICATION_NO_GO notice.",
        )
    )

    for directory, rationale in (
        (
            "06_解析稳定性图谱",
            "Candidate research artifact; no formal device or contact-capability claim.",
        ),
        (
            "07_实验门最小测量清单",
            "Experiment-gate planning artifact; no measurements have been made.",
        ),
    ):
        for candidate in sorted(
            path
            for path in (f0 / directory).rglob("*")
            if _is_delivery_file(path, f0 / directory)
        ):
            rows.append(
                _row(
                    root,
                    candidate,
                    decision="KEEP_CANDIDATE_ONLY_IN_F0",
                    formal_target=None,
                    rationale=rationale,
                )
            )

    rows.sort(key=lambda row: str(row["candidate"]))
    return {
        "schema": "YPS-F0-FORMAL-PROMOTION-FILE-MAP-1.0",
        "phase": "F0R_FORMAL_PROMOTION_BLOCKER_CORRECTIONS",
        "parent_phase": "F0_FORMAL_CONSOLIDATION_AND_ANALYTIC_STABILITY_MAP",
        "formal_directories_modified": False,
        "formal_write_authorized": False,
        "required_review_before_any_formal_write": True,
        "entries": rows,
        "summary": {
            "entry_count": len(rows),
            "candidate_formal_add_or_modify_count": sum(
                "AUTHORIZATION" in str(row["decision"]) for row in rows
            ),
            "candidate_only_or_evidence_count": sum(
                "AUTHORIZATION" not in str(row["decision"]) for row in rows
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    payload = build(arguments.repository_root)
    arguments.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

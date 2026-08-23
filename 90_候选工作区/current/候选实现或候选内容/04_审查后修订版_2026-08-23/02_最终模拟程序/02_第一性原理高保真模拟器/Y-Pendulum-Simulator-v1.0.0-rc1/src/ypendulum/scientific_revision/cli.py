"""Command-line entry point for the scientific revision layer."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .ablation import build_ablation_ladder, execute_ablation_chain
from .event_qualification import (
    compare_event_runs,
    execute_event_qualification,
)
from .scientific_guard import audit_summary_mapping
from .structural_audit import audit_structural_results


def _write_or_print(payload: object, output: str | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if output is None:
        print(text)
    else:
        target = Path(output).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ypendulum-scientific-revision",
        description=(
            "Y 形摆审查后修订工具：前向仅受拉柔索与离散柔性杆—有限刚体摆球 "
            "HF 后端、独立 EI、模型消融、事件资格与科学显示护栏。HF 名称不表示"
            "它自动比 FWD 更接近实验。"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    gui = subparsers.add_parser("gui", help="启动带科学护栏的原双后端桌面 GUI")
    gui.add_argument("--smoke-test", action="store_true")
    run = subparsers.add_parser("run-hf", help="运行一个带独立 EI 的修订 HF 模型")
    run.add_argument("--config", required=True)
    run.add_argument("--overlay", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--evidence-bundle")
    run.add_argument("--common-state")
    run.add_argument("--expected-overlay-sha256")
    ablation = subparsers.add_parser("build-ablation", help="生成 M0--M5 模型阶梯")
    ablation.add_argument("--measured-overlay", required=True)
    ablation.add_argument("--output", required=True)
    execute_ablation = subparsers.add_parser(
        "execute-ablation", help="从预冻结计划执行 M0--M5 共同初态冒烟"
    )
    execute_ablation.add_argument("--plan", required=True)
    execute_ablation.add_argument("--output", required=True)
    compare_events = subparsers.add_parser(
        "compare-event-runs", help="诊断比较已经存在的事件运行（不授予资格）"
    )
    compare_events.add_argument("--plan", required=True)
    compare_events.add_argument("--output", required=True)
    legacy_compare = subparsers.add_parser(
        "qualify-events", help="兼容别名：诊断比较已有运行，不生成资格矩阵"
    )
    legacy_compare.add_argument("--plan", required=True)
    legacy_compare.add_argument("--output", required=True)
    execute_events = subparsers.add_parser(
        "execute-event-qualification", help="从预冻结计划生成并比较事件资格矩阵"
    )
    execute_events.add_argument("--plan", required=True)
    execute_events.add_argument("--output", required=True)
    audit_run = subparsers.add_parser(
        "audit-run", help="审计一个 summary.json 的显示与证据边界"
    )
    audit_run.add_argument("--summary", required=True)
    audit_run.add_argument("--output")
    audit_structure = subparsers.add_parser(
        "audit-structure", help="审计结构性结果的有限窗证据"
    )
    audit_structure.add_argument("--input", required=True)
    audit_structure.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "gui":
        from .revised_desktop import main as gui_main

        return gui_main(["--smoke-test"] if arguments.smoke_test else [])
    if arguments.command == "run-hf":
        from .runner import run_revised_high_fidelity

        print(
            run_revised_high_fidelity(
                arguments.config,
                arguments.overlay,
                arguments.output,
                evidence_bundle_path=arguments.evidence_bundle,
                common_state_path=arguments.common_state,
                expected_overlay_sha256=arguments.expected_overlay_sha256,
            )
        )
        return 0
    if arguments.command == "build-ablation":
        print(build_ablation_ladder(arguments.measured_overlay, arguments.output))
        return 0
    if arguments.command == "execute-ablation":
        report = execute_ablation_chain(arguments.plan, arguments.output)
        print("PASS" if report["status"] == "PASS" else "FAIL")
        return 0 if report["status"] == "PASS" else 2
    if arguments.command in {"compare-event-runs", "qualify-events"}:
        report = compare_event_runs(arguments.plan, arguments.output)
        print("PASS" if report["passed"] else "FAIL")
        return 0 if report["passed"] else 2
    if arguments.command == "execute-event-qualification":
        report = execute_event_qualification(arguments.plan, arguments.output)
        print("PASS" if report["passed"] else "FAIL")
        return 0 if report["passed"] else 2
    if arguments.command == "audit-run":
        summary = json.loads(Path(arguments.summary).read_text(encoding="utf-8"))
        if not isinstance(summary, dict):
            raise ValueError("summary 根节点必须是 JSON 对象。")
        _write_or_print(audit_summary_mapping(summary), arguments.output)
        return 0
    if arguments.command == "audit-structure":
        audit_structural_results(arguments.input, arguments.output)
        print(Path(arguments.output).expanduser().resolve())
        return 0
    raise AssertionError(arguments.command)

"""Command-line entry point for the scientific revision layer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .ablation import build_ablation_ladder
from .event_qualification import qualify_event_plan
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
            "Y 形摆审查后修订工具：显式模型身份、独立 EI、模型消融、"
            "事件资格与科学显示护栏。"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    gui = subparsers.add_parser("gui", help="启动带科学护栏的原双后端桌面 GUI")
    gui.add_argument("--smoke-test", action="store_true")
    run = subparsers.add_parser("run-hf", help="运行一个带独立 EI 的修订 HF 模型")
    run.add_argument("--config", required=True)
    run.add_argument("--overlay", required=True)
    run.add_argument("--output", required=True)
    ablation = subparsers.add_parser("build-ablation", help="生成 M0--M5 模型阶梯")
    ablation.add_argument("--measured-overlay", required=True)
    ablation.add_argument("--output", required=True)
    qualify = subparsers.add_parser("qualify-events", help="执行事件工况资格比较")
    qualify.add_argument("--plan", required=True)
    qualify.add_argument("--output", required=True)
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
                arguments.config, arguments.overlay, arguments.output
            )
        )
        return 0
    if arguments.command == "build-ablation":
        print(build_ablation_ladder(arguments.measured_overlay, arguments.output))
        return 0
    if arguments.command == "qualify-events":
        report = qualify_event_plan(arguments.plan, arguments.output)
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

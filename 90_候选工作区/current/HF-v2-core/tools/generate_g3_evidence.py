#!/usr/bin/env python3
"""Generate or byte-check the deterministic HF-v2 G3 evidence artifacts."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from ypendulum_hfv2.audit.g3_evidence import (
    build_g3_evidence,
    canonical_g3_evidence_text,
)


def render_g3_report(evidence: dict[str, object], metrics_sha256: str) -> str:
    target = evidence["target"]
    assert isinstance(target, dict)
    lines = [
        "# HF-v2 G3 静态刚性接触证据报告",
        "",
        f"结论：`{evidence['status']}`。本轮没有取得 G3 候选资格；正式数值资格仍为 "
        f"`{evidence['formal_numerical_qualification']}`。",
        "",
        "## 范围和证据绑定",
        "",
        f"- 接触模型身份：`{evidence['contact_model_id']}`。",
        f"- 范围：`{evidence['scope']}`。",
        f"- 证据 JSON SHA-256：`{metrics_sha256}`。",
        f"- 正式登记：`{target['formal_registration_id']}`，正式源码只读哈希检查通过。",
        "- 唯一算法为 SciPy SLSQP；未使用兜底求解器、随机重启、容差放宽或新增种子。",
        "",
        "## 分门结论",
        "",
    ]
    gates = evidence["gate_summary"]
    assert isinstance(gates, dict)
    for name, passed in gates.items():
        lines.append(f"- `{name}`：{'PASS' if passed else 'FAIL'}。")
    lines.extend(
        [
            "",
            "## 冻结目标的原始结果",
            "",
            f"目标 `{target['case_id']}` 登记了 {target['constraint_count']} 项逐身份约束。"
            f"要求 3 个冻结种子全部通过，实际完成候选 {target['completed_seed_count']} 个，"
            f"通过全部独立门 {target['qualified_seed_count']} 个。",
            "",
        ]
    )
    seeds = target["seeds"]
    assert isinstance(seeds, list)
    for seed in seeds:
        assert isinstance(seed, dict)
        lines.extend(
            [f"### `{seed['seed_id']}`", "", f"- 执行状态：`{seed['execution_status']}`。"]
        )
        if seed["execution_status"] != "COMPLETED":
            lines.append(f"- 失败关闭：`{seed['failure_type']}`，{seed['failure_message']}")
        else:
            optimizer = seed["optimizer"]
            kkt = seed["kkt"]
            assert isinstance(optimizer, dict) and isinstance(kkt, dict)
            lines.extend(
                [
                    f"- 优化器返回：`success={str(optimizer['success']).lower()}`；该字段未作为验收门。",
                    f"- 摆球位置：`{seed['bob_position_m']}` m；总势能 `{seed['total_potential_J']:.16g}` J。",
                    f"- 间隙活动身份：`{seed['gap_active_ids']}`。",
                    f"- 正乘子支撑身份：`{seed['supported_ids']}`。",
                    f"- 活动行数/秩：{len(seed['gap_active_ids'])}/{kkt['active_constraint_rank']}；"
                    f"支撑行数/秩：{len(seed['supported_ids'])}/{kkt['supported_constraint_rank']}。",
                    f"- NNLS 乘子：`{kkt['multipliers_N']}` N。",
                    f"- 独立门总判定：`{str(seed['qualified_by_independent_gates']).upper()}`。",
                ]
            )
        lines.append("")
    small = evidence["small_benchmarks"]
    assert isinstance(small, dict)
    lines.extend(
        [
            "## NO-GO 根因",
            "",
            "1. 解析种子命中冻结的对称位置和两个正乘子，但另外两项结点套筒边界间隙也落入活动阈值。"
            "因此活动集为 4 行、秩为 3，不满足冻结的活动身份和满行秩门。",
            "2. `seed_01_infeasible_skew` 在初始登记状态触发结点套筒投影开度失败关闭。",
            "3. `seed_02_feasible_counter_skew` 的初始状态可登记，但唯一 SLSQP 路径进入摆球套筒径向单调性失效域并失败关闭。",
            "4. 按预冻结协议，不得根据这些结果修改种子、域、算法或阈值后将重跑包装成同一协议的 PASS。",
            "",
            "## 通过但不抬高结论的证据",
            "",
            f"- 小型接触基准：{small['passed_test_count']} 项测试通过。",
            "- P2 无接触回归、历史 G2R 等价观测量和候选架构门通过。",
            "- 解析种子的间隙雅可比、独立 NNLS 平衡、互补、动作—反作用和二阶曲率中，"
            "除活动身份/秩外的记录均保留在 JSON；局部门通过不能抵消多种子与活动集失败。",
            "",
            "## 结论边界与停止门",
            "",
            "本报告只证明当前 P3 静态接触候选按照冻结协议为 NO-GO。它不是装置预测、物理验证或"
            "实验验证，也不授权迁移到正式程序。本轮停在 `G3_PRO_REVIEW`，未进入 P4、P5 或 P6。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    output = arguments.output or root / "reports" / "g3_metrics.json"
    report = arguments.report or root / "reports" / "G3_REPORT.md"
    evidence = build_g3_evidence(root)
    metrics_text = canonical_g3_evidence_text(evidence)
    metrics_sha256 = hashlib.sha256(metrics_text.encode("utf-8")).hexdigest()
    report_text = render_g3_report(evidence, metrics_sha256)

    if arguments.check:
        if not output.exists() or output.read_text(encoding="utf-8") != metrics_text:
            raise SystemExit(f"G3 metrics are stale or missing: {output}")
        if not report.exists() or report.read_text(encoding="utf-8") != report_text:
            raise SystemExit(f"G3 report is stale or missing: {report}")
        print(f"G3 evidence byte-check PASS: {metrics_sha256}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(metrics_text, encoding="utf-8")
    report.write_text(report_text, encoding="utf-8")
    print(f"Wrote {output}")
    print(f"Wrote {report}")
    print(f"status={evidence['status']} sha256={metrics_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

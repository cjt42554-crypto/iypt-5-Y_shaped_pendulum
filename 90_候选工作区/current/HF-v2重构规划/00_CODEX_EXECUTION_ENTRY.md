# HF-v2 核心重构：Codex 执行入口

## 1. 当前状态

P2 预冻结提交 `2c91306` 和实现/证据提交 `3d507bb0c82e8a0a8e7560b4f80a8ddefb2ea2f1` 已完成。G2 候选状态为：

`PASS_G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONAL_ONLY`

允许结论为：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED__HF_NUMERICAL_QUALIFICATION_NO_GO`

G1R 的完整 Pro 裁决仍见：

`06_PRO_G1R_REVIEW_AND_P2_GATE.md`

正式数值资格：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

静态和动态硬接触：

`CLOSED_PENDING_PRO_REVIEW`

P2 已在 G2 停止。下一次唯一任务是 Pro 对提交 `3d507bb0c82e8a0a8e7560b4f80a8ddefb2ea2f1` 的独立复审；不得自动开始 P3。

## 2. 开始前必须读取

按以下顺序读取：

1. 顶层 `AGENTS.md`；
2. `90_候选工作区/交接说明_current.md`；
3. 本文件；
4. `06_PRO_G1R_REVIEW_AND_P2_GATE.md`；
5. `01_ARCHITECTURE_AND_PHYSICS_CONTRACT.md`；
6. `02_PHASED_IMPLEMENTATION_PLAN.md`；
7. `03_ACCEPTANCE_MATRIX.md`；
8. `04_MIGRATION_AND_ROLLBACK.md`；
9. `plan_manifest.json`；
10. `HF-v2-core` 的 `G2_REPORT.md`、`g2_metrics.json`、G2 清单、源码和测试。

`06_PRO_G1R_REVIEW_AND_P2_GATE.md` 定义了本次 G2 停止门；与较早任务范围冲突时，以该文件、本入口和 current 交接为准。

## 3. 下一次唯一范围：G2 独立复审

复审对象：

- `HF-v2-core/contracts/g2_acceptance_manifest.json`；
- `HF-v2-core/contracts/g2_module_manifest.json`；
- `HF-v2-core/src/ypendulum_hfv2/statics/`；
- `HF-v2-core/src/ypendulum_hfv2/audit/` 的 G2 新模块；
- `HF-v2-core/reports/G2_REPORT.md`；
- `HF-v2-core/reports/g2_metrics.json`；
- `HF-v2-core/tools/generate_g2_evidence.py`；
- 相关测试和提交 `3d507bb0c82e8a0a8e7560b4f80a8ddefb2ea2f1`。

复审至少检查：

1. 预冻结提交确实早于目标运行；
2. 质量、材料参考、连接点和广义布局没有第二真值；
3. 解析旋转力、反力闭合和二阶规范零模处理正确；
4. 净空只作解后域审计；
5. 状态 2 的 BFGS 退出没有被当作通过证据；
6. 三种子和三网格门没有结果驱动变化；
7. 结论严格停留在无接触静力算法条件性资格。

## 4. 等待复审期间禁止事项

- 不得修改正式 `01_最终理论/**`、`02_模拟程序/**` 或顶层 `AGENTS.md`；
- 不得实现或运行 P3 接触、P4 动力学或以后阶段；
- 不得运行三锚点接触压缩目标；
- 不得把 G2 升级为完整数值资格、装置级物理验证或实验验证；
- 不得因优化器状态 2 而追加重启、替代求解器或放宽容差；
- 不得重写历史 G1/G1R 工件。

## 5. 停止规则

当前已到 `G2_PRO_REVIEW_REQUIRED`。只有 Pro 独立复审通过，并且用户随后再次明确要求继续，才可讨论 P3。即使 G2 复审通过，也不得自动进入接触或动力学。

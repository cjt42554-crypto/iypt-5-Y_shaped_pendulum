# HF-v2 核心重构：Codex 执行入口

## 1. 当前状态

P2 已完成候选实现和 G2 证据：

- 预冻结：`2c91306f5da15c0025cf7b4efa3fc861d3075129`
- 实现与证据：`3d507bb0c82e8a0a8e7560b4f80a8ddefb2ea2f1`
- 交接：`564ba7c8020b52a541032098b55872cd54289cef`

Pro 独立复审认可静态方程和所提交结果的实质性证据：

`G2_SUBSTANTIVE_STATIC_EVIDENCE_PASS`

但未批准 G2 条件性资格。当前状态为：

`G2_PRO_APPROVAL_HOLD_PENDING_G2R`

正式数值资格：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

P3 及静态/动态硬接触：

`CLOSED_PENDING_PRO_REVIEW`

## 2. 开始前必须读取

按以下顺序读取：

1. 顶层 `AGENTS.md`；
2. `90_候选工作区/交接说明_current.md`；
3. 本文件；
4. `07_PRO_G2_REVIEW_AND_G2R.md`；
5. `06_PRO_G1R_REVIEW_AND_P2_GATE.md`；
6. `01_ARCHITECTURE_AND_PHYSICS_CONTRACT.md`；
7. `02_PHASED_IMPLEMENTATION_PLAN.md`；
8. `03_ACCEPTANCE_MATRIX.md`；
9. `04_MIGRATION_AND_ROLLBACK.md`；
10. `plan_manifest.json`；
11. 按需读取当前 G2 源码、清单、报告、指标和测试。

`07_PRO_G2_REVIEW_AND_G2R.md` 是当前最高优先级的审查性修正；与较早任务安排冲突时，以该文件、本入口和 current 交接为准。

## 3. 下一次唯一范围：G2R

下一次 Codex 只执行 G2R，不得进入 P3。

G2R 必须完成：

1. 修正静态坐标和组装身份绑定，使真实不同组装不能发生 token 碰撞；
2. 明确区分坐标布局身份和完整物理组装身份，或将全部必要字段纳入单一身份；
3. 增加改变参考姿态、附件节点身份、支点位置和环境的跨组装失败测试；
4. 显式传入冻结的 BFGS `c1`、`c2`；
5. 保留当前 G2 报告/指标为历史工件，版本化记录预冻结模块清单变化和后验闭合审计修正；
6. 增加三条绳完整材料中心线的三网格趋势；
7. 增加无量纲应变、伸长比和当前长/静长比诊断；
8. 在不改变物理方程、参数、Y 锚点、种子、网格、BFGS 方法和现有数值门的条件下重新生成 G2R 证据；
9. 比较修正前后的能量、宏观形状、张力、反力和稳定性；
10. 更新报告和交接，提交后停止并交回 Pro。

## 4. 禁止事项

G2R 期间不得：

- 实现或运行 P3 静态接触；
- 实现 P4 动力学、P5 活动集或 P6 动态接触；
- 接入 `hard_contact_candidate`；
- 修改 Y 锚点、三个种子、2/4/8 网格、BFGS 方法或现有通过阈值；
- 因状态 2 增加重启、替代优化器或放宽容差；
- 覆盖或删除历史 G1、G1R、G2 报告和机器证据；
- 修改正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、UI、公共 API 或 HDF5。

## 5. 提交和停止规则

- 只使用 `main`，不得创建分支；
- 先提交 G2R 协议、身份合同、等价性门和完整中心线采样规则，再运行修正后的目标证据；
- 协议必须明确这是 Pro 复审后的版本化修正，不能声称早于已观察的 G2 结果；
- 完成后运行全部候选测试、Ruff、`compileall`、JSON、Pandoc 和单命令证据检查；
- 更新 `交接说明_current.md` 与 `交接说明_history.md`；
- 提交并推送后停止，不得自动进入 P3。

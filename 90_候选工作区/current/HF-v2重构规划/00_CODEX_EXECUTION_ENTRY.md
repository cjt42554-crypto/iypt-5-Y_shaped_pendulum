# HF-v2 核心重构：Codex 执行入口

## 1. 当前状态

G2R 已通过 Pro 独立复审：

`G2R_PRO_REVIEW_PASS__NO_CONTACT_STATIC_ALGORITHM_ONLY`

P2 无接触静力算法状态为：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

用户的新继续指令已开启并完成 P3/G3。冻结静态接触目标的裁决为：

`NO_GO_G3_STATIC_CONTACT_ALGORITHM`

正式高保真数值资格仍为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

当前强制停止门为 `G3_PRO_REVIEW`。P4、P5、P6、正式程序迁移、公共 API、HDF5 和 UI 全部关闭。

## 2. 开始下一次任务前必须读取

按以下顺序读取：

1. 顶层 `AGENTS.md`；
2. `90_候选工作区/交接说明_current.md`；
3. 本文件；
4. `08_PRO_G2R_REVIEW_AND_P3_GATE.md`；
5. `HF-v2-core/contracts/P3_FROZEN_PROTOCOL.md`；
6. `HF-v2-core/contracts/P3_PROTOCOL_AMENDMENT_A1.md`；
7. `HF-v2-core/reports/G3_REPORT.md`；
8. `HF-v2-core/reports/g3_metrics.json`；
9. 按需读取架构、阶段、验收、迁移合同和当前源码。

`08_PRO_G2R_REVIEW_AND_P3_GATE.md` 给出 P3 原始准入边界；G3 的实际结果和当前停止状态以本入口、current 交接和绑定证据为准。

## 3. 下一次唯一范围：Pro 独立审查 G3 NO-GO

下一次不继续实现 P3，也不开始 P4、P5 或 P6。唯一范围是独立审查：

1. 接触模型和接触组装身份是否完整绑定；
2. 正式 `FIXED_REST_MATERIAL_SOCKETS_PROJECTIVE_V2` 的只读映射是否等价；
3. 协议附录 A1 是否在目标结果前形成，且没有改变物理活动域、目标或阈值；
4. 小型基准是否真实覆盖冻结的 7 类前置门；
5. 三个冻结种子是否严格使用唯一 SLSQP、固定选项且无兜底；
6. 解析种子的活动身份 4 行、秩 3 与正乘子支撑 2 行、秩 2 是否复算一致；
7. 另两个种子的套筒有效域失败关闭是否属于合同内预期行为；
8. P2 无接触回归和历史 G2R 等价证据是否保持有效；
9. `NO_GO_G3_STATIC_CONTACT_ALGORITHM` 是否应保持，下一版协议是否需要重新设计。

除非 Pro 完成新裁决且用户随后明确要求继续，不得修改冻结目标、种子、接触域、算法或阈值。

## 4. 已完成的 P3 范围

- 接触模型身份：`HFV2-DISCRETE-CORD-RIGID-BOB-0.3-CONTACT-CANDIDATE`；
- 静态、无摩擦、刚性、单边法向接触；
- 逐约束材料域、最近点见证、间隙、法向和解析雅可比；
- 零距离、塌缩、非唯一、重复登记和套筒有效域失败关闭；
- 唯一 SLSQP、三个冻结种子和独立 NNLS KKT；
- 活动身份、秩、互补、间隙雅可比、动作—反作用和二阶审计；
- P2 回归、架构审计、单命令证据和人类报告。

解析种子命中预期位置和两个正乘子，但两项结点套筒边界也被间隙阈值列为活动约束，形成 4 行、秩 3，违反冻结的两项活动身份和满行秩门。另两个种子分别在初始状态和唯一 SLSQP 路径中触发套筒有效域失败关闭。因此 3 个要求通过的种子实际为 `0/3`。

## 5. 禁止事项

当前不得：

- 通过删除零乘子约束、改写活动定义或放宽秩门把既有结果改为 PASS；
- 修改或新增种子后宣称仍是同一冻结协议；
- 增加求解器 fallback、随机重启、罚刚度或柔顺接触；
- 实现摩擦、恢复系数、冲量、动态互补或接触后推进；
- 修改 P2 轴向、弯曲、刚体、质量或无接触静态方程；
- 修改正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、UI、公共 API 或 HDF5；
- 开始 P4、P5 或 P6。

## 6. 当前证据入口

在 `90_候选工作区/current/HF-v2-core/` 运行：

```bash
.venv/bin/python tools/generate_g3_evidence.py --check
ruff check src tests tools
.venv/bin/python -m compileall -q src tests tools
.venv/bin/python -m pytest -q
```

无论局部测试或解析种子中有多少子门通过，当前总裁决不得高于 `NO_GO_G3_STATIC_CONTACT_ALGORITHM`，正式总状态不得高于 `HF_NUMERICAL_QUALIFICATION_NO_GO`。

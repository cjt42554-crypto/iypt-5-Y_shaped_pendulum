# HF-v2 候选核心与 G3 静态刚性接触 NO-GO

本目录并行维护两个候选模型身份：

- 无接触底层：`HFV2-DISCRETE-CORD-RIGID-BOB-0.2-CANDIDATE`；
- 启用静态接触：`HFV2-DISCRETE-CORD-RIGID-BOB-0.3-CONTACT-CANDIDATE`。

它们与正式 RC1 后端 `HF-DISCRETE-ROD-RIGID-BOB-1.0` 并行存在。本轮没有修改、替代或导入正式程序；正式 RC1 只作为只读接触登记来源和回归参考。

## 当前状态

P2 无接触静力算法保持 Pro 已批准的条件性资格：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

P3 按预冻结协议完成静态、无摩擦、刚性、单边法向接触的实现与 G3 证据，但冻结目标失败：

`NO_GO_G3_STATIC_CONTACT_ALGORITHM`

正式高保真数值资格仍为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

本轮已经停在 `G3_PRO_REVIEW`。P4 平滑动力学、P5 张紧—松弛活动集、P6 动态接触、正式程序迁移、公共 API、HDF5 和 UI 均未开始。

## P3 实现范围

- 以新的接触组装 SHA-256 身份绑定 P2 静态组装、正式登记合同、接触表面、逐约束参数域、几何容差和协议附录。
- 只读重建正式 `FIXED_REST_MATERIAL_SOCKETS_PROJECTIVE_V2` 的同支材料域、结点套筒和摆球套筒登记；没有导入正式 Python 包。
- 每项约束输出固定身份、最近点参数、见证点、中心距、间隙、法向、端点梯度和广义雅可比。
- 对塌缩段、零距离法向、分离的等价最近点、重复规范域和套筒有效域失效执行失败关闭。
- 唯一主算法为 `scipy.optimize.minimize(method="SLSQP")`，固定 `ftol=1e-12`、`maxiter=3000`、`disp=false`；没有 fallback、随机重启、容差放宽或结果驱动的新种子。
- 独立审计使用 NNLS 重构乘子，并检查原始、对偶、平衡、互补、活动身份、秩、间隙雅可比、动作—反作用和投影二阶曲率。

结点套筒非凸补域在任何目标结果产生前，由协议附录 A1 拆为两个互不重叠内部的凸约束身份。物理活动域、正式登记、目标、种子、求解器和阈值没有改变。

## 冻结目标结果

唯一目标 `SYMMETRIC_BOB_TWO_CORD_CONTACT_1` 要求三个冻结种子全部通过，实际只有解析种子返回候选，且没有任何种子通过全部独立门。

- `seed_00_analytic` 命中摆球位置 `[0, 0, -0.114] m` 和两个预期正乘子，分别约为 `0.288532254841271 N`；但另有两项零乘子的结点套筒边界落入活动间隙阈值。活动行数为 4、秩为 3，而冻结预期为两项活动接触、秩为 2，因此活动身份和满行秩门失败。
- `seed_01_infeasible_skew` 在初始登记状态触发结点套筒投影开度失效，按协议失败关闭。
- `seed_02_feasible_counter_skew` 的初始状态可登记，但唯一 SLSQP 路径进入摆球套筒径向单调性失效域，按协议失败关闭。

不能通过修改种子、登记域、求解器或阈值后重跑，将这次结果改写为同一协议下的 PASS。

## 通过但不抬高结论的证据

- 21 项冻结前置接触基准通过，覆盖解析几何、非唯一/退化失败关闭、一自由度单边 KKT、SLSQP 选项转发和接触组装雅可比中心差分。
- P2 无接触回归的 57 项定向测试通过。
- 接触评估前后的 P2 总势能和广义力逐位相同。
- 历史 G2R 指标哈希不变；三层主要静态观测量等价和完整材料中心线趋势复算通过。
- 候选架构清单完整，没有未分类源码、非法依赖、生产随机调用、生产 `try` 或超限模块。

这些结果只说明底层回归、小型接触原语和局部审计有效，不能抵消冻结目标的多种子、活动身份和秩失败。

## 合同与证据

- `contracts/P3_FROZEN_PROTOCOL.md`：目标结果前冻结的 P3 协议；
- `contracts/P3_PROTOCOL_AMENDMENT_A1.md`：目标结果前冻结的结点套筒约束身份修正；
- `contracts/p3_acceptance_manifest.json`：机器可读求解器、目标和验收门；
- `contracts/p3_formal_contact_registration.json`：正式只读登记和源码哈希；
- `reports/g3_metrics.json`：完整逐身份、逐种子、KKT、雅可比和二阶原始证据；
- `reports/G3_REPORT.md`：人类可审查的 G3 NO-GO 报告。

历史 `reports/G2_REPORT.md`、`reports/g2_metrics.json`、`reports/G2R_REPORT.md` 和 `reports/g2r_metrics.json` 均保留，不被 G3 证据覆盖。

## 当前验证入口

在本目录和合同绑定的隔离环境中运行：

```bash
.venv/bin/python tools/generate_g3_evidence.py --check
ruff check src tests tools
.venv/bin/python -m compileall -q src tests tools
.venv/bin/python -m pytest -q
```

G3 JSON 还可用标准 JSON 解析器复核；Markdown 交付物以 Pandoc Markdown 解析，并在浏览器中实际渲染检查。

## 结论上限与停止门

当前证据只支持“冻结 P3 静态接触算法候选为 NO-GO”。它不支持：

- 动态接触、冲量、摩擦、恢复系数或接触后时间推进；
- P4、P5 或 P6 的任何资格；
- 正式程序、公共 API、HDF5 或 UI 迁移；
- 装置级物理预测；
- 实验验证。

下一步唯一允许的工作是 Pro 独立审查 G3 实现、预冻结合同和 NO-GO 根因。任何新的 P3 修订协议或后续阶段都需要新的裁决和用户明确指令。

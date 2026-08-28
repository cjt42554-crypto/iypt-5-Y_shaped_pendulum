# 交接说明（current）

更新时间：2026-08-29 03:59 +0800（F0R 候选阻断修正已完成；当前只等待独立复审）

## 1. 当前状态与停止门

唯一授权范围 `F0R_FORMAL_PROMOTION_BLOCKER_CORRECTIONS` 已完成，状态为：

`F0R_COMPLETE_CANDIDATE_ONLY__STOP_AT_F0R_PRO_REVIEW`

当前必须停止在：

`F0R_PRO_REVIEW`

Git 绑定如下：

- F0R 输入基线与当时远程 `main`：`18a8a7055ddc70fd8a2b9898df0bb2b0d7368ca9`；
- F0R 候选实现与证据提交：`e2a1992b29502d673fe372665280510fb7c5852d`；
- 最终机器状态和本交接：由包含本文件的治理提交绑定。

正式总状态没有改变：

- 正式高保真总状态：`HF_NUMERICAL_QUALIFICATION_NO_GO`；
- P2 无接触静力历史结论上限：`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`；
- 接触认证收口：`G3R5_PRO_REVIEW_CONFIRMS_P3R5_TARGET_SUITE_NOT_ADMISSIBLE__G3R5_NOT_RUN__P3R5_CERTIFICATION_RETRY_PATH_CLOSED`。

本轮没有获得任何正式目录写入授权。旧 `90_候选工作区/current/HF-v2重构规划/plan_manifest.json` 仍只作历史快照，不是当前执行指令。

## 2. F0R 已完成交付

全部工作位于：

`90_候选工作区/current/F0_正式整理与解析稳定性图谱/**`

主要收口如下：

1. T：理论候选稿统一采用解析、理想模型数值、配置/归档候选、来源受限 RC1 和实验待定五类证据；来源受限 RC1 不再具有高保真机制裁决资格。补丁两端均指向 `01_最终理论/03-结构性理论.md`，干净临时树的源哈希、dry-run、应用和逐字节等价检查通过，正式源未修改。
2. A：图谱身份更新为 `YPS-IDEAL-TORUS-PATTERN-ATLAS-DRAFT-1.1`，继续复用正式 `FWD-TORUS-1.0` 后端。配置、结果、运行证据和来源锁采用严格关闭 schema；$p,q$ 不再强制转换；正式理论、合同、后端、全部生产源码、配置、schema 和运行时均被锁定；`sys.path` 可恢复并有故意漂移失败测试。
3. S：无接触迁移稿更新为 `YPS-NO-CONTACT-STATIC-REFERENCE-DRAFT-1.1`，生产状态与公共 API 只保留位置、姿态和保守无接触静态能力。动力学、阻力、功率、耗散、动量、动能和时间推进能力已从生产树移除；历史夹具留在测试层；规范运行证据绑定模型、组装、种子、求解器、阈值、源码与运行时。该迁移不携带历史资格。
4. M：稳定性交付明确分为 `OBSERVED_AT_FOUR_FROZEN_POINTS` 和 `INTERPOLANT_PROPERTY`。PCHIP 只作禁止外推的描述性可视化；零点状态为 `INTERPOLANT_HAS_NO_ZERO_CROSSING_ON_OBSERVED_CONVEX_HULL`，不再声称连续尺度物理观察或证明。
5. G：完成 F0R 总报告、机器状态、迁移溯源和 92 条逐文件提升清单；其中 63 条只能在后续明确授权后新增或修改正式目标，29 条保留为候选工具或证据，`formal_write_authorized=true` 为 0 条。
6. R/E：RC1 状态说明和实验门最小测量清单保留候选边界，没有扩展 RC1，也没有预设装置接触或实验结论。

完整证据与命令见：

- `90_候选工作区/current/F0_正式整理与解析稳定性图谱/F0_COMPLETION_REPORT.md`；
- `90_候选工作区/current/F0_正式整理与解析稳定性图谱/f0_machine_status.json`；
- `90_候选工作区/current/F0_正式整理与解析稳定性图谱/05_正式提升清单/formal_promotion_file_map.json`。

## 3. 已执行验证

本机绑定验证结果如下：

- 参数图谱：`14 passed`；三次独立全量运行均为 16 个参数组合、48 条主轨迹和 9 个工件，三次逐字节一致；全部 Brent 状态 `CONVERGED`，周期、能量、步长、闭合与张紧守卫门通过。
- 无接触静态：current 与 lower 两个 CPython 3.12 依赖单元均为 `57 passed`；两者复现相同源码清单、装配 token、种子、BFGS `status 2`、`success=false` 和五项独立通过诊断。状态 2 只作原始记录，未被隐藏或改写为优化器成功。
- 稳定性图谱：`7 passed`；在绑定运行时中三份完整输出逐字节一致；没有运行新接触算例。
- 理论同目标补丁、严格 schema 正负例、来源与运行时故意漂移、AST 静态-only 守卫、迁移溯源重算、Ruff、`compileall`、24 个 JSON 解析、两个 artifact manifest 内 13 个工件哈希、92 条文件映射、正式目录差分和冻结源哈希检查通过。
- F0 的 10 份 Markdown 和两份交接使用 Pandoc 3.1.3 `--from=markdown` 解析。三份关键报告以临时 MathJax 3.2.2、Playwright 和 Chrome 实际渲染；385/385 个公式节点完成且错误为 0，共 45 页经 Poppler 栅格化逐页检查。
- 仓库没有 `.github/workflows/**`；上述结果没有独立远端 CI 背书，只是本机实际执行并绑定到候选工件的验证。

## 4. 结论上限

F0R 的最高结论仅为：四类正式提升阻断已在候选区修正，并完成本机绑定的实现、数值、合同、来源和渲染验证，可进入独立候选复审。

它不意味着：

- 正式目录已经提升或获准写入；
- 正式高保真资格由 NO-GO 改为 PASS；
- 理想模型内部调谐构成实验校准；
- 新静态参考包继承历史 G2 资格；
- 四个冻结点的插值构成连续尺度物理证明；
- 装置、接触机制或实验已被验证。

## 5. 下一次唯一允许的工作

下一次只允许独立执行：

`F0R_PRO_REVIEW`

复审应从实现提交 `e2a1992b29502d673fe372665280510fb7c5852d`、F0R 总报告、机器状态、逐文件提升清单和本交接开始，独立核对候选修正与结论边界。复审本身不授权自动修改正式目录。

即使 F0R 复审通过，只有用户随后对具体正式目标逐项明确授权，才可以讨论正式提升批次；“继续工作”等一般措辞不构成该授权。

## 6. 继续禁止

不得：

- 修改或合并 `01_最终理论/**`、`02_模拟程序/**` 或顶层 `AGENTS.md`；
- 启动 P3R6、生成新接触资格留出卡或运行 G3R5；
- 修改、重算或追溯改写 P3–P3R5 冻结证据、目标、阈值或状态；
- 开始 P4、P5、P6、动力学或动态接触；
- 扩展、修补、复算或重新资格化 RC1；
- 为稳定性插值运行新接触模型尺度扫描；
- 把候选负曲率、理想模型调谐或静态参考结果写成装置级或实验结论。

本轮未执行正式提升、连续柔索或 RC1 复算、装置级物理验证、实验测量或实验验证。

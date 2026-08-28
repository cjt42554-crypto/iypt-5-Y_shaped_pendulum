# 交接说明（current）

更新时间：2026-08-28 17:02 +0800（P3R4 一次性目标准入已完成，目标套件不完整）

## 1. 当前裁决与停止点

本轮从远程 `main` 快进拉取 Pro 复审提交：

`b0e97f9910996397dac83667e09c8ca9aac73b11`

按其唯一授权范围完成：

`P3R4_STATIC_CONTACT_MANIFOLD_ADMISSIBILITY_AND_SOLVER_BASIN_SEPARATION`

P3R4 一次性目标准入分类为：

`TARGET_SUITE_NOT_ADMISSIBLE`

变几何与载荷尺度类别有可准入卡，但“非镜像对称且两个正乘子不相等”类别为 `0/4` 可准入，因此不得使用部分选择冻结目标。没有生成目标与算法初值冻结，没有运行 G3R4 资格种子，不存在 G3R4 静态接触算法 PASS 或 FAIL。

正式总状态继续为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

当前必须停在：

`G3R4_PRO_REVIEW`

下一次只能由 Pro 独立复审本轮预冻结、实现、零结果纠偏和一次性准入证据，再决定是否维持关闭或另开新的版本化协议。

## 2. 提交链与机器绑定

本轮提交链：

1. Pro 复审源提交：`b0e97f9910996397dac83667e09c8ca9aac73b11`；
2. P3R4 零结果预冻结：`411e1dd6537be50f55c5c5229b2e9a23350f44be`；
3. P3R4 初始独立实现：`7519585cdf35fd202ed8e822a0aca733b63d6eb6`；
4. 一次性结果前的失败关闭纠偏：`964ebb3f8ff942a1a75a99c9bb1510d6c016f129`；
5. P3R4 一次性准入证据：`dad339c3fc9190c0f07391181b64fe8ec8712c4b`。

首次启动一次性工具时，`R4_ASYM_B02` 在任何设计求解器进入前触发 `ContactGeometryError`；当时没有生成结果文件、部分账本或数值记录。纠偏只将八张冻结卡改为逐卡输入装配校验：无效输入以 `TARGET_INVALID` 失败关闭，参考发现与后续认证运行计数保持零，后续卡继续。冻结协议、设计卡、选择规则和门槛未修改。

实现阶段与准入阶段的机器提交顺序、源码哈希、正式源哈希和零目标/零资格运行绑定均为 `PASS`。

## 3. 八张冻结卡的一次性结果

全局计数：

- 设计卡尝试：`8`；
- 输入装配校验：`8`；
- 前代参考发现：`7`；
- 目标准入、二阶数值审计、流形有限邻域审计：各 `5`；
- 目标冻结：`0`；
- 资格种子：`0`。

逐卡结果：

- `R4_ASYM_B01`：`TARGET_INVALID`；前代参考恢复以 `FAIL_CLOSED_ACTIVE_SET_CARDINALITY_OR_RANK` 失败，未进入准入/二阶/流形审计。
- `R4_ASYM_B02`：`TARGET_INVALID`；输入装配因 `Material socket must leave positive active material extent.` 失败，后续数值计数均为零。
- `R4_ASYM_B03`：`TARGET_INVALID`；完成准入、二阶和流形审计，其中二阶一致性与流形邻域均通过，但冻结总门的 `component_scaled_kkt=false`。
- `R4_ASYM_B04`：`TARGET_INVALID`；前代参考恢复以 `FAIL_CLOSED_ACTIVE_SET_CARDINALITY_OR_RANK` 失败，未进入准入/二阶/流形审计。
- `R4_SCALE_T01`、`R4_SCALE_T02`、`R4_SCALE_T03`、`R4_SCALE_T04`：均为 `ADMISSIBLE`；按预冻结字典序规则只记录部分选择 `R4_SCALE_T01`。

由于缺少非对称必需类别，部分选择不能生成资格目标。

## 4. 证据定位

关键证据：

- `90_候选工作区/current/HF-v2-core/contracts/P3R4_FROZEN_PROTOCOL.md`；
- `90_候选工作区/current/HF-v2-core/contracts/p3r4_acceptance_manifest.json`；
- `90_候选工作区/current/HF-v2-core/contracts/p3r4_design_cards.json`；
- `90_候选工作区/current/HF-v2-core/contracts/p3r4_implementation_binding.json`；
- `90_候选工作区/current/HF-v2-core/contracts/p3r4_admissibility_selection.json`；
- `90_候选工作区/current/HF-v2-core/reports/p3r4_admissibility_metrics.json`；
- `90_候选工作区/current/HF-v2-core/reports/P3R4_ADMISSIBILITY_REPORT.md`。

关键 SHA-256：

- `p3r4_admissibility_metrics.json`：`87fe67e0f32dda0e508f86be18e796907ec71e22834c0826a9314454f817acdd`；
- `p3r4_admissibility_selection.json`：`ce1c882065a3dc64900a2e51b14157296d0558a38c23ffb70d8d53578dc34dce`；
- `P3R4_ADMISSIBILITY_REPORT.md`：`5657ab33fdd7453806131200a9bec0bd2f6215d491198ed4552ce2ac8095b20e`。

`contracts/p3r4_qualification_targets.json` 不存在。不得运行 `freeze_p3r4_targets.py --run-once` 或 `generate_g3r4_evidence.py --run-once`。

## 5. 已执行验证

本轮实际执行：

- 初始实现完整候选回归：`141 passed`；
- 零结果纠偏后完整候选回归：`142 passed in 86.77s`；
- Ruff 规则检查：通过；本轮 7 个 Python 改动文件的 `ruff format --check`：通过；
- `compileall`：通过；
- 模块清单、架构门、正式源哈希、实现哈希和提交顺序绑定：通过；
- 一次性准入工具 `--check`、JSON 计数闭合与 SHA-256 复核：通过；
- 新建/实质改写 Markdown 的 Pandoc `--from=markdown` 解析：通过；
- 预冻结协议 8 页和准入报告的浏览器实际渲染与逐页/宽视口视觉检查：已执行。

仓库不存在 `tools/check_markdown_math.py`。准入报告的窄纸张 PDF 会把九列宽表格放入横向滚动区；宽视口浏览器渲染中源文本结构正常。全仓 `ruff format --check` 仍会报告 47 个本轮未改动的历史文件与当前格式器不一致；本轮没有机械重写它们。

## 6. 必须保持的边界

不得：

- 重跑、补选、改名或结果驱动修改 P3R4 八张已观察卡；
- 改阈值、换种子、换算法、追加 fallback 或用 P3R3/P3R4 已观察结果标定新门；
- 用部分选择冻结目标，或把未运行的 G3R4 资格写成算法结论；
- 修改 P3/G3、P3R/G3R、P3R2/G3R2、P3R3/G3R3 或 P3R4 已绑定的协议、卡、报告、指标和哈希；
- 进入 P4、P5、P6、动力接触、正式提升、公共 API、HDF5、UI、物理验证或实验验证。

本轮所有新增与修改都位于 `90_候选工作区/current/**`。`01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、公共 API、HDF5 和 UI 均未修改。

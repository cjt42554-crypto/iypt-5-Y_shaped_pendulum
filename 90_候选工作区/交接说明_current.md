# 交接说明（current）

更新时间：2026-08-28 20:16 +0800（P3R5 一次性留出准入完成，目标套件不完整）

## 1. 当前结论与停止门

P3R5 冻结分类为：

`TARGET_SUITE_NOT_ADMISSIBLE`

八张未观察留出卡均按冻结顺序完整执行一次。非对称类别 `4/4` 为 `ADMISSIBLE`，尺度变化类别 `0/4` 为 `ADMISSIBLE`，因此不能形成两个必需类别的完整目标套件。非对称类别的局部通过已按冻结规则丢弃，不得结转为部分资格目标。

没有生成 `p3r5_qualification_targets.json`，没有冻结资格种子，没有运行 G3R5 实际复合算法。因此本轮不存在 G3R5 算法 PASS 或 `NO_GO_G3R5_STATIC_CONTACT_ALGORITHM`；只有 P3R5 目标套件不可准入。

强制停止门为：

`G3R5_PRO_REVIEW`

当前没有获授权的 Codex 后续执行任务。P3R5 失败不自动授权 P3R6；只能先做 Pro 独立复审，新一轮数值或物理修正必须有新假设、新版本协议与用户明确授权。

正式高保真总状态继续为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

## 2. 有序提交链

P3R5 已形成四个适用的严格顺序边界，且都已推送远程 `main`：

1. 零结果协议提交：`fc110ca8ab980b3628a510ede5badacde6652e6a`；
2. 开发实现提交：`d751848044cbb805bacbc72f3fa28c1c22d25757`；
3. 零数值运行留出冻结提交：`802bcd00113e163e2c5584edcf8a61930a3cbf6f`；
4. 一次性留出准入证据提交：`69f12bf54d0f00ee30be275813dcb6d702384234`。

因目标套件不完整，冻结协议的第 5 段目标与种子冻结和第 6 段 G3R5 资格证据不适用，已按失败关闭规则跳过。本交接为第 7 段停止边界。

## 3. 一次性准入事实

一次性账本共 `91` 条 JSONL 记录：

- 首条在打开具体留出文件前排他创建，尝试编号为 `1`；
- 末条为 `ADMISSIBILITY_CAMPAIGN_CLOSED`；
- 中间没有中断、重试、补选、阈值变更、随机重启或回退算法记录；
- 账本存在后未再运行 `--run-once`。

全局运行计数为：

- 输入装配 `8`；
- 参考构造 `8`；
- 目标准入 `8`；
- 二阶数值一致性 `8`；
- 约束流形有限邻域 `8`；
- 目标冻结 `0`；
- 资格种子 `0`。

八张卡的固定双活动 KKT 参考均在解析初值处以 `CONVERGED_AT_ENTRY` 闭合，Newton 迭代数为 `0`，三层完整残差 Jacobian 审计均通过。这只证明参考构造和冻结数值门在这些卡上自洽，不是算法吸引域、物理验证或实验验证。

## 4. 目标套件失败原因

四张非对称卡 `R5_ASYM_H01` 至 `R5_ASYM_H04` 的冻结准入检查全部通过，临界锥最小归一化曲率约为 `0.0237721` 至 `0.0253535`，高于冻结下限 `0.0005`。

四张尺度变化卡的参考构造、分量 KKT、中心化对偶证书、二阶 Richardson 一致性、流形有限邻域和完整复合 Jacobian 都通过，但临界锥和支撑切空间最小曲率均为负：

- `R5_SCALE_H01`：`-0.034607470089469086`；
- `R5_SCALE_H02`：`-0.04509710039136304`；
- `R5_SCALE_H03`：`-0.0678280310859007`；
- `R5_SCALE_H04`：`-0.03973832758607185`。

因此这四个驻定参考不满足冻结的严格正临界锥曲率门，各分类为 `TARGET_INVALID`。这是候选静态刚性无摩擦接触模型内的数值稳定性反证，不是实验装置预测。

指标中这四张卡的 `critical_cone_crosscheck=false` 不是第二个独立数值交叉误差失败：该布尔字段继承自历史实现的聚合 `critical.passed`，其中同时包含正曲率门。实际独立曲率交叉误差为 `4.10e-6` 至 `4.53e-5`，均不超过冻结上限 `5.0e-5`；未对称相对量约为 `7.66e-10` 至 `1.68e-9`，也不超过 `3.0e-5`。该标签耦合不改变负曲率已独立使目标失效的分类，但 Pro 复审时应按此解读。

## 5. 关键工件与哈希

必须保留且不得重写的 P3R5 工件包括：

- `90_候选工作区/current/HF-v2-core/contracts/P3R5_FROZEN_PROTOCOL.md`；
- `90_候选工作区/current/HF-v2-core/contracts/p3r5_implementation_binding.json`；
- `90_候选工作区/current/HF-v2-core/contracts/p3r5_holdout_cards.json`；
- `90_候选工作区/current/HF-v2-core/reports/p3r5_attempt_ledger.jsonl`；
- `90_候选工作区/current/HF-v2-core/contracts/p3r5_admissibility_selection.json`；
- `90_候选工作区/current/HF-v2-core/reports/p3r5_admissibility_metrics.json`；
- `90_候选工作区/current/HF-v2-core/reports/P3R5_ADMISSIBILITY_REPORT.md`。

关键结果哈希为：

- 账本：`f87c5aa3675ea792c2cbc6e24ae3b2daca8abdd4a7900a31f01de848316fd66c`；
- 准入指标：`e93eb9a0cb074ca1cc9a137149b89b8d2c4384f100c9a9eefaf5c0ff79a3f987`；
- 选择记录：`2a8eab29bda268a87bf8e8c488690a4150225b8964562e440f79b328fa733ff4`；
- Markdown 报告：`8db7859639ac36920050d820776e513e941692ace5339bc619675923190122cd`。

## 6. 已执行与未执行验证

实现提交前已执行：

- P3R5 定向候选测试：`30 passed in 5.13s`；
- 完整候选测试：`172 passed in 97.14s`；
- Ruff 规则检查与格式检查；
- `compileall`；
- 27 个实现路径哈希绑定；
- 架构门：`PASS`，生产层 `try=0`、随机调用 `=0`、依赖违规 `=0`、超限模块 `=0`；
- 运行时合同：`PASS`。

留出冻结后严格按协议只运行一次真实留出准入。结果后已执行一次性工具静态 `--check`、JSON 解析、计数闭合、账本哈希闭合、Pandoc `--from=markdown` 解析和 HTML/Chrome 实际渲染检查。Pandoc standalone 默认窄正文宽度使宽表的计数列标题换行，但没有渲染失败或内容截断。仓库中不存在 `tools/check_markdown_math.py`，因此未执行该专用检查器。

未执行：

- 目标与资格种子冻结；
- G3R5 实际多种子复合算法；
- P4、P5、P6、动力学或动态接触；
- 装置级物理验证或实验验证；
- 正式程序迁移、公共 API、HDF5 或 UI 验证。

## 7. 下一次开始前必须读取

按以下顺序读取：

1. 顶层 `AGENTS.md`；
2. 本文件；
3. `90_候选工作区/current/HF-v2重构规划/13_PRO_G3R4_REVIEW_AND_P3R5_GATE.md`；
4. `90_候选工作区/current/HF-v2-core/contracts/P3R5_FROZEN_PROTOCOL.md`；
5. `90_候选工作区/current/HF-v2-core/contracts/p3r5_acceptance_manifest.json`；
6. `90_候选工作区/current/HF-v2-core/contracts/p3r5_implementation_binding.json`；
7. `90_候选工作区/current/HF-v2-core/contracts/p3r5_holdout_cards.json`；
8. P3R5 账本、选择记录、准入指标和报告。

如果下一次任务是 Pro 独立复审，应静态审查提交链、一次性账本、哈希绑定、负曲率原始记录和上述 `critical_cone_crosscheck` 标签耦合；不得重跑留出准入。

## 8. 下一次禁止事项

在新的用户与 Pro 授权前，不得：

- 删除、截断、重写或重跑 P3R5 一次性账本与留出准入；
- 修改留出卡、参考构造、临界锥阈值、选择规则或实现提交；
- 冻结部分目标、运行资格种子或运行 G3R5；
- 把 `TARGET_SUITE_NOT_ADMISSIBLE` 写成 G3R5 算法 NO-GO；
- 自动开始 P3R6、P4、P5、P6、动力学或动态接触；
- 修改正式理论、正式程序、公共 API、HDF5 或 UI。

本轮所有修改均位于 `90_候选工作区/current/**`。`01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、既有目录结构、公共 API、HDF5 和 UI 均未修改。

# 交接说明（current）

更新时间：2026-08-28 18:33 +0900（G3R4 Pro 独立复审完成，P3R5 已授权）

## 1. 当前裁决与状态

P3R4 冻结分类保持：

`TARGET_SUITE_NOT_ADMISSIBLE`

G3R4 Pro 独立复审裁决为：

`G3R4_PRO_REVIEW_CONFIRMS_P3R4_TARGET_SUITE_NOT_ADMISSIBLE_WITH_ASSEMBLY_PREFLIGHT_DEVIATION__P3R5_HOLDOUT_REFERENCE_CONSTRUCTION_AUTHORIZED`

复审与 P3R5 授权提交为：

`d8e9173a3078d73e42a3875bd707758abf456521`

P3R5 当前状态为：

`P3R5_READY_FOR_CODEX_EXECUTION`

P2 无接触静力算法继续保持：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

历史静态接触裁决继续保持：

- `NO_GO_G3_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`；
- P3R3 的 `TARGET_SUITE_NOT_ADMISSIBLE`；
- P3R4 的 `TARGET_SUITE_NOT_ADMISSIBLE`。

正式高保真总状态继续为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

P4、P5、P6、动力学、动态接触、正式程序迁移、公共 API、HDF5、UI、装置级物理验证和实验验证全部关闭。

## 2. P3R4 复审结论

P3R4 正式账本的结果为：

- 八张冻结卡各有一次输入装配记录；
- 参考发现运行 `7`；
- 准入、二阶和流形审计各运行 `5`；
- 非对称类别 `0/4` 可准入；
- 尺度类别 `4/4` 可准入；
- 部分选择为 `R4_SCALE_T01`；
- 目标冻结和资格种子运行均为 `0`。

没有生成 `p3r4_qualification_targets.json`，没有运行 G3R4 资格算法，因此不存在 G3R4 算法 PASS 或 FAIL。

首次一次性工具启动在数值求解前因 `R4_ASYM_B02` 输入装配失败而中断；随后存在一次账本外、仅装配级逐卡诊断。该诊断没有运行参考发现、KKT、二阶、流形或资格求解，也没有改变卡、阈值、种子、算法或选择规则，所以不推翻正式数值分类。

但输入可构造性被额外观察过，必须永久保留：

`P3R4_ASSEMBLY_PREFLIGHT_DEVIATION`

`all_design_cards_executed_exactly_once=true` 只能解释为正式账本内受计数执行恰好一次，不得扩张为现实中的所有装配操作只发生一次。全部 P3R4 卡只能作为已观察开发/回归材料，不能再充当未观察目标。

完整裁决见：

`90_候选工作区/current/HF-v2重构规划/13_PRO_G3R4_REVIEW_AND_P3R5_GATE.md`

## 3. 下一次开始前必须读取

按以下顺序读取：

1. 顶层 `AGENTS.md`；
2. 本文件；
3. `90_候选工作区/current/HF-v2重构规划/00_CODEX_EXECUTION_ENTRY.md`；
4. `90_候选工作区/current/HF-v2重构规划/13_PRO_G3R4_REVIEW_AND_P3R5_GATE.md`；
5. `90_候选工作区/current/HF-v2-core/contracts/P3R4_FROZEN_PROTOCOL.md`；
6. `90_候选工作区/current/HF-v2-core/contracts/p3r4_acceptance_manifest.json`；
7. `90_候选工作区/current/HF-v2-core/contracts/p3r4_implementation_binding.json`；
8. `90_候选工作区/current/HF-v2-core/contracts/p3r4_admissibility_selection.json`；
9. `90_候选工作区/current/HF-v2-core/reports/P3R4_ADMISSIBILITY_REPORT.md`；
10. `90_候选工作区/current/HF-v2-core/reports/p3r4_admissibility_metrics.json`；
11. P3R4 的准入、算例、恢复、证据绑定、一次性工具及相关测试。

P3 至 P3R4 的冻结协议、源码绑定、设计卡、目标、种子、报告、指标和哈希均为不可变历史。

## 4. 下一次唯一范围

只执行：

`P3R5_STATIC_CONTACT_REFERENCE_CONSTRUCTION_AND_HOLDOUT_QUALIFICATION`

P3R5 是同一静态刚性、无摩擦、单边接触物理下最后一次仅修参考构造和资格治理的认证层修订。建议最低身份为：

- `HFV2-DISCRETE-CORD-RIGID-BOB-0.8-CONTACT-CANDIDATE`；
- `YPS-HFV2-CONTACT-ASSEMBLY-IDENTITY-6.0`；
- 独立包 `ypendulum_hfv2_p3r5`；
- `P3R5_*` 与 `G3R5_*` 工件命名空间。

全部 P3R3/P3R4 卡必须标记为：

`OBSERVED_DEVELOPMENT_AND_REGRESSION_ONLY`

它们只能用于开发、诊断和回归，不得用于 P3R5 资格目标、补选或留出泛化声明。

## 5. P3R5 必须完成的核心修正

P3R5 必须：

1. 在零留出结果时冻结参数域、纯输入可构造性谓词、确定性哈希选择规则、留出数量、顺序和选择规则；
2. 先在已观察开发集上实现并提交确定性双活动接触 KKT 参考构造器；
3. 实现提交进入远程 `main` 后，才按冻结规则生成具体未观察留出卡；
4. 在留出冻结前以纯合同谓词排除材料套筒无正活动范围、非法区间、非正长度/半径/尺度、非有限、塌缩和重复身份；
5. 默认原值继承 P3R4 的 KKT、对偶、临界锥、Richardson、流形、Jacobians、作用—反作用和 P2 逐比特只读门；
6. 在读取或装配第一张留出卡前写入不可删除的一次性尝试账本，异常、中断或部分执行后保留账本并停止。

留出冻结后若发生输入装配失败，必须分类为：

`P3R5_PROTOCOL_CONSTRUCTION_FAILURE`

不得修代码后重跑同一留出集。

## 6. 强制提交顺序

至少形成七个有序边界：

1. P3R5 零结果协议提交；
2. 开发实现提交，只运行已观察回归集；
3. 留出冻结提交，全部数值运行计数为零；
4. 一次性目标准入提交，含从进程启动开始的完整账本；
5. 目标与种子冻结提交，仅在两个必需类别完整时生成；
6. G3R5 资格证据提交，第 5 项进入远程 `main` 后才运行；
7. 交接提交，并停止在 `G3R5_PRO_REVIEW`。

任一阶段发生协议构造失败、目标套件不足、认证器内部不一致、历史回归失败或算法 NO-GO，都跳过不再适用的后续阶段并停止。

## 7. 禁止事项

不得：

- 修改或覆盖 P3 至 P3R4 历史冻结工件；
- 重跑、补选或结转 P3R4 卡与部分目标；
- 把账本外装配诊断改写成从未发生；
- 用已观察结果调整 KKT、对偶、二阶或流形门；
- 通过修改或重做实现提交磨取有利留出卡；
- 在留出冻结后修代码并重跑同一留出集；
- 增加 fallback、随机重启、罚刚度、柔顺接触、摩擦、恢复系数、冲量或动力学；
- 修改正式目录、公共 API、HDF5 或 UI；
- 开始 P4、P5、P6、动力学、动态接触或正式提升。

## 8. 停止规则与验证边界

P3R5 无论得到协议构造失败、目标套件不足、G3R5 候选 PASS 或算法 NO-GO，都必须停止在：

`G3R5_PRO_REVIEW`

P3R5 失败不自动授权 P3R6。继续必须提出新的物理或数值假设，并取得用户与 Pro 的新授权。

本次 Pro 复审通过 GitHub 连接器完成提交链、冻结协议、纠偏差分、关键源码和已提交指标的静态复核。没有重新运行仓库所称的 `142 passed`、Ruff、`compileall`、P3R4 一次性工具或数值求解，也没有独立重算三个已记录 SHA-256。

本次新增或实质改写的 Markdown 已通过 Pandoc `--from=markdown` 解析和基本格式检查。正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、数值源码、测试、公共 API、HDF5 和 UI 均未修改。

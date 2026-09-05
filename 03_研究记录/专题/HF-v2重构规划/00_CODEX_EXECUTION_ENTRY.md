# HF-v2 核心重构：Codex 执行入口

## 1. 当前状态

P2 无接触静力算法继续保持：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

历史静态接触裁决继续保持：

- `NO_GO_G3_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`。

P3R3 与 P3R4 冻结结果均为：

`TARGET_SUITE_NOT_ADMISSIBLE`

两轮都没有完整冻结资格目标，也没有运行 G3R3 或 G3R4 资格种子，因此不存在相应算法 PASS 或 FAIL。

最新 Pro 裁决为：

`G3R4_PRO_REVIEW_CONFIRMS_P3R4_TARGET_SUITE_NOT_ADMISSIBLE_WITH_ASSEMBLY_PREFLIGHT_DEVIATION__P3R5_HOLDOUT_REFERENCE_CONSTRUCTION_AUTHORIZED`

P3R5 当前状态为：

`P3R5_READY_FOR_CODEX_EXECUTION`

正式高保真总状态继续为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

P4、P5、P6、动力学、动态接触、正式程序迁移、公共 API、HDF5、UI、装置级物理验证和实验验证全部关闭。

## 2. 开始前必须读取

按以下顺序读取：

1. 顶层 `AGENTS.md`；
2. `90_候选工作区/交接说明_current.md`；
3. 本文件；
4. `13_PRO_G3R4_REVIEW_AND_P3R5_GATE.md`；
5. `HF-v2-core/contracts/P3R4_FROZEN_PROTOCOL.md`；
6. `HF-v2-core/contracts/p3r4_acceptance_manifest.json`；
7. `HF-v2-core/contracts/p3r4_implementation_binding.json`；
8. `HF-v2-core/contracts/p3r4_admissibility_selection.json`；
9. `HF-v2-core/reports/P3R4_ADMISSIBILITY_REPORT.md`；
10. `HF-v2-core/reports/p3r4_admissibility_metrics.json`；
11. `HF-v2-core/src/ypendulum_hfv2_p3r4/admissibility.py`；
12. `HF-v2-core/src/ypendulum_hfv2_p3r4/cases.py`；
13. `HF-v2-core/src/ypendulum_hfv2_p3r4/restoration.py`；
14. `HF-v2-core/src/ypendulum_hfv2_p3r4/evidence_support.py`；
15. `HF-v2-core/tools/generate_p3r4_admissibility.py`；
16. 按需读取 P3R4 测试和更早历史工件。

P3/G3、P3R/G3R、P3R2/G3R2、P3R3 和 P3R4 的协议、源码绑定、设计卡、目标、种子、报告、指标和哈希均为不可变历史。不得修改旧文件后追溯改写状态。

## 3. 下一次唯一范围

只执行：

`P3R5_STATIC_CONTACT_REFERENCE_CONSTRUCTION_AND_HOLDOUT_QUALIFICATION`

P3R5 只允许：

- 把全部 P3R3/P3R4 卡声明为已观察开发/回归集；
- 建立确定性活动接触 KKT 参考构造器；
- 在实现提交后，按预冻结哈希规则生成新的未观察留出卡；
- 在留出冻结前完成纯输入域可构造性证明；
- 继承并分离参考稳定性、二阶一致性、流形邻域和实际多种子吸引证据；
- 建立从工具启动前开始、异常后不可删除的一次性尝试账本。

不得修改 P2 势能/广义力、刚性无摩擦单边接触间隙、正式登记活动域、材料/载荷方程或历史结果。

P3R5 必须使用新身份，建议最低为：

- `HFV2-DISCRETE-CORD-RIGID-BOB-0.8-CONTACT-CANDIDATE`；
- `YPS-HFV2-CONTACT-ASSEMBLY-IDENTITY-6.0`；
- `ypendulum_hfv2_p3r5`；
- `P3R5_*` 与 `G3R5_*` 工件命名空间。

## 4. P3R4 复审结论必须保留

P3R4 正式结果为：

- 非对称类别 `0/4` 可准入；
- 尺度类别 `4/4` 可准入；
- 只有部分选择 `R4_SCALE_T01`；
- 目标冻结数和资格种子数均为零。

账本外逐卡装配诊断没有运行任何数值求解或认证，未改变卡、阈值、种子、算法和选择规则，因此不推翻 `TARGET_SUITE_NOT_ADMISSIBLE`。

但装配可构造性被额外观察过，所以必须永久保留：

`P3R4_ASSEMBLY_PREFLIGHT_DEVIATION`

`all_design_cards_executed_exactly_once=true` 只限正式账本内受计数执行，不得声称现实中的装配操作只发生一次。P3R4 卡不得再充当未观察目标。

## 5. 开发集与留出集

全部 P3R3/P3R4 卡标记为：

`OBSERVED_DEVELOPMENT_AND_REGRESSION_ONLY`

可在这些卡上开发、测试和解释新参考构造器，但不得：

- 用它们作为 P3R5 资格目标；
- 用 B03 的残差调整刚好放行它的 KKT 门；
- 把 P3R4 的部分尺度选择结转到 P3R5；
- 声称已观察卡证明留出泛化。

P3R5 零结果协议必须预先冻结参数生成域、纯输入谓词、确定性哈希选择规则、留出卡数量、顺序和目标选择规则。新实现进入远程 `main` 后，才能一次生成具体留出卡；生成时所有数值运行计数必须为零。

## 6. 输入构造门

留出冻结前必须以不运行参考求解器的纯合同谓词证明：

- 材料套筒留下严格正活动范围；
- 套筒区间合法且有序；
- 分支长度、接触半径和特征尺度严格为正；
- 全部输入有限、非塌缩、身份不重复；
- 解析构造位于允许物理有效域。

留出冻结后若仍发生输入装配失败，必须分类为：

`P3R5_PROTOCOL_CONSTRUCTION_FAILURE`

并停止。不得修实现后重跑同一留出集。

## 7. 参考构造器

P3R5 不得继续把 P3R3 复合算法直接作为唯一参考发现器。必须预冻结确定性双活动接触 KKT 构造器：

- 使用独立约化坐标消除规范，或在完整坐标中显式加入规范方程及乘子；
- 冻结残差、尺度、完整 Jacobian、线性求解器、奇异值门、全局化、迭代上限和失败状态；
- 固定活动身份与允许的活动集规则；
- 禁止 fallback、随机重启、容差放宽和结果驱动算法切换；
- 在已观察开发集上完成实现和回归后再冻结留出卡。

`R4_ASYM_B03` 只可用于解释并闭合分量尺度 KKT 残差，不得通过放宽 `1.0e-8` 量级门使其通过。

## 8. 认证门

默认原值继承 P3R4 的：

- 分量尺度 KKT、互补、正乘子和支撑秩；
- 中心化对偶、`highs-ds`、独立端点复核；
- 临界锥、矩阵/方向曲率交叉检查；
- 三层 Richardson 及截断/舍入不确定度；
- 确定性流形收回和真实势能邻域；
- Jacobians、作用—反作用和 P2 逐比特只读。

只有在零留出结果时给出独立数学或误差预算的门才可修改。不得依据 P3R4 结果调整阈值。

两个必需类别都必须从 P3R5 新留出卡中产生目标。套件不足时不得冻结部分目标或运行 G3R5。

## 9. 一次性账本

工具必须在读取或装配第一张留出卡前写入不可删除的尝试账本，绑定：

- 仓库 HEAD、工作树状态和启动时间；
- 协议、实现、留出卡和清单哈希；
- 尝试编号 `1`；
- 全部零运行计数。

每完成输入装配、参考构造或认证阶段就追加检查点。异常或中断必须保留账本并停止，禁止自助重跑。

## 10. 强制提交顺序

至少形成七个有序边界：

1. **P3R5 零结果协议提交**；
2. **开发实现提交**，只运行已观察回归集；
3. **留出冻结提交**，全部数值计数为零；
4. **一次性目标准入提交**，含从启动开始的完整账本；
5. **目标与种子冻结提交**，仅在两个类别完整时生成；
6. **G3R5 资格证据提交**，第 5 项进入远程 `main` 后才运行；
7. **交接提交**，停止在 `G3R5_PRO_REVIEW`。

任一阶段发生协议构造失败、套件不足、认证器内部不一致、历史回归失败或算法 NO-GO，都跳过不再适用的后续阶段并停止。

## 11. 禁止事项

不得：

- 修改 P3 至 P3R4 历史冻结工件；
- 重跑或补选 P3R4 卡；
- 把账本外装配诊断改写成“从未发生”；
- 结转 P3R4 部分目标；
- 用已观察结果调 KKT、二阶、流形或对偶门；
- 通过提交磨取有利留出卡；
- 在留出冻结后修代码并重跑同一留出集；
- 增加 fallback、随机重启、罚刚度、柔顺接触、摩擦、恢复系数、冲量或动力学；
- 修改正式目录、公共 API、HDF5 或 UI；
- 开始 P4、P5、P6 或正式提升。

## 12. 完成与停止规则

P3R5 无论得到协议构造失败、目标套件不足、G3R5 候选 PASS 或算法 NO-GO，都必须停止在：

`G3R5_PRO_REVIEW`

P3R5 是同一物理和认证框架下最后一次仅修参考构造/治理的修订。失败不自动授权 P3R6；继续必须提出新的模型或数值假设，并取得用户与 Pro 的新授权。

## 13. 当前验证边界

本次 Pro 复审通过 GitHub 连接器完成提交链、冻结协议、纠偏差分、关键源码和已提交指标的静态复核。没有重新运行仓库所称的 `142 passed`、Ruff、`compileall`、P3R4 一次性工具或任何数值求解，也没有独立重算三个交付 SHA-256。

本次只更新候选治理、执行入口和交接文档。正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、数值源码、测试、公共 API、HDF5 和 UI 均不修改。

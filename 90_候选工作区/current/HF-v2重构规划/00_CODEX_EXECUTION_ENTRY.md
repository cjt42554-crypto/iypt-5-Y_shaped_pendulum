# HF-v2 核心重构：Codex 执行入口

## 1. 当前状态

P2 无接触静力算法继续保持：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

历史静态接触裁决继续保持：

- `NO_GO_G3_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`。

P3R3 冻结结果为：

`TARGET_SUITE_NOT_ADMISSIBLE`

P3R3 没有冻结资格目标，也没有运行资格种子，因此不存在 G3R3 算法 PASS 或 FAIL。

最新 Pro 裁决为：

`G3R3_PRO_REVIEW_CONFIRMS_P3R3_TARGET_SUITE_NOT_ADMISSIBLE__P3R4_MANIFOLD_ADMISSIBILITY_AND_SOLVER_BASIN_SEPARATION_AUTHORIZED`

P3R4 当前状态为：

`P3R4_READY_FOR_CODEX_EXECUTION`

正式高保真总状态继续为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

P4、P5、P6、动力学、动态接触、正式程序迁移、公共 API、HDF5、UI、装置级物理验证和实验验证全部关闭。

## 2. 开始前必须读取

按以下顺序读取：

1. 顶层 `AGENTS.md`；
2. `90_候选工作区/交接说明_current.md`；
3. 本文件；
4. `12_PRO_G3R3_REVIEW_AND_P3R4_GATE.md`；
5. `HF-v2-core/contracts/P3R3_FROZEN_PROTOCOL.md`；
6. `HF-v2-core/contracts/p3r3_acceptance_manifest.json`；
7. `HF-v2-core/contracts/p3r3_qualification_targets.json`；
8. `HF-v2-core/reports/P3R3_ADMISSIBILITY_REPORT.md`；
9. `HF-v2-core/reports/p3r3_admissibility_metrics.json`；
10. `HF-v2-core/src/ypendulum_hfv2_p3r3/admissibility.py`；
11. `HF-v2-core/src/ypendulum_hfv2_p3r3/cases.py`；
12. `HF-v2-core/src/ypendulum_hfv2_p3r3/certification.py`；
13. `HF-v2-core/src/ypendulum_hfv2_p3r3/dual_certification.py`；
14. `HF-v2-core/src/ypendulum_hfv2_p3r3/restoration.py`；
15. 按需读取 P3R3 测试、P3R2 历史回归和更早冻结工件。

P3/G3、P3R/G3R、P3R2/G3R2、P3R3 的协议、源码绑定、设计卡、目标、种子、报告、指标和哈希均为不可变历史。不得修改旧文件后追溯改写状态。

## 3. 下一次唯一范围

只执行：

`P3R4_STATIC_CONTACT_MANIFOLD_ADMISSIBILITY_AND_SOLVER_BASIN_SEPARATION`

P3R4 只允许修正认证与资格治理：

- 分离参考点约束稳定性、二阶数值一致性、有限邻域几何审计和实际算法吸引证据；
- 用新版本替代 P3R3 与稳定裕量脱钩的双半径最大绝对层差门；
- 若宣称有限邻域，构造活动接触与规范约束流形上的确定性收回；
- 明确区分约束流形几何探针和允许偏离流形的求解器初值；
- 预冻结新的未观察目标卡族、选择规则、种子和运行计数；
- 保留 P3R3 对偶证书、独立二维端点复核和完整复合 Jacobian 审计为只读回归。

不得修改 P2 势能/广义力、刚性无摩擦单边接触间隙、正式登记活动域、材料/载荷方程或历史结果。

P3R4 必须使用新身份，建议起点为：

- `HFV2-DISCRETE-CORD-RIGID-BOB-0.7-CONTACT-CANDIDATE`；
- 新的认证/组装身份，不复用 4.0；
- `ypendulum_hfv2_p3r4`；
- `P3R4_*` 与 `G3R4_*` 工件命名空间。

## 4. 必须纠正的语义

P3R3 的 `_basin_certificate` 使用参考切空间直线：

$$
q_{\pm}=q_0\pm h S d
$$

并以固定参考乘子计算拉格朗日量中心差分。端点没有被收回：

$$
g_A(q_{\pm})=0
$$

因此它可以作为参考点 Hessian 的数值审计，但不能同时声称是活动约束流形上的有限盆地或求解器吸引域。

P3R4 必须二选一：

1. 取消“运行前算法盆地证书”，只做参考稳定性和几何安全邻域；算法吸引域由目标冻结后的实际多种子结果决定；
2. 或明确构造约束流形收回，并在收回曲线上审计真实势能、约化 Hessian 或有证明边界的等价量。

不得继续用固定乘子环境直线探针命名有限盆地。

## 5. 参考稳定性与二阶数值门

每个新参考必须在目标选择前独立通过：

- 身份、有限性、严格有效域、预期近活动/支撑身份和严格非活动正间隙；
- 分量尺度 KKT、正乘子、互补、显式对偶见证和独立端点复核；
- 真实一侧临界锥或等价约化切空间的严格正二阶充分条件；
- 矩阵 Hessian 与独立标量方向曲率；
- 物理/有效域 Jacobian、作用—反作用和 P2 逐比特只读；
- 完整复合残差 Jacobian 审计。

多半径数值一致性必须在任何新目标运行前冻结差分阶次和误差模型。应使用至少三个嵌套步长、Richardson 或等价独立误差估计，并要求“外推曲率减不确定度仍高于正门”。不得使用与曲率大小和稳定裕量脱钩的单一最大绝对层差，也不得依据 P3R3 已观察结果选取刚好放行的数值。

## 6. 有限邻域和种子

若实现约束流形收回，必须固定三个切向坐标及一个规范条件，确定性求解活动间隙为零。每个收回点至少保存：

- 活动间隙残差；
- 活动行秩；
- 支路方向连续性；
- 非活动最小正间隙；
- 最小有效域裕量；
- 收回迭代、容差和失败状态。

资格种子合同必须区分：

- 约束流形上的几何探针；
- 允许偏离流形的算法初值。

每个目标至少冻结参考种子和两个非共线偏置种子。种子必须在目标冻结提交进入 Git 历史后才可运行。

## 7. 新目标和历史卡

P3R3 六张设计卡及其结果已观察，只可作只读诊断/回归。不得重跑、补选或直接充当 P3R4 新资格目标，也不得用它们校准放行阈值。

P3R4 必须在任何新结果前冻结新的设计卡族，至少覆盖：

1. 非镜像对称且两个正乘子不相等；
2. 改变几何或载荷尺度。

每类应有冗余卡；所有卡按固定顺序各运行一次，使用预冻结确定性选择规则。`ASYM_A03` 的 `component_scaled_kkt=false` 必须作为独立历史失败保留，不能通过删除 KKT 门消除。

## 8. 强制提交顺序

至少形成六个有序边界：

1. **P3R4 零结果预冻结提交**：新协议、清单、身份、二阶误差模型、流形/几何邻域定义、新卡族和全部运行计数零；
2. **P3R4 独立实现提交**：新包、测试、工具和机器绑定进入历史；新卡仍未运行；
3. **P3R4 一次性目标准入提交**：全部新卡按冻结顺序各运行一次并提交完整指标；
4. **P3R4 目标与种子冻结提交**：只在两个必需类别均有合格目标时生成；资格运行计数仍为零；
5. **G3R4 资格证据提交**：第 4 项推送后才运行固定多种子复合算法；
6. **交接提交**：记录结果并停止。

第 3 项若目标集合不足，提交 `TARGET_SUITE_NOT_ADMISSIBLE` 或新协议冻结的等价状态，跳过第 4、5 项并立即交接。

## 9. 保留的 P3R3 修正

以下内容不得无故改写，应由哈希或行为回归约束：

- 中心化无量纲显式对偶见证；
- 唯一 `highs-ds` 后端；
- 独立二维半空间顶点端点复核；
- `CERTIFIER_INTERNAL_INCONSISTENCY` 失败关闭；
- 投影拟 Newton 身份；
- 完整复合残差 Jacobian 多步长审计；
- 物理间隙/有效域 Jacobian、作用—反作用和 P2 只读门。

P3R4 可复制到新命名空间并修正认证层，但不得修改 P3R3 历史包和工件。

## 10. 禁止事项

不得：

- 修改或覆盖 P3/P3R/P3R2/P3R3 历史冻结工件；
- 重跑 P3R3 六张卡；
- 把 `TARGET_SUITE_NOT_ADMISSIBLE` 改成 PASS；
- 把未运行的 G3R3 写成算法 FAIL；
- 依据已观察层差直接放宽 `1.0e-4`；
- 删除 KKT、对偶、临界锥、Jacobian、作用—反作用或 P2 只读门；
- 增加 fallback、随机重启、求解器瀑布、罚刚度、柔顺接触、摩擦、恢复系数或冲量；
- 修改接触活动域、P2 方程或正式目录；
- 开始 P4、P5、P6、动力学、动态接触或正式提升。

## 11. 完成与停止规则

P3R4 无论目标套件不足、G3R4 PASS 还是 G3R4 FAIL，都必须停止在：

`G3R4_PRO_REVIEW`

任何自动门结果都不开放后续阶段。

## 12. 当前验证边界

本次 Pro 复审通过 GitHub 连接器完成提交顺序、合同、指标和关键源码静态复核。没有重新运行仓库所称的 `128 passed`、Ruff、`compileall`、一次性准入器、G3R3 资格工具或历史 PDF 渲染。

本次只更新候选治理和交接文档。正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、数值源码、测试、公共 API、HDF5 和 UI 均不修改。

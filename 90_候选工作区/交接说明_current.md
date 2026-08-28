# 交接说明（current）

更新时间：2026-08-28 16:17 +0900（G3R3 Pro 复审完成，P3R4 已获准）

## 1. 最新裁决

P3R3 冻结分类保持：

`TARGET_SUITE_NOT_ADMISSIBLE`

最新 Pro 裁决为：

`G3R3_PRO_REVIEW_CONFIRMS_P3R3_TARGET_SUITE_NOT_ADMISSIBLE__P3R4_MANIFOLD_ADMISSIBILITY_AND_SOLVER_BASIN_SEPARATION_AUTHORIZED`

P3R3 六张设计卡不得重跑或补选。P3R3 没有冻结资格目标，也没有运行资格种子，因此不存在 G3R3 静态接触算法 PASS 或 FAIL；历史算法裁决仍只有：

- `NO_GO_G3_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`。

P2 无接触静力算法继续为：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

正式总状态继续为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

下一次唯一允许执行：

`P3R4_STATIC_CONTACT_MANIFOLD_ADMISSIBILITY_AND_SOLVER_BASIN_SEPARATION`

完成后必须停止在：

`G3R4_PRO_REVIEW`

## 2. 复审绑定

复审绑定提交：

1. P3R3 预冻结：`8401cfe617720b3532cdafd1249dd0edfbf6d789`；
2. P3R3 实现：`7db0abb7c0a59e7ca568c3f9797ff8edfe9d33d2`；
3. P3R3 准入证据：`214361e2fa946c491a337bc9c30e1d8083daa711`；
4. P3R3 交接：`b729004d5befab082f331982adaed530ae7fe73a`。

关键 SHA-256：

- `p3r3_qualification_targets.json`：`1111a14837cf2e17cdcc630f05e7f56b8b843e117fdfada07137f6df36f86063`；
- `p3r3_admissibility_metrics.json`：`8ad318b0ae579f05af6c4b52450d42ffbc7f0d681bf7bb42e60cb94b60be139f`；
- `P3R3_ADMISSIBILITY_REPORT.md`：`afac89acdf32537af16a904c7320784e1056e51c6ac876266af0a4c4518d88e4`。

完整裁决文件：

`90_候选工作区/current/HF-v2重构规划/12_PRO_G3R3_REVIEW_AND_P3R4_GATE.md`

Codex 执行入口：

`90_候选工作区/current/HF-v2重构规划/00_CODEX_EXECUTION_ENTRY.md`

## 3. 复审关键发现

三段提交链为严格单提交前进，程序性边界成立。六张卡均按冻结顺序运行一次；没有资格种子结果、重试、换算法或事后阈值修改。

主要问题不是 P3R3 结果记错，而是“局部盆地”身份的科学语义不足。当前实现对参考切空间方向直接取：

$$
q_{\pm}=q_0\pm h S d
$$

端点没有收回活动接触约束流形，只检查非活动间隙、有效域、活动行秩和支路方向；随后以固定参考乘子计算拉格朗日量双半径中心差分。这可以审计参考点 Hessian，但不能同时证明有限约束邻域或求解器吸引域。

冻结的统一最大绝对层差门也与稳定裕量脱钩。`ASYM_A01` 主失败方向的两个曲率为 `4.0131767572273365` 和 `4.0140850118115585`，相对差约 `0.0226%`，均远高于 `2.5e-4` 单层正曲率门，却因绝对差 `9.082545842220568e-4` 超过 `1.0e-4` 而失败。这只能维持 P3R3 协议失败，不能解释为参考不稳定。

`ASYM_A03` 另有 `component_scaled_kkt=false`，必须作为独立历史失败保留。

## 4. P3R4 必须完成

P3R4 使用新模型、组装、算法和工件身份，建议从 `0.7-CONTACT-CANDIDATE`、新组装身份和 `ypendulum_hfv2_p3r4` 开始。只允许认证和资格治理修正，不得改变物理模型。

必须分开四层证据：

1. 参考点约束稳定性；
2. 有阶次和误差模型的二阶数值一致性；
3. 可选的活动约束流形有限邻域几何/能量审计；
4. 目标冻结后实际执行的多种子算法吸引证据。

若继续多半径差分，必须在新目标运行前冻结至少三个嵌套步长、Richardson 或等价误差估计，并把不确定度与逐方向正曲率裕量比较。不得依据 P3R3 已观察结果选取刚好放行的阈值。

若宣称有限邻域，必须确定性收回到活动接触和规范约束流形，保存活动间隙残差、秩、支路连续性、非活动正间隙、有效域及收回失败状态。否则取消“盆地证书”称谓，算法吸引域只由实际资格种子结果判定。

## 5. 新目标和提交顺序

P3R3 六张卡及其结果只可作只读诊断/回归，不能重跑、补选、直接充当新目标或用于校准放行阈值。

P3R4 必须预冻结新的未观察卡族，至少覆盖：

- 非镜像对称、两个正乘子不相等；
- 改变几何或载荷尺度。

每类应有冗余候选，全部按固定顺序各运行一次并按预冻结规则选择。

提交顺序至少为：

1. 零结果预冻结；
2. 独立实现，所有新卡仍为零运行；
3. 一次性目标准入；
4. 仅在目标集合完整时冻结目标和种子，资格运行数为零；
5. 目标冻结提交推送后才运行 G3R4 资格；
6. 交接并停止。

若第 3 步目标集合不足，立即提交失败状态并停止，不生成或运行资格种子。

## 6. 必须保持的历史边界

不得修改：

- P3/G3、P3R/G3R、P3R2/G3R2、P3R3 的协议、绑定、卡、目标、种子、报告、指标或哈希；
- P2 势能和广义力；
- 刚性无摩擦单边接触间隙和正式登记活动域；
- 正式 `01_最终理论/**`、`02_模拟程序/**` 和顶层 `AGENTS.md`。

不得增加 fallback、随机重启、求解器瀑布、罚刚度、柔顺接触、摩擦、恢复系数或冲量。P4、P5、P6、动力学、正式提升、公共 API、HDF5、UI、物理验证和实验验证继续关闭。

## 7. 本轮实际验证

本轮通过 GitHub 连接器完成：

- 顶层规范、current 交接、P3R3 协议/清单/源码/测试和指标的静态读取；
- 三段提交的一提交前进比较；
- 关键双半径曲率、对偶证书、临界锥和完整 Jacobian 结果交叉核对；
- 远程提交状态查询。

本轮没有重新运行 `128 passed`、Ruff、`compileall`、一次性准入器、G3R3 资格工具或历史 PDF 渲染。

本轮只修改：

- `90_候选工作区/current/HF-v2重构规划/12_PRO_G3R3_REVIEW_AND_P3R4_GATE.md`；
- `90_候选工作区/current/HF-v2重构规划/00_CODEX_EXECUTION_ENTRY.md`；
- `90_候选工作区/交接说明_current.md`；
- `90_候选工作区/交接说明_history.md`。

正式理论、正式程序、数值源码、测试、公共 API、HDF5 和 UI 均未修改。

# HF-v2 核心重构：Codex 执行入口

## 1. 当前状态

P2 无接触静力算法继续保持：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

历史 P3/G3 裁决继续保持：

`NO_GO_G3_STATIC_CONTACT_ALGORITHM`

P3R/G3R 冻结裁决继续保持：

`NO_GO_G3R_STATIC_CONTACT_ALGORITHM`

Pro 对 G3R 的独立复审裁决为：

`G3R_PRO_REVIEW_CONFIRMS_FROZEN_NO_GO__P3R2_AUTHORIZED`

P3R2 当前执行状态为：

`P3R2_READY_FOR_CODEX_EXECUTION`

正式高保真总状态继续为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

P4、P5、P6、动态接触、正式程序迁移、公共 API、HDF5、UI、装置级物理验证和实验验证全部关闭。

## 2. 开始任务前必须读取

按以下顺序读取：

1. 顶层 `AGENTS.md`；
2. `90_候选工作区/交接说明_current.md`；
3. 本文件；
4. `10_PRO_G3R_REVIEW_AND_P3R2_GATE.md`；
5. `HF-v2-core/contracts/P3R_FROZEN_PROTOCOL.md`；
6. `HF-v2-core/contracts/p3r_acceptance_manifest.json`；
7. `HF-v2-core/reports/G3R_REPORT.md`；
8. `HF-v2-core/reports/g3r_metrics.json`；
9. `HF-v2-core/src/ypendulum_hfv2_p3r/solver.py`；
10. `HF-v2-core/src/ypendulum_hfv2_p3r/kkt.py`；
11. `HF-v2-core/src/ypendulum_hfv2_p3r/evidence.py`；
12. 按需读取 P3R 组装、临界锥、Jacobian、测试和历史 P3/G3 工件。

P3/G3 和 P3R/G3R 全部协议、目标、种子、报告、指标和哈希均为不可变历史证据。不得修改旧文件后把任何历史 NO-GO 改写为 PASS。

## 3. 下一次唯一范围

下一次只执行：

`P3R2_STATIC_CONTACT_NUMERICAL_CERTIFICATION_CORRECTION`

P3R2 只修正静态接触候选生成与独立 KKT 认证之间的闭合，不修改物理接触域、正式登记语义或 P2 方程。

必须使用新的候选模型、接触组装和独立包身份。建议起点为：

- `HFV2-DISCRETE-CORD-RIGID-BOB-0.5-CONTACT-CANDIDATE`；
- `YPS-HFV2-CONTACT-ASSEMBLY-IDENTITY-3.0`；
- `ypendulum_hfv2_p3r2`。

具体版本可以在预冻结提交中提高，但不得复用 `0.4-CONTACT-CANDIDATE`，不得覆盖 `ypendulum_hfv2_p3r`。

## 4. 必须分开的提交边界

Codex 必须至少形成以下三个有序提交：

1. **P3R2 预冻结提交**：只包含新协议、机器清单、模型/组装身份、回归与新目标定义、算法参数、测试身份绑定和源码哈希；此时两个新资格目标运行数必须为零；
2. **P3R2 实现提交**：实现新的独立包、测试和证据生成器，但不得包含新资格目标结果；
3. **G3R2 证据提交**：在前两个提交已进入 Git 历史后，才运行旧回归和两个新资格目标，提交 JSON、原始报告和人类报告。

若实现提交必须包含预目标小型基准结果，机器清单必须明确区分“小型算法基准”和“资格目标”，且资格目标运行数仍须为零。

## 5. P3R2 必须实现的算法闭合

P3R2 可以使用“固定 SLSQP 主阶段 + 固定 KKT 恢复阶段”，但两者必须共同组成一个对每个种子总是执行的单一算法。KKT 恢复不得仅在失败种子上触发，也不得作为备用求解器。

预冻结协议必须完整定义：

- 活动集选择规则和活动集变化的失败关闭政策；
- 已登记附件旋转规范方向的投影或坐标固定；
- 投影 KKT 方程、拉格朗日 Hessian来源和线性系统方法；
- 固定最大迭代数、阻尼/线搜索、步长和终止门；
- 非活动接触间隙及套筒有效域的可行性保护；
- 无法恢复时的确定性失败状态；
- 无 fallback、无随机重启、无罚刚度、无结果驱动阈值放宽。

## 6. 证据必须新增的可观测量

每个种子必须记录 SLSQP 后和 KKT 恢复后的：

- 完整广义站立残差向量及坐标身份；
- 平移力分量，单位 N；
- 转动力矩分量，单位 N·m；
- 预冻结 $L_*$、$F_*$、$E_*=F_*L_*$；
- 无量纲站立残差；
- 最大分量身份、原始值、尺度化值和门限；
- 规范乘子、逐身份对偶区间和 LP 可行性。

当前 P3R 的旧标量门仍必须作为回归门保留：

`stationarity_residual_N <= 1.0e-8`

不得通过删除旧门或只改变单位取得回归 PASS。

## 7. 目标与种子

当前 35° 目标和三个原种子已经被观察，只能作为强制回归。目标、种子和旧 `1e-8` 门保持不变，三个种子必须全部通过。

另须在预冻结提交中定义至少两个尚未运行的新资格目标，每个至少三个确定性种子：

1. 一个非镜像对称双接触平衡，两项接触乘子不同；
2. 一个不同几何或载荷尺度的静态接触平衡，用于检验尺度合同和恢复算法的可迁移性。

两个目标均须有解析或高精度参考、预期接触/支撑身份、乘子、严格有效域裕量和二阶结构。任意一个冻结种子失败，G3R2 必须判为 NO-GO。

## 8. 禁止事项

当前不得：

- 修改或覆盖 P3/P3R 的冻结协议、目标、种子、报告、指标或哈希；
- 把 P3R 的 `2/3` 追溯改写为 PASS；
- 放宽旧 `1e-8` 平衡门、删除反偏种子或把通过数改为 `2/3`；
- 只对失败种子启用精化、追加求解器或增加随机重启；
- 修改接触登记活动域来消除数值失败；
- 增加罚刚度、柔顺接触、摩擦、恢复系数、冲量或动力学；
- 修改 P2 轴向、弯曲、刚体、质量、重力、浮力或无接触静力方程；
- 修改正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、公共 API、HDF5 或 UI；
- 开始 P4、P5 或 P6。

## 9. 完成与停止规则

P3R2 完成后必须生成独立 `G3R2` 证据并停止在：

`G3R2_PRO_REVIEW`

无论 G3R2 自动门结果是 PASS 还是 NO-GO，都不得自行进入 P4、P5、P6、动态接触或正式提升。

完整裁决见：

`90_候选工作区/current/HF-v2重构规划/10_PRO_G3R_REVIEW_AND_P3R2_GATE.md`

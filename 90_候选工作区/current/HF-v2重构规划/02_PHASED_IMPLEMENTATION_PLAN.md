# HF-v2 分阶段实施计划

## 总体策略

HF-v2 与 RC1 并行开发。每一阶段只解决一个层次的问题，并在进入下一阶段前形成可独立否证的门。禁止一次性重写整个程序后再集中调试。

## P0：基线冻结与候选骨架

状态：`COMPLETE`

已记录 RC1 源码身份、公共接口和依赖图，并建立独立候选包。RC1 保持冻结参考和回滚后端，不作为 HF-v2 架构模板。

## P1：纯物理核

状态：`IMPLEMENTATION_TESTS_PASS`

已实现显式拓扑、单边轴向材料、离散曲率弯曲能、质量与外载、`SO(3)` 姿态、偏心连接和局部审计。历史 `0.1` 弯曲方程仅作为历史工件；当前无接触模型身份为 `HFV2-DISCRETE-CORD-RIGID-BOB-0.2-CANDIDATE`。

## G1R：局部模型合同修正

状态：`PRO_REVIEW_PASS`

批准结论：

`G1R_PRO_REVIEW_PASS__LOCAL_MODEL_CONTRACT_ONLY`

完成了折返能垒、参考弧长唯一真值、状态/质量布局绑定、惯量合同和证据自动化修正。

## P2：无接触静态制备

状态：`CONDITIONALLY_QUALIFIED_AFTER_G2R`

批准结论：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

P2 已完成：

- 强绑定拓扑、状态、质量、材料段和广义坐标的静态组装；
- 单边轴向、离散弯曲、重力、浮力和偏心连接总势能；
- 解析广义力和右 Jacobian 转矩映射；
- 唯一 BFGS、三个确定性种子；
- 解析竖直系统和严格正净空 Y 形锚点；
- 2/4/8 三层网格、残差、反力、净空和二阶稳定性审计。

## G2R：G2 复审修正

状态：`PRO_REVIEW_PASS`

批准结论：

`G2R_PRO_REVIEW_PASS__NO_CONTACT_STATIC_ALGORITHM_ONLY`

G2R 已完成：

1. 用单一、字段完备的 SHA-256 身份绑定坐标解释和完整无接触静态物理组装；
2. 增加参考姿态、附件/规定节点身份、支点位置和重力的真实跨组装互拒；
3. 将 BFGS `c1`、`c2` 等全部冻结选项显式传入唯一求解器，未知选项失败关闭；
4. 版本化披露原 G2 模块清单和闭合审计的后验修正，保持历史 G2 工件不变；
5. 增加三支路 129 点完整材料中心线趋势；
6. 增加无量纲应变和伸长诊断；
7. 验证 G2R 与历史 G2 的主要静态观测量等价。

G2R 没有修改物理方程、Y 形锚点、种子、网格、BFGS 方法或既有数值门。

## P3：静态硬接触历史阶段

状态：`HISTORICAL_G3_NO_GO_CONFIRMED_BY_PRO_REVIEW`

P3 在 HF-v2 当前物理核心和静态组装上增加了静态、无摩擦、刚性、单边法向非穿透约束，并完成逐接触 KKT 与二阶证据。接触模型身份为：

`HFV2-DISCRETE-CORD-RIGID-BOB-0.3-CONTACT-CANDIDATE`

冻结目标裁决为：

`NO_GO_G3_STATIC_CONTACT_ALGORITHM`

Pro 独立复审裁决为：

`G3_PRO_REVIEW_CONFIRMS_FROZEN_NO_GO__P3R_REQUIRED`

历史 NO-GO 必须保留，因为冻结目标要求间隙活动身份恰为两项摆球接触且满行秩 `2/2`，实际解析位置必然还具有两项零乘子的上支—下支套筒边界，形成四项间隙活动、活动秩三、两项正乘子支撑和支撑秩二。另两个种子因套筒有效域异常未返回候选，最终为 `0/3` 通过。

该历史结论只否决 `0.3-CONTACT-CANDIDATE` 与冻结 P3 协议，不否决静态刚性接触路线。P3 合同、A1、目标、报告和指标现为不可变历史工件。

## P3R：静态接触协议、有效域和资格数学修正

状态：`COMPLETE_WITH_G3R_NO_GO`

P3R 使用新的身份：

- `HFV2-DISCRETE-CORD-RIGID-BOB-0.4-CONTACT-CANDIDATE`；
- `YPS-HFV2-CONTACT-ASSEMBLY-IDENTITY-2.0`。

P3R 已完成：

1. 自包含正式登记适配合同；
2. 物理间隙与套筒有效域的有身份残差和 Jacobian；
3. 有限不可行状态与真正未定义几何的不同失败政策；
4. 近活动、规范支撑、弱活动、可能支撑、必然支撑和对偶区间；
5. 真实一侧临界锥及独立方向曲率交叉检查；
6. 19 个机器基准身份到唯一 pytest 节点的显式绑定；
7. 历史对称目标的结构回归；
8. 一个预冻结 35° 新资格目标和三个确定性种子。

## G3R：P3R 独立资格门

状态：`NO_GO_CONFIRMED_BY_PRO_REVIEW`

冻结裁决为：

`NO_GO_G3R_STATIC_CONTACT_ALGORITHM`

Pro 独立复审裁决为：

`G3R_PRO_REVIEW_CONFIRMS_FROZEN_NO_GO__P3R2_AUTHORIZED`

五项前置门、旧结构回归、解析种子和正偏种子通过；反偏种子的独立站立残差为 `1.1056080207858155e-8`，超过冻结上限 `1.0e-8`，使新目标为 `2/3`，因此冻结 G3R 必须保持 NO-GO。

其余接触身份、秩、乘子误差、有效域、Jacobian、作用—反作用、P2 只读性和临界锥门均通过。该证据只否决 `0.4-CONTACT-CANDIDATE` 与冻结 G3R 协议，不足以否定静态刚性接触路线。

## P3R2：静态接触数值认证闭合

状态：`COMPLETED_WITH_G3R2_NO_GO_PENDING_PRO_REVIEW`

P3R2 使用新的候选模型、接触组装、尺度合同和独立包身份：

- `HFV2-DISCRETE-CORD-RIGID-BOB-0.5-CONTACT-CANDIDATE`；
- `YPS-HFV2-CONTACT-ASSEMBLY-IDENTITY-3.0`；
- `YPS-HFV2-P3R2-COMPOSITE-SLSQP-KKT-RESTORATION-1.0`；
- `YPS-HFV2-P3R2-COMPONENT-SCALE-1.0`；
- `ypendulum_hfv2_p3r2`。

有序提交为：

1. 预冻结 `227b4472cc33f4c5f70d81185030bb5709f6cfa1`；
2. 实现 `61b107d27db015b71d7b48bad5dd0431367e67f4`；
3. G3R2 证据 `507f403c2c08697d111e286eac88e3126564ff98`。

前两项进入 Git 历史前，两个新资格目标运行数均为零。每个结构回归、35 度回归和新资格种子都执行同一条固定 SLSQP 与总是执行的投影 KKT 恢复路径。P3/P3R 历史工件、35 度目标、三个原种子和旧 `1e-8` 标量门保持不变。

完整分量级站立残差以平移力 N、转动力矩 N·m 和无量纲分量分别报告；独立 NNLS/LP 使用同一尺度合同。没有失败触发的 fallback、随机重启、罚刚度、柔顺接触、摩擦、恢复系数、冲量或结果驱动容差放宽。

历史 35 度三个原种子全部通过；原反偏种子的旧站立残差由 `1.1056080207858129e-8` 恢复至 `9.06677484273175e-13`。

## G3R2：P3R2 独立资格门

状态：`EVIDENCE_COMPLETE__NO_GO_PENDING_PRO_REVIEW`

冻结裁决为：

`NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`

非对称 32/41 度目标和 1.4 倍几何尺度目标均为 `0/3`。两个解析参考都精确满足预登记位置、KKT 和解析乘子，但真实临界锥最小支持曲率分别为 `-4.816125831771666` 和 `-0.0022739949514351543`，因此它们是驻点而不是局部稳定平衡。两个目标的偏置种子均确定性转入其他稳定分支；非对称目标的偏置分支还使尺度化同带 LP 不可行。

G3R2 指标 SHA-256 为：

`b9580859b3eccbaf21ee240b911d2c83354ffe7a88916612f6993efdeab2bfe8`

该证据只否决 `0.5-CONTACT-CANDIDATE` 与冻结 P3R2/G3R2 协议，不否定静态刚性无摩擦接触路线。当前强制停在 `G3R2_PRO_REVIEW`；只有新的 Pro 独立裁决与用户明确授权才能讨论任何后续修正。P4 不因本轮旧回归通过而开放。

## P4：平滑区间动力学

状态：`CLOSED_PENDING_G3R2_PRO_REVIEW`

目标是实现统一隐式中点、群姿态、单一 Newton/线搜索、预冻结步长控制和完整功率账本，并验证二阶时间收敛、保守能量阶数、被动耗散和对称基准动量。

## P5：张紧—松弛活动集

状态：`CLOSED_PENDING_G3R2_PRO_REVIEW`

目标是采用半光滑活动集或等价互补推进，使每个接受步直接满足非负轴力。完成后进入独立 Pro 裁决门。

## P6：动态硬接触

状态：`CLOSED_PENDING_G3R2_PRO_REVIEW`

开启前必须冻结速度/位置互补、冲量律、恢复系数、摩擦、接触集以及能量—动量合同。不得自行使用罚刚度或库默认值。

## P7：外围适配

状态：`AFTER_CORE_QUALIFICATION`

核心通过后接入现有配置、公共 API、结果类型、HDF5、分析和 UI。适配器只转换数据，不复制物理；RC1 与 HF-v2 并行存在。

## P8：性能、三锚点与正式提升

状态：`USER_AND_PRO_REQUIRED`

完成空间/时间加密、模型形态比较和性能剖析后，只有用户明确授权且 Pro 通过审查，才能修改正式 `02_模拟程序/**`。RC1 在代表性验证完成前不得删除。

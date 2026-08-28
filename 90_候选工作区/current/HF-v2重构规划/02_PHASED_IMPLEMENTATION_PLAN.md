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

P2 已完成强绑定静态组装、总势能/解析广义力、唯一 BFGS、三种子、解析竖直系统、正净空 Y 锚点、三层网格和二阶稳定性审计。

## G2R：G2 复审修正

状态：`PRO_REVIEW_PASS`

批准结论：

`G2R_PRO_REVIEW_PASS__NO_CONTACT_STATIC_ALGORITHM_ONLY`

完成完整组装身份、真实跨组装互拒、显式 BFGS 选项、协议偏离版本化、129 点材料中心线和无量纲域诊断。G2R 没有修改物理方程、Y 锚点、种子、网格、BFGS 方法或既有数值门。

## P3：静态硬接触历史阶段

状态：`HISTORICAL_G3_NO_GO_CONFIRMED_BY_PRO_REVIEW`

冻结裁决：

`NO_GO_G3_STATIC_CONTACT_ALGORITHM`

Pro 裁决：

`G3_PRO_REVIEW_CONFIRMS_FROZEN_NO_GO__P3R_REQUIRED`

历史 NO-GO 来自真实弱活动套筒边界与冻结活动集预期不相容，以及两个初始种子有限有效域失败关闭。该结论只否决 `0.3-CONTACT-CANDIDATE` 与冻结 P3 协议。

## P3R：静态接触协议、有效域和资格数学修正

状态：`HISTORICAL_G3R_NO_GO_CONFIRMED_BY_PRO_REVIEW`

冻结裁决：

`NO_GO_G3R_STATIC_CONTACT_ALGORITHM`

Pro 裁决：

`G3R_PRO_REVIEW_CONFIRMS_FROZEN_NO_GO__P3R2_AUTHORIZED`

P3R 建立正式登记适配、有限有效域残差、近活动/支撑/对偶区间语义、真实一侧临界锥、结构回归和 35 度新目标。反偏种子以 `1.1056080207858155e-8` 超过旧 `1.0e-8` 驻定门，使冻结 G3R 为 `2/3`。

## P3R2：静态接触数值认证闭合

状态：`HISTORICAL_G3R2_NO_GO_CONFIRMED_BY_PRO_REVIEW`

P3R2 使用：

- `HFV2-DISCRETE-CORD-RIGID-BOB-0.5-CONTACT-CANDIDATE`；
- `YPS-HFV2-CONTACT-ASSEMBLY-IDENTITY-3.0`；
- `YPS-HFV2-P3R2-COMPOSITE-SLSQP-KKT-RESTORATION-1.0`；
- `YPS-HFV2-P3R2-COMPONENT-SCALE-1.0`；
- `ypendulum_hfv2_p3r2`。

有序提交为预冻结 `227b4472cc33f4c5f70d81185030bb5709f6cfa1`、实现 `61b107d27db015b71d7b48bad5dd0431367e67f4` 和证据 `507f403c2c08697d111e286eac88e3126564ff98`。历史 35 度三个原种子全部通过，反偏种子恢复至 `9.06677484273175e-13`。

## G3R2：P3R2 独立资格门

状态：`NO_GO_CONFIRMED_BY_PRO_REVIEW`

冻结裁决：

`NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`

Pro 裁决：

`G3R2_PRO_REVIEW_CONFIRMS_FROZEN_NO_GO__P3R3_TARGET_ADMISSIBILITY_AND_DUAL_CERTIFICATION_AUTHORIZED`

两个新目标均为 `0/3`，因此冻结 NO-GO 不得改变。但 Pro 复审确认：

1. 非对称 32/41 度和 1.4 倍尺度解析参考的最小临界锥曲率分别为 `-4.816125831771666` 与 `-0.0022739949514351543`，两者都是不稳定驻点；
2. 偏置种子进入正曲率稳定分支，不能据此直接判定复合求解算法失败；
3. 非对称稳定分支存在显式正乘子和远低于允许带的驻定残差，但 LP 报告不可行，构成认证自洽性矛盾；
4. 状态相关规范投影的恢复矩阵未证明包含完整投影导数。

该证据只否决 `0.5-CONTACT-CANDIDATE` 与冻结 P3R2/G3R2 目标套件，不否定静态刚性无摩擦接触路线。

## P3R3：目标准入与对偶认证修正

状态：`READY_FOR_CODEX_EXECUTION`

唯一范围：

`P3R3_STATIC_CONTACT_TARGET_ADMISSIBILITY_AND_DUAL_CERTIFICATION_CORRECTION`

P3R3 必须：

1. 使用 `0.6` 或更高候选身份、新认证/组装身份和独立包；
2. 逐字节保留 P3/P3R/P3R2 全部历史工件；
3. 在资格种子前建立独立 `TARGET_ADMISSIBILITY`，要求正乘子 KKT、严格有效域和真实临界锥正曲率；
4. 把 `TARGET_INVALID` 与算法种子失败分开；
5. 以规范乘子为 LP 显式可行见证，保存逐分量松弛，并用独立方法复核区间；
6. 明确精确 Newton 或拟 Newton，并复核完整复合残差 Jacobian；
7. 冻结至少两个新的、未观察、局部稳定双接触目标，每个至少三个局部盆地内确定性种子；
8. 保持 35 度三个历史种子和旧 `1.0e-8` 回归门；
9. 以预冻结、实现/准入工具、G3R3 证据三个有序提交完成；
10. 完成后停止在 `G3R3_PRO_REVIEW`。

若不足两个参考通过准入，应提交 `TARGET_SUITE_NOT_ADMISSIBLE`，不得强行运行算法资格种子。

## P4：平滑区间动力学

状态：`CLOSED_PENDING_G3R3_PRO_REVIEW`

目标是实现统一隐式中点、群姿态、单一 Newton/线搜索、预冻结步长控制和完整功率账本。P3R3/G3R3 结束前不得开始。

## P5：张紧—松弛活动集

状态：`CLOSED_PENDING_G3R3_PRO_REVIEW`

目标是采用半光滑活动集或等价互补推进，使每个接受步直接满足非负轴力。当前关闭。

## P6：动态硬接触

状态：`CLOSED_PENDING_G3R3_PRO_REVIEW`

开启前必须冻结速度/位置互补、冲量律、恢复系数、摩擦、接触集以及能量—动量合同。不得自行使用罚刚度或库默认值。

## P7：外围适配

状态：`AFTER_CORE_QUALIFICATION`

核心通过后接入现有配置、公共 API、结果类型、HDF5、分析和 UI。适配器只转换数据，不复制物理；RC1 与 HF-v2 并行存在。

## P8：性能、三锚点与正式提升

状态：`USER_AND_PRO_REQUIRED`

完成空间/时间加密、模型形态比较和性能剖析后，只有用户明确授权且 Pro 通过审查，才能修改正式 `02_模拟程序/**`。RC1 在代表性验证完成前不得删除。

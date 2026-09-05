# HF-v2 G3 静态刚性接触证据报告

结论：`NO_GO_G3_STATIC_CONTACT_ALGORITHM`。本轮没有取得 G3 候选资格；正式数值资格仍为 `HF_NUMERICAL_QUALIFICATION_NO_GO`。

## 范围和证据绑定

- 接触模型身份：`HFV2-DISCRETE-CORD-RIGID-BOB-0.3-CONTACT-CANDIDATE`。
- 范围：`static_frictionless_rigid_unilateral_normal_contact_algorithm`。
- 证据 JSON SHA-256：`97522f837822e2108bce9fe117ad5a5007e2d48a859a9b7f389481010072aa62`。
- 正式登记：`FIXED_REST_MATERIAL_SOCKETS_PROJECTIVE_V2`，正式源码只读哈希检查通过。
- 唯一算法为 SciPy SLSQP；未使用兜底求解器、随机重启、容差放宽或新增种子。

## 分门结论

- `contract_and_formal_source_binding`：PASS。
- `exact_runtime`：PASS。
- `small_benchmarks_before_target`：PASS。
- `architecture`：PASS。
- `p2_regression`：PASS。
- `frozen_target`：FAIL。

## 冻结目标的原始结果

目标 `SYMMETRIC_BOB_TWO_CORD_CONTACT_1` 登记了 9 项逐身份约束。要求 3 个冻结种子全部通过，实际完成候选 1 个，通过全部独立门 0 个。

### `seed_00_analytic`

- 执行状态：`COMPLETED`。
- 优化器返回：`success=true`；该字段未作为验收门。
- 摆球位置：`[0.0, 0.0, -0.114]` m；总势能 `-0.1152967967464195` J。
- 间隙活动身份：`['junction:junction:upper_A:upper_A_s000|lower:lower_s000:first_outside', 'junction:junction:upper_B:upper_B_s000|lower:lower_s000:first_outside', 'bob:upper_A:upper_A_s000', 'bob:upper_B:upper_B_s000']`。
- 正乘子支撑身份：`['bob:upper_A:upper_A_s000', 'bob:upper_B:upper_B_s000']`。
- 活动行数/秩：4/3；支撑行数/秩：2/2。
- NNLS 乘子：`[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.2885322548412712, 0.28853225484127115, 0.0]` N。
- 独立门总判定：`FALSE`。

### `seed_01_infeasible_skew`

- 执行状态：`FAIL_CLOSED_CONTACT_GEOMETRY`。
- 失败关闭：`DegenerateContactGeometry`，Junction socket projective opening is invalid.

### `seed_02_feasible_counter_skew`

- 执行状态：`FAIL_CLOSED_CONTACT_GEOMETRY`。
- 失败关闭：`DegenerateContactGeometry`，Bob socket radial monotonicity left its frozen valid domain.

## NO-GO 根因

1. 解析种子命中冻结的对称位置和两个正乘子，但另外两项结点套筒边界间隙也落入活动阈值。因此活动集为 4 行、秩为 3，不满足冻结的活动身份和满行秩门。
2. `seed_01_infeasible_skew` 在初始登记状态触发结点套筒投影开度失败关闭。
3. `seed_02_feasible_counter_skew` 的初始状态可登记，但唯一 SLSQP 路径进入摆球套筒径向单调性失效域并失败关闭。
4. 按预冻结协议，不得根据这些结果修改种子、域、算法或阈值后将重跑包装成同一协议的 PASS。

## 通过但不抬高结论的证据

- 小型接触基准：21 项测试通过。
- P2 无接触回归、历史 G2R 等价观测量和候选架构门通过。
- 解析种子的间隙雅可比、独立 NNLS 平衡、互补、动作—反作用和二阶曲率中，除活动身份/秩外的记录均保留在 JSON；局部门通过不能抵消多种子与活动集失败。

## 结论边界与停止门

本报告只证明当前 P3 静态接触候选按照冻结协议为 NO-GO。它不是装置预测、物理验证或实验验证，也不授权迁移到正式程序。本轮停在 `G3_PRO_REVIEW`，未进入 P4、P5 或 P6。

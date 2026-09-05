# HF-v2 G3R 静态接触算法证据报告

状态：`NO_GO_G3R_STATIC_CONTACT_ALGORITHM`

指标 SHA-256：`4da70615db740ca345ae6032dfabac89a8188ffb374890126a41220ffb765241`

## 1. 结论

P3R 没有通过冻结的 G3R 门。19 个身份绑定前置基准、旧对称结构回归、
新目标解析种子和正偏种子均通过；新目标反偏种子的独立 KKT 平衡残差
超过预冻结上限，因此三种子资格为 `2/3`，整门必须判为 NO-GO。

本报告只评价候选静态、无摩擦、刚性、单边法向接触算法。它不是装置
预测、物理验证或实验验证。正式高保真总状态仍为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

历史 `0.3-CONTACT-CANDIDATE` 的 G3 NO-GO、旧报告、旧指标及其哈希均
保持不变。P3R 使用 `0.4-CONTACT-CANDIDATE` 和新的接触组装身份。

## 2. 门禁结果

- `contract_and_frozen_source_binding`：PASS
- `exact_runtime`：PASS
- `architecture`：PASS
- `benchmark_identity_binding_before_target`：PASS
- `observed_symmetric_regression_before_target`：PASS
- `unobserved_qualification_target`：FAIL

## 3. Pro 指定的旧目标结构回归

旧对称目标只作已观察回归，状态为 `PASS`。证据保留了全部正式登记接触，
没有删除零乘子弱活动行：

- 近活动身份为 4 项，Jacobian 秩为 3；
- 规范正乘子支撑为 2 项摆球—上支接触，支撑秩为 2；
- 两项摆球接触在允许对偶集合中是必然支撑；
- 两项上支—下支弱活动接触具有无上界的可能对偶反力区间；
- 真实一侧临界锥的最小归一化曲率为
  `0.011732535723084955`，独立方向曲率交叉检查通过。

该回归只证明 P3R 正确保留并报告旧目标的退化结构，不用于新资格结论。

## 4. 新资格目标

唯一预冻结新目标 `P3R_SYMMETRIC_35_DEG_TWO_BOB_CONTACT_1` 的状态为
`FAIL`。三个确定性种子均完成同一个 SLSQP 调用：

- `target_seed_00_analytic`：资格 `PASS`；
- `target_seed_01_positive_skew`：资格 `PASS`；
- `target_seed_02_counter_skew`：资格 `FAIL`。

两个合格种子的最大位置展宽为 `9.35469869408195e-10 m`，势能展宽为
`1.3877787807814457e-17 J`。冻结选择规则在合格候选中得到
`target_seed_00_analytic`，但这不消除第三种子的失败。

## 5. 反偏种子的精确失败门

`target_seed_02_counter_skew` 的优化器返回 `success=true`，但优化器成功
标志不属于验收证据。独立审计得到：

- 平衡残差：`1.1056080207858155e-8 N`；
- 冻结平衡上限：`1.0e-8 N`；
- 结果：KKT 平衡门失败；
- 因允许平衡带内不存在非负乘子，对偶区间可行性失败；
- 可能支撑和必然支撑身份门随之失败。

该种子的其余门，包括有限性、原始非穿透、接触身份、活动秩、支撑秩、
位置、乘子误差、严格有效域内部、物理间隙 Jacobian、有效域 Jacobian、
作用—反作用、P2 只读性和真实临界锥，均通过。位置误差仅为
`6.161943134247065e-9 m`，但接近预期位置不能替代冻结 KKT 门。

协议禁止在看到结果后放宽平衡阈值、更换种子、增加重启、追加求解器或
改变选择规则，因此该失败按原样保留。

## 6. 可重复性与停止门

两次独立生成的 `g3r_metrics.json` 字节一致，SHA-256 均为本报告顶部的
`4da70615...5241`。`G3R_REPORT_RAW.md` 保留冻结生成器的逐字节原始报告；
本文件只修正原始报告中缺少列表前空行的 Pandoc 排版，并补充指标 JSON
中已经存在的失败原因，没有改变任何数值、状态或结论。

本轮强制停在：

`G3R_PRO_REVIEW`

不进入 P4、P5 或 P6。未修改正式理论、正式程序、公共 API、HDF5 或 UI。

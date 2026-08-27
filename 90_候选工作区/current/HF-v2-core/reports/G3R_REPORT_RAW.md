# HF-v2 G3R 静态接触算法证据报告

状态：`NO_GO_G3R_STATIC_CONTACT_ALGORITHM`

指标 SHA-256：`4da70615db740ca345ae6032dfabac89a8188ffb374890126a41220ffb765241`

## 1. 结论边界

本报告只评价候选静态、无摩擦、刚性、单边法向接触算法。
它不是装置预测、物理验证或实验验证。正式高保真总状态仍为
`HF_NUMERICAL_QUALIFICATION_NO_GO`。

历史 `0.3-CONTACT-CANDIDATE` 的 G3 NO-GO、旧报告与旧指标保持不变。
P3R 使用 `0.4-CONTACT-CANDIDATE` 和新的接触组装身份。

## 2. 门禁结果

- `contract_and_frozen_source_binding`：PASS
- `exact_runtime`：PASS
- `architecture`：PASS
- `benchmark_identity_binding_before_target`：PASS
- `observed_symmetric_regression_before_target`：PASS
- `unobserved_qualification_target`：FAIL

## 3. Pro 指定的结构回归

旧对称目标只作已观察回归。报告分别保留近活动集合、正乘子支撑集合、
弱活动集合、对偶反力区间和真实临界锥；不删除零乘子接触。

回归状态：`PASS`。

## 4. 新资格目标

目标状态：`FAIL`。
- `target_seed_00_analytic`：执行 `COMPLETED`，资格 `PASS`
- `target_seed_01_positive_skew`：执行 `COMPLETED`，资格 `PASS`
- `target_seed_02_counter_skew`：执行 `COMPLETED`，资格 `FAIL`

多种子位置展宽：`9.35469869408195e-10` m。

多种子势能展宽：`1.3877787807814457e-17` J。

冻结选择规则得到：`target_seed_00_analytic`。

## 5. 停止门

本轮强制停在 `G3R_PRO_REVIEW`。不进入 P4、P5 或 P6。

未修改正式理论、正式程序、公共 API、HDF5 或 UI。

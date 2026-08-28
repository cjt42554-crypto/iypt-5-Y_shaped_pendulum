# HF-v2 G3R2 静态接触数值认证证据报告

状态：`NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`

指标 SHA-256：`b9580859b3eccbaf21ee240b911d2c83354ffe7a88916612f6993efdeab2bfe8`

## 1. 结论边界

本报告只评价候选静态、无摩擦、刚性、单边法向接触算法的数值认证闭合。
它不是装置预测、物理验证或实验验证。正式高保真总状态仍为
`HF_NUMERICAL_QUALIFICATION_NO_GO`。

历史 G3 和 G3R 的冻结 NO-GO、报告、指标与哈希均保持不变。

## 2. 门禁结果

- `contract_commits_and_frozen_source_binding`：PASS
- `exact_runtime`：PASS
- `architecture`：PASS
- `benchmark_identity_binding_before_targets`：PASS
- `observed_symmetric_structure_regression`：PASS
- `observed_P3R_35_degree_three_seed_regression`：PASS
- `two_prefrozen_unobserved_qualification_targets`：FAIL

## 3. 历史结构与 35 度回归

旧对称结构回归状态：
`PASS`。

P3R 35 度三种子回归状态：
`PASS`。

- `target_seed_00_analytic`：执行 `COMPLETED`，资格 `PASS`
- `target_seed_01_positive_skew`：执行 `COMPLETED`，资格 `PASS`
- `target_seed_02_counter_skew`：执行 `COMPLETED`，资格 `PASS`

## 4. 两个新资格目标

### P3R2_ASYMMETRIC_32_41_DEG_TWO_BOB_CONTACT_1

状态：`FAIL`。

- `asym_seed_00_analytic`：执行 `COMPLETED`，资格 `FAIL`
- `asym_seed_01_positive_skew`：执行 `COMPLETED`，资格 `FAIL`
- `asym_seed_02_counter_skew`：执行 `COMPLETED`，资格 `FAIL`

合格种子数：`0/3`。

位置展宽：`POSITIVE_INFINITY` m。

势能展宽：`POSITIVE_INFINITY` J。

### P3R2_SCALED_1P4_35_DEG_TWO_BOB_CONTACT_1

状态：`FAIL`。

- `scale_seed_00_analytic`：执行 `COMPLETED`，资格 `FAIL`
- `scale_seed_01_positive_skew`：执行 `COMPLETED`，资格 `FAIL`
- `scale_seed_02_counter_skew`：执行 `COMPLETED`，资格 `FAIL`

合格种子数：`0/3`。

位置展宽：`POSITIVE_INFINITY` m。

势能展宽：`POSITIVE_INFINITY` J。

## 5. 停止门

本轮强制停在 `G3R2_PRO_REVIEW`。不进入 P4、P5 或 P6。

未修改正式理论、正式程序、公共 API、HDF5 或 UI。

# P3R5 未观察留出目标准入报告

生成时间：2026-08-28T20:14:14+08:00

实现提交：`d751848044cbb805bacbc72f3fa28c1c22d25757`

留出冻结提交：`802bcd00113e163e2c5584edcf8a61930a3cbf6f`

分类状态：`TARGET_SUITE_NOT_ADMISSIBLE`

本报告覆盖固定双活动 KKT 参考、参考稳定性、二阶数值一致性和约束流形有限邻域；不含资格种子运行，不构成正式数值资格、物理验证或实验验证。

| 留出卡 | 类别 | 输入装配 | 参考构造 | 准入 | 二阶 | 流形 | 失败阶段 | 状态 |
|---|---|---:|---:|---:|---:|---:|---|---|
| R5_ASYM_H01 | asymmetric_unequal_positive_multipliers | 1 | 1 | 1 | 1 | 1 | - | ADMISSIBLE |
| R5_ASYM_H02 | asymmetric_unequal_positive_multipliers | 1 | 1 | 1 | 1 | 1 | - | ADMISSIBLE |
| R5_ASYM_H03 | asymmetric_unequal_positive_multipliers | 1 | 1 | 1 | 1 | 1 | - | ADMISSIBLE |
| R5_ASYM_H04 | asymmetric_unequal_positive_multipliers | 1 | 1 | 1 | 1 | 1 | - | ADMISSIBLE |
| R5_SCALE_H01 | changed_geometry_and_load_scale | 1 | 1 | 1 | 1 | 1 | - | TARGET_INVALID |
| R5_SCALE_H02 | changed_geometry_and_load_scale | 1 | 1 | 1 | 1 | 1 | - | TARGET_INVALID |
| R5_SCALE_H03 | changed_geometry_and_load_scale | 1 | 1 | 1 | 1 | 1 | - | TARGET_INVALID |
| R5_SCALE_H04 | changed_geometry_and_load_scale | 1 | 1 | 1 | 1 | 1 | - | TARGET_INVALID |

## 选择结果

- 未形成完整目标套件，不得冻结或运行资格种子。

一次性账本 SHA-256：`f87c5aa3675ea792c2cbc6e24ae3b2daca8abdd4a7900a31f01de848316fd66c`。

资格种子结果运行数：`0`。

正式高保真数值资格保持：`HF_NUMERICAL_QUALIFICATION_NO_GO`。

最终停止门：`G3R5_PRO_REVIEW`。

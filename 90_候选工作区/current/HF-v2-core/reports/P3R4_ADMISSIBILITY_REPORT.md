# P3R4 目标准入报告

生成时间：2026-08-28T16:58:49+08:00

实现提交：`964ebb3f8ff942a1a75a99c9bb1510d6c016f129`

分类状态：`TARGET_SUITE_NOT_ADMISSIBLE`

本报告只覆盖参考点约束稳定性、二阶数值一致性和约束流形有限邻域；不含资格种子运行，不构成正式数值资格、物理验证或实验验证。

| 设计卡 | 类别 | 输入装配 | 参考运行 | 准入运行 | 二阶审计 | 流形审计 | 失败阶段 | 状态 |
|---|---|---:|---:|---:|---:|---:|---|---|
| R4_ASYM_B01 | asymmetric_unequal_positive_multipliers | 1 | 1 | 0 | 0 | 0 | REFERENCE_DISCOVERY | TARGET_INVALID |
| R4_ASYM_B02 | asymmetric_unequal_positive_multipliers | 1 | 0 | 0 | 0 | 0 | INPUT_ASSEMBLY_VALIDATION | TARGET_INVALID |
| R4_ASYM_B03 | asymmetric_unequal_positive_multipliers | 1 | 1 | 1 | 1 | 1 | - | TARGET_INVALID |
| R4_ASYM_B04 | asymmetric_unequal_positive_multipliers | 1 | 1 | 0 | 0 | 0 | REFERENCE_DISCOVERY | TARGET_INVALID |
| R4_SCALE_T01 | changed_geometry_and_load_scale | 1 | 1 | 1 | 1 | 1 | - | ADMISSIBLE |
| R4_SCALE_T02 | changed_geometry_and_load_scale | 1 | 1 | 1 | 1 | 1 | - | ADMISSIBLE |
| R4_SCALE_T03 | changed_geometry_and_load_scale | 1 | 1 | 1 | 1 | 1 | - | ADMISSIBLE |
| R4_SCALE_T04 | changed_geometry_and_load_scale | 1 | 1 | 1 | 1 | 1 | - | ADMISSIBLE |

## 选择结果

- `changed_geometry_and_load_scale`：`R4_SCALE_T01`

目标与算法初值尚未冻结；必须先提交本准入结果。

资格种子结果运行数：`0`。

正式高保真数值资格保持：`HF_NUMERICAL_QUALIFICATION_NO_GO`。

最终停止门仍为：`G3R4_PRO_REVIEW`。

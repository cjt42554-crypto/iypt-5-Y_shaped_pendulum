# 参数—图样图谱正式化迁移稿

## 1. 身份与结论边界

本目录是 `F0_FORMAL_CONSOLIDATION_AND_ANALYTIC_STABILITY_MAP` 的候选迁移稿，不是正式目录中的已提升程序。

图谱身份为：

`YPS-IDEAL-TORUS-PATTERN-ATLAS-DRAFT-1.0`

所有结果轨迹均调用正式前向求解器中的 `FWD-TORUS-1.0` 后端。迁移稿不保存第二套环面方程，也不自行调用另一个 ODE 积分器。数值调谐的解释被固定为：

`ideal_model_internal_not_experimental_calibration`

因此，本程序只能支持理想、对称、无质量、不可伸长且始终张紧的环面模型内部图谱，不能给出真实装置校准、连续柔索验证、高保真资格或实验验证。

## 2. 与旧候选脚本的差异

旧 `无实验参数图谱/pattern_atlas.py` 同时携带环面方程、积分器、常量扫描矩阵和无 schema 输出。此迁移稿将它们拆分为：

- `configs/atlas_v1.json`：目标比、振幅、观察窗、容差和数值设置；
- `schemas/atlas_output.schema.json`：确定性 JSON 输出合同；
- `src/y_pendulum_pattern_atlas/backend.py`：只负责绑定正式环面后端及其 SHA-256；
- `src/y_pendulum_pattern_atlas/atlas.py`：相位拟合、调谐、闭合诊断、图表和确定性工件；
- `tests/test_atlas.py`：正式后端身份、无重复 ODE、纯模态周期、能量、步长、张紧守卫、schema 和字节确定性检查。

输出中不写运行时钟时间。相同源码、配置、正式后端和运行环境应生成字节相同的 JSON、CSV、SVG、PNG 与工件清单。

## 3. 运行

在本目录执行：

```bash
python -m y_pendulum_pattern_atlas \
  --config configs/atlas_v1.json \
  --output outputs/full \
  --repository-root ../../../..
```

快速子集使用 `--smoke`。安装前也可通过设置 `PYTHONPATH=src` 运行。

## 4. 验证层级

测试和图谱复算属于实现级测试与理想模型数值验证。它们不覆盖：

- 连续柔索或离散杆动力学；
- RC1 或 HF-v2 高保真数值资格；
- 静态或动态接触；
- 装置参数定值；
- 实验验证。

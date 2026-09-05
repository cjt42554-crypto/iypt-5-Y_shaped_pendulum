# 参数—图样图谱正式化迁移稿

## 1. 身份与结论边界

本目录是 `F0_FORMAL_CONSOLIDATION_AND_ANALYTIC_STABILITY_MAP` 的候选迁移稿，不是正式目录中的已提升程序。

图谱身份为：

`YPS-IDEAL-TORUS-PATTERN-ATLAS-DRAFT-1.1`

所有结果轨迹均调用正式前向求解器中的 `FWD-TORUS-1.0` 后端。迁移稿不保存第二套环面方程，也不自行调用另一个 ODE 积分器。数值调谐的解释被固定为：

`ideal_model_internal_not_experimental_calibration`

因此，本程序只能支持理想、对称、无质量、不可伸长且始终张紧的环面模型内部图谱，不能给出真实装置校准、连续柔索验证、高保真资格或实验验证。

## 2. 与旧候选脚本的差异

旧 `无实验参数图谱/pattern_atlas.py` 同时携带环面方程、积分器、常量扫描矩阵和无 schema 输出。此迁移稿将它们拆分为：

- `configs/atlas_v1.json`：目标比、振幅、观察窗、容差和数值设置；
- `schemas/atlas_config.schema.json`：从顶层到每个嵌套对象均关闭的严格输入合同，不接受字符串或小数型 $p,q$；
- `schemas/atlas_output.schema.json`：覆盖全部结果字段且逐层关闭的确定性输出合同；
- `schemas/atlas_run_evidence.schema.json`：运行证据、优化器状态和诊断合同；
- `contracts/source_manifest_lock.json`：绑定正式理论、正式 contracts、正式 torus 后端、全部候选生产源码、配置、schema、构建元数据和运行时身份；
- `src/y_pendulum_pattern_atlas/backend.py`：只负责绑定正式环面后端及其 SHA-256，并在导入后逐字恢复 `sys.path`；
- `src/y_pendulum_pattern_atlas/atlas.py`：相位拟合、调谐、闭合诊断、图表和确定性工件；
- `outputs/full/atlas_run_evidence.json`：16 个图谱案例、48 条主结果轨迹、优化器状态、阈值、运行时和完整源清单；
- `outputs/full_repeat_verification.json`：三次全量运行的 9 个工件逐字节一致性、schema 和语义计数核验；
- `tests/test_atlas.py`：正式后端身份、无重复 ODE、纯模态周期、能量、步长、张紧守卫、严格 schema、故意源漂移、运行时漂移、`sys.path` 污染和字节确定性检查。

输出中不写运行时钟时间。相同源码、配置、正式后端和锁定运行环境应生成字节相同的 JSON、CSV、SVG、PNG、运行证据与工件清单。任一绑定文件、绑定文件集合或运行时身份变化都会在结果运行前 fail closed。

## 3. 运行

在本目录执行：

```bash
python -m y_pendulum_pattern_atlas \
  --config configs/atlas_v1.json \
  --output outputs/full \
  --repository-root ../../../..
```

快速子集使用 `--smoke`。安装前也可通过设置 `PYTHONPATH=src` 运行。

源锁只能在候选源码、配置或 schema 经审查后显式重建：

```bash
PYTHONPATH=src python tools/generate_source_manifest_lock.py
PYTHONPATH=src python tools/generate_source_manifest_lock.py --check
```

全量复算完成后，可对至少两份独立输出执行：

```bash
python tools/verify_full_repeats.py \
  /path/to/repeat-1 /path/to/repeat-2 /path/to/repeat-3 \
  --project-root . \
  --output outputs/full_repeat_verification.json
```

F0R 交付证据使用三次独立全量运行；每次均覆盖 16 个案例和 48 条主结果轨迹。九个 JSON、CSV、SVG、PNG 及工件清单文件在三次运行间逐字节相同。

## 4. 验证层级

测试和图谱复算属于实现级测试与理想模型数值验证。它们不覆盖：

- 连续柔索或离散杆动力学；
- RC1 或 HF-v2 高保真数值资格；
- 静态或动态接触；
- 装置参数定值；
- 实验验证。

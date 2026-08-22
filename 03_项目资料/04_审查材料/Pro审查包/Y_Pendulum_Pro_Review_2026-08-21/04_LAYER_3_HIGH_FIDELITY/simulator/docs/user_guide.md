# 用户手册

> 本手册的主线是当前第 3 层独立模型
> `HF-DISCRETE-ROD-RIGID-BOB-1.0`。软件定位为个人科研计算工具和可修改原型，
> 不是发布级平台。旧 `full`/H1 路径仍可用于兼容回归，但不能充当独立高保真证据。

## 1. 推荐工作流

1. 用 A0/A1 或冻结的第 2 层前向程序设计几何、释放状态和目标时间窗；它们是辅助层，不是本层状态推进器。
2. 独立测量三支材料长度、直径、线密度、轴向刚度/黏性、摆球质量/半径、连接偏心和环境参数。
3. 从 `configs/examples/high_fidelity_shared_forward_window.yaml` 复制个人算例，并运行 `ypendulum validate-config CONFIG`。
4. 先把 `t_end` 临时缩成 1--2 ms 做资源与守卫探针；不得用短窗结果冒充目标全窗。
5. 用 `scripts/run_representative_hf_sensitivity.py` 比较目标时间步、两倍时间步和一个代表性粗网格。
6. 冻结目标 YAML 后以 8--12 个后处理 worker 运行完整时间窗，保留默认积分 checkpoint，并检查状态、有符号轴力、非负张力、能量账、11 个守卫和事件。
7. 只有需要更严格的数值研究时才运行完整 `hf-validate` 六候选矩阵；它不是个人目标计算的发布前置条件。
8. 若有实验数据，再冻结对齐规则并运行 `compare-experiment`；没有实验时明确写“未做实验验证”。

## 2. 安装

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

UI：

```bash
python -m pip install -e '.[ui]'
ypendulum ui
```

## 3. 配置要点

所有物理量推荐使用 `{value, unit, source, uncertainty}`。`rest_length` 是材料自然长度，不是加载后的端点弦长。当前正式 HF 采用被动单边/双边 Kelvin--Voigt 凸组合，并在普通 HF 算例中取
`compression_regularization_scale: 1.0`，即有限压缩刚度的双边离散杆。程序分别输出有符号轴力与非负张力，不能把压缩写成“负张力”。

旧 H1 表格本构只用于历史兼容；若仍需使用，应写入标定试样长度：

```yaml
material_model: tabulated_tension_extension
table_file: material_curve.csv
table_calibration_length: {value: 0.500, unit: m, source: calibrated_independent}
```

材料表固定列名：`extension,tension`，单位分别为 m、N，且从 `(0,0)` 开始、加载支路单调。若存在明显滞回，单值表格不适用。

## 4. 常用命令

```bash
ypendulum validate-config CONFIG
ypendulum diagnose CONFIG --output diagnosis.json
YPS_HF_POSTPROCESS_WORKERS=12 ypendulum simulate CONFIG
ypendulum analyze RUN_DIRECTORY
ypendulum compare RUN_A RUN_B
python scripts/run_representative_hf_sensitivity.py \
  --config configs/examples/high_fidelity_shared_forward_window.yaml \
  --window-s 0.01 \
  --output validation/representative_hf_sensitivity.json \
  --series-output validation/representative_hf_sensitivity_series.npz
```

`ypendulum equilibrate`、`modes`、`converge`、`ablate`、`sweep` 和
`uncertainty` 仍可用于其已登记模式，但不要把旧 H1 的成功状态外推为当前独立 HF 的成功状态。完整 HF 矩阵使用：

```bash
ypendulum hf-validate \
  configs/examples/high_fidelity_shared_forward_window.yaml \
  configs/high_fidelity_shared_forward_validation.yaml \
  --output /tmp/yps-hf-validation-fresh
```

独立轴向标定：

```bash
ypendulum calibrate-axial axial.csv \
  --rest-length 0.500 \
  --output axial_fit.json \
  --table-output material_curve.csv
```

输入列默认 `force_N,extension_m`。程序报告 \(EA\)、普通最小二乘标准误差和 95% 区间；系统误差仍需单独传播。

阻尼包络诊断：

```bash
ypendulum calibrate-damping damping.csv --output damping_fit.json
```

输入列默认 `time_s,amplitude_m`。它只在指数与反比例包络之间做诊断，不证明唯一耗散机制。

实验比较：

```bash
ypendulum compare-experiment runs/test trajectory.csv \
  --output-directory comparison
```

默认不拟合任何对齐参数。可显式启用有限时间平移、平面平移和旋转，但这些 nuisance 参数必须在验证集揭示前冻结。

HF 顶层运行默认在目标目录旁保存积分 checkpoint。也可显式指定：

```bash
YPS_HF_POSTPROCESS_WORKERS=12 \
ypendulum simulate CONFIG --hf-checkpoint /data/run.integration.npz
```

若积分已完成而后处理失败，或只修改了后处理实现，则换用新的输出目录并回放：

```bash
YPS_HF_POSTPROCESS_WORKERS=12 \
ypendulum simulate CONFIG \
  --hf-checkpoint /data/run.integration.npz \
  --resume-hf-checkpoint
```

checkpoint 必须与解析后的配置、模型身份、状态尺寸和展示时标一致。它不是跨理论
版本自动迁移器；理论或状态语义变化时必须重新积分。

## 5. 当前 HF 初始条件

- `held_endpoint_equilibrium_release`：固定用户给定的结点、摆球质心和刚体连接端，只优化三支内部材料珠；通过稳定性检查后同时释放。这是共享目标算例采用的协议。
- `geometric_direct_release`：在三支端点弦长均不短于材料自然长度时按直线材料坐标构造非平衡释放；若弦长短于自然长度则失败关闭，不能凭空吞掉多余材料长度。

旧 `static_equilibrium`、`reduced_angles_release`、`cartesian_release`、`direct_state` 和 `restart` 属 A0/A1/H1 路径，不是当前 HF 隐式别名。瞬间解除夹持可能真实激发纵波；这不是自动数值错误。释放装置若有有限加速度历程，应显式建模为规定支点或外力。

## 6. 诊断解释

`diagnose` 分别给出：

- 相位预算要求的频率精度；
- 有限振幅、结点/绳质量、轴向伸长、绳波、气动和支点运动量级；
- 松绳角裕量；
- 输出样本/周期和观测周期数；
- 内部步长、输出采样对纵波与重新受拉峰值的解析能力；
- 参数来源缺口；
- 当前配置最多支持的科学声明等级。

“低频轨迹可用”不等于“张力峰可用”。后者需要 `resolve_longitudinal_waves: true`、更小内部步长、更密输出以及专门的网格/时间收敛。

## 7. 结果目录

当前 HF 的 `result.h5` 保存：

- 展示时刻和自适应接受步时刻；
- 全部材料珠、有限质量结点和刚体摆球的平动状态；
- 摆球四元数、角速度和偏心连接点；
- `/cables/<branch>/segments/signed_axial_force`（压缩为负）；
- `/cables/<branch>/segments/tension`（只取非负拉伸部分，用于张力状态事件）；
- 机械能、轴向/气动耗散、气流功、支点功和第一律残差；
- 支点反力、11 个逐分量守卫、事件与接受步证书。

所有 HDF5 科学数据集均带单位和说明；汇总另见 `summary.json`、`diagnostics.json`、`events.json` 和 `report.md`。无根原始轨迹保守返回
`UNDETERMINED / SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED`，表示尚未由独立连续检查升级，不等于求解器失败。

个人科研模式下，`analyze`、`compare` 和 `compare-experiment` 可以直接读取这类
原始结果；它们会把原始状态与“未做连续守卫认证”的解释写进报告。只有显式提供
验证规格时才产生可选证书旁文件。

## 8. 性能选择

- 默认 `auto` 在至少 64 个样本时取不超过 12 个物理核心；更短探针直接串行。
- 目标机器独占时推荐 12 worker；与其他重负载程序共用时推荐 8 worker。
- 完整 15,361 样本后处理实测：1/8/12 worker 分别为
  191.07/29.10/20.81 s，12 worker 为 9.18×，平均占用 11.91 个等效核心，
  峰值进程树内存约 507 MB。
- 当前模拟器不使用 GPU。日志中的整机 GPU 百分比可能来自桌面，不应写成模拟
  加速。只有 CPU 批处理不再满足需求时，才单独评估批量线段对 GPU 核。
- 详细端到端、积分、后处理、内存和等价性数据见
  `docs/performance_optimization.md`。

## 9. 科学声明

- `DERIVED`：方程/配置已形成，但未完成目标数值检查。
- `VERIFIED`：核心实现回归、目标运行和约定的数值敏感性获得支持；不自动等于实验正确。
- `CALIBRATED`：关键参数由独立实验得到。
- `VALIDATED`：冻结模型在独立实验验证数据上通过预先声明的指标。
- `PREDICTIVE`：进一步通过未参与建模选择的几何或释放条件。

本个人研究交付只在证据允许的层级陈述。没有独立实验数据时，不使用
`VALIDATED/PREDICTIVE`；软件状态字符串也不能替代科研判断。

# Python API

## 核心入口

```python
from ypendulum import (
    load_config,
    diagnose_config,
    solve_static_equilibrium,
    simulate,
    analyze_run,
    analyze_linear_modes,
    compare_experiment,
    run_convergence_study,
)
from ypendulum.hf import (
    HighFidelityModel,
    HighFidelityResult,
    prepare_initial_state,
    simulate_high_fidelity,
    certify_single_hf_bundle,
    run_hf_validation,
)
```

### `load_config(path_or_mapping)`

解析 YAML/字典、绳配置继承、单位和物理一致性。返回 `SimulationConfig`。相对材料表、支点轨迹、重启文件和验证清单路径相对于配置文件解析。

### `diagnose_config(config, solve_equilibrium=True, write_output=None)`

不积分动力学。返回量级、范围、观测可辨识性、数值解析能力、参数来源和声明上限。部分诊断来自旧 A0/A1/H1 路径；它们不能替代当前 HF 的 held 初态制备、守卫或目标实跑。

### `solve_static_equilibrium(config, model=None)`

旧 H1 接口，返回 `StaticEquilibrium`：加载位置、速度、最大自由节点力残差、迭代数和局部稳定性特征值审计。当前 HF 使用 `prepare_initial_state`。

### `simulate(config, equilibrium=None, hf_validation_spec=None, hf_checkpoint_path=None, hf_resume_checkpoint=False, write_output=True)`

按 `run.mode` 返回：

- A0：`AnalyticPrediction`
- A1：`TorusResult`
- `full` / H1：`SimulationResult`（历史兼容）
- `high_fidelity`：`HighFidelityResult`

HF 结果包含展示网格和接受步状态、材料珠/结点/刚体运动、有符号轴力、非负张力、11 个守卫、能量、反力、事件、诊断和明确的物理/数值状态。`hf_validation_spec` 只在确实需要完整独立数值证书时传入；个人目标实跑可以省略，并保留原始保守状态。

HF 顶层写盘运行在未显式指定时把积分 checkpoint 放在目标目录旁。
`hf_checkpoint_path` 可指定其他位置；`hf_resume_checkpoint=True` 会验证配置、
状态尺寸、展示时间和数组摘要，然后跳过积分、只重做后处理。`write_output=False`
不会隐式创建 checkpoint，除非调用方明确给出路径。

### `analyze_linear_modes(config, count=2)`

旧 H1 中由同一静力切线和质量矩阵求小振动广义特征值，并报告摆球动能参与率、方向和结点/摆球位移比。它不是当前 HF 的有限振幅频率。

### `analyze_run(run_directory)`

从已保存运行重新提取主频、可靠性、相位漂移、闭合误差和能量指标。记录不足三个周期或存在结构切换时不会伪报稳定双主频。

个人科研模式允许分析原始 HF 保守状态；返回值同时包含原始状态和
`result_interpretation`。若存在且通过可选独立证书，则另外报告升级后的状态；
无证书时不会把 `UNDETERMINED` 改写成成功。

### `compare_experiment(...)`

将冻结运行与 `time,x,y,z` 或 `time,u_pixel,v_pixel` CSV 作前向比较。默认无对齐拟合；显式启用的时间平移、平移和旋转会列入报告。

原始 HF 轨迹可直接进入个人研究比较，但报告中的 `prediction_qualification`
会保留原始物理/数值状态；求解失败或数值未决轨迹仍被拒绝。

### `run_convergence_study(config)`

旧 H1 数值研究入口。当前 HF 的严格矩阵入口是
`ypendulum.hf.run_hf_validation(config, validation_spec)`；个人科研最低检查可使用
`scripts/run_representative_hf_sensitivity.py`，它输出原始时间步和网格差异而不自动升级资格。

## 当前 HF 低层 API

### `HighFidelityModel(config)`

装配独立离散杆、有限质量结点、有限刚体摆球、偏心连接、弯曲、气动与固定材料接触守卫。它不调用旧 H1 的 `FullCableModel` 作为状态推进器。

### `prepare_initial_state(config, model)`

执行 `geometric_direct_release` 或 `held_endpoint_equilibrium_release`，返回 `PreparationResult`。held 模式的审计包含自由材料珠力残差、稳定种子和 Hessian 稳定性信息。

### `simulate_high_fidelity(config, model=None, preparation=None, checkpoint_path=None, resume_from_checkpoint=False)`

只进行内存计算并返回 `HighFidelityResult`，适合短探针和敏感性工具。它不建立标准运行目录；需要 HDF5、JSON、图和观察量时使用顶层 `simulate`。

若给出 `checkpoint_path`，积分完成后先保存 accepted/presentation 时间与状态，
再计算有符号轴力、张力、能量、守卫和事件。回放时积分墙钟为 0，后处理仍按
固定索引顺序生成同一结果。

### `certify_single_hf_bundle(...)`

对已有内存结果做只读独立复核。无完整验证规格时最多给出实际目标所需的守卫域证据，不会把原始结果对象重标为完成。个人科研工作流不要求为了取得一个状态字符串而运行完整六候选矩阵。

## 材料标定 API

```python
from ypendulum.calibration import (
    fit_axial_stiffness,
    build_tabulated_tension_extension,
    compare_envelope_models,
)
```

标定函数只接受 SI 数组。任何系统性仪器误差和数据分组策略由调用方显式管理。

## 低层接口

当前 HF 的
`HighFidelityModel.evaluate(t, particle_positions, particle_velocities, bob_position, bob_velocity, quaternion, angular_velocity, ...)`
返回独立 Newton--Euler 离散杆评估，包括有符号轴力、非负张力、弯曲、气动、刚体力矩、能量和逐分量守卫所需几何量。旧
`FullCableModel.evaluate(...)` 仅服务 H1 兼容路径。低层接口可能随理论修改演化；可复现实跑优先使用配置驱动的 `simulate`。

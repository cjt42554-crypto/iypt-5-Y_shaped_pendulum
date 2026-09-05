# RC1 入口、依赖与输出基线

绑定提交：`de37ff2293ab3d92beb8876dbea312224fa27e90`。

## 入口和依赖方向

```text
ypendulum.api
  -> ypendulum.hf.__init__
       -> certificate_io
       -> independence
       -> model
       -> solver
       -> state
       -> validation

model
  -> config.models + config.units + geometry.supports
  -> NumPy + SciPy sparse

solver
  -> config hashing + config models + config validation
  -> model + state
  -> SciPy integrate/optimize/sparse.linalg
  -> checkpoint/hash/filesystem + CPU/process/thread presentation work

validation
  -> model + solver + state
  -> qualification, certificates and independent audit calculations

io.hdf5
  -> state.HighFidelityResult
```

`api.py` 根据运行模式构造 `HighFidelityModel`，调用 `simulate_high_fidelity`，再把 `HighFidelityResult` 交给分析、HDF5、图形、报告和证书路径。`hf.__init__` 同时重新导出物理模型、求解、结果、资格验证、独立性研究和证书 I/O，因此 RC1 的公共 HF 命名空间不是纯物理边界。

## P0/P1 拆分裁决

- 只逐方程核对 `model.py` 的局部轴向、三点弯曲和刚体连接几何，不复制 `HighFidelityModel` 单体。
- 不复制 `solver.py` 的静态制备、积分器选择、检查点、并行呈现或结果装配。
- 不让 `validation.py`、HDF5、分析、哈希、报告或 UI 被候选物理模块导入。
- P0/P1 不生成 `HighFidelityResult`；公共适配延后到 P7。
- RC1 轨迹不是 HF-v2 真值。P0 表征只冻结输入和可否证不变量。

完整 blob 身份见 `baseline_sources.json`，公共字段与状态词汇见 `rc1_public_interface.json`。

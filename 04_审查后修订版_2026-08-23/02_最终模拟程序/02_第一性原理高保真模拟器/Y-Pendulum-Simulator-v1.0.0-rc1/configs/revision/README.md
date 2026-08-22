# 修订模型配置

`hf-bilateral-explicit-ei-baseline.yaml` 只把旧后端隐含的几何 `EI=Eπd⁴/64` 显式写出，便于消融和审计。它不是实验标定结果。

正式实验预测应复制 `hf-measured-ei.template.yaml`，填入三支分别测得的弯曲刚度，并保留原始标定数据、拟合区间、频率、振幅和温度条件。

运行示例：

```bash
PYTHONPATH=src python -m ypendulum.scientific_revision run-hf \
  --config configs/examples/high_fidelity_shared_forward_window.yaml \
  --overlay configs/revision/hf-bilateral-explicit-ei-baseline.yaml \
  --output runs/revision/hf-explicit-ei
```

构造模型阶梯：

```bash
PYTHONPATH=src python -m ypendulum.scientific_revision build-ablation \
  --measured-overlay configs/revision/hf-bilateral-explicit-ei-baseline.yaml \
  --output runs/revision/ablation-overlays
```

GUI 使用：启动审查后修订 GUI 后，在左侧顶部选择 overlay。overlay 的路径、SHA-256、模型身份、压缩权重和三支 EI 会写入运行结果；运行期间文件变化会导致任务失败，而不是静默使用新内容。

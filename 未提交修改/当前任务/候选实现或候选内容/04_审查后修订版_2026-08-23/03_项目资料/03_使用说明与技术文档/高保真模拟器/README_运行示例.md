# 可复现示例与轻量级参考输出

`configs/examples/` 保存输入配置；`examples/reference_outputs/` 保存由当前 `1.0.0rc1` 代码实际生成的轻量级审计结果。完整 HDF5 运行文件没有复制进发布示例，以控制体积；它们可通过下列命令重新生成。

```bash
ypendulum simulate configs/examples/analytic_3to2.yaml
ypendulum simulate configs/examples/ideal_3to2.yaml
ypendulum simulate configs/examples/full_quick_3to2.yaml
ypendulum simulate configs/examples/full_quick_newmark_3to2.yaml
ypendulum simulate configs/examples/camera_projection.yaml
```

示例覆盖：

- `analytic_3to2`：A0 解析极限；
- `ideal_3to2`：A1 精确环面 ODE；
- `full_quick_3to2`：Radau-H1 三维有限质量柔索；
- `full_quick_newmark_3to2`：二阶稀疏 Newmark 交叉求解；
- `camera_projection`：针孔相机、畸变、采样与曝光前向模型；
- `calibration`：独立轴向加载与振幅包络标定的合成数据；
- `experiment_comparison`：已知时间偏移、坐标平移和固定平面旋转的合成前向比较。

合成实验比较只验证数据管线和 nuisance 参数的可恢复性，不构成真实实验 `VALIDATED` 或 `PREDICTIVE` 证据。

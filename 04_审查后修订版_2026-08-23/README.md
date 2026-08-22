# Y 形摆审查后修订版（2026-08-23）

本目录是仓库原项目的完整独立副本，并叠加审查后修订层。仓库根目录下原有 `01_最终理论`、`02_最终模拟程序` 和 `03_项目资料` 未作修改。

## 当前科学状态

```text
MODEL_CONSISTENT
CODE_VERIFIED for inherited frozen scopes
NOT YET NUMERICALLY QUALIFIED for all event-rich target cases
NOT EXPERIMENTALLY VALIDATED
NOT PREDICTIVE
```

## 本次实际修改

1. 将前向仅受拉柔索、双边柔性杆、仅受拉受控极限和理想环面拆成不同模型身份；
2. 三支弯曲刚度改为可独立输入的 `EI_A, EI_B, EI_lower`；
3. 新增 M0--M5 消融生成器，不再以“让完整后端强行一致”为目标；
4. 新增事件工况空间、时间、求解器和输出带宽资格工具；
5. 新增带科学护栏的 GUI 与修订子进程：
   - GUI 可选择一份带来源记录的显式各支路 EI overlay；
   - HF 任务实际由修订 runner 执行，不只是改显示标签；
   - HF 明确标为双边柔性杆；
   - 压缩或显著弯曲时自动显示原始材料路径；
   - 有限记录 FFT 永远只标为预览；
6. 新增结构性证据审计，禁止由有限窗闭合直接推出锁频、不变环面或连续参数域定理；
7. 新增材料、连接、支架、相机的独立标定与留出验证协议。

## 入口

进入高保真模拟器目录：

```bash
cd '02_最终模拟程序/02_第一性原理高保真模拟器/Y-Pendulum-Simulator-v1.0.0-rc1'
```

启动修订 GUI：

```bash
./启动Y形摆审查后修订版.sh
```

GUI 顶部的“科学修订模型身份 / 独立 EI”区域用于选择 overlay。每次提交都会把 overlay 路径和 SHA-256 封存到运行请求中；子进程会在运行前重新校验哈希。默认 baseline 只是把旧隐式几何 EI 显式化，不代表独立测量。

查看修订工具：

```bash
PYTHONPATH=src python -m ypendulum.scientific_revision --help
```

显式独立 EI 运行：

```bash
PYTHONPATH=src python -m ypendulum.scientific_revision run-hf \
  --config configs/examples/high_fidelity_shared_forward_window.yaml \
  --overlay configs/revision/hf-bilateral-explicit-ei-baseline.yaml \
  --output runs/revision/hf-explicit-ei
```

构建 M0--M5：

```bash
PYTHONPATH=src python -m ypendulum.scientific_revision build-ablation \
  --measured-overlay configs/revision/hf-bilateral-explicit-ei-baseline.yaml \
  --output runs/revision/ablation
```

事件资格：

```bash
PYTHONPATH=src python -m ypendulum.scientific_revision qualify-events \
  --plan configs/revision/event-qualification-plan.example.yaml \
  --output runs/revision/event-qualification-report
```

## 重要边界

`hf-bilateral-explicit-ei-baseline.yaml` 中的 `6.75e-6 N*m^2` 只是把旧模型由 `E,d` 隐式得到的 EI 显式写出，不是新测量值。真实预测前必须换成三支独立弯曲标定结果。

修订层不会把原有测试重新包装成实验验证，也不会用两个模型彼此接近替代真实实验。

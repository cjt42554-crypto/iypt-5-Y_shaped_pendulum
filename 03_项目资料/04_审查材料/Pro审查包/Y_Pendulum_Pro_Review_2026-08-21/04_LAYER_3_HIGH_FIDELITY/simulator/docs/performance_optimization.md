# HF 性能优化与复现实测

本文只讨论第 3 层 `HF-DISCRETE-ROD-RIGID-BOB-1.0` 程序的计算性能，
不改变前向理论、前向数值理论或第 4 层结构性理论。软件定位为个人科研计算
工具；优化的保留条件是墙钟下降且核心科学数组、守卫和事件不退化。

## 1. 优化内容

按收益和风险排序，当前保留了以下改动：

1. 每个 presentation sample 只调用一次 `HighFidelityModel.evaluate`，同一次
   结果同时生成全杆状态、有符号轴力、非负张力、能量、反力和守卫；不再为
   守卫几何重复遍历接触对。
2. 建模时一次性注册材料 socket、同支全段/部分材料分离对、跨支结点 socket
   对及所有不随时间变化的索引。
3. 普通线段距离、自碰撞净空和批量派生量使用 NumPy 批处理；只有带材料约束
   的少数部分段和 projective socket 保持标量分支。
4. presentation samples 按固定连续索引块交给确定性的 `spawn` 多进程池。子进程
   只做彼此独立的逐样本评估，主进程按原索引回填；事件排序、轴向状态转换和
   累计功—能积分仍在主进程进行。
5. 积分完成后、后处理开始前写入
   `YPS-HF-INTEGRATION-CHECKPOINT-1.0`。它保存 accepted/presentation 时间和完整
   状态、事件根、求解器计数、配置身份和数组摘要；后处理失败或改变时可直接
   回放，不重跑隐式积分。

默认后处理 worker 数为 `min(12, 物理核心数)`。可用
`YPS_HF_POSTPROCESS_WORKERS=1|8|12|auto` 覆盖。少于 64 个样本的自动模式直接
串行，避免进程启动开销。

为避免在数值库已有线程的父进程中 `fork`，进程池固定采用 `spawn`。这比
`fork` 多一次安全启动成本，但不会继承 OpenBLAS/GUI/监控线程状态，适合长窗
个人计算。

## 2. 1 ms 端到端实测

硬件为 Ryzen 9 9955HX（16 个物理核心）和 RTX 5060 Laptop GPU。两次运行都
从完成的目标算例 `t=0` 状态开始，窗口 1 ms、129 个 presentation samples，
比较 59 组科学数组及事件。优化后运行包含 checkpoint 写入。

| 指标 | 优化前串行 | 优化后 12 worker | 变化 |
|---|---:|---:|---:|
| 求解器总墙钟 | 113.7493 s | 5.2260 s | 21.77× |
| 隐式积分 | 39.3837 s | 3.7035 s | 10.63× |
| 后处理及求解器开销 | 74.3656 s | 1.5226 s | 48.84× |
| 全运行平均等效 CPU 核 | 1.004 | 4.449 | — |
| 后处理平均等效 CPU 核 | 约 1 | 13.106 | — |
| 进程树峰值 RSS | 212.9 MB | 228.5 MB | +15.5 MB |
| 模拟 GPU 后端 | 未使用 | 未使用 | 不变 |

对照通过：59/59 数组在冻结浮点容差内，57 组逐位相等；仅两个接触守卫数组
因批量距离的舍入顺序出现差异，最大绝对差
`6.938893903907228e-18`，远低于 `5e-13` 的绝对容差。事件完全相同。

## 3. 完整 0.12 s 保存轨迹的后处理实测

为了不重新运行旧串行长积分，下面只读取已经保存的 15,361 个状态样本，分别
用 1、8、12 worker 重新计算全杆位置/速度、有符号轴力、张力、反力、能量、
11 个守卫和 12 个轴向状态事件。三次都使用同一状态，因而结果差异只可能来自
后处理实现。

| worker | 墙钟 | 加速比 | 平均等效 CPU 核 | 进程树峰值 RSS |
|---:|---:|---:|---:|---:|
| 1 | 191.0736 s | 1.00× | 1.000 | 478.3 MB |
| 8 | 29.0962 s | 6.57× | 7.943 | 482.6 MB |
| 12 | 20.8061 s | 9.18× | 11.909 | 507.1 MB |

44 组输出全部通过；事件数、顺序、分支、材料段、状态转换和时刻完全一致，
相对原保存结果的最大绝对差为 `2.220446049250313e-16`。因此目标机器默认选择
12 worker；若同时运行其他重负载任务，可手动降为 8。

## 4. checkpoint

顶层 CLI 默认把 HF checkpoint 放在结果目录旁：

```bash
YPS_HF_POSTPROCESS_WORKERS=12 \
ypendulum simulate CONFIG --hf-checkpoint /path/to/run.integration.npz
```

若积分已完成但结果目录未发布，或只想使用修改后的后处理重新生成结果：

```bash
YPS_HF_POSTPROCESS_WORKERS=12 \
ypendulum simulate CONFIG \
  --hf-checkpoint /path/to/run.integration.npz \
  --resume-hf-checkpoint
```

1 ms 实测中，完整运行用 5.2260 s，checkpoint 回放仅做后处理用 1.5126 s，
为 3.46×；回放的 59 组科学数组全部逐位相等。对长窗而言，主要收益不是这
个短窗比值，而是后处理失败后避免重新支付隐式积分成本。

## 5. GPU 决策

当前未实现 GPU 后端。性能日志中的 `nvidia-smi` 数字是整机桌面活动，不能
归因于模拟器。CPU 批处理已把完整保存轨迹的后处理降到 20.81 s；此时把分支
密集的材料 socket 和隐式 Radau/BDF 搬到 GPU，风险和维护成本高于可证明收益。

只有以后出现“很多同拓扑时间样本或参数成员”的批量任务时，才应先把普通
线段对距离/力核作为独立 GPU 候选，并继续把自适应隐式积分、事件定位和 socket
守卫留在 CPU。保留 GPU 改动前仍须报告端到端墙钟，而不是只报核函数吞吐率。

## 6. 证据和限制

机器可读汇总为
`validation/performance/performance_optimization_report.json`。主要原始报告为：

- `hf_baseline_final_1ms.json`；
- `hf_final_optimized_12_1ms.json`；
- `hf_compare_baseline_vs_final_optimized_12.json`；
- `hf_full_postprocess_serial.json`、`hf_full_postprocess_8.json`、
  `hf_full_postprocess_12.json`；
- `hf_final_checkpoint_resume_12_1ms.json`；
- `hf_compare_final_save_vs_resume_12.json`。

必须同时保留以下限制：

- 完成的 0.12 s 目标轨迹由优化前源码积分产生；优化后没有重跑同等级长积分。
- 优化后源码的动力学等价性由新鲜 1 ms 积分对照支持；完整 0.12 s 则由对同一
  保存状态的全输出重算支持。不能把它写成“优化后完整长积分已运行”。
- 完整六候选形式资格矩阵未运行；这不阻止个人科研使用，但原始结果继续明确
  标记 `UNDETERMINED / SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED`。
- 这些数字只绑定当前机器、目标网格和当前 Python/SciPy 环境；理论或网格改变
  后应先重跑 1--2 ms 基准。

# IYPT 2027 Y 形摆：阶段 3 高保真模拟交付说明

## 1. 交付结论

阶段 3 已按“个人科研计算工具 / 可修改原型”标准收口，可以进入阶段 4。

当前规范高保真模型为 `HF-DISCRETE-ROD-RIGID-BOB-1.0`：三支离散材料杆、
被动轴向局部本构、非零中心线弯曲、有限惯量刚体摆球、偏心连接、气动和有限
尺寸接触守卫。它与第 1、2 层前向柔索模型隔离，不调用前向后端的状态推进器。

本结论是“当前目标计算可用”，不是发布级软件认证，也不是实验意义上的
`VALIDATED` 或 `PREDICTIVE`。

## 2. 主要交付物

- 理论与程序说明：
  `IYPT_2027_Y_Pendulum_第一性原理高保真模拟理论与程序说明.md`；
- 程序根：`Y-Pendulum-Simulator-v1.0.0-rc1/`；
- 目标配置：
  `Y-Pendulum-Simulator-v1.0.0-rc1/configs/examples/high_fidelity_shared_forward_window.yaml`；
- 0.12 s 原始目标结果：
  `Y-Pendulum-Simulator-v1.0.0-rc1/validation/target_hf_0p12_raw/`；
- 代表性网格/时间步敏感性：
  `validation/representative_hf_sensitivity.json` 与
  `validation/representative_hf_sensitivity_series.npz`；
- 性能说明：`docs/performance_optimization.md`；
- 机器可读性能汇总：
  `validation/performance/performance_optimization_report.json`。

## 3. 目标算例结果

0.12 s、24/24/32 网格、Radau、正式 held 初态和双边杆端点已经完成：

- presentation / accepted samples：15,361 / 15,362；
- 所有保存的状态、有符号轴力、非负张力、能量和 11 个守卫数组有限；
- 全局有符号轴力范围：
  ([-3.8320\times10^{-3},1.08528]\ {\rm N})；
- 非负张力范围：([0,1.08528]\ {\rm N})；
- 最大能量账本残差：(7.91404\times10^{-11})；
- 最小样本守卫为 `ROD_SELF_CLEARANCE`：
  (2.46673\times10^{-5}\ {\rm m}>0)；
- 12 个轴向状态采样括区事件；没有物理守卫退出事件；
- 摆球最大位移 (5.58362\times10^{-2}\ {\rm m})，最大速度
  (6.95859\times10^{-1}\ {\rm m,s^{-1}})。

原始结果状态是
`UNDETERMINED / SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED`。含义是：隐式求解和全部
样本守卫完成，但在项目范围收缩后没有继续运行发布级完整六候选连续守卫资格矩阵；
它不是求解失败。个人研究 API 可以分析、互比和与实验比较这个结果，同时保留该
状态，不会伪装成完整认证。

0.12 s 只覆盖约 0.25 个候选低频周期，因此没有足够信息可靠提取双主频、3:2
锁频或闭合误差。阶段 4 不得把候选 FFT 边界峰当作结构性事实。

## 4. 代表性敏感性

0.01 s 释放瞬态上比较了：

- 同一 24/24/32 网格的目标时间步 (h) 与 (2h)；
- 24/24/32 与 20/20/30 网格；
- 摆球、结点和全杆位置/速度；
- 有符号轴力、非负张力、机械能和守卫。

三成员都返回完整代表窗，所有数组有限。26 个时间步和网格差异指标均低于事先
给定的实用分辨率；最紧的是网格 RMS 有符号轴力，占其空间预算 11.4%。这足以
支持个人目标计算，但不是完整三层 Cauchy 资格矩阵。

## 5. 性能优化

保留的优化均通过旧版—新版科学输出对照：

1. presentation sample 的接触、守卫和派生量只计算一次；
2. 预计算静态拓扑、线段配对、豁免类和材料 socket；
3. NumPy 批处理线段距离和接触裕量；
4. 固定连续分块、固定索引回填的 `spawn` CPU 多进程；
5. 事件排序和累计积分留在主进程；
6. 在积分与后处理间保存可回放 checkpoint。

1 ms 端到端代表算例：总墙钟 113.749 s → 5.226 s（21.77×），积分
39.384 s → 3.703 s（10.63×），后处理及开销 74.366 s → 1.523 s
（48.84×）。59 组科学数组全部通过，最大绝对差 (6.94\times10^{-18})。

完整保存轨迹的 15,361 样本后处理：串行 191.074 s，8 worker 29.096 s，
12 worker 20.806 s；12 worker 为 9.18×、平均占用 11.91 个等效 CPU 核，
峰值进程树内存约 507 MB。44 组核心输出和 12 个事件身份全部通过，最大差
(2.22\times10^{-16})。

因此目标机器默认使用 12 worker；共用机器可设 8。GPU 没有投入：当前 CPU
后处理已降到 20.81 s，自适应隐式积分和材料 socket 仍留在 CPU 风险最低。
性能日志中的整机 GPU 百分比不是模拟器使用量。

checkpoint 的 1 ms 回放不重新积分，墙钟 1.513 s，59 组数组逐位相同。

## 6. 推荐运行

```bash
cd '/home/cjt/Desktop/iypt/5 Y形摆/第一性原理模拟/Y-Pendulum-Simulator-v1.0.0-rc1'
source /tmp/yps-hf-stage3-venv-AJNLh0qQ/bin/activate
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
YPS_HF_POSTPROCESS_WORKERS=12 \
ypendulum simulate configs/examples/high_fidelity_shared_forward_window.yaml
```

若积分已经完成、只需重新后处理：

```bash
YPS_HF_POSTPROCESS_WORKERS=12 \
ypendulum simulate CONFIG \
  --hf-checkpoint /path/to/run.integration.npz \
  --resume-hf-checkpoint
```

不要再用旧串行版本启动同等级目标运行。

## 7. 当前回归证据

最终优化源码上的定向结果：

- HF 核心/几何/checkpoint：33 项通过；
- HF API/CLI：14 项通过；
- 独立 reference、守卫和短窗验证（排除完整六候选长矩阵）：20 项通过，
  1 项按范围明确未运行；
- 配置、统一平台和 CLI 状态：44 项通过；
- 本次修改涉及的源码、脚本和测试文件 Ruff 检查通过。

全仓库宽泛 Ruff 仍会报告旧 H1/历史发布脚本的既有风格问题；按当前范围没有为
消除发布级样式债务而改写无关模块。

## 8. 必须保留的限制

1. 0.12 s 目标轨迹由性能优化前源码完成；优化后没有重跑同等级长积分。
2. 优化后动力学等价性来自新鲜 1 ms 积分；完整长窗证据来自对同一保存状态的
   全输出重算，不能写成“优化后 0.12 s 已重新积分”。
3. 未运行完整六候选正式 HF 资格矩阵，未做真实实验验证。
4. 模型不含扭转、材料损伤、结点滑移、接触后动力学、摩擦/断裂、柔性支架
   双向耦合、完整 CFD 和非球形摆球。
5. 到达接触/几何守卫边界后模型停止适用；不能让数值积分穿过边界后继续解释。
6. 理论、状态或守卫语义变化后，旧 checkpoint 不再适用，应重新做 1--2 ms
   等价性和代表性敏感性。

## 9. 向阶段 4 交接

阶段 4 只可使用本层已经输出的轨迹、轴力/张力、能量、守卫、事件、参数和
敏感性作为证据；不得把 HF 数值实现细节混写成前向理论，也不得把结构性解释
回填到本文件冒充第一性原理方程。

阶段 4 当前可安全研究的对象包括：几何约束与双模时间尺度、有限质量结点和
分布质量修正、弯曲/刚体偏心对公共可观测量的修正、轴向压缩—拉伸状态切换、
守卫接近与有效域边界。任何锁频、分岔或普适尺度律若需要多个周期或参数扫描，
必须明确标为待验证，不能由 0.12 s 单轨迹外推。

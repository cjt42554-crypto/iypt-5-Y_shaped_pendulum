# Y 形摆四层研究：给无项目记忆 Pro 模型的审查导读

## 0. 你现在拥有的上下文

你正在审查 IYPT 2027 第五题 Y-shaped pendulum / Bowditch pendulum 的一套四层研究成果。你没有任何先前对话记忆，也不能访问制包机器的本地路径；因此请只使用本包内容，不要假设包外事实。

官方题目核心是：构造 Bowditch/Y 形摆，研究摆球形成的 Lissajous 图样如何依赖相关参数。

本项目用户明确规定的层级顺序是：

1. 前向预测理论；
2. 前向预测理论的数值计算理论与数值程序；
3. 第一性原理高保真模拟；
4. 结合前三层结果形成结构性理论。

原始通用框架文档中的“第二层/第三层”命名顺序与用户本项目的顺序不同。审查时以以上四项用户顺序为准，不要因名称编号差异把内容判为混层。

## 1. 审查范围

项目已经按“个人科研计算工具 / 可修改原型”收口，不按生产发布软件验收。

请重点审查：

1. 物理模型是否闭合、自洽，符号和量纲是否正确；
2. 前向理论、数值理论、HF 模型和结构性理论是否真正隔离；
3. 数值程序是否忠实实现其对应理论；
4. HF 是否包含前向模型中不存在的独立局部自由度和相互作用；
5. 状态、有符号轴力、非负张力、能量、守卫和事件是否一致；
6. 代表性网格/时间步敏感性是否足以支持当前用途；
7. 性能优化是否保持科学输出；
8. 结构性推导和数值结论是否正确、是否过度外推；
9. 已披露限制是否充分；
10. 哪些改动能直接提高物理正确性、数值可用性或后续可修改性。

请不要把下列发布级事项作为阻断：

- Git 提交、wheel/sdist、ZIP 发布流程；
- 恶意 JSON、TOCTOU、复杂 manifest 互绑；
- crash-atomic 覆盖语义；
- 多用户权限、服务恢复、生产监控；
- 不可伪造证书链；
- 极端攻击输入的总函数防御。

如果这些方面存在问题，可以在“非目标工程建议”中一句话说明，但不要因此把科学原型判为失败。

## 2. 建议审查顺序

### A. 先读

1. **01_ALL_IN_ONE_THEORY_AND_HANDOFF.md**
2. **original_requirements.md**
3. **master_delivery.md**

这三份文件足以建立项目边界、主要方程、结果和已知限制。

### B. 再按层审查

#### Layer 1

- `02_LAYER_1_FORWARD_THEORY/forward_theory.md`

检查：

- 规范输入和状态；
- 柔索本构、边界、能量和有效域；
- 事件/退出语义；
- FWD-CABLE 与 FWD-TORUS 的边界；
- 是否把结构性频率结论留到阶段 4。

#### Layer 2

- `03_LAYER_2_NUMERICAL_THEORY_AND_SOLVER/numerical_theory.md`
- `03_LAYER_2_NUMERICAL_THEORY_AND_SOLVER/solver/y_pendulum_forward/`
- `03_LAYER_2_NUMERICAL_THEORY_AND_SOLVER/solver/tests/`
- `03_LAYER_2_NUMERICAL_THEORY_AND_SOLVER/solver/configs/`
- `03_LAYER_2_NUMERICAL_THEORY_AND_SOLVER/solver/validation/`

检查：

- 离散状态是否对应阶段 1；
- cable/torus 两后端；
- 初态制备；
- 事件定位和同刻事件；
- 观测与集合预测；
- 收敛/敏感性门；
- 结果合同；
- final convergence reports 是否支持当前声明。

#### Layer 3

- `04_LAYER_3_HIGH_FIDELITY/hf_theory_and_program.md`
- `04_LAYER_3_HIGH_FIDELITY/stage3_handoff.md`
- `04_LAYER_3_HIGH_FIDELITY/simulator/src/ypendulum/`
- `04_LAYER_3_HIGH_FIDELITY/simulator/tests/`
- `04_LAYER_3_HIGH_FIDELITY/simulator/configs/`
- `04_LAYER_3_HIGH_FIDELITY/target_result_evidence/`
- `04_LAYER_3_HIGH_FIDELITY/performance_evidence/`

检查：

- 离散杆、弯曲、有限结点、有限刚体、偏心附件是否构成独立 HF；
- signed axial force 与 nonnegative tension 是否分离；
- 能量账和气动力功率符号；
- 固定材料 socket、接触豁免与 11 个守卫；
- held 初态；
- CPU 并行/checkpoint 是否保持结果；
- raw status 为何仍是 UNDETERMINED；
- 0.12 s 轨迹能支持哪些、不能支持哪些物理结论。

#### Layer 4

- `05_LAYER_4_STRUCTURAL_THEORY/structural_theory.md`
- `05_LAYER_4_STRUCTURAL_THEORY/analysis/`
- `05_LAYER_4_STRUCTURAL_THEORY/results/`
- `05_LAYER_4_STRUCTURAL_THEORY/figures/`

检查：

- 无量纲 Hamilton 量；
- 两条精确不变模态；
- 线性频率设计律；
- Chebyshev Lissajous 隐式曲线；
- 四阶 Birkhoff 正规形；
- 有限振幅几何预补偿；
- 可公度、内共振、锁频的区分；
- 张力充分条件；
- HF 无量纲机制群；
- 可证伪实验预测。

## 3. 最终身份

| 对象 | SHA-256 |
|---|---|
| 阶段 1 前向理论 | 7eaf18e30087438507aef73c481b49e5b1427a146d79c0fd2b35ca10dc02cdb2 |
| 阶段 2 数值理论 | 14b9e5bae0778753acbc46757286b4d5e646b120698ddd2bc33e16158efa78a7 |
| 阶段 2 delivery root | dec497d42e0384f403b4c652a40799e389702a94b4299b24a4555f2bd9ea93ef |
| 阶段 3 主说明 | 67f8b8de88f4aa090825a573e6a34ec8cd35cb0f82ede8722f82114290e6bde9 |
| 阶段 3 交付说明 | c42c6b257efeb482904ba76963b9461f9bae8b14eade661f2135c37068a2f771 |
| 阶段 3 当前 Python 源树 | e2476a8e77d75feee2630e8619472cdee1e35a364017ce514aa0b227227b14f4 |
| 阶段 4 主文稿 | ae7d3b5ecde45603af4b57426972ae94374c9f0e256da9f4973f834a9f064c6d |
| 阶段 4 分析脚本 | 895a1340bdeca678f1d44a783bba15c9fcab7e9489401ecf0b4e581ced0c2020 |
| 阶段 4 结果 JSON | f1f0789e6ea6910f4d351d21da01e7a6bb4f91ac34169251d0df13a89a42ace1 |

包根 **MANIFEST.json** 和 **SHA256SUMS.txt** 绑定本包实际包含的文件。它们只是传输完整性清单，不是要求你审查的生产证书。

## 4. 已完成的 HF 目标结果

正式目标：

- 0–0.12 s；
- 24/24/32 材料网格；
- Radau；
- held endpoint equilibrium release；
- 15,361 presentation samples；
- 15,362 accepted samples；
- 积分墙钟 4,881.448 s。

主要量：

- signed axial force：
  \([-3.8320\times10^{-3},1.08528]\ {\rm N}\)；
- tension：
  \([0,1.08528]\ {\rm N}\)；
- 最大能量账本残差：
  \(7.9140\times10^{-11}\)；
- 11 个样本守卫均为正；
- 最小守卫 ROD_SELF_CLEARANCE：
  \(2.46673\times10^{-5}\ {\rm m}\)；
- 12 个轴向状态采样括区事件；
- 没有物理守卫退出。

raw status：

**UNDETERMINED / SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED**

原因：范围收缩后没有运行完整六候选、全窗连续守卫资格矩阵。请审查“它是否适合作为个人研究结果并保留这一状态”，不要把它误读成积分失败，也不要把它升级成形式认证。

0.12 s 只覆盖约 0.25 个候选慢周期，所以不能从这条轨迹可靠声称双主频、3:2/4:3 锁频、分岔或混沌。

## 5. 性能结果

1 ms 端到端：

| 指标 | 优化前 | 12 worker 后 | 加速 |
|---|---:|---:|---:|
| 总墙钟 | 113.749 s | 5.226 s | 21.77× |
| 积分 | 39.384 s | 3.703 s | 10.63× |
| 后处理及开销 | 74.366 s | 1.523 s | 48.84× |
| 峰值进程树内存 | 203.1 MiB | 217.9 MiB | — |

59 组科学数组通过，最大绝对差
\(6.94\times10^{-18}\)，事件相同。

完整保存轨迹后处理：

- 串行 191.074 s；
- 8 worker 29.096 s；
- 12 worker 20.806 s；
- 12 worker 加速 9.18×；
- 平均 11.909 个等效 CPU 核；
- 峰值进程树内存 483.6 MiB；
- 44 组核心输出、12 个事件相同；
- 最大绝对差 \(2.22\times10^{-16}\)。

GPU 没有使用。CPU 后处理已经降到 20.81 s，自适应隐式积分和分支密集 socket 守卫仍留在 CPU。

## 6. 结构性主结论

理想张紧环面的线性比：

\[
\rho_0=\frac{\omega_\varphi}{\omega_\theta}
=\sqrt{1+\frac h\ell}.
\]

小振幅 \(p:q\) 设计：

\[
\frac h\ell=\left(\frac pq\right)^2-1.
\]

四阶频移：

\[
\Omega_\varphi
=1-\frac{A_\varphi^2}{16}+\frac{A_\theta^2}{8}+O(A^4),
\]

\[
\Omega_\theta
=\frac1{\sqrt\kappa}
\left(
1-\frac{A_\theta^2}{16}
+\frac{A_\varphi^2}{8\kappa}
\right)+O(A^4).
\]

代表性 3:2，\(A_\varphi=0.15,A_\theta=0.10\)：

- 零振幅 \(h/\ell=1.25\)；
- 四阶补偿 \(1.253515625\)；
- 数值调谐 \(1.253365023\)；
- \(\ell=0.300\ {\rm m}\) 时解析修正约 \(+1.055\ {\rm mm}\)；
- 30 慢周期相位误差由 \(-0.4222\) rad 降至 \(0.0191\) rad，数值调谐后 \(1.97\times10^{-4}\) rad。

张紧扫描：

- 1591 点；
- 1311 点六周期保持张紧；
- 277 点 B 支先失张；
- 3 点 A 支先失张。

## 7. 本包未包含的大文件

主包不包含 156 MB HF HDF5、95 MB Stage-2 cable trajectory NPZ 和性能测试的重复 NPZ。

取而代之，本包提供：

- 原文件 SHA-256 和字节数；
- HDF5 完整数据集树；
- 每个数据集的 shape、dtype、finite count、min/max/mean 和内容哈希；
- 301 点 HF 物理量降采样 CSV；
- 原始 config、summary、diagnostics、events、report 和图；
- 性能 JSON、时间日志和等价性报告；
- Stage-2 CSV、result JSON 和收敛报告。

因此你能审查科学主张和代码逻辑，但不能仅凭本包重新运行 0.12 s HF 积分或逐字节重建被排除的大数组。不要把这一传输体积选择误判成数据不存在。

## 8. 已知限制

1. 尚无真实实验数据。
2. 优化后没有重新做同等级 0.12 s 长积分；有新鲜 1 ms 积分等价性，以及对保存 0.12 s 状态的完整后处理重算。
3. 未做发布级完整六候选 HF 资格。
4. HF 不含扭转、损伤、摩擦接触后动力学、断裂、柔性支架双向耦合和完整 CFD。
5. 接触/几何守卫到零后模型停止，不提供越界后的物理续接。
6. 结构性六周期张紧扫描不是全振幅域证明。
7. 当前没有锁频、分岔、混沌或实验验证结论。

## 9. 请按以下格式输出审查

### 9.1 总判定

分别给出：

- Layer 1：GO / CONDITIONAL GO / NO-GO
- Layer 2：GO / CONDITIONAL GO / NO-GO
- Layer 3：GO / CONDITIONAL GO / NO-GO
- Layer 4：GO / CONDITIONAL GO / NO-GO
- 四层隔离：GO / NO-GO
- 个人科研计算目标：GO / NO-GO

### 9.2 问题分级

- **P0：**核心物理错误、主要方程错误、目标计算不能成立；
- **P1：**会实质影响结论或让明显数值/事件错误伪装成功；
- **P2：**不阻断当前个人研究，但值得改进；
- **非目标工程建议：**生产/发布级事项。

每个问题必须给：

1. 文件和章节/函数；
2. 具体公式、代码路径或反例；
3. 影响哪个已声明结论；
4. 最小修正；
5. 是否需要重跑 HF 长积分。

### 9.3 独立复算

请优先独立复算：

- 线性频率比；
- 两条纯模态；
- 四阶正规形与幅频公式；
- 3:2 补偿式；
- 张力充分条件；
- HF 无量纲机制量；
- 性能加速比；
- 程序是否真的保持 signed axial force、tension、energy、guards 和 events。

### 9.4 禁止的审查捷径

- 不要因为文件很多就只审查 README；
- 不要把名称或 manifest 当作功能已经实现；
- 不要把 raw UNDETERMINED 当成失败或成功，必须看其语义；
- 不要把有限窗 FFT 峰当作可靠结构频率；
- 不要把可公度图样自动称为内共振或锁频；
- 不要要求把个人原型补成生产服务后才允许进入实验。

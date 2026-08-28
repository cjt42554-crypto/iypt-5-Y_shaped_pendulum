# 离散杆—刚体无接触静态参考模型迁移稿

## 1. 新身份

本目录是独立的候选迁移包，不是 HF-v2 完整模拟器的改名副本，也没有获得正式目录提升。

模型身份固定为：

`YPS-DISCRETE-ROD-RIGID-BOB-NO-CONTACT-STATIC-REFERENCE-DRAFT-1.0`

能力固定为：

`conservative_no_contact_static_reference_only`

历史结论上限仍为：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

迁移动作本身不携带或重新授予这一资格，接口返回的资格状态始终为 `NOT_CARRIED_BY_MIGRATION`。

## 2. 方程身份

迁移稿保留以下独立离散模型：

- 材料坐标离散杆拓扑与唯一静长；
- 单边轴向局部材料；
- 离散曲率 binormal 弯曲能、解析负梯度和反平行能垒；
- `SO(3)` 姿态与偏心刚体连接；
- 无接触总势能、解析广义力和完整装配身份；
- 固定 BFGS 与确定性种子顺序；
- 能量—力、平衡、二阶及网格趋势所需的独立审计工具。

该模型与正式连续柔索方程不是同一模型。它不得替换连续柔索前向求解器或 RC1。

## 3. 明确排除

源码树不包含：

- `contact/**`；
- `statics/contact_assembly.py` 或 `contact_solver.py`；
- 任意 `ypendulum_hfv2_p3r*` 包；
- P3–P3R5 目标、阈值、资格工具或结论；
- 动力学、动态接触、UI、HDF5 或完整模拟器入口。

包级测试会解析每个 Python 文件的导入，若重新引入上述模块则失败关闭。

## 4. 接口语义

`solve_no_contact_static_reference` 只执行确定性无接触静力种子，并运行独立实现诊断。能量—力有限差分在优化前的绑定初始坐标上进行，避免在近驻定点用接近零的梯度作相对误差分母；平衡和广义力残差在最终坐标上检查。SciPy 的 `optimizer_success` 与 `optimizer_status` 仅作为记录返回，不作为资格门。

`implementation_diagnostics_passed` 只表示调用者给出的能量—力与平衡阈值在该次运行中通过。它不表示：

- 正式数值资格；
- 接触能力；
- 动力学能力；
- 装置级物理验证；
- 实验验证。

## 5. 受支持运行时草案

当前候选支持声明有意限制为 CPython 3.12、NumPy 1.26–2.x 和 SciPy 1.12–1.x。F0 验证应至少覆盖两个依赖单元，并单独记录 BFGS 状态 2 的跨版本行为。扩大 Python 或依赖范围必须先增加独立 CI 单元，不能从一次本机 PASS 外推。

## 6. 溯源

生产源码由 `HF-v2-core/src/ypendulum_hfv2` 的允许文件逐一迁移，绝对包导入只作命名空间替换，文件末尾统一为至少一个换行；除此之外的正文差异会由溯源工具失败关闭。`migration_provenance.json` 记录每个源文件、目标文件及两侧 SHA-256。`contracts/` 中两份历史验收清单只作为测试阈值和绑定算例输入，不是新模型身份文件。

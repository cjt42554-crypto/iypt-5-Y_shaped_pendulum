# 当前交接：2026-09-05 数值审查修复

## 当前状态

本轮修复基于 `cd4f042a8ffbe8148b935a4cf7f1c58789638bc3`，在 `main` 上继续。原路径 F 的限定结论不变；高保真、连续守卫完备性、接触后动力学及装置验证仍未获得资格。

本轮按用户 2026-09-05 的明确授权直接修复正式实现和测试；项目按短期个人科研工具处理。未新增实验数据，未把实现测试晋升为装置级验证。`交接说明_history.md` 按要求清空为零字节，Git 提交历史及既有原始计算/冻结证据不删除、不改写。

## 本轮实际修改

在 `02_模拟程序/01_前向预测数值求解器/y_pendulum_forward_solver/` 中：

1. 新增 `y_pendulum_forward/energy_ledger.py`。以求解器接受步的密集输出做三点 Gauss–Legendre 功率积分；输出时刻使用接受步前缀加局部积分，不再把输出网格当作独立账本的积分网格。物理端力功、代数反力功和各功率端口的绝对交换量分别累计；禁止越过求解器已接受时间范围外推。
2. `cable.py` 增加独立积分、动态能量尺度及重力尺度残差。动态尺度定义为峰值动能、观测到的总能变化和绝对端口交换功的最大值，不伪称“已知平衡态以上能量”；尺度低于舍入分辨能力时输出 `null`/未分辨状态。
3. 保留旧的输出梯形积分指标，供既有收敛程序独立重算；新旧方法显式标注，不更改既有资格门来制造 PASS。新独立账本和旧审计不是同一个证据。
4. 质量矩阵已知为对称正定时，条件数改由同一次特征值分解的最大/最小特征值计算，去掉重复 SVD；保留 Cholesky 与正定检查。增加接受步数、功率求积次数和装配/积分/诊断耗时，便于实际定位热点。
5. 新增 `tests/test_audit_energy.py`，覆盖五次功率多项式、不同输出网格相同末端功、外推/非有限值拒绝、空输出、无重复 SVD、真实短算例以及新旧能量诊断。更新既有守卫失败测试的注入函数，使其传递新增账本参数而保留原断言。

## 应如何读新诊断

优先查看 `power_quadrature_method`、`power_integral_physical_traction`、`power_integral_algebraic_reaction`、`max_accepted_step_absolute_energy_power_residual_*` 和 `max_dynamic_relative_energy_power_residual_*`。

`max_output_trapezoid_work_difference` 用于识别输出采样积分误差；`dynamic_energy_scale_resolved=false` 时不要解读动态相对误差。旧的 `max_absolute_energy_power_residual_*`、`max_relative_energy_power_residual_*` 仍对应输出梯形法，见 `legacy_energy_residual_method`。新增耗时仅用于性能诊断，不是物理输入或确定性比较量。

## 验证和边界

本地执行完整前向求解器测试：`python -m unittest discover -s tests`，113 项通过。执行目录为上述 `y_pendulum_forward_solver`，环境中令 `OPENBLAS_NUM_THREADS=1`。测试中的真实短轨迹确认仅改变输出间隔不改变独立账本的末端积分。

没有重跑其他高保真/静态参考/图谱程序的完整 campaign，没有新增解析 Jacobian、稀疏质量求解或弯曲/接触力学。三点功率求积仍需时间细化，尤其是非光滑功率；它不是严格误差上界。其额外诊断成本已单独记录，不声称整个求解器因此更快。

## 下一步

优先按新耗时记录定位 RHS、隐式求解和诊断热点；需要时利用质量矩阵结构，但不能给 $M^{-1}K$ 伪造有限元邻接稀疏模式。SciPy 端点变号和输出采样不能保证捕获任意步内越界，本轮未完成连续柔索守卫的区间认证。涉及近松弛/再受拉的实验时再评估弯曲和接触，而非无依据增加自由度。

## 临界事件测试的跨环境修正

首次远端测试 111 项通过、1 项失败。失败来自既有环面切触算例：本地返回 `EVENT_UNRESOLVED`，远端因双重根附近的末位舍入产生微小变号，返回 `OUT_OF_SCOPE / SUCCESS_EVENT`。生产环面方程未改动。修正测试只接受这两种禁止继续的状态，定位分支额外核验张力零残差及距解析切触时间小于 1 微秒；样点审计分支仍要求原来的 12 位时间匹配。另加直接构造切触状态的独立测试，固定核验采样审计必须拒绝完成。没有把事件失败改成完成，也没有放宽求解器验收门。

## 本轮提交验证记录

下方记录由实际执行修复测试的提交工作流写入；完整日志位于 `current/2026-09-05_数值审查修复/validation.log`。

实际远端验证：在前向求解器包目录执行 `PYTHONPATH=.:tests OPENBLAS_NUM_THREADS=1 python -m unittest discover -s tests`，退出码 `0`。NumPy 2.3.5、SciPy 1.17.0、Matplotlib 3.10.8。

工作流运行编号：`33923422856`；测试对象是基于 `c9135760fec8fa0c7bd2c79d757b0cc7e6f4b02c` 应用本轮补丁后的工作树。

```text
Python 3.13.15
Ran 113 tests in 69.067s
OK
```

# 离散杆—刚体无接触静态参考模型

## 1. 正式身份与结论上限

本目录是仓库中的正式静态参考实现，但不是完整模拟器，也不是正式数值资格包。

冻结身份如下：

- 模型：`YPS-NO-CONTACT-STATIC-REFERENCE-1.1`
- 发布状态：`FORMAL_RELEASE_STATIC_REFERENCE_ONLY`
- 能力：`position_orientation_conservative_no_contact_static_reference_only`
- 结论上限：`FORMAL_STATIC_REFERENCE_IMPLEMENTATION_AND_RUNTIME_EVIDENCE_ONLY`
- 资格状态：`NO_FORMAL_NUMERICAL_QUALIFICATION_CARRIED`

“正式”只表示本实现已进入正式程序目录并具有关闭的身份、合同、来源和运行时证据接口。它不表示已经取得正式数值资格、装置级物理验证或实验验证。

## 2. 能力边界

生产源码只包含：

- 材料坐标离散杆拓扑和唯一静长；
- 自由材料结点位置、摆球位置和 `SO(3)` 姿态；
- 保守单边弹性轴向势能；
- 离散曲率 binormal 弯曲能及其解析负梯度；
- 分开的重力与浮力静态载荷；
- 偏心刚体连接几何和静态力矩映射；
- 无接触总势能、解析广义力和完整装配令牌；
- 固定 BFGS 静力算法和保守静态实现审计。

生产状态和公共 API 不含速度、角速度、时间步、惯性动力学、动能、动量、阻力、耗散、功率或旋转时间推进。该包也不实现接触、摩擦、碰撞、动态接触或 P3–P3R5 资格流程。

本离散模型与正式连续柔索方程不是同一模型，不得替换连续柔索前向求解器或 RC1。

## 3. 规范合同与求解器边界

`contracts/static_reference_run_contract.json` 固定一个静态 Y 形算例、一个确定性种子、BFGS 设置和审计阈值。物理方程、BFGS 设置、阈值和生产 API 与经复审的 F0R 候选基线保持一致。

优化器的 `success`、状态码和消息只作原始记录。`implementation_diagnostics_passed` 只表示该次运行通过合同给定的能量—力与静态平衡诊断，不能改写优化器状态，也不能授予正式数值资格。

旧来源包的 G1R/G2 清单仅按原字节保存在 `tests/fixtures/historical/` 中用于回归测试。清单中的历史 `CANDIDATE` 身份不属于本正式模型身份，且不被迁移为当前资格。

## 4. 从仓库 checkout 运行

在仓库根目录执行：

```bash
cd '02_模拟程序/04_离散杆刚体无接触静态参考模型'
python3 -m pip install -e '.[dev]'
python3 -m pytest
```

支持声明为 CPython 3.12、NumPy `>=1.26,<3` 和 SciPy `>=1.12,<2`。探针会核对实际解释器、依赖版本、正式身份、合同、schema、导入文件位置和全部生产源码来源。

正式树不保存生成的 `outputs/**`。需要生成规范运行证据时，应把输出写到 checkout 外部的临时路径：

```bash
python3 tools/runtime_probe.py \
  --project-root . \
  --output /tmp/yps_static_reference_evidence.json \
  > /tmp/yps_static_reference_evidence.stdout.json
cmp /tmp/yps_static_reference_evidence.json \
  /tmp/yps_static_reference_evidence.stdout.json
```

探针要求 `--project-root` 精确解析到脚本所在的正式包根，且会核对实际导入文件。指向候选树、镜像树或其他同名安装的请求会失败关闭。

## 5. 最小公共 API

```python
from ypendulum_static_reference import (
    StaticReferenceAuditThresholds,
    solve_no_contact_static_reference,
)
from ypendulum_static_reference.statics.solver import StaticSolverSettings

result = solve_no_contact_static_reference(
    assembly,
    (seed,),
    StaticSolverSettings(),
    StaticReferenceAuditThresholds(
        finite_difference_relative_steps=(1e-4, 3e-5, 1e-5, 3e-6, 1e-6, 3e-7),
        finite_difference_final_relative_error_max=2e-6,
        finite_difference_minimum_strict_decrease_steps=3,
        scaled_generalized_force_residual_max=2e-7,
        scaled_global_force_balance_max=2e-10,
        scaled_global_moment_balance_max=2e-9,
    ),
)
```

`assembly` 与 `seed` 必须由调用方按正式类型明确构造；生产包不会隐式加载历史夹具，也不会从历史 G2 状态推导资格。

## 6. 证据解释

`schemas/static_run_evidence.schema.json` 只描述单次正式静态实现与运行时证据。即使严格 schema、来源绑定、确定性复算和全部独立诊断均通过，当前最高结论仍是：

`FORMAL_STATIC_REFERENCE_IMPLEMENTATION_AND_RUNTIME_EVIDENCE_ONLY`

未由本包证明的事项包括正式数值资格、接触或摩擦能力、动力学能力、连续柔索等价性、装置级物理有效性和实验有效性。

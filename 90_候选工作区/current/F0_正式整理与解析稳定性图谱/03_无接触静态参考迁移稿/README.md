# 离散杆—刚体无接触静态参考模型迁移稿

## 1. 身份与结论上限

本目录是候选迁移包，不是正式目录中的已提升程序，也不是完整模拟器。

模型身份为：

`YPS-NO-CONTACT-STATIC-REFERENCE-DRAFT-1.1`

能力为：

`position_orientation_conservative_no_contact_static_reference_only`

本迁移稿的最高结论为：

`CANDIDATE_STATIC_IMPLEMENTATION_AND_RUNTIME_EVIDENCE_ONLY`

资格状态固定为：

`NO_FORMAL_NUMERICAL_QUALIFICATION_CARRIED`

旧来源包曾记录过有条件的无接触静态算法结果，但该历史状态没有被迁移、继承或重新授予。历史清单只保存在 `tests/fixtures/historical/` 中用于回归测试。

## 2. 生产方程与状态边界

生产源码只包含：

- 材料坐标离散杆拓扑和唯一静长；
- 自由材料结点位置、摆球位置和 `SO(3)` 姿态；
- 单边弹性轴向势能；
- 离散曲率 binormal 弯曲能及其解析负梯度；
- 分开的重力与浮力静态载荷；
- 偏心刚体连接几何和静态力矩映射；
- 无接触总势能、解析广义力、完整装配令牌；
- 固定 BFGS 静力算法和保守静态实现审计。

生产状态和 API 不含速度、角速度、时间步、惯性动力学、动能、动量、阻力、耗散、功率或旋转时间推进。`audit/g2_cases.py`、`audit/passivity.py` 和 `audit/invariance.py` 不在生产树中；算例构造和对象性回归均位于测试层。

该离散模型与正式连续柔索方程不是同一模型，不得替换连续柔索前向求解器或 RC1。

## 3. 接口与阈值

`solve_no_contact_static_reference` 只运行明确给定的静态种子。`StaticReferenceAuditThresholds` 会严格拒绝空、非有限、非正、非递减有限差分序列以及无效步数；求解器设置也严格固定为单一 BFGS 配置。

优化器的 `success`、状态码和消息只作记录。`implementation_diagnostics_passed` 仅表示该次运行通过给定的能量—力和平衡阈值，不表示：

- 正式数值资格；
- 接触或摩擦能力；
- 动力学能力；
- 装置级物理验证；
- 实验验证。

## 4. 规范运行证据

`contracts/static_reference_run_contract.json` 固定一个候选静态算例、一个种子、求解器设置和审计阈值。规范证据保存在：

`outputs/canonical_static_run_evidence.json`

该证据包含：

- 装配身份 schema 和完整装配令牌；
- 种子标识和种子 SHA-256；
- 求解器设置和实际优化器状态；
- 审计阈值和全部诊断；
- CPython、NumPy、SciPy、pytest 与 jsonschema 运行时身份及其哈希；
- 全部生产源码、规范合同、模型身份、构建元数据、证据 schema、算例构造器和证据工具的源清单与哈希。

生成命令为：

```bash
PYTHONPATH=src:. python tools/runtime_probe.py \
  --project-root . \
  --output outputs/canonical_static_run_evidence.json
```

## 5. 运行时验证边界

支持声明限制为 CPython 3.12、NumPy 1.26–2.x 和 SciPy 1.12–1.x。F0R 本机验证覆盖当前依赖单元和下界依赖单元，并在两者中分别运行完整测试与规范状态 2 探针。`runtime_matrix.json` 只记录实现与运行时证据，不外推到其他 Python、依赖版本或平台。

## 6. 语义溯源

`migration_provenance.json` 使用逐文件语义映射，不再声称候选源码只是旧包的命名空间替换。每个生产文件记录来源哈希、目标哈希和静态抽取动作；新身份与新接口标为候选新增。生成器同时检查精确生产文件集合和 AST 静态边界：

```bash
python tools/generate_migration_provenance.py \
  --repository-root ../../../.. \
  --output migration_provenance.json \
  --check
```

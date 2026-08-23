# IYPT 2027 第 5 题 Y 形摆：前向数值计算阶段 2 验收记录

> 记录日期：2026-08-21（Asia/Singapore）  
> 记录角色：阶段 2 工程证据的中文索引与自检结论  
> 自检结论：**GO 候选；最终阶段门以独立只读复验为准**

## 0. 结论与边界

当前前向数值计算阶段已经形成相互一致的数值理论、双前向后端、严格输入/输出合同、有限联合不确定性接口、完整测试、两份正式收敛报告、两份参考轨迹和一份集合预测示例。

本记录只支持以下结论：

1. `FWD-CABLE-1.0` 的生产配置在预冻结的空间、求积、时间、事件、规范输出、物理不变量和独立动力学缺陷门下获得 `REFINEMENT_SUPPORTED`；
2. `FWD-TORUS-1.0` 的生产配置在预冻结的时间、事件、几何、张力、能量、观测和独立动力学缺陷门下获得 `REFINEMENT_SUPPORTED`；
3. 参考运行和有限集合示例绑定同一冻结理论、同一可执行源码身份和各自完整配置；
4. 程序达到“研究级、可运行、可修改”的交付目标。

本记录不支持以下越界结论：

- 不证明连续退化柔索强解全局存在唯一；
- 不给出验证性 ODE/PDE 区间误差包络；
- 不声称有限不确定性样本包络整个允许集合；
- 不包含第一性原理高保真模拟；
- 不包含高保真—前向比较；
- 不提出频率、共振、稳定性、分岔或其他结构性理论。

## 1. 输入与版本身份

| 对象 | 身份 |
|---|---|
| 总需求说明 | SHA-256 `e4c622f6a236642ce6c8eb94f8ad45097f268b016919bb0d1965108cfa23918e` |
| 冻结前向理论 | SHA-256 `7eaf18e30087438507aef73c481b49e5b1427a146d79c0fd2b35ca10dc02cdb2` |
| 数值计算理论 | SHA-256 `14b9e5bae0778753acbc46757286b4d5e646b120698ddd2bc33e16158efa78a7` |
| 程序 README | SHA-256 `45320b531e0aa4585e5759200e7b08ce1cd1bd3abe01e950f1c972e74886cf21` |
| 可执行源码树 | `c1a158645722a968282761b3cf3c69c82ca6e49326a0a0dfa16bee62330ada56` |
| Cable 生产配置规范哈希 | `f76f5587eb298473b983cf05f995fb212f40e9d490ef022f267723e03f53188f` |
| Torus 生产配置规范哈希 | `f660f9190b0bcfbd5e5ed8945c24f06229cec02e88b0d6bad7008a4b96f43088` |
| Torus 集合规范哈希 | `743da929bae5c80d8a6305d423181772b2aa48973bcfef675caabaf1adf81ca9` |

可执行源码树哈希覆盖活动包中的全部 `.py` 文件、`run.py`、`pyproject.toml` 和 `requirements.txt`。README、理论文档、报告和二进制轨迹另由 artifact manifest 绑定。

正式运行环境：

- Python `3.12.3`；
- NumPy `1.26.4`；
- SciPy `1.11.4`；
- Matplotlib `3.6.3`；
- Linux `7.0.0-28-generic`，x86_64，glibc `2.39`。

## 2. 数值实现要点

### 2.1 Cable

- 材料坐标 P1 连续 Galerkin 有限元；
- 三支独立材料网格，唯一共享连接结点和摆球结点；
- 一致质量矩阵，点质量只装配一次；
- 规定支点的质量耦合项保留；
- 冻结的精确正部、分段激活和仅受拉张力原样计算；
- 阻力、空气功率和分布外力使用一致 Gauss–Legendre 求积；
- Radau 自适应时间积分；
- 物理退出、数值失败和观测错误分栏返回。

### 2.2 Torus

- 独立四状态 ODE，不借用 Cable 初态或场状态；
- DOP853 自适应时间积分；
- 每个状态重算几何、未平方环面关系、物理分支量、三张力和能量；
- 首次 $R$ 或任一张力归零即终止，不拼接到 Cable。

### 2.3 资格门

生产配置就是待认证最细层。工具向后生成：

- Cable 空间 `n*/4, n*/2, n*`；
- Cable 求积 `q*-4, q*-2, q*`；
- Cable/Torus 时间容差 `16, 4, 1` 倍、最大步长 `4, 2, 1` 倍。

每层从配置独立推导并重算完整状态、拓扑、派生量、观测、守卫、事件和物理不变量。能量和三项动力学缺陷的绝对上限只约束生产最细层；粗层仍须非负有限并通过全部结构门。能量参加适用的三层趋势检查；三项动力学缺陷的逐项趋势门只适用于时间研究。空间和求积报告中对应字段的 `true` 表示 `N/A (time-only)`，不是该缺陷已随空间或求积加密实测下降。

独立动力学证书采用 Hermite 中点—Simpson 缺陷，并分别门控：

- 局部归一化率缺陷；
- 带符号累计缺陷；
- 绝对累计缺陷。

## 3. 完整测试

执行命令：

```bash
PYTHONPYCACHEPREFIX=/tmp/yps-pycache python3 run.py self-test
```

结果：`Ran 106 tests in 19.086s`，`OK`。

测试覆盖激活函数、本构、有限元装配、移动支点、初态制备、事件与切触、严格 JSON、资源边界、状态命名空间、观测、I/O 写前预检、覆盖保护与同步异常回滚、集合成员保留、规范输出重算、全守卫注册表、事件左极限、输出网格、三类动力学缺陷和粗层—最细层资格语义。覆盖写入不是并发观察或进程崩溃意义下的 `crash-atomic` 单次目录切换。该结果不替代正式长窗收敛报告。

## 4. Torus 正式收敛证据

报告：`y_pendulum_forward_solver/validation/torus_convergence.json`  
报告 SHA-256：`5b9836676f33374b7a51745bbc3570def1d7cb2518b225cd7488648e73af0a10`

- 结论：`REFINEMENT_SUPPORTED`；
- 生产配置规范哈希：`f660f9190b0bcfbd5e5ed8945c24f06229cec02e88b0d6bad7008a4b96f43088`；
- 源码起止均为 `c1a158645722a968282761b3cf3c69c82ca6e49326a0a0dfa16bee62330ada56`；
- `whole_study_source_stable=true`；
- `base_config_is_finest_level=true`；
- 3 次唯一运行；
- 三个时间层全部通过；
- 全状态 Cauchy、能量趋势、三项动力学缺陷趋势和全部最细层阈值均通过。

| 层级角色 | 能量指标 | 局部缺陷 | 带符号累计 | 绝对累计 |
|---|---:|---:|---:|---:|
| 粗层 | `7.4014e-14` | `2.2197e-11` | `3.0119e-12` | `4.5889e-11` |
| 中层 | `6.0649e-16` | `1.5256e-12` | `2.7463e-12` | `9.6926e-12` |
| 生产最细层 | `4.5171e-16` | `1.5092e-12` | `2.7453e-12` | `9.6856e-12` |

表中的很小数值不能被提升为一般精度定理；它们只属于本冻结配置和本经验资格门。

## 5. Cable 正式收敛证据

报告：`y_pendulum_forward_solver/validation/cable_convergence.json`  
报告 SHA-256：`7eae68f0fafb8083adbe6c14c568cb5b267f22c17fa7897020fa06afaa3dcd72`

- 结论：`REFINEMENT_SUPPORTED`；
- 生产配置规范哈希：`f76f5587eb298473b983cf05f995fb212f40e9d490ef022f267723e03f53188f`；
- 源码起止均为 `c1a158645722a968282761b3cf3c69c82ca6e49326a0a0dfa16bee62330ada56`；
- `whole_study_source_stable=true`；
- `base_config_is_finest_level=true`；
- 7 次唯一运行；
- 空间、求积、时间三项研究全部通过；
- 九个层级结果全部通过；
- 空间、求积、时间研究的全状态 Cauchy、适用的能量趋势、守卫预算和全部最细层阈值均通过；三项动力学缺陷趋势只在时间研究中适用并全部通过，空间与求积报告的对应 `true` 是 `N/A (time-only)`。

### 5.1 研究摘要

| 研究 | 结论 | 报告的归一比值观察阶 | 最细层阈值 | 边界反力门 |
|---|---|---:|---|---|
| 空间 | 通过 | `1.56698` | 全部通过 | 通过，`3.3849e-3 → 1.5055e-3 → 7.1922e-4 N` |
| 求积 | 通过 | `0.03662` | 全部通过 | 通过/处于冻结地板 |
| 时间 | 通过 | `2.46983` | 全部通过 | 通过/处于冻结地板 |

求积观察阶接近零不被解释成一个新的结构性结论；该研究的层间差已进入冻结误差地板，资格依赖原始差、阈值、规范门和全部**适用**趋势的联合结果，不把 time-only 动力学趋势当作求积下降证据。

### 5.2 时间层动力学证书

| 层级角色 | 能量指标 | 局部缺陷 | 带符号累计 | 绝对累计 | 绝对累计原始最细阈值门 |
|---|---:|---:|---:|---:|---|
| 粗层 | `2.0097e-12` | `1.7828e-4` | `2.3419e-8` | `2.8332e-6` | 不适用；只查非负有限与趋势 |
| 中层 | `1.9967e-12` | `1.8289e-4` | `2.3045e-8` | `9.5979e-7` | 不适用；只查非负有限与趋势 |
| 生产最细层 | `1.9918e-12` | `1.8094e-4` | `2.2785e-8` | `3.0630e-7` | 通过，阈值 `2.0e-6` |

粗层绝对累计量高于生产最细层阈值是故意粗化的数值误差，不是物理失败。报告保留 `raw=false`，同时以 `accuracy_threshold_role=refinement_coarse_level_finite_trend_only` 明确只施加非负有限与趋势门；生产层 `raw=true` 且作为 `qualified_finest_level` 施加绝对门。这一语义与数值理论一致。

## 6. 规范参考运行

### 6.1 Torus

- `COMPLETED/SUCCESS_SINGLE_RUN`；
- $\tau=2.0\,\mathrm{s}$；
- 1001 个规范状态样本，201 个有效正交观测样本；
- 相对能量漂移 `4.5171e-16`；
- 未平方环面残量 `1.3878e-16`；
- 物理分支残量 `2.2204e-16`；
- `min_Q_T=0.4206514637`；
- 源码起止稳定且配置哈希与生产配置一致。

NPZ 含 26 个数组字段，`X_torus` shape 为 `(1001,4)`，所有数值数组有限；CSV 有 1001 个数据行和一个表头。

### 6.2 Cable

- `COMPLETED/SUCCESS_SINGLE_RUN`；
- $\tau=0.12\,\mathrm{s}$；
- 7681 个规范状态样本，13 个有效正交观测样本；
- 节点位置和速度 shape 均为 `(7681,81,3)`；
- 相对能量—功率残量 `1.9918e-12`；
- 理论牵引—代数反力最大差 `7.1922e-4 N`；
- 三类耗散最小值均为 0，没有负耗散；
- 源码起止稳定且配置哈希与生产配置一致。

NPZ 含 466 个数组字段，所有数值数组有限；CSV 有 7681 个数据行和一个表头。

`SUCCESS_SINGLE_RUN` 仍只是规范参考轨迹的单跑状态；其生产配置是否可用于正式预测由第 4、5 节的独立 `REFINEMENT_SUPPORTED` 报告提供证据。

## 7. 有限联合预测集合

目录：`y_pendulum_forward_solver/validation/reference_ensemble_torus/`

- `SAMPLED_PREDICTION_SET_COMPLETE`；
- 集合规范哈希 `743da929bae5c80d8a6305d423181772b2aa48973bcfef675caabaf1adf81ca9`；
- 两个 Torus 成员全部保留；
- 概率权重和为 1；
- 两个成员均为 `COMPLETED/SUCCESS_SINGLE_RUN`；
- 集合源码起止哈希相等；
- 五类不确定性分栏齐全；
- `validation_errors=[]`。

该产物证明有限成员执行、身份、权重和保留合同可运行，不证明两个成员覆盖连续联合不确定集。

## 8. 失败证据与修正历史

`validation/cable_convergence_failed_prefine_gate_2026-08-21.json` 的 SHA-256 为：

`7457ef0d2dc3f13a6570daaec7519e77d7ae8006f3bc29459afc82be7359f325`

这份报告保留了一个真实的 NO-GO 历史：旧资格实现把生产最细层的绝对动力学缺陷上限错误施加到故意粗化的时间层。粗、中、细绝对累计量分别为 `2.8332e-6`、`9.5979e-7`、`3.0630e-7`，本身严格下降，但粗层被错误否决。

修正没有改变阈值或生产配置，而是把数值理论原已要求的职责分离落实到程序：所有层继续强制结构、身份、守卫、耗散、质量、规范输出和非负有限性；能量与三项动力学绝对精度上限只施加到生产最细层；本次时间研究的三层仍全部参加逐项动力学趋势。失败报告未被覆盖，便于复核修正不是事后调参。

## 9. 安全复核命令

下列命令把全部新结果写入由 `mktemp` 创建的 `/tmp` 唯一目录，不会覆盖已经由 artifact manifest 绑定的 `validation/` 正式产物。它们是冻结交付后的安全复核命令；最初生成正式证据时使用的等价命令不得在冻结交付树上原地重放。若要把一次新运行提升为正式证据，必须重新独立验收并重建 manifest 与 delivery root。

```bash
cd '/home/cjt/Desktop/iypt/5 Y形摆/前向理论数值计算/y_pendulum_forward_solver'

PYTHONPYCACHEPREFIX=/tmp/yps-pycache python3 run.py self-test

YPS_STAGE2_REPRO_ROOT="$(mktemp -d /tmp/yps-stage2-repro-XXXXXXXX)"

PYTHONPYCACHEPREFIX=/tmp/yps-pycache python3 run.py converge \
  configs/torus_example.json \
  --output "$YPS_STAGE2_REPRO_ROOT/torus_convergence.json"

PYTHONPYCACHEPREFIX=/tmp/yps-pycache python3 run.py converge \
  configs/cable_example.json \
  --output "$YPS_STAGE2_REPRO_ROOT/cable_convergence.json"

PYTHONPYCACHEPREFIX=/tmp/yps-pycache python3 run.py run \
  configs/torus_example.json \
  --output "$YPS_STAGE2_REPRO_ROOT/reference_torus" --no-plots

PYTHONPYCACHEPREFIX=/tmp/yps-pycache python3 run.py run \
  configs/cable_example.json \
  --output "$YPS_STAGE2_REPRO_ROOT/reference_cable" --no-plots

PYTHONPYCACHEPREFIX=/tmp/yps-pycache python3 run.py ensemble \
  configs/ensemble_torus_example.json \
  --output "$YPS_STAGE2_REPRO_ROOT/reference_ensemble_torus"

printf '%s\n' "$YPS_STAGE2_REPRO_ROOT"
```

Cable 正式加密计算量显著大于单次运行。为保护证据身份并避免工作站资源争用，正式运行应串行执行，期间不修改可执行源码或生产配置。

## 10. 文件级完整性

载荷清单：`y_pendulum_forward_solver/validation/artifact_manifest.json`

载荷清单 SHA-256：`0a12aabf4bc47bf43828735736050340c4376d3aeec350d3fe30e004e94137ff`

交付根：`y_pendulum_forward_solver/validation/delivery_root.json`

artifact manifest 逐文件记录相对路径、字节数和 SHA-256，覆盖冻结理论、数值理论、活动程序、配置、测试、正式报告、失败报告、参考轨迹和集合结果；排除缓存、临时文件、历史 Ritz 程序、manifest 自身、本记录和交付根。`delivery_root.json` 绑定 manifest 与本验收记录，最终交付以交付根文件的 SHA-256 作为外部信任锚。

## 11. 自检判定

阶段 2 的本地工程自检条件均已满足，因此本记录给出 **GO 候选**：

- 数值理论与活动程序一致；
- 双前向后端绑定冻结理论；
- 106 项测试通过；
- Cable 三类正式加密通过；
- Torus 正式时间加密通过；
- 参考轨迹与集合示例已在当前源码身份下重生；
- 旧 Ritz 程序不再作为活动后端；
- 高保真和结构性内容未混入本阶段。

最终是否把阶段 2 冻结为 GO，由独立只读阶段门在同一交付根上复验；若源文件、生产配置、阈值、报告或 manifest 再发生变化，本结论自动失效，必须重新绑定和复门。

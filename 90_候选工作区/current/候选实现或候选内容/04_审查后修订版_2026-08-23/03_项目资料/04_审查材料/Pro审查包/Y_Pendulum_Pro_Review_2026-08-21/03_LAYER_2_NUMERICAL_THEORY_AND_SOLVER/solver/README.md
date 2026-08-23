# Y 形摆前向预测理论数值求解器

这是 IYPT 2027 第 5 题 Y 形摆的研究级前向计算后端。它忠实计算已冻结的前向预测理论，允许未来随理论版本模块化修改；不以发布打包、安装器或长期 API 兼容为目标。

本目录严格不包含：

- 第一性原理高保真模型；
- 高保真—前向比较结论；
- 频率、共振、稳定性、分岔或其他结构性理论。

这些内容分别属于后续阶段，不能用本程序的图或时序替代。

## 1. 冻结身份

活动物理后端为：

- `FWD-CABLE-1.0`：三支有限质量、可伸长、仅受拉轴向柔索；
- `FWD-TORUS-1.0`：首次失张以前的独立四状态环面模型。

两者共同绑定前向理论：

- 文件：`../../理论/IYPT_2027_Y_Pendulum.md`；
- SHA-256：`7eaf18e30087438507aef73c481b49e5b1427a146d79c0fd2b35ca10dc02cdb2`。

当前规范数值模型 ID 为：

- `NUM-FWD-CABLE-P1-Radau-1.0`；
- `NUM-FWD-TORUS-DOP853-1.0`。

旧 15 自由度 Ritz 程序位于相邻历史目录，只作为原型存档，不是当前后端，也不能与本程序共享结果标签。

## 2. 环境与快速运行

依赖为 Python、NumPy、SciPy 和 Matplotlib。当前工作站可直接从源码树运行：

```bash
cd '/home/cjt/Desktop/iypt/5 Y形摆/前向理论数值计算/y_pendulum_forward_solver'
python3 run.py self-test
python3 run.py run configs/torus_example.json --output runs/torus_example
python3 run.py run configs/cable_example.json --output runs/cable_example
```

不需要绘图时可加 `--no-plots`。默认写入器拒绝覆盖非空目录；只有明确传入 `--overwrite`，且目录中没有未知文件时，才会先在同父目录 staging 树写全，再以 backup/staging 两次重命名完成覆盖，并在同步异常时回滚。这不是并发观察或进程崩溃意义下的 `crash-atomic` 单次切换。

核心库接口为：

```python
from y_pendulum_forward import run_config

result = run_config(config_dict)
```

求解器不依赖 GUI。未来统一平台只需消费 `SimulationResult`，不应直接绑定 Cable 或 Torus 内部数组布局。

## 3. 正式收敛资格

冻结交付后的复核必须写入新的临时目标，不能直接覆盖 `validation/` 中已经由 manifest 绑定的正式证据。例如：

```bash
YPS_VALIDATION_REPRO_ROOT="$(mktemp -d /tmp/yps-validation-repro-XXXXXXXX)"

python3 run.py converge configs/torus_example.json \
  --output "$YPS_VALIDATION_REPRO_ROOT/torus_convergence.json"

python3 run.py converge configs/cable_example.json \
  --output "$YPS_VALIDATION_REPRO_ROOT/cable_convergence.json"

printf '%s\n' "$YPS_VALIDATION_REPRO_ROOT"
```

最后一行会打印可复核目录。只有在明确重新生成整套正式证据、独立验收并重建 artifact manifest 与 delivery root 时，才可把新的结果提升为 `validation/` 正式产物。

输入配置就是待认证、待交付的生产最细层，工具不会从它继续生成更细层并把另一个配置暗中称为生产配置。它向后构造两层粗化：

- Cable 空间：生产单元数的 `1/4, 1/2, 1`；
- Cable 求积：生产阶数的 `q-4, q-2, q`；
- Cable/Torus 时间：生产容差的 `16, 4, 1` 倍，最大步长的 `4, 2, 1` 倍；
- 每项研究只改变一个误差源，另外两个保持生产最细设置。

配置中的 `validation` 必须预先冻结 `YPS-FWD-VALIDATION-1.0` 的全部阈值。`numerics.output_dt` 必须等于每项正式研究的 `comparison_time_step`，使最后一层执行配置哈希严格等于生产配置哈希。稀疏展示应在资格轨迹之后抽样，不能改动正式配置。

每一层都必须通过：

- 配置、物理、数值、观测、源码和运行时身份；
- 完整输出网格与初态绑定；
- 状态、拓扑、派生量和物理不变量的独立重算；
- 穷尽守卫注册表、事件和事件左极限；
- 观测时标、掩码、值和错误原因；
- 耗散、质量矩阵或环面几何/张力等结构门。

能量和三项动力学缺陷的绝对精度上限只施加到生产最细层。故意较粗的两层仍必须给出非负有限量；能量参加适用的三层趋势检查，三项动力学缺陷只在时间研究中参加逐项趋势检查，但不会因粗层超过“生产最细层精度阈值”而被误杀。空间/求积报告中的动力学趋势 `true` 是 `N/A (time-only)`，不是实测下降。粗层的 NaN、守卫缺失、负耗散、质量失败或规范输出伪造仍会失败关闭。

动力学证书从返回状态和冻结右端独立重算 Hermite 中点—Simpson 区间缺陷，并分别门控：

- 局部归一化率缺陷；
- 带符号累计缺陷；
- 绝对累计缺陷。

三项各自检查随时间加密的趋势。只看层间轨迹接近、只看求解器成功标志或只看单步局部缺陷都不够。

`SUCCESS_SINGLE_RUN` 仅表示一次离散运行成功；只有正式报告给出 `REFINEMENT_SUPPORTED`，才表示该生产配置在预冻结经验门下获得整段数值支持。它仍不是连续 PDE 的存在唯一性证明或严格区间误差界。

## 4. 有限联合不确定性

示例命令：

```bash
python3 run.py ensemble configs/ensemble_torus_example.json \
  --output runs/ensemble_torus_example
```

集合 schema 为 `YPS-FWD-ENSEMBLE-1.0`。一个集合只能使用一个物理 `model_id`，每个成员必须保留完整配置、权重、物理状态、数值状态、轨迹、事件和观测，并把下列五类来源严格分栏：

- 物理参数；
- 初态；
- 数值误差；
- 观测标定；
- 实验噪声。

失败成员不会被删除。`SAMPLED_PREDICTION_SET_COMPLETE` 只表示每个成员都已执行并保留，不表示所有成员都成功，也不表示有限样本包络了整个连续允许集合。

## 5. 结果合同

每次运行同时返回：

- `contract_status`：冻结物理合同候选状态；
- `numerical_status`：数值求解状态；
- `tau`、`returned_interval` 和全部同刻事件；
- Cable 全局节点场或 Torus 四状态；
- 冻结派生量、能量、功率、反力和守卫；
- 观测值、有效掩码、事件歧义和原因；
- 完整配置与物理/数值/观测/源码/运行时身份。

物理和数值状态不能混称：

- 只有物理谓词失败才返回 `INVALID_INPUT`；
- 数值 schema、资源或积分失败时物理状态留空，并返回相应数值状态；
- 合法物理轨迹上的观测输入错误只使观测无效；
- 明确定位的物理首根才产生 `OUT_OF_SCOPE`；
- 程序不会把求解器失败命名为 `REGULARITY_LOSS`。

规范磁盘结果为：

- `config.snapshot.json`：实际执行的完整配置；
- `result.json`：状态、事件、身份和紧凑诊断；
- `trajectory.npz`：完整无损数组；
- `series.csv`：常用时序；
- 可选 `trajectory.png`、`energy.png`。

`result.json` 对大型数组只记录 shape；真实数组在 `trajectory.npz`，不是被删除。

## 6. 模块和修改入口

```text
y_pendulum_forward/
├── activation.py       # 冻结 P_delta、P'_delta、Phi_delta 和正部
├── cable.py            # P1 材料有限元、事件、D_F 与能量账
├── torus.py            # 四维环面 ODE、张力、几何和事件
├── providers.py        # 支点、空气、点力和分布力注册表
├── initial_fields.py   # 连续初态表示与审计
├── observations.py     # 正交与 Brown–Conrady 相机
├── convergence.py      # 三层整段资格与独立规范重算
├── ensemble.py         # 有限联合预测集合
├── contracts.py        # 身份、严格输入和统一结果
├── runner.py           # 双前向模型调度
├── io.py               # 预检、同父 staging、覆盖保护和同步异常回滚
└── cli.py              # 命令行入口
```

未来修改遵循下面的边界：

1. 新的合法输入函数优先注册到 `providers.py` 或 `observations.py`，未知类型继续失败关闭；
2. 只改变离散算法时更新数值模型 ID、测试和加密证据，不改物理 `model_id`；
3. 改变本构、状态空间、有效域或分支规则时，先形成新前向理论版本和 SHA，再建立新物理模型 ID；
4. 保留旧后端和旧失败报告用于回归，不在旧结果上改标签；
5. 每次可执行源码或生产配置改变后，重新运行完整测试、正式收敛、参考轨迹、集合示例和交付 manifest。

## 7. 当前正式证据位置

- `validation/torus_convergence.json`：Torus 正式时间加密；
- `validation/cable_convergence.json`：Cable 空间、求积和时间加密；
- `validation/reference_torus/`：Torus 规范参考运行；
- `validation/reference_cable/`：Cable 规范参考运行；
- `validation/reference_ensemble_torus/`：有限联合预测集合示例；
- `validation/cable_convergence_failed_prefine_gate_2026-08-21.json`：曾错误把生产最细阈值施加到故意粗层的失败报告，作为审计历史保留；
- `validation/artifact_manifest.json`：交付载荷逐文件哈希；
- `validation/delivery_root.json`：绑定 manifest 与中文验收记录的交付根；
- `../IYPT_2027_Y_Pendulum_前向数值计算阶段2验收记录.md`：人可读验收记录。

报告中的结论和哈希比 README 摘要更具权威性；最终状态以验收记录和交付根为准。

## 8. 已知边界

- P1 是弱式近似，不证明连续强解存在；
- 一般相切事件没有严格区间首根证明，当前使用加密与经验传播预算失败关闭；
- `STATIC_HOLD_RELEASE` 的确定性多初值检查不证明连续泛函全局唯一；
- JSON 只注册有限类输入函数，但注册表保留未来修改入口；
- 当前没有验证性 ODE/PDE 区间积分；
- 当前程序是可运行、可修改的研究代码，不是发布版；
- GUI、高保真后端和结构性研究尚未在本阶段实现。

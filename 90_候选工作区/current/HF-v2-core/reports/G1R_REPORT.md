# HF-v2 G1R 局部模型合同修订报告

## 结论

Pro G1 审查要求的 G1R 局部修订已在候选工作区完成。候选模型身份已从历史的 `HFV2-DISCRETE-CORD-RIGID-BOB-0.1-CANDIDATE` 升级为：

`HFV2-DISCRETE-CORD-RIGID-BOB-0.2-CANDIDATE`

本轮证据允许的结论上限仅为：

`G1R_LOCAL_MODEL_CONTRACT_VERIFIED__HF_NUMERICAL_QUALIFICATION_NO_GO`

这表示新弯曲方程及其解析力、材料参考弧长、状态/质量布局和局部刚体合同在清单绑定的小系统测试中通过；不表示静态求解、时间积分、接触、三锚点、数值算法资格、物理验证或实验验证已完成。

## 审查与历史绑定

本轮从远程 `main` 快进拉取到 Pro 最新交接提交 `d2f6d8e716126a46580f085fb66a82134b144c62`，执行范围由绑定 `4d8777095e90f431d686ae338b754abb430a6a98` 的 Pro G1 审查裁决限定为 G1R。

历史 `0.1` G1 工件没有被改写。字节级 SHA-256 同时由特征测试和 `g1r_metrics.json` 绑定，包括：

- `reports/G1_REPORT.md`；
- `reports/g1_metrics.json`；
- `contracts/acceptance_manifest.json`；
- `contracts/model_identity.json`；
- `contracts/baseline_sources.json`。

新增的 `model_identity_0_2.json`、`g1r_acceptance_manifest.json`、`g1r_module_manifest.json`、`G1R_REPORT.md` 和 `g1r_metrics.json` 只描述 `0.2-CANDIDATE` G1R，不追溯改写历史 G1 结论。

## 新弯曲方程与解析力

对非零 $EI_i$，相邻单位切向为 $t_{i,-}$ 与 $t_{i,+}$ 时，生产弯曲能改为：

$$
\boldsymbol\kappa_i=
\frac{2\,t_{i,-}\times t_{i,+}}
{1+t_{i,-}\cdot t_{i,+}},
$$

$$
U_i=
\frac{EI_i}{2\bar\ell_i}
\left\lVert\boldsymbol\kappa_i\right\rVert^2,
\qquad
\bar\ell_i=\frac{\ell^0_{i,-}+\ell^0_{i,+}}{2}.
$$

代码中的节点力是该能量的闭式解析负坐标梯度，生产路径没有调用有限差分、自动换式、分母裁剪或备用力。当 $EI_i=0$ 时，数学零刚度分支在构造段切向和曲率分母前返回精确零能、零力。

对三类冻结样例，最终相对步长 $10^{-6}$ 的力—能量中心差分相对误差为：

- 平面：`2.9228e-11`；
- 三维：`8.0235e-11`；
- 近反平行但仍合法：`1.9548e-8`。

三者均低于未放宽的 `5e-7` 门槛，且都在首个舍入主导最小值之前存在至少三步连续严格下降区间。

当转角按 $\pi-0.2$、$\pi-0.1$、$\pi-0.05$、$\pi-0.025$ 趋近 $\pi$ 时，弯曲能为 `23.8402`、`95.8400`、`383.8400`、`1535.8400 J`，相邻增长比均大于 `3.9`。精确反平行因 $1+t_{i,-}\cdot t_{i,+}=0$ 而失败关闭，不再是“有限能量加外围角度 guard”。

直杆零能/零力/中心差分零梯度、共同刚体运动客观性、内力合力合矩和光滑圆弧加密趋势也均通过。圆弧四层误差从 `1.5780e-3 J` 逐层下降到 `1.9836e-4 J`；这是所列小系统的趋势检查，不是整机网格收敛资格。

## 材料、布局与刚体合同

- `MaterialSegment.rest_length` 不再是构造参数，只读派生为 $S_{\mathrm{end}}-S_{\mathrm{start}}$。测试证明无法构造与材料坐标不一致的静长，分支总静长等于端点材料坐标差，细分前后总质量和串联等效轴向刚度不变。
- `HFV2State` 和 `MassProperties` 都保存不可变、唯一且逐项精确的 `free_node_ids`。两个自由节点交换顺序后，状态—拓扑、质量—拓扑和质量—状态检查都失败关闭。
- 刚体惯量除对称正定外，现在还要求主惯量满足三角不等式。正定但不可实现的 `diag(1, 1, 3)` 被拒绝。
- `total_linear_momentum` 对速度输入和最终动量都执行有限性检查。
- `SO3_ROUNDOFF_TOLERANCE=2e-12` 被输入旋转、群乘法输出、状态和客观性审计共用。清单冻结的三个多轴案例覆盖不同步长及 `10000`、`12000`、`20000` 次更新，最大正交误差为 `1.0261e-12`，最大行列式误差为 `3.4484e-13`。

## 证据链与架构检查

`tools/generate_g1r_evidence.py` 是单一确定性复算入口。它从当前源码、`g1r_acceptance_manifest.json` 和 `g1r_module_manifest.json` 重算指标，生成规范化 JSON；`--check` 模式要求重算结果与已提交证据逐字节一致。

`g1r_metrics.json` 绑定：

- 所有 `src/ypendulum_hfv2/**/*.py` 源文件的 SHA-256；
- 验收清单、模块分类清单、`0.2` 模型身份和证据生成器的 SHA-256；
- Python `3.12.3` 和 NumPy `1.26.4`；
- 历史 `0.1` G1 工件的 SHA-256；
- 有限差分步长序列、最终误差、明确下降区间与每项门槛。

模块清单自动发现并分类包内全部 `17` 个 Python 模块；任何新增但未分类的模块都使门失败。其中 `11` 个生产合同/物理模块执行反向依赖和静态源码扫描，结果是：未分类文件 `0`、清单缺失文件 `0`、禁用导入 `0`、SciPy 求解器导入 `0`、`try` 语句 `0`、随机调用 `0`。

这一架构证据只证明所分类和所扫描源码的上述可观测属性，不声称已在一般意义上证明“任意 fallback 绝对不可能”。

## 已执行的验证

在一次性隔离环境 `/tmp/ypendulum-hfv2-g1r.uFTZIJ/venv` 中执行：

```bash
python -m pytest -q
python -m ruff check src tests tools
python -m compileall -q src tests tools
python tools/generate_g1r_evidence.py --check
```

结果：

- 候选完整测试：`57 passed, 0 failed, 0 skipped`；
- Ruff：通过；
- `compileall`：通过；
- G1R JSON 证据重算逐字节检查：通过。

另行完成了全部候选 JSON 解析、Markdown 数学分隔符检查、Pandoc Markdown 解析、HTML 渲染及渲染产物检查，以及候选包隔离安装和仓库外部导入烟雾测试。

## 修改边界与未执行项

本轮实质修改仅位于 `90_候选工作区/current/HF-v2-core/**`，另按仓库规范更新了 `90_候选工作区/交接说明_current.md` 和 `90_候选工作区/交接说明_history.md`。

正式理论 `01_最终理论/**`、正式程序 `02_模拟程序/**`、顶层 `AGENTS.md`、既有目录结构、UI、公共 API 和 HDF5 均未修改。

未实现或未执行：

- P2 无接触静态制备、KKT、稳定性与多种子；
- P3 静态硬接触；
- P4 平滑动力学、时间阶和能量收敛；
- P5 张紧—松弛活动集；
- P6 动态硬接触，状态仍为 `CLOSED_PENDING_PRO_REVIEW`；
- P7 公共 API、配置、结果、HDF5 和 UI 适配；
- P8 三锚点、空间/时间加密、性能与正式提升；
- 模型间收敛极限比较、数值算法资格、物理验证和实验验证。

因此正式数值资格继续为 `HF_NUMERICAL_QUALIFICATION_NO_GO`。按 Pro 审查门，本轮在 G1R 停止；只有 Pro 再审通过且用户再次明确要求继续时，才允许进入 P2。

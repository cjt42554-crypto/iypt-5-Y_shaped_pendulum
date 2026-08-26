# 交接说明（current）

更新时间：2026-08-26 23:39 +0800（HF-v2 G1R 完成，等待 Pro 复审）

## 1. 当前结论

G1R 候选实现提交为：

`55cb5db754adde63af77363b3d2d59aa4c9a31d9`

候选模型身份为：

`HFV2-DISCRETE-CORD-RIGID-BOB-0.2-CANDIDATE`

本地证据允许的结论上限仅为：

`G1R_LOCAL_MODEL_CONTRACT_VERIFIED__HF_NUMERICAL_QUALIFICATION_NO_GO`

P2 仍未开放。只有 Pro 对上述候选提交复审通过，且用户再次明确要求继续，才允许进入 P2。

正式数值资格仍为 `HF_NUMERICAL_QUALIFICATION_NO_GO`，动态硬接触仍为 `CLOSED_PENDING_PRO_REVIEW`。

## 2. G1R 完成内容

主要修订位于 `90_候选工作区/current/HF-v2-core/`：

1. 弯曲能改为离散曲率 binormal 二次能，生产力为闭式解析负梯度；无分母裁剪、有限差分力或备用换式。
2. 非零刚度下精确反平行由方程分母退化而失败关闭；零刚度在计算切向/分母前返回精确零能和零力。
3. `MaterialSegment.rest_length` 只读派生为 `material_end - material_start`，消除材料坐标与静长的双重真值。
4. `HFV2State` 和 `MassProperties` 都绑定逐项精确的不可变 `free_node_ids`，同数量顺序错配会失败关闭。
5. 增加主惯量三角不等式、线动量有限性和共享 `SO(3)` 舍入容差合同。
6. 增加清单驱动的确定性 G1R 证据生成器、全包模块自动发现/分类和失败关闭架构审计。
7. 历史 `0.1` G1 报告、指标和合同保持字节不变，并由 SHA-256 特征测试绑定。

完整报告与机器可读证据位于：

- `90_候选工作区/current/HF-v2-core/reports/G1R_REPORT.md`；
- `90_候选工作区/current/HF-v2-core/reports/g1r_metrics.json`；
- `90_候选工作区/current/HF-v2-core/contracts/g1r_acceptance_manifest.json`；
- `90_候选工作区/current/HF-v2-core/contracts/g1r_module_manifest.json`。

## 3. 已执行验证

在 Python `3.12.3`、NumPy `1.26.4`、pytest `8.4.2`、Ruff `0.16.4` 的一次性隔离环境中：

- 全部候选测试：`57 passed, 0 failed, 0 skipped`；
- Ruff：通过；
- `compileall`：通过；
- `python tools/generate_g1r_evidence.py --check`：通过；
- 10 个候选 JSON 文件解析：通过；
- README 与 G1R 报告的 Pandoc Markdown 解析、MathML HTML 渲染、Chrome 实际渲染目视检查：通过；
- 候选包从仓库拷贝隔离构建安装并在仓库外导入：通过；
- 正式理论、正式程序和顶层 `AGENTS.md` 差异：无。

关键数值：

- 弯曲力—能量最终差分相对误差：平面 `2.9228e-11`、三维 `8.0235e-11`、近反平行 `1.9548e-8`，均低于 `5e-7`；
- 转角趋近 $\pi$ 的四级能量递增比均大于 `3.9`；
- 圆弧四层误差严格逐层下降；
- 三个多轴 `SO(3)` 更新案例的最大正交误差 `1.0261e-12`，低于共享门槛 `2e-12`；
- `17/17` 包内 Python 模块已分类，未分类与清单缺失均为 `0`。

## 4. 下一次唯一任务

请 Pro 对候选提交 `55cb5db754adde63af77363b3d2d59aa4c9a31d9` 执行独立只读复审，至少检查：

1. 新离散曲率能的解析负梯度符号、方程域与近反平行证据；
2. 零刚度分支是数学分支而不是 fallback；
3. 参考弧长唯一真值与细分不变性；
4. 状态/质量布局绑定是否足以阻止后续组装错配；
5. 证据生成器、阈值清单、源码哈希和模块自动发现是否形成完整证据链；
6. 是否允许 P2 在新的用户继续指令下开始。

在 Pro 明确裁决前，不实现、不运行 P2 静态制备/KKT/多种子，不接入任何静态或动态接触，不运行三锚点，不修改正式理论、正式程序、UI、公共 API 或 HDF5。

# 交接说明（current）

更新时间：2026-08-27 01:25 +0800（HF-v2 P2 / G2 候选完成）

## 1. 当前结论与停止门

P2 预冻结提交：

`2c91306`

P2 实现与 G2 证据提交：

`3d507bb0c82e8a0a8e7560b4f80a8ddefb2ea2f1`

候选 G2 状态：

`PASS_G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONAL_ONLY`

允许结论：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED__HF_NUMERICAL_QUALIFICATION_NO_GO`

当前必须停止于：

`G2_PRO_REVIEW_REQUIRED`

正式总状态仍为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

静态和动态硬接触均未开放。不得自动进入 P3。

## 2. 本轮实际完成

工作路径仅位于：

`90_候选工作区/current/HF-v2-core/`

完成内容：

1. 在任何目标结果前冻结质量集总、唯一 BFGS、容差、三个确定性种子、Y 锚点、净空和 G2 阈值；
2. 建立强制绑定拓扑、状态、质量、材料段顺序和广义坐标切片的静态组装器；
3. 所有静长仅从拓扑材料坐标差派生；
4. 节点质量按参考段对端点各一半集总，支点、共享结点和刚体连接点贡献保持各自真实位置；
5. 组装单边轴向、离散弯曲、重力、浮力和偏心刚体连接的总势能与解析广义力；
6. 实现唯一 BFGS 求解路径，不含 fallback、容差放宽或随机种子；
7. 完成解析竖直小系统、一个正净空 Y 锚点、三个确定性种子和 2/4/8 三层网格；
8. 独立复算反力闭合、正伸长/张力、段长、曲率分母、净空、Hessian、方向曲率和网格趋势；
9. 规范化相对导入并执行分类依赖矩阵，生产求解器不依赖审计/报告层；
10. 生成清单驱动单命令证据、G2 报告和 67 项完整测试。

关键证据：

- 总势能—解析广义力最终相对误差 `4.25997003976729e-10`；
- 竖直解析系统位置误差 `2.220446049250313e-16 m`；
- 三层所选解缩放力残差分别为 `1.2024e-8`、`4.9772e-10`、`9.2388e-10`；
- 三层最小净空分别约为 `0.0788007 m`、`0.0787991 m`、`0.0787984 m`；
- 形状、反力和势能相邻层差值比约为 `0.2490`、`0.2535`、`0.2495`，均小于冻结上限 `0.95`；
- 三层均只有一个连接臂旋转规范零模，其余归一化 Hessian 最小特征值约 `0.04563`。

## 3. 必须保留的证据解释

2 段与 8 段所选 BFGS 候选记录 SciPy 状态 2（精度损失），4 段记录状态 0。优化器 `success` 没有作为门；状态 2 候选依靠预冻结的独立残差、净空和二阶门通过。不得把这写成三个优化器均正常退出，也不得在复审前追加重启、换算法或放宽容差。

第一次未提交证据试算曾为 `NO-GO`，原因是把全局作用—反作用闭合恒等式误写成第二个、比求解器容差更严的平衡残差门。修正后，闭合审计从外力与支点反力合量中扣除尚存的自由广义残差；原始平衡残差仍写入 JSON。没有改动任何冻结阈值、物理参数、几何参数、种子或求解器。

G1R 工件保持字节不变，只作为历史证据；它们不再伪称可针对 P2 新源码重算。

## 4. 证据与复算

主要文件：

- `HF-v2-core/contracts/G2_FROZEN_PROTOCOL.md`；
- `HF-v2-core/contracts/g2_acceptance_manifest.json`；
- `HF-v2-core/contracts/g2_module_manifest.json`；
- `HF-v2-core/reports/G2_REPORT.md`；
- `HF-v2-core/reports/g2_metrics.json`；
- `HF-v2-core/tools/generate_g2_evidence.py`。

在 `HF-v2-core/` 中复算：

```bash
python3 tools/generate_g2_evidence.py --check
ruff check src tests tools
python3 -m compileall -q src tests tools
```

完整测试需要 RC1 表征测试依赖；安全命令见 `HF-v2-core/README.md`。本轮结果为 `67 passed, 1 warning`。警告来自隔离环境中的 Matplotlib `Axes3D` 导入；相关测试通过，P2 候选和 G2 证据不导入 Matplotlib。

G2 报告和预冻结协议均已通过 Pandoc Markdown 解析、HTML/MathML 实际渲染和逐页截图检查。

## 5. 正式树与未执行项

正式 `01_最终理论/**`、`02_模拟程序/**` 和顶层 `AGENTS.md` 未修改。测试构建一度生成未跟踪 `ypendulum.egg-info/`，已移入系统回收站并复核正式树无差异。

未执行：静态接触/KKT、动力学、活动集、动态接触、三锚点压缩目标、正式程序适配、公共 API、HDF5、UI、装置级物理验证和实验验证。

## 6. 下一次唯一任务

下一次只允许 Pro 对提交 `3d507bb0c82e8a0a8e7560b4f80a8ddefb2ea2f1` 做独立 G2 复审。重点复核强绑定布局、连接点质量、旋转解析力、反力闭合定义、规范零模、净空域、状态 2 候选判定和三网格趋势。

即使 Pro 复审通过，也只有用户随后再次明确要求继续，才可讨论 P3；不得自动实现或运行接触。

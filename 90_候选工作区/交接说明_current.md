# 交接说明（current）

更新时间：2026-08-27 19:31 +0800（HF-v2 P3/G3 已完成并判为 NO-GO）

## 1. 当前裁决

本轮先将 GitHub `origin/main` 从 `7d1786474b1d2b9c492a07ab38589dd27888040d` 快进到 Pro 裁决提交：

`fe5063fe739506812fa1dfca4dbf907dd89b4465`

Pro 已批准：

- G2R：`G2R_PRO_REVIEW_PASS__NO_CONTACT_STATIC_ALGORITHM_ONLY`；
- P2：`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`；
- P3：在新的用户继续指令下可开始，但只能实现静态、无摩擦、刚性、单边法向接触，并在 G3 停止。

用户的新继续指令已开启 P3。本轮 G3 最终裁决为：

`NO_GO_G3_STATIC_CONTACT_ALGORITHM`

正式高保真数值资格仍为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

当前强制停止门为 `G3_PRO_REVIEW`。P4、P5、P6、正式程序迁移、公共 API、HDF5、UI、物理验证和实验验证全部关闭。

## 2. 提交与证据身份

- P3 预冻结协议提交：`56c751016ab6e3be13bf7966dc29f20de7bd0f12`；
- P3 结点套筒身份附录 A1 与接触几何提交：`25fac66ea8e6ae157d4ec1e6e5ec872636e8a1ce`；
- P3 实现与 G3 NO-GO 证据提交：`74c6354fbe7e4c3b2e62fd21476fd261681e1245`；
- G3 指标：`90_候选工作区/current/HF-v2-core/reports/g3_metrics.json`；
- G3 指标 SHA-256：`97522f837822e2108bce9fe117ad5a5007e2d48a859a9b7f389481010072aa62`；
- 人类报告：`90_候选工作区/current/HF-v2-core/reports/G3_REPORT.md`。

接触模型身份为：

`HFV2-DISCRETE-CORD-RIGID-BOB-0.3-CONTACT-CANDIDATE`

无接触底层继续保持：

`HFV2-DISCRETE-CORD-RIGID-BOB-0.2-CANDIDATE`

## 3. 已完成实现

1. 只读重建正式 `FIXED_REST_MATERIAL_SOCKETS_PROJECTIVE_V2` 的同支材料域、结点套筒和摆球套筒登记；正式 `model.py` 与 `reference.py` 的 Git blob 和 SHA-256 在证据生成时复核通过。
2. 接触组装身份绑定 P2 静态组装、接触模型、正式登记合同、A1 协议、表面参数、逐约束域和几何容差。
3. 逐身份输出最近点参数、见证点、中心距、间隙、法向、端点梯度和广义雅可比。
4. 对塌缩段、零距离法向、分离的等价最近点、重复规范域和套筒有效域失效执行失败关闭。
5. 唯一主算法为 SciPy SLSQP，固定 `ftol=1e-12`、`maxiter=3000`、`disp=false`；没有 fallback、随机重启、容差放宽或新增种子。
6. 独立审计使用 NNLS 重构乘子，并检查原始、对偶、平衡、互补、活动身份、秩、间隙雅可比、动作—反作用和投影二阶曲率。
7. 单命令生成并逐字节检查 G3 JSON 和 Markdown 报告，同时复算 P2 无接触回归和历史 G2R 等价观测量。

协议附录 A1 在任何目标结果产生前形成。它只把结点套筒非凸补域拆为 `first_outside` 与 `second_outside_first_inside` 两个凸约束身份；物理活动域、正式登记、目标、种子、求解器和阈值均未改变。

## 4. 冻结目标原始结果

唯一目标为 `SYMMETRIC_BOB_TWO_CORD_CONTACT_1`，登记 9 项逐身份约束，要求三个冻结种子全部通过。实际返回候选 `1/3`，通过全部独立门 `0/3`。

### `seed_00_analytic`

- SLSQP 返回 `success=true`，但该字段不作为验收门；
- 摆球位置为 `[0, 0, -0.114] m`；
- 两个正乘子约为 `0.2885322548412712 N` 和 `0.28853225484127115 N`，支撑身份和秩 `2/2` 符合解析预期；
- 另有两项零乘子的上支—下支结点套筒边界落入活动间隙阈值；
- 间隙活动身份共 4 项，活动雅可比秩为 3，而冻结预期是 2 项、秩 2；
- 因此活动身份和满行秩门失败，独立 KKT 总门为 FAIL；
- 位置、正乘子、间隙雅可比、平衡、互补、见证内点裕量和二阶曲率等其余子门通过，但不能抵消活动集失败。

### `seed_01_infeasible_skew`

初始登记状态触发：

`DegenerateContactGeometry: Junction socket projective opening is invalid.`

按预冻结政策失败关闭，没有换种子、换求解器或放宽有效域。

### `seed_02_feasible_counter_skew`

初始状态可登记，但唯一 SLSQP 路径进入：

`DegenerateContactGeometry: Bob socket radial monotonicity left its frozen valid domain.`

按预冻结政策失败关闭，没有 fallback 或重启。

## 5. 已执行验证

- G3 前置接触基准：`21 passed`；
- P2/RC1 定向无接触回归：`57 passed`；
- 候选完整测试：`96 passed`；
- G3 单命令逐字节检查：PASS，SHA-256 为 `97522f837822e2108bce9fe117ad5a5007e2d48a859a9b7f389481010072aa62`；
- Ruff：PASS；
- `compileall`：PASS；
- JSON 解析：PASS；
- `git diff --check`：PASS；
- 新建或实质改写 Markdown 的 Pandoc `--from=markdown` 解析：PASS；
- `G3_REPORT.md` 和候选 README 的 standalone HTML 浏览器实际渲染：PASS，无横向溢出、无控制台错误；
- 正式登记源码 Git blob 与 SHA-256 只读复核：PASS；
- 历史 G2R 指标哈希、三网格主要静态观测量等价和完整中心线趋势：PASS；
- 接触层评估前后 P2 总势能和广义力逐位相同：PASS。

隔离 `.venv` 为完成 RC1 表征测试安装了正式 `pyproject.toml` 已声明的测试运行依赖；该环境被 Git 忽略，没有修改候选或正式依赖合同。

## 6. 下一次唯一任务

下一次只能由 Pro 对 G3 实现、预冻结合同和 NO-GO 根因进行独立审查。重点复核：

1. 正式登记到 HF-v2 逐约束域的映射和 A1 身份拆分；
2. 零乘子结点套筒边界是否按冻结定义必须属于间隙活动集；
3. 活动 4 行、秩 3 与支撑 2 行、秩 2 的独立复算；
4. 两个非解析种子的套筒有效域失败关闭；
5. 下一版协议是保持 NO-GO、重构接触登记/活动定义，还是另行预冻结新的目标；
6. 任何新协议都必须承认当前目标结果已经被观察，不得追溯改写本轮冻结协议。

在 Pro 新裁决和用户新的明确继续指令之前，不得继续修改 P3，不得开始 P4、P5 或 P6。

## 7. 禁止范围和结论上限

- 不得删除零乘子活动约束、改变活动阈值、修改种子或新增兜底后宣称本轮 G3 通过；
- 不得实现摩擦、恢复系数、冲量、动态互补或接触后时间推进；
- 不得修改 P2 轴向、弯曲、刚体、质量或无接触静态方程；
- 不得修改正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、UI、公共 API 或 HDF5；
- 当前证据不是装置预测、物理验证或实验验证。

正式理论与正式程序在本轮均未修改。

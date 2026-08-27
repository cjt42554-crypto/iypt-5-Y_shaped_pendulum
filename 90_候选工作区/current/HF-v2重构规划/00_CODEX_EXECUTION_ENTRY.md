# HF-v2 核心重构：Codex 执行入口

## 1. 当前状态

G2R 已通过 Pro 独立复审：

`G2R_PRO_REVIEW_PASS__NO_CONTACT_STATIC_ALGORITHM_ONLY`

P2 无接触静力算法状态为：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

P3/G3 的冻结历史裁决保持：

`NO_GO_G3_STATIC_CONTACT_ALGORITHM`

Pro 对该 NO-GO 的独立复审裁决为：

`G3_PRO_REVIEW_CONFIRMS_FROZEN_NO_GO__P3R_REQUIRED`

该裁决只确认 `0.3-CONTACT-CANDIDATE` 在冻结 P3 协议下没有取得资格，不表示静态刚性单边接触路线在物理或数学上被否定。

P3R 当前状态为：

`P3R_ELIGIBLE_ON_NEW_USER_INSTRUCTION`

正式高保真数值资格仍为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

P4、P5、P6、动态接触、正式程序迁移、公共 API、HDF5 和 UI 全部关闭。

## 2. 开始下一次任务前必须读取

按以下顺序读取：

1. 顶层 `AGENTS.md`；
2. `90_候选工作区/交接说明_current.md`；
3. 本文件；
4. `09_PRO_G3_REVIEW_AND_P3R_GATE.md`；
5. `08_PRO_G2R_REVIEW_AND_P3_GATE.md`；
6. `HF-v2-core/contracts/P3_FROZEN_PROTOCOL.md`；
7. `HF-v2-core/contracts/P3_PROTOCOL_AMENDMENT_A1.md`；
8. `HF-v2-core/reports/G3_REPORT.md`；
9. `HF-v2-core/reports/g3_metrics.json`；
10. 按需读取当前接触源码、测试、架构和迁移合同。

P3 和 G3 工件是不可变历史证据。下一次不得修改这些文件后把旧结果重写为 PASS。

## 3. 下一次唯一范围：P3R 静态接触协议与接口修正

只有新的用户明确继续指令才能开启 P3R。P3R 仍只处理静态、无摩擦、刚性、单边法向接触，不开始 P4、P5 或 P6。

在任何新的资格目标结果产生前，P3R 必须先冻结新的协议、清单、接触模型身份和接触组装身份。新的身份不得沿用：

`HFV2-DISCRETE-CORD-RIGID-BOB-0.3-CONTACT-CANDIDATE`

P3R 必须完成：

1. 保持全部 P3/G3 合同、报告、指标和哈希不变，使用独立的 P3R/G3R 工件；
2. 用一个自包含适配合同统一正式登记与 A1 的逐约束身份语义；
3. 把有限的套筒有效域违反暴露为有身份、有单位、有符号残差及 Jacobian，而不是只抛异常；
4. 只对非有限状态、塌缩段、零距离法向、分离的等价最近点等真正未定义几何失败关闭；
5. 分别定义近活动集合、正乘子支撑集合、对偶非唯一性和临界锥；
6. 不再把全部零间隙约束满行秩当作 KKT 必要条件；
7. 在真实不等式临界锥上执行二阶审计，而不是把全部弱活动约束当作等式；
8. 把机器清单中的每个前置基准身份显式绑定到测试节点；
9. 将已观察的对称 G3 目标只作为回归，并保留其“四项间隙活动、两项正乘子支撑、活动秩三、支撑秩二”的结构事实；
10. 在结果出现前另行冻结至少一个新的资格目标及确定性多种子；
11. 保持唯一主求解器、固定选项、无 fallback、无随机重启、无罚刚度和无结果驱动容差放宽；
12. 完成 G3R 后停止并交回 Pro。

## 4. G3 复审确认的三个根因

### 4.1 冻结目标预期与正式登记矛盾

目标中上支—下支所需中心距为 `0.012 m`，结点套筒长度为 `0.024 m`。在解析对称位置，上支套筒边界到竖直下支中心线的距离严格等于 `0.012 m`。因为正式活动域保留套筒公共边界，两项上支—下支约束必然具有零间隙和零乘子。

因此，间隙活动身份为四项而正乘子支撑身份为两项是结构事实，不是舍入误差。不得删除零乘子约束以强行匹配旧预期。

### 4.2 有效域异常阻断多种子恢复

当前 `ContactStaticAssembly.evaluate` 对有限的套筒有效域违反直接抛 `DegenerateContactGeometry`，而 SLSQP 只收到接触间隙约束。初始无效种子无法进入求解，初始有效种子的有限试探也可能立即中止。冻结的 `3/3` 多种子门与该接口不相容。

### 4.3 活动秩与二阶门处理弱活动约束不正确

当前 KKT 总门要求全部近活动行满秩；当前二阶门又投影到全部活动行的等式切空间。对 `g=0, lambda=0` 的弱活动约束，这不是一般不等式 KKT 和临界锥的正确处理。P3R 必须保留约束并修正资格数学，而不是删行。

## 5. 禁止事项

当前不得：

- 修改 P3 冻结目标、种子、域、求解器或阈值后把旧 G3 改判为 PASS；
- 覆盖 `P3_FROZEN_PROTOCOL.md`、A1、`g3_metrics.json` 或 `G3_REPORT.md`；
- 把已观察的对称目标重新包装成唯一未见资格目标；
- 将间隙活动集合和正乘子支撑集合混为同一概念；
- 通过删除零乘子约束、提高活动阈值或仅放宽秩门取得表面 PASS；
- 增加求解器瀑布、随机重启、罚刚度、柔顺接触、摩擦或恢复系数；
- 修改 P2 轴向、弯曲、刚体、质量或无接触静力方程；
- 修改正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、公共 API、HDF5 或 UI；
- 开始 P4、P5 或 P6。

## 6. 当前证据入口与验证边界

既有 G3 工件可在 `90_候选工作区/current/HF-v2-core/` 复核：

```bash
.venv/bin/python tools/generate_g3_evidence.py --check
ruff check src tests tools
.venv/bin/python -m compileall -q src tests tools
.venv/bin/python -m pytest -q
```

Pro 本次通过 GitHub 连接器完成提交顺序、合同、源码、目标几何、KKT/二阶代码、测试调用路径和 G3 指标的独立静态复核，并复算解析套筒边界间隙；没有在连接器环境中重新运行上述命令。

完整裁决见：

`90_候选工作区/current/HF-v2重构规划/09_PRO_G3_REVIEW_AND_P3R_GATE.md`

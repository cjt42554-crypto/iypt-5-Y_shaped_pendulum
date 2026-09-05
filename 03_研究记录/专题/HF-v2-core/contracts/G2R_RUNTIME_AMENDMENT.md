# HF-v2 G2R-A1 SciPy 运行时修正附录

状态：`FROZEN_BEFORE_FIRST_VALID_G2R_TARGET_EXECUTION`

冻结时间：2026-08-27T08:57:00Z

## 1. 触发事实

G2R 原预冻结提交 `7a19702` 后，第一次目标尝试使用历史 G2 环境 SciPy 1.11.4。该版本的 `scipy.optimize.minimize(method="BFGS")` 对显式 `options={"c1": 1e-4, "c2": 0.9}` 连续发出：

```text
OptimizeWarning: Unknown solver options: c1, c2
```

本机函数签名核对确认 SciPy 1.11.4 的 `_minimize_bfgs` 没有 `c1`、`c2` 形参。SciPy 1.12 官方 BFGS 选项文档已经列出 `c1` 和 `c2`。因此，原尝试虽然数值上沿用了旧默认值，却没有满足“冻结参数由调用显式控制”的 G2R 阻断修复要求。

该次 `/tmp` 尝试整体作废：不提交其 JSON，不将其 PASS 字段当作 G2R 结果，不据其数值修改任何物理门、等价容差、中心线门、种子、网格或选择规则。

## 2. 修正范围

在第一次有效 G2R 目标运行前冻结以下附加要求：

1. 候选包最低 SciPy 版本从 `1.11` 修正为 `1.12`；
2. 生产求解入口在 SciPy 报告未知求解器选项时失败关闭，不允许只留下警告后继续；
3. G2R 证据必须检查实际运行时 BFGS 实现签名包含 `c1` 和 `c2`；
4. 第一次有效 G2R 目标运行绑定本机既有 CPython 3.12.3、NumPy 2.5.2、SciPy 1.18.1 环境；
5. 原 G2R 的物理方程、BFGS 方法、`c1=1e-4`、`c2=0.9`、`gtol`、`maxiter`、`xrtol`、种子、网格、选择规则和全部通过门保持不变；
6. 与历史 SciPy 1.11.4 G2 结果的五类预冻结等价容差保持不变。若跨版本结果超门，则 G2R 失败，不再调宽容差。

这是一项由公开 API 支持事实触发的运行时兼容性修正，不是根据目标物理结果调参。原 G2R 预冻结记录继续保留；本附录明确披露其发生在一次无效警告运行之后。

## 3. 结论边界

只有在支持 `c1`、`c2` 的运行时中无未知选项警告完成，并通过原 G2R 全部门，才可写：

`G2R_CANDIDATE_PASS_PENDING_PRO_REVIEW__HF_NUMERICAL_QUALIFICATION_NO_GO`

本附录不批准 G2R，不开放 P3，也不改变 Pro 再审停止门。

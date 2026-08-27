# HF-v2 G2R 协议偏离记录

记录版本：`YPS-HFV2-G2R-DEVIATIONS-1.0`

记录时间：2026-08-27T08:43:03Z

## 1. 时间顺序

1. 提交 `2c91306f5da15c0025cf7b4efa3fc861d3075129` 于 2026-08-26T17:02:58Z 预冻结 G2 协议。
2. 目标实现与证据提交 `3d507bb0c82e8a0a8e7560b4f80a8ddefb2ea2f1` 于 2026-08-26T17:30:22Z 完成。
3. Pro 独立复审提交 `3e1cd55b0873cd8fa11585ea5959aac0b79908e7` 于 2026-08-26T19:49:35Z 判定 `G2_PRO_APPROVAL_HOLD_PENDING_G2R`。
4. 本记录在任何 G2R 目标运行前建立。G2R 不追溯声称下列修正从原 G2 目标结果出现前就已冻结。

## 2. 模块依赖清单偏离

预冻结版位于提交 `2c91306f5da15c0025cf7b4efa3fc861d3075129` 的 `contracts/g2_module_manifest.json`：

- SHA-256：`4dcb695d338880102dcd0d128db67ecde3da8b1ab8784864a93a5867ea804102`；
- Git blob：`0d600b95fee42076754ed3bb8c49ab33b1463b49`。

G2 结果提交及当前历史版：

- SHA-256：`b29793ecd4d2653a16dd5215bb7724250b8ad08c84f6e133a63d46f96834064b`；
- Git blob：`00e2ce85d2686d86d5d15221950f32527ab8a2e5`。

完整语义差异只有一处：

```diff
- "physical_core": ["physical_core"]
+ "physical_core": ["physical_core", "state_contract", "topology_contract"]
```

修改原因是 `mass.py` 的类型检查导入指向状态和拓扑合同。该修改使依赖清单与既有源码关系一致，但确实发生在原 G2 预冻结之后，因此原 G2 不再满足“模块审计协议从目标结果前起逐字不变”的强声明。

G2R 使用独立的 `g2r_module_manifest.json`；它在 G2R 目标运行前登记计划新增的 G2R 审计模块，不覆盖上述两版 G2 清单。

## 3. 闭合审计后验修正

第一次未提交的 G2 目标试算把尚存的自由广义力平衡残差再次作为作用—反作用闭合门，因而得到 `NO-GO`。在观察该结果后，审计被修正为分别保存：

1. 原始平衡残差；
2. 扣除自由广义残差后的内力—支点反力—外力恒等式闭合量。

修正后的闭合量为：

$$
r_F=F_{\mathrm{ext}}+R-\sum_a Q_a-Q_b,
$$

$$
r_M=M_{\mathrm{ext}}+M_R-\sum_a x_a\times Q_a-x_b\times Q_b-R_b\tau_b.
$$

Pro 复审认可该数学定义本身正确，也确认修正没有改变物理方程、参数、种子、求解器或数值阈值。但它属于看到目标结果后的审计定义修正，故当前 G2 只能视为修正后可信证据，不能视为完整无偏预注册结果。

## 4. G2R 处理

G2R 不再改动上述闭合定义，也不把它伪装为原始预冻结定义。G2R 只在新的冻结记录下修复完整组装身份、显式 BFGS 线搜索选项、中心线审计和无量纲段诊断，并用独立 `g2r_metrics.json` 报告修正结果与历史 G2 的等价性。

# HF-v2 P3R3 目标准入与对偶认证修正预冻结协议

冻结时间：2026-08-28T14:02:54+08:00

预冻结源码父提交：`5e28dfec6098451316f82000c5d0428f64078e74`

本协议执行 Pro 裁决：

`G3R2_PRO_REVIEW_CONFIRMS_FROZEN_NO_GO__P3R3_TARGET_ADMISSIBILITY_AND_DUAL_CERTIFICATION_AUTHORIZED`

冻结时，六个候选设计卡的参考发现运行数、目标准入运行数、盆地探针运行数和全部新资格种子运行数均为 `0`。本协议不含任何 P3R3 新参考坐标、乘子、曲率、盆地或资格结果。

## 1. 身份、范围与历史裁决

历史状态逐项保持：

- `NO_GO_G3_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`；
- `HF_NUMERICAL_QUALIFICATION_NO_GO`。

P3R3 使用新的候选模型身份：

`HFV2-DISCRETE-CORD-RIGID-BOB-0.6-CONTACT-CANDIDATE`

新的接触认证组装身份为：

`YPS-HFV2-CONTACT-ASSEMBLY-IDENTITY-4.0`

新的复合算法身份为：

`YPS-HFV2-P3R3-COMPOSITE-SLSQP-PROJECTED-QUASI-NEWTON-1.0`

新的目标准入身份为：

`YPS-HFV2-P3R3-TARGET-ADMISSIBILITY-1.0`

新的对偶认证身份为：

`YPS-HFV2-P3R3-CENTERED-DIMENSIONLESS-DUAL-CERTIFIER-1.0`

新的局部盆地身份为：

`YPS-HFV2-P3R3-SCALE-NORMALIZED-LOCAL-BASIN-1.0`

独立包命名空间为 `ypendulum_hfv2_p3r3`。P3R3 只修正目标准入、局部稳定分支与盆地、对偶区间认证、投影恢复 Jacobian 身份和证据分类。P2 势能、P2 广义力、刚性无摩擦单边法向接触间隙、套筒有效域和正式登记语义逐比特继承 P3R2，不改变物理接触本构。

## 2. 历史证据与已观察分支不可变

`p3r3_acceptance_manifest.json` 绑定 P3/G3、P3R/G3R 和 P3R2/G3R2 的协议、清单、源码、报告、指标及 SHA-256。历史 G3R2 指标保持：

`b9580859b3eccbaf21ee240b911d2c83354ffe7a88916612f6993efdeab2bfe8`

P3R2 的非对称 32/41 度参考、1.4 倍尺度参考及其已发现稳定分支都已经观察，只能作诊断回归。不得把它们重新命名、缩放或微扰后包装成 P3R3 未观察资格目标，也不得修改 P3R2 的目标、种子、算法、门槛、LP 结果、报告、指标或哈希后重跑改判。

P3R 35 度目标、三个原种子和旧混合标量门 `1.0e-8` 逐值保留，继续作为强制历史回归。

## 3. 四段式提交与运行顺序

P3R3 使用以下有序 Git 边界：

1. 本协议、机器清单、设计卡和新身份；所有新运行计数为零；
2. 独立包、测试、参考发现器、准入器、对偶认证器、恢复闭合和证据工具；仍不保存任何新参考或新资格种子结果；
3. 前两项进入 Git 历史后，执行固定设计卡的参考发现和独立准入；只有每类至少一个参考通过时，才冻结两个参考、分支身份、盆地证书和三个局部种子；此提交的新资格种子运行数仍为零；
4. 第三项进入 Git 历史后，才运行历史回归和两个新目标的资格种子，提交 G3R3 JSON、原始报告和人类报告。

若不足两个类别各有一个参考通过，第三项只提交准入证据和状态 `TARGET_SUITE_NOT_ADMISSIBLE`，不得生成或运行资格种子。

## 4. 候选参考发现与选择规则

机器清单预冻结两个类别、每类三个设计卡。所有设计输入、设计顺序和单一发现种子在本提交中固定。参考发现只用于构造待审参考，不是算法资格结果，其身份为：

`YPS-HFV2-P3R3-REFERENCE-DISCOVERY-PREDECESSOR-COMPOSITE-1.0`

每张设计卡只允许执行一次固定的 P3R2 前代复合算法：固定 SLSQP 后总是执行投影 KKT 恢复。优化器 `success` 不构成参考有效性证据。不得在失败后换发现种子、换算法、放宽阈值或重跑。

六张设计卡全部按机器清单顺序执行并独立分类。每个类别选择按 `design_id` 字典序最小的 `ADMISSIBLE` 参考；不按曲率、残差、乘子、盆地或最终资格表现择优。未被选中的通过参考只作准入诊断，失败参考标记 `TARGET_INVALID`。

## 5. 独立目标准入

参考发现结束后、冻结任何资格种子前，每个候选参考必须执行独立 `TARGET_ADMISSIBILITY`。全部门同时通过才可标记 `ADMISSIBLE`：

1. 模型、组装、坐标、接触登记、规范方向和设计卡身份完整绑定；
2. 全部量有限，套筒有效域最小归一化裕量不低于 `1.0e-5`；
3. 恰有两项预期摆球接触近活动、支撑秩为二，所有非活动物理间隙严格大于 `1.0e-5 m`；
4. 两项规范乘子均严格大于 `1.0e-6 N`，非镜像类别还要求两乘子差的绝对值大于 `1.0e-4 N`；
5. 显式规范乘子通过第 7 节逐分量 KKT 允许带、非负性、互补、作用—反作用和对偶见证门；
6. P2 总势能与广义力相对只读基组装逐比特一致；
7. 真实一侧临界锥最小归一化曲率和正乘子支撑切空间最小曲率均严格大于 `5.0e-4`；
8. 矩阵拉格朗日 Hessian 与独立方向有限差分曲率最大差不超过 `5.0e-5`，非对称度不超过 `3.0e-5`；
9. 规范自由度、临界方向、接触见证参数和局部分支符号均完整记录；
10. 第 6 节局部盆地证书通过；
11. 第 8 节投影拟 Newton 完整复合残差 Jacobian 多步长审计通过。

任何门失败都产生 `TARGET_INVALID`，并且不得为该参考冻结或运行资格种子。`TARGET_INVALID` 不是 `ALGORITHM_SEED_FAIL`。

## 6. 尺度化局部盆地证书与资格种子

沿用 P3R2 的输入派生尺度：

$$
D_q=\operatorname{diag}(L_*,L_*,L_*,1,1,1),
$$

其中 $L_*$ 是绑定组装的最大材料段参考长度。局部盆地半径冻结为无量纲坐标半径：

$$
\rho_{\mathrm{basin}}=2.0\times10^{-4}.
$$

在参考处由两项支撑 Jacobian 与附件旋转规范行构造确定性切空间。切空间基不直接采用可能旋转的 SVD 列，而是按固定广义坐标轴顺序投影后做确定性 Gram--Schmidt；每个方向以最大绝对分量为正完成符号规范。

盆地探针使用固定切向方向集合：三个规范基方向，以及每对基方向的归一化和与差。对每条无向方向在 `0.5 rho_basin` 和 `rho_basin` 的正负端点检查：

- 坐标图、套筒有效域和非活动正间隙；
- 拉格朗日方向曲率不低于 `2.5e-4`；
- 接触 Jacobian 秩和分支符号不改变；
- 有限差分曲率在两个半径层之间保持同号且差值不超过 `1.0e-4`。

盆地证书不调用算法资格求解器。通过后，三个资格种子才由机器生成并冻结：

1. 精确参考；
2. 固定第一组合切向方向的正扰动；
3. 固定第二组合切向方向的反扰动。

扰动半径固定为 `0.25 rho_basin`。种子必须保持在同一预认证分支半径内；不得用跨盆地扰动测试局部恢复。

## 7. 显式见证与对偶区间认证

对规范乘子 $\lambda_0$，先在分量尺度下定义：

$$
A=D_r^{-1}J_A^{\mathsf T}F_*,
\qquad
b=D_r^{-1}\nabla\Pi,
\qquad
\eta_0=\lambda_0/F_*.
$$

允许带同样尺度化为 $\widehat a=D_r^{-1}a_{\mathrm{raw}}$。调用 LP 前直接保存并验证：

$$
\widehat r_0=b-A\eta_0,
$$

$$
s_{\mathrm{upper}}=\widehat a-\widehat r_0.
$$

$$
s_{\mathrm{lower}}=\widehat a+\widehat r_0.
$$

$$
s_{\mathrm{multiplier}}=\eta_0.
$$

显式见证最小松弛不得低于 `-5.0e-12`。LP 使用中心变量 $\delta=\eta-\eta_0$，从而避免在大梯度和窄允许带之间做未中心化消减：

$$
-A\delta\le\widehat a-\widehat r_0,
\qquad
A\delta\le\widehat a+\widehat r_0,
\qquad
\delta\ge-\eta_0.
$$

唯一后端冻结为 SciPy `linprog(method="highs-ds")`，`presolve=true`，原始与对偶可行性容差均为 `1.0e-10`。必须保存后端版本、原始状态、消息、预处理、缩放身份和每次端点调用结果。

若显式见证通过而后端报告不可行，状态必须为 `CERTIFIER_INTERNAL_INCONSISTENCY`，不得清空支撑身份或解释为物理不可行。

双接触区间端点还必须由独立二维半空间顶点枚举复核。该方法枚举两两边界交点和非负轴边界，直接检查全部无量纲不等式。后端与独立端点的最大绝对差不得超过 `5.0e-9 N`；每个端点代回后的最小松弛不得低于 `-5.0e-12`。不得在看到结果后关闭预处理、切换后端或放宽允许带。

## 8. 投影拟 Newton 恢复闭合

P3R3 明确把恢复矩阵定义为：

`YPS-HFV2-P3R3-PROJECTED-QUASI-NEWTON-JACOBIAN-1.0`

它保留 $P(q)^{\mathsf T}H_L$ 主块，但不冒充包含 $\mathrm dP/\mathrm dq$ 的精确 Newton。完整复合残差包括状态相关投影、活动间隙和规范坐标。对尺度化未知量使用中心差分步长：

`3.0e-5, 1.0e-5, 3.0e-6`

独立构造完整复合残差 Jacobian。最细两层完整 Jacobian 的相对差不得超过 `5.0e-4`；拟 Newton 矩阵与最细完整 Jacobian 的相对差不得超过 `5.0e-3`。审计失败时目标不得准入，资格种子阶段则失败关闭。

恢复的固定 SLSQP、活动集、尺度、Hessian 步长、线性求解、最大 Newton 次数和 Armijo 搜索沿用 P3R2。新增候选接受条件：全部活动乘子必须不低于 `0 N`。线搜索还继续保持全部物理间隙、非活动正间隙、严格有效域和坐标图。没有 fallback、随机重启、对角正则、罚刚度或结果驱动容差变化。

## 9. 设计卡与未观察目标规则

机器清单冻结六张设计卡：

- 非镜像类别：`ASYM_A01`、`ASYM_A02`、`ASYM_A03`；
- 几何/载荷尺度类别：`SCALE_S01`、`SCALE_S02`、`SCALE_S03`。

设计卡只冻结输入几何、材料、质量、接触半径、解析驻点位置和唯一参考发现种子。设计卡不是已准入目标；本协议不预言哪个设计会通过。每类按 `design_id` 选择首个通过者，形成两个新的局部稳定双接触目标。非镜像目标必须具有两项不相等正乘子；尺度目标必须具有不同于历史 1.0 和已观察 1.4 的几何尺度。

## 10. G3R3 分类、结论上限与停止门

G3R3 必须分别报告：

- `TARGET_INVALID`；
- `TARGET_SUITE_NOT_ADMISSIBLE`；
- `CERTIFIER_INTERNAL_INCONSISTENCY`；
- `ALGORITHM_SEED_FAIL`；
- 历史回归失败；
- 全部门通过。

不得用目标无效隐藏算法失败，也不得把目标无效计作算法种子失败。

通过状态上限为：

`G3R3_CANDIDATE_PASS_PENDING_PRO_REVIEW__STATIC_CONTACT_LOCAL_BASIN_ONLY`

算法失败状态为：

`NO_GO_G3R3_STATIC_CONTACT_ALGORITHM`

无论结果是 PASS、NO-GO、`TARGET_INVALID`、`TARGET_SUITE_NOT_ADMISSIBLE` 还是 `CERTIFIER_INTERNAL_INCONSISTENCY`，完成证据后都必须停在：

`G3R3_PRO_REVIEW`

不得进入 P4、P5 或 P6，不得实现动力学、摩擦、恢复、罚接触或冲量，不得修改正式理论、正式程序、公共 API、HDF5 或 UI。物理验证与实验验证均未执行，正式高保真总状态继续为 `HF_NUMERICAL_QUALIFICATION_NO_GO`。

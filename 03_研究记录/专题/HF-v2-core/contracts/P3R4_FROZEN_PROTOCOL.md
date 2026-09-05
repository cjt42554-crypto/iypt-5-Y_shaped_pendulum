# HF-v2 P3R4 约束流形准入与算法吸引证据分离预冻结协议

冻结时间：2026-08-28T16:20:00+08:00

预冻结源码父提交：`b0e97f9910996397dac83667e09c8ca9aac73b11`

本协议执行 Pro 裁决：

`G3R3_PRO_REVIEW_CONFIRMS_P3R3_TARGET_SUITE_NOT_ADMISSIBLE__P3R4_MANIFOLD_ADMISSIBILITY_AND_SOLVER_BASIN_SEPARATION_AUTHORIZED`

冻结时，八张 P3R4 设计卡的参考发现、目标准入、二阶数值审计、约束流形收回、目标冻结、资格种子及 G3R4 结果运行数全部为 `0`。本协议不包含任何 P3R4 参考坐标、乘子、曲率、流形收回点、目标、种子结果或资格结论。

## 1. 身份、范围与结论边界

P3R4 使用新的候选模型身份：

`HFV2-DISCRETE-CORD-RIGID-BOB-0.7-CONTACT-CANDIDATE`

新的接触组装身份为：

`YPS-HFV2-CONTACT-ASSEMBLY-IDENTITY-5.0`

新的复合算法身份为：

`YPS-HFV2-P3R4-COMPOSITE-SLSQP-PROJECTED-QUASI-NEWTON-1.0`

新的目标准入身份为：

`YPS-HFV2-P3R4-REFERENCE-STABILITY-AND-MANIFOLD-ADMISSIBILITY-1.0`

新的二阶数值身份为：

`YPS-HFV2-P3R4-RICHARDSON-SECOND-ORDER-CONSISTENCY-1.0`

新的约束流形身份为：

`YPS-HFV2-P3R4-DETERMINISTIC-ACTIVE-MANIFOLD-RETRACTION-1.0`

新的实际算法吸引身份为：

`YPS-HFV2-P3R4-ACTUAL-MULTISEED-ATTRACTION-1.0`

独立包命名空间为 `ypendulum_hfv2_p3r4`。P3R4 只修正认证和资格治理，不改变 P2 总势能、P2 广义力、刚性无摩擦单边法向接触间隙、套筒有效域、材料方程或载荷方程。

历史状态分别保持：

- `G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`；
- `NO_GO_G3_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`；
- `TARGET_SUITE_NOT_ADMISSIBLE`，仅指冻结 P3R3 协议；
- `HF_NUMERICAL_QUALIFICATION_NO_GO`。

P3R3 没有运行资格种子，因此不存在 G3R3 算法 PASS 或 FAIL。P3R4 不得把 `TARGET_SUITE_NOT_ADMISSIBLE` 追溯改写为算法失败。

## 2. 四层证据严格分离

P3R4 的结果必须分别保存并分别判定以下四层：

1. 参考点约束稳定性；
2. 有理论阶次、截断误差和舍入误差模型的二阶数值一致性；
3. 活动接触与规范约束流形上的有限几何和真实势能邻域；
4. 目标与种子冻结后实际执行的复合算法多种子吸引证据。

前三层只用于目标准入。它们不构成求解器吸引域证据。第四层只由实际资格种子运行产生。任何报告不得继续使用 P3R3 的“运行前局部盆地证书”称谓。

## 3. 强制提交与一次性运行顺序

P3R4 使用六段不可倒置边界：

1. 零结果预冻结：本协议、模型/组装/算法身份、二阶误差模型、流形定义、八张新设计卡、选择规则及全零运行计数；
2. 独立实现：新包、测试、三个工具及机器绑定进入 Git 历史，八张新卡仍为零运行；
3. 一次性目标准入：八张卡按冻结顺序各执行一次，提交完整准入指标、选择结果和人类报告，但不生成资格种子；
4. 目标与种子冻结：只有两个必需类别都有选中目标时，才从已提交准入指标生成目标与确定性种子；资格运行计数保持零；
5. G3R4 资格证据：第 4 段提交已经进入远程 `main` 后，才运行固定多种子复合算法；
6. 交接：记录结果并停止在 `G3R4_PRO_REVIEW`。

第 3 段若目标套件不足，必须提交 `TARGET_SUITE_NOT_ADMISSIBLE`，跳过第 4、5 段并直接交接。一次性工具必须拒绝已有输出、部分账本、脏工作树或错误提交身份。

## 4. 新设计卡与选择规则

八张卡属于两个必需类别：

- `asymmetric_unequal_positive_multipliers`：`R4_ASYM_B01` 至 `R4_ASYM_B04`；
- `changed_geometry_and_load_scale`：`R4_SCALE_T01` 至 `R4_SCALE_T04`。

非镜像卡使用冻结解析构造：对分支 $i$，支撑点、分支长度和与竖直方向夹角分别为 $s_i$、$L_i$ 和 $\theta_i$，解析摆球中心深度为 $d$。分支接触半径由输入恒等式冻结：

$$
r_i=d\sin\theta_i-R_b-c_{\min}.
$$

该恒等式只构造设计输入，不预言恢复算法、KKT、二阶或流形准入结果。尺度卡使用未在 P3R3 中出现的比例 `0.82`、`1.05`、`1.30` 和 `1.75`，并逐卡冻结几何、载荷、材料和唯一参考发现种子。

八张卡全部按 `p3r4_design_cards.json` 顺序各运行一次。每类按 `design_id` 字典序选择最小的 `ADMISSIBLE` 卡，不按残差、曲率、不确定度、收回迭代或未来资格结果择优。P3R3 六张已观察卡不得重跑、补选、改名、缩放或微扰后充当新目标，也不得用于校准本协议数值门。

## 5. 固定参考发现算法

每张新卡只允许执行一次 P3R3 固定复合算法作为参考发现器，身份为：

`YPS-HFV2-P3R4-REFERENCE-DISCOVERY-P3R3-COMPOSITE-1.0`

算法顺序固定为 SLSQP 主阶段后始终执行投影拟 Newton KKT 恢复。优化器 `success` 不是准入证据。不得在失败后换种子、换算法、增加 fallback、随机重启、放宽阈值或重跑。

## 6. 第一层：参考点约束稳定性

每个恢复参考必须同时通过：

- 身份完整、全部量有限、严格有效域归一化裕量不低于 `1.0e-5`；
- 恰有两项预期摆球接触近活动且支撑秩为二；
- 全部非活动物理间隙严格大于 `1.0e-5 m`；
- 两项支撑乘子均严格大于 `1.0e-6 N`；
- 非镜像类别两乘子差严格大于 `1.0e-4 N`；
- 分量尺度 KKT、非负性、互补、中心化显式对偶见证、唯一 `highs-ds` 后端及独立二维端点复核；
- 真实一侧临界锥和正乘子支撑切空间最小归一化曲率均严格大于 `5.0e-4`；
- 矩阵拉格朗日 Hessian 与独立方向曲率交叉差不超过 `5.0e-5`，非对称度不超过 `3.0e-5`；
- 物理间隙和有效域 Jacobian、作用—反作用、完整复合残差 Jacobian；
- P2 总势能与广义力相对只读基组装逐比特一致。

P3R3 的中心化对偶、独立端点、临界锥、完整 Jacobian 和 P2 只读实现只作哈希与行为回归。`ASYM_A03` 的历史 `component_scaled_kkt=false` 保持独立失败，不因本协议而消失。

## 7. 第二层：二阶数值一致性

在参考处构造由两项支撑行和一个规范行排除后的确定性三维切空间。方向集合冻结为三个基方向和三对基方向的归一化和、差，共九条无向方向。

对每条方向 $d$，以尺度矩阵 $D_q$ 和固定参考乘子 $\lambda_0$ 计算：

$$
\kappa(h)=\frac{L(q_0+hD_qd;\lambda_0)-2L(q_0;\lambda_0)+L(q_0-hD_qd;\lambda_0)}{h^2E_*}.
$$

该量明确命名为“参考拉格朗日 Hessian 方向审计”，不是流形有限邻域或算法盆地。

冻结三个嵌套无量纲步长：

`4.0e-4, 2.0e-4, 1.0e-4`

理论截断阶次为二阶。两级 Richardson 外推为：

$$
R_{01}=\frac{4\kappa(h/2)-\kappa(h)}{3},
$$

$$
R_{12}=\frac{4\kappa(h/4)-\kappa(h/2)}{3}.
$$

截断不确定度冻结为：

$$
u_{\mathrm{trunc}}=\lvert R_{12}-R_{01}\rvert.
$$

每层中心差分的舍入上界使用 IEEE 754 双精度机器精度 $\epsilon$ 和安全因子 `64`：

$$
u_{\mathrm{round}}(h)=64\epsilon\frac{\lvert L_+\rvert+2\lvert L_0\rvert+\lvert L_-\rvert}{h^2E_*}.
$$

细层 Richardson 舍入上界为：

$$
u_{R}=\frac{4u_{\mathrm{round}}(h/4)+u_{\mathrm{round}}(h/2)}{3}.
$$

总不确定度为 $u=u_{\mathrm{trunc}}+u_R$。每条方向必须满足：

$$
R_{12}-u>5.0\times10^{-4}.
$$

若相邻两组差值都高于各自舍入分辨下界的八倍，还必须同号并给出观测阶次：

$$
p=\log_2\frac{\lvert\kappa(h)-\kappa(h/2)\rvert}{\lvert\kappa(h/2)-\kappa(h/4)\rvert},
$$

且 `1.0 <= p <= 3.0`。若任一差值不能从舍入下界中分辨，则仅当两个差值都不超过相应舍入下界的八倍时标记 `ROUNDING_LIMITED_CONSISTENT`；其他情况失败关闭。不得使用 P3R3 的统一 `1.0e-4` 双半径绝对层差门。

## 8. 第三层：活动约束流形有限邻域

P3R4 明确构造流形坐标。设 $B\in\mathbb R^{6\times3}$ 为参考确定性切空间基，$z\in\mathbb R^3$ 为冻结切向坐标，$x=D_q^{-1}(q-q_0)$。每个探针必须确定性求解六个方程：

$$
g_A(q)=0,
$$

$$
\gamma(q)=0,
$$

$$
B^{\mathsf T}x=z.
$$

其中 $g_A$ 是两项冻结活动物理间隙，$\gamma$ 是附件旋转规范。Newton Jacobian 使用解析活动间隙行、规范行和 $B^{\mathsf T}$；无对角正则或替代求解器。最大 Newton 次数 `15`，无量纲无穷范数收敛门 `1.0e-11`，线搜索固定为 $2^{-k}$，最大回退 `20`，Armijo 系数 `1.0e-4`，线性系统相对最小奇异值门 `1.0e-12`。

有限邻域半径冻结为 `2.0e-4`，半径层为 `0.5` 和 `1.0`，方向集合与第 7 节相同。每个正负端点必须保存并通过：

- 活动间隙最大绝对残差不超过 `1.0e-11 L_*`；
- 切向坐标和规范最大绝对残差不超过 `1.0e-11`；
- 活动行秩保持二，分支行方向相关均为正；
- 非活动物理间隙严格大于 `5.0e-6 m`；
- 有效域最小归一化裕量不低于 `1.0e-5`；
- 相对参考的真实势能增量减去 `64 epsilon` 舍入上界后严格为正。

每对正负收回点还必须给出真实势能中心曲率，并严格大于 `2.5e-4`。本层只证明冻结采样方向上的流形几何安全和势能上升，不证明整个连续球，也不证明求解器吸引域。

## 9. 第四层：目标冻结后的实际多种子吸引证据

通过准入的目标只在第 3 段结果提交后生成。每个目标冻结三个算法初值：

1. 精确参考；
2. 第一非共线组合方向的正偏置；
3. 第二非共线组合方向的负偏置。

偏置半径为流形邻域半径的 `0.25`。偏置种子明确标记为 `solver_initial_guess_allowed_off_manifold`，不要求预先满足活动间隙为零；流形探针则标记为 `constraint_manifold_geometry_probe`，两者不得混用。

第 4 段目标冻结提交进入远程 `main` 后，每个种子只执行同一固定 P3R4 复合算法一次。只有实际收敛并同时通过独立 KKT、分支身份、参考误差、乘子误差、能量一致性、对偶、临界锥、Jacobians、作用—反作用和 P2 只读门，才是算法吸引证据。

每种子参考无量纲无穷误差不超过 `3.0e-6`；乘子误差不超过特征力的 `5.0e-6`；同一目标多种子坐标跨度不超过 `4.0e-6`；势能跨度不超过特征能量的 `5.0e-8`。

## 10. 分类与停止门

目标准入状态必须区分：

- `TARGET_INVALID`；
- `TARGET_SUITE_NOT_ADMISSIBLE`；
- `CERTIFIER_INTERNAL_INCONSISTENCY`；
- `ADMISSIBLE`。

资格状态必须区分：

- `ALGORITHM_SEED_FAIL`；
- `HISTORICAL_REGRESSION_FAIL`；
- `CERTIFIER_INTERNAL_INCONSISTENCY`；
- 全部门通过。

G3R4 候选通过状态上限为：

`G3R4_CANDIDATE_PASS_PENDING_PRO_REVIEW__STATIC_CONTACT_MANIFOLD_AND_ACTUAL_MULTISEED_ONLY`

算法失败状态为：

`NO_GO_G3R4_STATIC_CONTACT_ALGORITHM`

正式总状态无条件保持：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

无论得到目标套件不足、G3R4 PASS、算法 NO-GO、历史回归失败或认证器内部不一致，都必须停止在：

`G3R4_PRO_REVIEW`

## 11. 禁止事项

不得：

- 修改 P3/G3、P3R/G3R、P3R2/G3R2 或 P3R3 的任何冻结协议、源码绑定、设计卡、目标、种子、报告、指标或哈希；
- 重跑 P3R3 六张设计卡或 G3R3 资格工具；
- 使用 P3R3 已观察层差校准本协议阈值；
- 把参考 Hessian 直线差分命名为有限流形邻域或算法盆地；
- 把流形探针当成算法初值结果，或把算法初值当成流形收回点；
- 删除 KKT、对偶、临界锥、Jacobian、作用—反作用或 P2 只读门；
- 增加 fallback、随机重启、求解器瀑布、罚刚度、柔顺接触、摩擦、恢复系数或冲量；
- 修改正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、公共 API、HDF5 或 UI；
- 开始 P4、P5、P6、动力学、动态接触、正式提升、装置级物理验证或实验验证。

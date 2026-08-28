# HF-v2 P3R5 双活动 KKT 参考构造与未观察留出资格预冻结协议

冻结时间：2026-08-28T19:24:00+08:00

预冻结源码父提交：`e1564d76e054eb3655e29531acfc71c99feb3728`

本协议执行 Pro 裁决：

`G3R4_PRO_REVIEW_CONFIRMS_P3R4_TARGET_SUITE_NOT_ADMISSIBLE_WITH_ASSEMBLY_PREFLIGHT_DEVIATION__P3R5_HOLDOUT_REFERENCE_CONSTRUCTION_AUTHORIZED`

冻结时，P3R5 具体留出卡数、输入装配、参考构造、目标准入、二阶审计、流形审计、目标冻结、资格种子和 G3R5 结果运行数全部为 `0`。本协议不包含任何 P3R5 留出参数、参考坐标、乘子、曲率、流形点、目标、种子结果或资格结论。

## 1. 身份、唯一范围与结论上限

P3R5 候选模型身份为：

`HFV2-DISCRETE-CORD-RIGID-BOB-0.8-CONTACT-CANDIDATE`

接触组装身份为：

`YPS-HFV2-CONTACT-ASSEMBLY-IDENTITY-6.0`

双活动参考构造器身份为：

`YPS-HFV2-P3R5-FIXED-DUAL-ACTIVE-PROJECTED-KKT-NEWTON-1.0`

实际资格算法身份为：

`YPS-HFV2-P3R5-COMPOSITE-SLSQP-PROJECTED-QUASI-NEWTON-1.0`

独立包命名空间为 `ypendulum_hfv2_p3r5`，工件使用 `P3R5_*` 和 `G3R5_*` 命名空间。

P3R5 只修正参考构造、未观察留出治理和认证层中彼此误耦合的有限性判定。它不改变 P2 总势能、P2 广义力、刚性无摩擦单边法向接触间隙、材料套筒有效域、材料方程、载荷方程、P3R4 实际复合算法数值行为或任何历史工件。

历史状态保持：

- `G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`；
- `NO_GO_G3_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`；
- P3R3 与 P3R4 的 `TARGET_SUITE_NOT_ADMISSIBLE`；
- `P3R4_ASSEMBLY_PREFLIGHT_DEVIATION`；
- `HF_NUMERICAL_QUALIFICATION_NO_GO`。

## 2. 已观察开发集与未观察留出集

P3R3 和 P3R4 的全部设计卡、参考结果、失败模式和通过指标统一标记为：

`OBSERVED_DEVELOPMENT_AND_REGRESSION_ONLY`

其绑定路径和 SHA-256 冻结在 `p3r5_holdout_domain.json`。这些工件只可用于：

- 开发双活动 KKT 方程、Jacobian、线性代数和失败分类；
- 回归 P3R5 没有改变既有物理组装；
- 解释历史认证器字段之间的误耦合。

它们不得成为 P3R5 资格目标、目标补选或留出泛化证据。P3R4 的 `R4_SCALE_T01` 不得结转；任何 P3R3/P3R4 卡的缩放、改名或微扰只有在零结果域中由预冻结生成规则独立产生、物理签名不重复且按哈希规则选中时，才可能成为新的 P3R5 留出卡。

## 3. 参数域、纯输入谓词与确定性哈希选择

参数格点、派生公式、枚举顺序、已观察尺度排除表和每类四张留出卡的数量冻结在 `p3r5_holdout_domain.json`。两个必需类别依次为：

1. `asymmetric_unequal_positive_multipliers`；
2. `changed_geometry_and_load_scale`。

不对称类别使用解析轴点到两条不同角度上支胶囊相切构造。对分支 $i$，给定深度 $d$、支撑长度 $L_i$、竖直夹角 $\theta_i$、摆球半径 $R_b$ 和最小间隙 $c_{\min}$，冻结：

$$
s_A=(-L_A\sin\theta_A,0,-L_A\cos\theta_A),
$$

$$
s_B=(L_B\sin\theta_B,0,-L_B\cos\theta_B),
$$

$$
r_i=d\sin\theta_i-R_b-c_{\min}.
$$

尺度类别只使用 `p3r5_holdout_domain.json` 中未被 P3R3/P3R4 观察的离散尺度，并按已冻结的长度、刚度、质量与转动惯量缩放律生成。

候选在选择前必须通过纯合同谓词。该谓词不得导入或调用接触组装、参考求解器、KKT、对偶、二阶、流形或资格代码，至少同时证明：

- 所有数值有限；全部长度、半径、尺度、质量、刚度和惯量严格为正；
- 支撑距离与声明分支长度相符，解析相切恒等式成立；
- 对每对材料分支，结点套筒满足 $2(r_i+r_j+c_{\min})<\min(L_i,L_j)$；
- 摆球套筒满足 $R_b+r_{\mathrm{lower}}+c_{\min}<L_{\mathrm{lower}}$；
- 两个解析上支接触见证的材料参数边界裕量不低于 `0.08`；
- 两项声明活动身份存在、唯一且互不重复；支撑、分支和物理签名不塌缩；
- 物理签名与全部 P3R3/P3R4 已观察卡不重复。

开发实现提交进入远程 `main` 后，以该精确提交哈希 `implementation_commit` 参与摘要。每个纯谓词通过候选的排序键为：

$$
\operatorname{SHA256}(\texttt{P3R5-HOLDOUT-1.0}\mathbin{\|}\texttt{NUL}\mathbin{\|}
\texttt{implementation\_commit}\mathbin{\|}\texttt{NUL}\mathbin{\|}
\texttt{category}\mathbin{\|}\texttt{NUL}\mathbin{\|}
\texttt{canonical\_candidate\_json}).
$$

摘要升序、规范 JSON 升序为唯一破同序；每类取前四张。实现提交不得为了改变留出选择而重做、修订或磨取。留出冻结工具不得调用数值求解器。留出冻结提交中的输入装配、参考、准入、二阶、流形、目标和资格运行数必须全部为 `0`。

## 4. 固定双活动投影 KKT 参考构造器

每张卡声明恰好两项活动物理间隙身份，活动集在参考构造中固定，不允许结果驱动增删。设 $q\in\mathbb R^6$ 为摆球平移与旋转向量，$D_q$ 为既有坐标尺度，$D_s$ 为既有驻定尺度，$F_*$ 和 $L_*$ 分别为特征力与特征长度，$\lambda\in\mathbb R^2$ 为声明活动乘子。

附件臂绕自身的规范方向由既有 SO(3) 右 Jacobian 定义。令 $P(q)\in\mathbb R^{6\times5}$ 为该规范方向的确定性正交补，$\gamma(q)$ 为附件臂体轴与旋转向量的规范坐标。无量纲未知量为：

$$
y=\begin{bmatrix}D_q^{-1}(q-q_0)\\ \lambda/F_*\end{bmatrix}\in\mathbb R^8.
$$

完整残差冻结为：

$$
R(y)=
\begin{bmatrix}
P(q)^{\mathsf T}D_s^{-1}\left(\nabla\Pi(q)-J_A(q)^{\mathsf T}\lambda\right)\\
g_A(q)/L_*\\
\gamma(q)
\end{bmatrix}\in\mathbb R^8.
$$

其中 $g_A$ 是两项声明活动物理间隙；$\nabla\Pi=-Q$ 由既有 P2 广义力确定。该方程同时包含五项独立驻定方程、两项活动间隙和一项规范方程，不使用罚项、柔顺接触或松弛活动集。

初值唯一固定为解析构造的摆球位置、零旋转和只在两项声明活动行上执行的分量尺度非负最小二乘乘子。初值生成不得运行 SLSQP、前代复合算法、随机重启或多起点。

Newton 每次迭代使用完整残差的中心无量纲差分 Jacobian，步长固定为 `1.0e-6`。线性求解器固定为 `numpy.linalg.solve`；相对最小奇异值必须不低于 `1.0e-12`；无对角正则。最大 Newton 次数为 `20`。线搜索只允许 $\alpha=2^{-k}$，`k=0,...,20`，Armijo 系数为 `1.0e-4`。

每个候选步必须保持：

- 两项活动乘子非负；
- 最小物理间隙不低于 `-1.0e-10 m`；
- 非活动物理间隙严格大于 `1.0e-7 m`；
- 最小有效域归一化裕量不低于 `1.0e-5`；
- 坐标、乘子、间隙、有效域和残差全部有限。

收敛门为 $\lVert R\rVert_\infty\le 1.0\times10^{-11}$。失败状态固定为：

- `FAIL_CLOSED_DECLARED_ACTIVE_IDENTITY`；
- `FAIL_CLOSED_INITIAL_DOMAIN`；
- `FAIL_CLOSED_LINEAR_SYSTEM`；
- `FAIL_CLOSED_NEGATIVE_ACTIVE_MULTIPLIER`；
- `FAIL_CLOSED_ACTIVITY_OR_DOMAIN_CHANGE`；
- `FAIL_CLOSED_NO_ACCEPTED_STEP`；
- `FAIL_CLOSED_ITERATION_LIMIT`；
- `FAIL_CLOSED_UNDEFINED_GEOMETRY_OR_COORDINATE`。

禁止 fallback、随机重启、容差放宽、活动集替换和结果驱动算法切换。

## 5. 完整 Jacobian 的独立交叉检查

最终参考处必须保存三层完整残差中心差分 Jacobian，步长为：

`3.0e-6, 1.0e-6, 3.0e-7`

以最细层 Frobenius 范数为分母，中层与最细层的相对差不得超过 `5.0e-4`。

独立块 Jacobian 使用：

- 解析活动物理间隙行；
- 解析规范行；
- 固定乘子拉格朗日梯度的中心差分 Hessian，平移和旋转物理步长均为 `2.0e-6`；
- 解析乘子块 $-J_A^{\mathsf T}$。

独立块 Jacobian 与最细完整残差 Jacobian 的相对差不得超过 `5.0e-3`。任一 Jacobian 非有限、层间不一致或块交叉检查失败，均分类为 `CERTIFIER_INTERNAL_INCONSISTENCY`，不得换步长重算。

## 6. 分量 KKT 与中心化对偶必须分离

P3R4 的已观察 `R4_ASYM_B03` 在分量驻定、互补、正乘子、支撑秩、中心化显式对偶、二阶和流形检查上分别有通过证据，但旧 `P3R3KKTAudit.finite` 同时要求一组已被中心化对偶替代的旧双区间端点为有限；该端点为 `NaN` 时使 `component_scaled_kkt=false`。P3R5 不追溯修改 P3R4 结果，也不把 B03 改判为可准入。

P3R5 在零留出结果时冻结以下分离：

- `component_scaled_kkt_finite` 只检查坐标、物理间隙、有效域、乘子、驻定向量、分量尺度、原始/无量纲残差、互补量和秩字段；
- 旧双区间端点不进入分量 KKT 有限性，也不作为 P3R5 对偶证据；
- 对偶可行性只由既有中心化显式见证、唯一 `highs-ds` 后端和独立二维端点复核单独判定；
- 任一真实数值字段出现非有限仍失败关闭。

这只消除两个独立证据层的字段误耦合，不放宽 `1.0e-8` 分量驻定、`1.0e-10 m` 穿透、`1.0e-10 N` 对偶负值、互补、正乘子或秩门。

## 7. 继承的目标准入、二阶与流形门

除第 4 至第 6 节明确冻结的新参考构造和有限性分离外，P3R5 原值继承 P3R4：

- 平移绝对驻定 `1.0e-8 N`，旋转绝对驻定为 `1.0e-8 L_* N`，无量纲分量最大值 `1.0e-8`；
- 穿透最大值 `1.0e-10 m`、对偶负值最大值 `1.0e-10 N`、互补绝对值 `1.0e-12 N m` 与尺度因子 `1.0e-10`；
- 恰有两项近活动摆球接触、两项正支撑乘子、支撑秩二、乘子严格大于 `1.0e-6 N`；
- 不对称类别的两乘子差严格大于 `1.0e-4 N`；
- 非活动间隙严格大于 `1.0e-5 m`，有效域归一化裕量不低于 `1.0e-5`，见证参数裕量不低于 `0.05`；
- 中心化对偶、`highs-ds` 与独立二维端点复核；
- 临界锥和支撑切空间最小曲率严格大于 `5.0e-4`，曲率交叉差不超过 `5.0e-5`，非对称度不超过 `3.0e-5`；
- 三层 Richardson 步长 `4.0e-4, 2.0e-4, 1.0e-4`、二阶截断模型、`64 epsilon` 舍入上界和既有观测阶次规则；
- 流形半径 `2.0e-4`、半径层 `0.5, 1.0`、九条无向方向及正负端点，真实势能中心曲率严格大于 `2.5e-4`；
- 物理间隙/有效域 Jacobian、作用—反作用和 P2 势能/广义力逐比特只读门。

两个必需类别都必须从 P3R5 新留出卡产生 `ADMISSIBLE` 目标。每类按 `holdout_id` 字典序选择最小可准入卡。套件不足时不得冻结部分目标或运行 G3R5。

## 8. 一次性尝试账本

P3R5 准入工具启动后，先读取 Git `HEAD`、工作树状态和启动时间，再以排他创建方式原子写入：

`reports/p3r5_attempt_ledger.jsonl`

创建账本前不得打开、解析或装配具体留出卡。工具命令行必须显式传入预期协议、实现绑定、留出冻结和清单 SHA-256；启动记录先保存这些预期值、尝试编号 `1`、仓库 `HEAD`、工作树状态、零运行计数以及“异常后保留账本并禁止自助重跑”声明。随后才读取文件并逐一核对实际哈希。

账本只能追加，不得截断、重写、删除或以最终结果替换。每张卡依次追加：

1. 输入装配开始与完成；
2. 参考构造开始与完成；
3. KKT/对偶/Jacobian 准入完成；
4. 二阶审计完成；
5. 流形审计完成；
6. 卡分类完成。

每次追加后必须刷新文件和目录元数据。异常、中断、部分输出、错误提交身份或哈希不符必须追加可行的失败检查点并停止。账本存在即拒绝再次 `--run-once`。

留出冻结后发生任何输入装配失败，分类必须为：

`P3R5_PROTOCOL_CONSTRUCTION_FAILURE`

并立即停止；不得修代码后重跑同一留出集。

## 9. 目标、种子与 G3R5 实际算法证据

只有一次性准入提交已进入远程 `main`，且两个类别都完整时，才生成目标与种子冻结提交。每个目标冻结三个实际复合算法初值：精确参考、第一非共线方向正偏置、第二非共线方向负偏置；偏置半径保持流形半径的 `0.25`。

目标冻结提交中的资格运行数保持 `0`。该提交进入远程 `main` 后，每个种子只运行一次 P3R4 数值行为不变的 SLSQP 加投影拟 Newton 复合算法。参考误差、乘子误差、多种子跨度、能量跨度及全部历史回归门原值继承 P3R4。

## 10. 七段提交顺序与失败关闭

P3R5 至少形成七个不可倒置边界：

1. 零结果协议提交；
2. 开发实现提交，只运行已观察 P3R3/P3R4 回归；
3. 留出冻结提交，全部数值运行计数为零；
4. 一次性目标准入提交，包含不可删除账本和全部留出结果；
5. 目标与种子冻结提交，只在两个类别完整时生成；
6. G3R5 资格证据提交，只在第 5 项已进入远程 `main` 后运行；
7. 交接提交并停止在 `G3R5_PRO_REVIEW`。

任一阶段出现协议构造失败、套件不足、认证器内部不一致、历史回归失败或算法 NO-GO，都跳过不再适用的后续数值阶段并进入交接。

## 11. 分类与停止门

留出准入状态必须区分：

- `P3R5_PROTOCOL_CONSTRUCTION_FAILURE`；
- `TARGET_INVALID`；
- `TARGET_SUITE_NOT_ADMISSIBLE`；
- `CERTIFIER_INTERNAL_INCONSISTENCY`；
- `ADMISSIBLE`。

G3R5 候选通过状态上限为：

`G3R5_CANDIDATE_PASS_PENDING_PRO_REVIEW__STATIC_CONTACT_HOLDOUT_REFERENCE_AND_ACTUAL_MULTISEED_ONLY`

算法失败状态为：

`NO_GO_G3R5_STATIC_CONTACT_ALGORITHM`

正式总状态无条件保持：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

无论得到协议构造失败、套件不足、候选 PASS、算法 NO-GO、历史回归失败或认证器内部不一致，都必须停止在：

`G3R5_PRO_REVIEW`

P3R5 失败不自动授权 P3R6。

## 12. 禁止事项

不得：

- 修改 P3 至 P3R4 的协议、源码绑定、设计卡、目标、种子、报告、指标或哈希；
- 重跑或补选 P3R4 卡，或消除 `P3R4_ASSEMBLY_PREFLIGHT_DEVIATION`；
- 用已观察结果调整 KKT、对偶、二阶、流形、Jacobian 或目标门；
- 通过重做实现提交磨取有利留出卡；
- 留出冻结后修实现并重跑同一留出集；
- 增加 fallback、随机重启、容差放宽、罚刚度、柔顺接触、摩擦、恢复系数、冲量或动力学；
- 修改正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、公共 API、HDF5 或 UI；
- 开始 P4、P5、P6、动力学、动态接触、正式提升、装置级物理验证或实验验证。

## 13. 当前验证边界

本协议阶段只冻结治理、数学定义、输入域、身份和计划路径。尚未创建 P3R5 包、具体留出卡、实现绑定、账本、目标、种子或结果；尚未执行 P3R5 输入装配、参考构造、数值认证或资格算法。

正式理论、正式程序、公共 API、HDF5 和 UI 均保持只读。

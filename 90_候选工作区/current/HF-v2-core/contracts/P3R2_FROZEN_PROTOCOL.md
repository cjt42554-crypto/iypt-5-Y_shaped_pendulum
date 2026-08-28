# HF-v2 P3R2 静态接触数值认证闭合预冻结协议

冻结时间：2026-08-28T11:32:10+08:00

预冻结源码父提交：`5b5b288506c8e3eb5e810fe7a569e3ac6f07e3f4`

本协议执行 Pro 裁决
`G3R_PRO_REVIEW_CONFIRMS_FROZEN_NO_GO__P3R2_AUTHORIZED`。冻结时，两个新
资格目标的求解器运行数均为 `0`，动态接触运行数为 `0`。P3、P3R 目标和
证据已经被观察，只能作不可变历史或强制回归，不能充当新资格证据。

## 1. 身份、范围与历史裁决

历史状态保持：

- `NO_GO_G3_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R_STATIC_CONTACT_ALGORITHM`；
- `HF_NUMERICAL_QUALIFICATION_NO_GO`。

P3R2 使用新的候选模型身份：

`HFV2-DISCRETE-CORD-RIGID-BOB-0.5-CONTACT-CANDIDATE`

新的接触组装身份为：

`YPS-HFV2-CONTACT-ASSEMBLY-IDENTITY-3.0`

新的复合算法身份为：

`YPS-HFV2-P3R2-COMPOSITE-SLSQP-KKT-RESTORATION-1.0`

新的尺度合同身份为：

`YPS-HFV2-P3R2-COMPONENT-SCALE-1.0`

独立包命名空间为 `ypendulum_hfv2_p3r2`。P3R2 只闭合静态接触候选生成与
独立 KKT 认证，不改变 P3R 的物理接触域、登记参数域、P2 势能、广义力、
材料、质量、重力、浮力或刚体连接。

## 2. 历史证据不可变

`p3r2_acceptance_manifest.json` 冻结 P3/G3 和 P3R/G3R 合同、报告、指标与
哈希。历史 G3 指标 SHA-256 保持：

`97522f837822e2108bce9fe117ad5a5007e2d48a859a9b7f389481010072aa62`

历史 G3R 指标 SHA-256 保持：

`4da70615db740ca345ae6032dfabac89a8188ffb374890126a41220ffb765241`

当前 35 度目标、三个原种子和旧混合标量门 `1e-8` 均逐值保留。P3R2
不得追溯修改旧报告，也不得把 P3R 的 `2/3` 改写为通过。

## 3. 单一复合算法

每个结构回归、35 度回归和新资格种子都执行同一有序算法：

1. 固定 SLSQP 主阶段；
2. 固定投影 KKT 恢复阶段。

恢复阶段无条件进入。若 SLSQP 后已经满足恢复终止门，仍记录
`CONVERGED_AT_ENTRY`、完整入口残差和零 Newton 更新；这不是跳过恢复。
恢复阶段不是失败触发的 fallback，也不允许转交其他求解器。

### 3.1 固定 SLSQP 主阶段

唯一主优化调用仍为 `scipy.optimize.minimize(method="SLSQP")`：

```text
ftol = 1e-12
maxiter = 3000
disp = false
```

目标 Jacobian 是解析的负 P2 广义力。物理间隙 Jacobian 是解析登记
Jacobian，有效域 Jacobian 是 P3R 已冻结的身份固定中心差分。SLSQP
`success` 和内部乘子都不作为验收门。

### 3.2 固定恢复活动集

在 SLSQP 最终点先按

$$
A_{\mathrm{near}}=\{i:g_i\le 10^{-7}\ \mathrm{m}\}
$$

形成近活动物理接触集合。使用本协议第 5 节的尺度化 NNLS 重构规范乘子，
再以

$$
A_{\mathrm{restore}}=
\{i\in A_{\mathrm{near}}:\lambda_i>10^{-9}\ \mathrm{N}\}
$$

形成恢复活动集。P3R2 当前资格族要求恢复活动集恰有两行且满行秩；否则
确定性失败关闭。该集合的身份和顺序在一次恢复内固定。

初始近活动但不在恢复集中的弱活动行不删除。恢复中要求全部物理间隙不低于
`-1e-10 m`；初始非近活动身份必须始终严格大于 `1e-7 m`，否则按活动身份
变化失败关闭。最终 KKT 审计仍对完整近活动集合重构规范乘子与对偶区间。

### 3.3 旋转规范与投影方程

附件臂非零时，绕附件臂的右乘旋转是登记规范方向。由当前旋转向量的 SO(3)
右 Jacobian 把附件臂单位方向映射到广义坐标规范方向 $h(q)$。在第 4 节的
无量纲坐标中，对 $h(q)$ 的单位化方向构造确定性 SVD 正交补 $P(q)$。

同时使用最小旋转坐标固定：

$$
c_{\mathrm{gauge}}(q)=
\hat a_{\mathrm{body}}^{\mathsf T}\phi=0,
$$

其中 $\phi$ 是三分量旋转向量。恢复未知量为 $(q,\lambda_A)$，方程为：

$$
P(q)^{\mathsf T}D_r^{-1}
\left(\nabla\Pi(q)-J_A(q)^{\mathsf T}\lambda_A\right)=0,
$$

$$
g_A(q)/L_*=0,
$$

$$
c_{\mathrm{gauge}}(q)=0.
$$

这里 $D_r$ 是第 4 节的分量残差尺度。投影站立方程有五项，活动间隙有两
项，规范固定有一项，与六个广义坐标和两个乘子组成固定的八阶方程组。

### 3.4 Hessian、线性系统与全局化

拉格朗日梯度为：

$$
r_L(q,\lambda_A)=
\nabla\Pi(q)-J_A(q)^{\mathsf T}\lambda_A.
$$

其关于 $q$ 的 Hessian 块使用固定乘子中心差分，平移步长为 `2e-6 m`，
旋转步长为 `2e-6 rad`。活动间隙块使用解析 Jacobian。全部块按第 4 节的
坐标与残差尺度组装成无量纲八阶 Newton 系统，并唯一使用
`numpy.linalg.solve`。相对最小奇异值低于 `1e-12` 时失败关闭，不加对角
正则，不切换最小二乘或伪逆。

恢复最多执行 `12` 次 Newton 更新。每次只尝试

$$
\alpha_k=2^{-k},\qquad k=0,1,\ldots,20.
$$

候选必须同时满足：

- 无量纲复合残差无穷范数满足 Armijo 系数 `1e-4` 的严格下降；
- 全部物理间隙不低于 `-1e-10 m`；
- 初始非近活动接触仍严格大于 `1e-7 m`；
- 全部有效域归一化残差不低于 `1e-5`；
- 旋转向量留在既有 `0.75 rad` 静态坐标图内。

没有步长被接受、线性系统不合格、几何未定义、活动身份变化或迭代耗尽时，
均返回有身份的确定性失败状态。禁止随机重启、算法瀑布、罚刚度、柔顺
接触和结果驱动分支。

复合残差无穷范数不大于 `1e-11` 时恢复收敛。该算法终止门严于、但不替代
第 5 节的独立认证门。

## 4. 坐标、单位与尺度合同

本轮六个广义坐标顺序固定为：

```text
bob_position_x, bob_position_y, bob_position_z,
bob_rotation_x, bob_rotation_y, bob_rotation_z
```

前三项坐标单位为 m，后三项为 rad。对应站立残差前三项单位为 N，后三项
单位为 N m。

每个算例的特征长度由模型几何预先确定：

$$
L_*=\max_e L_{0,e},
$$

即绑定静态组装中全部材料段参考长度的最大值。特征力使用既有只读静态审计
定义：

$$
F_*=\lVert g\rVert
\left(\lvert m_{\mathrm{bob,eff}}\rvert+
\sum_n\lvert m_{n,\mathrm{eff}}\rvert\right).
$$

本轮无浮力，因此有效质量就是绑定质量。特征能量为：

$$
E_*=F_*L_*.
$$

坐标尺度和残差尺度分别为：

$$
D_q=\operatorname{diag}(L_*,L_*,L_*,1,1,1),
$$

$$
D_r=\operatorname{diag}(F_*,F_*,F_*,E_*,E_*,E_*).
$$

完整无量纲站立向量为：

$$
\widehat r=D_r^{-1}
\left(\nabla\Pi-J^{\mathsf T}\lambda\right).
$$

$L_*$、$F_*$ 和 $E_*$ 都由输入组装计算，不能由已观察失败分量反推。

## 5. 独立 KKT 与对偶区间认证

对 SLSQP 后和恢复后的状态都保存完整六分量站立向量、坐标身份、真实单位、
尺度化值、最大分量身份与门限。恢复后必须同时满足：

- 历史混合标量回归门：`max(abs(raw six components)) <= 1e-8`；
- 平移力逐分量门：`abs(r_i) <= 1e-8 N`；
- 转动力矩逐分量门：`abs(r_i) <= 1e-8 L_* N m`；
- 无量纲逐分量门：`abs(rhat_i) <= 1e-8`。

历史门保留原名只用于回归，不再把六项统称为 N。

规范乘子通过尺度化 NNLS 独立重构：

$$
\min_{\lambda\ge0}
\left\lVert D_r^{-1}
(\nabla\Pi-J_A^{\mathsf T}\lambda)\right\rVert_2.
$$

逐身份对偶区间 LP 使用与上述三类新门一致的逐分量允许带，即每个分量取
绝对单位门和无量纲门换算后的较小值。LP 不可行时，可能支撑和必然支撑
均标记为“未认证”，不得解释为空物理支撑集。原始、对偶、互补、秩、作用
反作用、有效域、Jacobian、真实临界锥、二阶交叉检查和 P2 逐比特只读门
继续保留。

## 6. 强制历史回归

### 6.1 旧 30 度结构回归

`SYMMETRIC_BOB_TWO_CORD_CONTACT_1_P3R2_STRUCTURE_REGRESSION` 保留四项近活动、
两项正乘子支撑、两项弱活动、近活动秩 3、支撑秩 2 和非唯一对偶区间。
它执行复合算法，但只产生结构回归结论。

### 6.2 P3R 35 度三种子回归

`P3R_SYMMETRIC_35_DEG_TWO_BOB_CONTACT_1` 的目标、三个原种子、预期位置、
接触身份、乘子与旧 `1e-8` 门逐值不变。三个种子都必须执行复合算法并
全部通过；任一个失败则不运行新资格目标，G3R2 判为 NO-GO。

## 7. 冻结的新资格目标

### 7.1 非镜像几何、不等乘子双接触

`P3R2_ASYMMETRIC_32_41_DEG_TWO_BOB_CONTACT_1` 使用左、右上支相对竖直
方向分别为 32 度和 41 度，上支参考长度分别为 `0.8 m` 和 `0.9 m`，上支
接触半径也不同。摆球中心冻结在 `[0, 0, -0.1] m`，附件臂和下支仍竖直，
因此零旋转是解析规范代表。

接触所需中心距由

$$
r_A=0.1\sin 32^\circ,
\qquad
r_B=0.1\sin 41^\circ
$$

冻结。净向上非接触载荷为 $D=1.069899461282053\ \mathrm{N}$，两项解析
乘子为：

$$
\lambda_A=
\frac{D\cos41^\circ}{\sin73^\circ}
=0.8443577931300797\ \mathrm{N},
$$

$$
\lambda_B=
\frac{D\cos32^\circ}{\sin73^\circ}
=0.9487835290595398\ \mathrm{N}.
$$

它们严格不等，且水平与竖直解析平衡同时闭合。机器清单冻结一个解析种子
和两个相反偏置种子。

### 7.2 1.4 倍几何尺度目标

`P3R2_SCALED_1P4_35_DEG_TWO_BOB_CONTACT_1` 将 P3R 35 度目标的全部几何
长度乘以 `1.4`，并预先把轴向刚度、线密度和摆球质量改为新的输入尺度。
解析深度为 `0.13912705429056363 m`，每项解析乘子为
`0.5115787041556651 N`。该目标检验 $L_*$、$F_*$、$E_*$ 和恢复算法不是
针对单一长度或载荷调制。机器清单同样冻结三个确定性种子。

两个目标均为算法资格算例，不是装置预测。每个目标的全部三个种子必须
通过，且两次独立证据生成必须逐字节一致。任一种子失败，G3R2 整门判为
NO-GO；不得修改目标、种子、算法或门限后在同一协议内重跑。

## 8. 提交顺序、结论上限与停止门

提交顺序固定为：

1. 本预冻结协议、机器清单和身份合同；
2. 独立包、测试、证据生成器和实现哈希；
3. G3R2 指标、原始报告、人类报告和交接。

前两项进入 Git 历史前不得运行两个新资格目标。

通过状态上限为：

`G3R2_CANDIDATE_PASS_PENDING_PRO_REVIEW__STATIC_CONTACT_ALGORITHM_ONLY`

失败状态为：

`NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`

无论自动门结果如何，完成证据后必须停在：

`G3R2_PRO_REVIEW`

不得进入 P4、P5 或 P6，不得实现动态接触、摩擦、恢复、罚接触或冲量，
不得修改正式理论、正式程序、公共 API、HDF5 或 UI。物理验证与实验验证
均未执行，正式高保真总状态继续为 `HF_NUMERICAL_QUALIFICATION_NO_GO`。

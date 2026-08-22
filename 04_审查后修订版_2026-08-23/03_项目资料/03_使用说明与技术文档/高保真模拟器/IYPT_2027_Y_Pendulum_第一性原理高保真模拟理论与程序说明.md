# IYPT 2027 第五题 Y 形摆：第一性原理高保真模拟理论与程序说明

> 所属层：四层研究框架的第 3 层。  
> 规范模型：`HF-DISCRETE-ROD-RIGID-BOB-1.0`。  
> 程序目录：`Y-Pendulum-Simulator-v1.0.0-rc1/`。  
> 软件定位：个人科研计算工具与可修改原型，不是对外发布或生产系统。  
> 当前科学声明：完成物理核心与短窗可信性验证；0.12 s 目标长窗和代表性敏感性结果见第 18 节。  
> 层边界：本文只写第 3 层的独立物理、数值实现、运行证据和适用范围，不提出第 4 层结构性理论。

---

## 0. 结论先行

本层实现了一条与前向柔索弱形式相独立的 Newton–Euler 计算路径：

1. 三根支路由具有集中质量的材料珠和局部连接构成；
2. 轴向内力采用被动的“单边绳律—双边杆律”凸组合，正式 HF 目标取双边杆端点；
3. 相邻三点具有非零中心线弯曲能及其保守力；
4. 摆球是有限半径、有限惯量、四元数姿态和偏心连接点的刚体；
5. 主要输出包括全状态、有符号轴力、非负张力、弯曲能、刚体转动、支点反力、功—能账本和几何/接触守卫；
6. 接触是当前模型的有效域终止边界；程序不虚构未定义的冲量、摩擦、粘附或接触后运动。

个人科研原型的最低验收是：模型与本文一致；目标配置能运行；核心物理量可导出；至少完成代表性的时间步和网格敏感性；明显数值、接触和事件错误不能伪装成功；代码结构便于今后修改；限制写清。Git、wheel/sdist、ZIP、复杂 manifest 互绑、恶意 JSON 攻击面和 crash-atomic 发布语义不再阻塞第 3、4 层。已经完成的工程防护保留，但不继续扩张。

---

## 1. 四层内容隔离

| 层 | 在本文中的处理 |
|---|---|
| 第 1 层：前向预测理论 | 只接收已经冻结的公共物理输入与可观测量身份，不重写其理论 |
| 第 2 层：前向数值理论与程序 | 作为外部冻结后端用于对照；HF 内核不导入它的质量矩阵、柔索弱形式或状态推进器 |
| 第 3 层：高保真模拟 | 本文主体 |
| 第 4 层：结构性理论 | 明确排除；尺度律、分岔、稳定性边界和机制解释必须另立文档 |

HF 与前向后端可以共享支点轨迹、质量、自然长度、线密度、轴向参数、空气参数和公共初态，但不能读取前向轨迹来构造 HF 轨迹。直径、弯曲刚度、刚体惯量、偏心连接和排除几何是 HF 专属输入。

---

## 2. 拓扑、坐标与输入

### 2.1 拓扑

三条有向材料支路为

\[
\mathcal B=\{A,B,\ell\}.
\tag{HF.1}
\]

上支 \(A\) 从支点 \(\boldsymbol a(t)\) 指向有限质量结点 \(J\)，上支 \(B\) 从 \(\boldsymbol b(t)\) 指向 \(J\)，下支 \(\ell\) 从 \(J\) 指向刚体摆球上的偏心材料连接点 \(C\)。三支在 \(J\) 固结；当前模型不允许穿环滑动、材料跨支交换、打结重排或拓扑重连。

世界坐标中的 \(\boldsymbol g\) 直接表示重力加速度矢量。所有规范输入和输出采用 SI 单位。

### 2.2 公共输入

与前向后端可共享：

- \(\boldsymbol g,\boldsymbol a(t),\boldsymbol b(t)\)；
- \(m_J,m_b\)；
- 每支 \(L_\beta,\mu_\beta,EA_\beta,C_{a,\beta}\)；
- 环境密度、空气速度及线性/二次阻力参数；
- \(J\) 和摆球质心的初始位置、速度；
- 比较时间窗和公共观测定义。

### 2.3 HF 专属输入

- 支路直径 \(d_\beta\)、截面积 \(A_\beta\) 与圆截面二次矩；
- 中心线弯曲刚度 \(EI_\beta\)；
- 摆球半径 \(R_b\)、惯量 \(I_b\)、姿态四元数；
- 体坐标偏心连接臂 \(\boldsymbol a_b\)；
- 摆球—杆及杆—杆的有限尺寸守卫；
- HF 自己的材料珠数、积分器、容差和时间步。

---

## 3. 独立状态空间

### 3.1 材料珠

支路 \(\beta\) 给定 \(N_\beta\) 个内部材料珠，完整点列为

\[
\boldsymbol x^{(\beta)}_0,\boldsymbol x^{(\beta)}_1,\ldots,
\boldsymbol x^{(\beta)}_{N_\beta},
\boldsymbol x^{(\beta)}_{N_\beta+1}.
\tag{HF.2}
\]

两端点分别是支点、\(J\) 或摆球连接点；内部材料珠是动力自由度。材料质量按材料控制体集总。当前离散约定下，内部材料珠质量为

\[
m_p^{(\beta)}=\mu_\beta\frac{L_\beta}{N_\beta}.
\tag{HF.3}
\]

两个端连接的自然长度为 \(L_\beta/(2N_\beta)\)，内部连接的自然长度为 \(L_\beta/N_\beta\)，各连接自然长度之和严格为 \(L_\beta\)。结点 \(J\) 的质量独立给定，不与材料珠重复计算。

### 3.2 有限刚体摆球

摆球状态包括质心位置与速度 \((\boldsymbol r_b,\boldsymbol v_b)\)、标量在前的单位四元数

\[
q=(q_0,q_1,q_2,q_3),\qquad \lVert q\rVert=1,
\tag{HF.4}
\]

以及世界坐标角速度 \(\boldsymbol\omega\)。若动力粒子总数为

\[
N_p=N_A+N_B+N_\ell+1,
\]

完整一阶状态维数为

\[
n_y=6N_p+13.
\tag{HF.5}
\]

有限刚体姿态、偏心连接和角速度自由度并不存在于冻结的前向柔索状态中，这是两后端物理独立性的一个核心来源。

---

## 4. 被动轴向局部本构

### 4.1 局部几何

对局部连接 \(j\)，定义

\[
\boldsymbol e_j=\boldsymbol x_{j+1}-\boldsymbol x_j,\qquad
\ell_j=\lVert\boldsymbol e_j\rVert,\qquad
\boldsymbol t_j=\frac{\boldsymbol e_j}{\ell_j},
\tag{HF.6}
\]

\[
\delta_j=\ell_j-\ell_j^0,\qquad
\dot\delta_j=
(\boldsymbol v_{j+1}-\boldsymbol v_j)\cdot\boldsymbol t_j,
\tag{HF.7}
\]

\[
k_j=\frac{EA}{\ell_j^0},\qquad
c_j=\frac{\eta A}{\ell_j^0}.
\tag{HF.8}
\]

这里 \(\ell_j^0>0\) 是局部自然长度。

### 4.2 单边绳律与双边杆律

双边 Kelvin–Voigt 试算轴力为

\[
F_j^{\rm B}=k_j\delta_j+c_j\dot\delta_j.
\tag{HF.9}
\]

单边支路为

\[
F_j^{\rm U}=
\begin{cases}
F_j^{\rm B}, & \delta_j>0\ \text{且}\ F_j^{\rm B}>0,\\
0, & \text{其他}.
\end{cases}
\tag{HF.10}
\]

用 \(\alpha\in[0,1]\) 定义被动凸组合

\[
F_j=(1-\alpha)F_j^{\rm U}+\alpha F_j^{\rm B}.
\tag{HF.11}
\]

\(F_j\) 是动力学使用的有符号轴力：\(F_j>0\) 表示拉伸，\(F_j<0\) 表示压缩。用于张力图和松弛/重张事件的量另定义为

\[
T_j=\max(F_j,0).
\tag{HF.12}
\]

程序因此分别保存 `signed_axial_force` 与 `tension`，不把压缩误写成“负张力”，也不在动力学中用 \(T_j\) 替代有符号力。

正式 HF 目标取

\[
\boxed{\alpha=1},
\tag{HF.13}
\]

即具有有限压缩刚度的离散杆。受控独立性极限可以令 \(\alpha\to0\)，但 \(\alpha<1\) 的成员明确标为 `OUT_OF_SCOPE`，不能冒充正式 HF 生产物理。

### 4.3 储能与耗散

轴向储能写成

\[
U_{\rm ax}=
(1-\alpha)\frac12\sum_j k_j[\delta_j]_+^2
+\alpha\frac12\sum_j k_j\delta_j^2.
\tag{HF.14}
\]

双边杆的黏性耗散为 \(\sum_j c_j\dot\delta_j^2\)。单边分支在激活区使用同一黏性耗散；投影释放造成的储能下降另行进入耗散账本。局部回归直接核对力、储能率和耗散，不用 \(\max(0,\cdot)\) 截断负耗散来掩盖符号错误。

---

## 5. 三点中心线弯曲

对连续三点
\((\boldsymbol x_{i-1},\boldsymbol x_i,\boldsymbol x_{i+1})\)，
令左右单位切向为 \(\boldsymbol t_{i-1},\boldsymbol t_i\)，双长度为

\[
\bar\ell_i=\frac{\ell^0_{i-1}+\ell^0_i}{2}.
\tag{HF.15}
\]

中心线弯曲能为

\[
U_{{\rm bend},i}
=\frac12\frac{EI}{\bar\ell_i}
\left\lVert\boldsymbol t_i-\boldsymbol t_{i-1}\right\rVert^2,
\qquad
EI=s_E E\frac{\pi d^4}{64}.
\tag{HF.16}
\]

正式 HF 取 \(s_E=1\)。令

\[
P_j=\frac{I-\boldsymbol t_j\boldsymbol t_j^{\mathsf T}}{\ell_j},
\qquad
\Delta\boldsymbol t_i=\boldsymbol t_i-\boldsymbol t_{i-1},
\qquad
\kappa_i=\frac{EI}{\bar\ell_i},
\tag{HF.17}
\]

则三点所受保守力为

\[
\boldsymbol f_{i-1}^{(b)}
=-\kappa_i P_{i-1}\Delta\boldsymbol t_i,
\tag{HF.18a}
\]

\[
\boldsymbol f_i^{(b)}
=\kappa_i(P_{i-1}+P_i)\Delta\boldsymbol t_i,
\tag{HF.18b}
\]

\[
\boldsymbol f_{i+1}^{(b)}
=-\kappa_i P_i\Delta\boldsymbol t_i.
\tag{HF.18c}
\]

三力之和为零，并满足
\(\boldsymbol f=-\partial U_{\rm bend}/\partial\boldsymbol x\)。
回归测试用中心差分核对能量梯度、合力和刚体平移不变性。

这仍是离散中心线杆，不包含材料 director、扭转和剪切自由度；因此不声称实现了完整 Cosserat 杆。

---

## 6. 有限刚体摆球与偏心连接

对球形摆球取

\[
I_b=\kappa_I m_b R_b^2,\qquad 0<\kappa_I\le\frac23.
\tag{HF.19}
\]

均匀实心球对应 \(\kappa_I=2/5\)。体坐标连接臂为 \(\boldsymbol a_b\)，世界坐标下

\[
\boldsymbol a=R(q)\boldsymbol a_b,\qquad
\boldsymbol r_C=\boldsymbol r_b+\boldsymbol a,\qquad
\boldsymbol v_C=\boldsymbol v_b+\boldsymbol\omega\times\boldsymbol a.
\tag{HF.20}
\]

摆球平动和转动方程为

\[
m_b\ddot{\boldsymbol r}_b
=m_b\boldsymbol g+\boldsymbol F_{\rm buoy}
+\boldsymbol F_{\rm aero,b}+\boldsymbol F_C,
\tag{HF.21}
\]

\[
I_b\dot{\boldsymbol\omega}
=\boldsymbol a\times\boldsymbol F_C.
\tag{HF.22}
\]

球形惯量各向同性，所以没有非球形刚体的
\(\boldsymbol\omega\times(I\boldsymbol\omega)\) 项。四元数运动学为

\[
\dot q=
\frac12(0,\boldsymbol\omega)\otimes q
+\gamma_q(1-q\cdot q)q.
\tag{HF.23}
\]

\(\gamma_q\) 的量纲为 \({\rm s}^{-1}\)，只用于抑制数值范数漂移，不代表物理力矩。

---

## 7. Newton 方程与外力

每颗内部材料珠 \(p\) 满足

\[
m_p\ddot{\boldsymbol x}_p
=m_p\boldsymbol g
+\sum\boldsymbol F_{\rm ax}
+\sum\boldsymbol F_{\rm bend}
+\boldsymbol F_{\rm aero,p}.
\tag{HF.24}
\]

有限质量结点 \(J\) 满足

\[
m_J\ddot{\boldsymbol r}_J
=m_J\boldsymbol g+
\sum_{\beta\in\{A,B,\ell\}}
\left(
\boldsymbol F_{{\rm ax},\beta J}
+\boldsymbol F_{{\rm bend},\beta J}
\right)
+\boldsymbol F_{\rm aero,J}.
\tag{HF.25}
\]

所有轴向力和弯曲力都在相邻物体间成对装配。支点端的相反力记录为支点反力；下支端力同时进入摆球平动及偏心力矩。

启用浮力时

\[
\boldsymbol F_{\rm buoy}
=-\rho_a\frac{4\pi R_b^3}{3}\boldsymbol g.
\tag{HF.26}
\]

摆球相对空气速度
\(\boldsymbol v_{\rm rel,b}=\boldsymbol v_b-\boldsymbol u_a\)，
其阻力为

\[
\boldsymbol F_{\rm aero,b}
=-c_{1,b}\boldsymbol v_{\rm rel,b}
-\frac12\rho_a C_{D,b}\pi R_b^2
\lVert\boldsymbol v_{\rm rel,b}\rVert
\boldsymbol v_{\rm rel,b}.
\tag{HF.27}
\]

材料珠的分布阻力沿局部切向分解为平行和法向分量，再分别施加线性和二次被动阻力。这是局部阻力闭合，不是 CFD；系数必须来自测量、文献或明确有界估计。

---

## 8. 功—能账本

机械能逐时刻重算为

\[
E_m=
K_p+K_{b,{\rm tr}}+K_{b,{\rm rot}}
+U_g+U_{\rm ax}+U_{\rm bend},
\tag{HF.28}
\]

其中

\[
K_p=\frac12\sum_p m_p\lVert\boldsymbol v_p\rVert^2,
\qquad
K_{b,{\rm tr}}=\frac12m_b\lVert\boldsymbol v_b\rVert^2,
\qquad
K_{b,{\rm rot}}=\frac12I_b\lVert\boldsymbol\omega\rVert^2.
\tag{HF.29}
\]

相对空气的被动耗散记为 \(D_{\rm aero}\ge0\)。由于
\(\boldsymbol v=\boldsymbol v_{\rm rel}+\boldsymbol u_a\)，

\[
\boldsymbol F_{\rm aero}\cdot\boldsymbol v
=-D_{\rm aero}
+\boldsymbol F_{\rm aero}\cdot\boldsymbol u_a.
\tag{HF.30}
\]

因此必须把相对空气耗散和气流输入功分开。规定支点运动的功率由杆端力与支点速度直接计算。第一律残差为

\[
\mathcal R_E(t)=
\frac{
E_m(t)-E_m(0)
+\int_0^t\!\left(D_{\rm ax}+D_{\rm aero}\right)\,{\rm d}\tau
-\int_0^t\!\left(P_{\rm air}+P_{\rm support}\right)\,{\rm d}\tau
}{E_*}.
\tag{HF.31}
\]

\(E_*\) 由质量、重力和特征长度构成，并含机器地板；它不把坐标原点相关的绝对势能作为唯一尺度。程序同时保存有量纲残差和归一残差。

---

## 9. 固定端点平衡—释放初态

目标几何的下支端点弦长小于材料自然长度，不能用直线布珠吞掉多余弧长。正式配置采用
`held_endpoint_equilibrium_release`：

1. 在 \(t=0\) 固定两个支点、用户给定的 \(J\)、摆球质心和单位初始姿态；
2. 优化变量只包含三支内部材料珠；
3. 弦长小于材料长度时，在重力—弦平面构造具有完整材料长度的正弦弓形种子；
4. 组合重力延续、镜像种子和小的出平面扰动进行多起点势能极小化；
5. 自由材料珠最大净力必须低于配置中的力阈值；
6. 用自由坐标势能 Hessian 的最小特征值排除低残差鞍点；
7. 所有几何守卫必须严格为正；
8. 从已证局部稳定候选中选能量最低者。

释放时，\(J\)、摆球质心与角速度使用用户指定值；支路内部材料珠速度按固定材料坐标在两端速度之间插值。制备诊断保存自由珠残差、最小 Hessian 特征值、稳定种子、夹具反力以及释放瞬间的净力和力矩。

`geometric_direct_release` 只适用于三支端点弦长均不小于材料长度、且可以构造完整材料态的输入；否则失败关闭，不自动制造无能量的压缩直杆。

---

## 10. 有效域与 11 个守卫

本模型没有接触后的冲量、摩擦或柔顺接触。接触和几何奇异是有效域边界。特征长度取

\[
L_*=
\max\left\{
\lVert\boldsymbol b(0)-\boldsymbol a(0)\rVert,
L_A,L_B,L_\ell
\right\}.
\tag{HF.32}
\]

| 守卫 | 单位 | 原始裕量 |
|---|---:|---|
| `MINIMUM_SEGMENT_LENGTH` | m | 最小局部段长减几何塌缩尺度 |
| `BENDING_TURN_CLEARANCE` | 1 | \(\min(1+\boldsymbol t_-\cdot\boldsymbol t_+)-10^{-8}\) |
| `AERODYNAMIC_CHORD_LENGTH` | m | 两跨气动弦长减气动奇异尺度 |
| `BOB_ROD_CLEARANCE` | m | 摆球排除球面到非注册杆段表面的最小净空 |
| `ROD_SELF_CLEARANCE` | m | 同支远隔段和异支非连接区的最小杆面净空 |
| `BOB_SOCKET_MATERIAL_EXTENT` | m | 下支固定材料 socket 尚余的材料长度 |
| `BOB_SOCKET_RADIAL_MONOTONICITY` | m² | bob socket 每个仿射材料单元的径向逸出裕量 |
| `BOB_SOCKET_CUT_CLEARANCE` | m | 固定材料 cut 点到摆球表面的注册余量 |
| `JUNCTION_SOCKET_MATERIAL_EXTENT` | m | 结点 socket 尚余的材料长度 |
| `JUNCTION_SOCKET_PROJECTIVE_OPENING` | 1 | 两支固定材料 socket 在独立参数 \((s,t)\) 上的投影开口下界 |
| `JUNCTION_SOCKET_CUT_CLEARANCE` | m | 两支 socket cut 点的注册中心距余量 |

前 3 项始终注册；启用 `contact_guard_enabled` 时全部 11 项注册。接触注册身份为
`FIXED_REST_MATERIAL_SOCKETS_PROJECTIVE_V2`。
对每个分量 \(g_i\) 保存单位、物理尺度 \(S_i\) 和机器容差

\[
\tau_i=1024\,\epsilon_{\rm mach}S_i.
\tag{HF.33}
\]

守卫根在 \(g_i=0\) 定位；\(\tau_i\) 仅用于判断是否能认证严格为正。首个已定位越界返回
`OUT_OF_SCOPE / SUCCESS_EVENT` 和半开有效区间 \([0,\tau)\)。
若接受步内可能存在相切或“正—负—正”越界但无法定位，必须返回
`UNDETERMINED / EVENT_UNRESOLVED`，不能写成完成。

个人原型仍保留独立 reference 对 11 个分量的短窗复核，但不把“不可伪造形式证书”当作继续进入第 4 层的前置条件。

---

## 11. 数值方法

### 11.1 一阶系统

完整离散 Newton–Euler 方程写为

\[
\dot y=f_{\rm HF}(t,y;p).
\tag{HF.34}
\]

\(f_{\rm HF}\) 只调用本层的材料珠、局部轴向律、三点弯曲、刚体、局部空气力和接触几何，不调用前向求解器。

### 11.2 积分器与容差

默认积分器是隐式 Radau IIA；BDF 可用于交叉检查。位置、速度、四元数和角速度分别配置绝对容差，不用一个无量纲数同时衡量米、米每秒和弧度每秒。最大步长同时受用户配置、重力时间尺度和纵波传播尺度限制。

程序区分：

- `time`：由 `output_dt` 决定的展示和比较网格；
- `integration_time`：积分器实际接受步。

展示网格不能冒充积分步，也不能用稀疏输出隐藏中间错误。运行时还设置接受步、输出样本、内存和结果大小硬上限，在大分配前失败关闭。

### 11.3 动力缺陷

对接受步 \((t_n,y_n)\to(t_{n+1},y_{n+1})\)，令
\(h_n=t_{n+1}-t_n\)，用端点 RHS 构造 Hermite 中点

\[
y_{n+1/2}
=\frac{y_n+y_{n+1}}{2}
+\frac{h_n}{8}(f_n-f_{n+1}),
\tag{HF.35}
\]

再用 Simpson 增量

\[
\Delta y_n^{S}
=\frac{h_n}{6}
\left(f_n+4f_{n+1/2}+f_{n+1}\right),
\tag{HF.36}
\]

得到缺陷

\[
r_n=y_{n+1}-y_n-\Delta y_n^{S}.
\tag{HF.37}
\]

验证可同时检查局部归一缺陷、有符号累积和绝对累积，从而阻止“每步略错但同号累积”的伪轨迹。该严格工具已经存在；个人目标运行只要求它足以揭示明显错误，不再扩展成发布级不可伪造证书链。

### 11.4 原始状态语义

若积分完成而单次求解器没有独立证明每个接受步内的全部相切守卫，原始结果保守记录为

~~~text
UNDETERMINED / SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED
~~~

这表示“得到完整候选轨迹，但连续守卫仍需独立复核”，不是积分器失败。独立守卫复核可以给出“目标窗内可用”的旁证，但不改写原始状态。

真实首根为

~~~text
OUT_OF_SCOPE / SUCCESS_EVENT
~~~

不能继续进入未定义的接触后物理。

---

## 12. 输出

单运行目录的科学核心包括：

- `config_resolved.yaml`：实际使用的 SI 配置；
- `result.h5`：全状态、局部场和数值接受步；
- `summary.json` 与 `diagnostics.json`：状态、范围、能量和守卫摘要；
- `events.csv` 与 `events.json`：事件；
- `observer_output.npz`：观测量；
- `report.md`：人可读摘要。

`result.h5` 至少保存：

- `/time` 与 `/numerical_certificate/accepted_step_time`；
- 所有材料珠的位置、速度和质量；
- \(J\) 的位置与速度；
- 摆球质心位置/速度、四元数、角速度和偏心连接点；
- 三支完整材料路径；
- `/cables/<branch>/segments/signed_axial_force`：有符号动力学轴力；
- `/cables/<branch>/segments/tension`：非负张力；
- 支点反力、机械能各项、耗散、空气/支点输入功和第一律残差；
- 3 或 11 个守卫序列及其单位、尺度和容差。

既有身份和旁证文件保留；个人使用的核心是物理量与当前配置一致、可以重算，而不是所有文件都必须被复杂发布 manifest 互锁。

---

## 13. 个人科研原型的最低验收

### 13.1 必须满足

1. 轴向力—能—耗散、弯曲能梯度、偏心力矩和四元数运动学通过定向回归；
2. 目标配置完成固定端点平衡制备并进入动力学；
3. 有符号轴力与非负张力不混义；
4. 原始耗散不靠截断隐藏负值；
5. 接触关闭/开启时守卫集合分别精确为 3/11 项；
6. 生产守卫和独立 reference 对同一状态相符；
7. 人工构造的隐藏穿越和相切守卫不能伪装完成；
8. 目标轨迹状态、能量、轴力和守卫有限；
9. 至少有一组时间步和一组网格敏感性，报告原始误差；
10. 适用范围、没建模的物理和修改入口写清。

### 13.2 不再作为阻断项

- 无限扩展恶意 JSON、环状对象和极端大整数的对抗；
- 证明目录替换在掉电和并发读者意义下完全 crash-atomic；
- Git 标签、wheel/sdist、ZIP 安装链和发布级 CLI；
- 复杂文件 manifest 互绑；
- 为“不可伪造”继续叠加形式证书。

---

## 14. 代表性敏感性设计

目标配置为：

| 量 | 目标值 |
|---|---:|
| 材料珠数 \(N_A/N_B/N_\ell\) | 24/24/32 |
| 物理窗 | 0.12 s |
| `output_dt` | \(7.8125\times10^{-6}\ {\rm s}\) |
| `max_step` | \(7.8125\times10^{-6}\ {\rm s}\) |
| 积分器 | Radau |
| \(\alpha\) | 1 |

本次最低敏感性不要求六候选发布矩阵，而是：

1. **时间步对照**：同一目标网格、同一制备态、同一代表窗，比较 \(h\) 与 \(2h\)；
2. **空间网格对照**：同一代表窗比较目标网格与一个较粗网格；
3. 对摆球和 \(J\) 的位置/速度、有符号轴力、张力、机械能与最小守卫报告 RMS 或最大差异；
4. 代表窗必须包含释放后的初始高频响应；
5. 不因看到结果而反向放宽先前声明的分辨率。

程序仍保留更严格的三层网格、三层时间步、Radau/BDF 和 HF 独立性矩阵；它们可在以后需要时运行，不再阻塞当前个人研究。

---

## 15. 计算性能

### 15.1 CPU

Radau/BDF 的时间推进有前后依赖，单条轨迹不能简单切成互不依赖的时间段。当前可安全并行的部分是：

- 固定端点稳定性检查中相互独立的有限差分 Hessian 列，最多使用 8 个 CPU 线程；
- 相互独立的网格、时间步、积分器和参数成员；
- 单条轨迹中彼此独立的 presentation samples 后处理。

当前实现对每个 presentation sample 只做一次完整 `evaluate`，同一次局部力和
几何结果同时生成有符号轴力、非负张力、能量、反力和 11 个守卫。材料 socket、
线段对、接触豁免类和固定索引在建模时预计算；普通线段距离和接触裕量采用
NumPy 批处理。样本按固定连续块交给 `spawn` 多进程池，主进程按原索引回填，
事件排序和累计积分不下放，因此多进程调度不会改变结果顺序。

默认 worker 数是 `min(12, 物理核心数)`，可用
`YPS_HF_POSTPROCESS_WORKERS=1|8|12|auto` 覆盖；少于 64 个样本时自动串行。
`spawn` 避免在已加载 OpenBLAS 或界面线程的父进程中 `fork`，以少量启动成本
换取更低死锁风险。

外层并行时应令 `OPENBLAS_NUM_THREADS=1`、`OMP_NUM_THREADS=1`，避免每个成员再次占满所有线程。每个成员必须使用不同输出目录。

### 15.2 GPU

当前环境没有 JAX、CuPy、Numba 或自定义 CUDA 后端。目标问题隐式、分支密集，
并含材料约束 socket；未经重构直接搬到 GPU 很可能被数据传输和稀疏线性求解
开销抵消。CPU 向量化和 12 核样本并行已把完整 15,361 样本后处理从
191.07 s 降到 20.81 s，因此本版不虚报 GPU 加速，也不把 `nvidia-smi` 的桌面
背景负载归因于模拟器。

若以后需要同时计算数百个同网格参数成员，可以先剖析运行时间，再把局部力、接触距离和 Jacobian 批量矢量化，评估 JAX/CUDA 或自定义稀疏核。GPU 接入必须以总墙钟时间和相同物理残差为验收依据。

---

## 16. 程序结构与可修改性

| 对象 | 主要文件 |
|---|---|
| HF 状态和结果 | `src/ypendulum/hf/state.py` |
| 轴向律、弯曲、刚体、空气力、接触几何、RHS | `src/ypendulum/hf/model.py` |
| 初态制备、Radau/BDF、事件、采样、能量账本 | `src/ypendulum/hf/solver.py` |
| 独立局部力、能量和守卫 reference | `src/ypendulum/hf/reference.py` |
| 代表性与严格加密工具 | `src/ypendulum/hf/validation.py` |
| HF 物理受控极限 | `src/ypendulum/hf/independence.py` |
| HDF5 输出 | `src/ypendulum/io/hdf5.py` |
| 程序 API 与命令行 | `src/ypendulum/api.py`、`src/ypendulum/cli.py` |
| 双后端适配与比较 | `src/ypendulum/unified/` |
| 本地图形界面 | `src/ypendulum/ui/` |

修改原则是“方程属于局部物理模块，输出和验证只消费状态”。若以后加入扭转、非球惯量或接触后动力学，应在局部模块新增状态和方程，再同步扩展 HDF5 与定向测试；不必推倒统一平台。

---

## 17. 运行方法

在程序目录中创建环境：

~~~bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[ui,dev]'
~~~

检查配置：

~~~bash
ypendulum validate-config \
  configs/examples/high_fidelity_shared_forward_window.yaml
~~~

运行目标 HF：

~~~bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
YPS_HF_POSTPROCESS_WORKERS=12 \
ypendulum simulate \
  configs/examples/high_fidelity_shared_forward_window.yaml
~~~

顶层运行默认在目标输出目录旁写积分 checkpoint；也可显式指定和回放：

~~~bash
YPS_HF_POSTPROCESS_WORKERS=12 \
ypendulum simulate CONFIG --hf-checkpoint /data/run.integration.npz

YPS_HF_POSTPROCESS_WORKERS=12 \
ypendulum simulate CONFIG \
  --hf-checkpoint /data/run.integration.npz \
  --resume-hf-checkpoint
~~~

checkpoint 位于隐式积分和 presentation 后处理之间，保存 accepted/presentation
时间与完整状态、事件根、求解器计数和配置身份。它允许后处理失败或修改后不重跑
积分，但不能自动跨越状态语义或理论版本变化。

运行个人研究所需的代表性短窗敏感性：

~~~bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
python scripts/run_representative_hf_sensitivity.py \
  --window-s 0.01 \
  --output validation/representative_hf_sensitivity.json \
  --series-output validation/representative_hf_sensitivity_series.npz
~~~

脚本先制备一次目标网格状态，再以三个独立 CPU 进程运行
\(h\)、\(2h\) 和 20/20/30 网格；它输出原始误差，不自动把短窗结果升级成正式资格。

可选的完整资格矩阵：

~~~bash
ypendulum hf-validate \
  configs/examples/high_fidelity_shared_forward_window.yaml \
  configs/high_fidelity_shared_forward_validation.yaml \
  --output /tmp/yps-hf-validation-fresh
~~~

启动本地界面：

~~~bash
ypendulum ui
~~~

目标算例高刚度且较慢。应先用短窗探针估算资源，再运行 0.12 s 长窗。多个独立敏感性成员可以利用 CPU 并行，但要避免与其他高负载程序过度订阅。

---

## 18. 当前计算证据

### 18.1 物理核心和守卫

| 证据 | 当前结论 |
|---|---|
| 轴向被动性、有符号轴力/张力分离、弯曲能梯度、刚体力矩、四元数、初态制备和接触域 | 核心定向回归最近一组 56 项通过 |
| 独立 reference 与 11 守卫 | 定向整文件回归 20 项通过；完整六候选长矩阵按范围收缩未运行 |
| 接触关闭/开启 | 独立检查精确覆盖 3/11 项 |
| 0.2 ms 短轨迹连续守卫 | `CERTIFIED_POSITIVE` |
| 正—负—正隐藏越界与相切构造 | 均失败关闭，不伪装为完成 |

### 18.2 目标短窗探针

目标网格 24/24/32、正式 held 初态、\(\alpha=1\) 的 2 ms 探针得到：

| 量 | 数值 |
|---|---:|
| 墙钟时间 | 273.67 s |
| 动力积分时间 | 81.588 s |
| 输出样本 / 接受步时刻 | 257 / 258 |
| 制备稳定种子 | `gravity_plane` |
| 制备最小 Hessian 特征值 | \(5.8498741\times10^{-3}\ {\rm N\,m^{-1}}\) |
| 最小归一守卫 | \(7.5666454\times10^{-5}\) |
| 有符号轴力范围 | \([-3.8320\times10^{-3},\,1.64621\times10^{-1}]\ {\rm N}\) |
| 非负张力范围 | \([0,\,1.64621\times10^{-1}]\ {\rm N}\) |
| 最大能量残差 | \(1.50454\times10^{-11}\) |

该探针证明目标配置可以完成稳定初态制备、进入独立 HF 动力学，并输出状态、轴力、张力、能量和 11 守卫。它不能替代 0.12 s 长窗或敏感性结论。

### 18.3 代表性时间步与网格敏感性

计算使用 0.01 s 代表窗，完整保留释放后的初始高频响应。细网格为
24/24/32；粗网格为 20/20/30。时间步比较复用完全相同的细网格 held
制备态，比较 \(h=7.8125\times10^{-6}\ {\rm s}\) 与 \(2h\)。三成员由
独立 CPU 进程并行运行，OpenBLAS/OMP 各限 1 线程。

| 运行证据 | 数值 |
|---|---:|
| 总墙钟 / 峰值 RSS | 1290.25 s / 305772 KiB |
| 共享细网格制备墙钟 | 42.97 s |
| 细网格 \(h\) 输出 / 接受时刻 | 1281 / 1282 |
| 细网格 \(2h\) 输出 / 接受时刻 | 1281 / 647 |
| 三成员状态 | 均为原始保守状态 `UNDETERMINED / SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED`，有效窗均为 \([0,0.01]\ {\rm s}\) |
| 有限性 | 三成员所有科学数组均有限 |
| 最大能量账本残差 | \(1.5050\times10^{-11}\) |
| 源码稳定性 | 起止源码 SHA-256 均为 `0e12494439d5781857c76892f5161236d9c35bc809c0f3907df92df7905b2a5e` |

时间步差异：

| 量 | RMS | 最大值 |
|---|---:|---:|
| 摆球位置 | \(2.16\times10^{-16}\ {\rm m}\) | \(8.88\times10^{-16}\ {\rm m}\) |
| 摆球速度 | \(5.11\times10^{-15}\ {\rm m\,s^{-1}}\) | \(1.28\times10^{-13}\ {\rm m\,s^{-1}}\) |
| \(J\) 位置 | \(1.19\times10^{-15}\ {\rm m}\) | \(6.52\times10^{-15}\ {\rm m}\) |
| \(J\) 速度 | \(2.86\times10^{-12}\ {\rm m\,s^{-1}}\) | \(1.03\times10^{-10}\ {\rm m\,s^{-1}}\) |
| 全杆位置 | \(4.44\times10^{-15}\ {\rm m}\) | \(6.14\times10^{-14}\ {\rm m}\) |
| 全杆速度 | \(5.47\times10^{-12}\ {\rm m\,s^{-1}}\) | \(1.47\times10^{-9}\ {\rm m\,s^{-1}}\) |
| 有符号轴力 | \(2.36\times10^{-11}\ {\rm N}\) | \(3.56\times10^{-9}\ {\rm N}\) |
| 非负张力 | \(2.35\times10^{-11}\ {\rm N}\) | \(3.56\times10^{-9}\ {\rm N}\) |
| 机械能 | \(3.07\times10^{-16}\ {\rm J}\) | \(1.78\times10^{-15}\ {\rm J}\) |

网格差异：

| 量 | RMS | 最大值 |
|---|---:|---:|
| 摆球位置 | \(1.39\times10^{-9}\ {\rm m}\) | \(3.61\times10^{-9}\ {\rm m}\) |
| 摆球速度 | \(6.74\times10^{-7}\ {\rm m\,s^{-1}}\) | \(2.01\times10^{-6}\ {\rm m\,s^{-1}}\) |
| \(J\) 位置 | \(2.29\times10^{-7}\ {\rm m}\) | \(7.22\times10^{-7}\ {\rm m}\) |
| \(J\) 速度 | \(1.05\times10^{-4}\ {\rm m\,s^{-1}}\) | \(3.20\times10^{-4}\ {\rm m\,s^{-1}}\) |
| 全杆位置 | \(1.34\times10^{-5}\ {\rm m}\) | \(1.22\times10^{-4}\ {\rm m}\) |
| 全杆速度 | \(7.19\times10^{-4}\ {\rm m\,s^{-1}}\) | \(1.17\times10^{-2}\ {\rm m\,s^{-1}}\) |
| 有符号轴力 | \(1.140\times10^{-3}\ {\rm N}\) | \(5.186\times10^{-3}\ {\rm N}\) |
| 非负张力 | \(1.139\times10^{-3}\ {\rm N}\) | \(5.186\times10^{-3}\ {\rm N}\) |
| 机械能 | \(1.443\times10^{-7}\ {\rm J}\) | \(1.563\times10^{-7}\ {\rm J}\) |

作为旁证，这 26 个原始误差量均低于早先在结果出现前冻结的对应时间/空间阈值；最紧的是网格 RMS 有符号轴力，为空间预算的 11.4%。这不是把短窗升级为完整资格，只说明目标网格和时间步在释放瞬态上已经具有充足实用裕量。

细网格最小归一守卫为
\(7.5666\times10^{-5}\)，限制分量是 `ROD_SELF_CLEARANCE`，对应原始净空约
\(2.47\times10^{-5}\ {\rm m}\)。它严格为正，但低于旧完整资格矩阵要求的
\(3\times10^{-4}\) 额外安全裕量；因此本文只给出“个人科研目标算例可用”的
结论，不声称该短窗已经通过旧形式资格。

原始证据文件：

- `validation/representative_hf_sensitivity.json`，SHA-256
  `a2fb9189174522d10d3a6b228c29a362d224faf33942a30c3f5e3cf3257b4160`；
- `validation/representative_hf_sensitivity_series.npz`，SHA-256
  `34d2d4747b232d55fb9db7e308f38988a544314c16c166d8d87d677281d0dfcc`。

### 18.4 0.12 s 目标长窗

目标网格 24/24/32、正式 held 初态、
\(h_{\rm out}=7.8125\times10^{-6}\ {\rm s}\)、Radau、
\(\alpha=1\) 的 0.12 s 原始科学运行已经完成并保存到
`validation/target_hf_0p12_raw/`：

| 量 | 结果 |
|---|---:|
| 有效返回窗 | \([0,0.12]\ {\rm s}\) |
| presentation / accepted samples | 15,361 / 15,362 |
| 隐式积分墙钟 | 4,881.448 s |
| 从首次配置写入到结果写入的目录时间差 | 约 13,536.44 s；含制备、积分、旧串行后处理和 I/O，不是独立单调计时器 |
| \(n_{\rm fev},n_{\rm jev},n_{\rm lu}\) | 107,544 / 3 / 30,714 |
| 初态自由材料珠残差 | \(1.5437\times10^{-9}\ {\rm N}\) |
| 初态 Hessian 最小特征值 | \(5.84987\times10^{-3}\ {\rm N\,m^{-1}}\) |
| 有符号轴力全局范围 | \([-3.8320\times10^{-3},1.08528]\ {\rm N}\) |
| 非负张力全局范围 | \([0,1.08528]\ {\rm N}\) |
| 最大能量账本残差 | \(7.91404\times10^{-11}\) |
| 最大四元数范数误差 | \(4.10783\times10^{-15}\) |
| 摆球最大位移 / 速度 | \(5.58362\times10^{-2}\ {\rm m}\) / \(6.95859\times10^{-1}\ {\rm m\,s^{-1}}\) |
| 结点最大位移 / 速度 | \(1.74859\times10^{-2}\ {\rm m}\) / \(6.66760\times10^{-1}\ {\rm m\,s^{-1}}\) |
| 摆球最大角速度 | \(2.36571\ {\rm rad\,s^{-1}}\) |
| 轴向状态事件 | 12 个采样括区事件；没有物理守卫退出事件 |

11 个样本守卫全窗严格为正。最小的是 `ROD_SELF_CLEARANCE`，净裕量为
\(2.46673\times10^{-5}\ {\rm m}\)；其余关键最小值包括
`BOB_ROD_CLEARANCE` \(1.57268\times10^{-2}\ {\rm m}\)、
`MINIMUM_SEGMENT_LENGTH` \(5.09212\times10^{-3}\ {\rm m}\) 和
`JUNCTION_SOCKET_CUT_CLEARANCE` \(2.96706\times10^{-3}\ {\rm m}\)。所有保存的
状态、力、能量和守卫数组均有限，且逐段满足
\(T=\max(F_{\rm axial},0)\)。

原始状态仍诚实保留为
`UNDETERMINED / SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED`：这条运行没有在后续范围
收缩后继续执行完整六候选形式资格矩阵。原始科学结果写盘后曾进入可选形式证书
阶段，但该阶段在用户“不再要求生产级验收”的新边界下停止；没有把证书中止写成
动力学失败。由于 0.12 s 只覆盖约 0.25 个候选低频周期，主频和 3:2 频率比均
标记为不可靠，不能从这条短物理时间窗推断闭合轨道或锁频。

身份与主要文件：

- 运行期源码起止 SHA-256：
  `0e12494439d5781857c76892f5161236d9c35bc809c0f3907df92df7905b2a5e`；
- 解析配置 SHA-256：
  `39cab48840410b4a11e5593395acb146cd71c226da435dfebe0446e7356ec6ec`；
- `result.h5`：
  `b1ba3b0fb343d31f95de596fd40c5dfef98b2df7736b40e11085b3cff464eb81`；
- `summary.json`：
  `4bb8ad93ab2eec217e4cb0ead1cd871c3635c9a79c797bdc0f6f2f38a79524eb`；
- `diagnostics.json`：
  `1f627891e04b1b919c3b5bd5fe460ffd589ec37003ec3f97f321356819483b8f`；
- `events.json`：
  `3a8022c8ff4f72a618bc6744c7e1e01a9d60a49c082c7d2ed93e4ba2c4badacd`。

### 18.5 性能优化实测

优化严格使用同一目标初态做 1 ms 新鲜积分对照，并用完整 0.12 s 保存状态做全
样本后处理对照。保留的改动是：单样本评估去重、固定拓扑/接触注册、NumPy
批处理、固定分块 `spawn` 多进程和积分 checkpoint。

1 ms 端到端结果（优化后含 checkpoint 写入）：

| 指标 | 优化前 | 优化后 12 worker | 加速比 |
|---|---:|---:|---:|
| 总墙钟 | 113.749 s | 5.226 s | 21.77× |
| 积分 | 39.384 s | 3.703 s | 10.63× |
| 后处理及开销 | 74.366 s | 1.523 s | 48.84× |
| 进程树峰值 RSS | 212.9 MB | 228.5 MB | — |
| 后处理平均等效 CPU 核 | 约 1 | 13.106 | — |
| 模拟 GPU | 未使用 | 未使用 | — |

59 组科学数组全部通过；57 组逐位相等，最大绝对差
\(6.94\times10^{-18}\)，事件相同。完整 15,361 样本后处理实测为：串行
191.074 s，8 worker 29.096 s（6.57×、平均 7.94 核），12 worker 20.806 s
（9.18×、平均 11.91 核）；12-worker 进程树峰值约 507 MB。44 组完整输出和
12 个事件身份全部通过，最大差 \(2.22\times10^{-16}\)。

checkpoint 的同源码 1 ms 回放把 5.226 s 完整运行缩成 1.513 s 后处理，59 组
数组逐位相等。其主要科学价值是：长积分一旦成功，即使后处理失败或改变，也不
必重新支付积分时间。

这里必须区分两类证据：完成的 0.12 s 轨迹由优化前源码积分；优化后没有重跑
同等级长积分。优化后动力学由新鲜 1 ms 运行支持，完整长窗只对同一保存状态重算
了全部输出。详细命令、CPU/GPU/内存和机器可读数据见程序目录中的
`docs/performance_optimization.md` 与
`validation/performance/performance_optimization_report.json`。

---

## 19. 适用范围与限制

当前模型明确不包含：

1. 截面 director、扭转、剪切和各向异性；
2. 塑性、损伤、断裂、长期滞回及温湿度演化；
3. 结点有限尺寸、结点转动惯量与结点摩擦；
4. 接触后的冲量、摩擦、柔顺、粘附和碰撞恢复；
5. 穿环滑动、打结重排与材料跨支交换；
6. 柔性支架和摆的双向耦合；
7. 非球形摆球、各向异性惯量及自转气动矩；
8. 完整 CFD 或流固耦合；
9. 地面、笔尖、漏沙、颗粒或容器内流动；
10. 未标定像素到米的自动换算；
11. 真实实验意义上的模型验证。

因此本层回答的是：给定局部材料、几何、刚体和环境参数后，有效域内的离散 Newton–Euler 候选轨迹，以及该轨迹对网格和时间步的敏感性。它不能单独证明哪个物理模型“本质上正确”，也不在本文提炼普适结构律。

---

## 20. 与第 4 层的交接边界

第 3 层只向第 4 层交付：

- 冻结的 HF 方程、参数和适用域；
- 目标轨迹与公共可观测输出；
- 代表性网格和时间步差异；
- 与冻结前向后端在公共可观测量上的差异；
- 失效时刻、守卫边界和未定义物理。

尺度分析、主导机制、分岔、模式锁定、慢流形、稳定性边界和实验可证伪规律都属于第 4 层，必须写入独立 Markdown，不能回填到本层方程中。

---

## 21. 参考资料与实现关系

1. M. Bergou, M. Wardetzky, S. Robinson, B. Audoly, E. Grinspun, “Discrete Elastic Rods,” *ACM Transactions on Graphics* 27(3), 2008。本实现只借用局部中心线弯曲思想，不声称实现完整 framed rod。
2. W. R. Hamilton, “On Quaternions and the Rotation of a Solid Body,” *Proceedings of the Royal Irish Academy* 4 (1850), 38–56。
3. SciPy `solve_ivp`、`Radau` 和 `BDF` 的算法文档。SciPy 提供积分器；本项目定义物理 RHS、初态制备、能量账本、守卫和敏感性。

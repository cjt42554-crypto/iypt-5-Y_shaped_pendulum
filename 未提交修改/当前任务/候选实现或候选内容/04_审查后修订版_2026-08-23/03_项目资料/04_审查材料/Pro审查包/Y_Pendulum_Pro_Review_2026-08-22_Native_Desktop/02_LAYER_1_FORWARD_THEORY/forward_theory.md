# IYPT 2027 第 5 题 Y 形摆：前向预测理论

> **研究层级**：第 1 层——前向预测理论  
> **规范主模型**：`FWD-CABLE-1.0`  
> **解析降阶模型**：`FWD-TORUS-1.0`  
> **冻结日期**：2026-08-21  
> **文档性质**：物理—数学模型合同  
> **明确排除**：数值离散与算法、高保真后端、结构性理论

---

## 0. 结论、题意边界与完成口径

### 0.1 官方题意与本文自选装置

IYPT 官方第 5 题要求构造绳线呈 Y 形的 Bowditch pendulum，并研究摆球产生的 Lissajous 图样如何依赖相关参数。题目由 IOC 于 2026 年 7 月 14 日批准；原题可由 [IYPT 官方题目页](https://iypt.org/iypt-2027-problems/) 和 [官方最终版 PDF](https://iypt.org/wp-content/uploads/2026/07/IYPT-Problems-for-2027-final-edition-web.pdf) 核验。

官方题面没有规定：

- 两个上支点是否等高或左右对称；
- 上部是两段独立材料绳，还是一根穿环滑动的连续绳；
- 汇合处是固定材料结、滑环，还是有质量连接件；
- 绳是否始终张紧、是否可伸长、是否有质量；
- 摆球是质点还是有限刚体；
- 支点运动、空气、接触和图样记录方式。

为把开放题转化为确定的前向问题，本文自行选择：

1. 两条独立上支与一条下支在无滑移材料连接结点 \(J\) 汇合；
2. 三支均为有质量、可伸长、仅受拉的轴向柔索；
3. 连接结点质量 \(m_J>0\)，摆球为点质量 \(m>0\)；
4. 两个上支点的位置是规定函数 \(A(t),B(t)\)，固定且等高只是常用实验特例；
5. 空气速度场和外力可以作为预先给定的输入；
6. 不包含连接处滑移、断裂、物体接触、弯曲/扭转刚度、有限尺寸摆球姿态和动态支架反馈。

这些是本文模型假设，不是官方题面的追加规定。James Dean 于 1815 年描述过由两条上支和一条下支构成的 Y 形装置；Nathaniel Bowditch 同年分析了二点悬挂摆并报告实验。原始扫描分别见 [Dean 论文](https://archive.org/details/mobot31753002119169/page/n248/mode/2up) 与 [Bowditch 论文](https://archive.org/details/mobot31753002119169/page/n420/mode/2up)。本文的连续柔索模型和现代坐标方程均针对上述自选装置重新定义，不是对历史论文逐式转录。

### 0.2 严格层级边界

本文只回答：

> 给定模型、全部物理参数、完整初态、外部输入和观察终止时刻后，模型规定什么状态演化，以及以什么状态结束本次预测？

本文明确不回答：

| 排除内容 | 独立后续交付物 |
|---|---|
| 网格、形函数、质量矩阵装配、时间积分器、步长、容差、事件定位、误差估计、收敛阶 | 前向预测理论的数值计算理论与程序 |
| 从更局部、更少约化的杆、柔索、连接件、刚体和接触规律建立的独立计算路径 | 第一性原理高保真模拟 |
| 频率比设计、有限振幅频移、锁频、内共振、正规形、Poincaré 映射、分岔、稳定性、混沌和参数控制律 | 结构性理论 |

运动方程、状态、本构、边界、初态、能量、观测和退出规则属于前向理论，因而保留；由这些方程进一步提炼的结构规律不提前写入本层。

### 0.3 模型注册表

| `model_id` | 角色 | 阶段门状态 | 明确有效域 |
|---|---|---|---|
| `FWD-CABLE-1.0` | 规范主模型 | 条件性 GO | 有质量、可伸长、仅受拉轴向柔索；有限质量结点；点质量摆球；无接触、滑移、断裂和弯扭；唯一强解存在 |
| `FWD-TORUS-1.0` | 解析降阶前向模型 | 首次失张前 GO | 无质量、不可伸长、三支严格正张力、等高固定支点、点质量摆球 |

两者是从 \(t=0\) 起分别冻结的独立模型，禁止在看到轨迹后临时互换。`FWD-TORUS-1.0` 到达失张边界时返回终止状态；它不会凭四个环面状态变量临时“提升”为包含三条完整绳形的 `FWD-CABLE-1.0` 状态。

本文不注册旧稿中的“无质量解析结点 + 有限质量冲量”混合状态机。这两部分具有不同状态空间，原有重置映射不足以唯一续接。`FWD-CABLE-1.0` 从初始时刻起固定使用有限质量、有限刚度和仅受拉本构，在同一状态空间中描述受拉、松弛与重新受拉。

### 0.4 前向输出与“闭合”的准确含义

规范物理输出为

$$
\boxed{
\mathcal R_F^{\mathrm{phys}}
=
\left(
\mathsf S,\tau,
\boldsymbol X|_{\mathbb I_{\mathrm{ret}}},
\boldsymbol D_F|_{\mathbb I_{\mathrm{ret}}},
\mathcal E_\tau
\right).
}
\tag{F.1}
$$

其中：

- \(\boldsymbol X\) 是完整物理状态；
- \(\boldsymbol D_F\) 是第 5.5 节逐项冻结的派生输出；
- \(\tau\le T\) 是实际返回的有效终止时刻；
- \(\mathcal E_\tau\) 是同刻触发的全部退出谓词；
- \(\mathsf S\) 是状态标志集合，其允许值只包括
  \(\{\texttt{COMPLETED}\}\)、
  \(\{\texttt{INVALID_INPUT}\}\)、
  \(\{\texttt{OUT_OF_SCOPE}\}\)、
  \(\{\texttt{REGULARITY_LOSS}\}\) 和
  \(\{\texttt{OUT_OF_SCOPE},\texttt{REGULARITY_LOSS}\}\)。

`COMPLETED` 与任何退出标志不得并列；`INVALID_INPUT` 也不得与其他标志并列。

返回时间集按状态固定为

$$
\mathbb I_{\mathrm{ret}}=
\begin{cases}
[0,T],&\mathsf S=\{\texttt{COMPLETED}\},\\
[0,\tau),&\text{发生提前退出}.
\end{cases}
$$

提前退出时，若终止左极限存在，还要把
\(\boldsymbol X(\tau^-),\boldsymbol D_F(\tau^-)\) 与守卫值写入
\(\mathcal E_\tau\)；这不授权对 \(\tau\) 之后续接。

无效输入的正式结果为

$$
\boxed{
\mathcal R_{F,\mathrm{invalid}}^{\mathrm{phys}}
=
\left(
\{\texttt{INVALID_INPUT}\},
0,\varnothing,\varnothing,
\mathcal E_{\mathrm{input}}
\right),
\qquad
\mathbb I_{\mathrm{ret}}=\varnothing.
}
$$

\(\mathcal E_{\mathrm{input}}\) 必须列出全部失败输入谓词、实际值和期望条件。

给出观测合同后，观测增强输出另定义为

$$
\boxed{
\mathcal R_F^{\mathrm{obs}}
=
\left(
\mathcal R_F^{\mathrm{phys}},
\mathsf S_{\mathrm{obs}},
\{\overline{\boldsymbol Y}_k\}_{k\in\mathcal K_{\mathrm{valid}}},
\mathcal E_{\mathrm{obs}}
\right).
}
\tag{F.2}
$$

\(\mathsf S_{\mathrm{obs}}\) 是
\(\{\texttt{OBSERVATION_INPUT_VALID}\}\) 或
\(\{\texttt{INVALID_OBSERVATION_INPUT}\}\)；
\(\mathcal K_{\mathrm{valid}}\) 是返回时间集内且逐样本投影合法的索引；
\(\mathcal E_{\mathrm{obs}}\) 列出全部静态观测输入错误和逐样本无效原因。
观测输入无效时，物理结果保持不变，观测样本集合为空。

因此，物理输入并不凭空包含相机。只有
\(\mathsf S=\{\texttt{COMPLETED}\}\)
才支持“模型给出整个 \([0,T]\) 状态”的声称。合法终止不是实验支持模型的证据，也不是用任意规则继续计算的许可。

本文所称“闭合”是模型规格意义的条件闭合：在完整输入、已声明有效域和唯一强解存在的条件下，后续演化不需要临时补充物理规则。本文不把它夸大为退化连续柔索在最弱能量空间中的全局存在唯一性定理。

---

## 1. 规范主模型 `FWD-CABLE-1.0` 的输入合同

### 1.1 拓扑、材料坐标与方向

支路集合为

$$
\mathcal B_s=\{A,B,\ell\}.
$$

每支柔索使用无载参考弧长材料坐标

$$
S\in[0,L_i^0],\qquad i\in\mathcal B_s.
$$

材料方向固定为：

- 上支 \(A\)：从支点 \(A(t)\) 指向连接结点 \(J\)；
- 上支 \(B\)：从支点 \(B(t)\) 指向连接结点 \(J\)；
- 下支 \(\ell\)：从连接结点 \(J\) 指向摆球质心。

“无滑移材料连接结点”表示三支在 \(J\) 处的材料端点身份固定。若实际装置是一根穿环滑动的连续上绳，其长度约束和张力分配均不同，不属于本模型。

### 1.2 规范动力学参数集

取 \(\boldsymbol e_z\) 为竖直向下单位向量，重力加速度为 \(g\boldsymbol e_z\)。规范参数集为

$$
\boxed{
\begin{aligned}
\boldsymbol\Theta_F=\big(&g,
\{L_i^0,\mu_i,EA_i,C_{a,i},\delta_i,
c_{\parallel i},c_{\perp i},
d_{\parallel i},d_{\perp i},
\mathcal D_i^{\mathrm{mat}}\}_{i\in\mathcal B_s},\\
&m_J,m,\rho_a,V_{\mathrm{bob}},
c_{1b},c_{2b},\lambda_{\min}\big).
\end{aligned}
}
\tag{F.3}
$$

| 符号 | 意义 | SI 单位或类型 |
|---|---|---|
| \(g\) | 当地重力加速度大小 | \(\mathrm{m\,s^{-2}}\) |
| \(L_i^0\) | 第 \(i\) 支无载参考弧长 | \(\mathrm m\) |
| \(\mu_i\) | 第 \(i\) 支单位参考长度质量 | \(\mathrm{kg\,m^{-1}}\) |
| \(EA_i\) | 轴向拉伸刚度 | \(\mathrm N\) |
| \(C_{a,i}\) | 轴向 Kelvin–Voigt 黏性系数 | \(\mathrm{N\,s}\) |
| \(\delta_i\) | 松弛区到线性受拉区的平滑宽度 | 无量纲 |
| \(c_{\parallel i},c_{\perp i}\) | 单位参考长度线性空气阻力系数 | \(\mathrm{N\,s\,m^{-2}}\) |
| \(d_{\parallel i},d_{\perp i}\) | 单位参考长度二次空气阻力系数 | \(\mathrm{N\,s^2\,m^{-3}}\) |
| \(\mathcal D_i^{\mathrm{mat}}\) | 允许的 \((\lambda_i,\dot\lambda_i)\) 材料状态域 | 预先冻结的集合 |
| \(m_J,m\) | 连接结点质量、摆球质量 | \(\mathrm{kg}\) |
| \(\rho_a\) | 空气密度 | \(\mathrm{kg\,m^{-3}}\) |
| \(V_{\mathrm{bob}}\) | 摆球排开空气的体积 | \(\mathrm{m^3}\) |
| \(c_{1b},c_{2b}\) | 摆球线性、二次阻力系数 | \(\mathrm{N\,s\,m^{-1}}\)、\(\mathrm{N\,s^2\,m^{-2}}\) |
| \(\lambda_{\min}\) | 排除中心线切向退化的合同下界 | 无量纲 |

规范符号条件为

$$
g,L_i^0,\mu_i,EA_i,m_J,m,\delta_i,\lambda_{\min}>0,
$$

$$
C_{a,i},c_{\parallel i},c_{\perp i},
d_{\parallel i},d_{\perp i},
\rho_a,V_{\mathrm{bob}},c_{1b},c_{2b}\ge0.
$$

本 `model_id` 只采用第 2.4 节的平滑、仅受拉 Kelvin–Voigt 本构。Maxwell、迟滞或其他内变量材料必须获得新的模型 ID，并给出内部状态、自由能、耗散关系和初态；不得在本次运行中临时替换。

### 1.3 外部输入函数与退出守卫

给定整个观察区间上的外部输入

$$
\boxed{
\begin{aligned}
\boldsymbol U_F|_{[0,T]}=\big(
&A(t),B(t),
\boldsymbol u_a(\boldsymbol r,t),\\
&\{\boldsymbol f_{\mathrm{ext},i}(S,t)\}_{i\in\mathcal B_s},
\boldsymbol F_{\mathrm{ext},J}(t),
\boldsymbol F_{\mathrm{ext},b}(t)
\big).
\end{aligned}
}
\tag{F.4}
$$

其中：

- \(A(t),B(t)\) 是规定运动支点；固定支点取常向量；
- \(\boldsymbol u_a\) 是空气速度场；静止空气取零；
- \(\boldsymbol f_{\mathrm{ext},i}\) 是单位参考长度外力；
- \(\boldsymbol F_{\mathrm{ext},J},\boldsymbol F_{\mathrm{ext},b}\) 是结点和摆球外力。

规范输入正则性至少要求

$$
A,B\in C^2([0,T];\mathbb R^3),
\qquad
\boldsymbol F_{\mathrm{ext},J},
\boldsymbol F_{\mathrm{ext},b}\in
C^0([0,T];\mathbb R^3),
$$

$$
\boldsymbol f_{\mathrm{ext},i}
\in C^0([0,T];L^2(0,L_i^0;\mathbb R^3)),
$$

并要求 \(\boldsymbol u_a(\boldsymbol r,t)\) 在所有可达位置上关于
\((\boldsymbol r,t)\) 连续、关于 \(\boldsymbol r\) 局部 Lipschitz。
每个材料有效域 \(\mathcal D_i^{\mathrm{mat}}\) 是预测前冻结的开集；
每个退出守卫在 \(\mathscr C_F^{\mathrm{str}}\) 轨迹上连续。若需要唯一的事件法向或事件时刻导数，
相应守卫还须在该邻域可微。

规定支点不是动态支架。若支点需要由支架受力反过来决定，则支架自由度必须进入另一个闭合模型，不能同时把 \(A(t),B(t)\) 当作已知输入。

模型外几何事件由预测前冻结的可选守卫集

$$
\boxed{
\mathcal G_{\mathrm{exit}}
=
\{g_k^{\mathrm{exit}}(\boldsymbol X,t)\}_{k=1}^{n_g},
\qquad
g_k^{\mathrm{exit}}>0\ \text{表示模型仍有效}.
}
\tag{F.5}
$$

描述。无接触风险的理想装置取 \(n_g=0\)。有障碍物、绳—绳或摆球—支架风险时，守卫几何、间隙符号和阈值必须在预测前给出；本文只在守卫到零时终止，不定义接触后的力、摩擦或冲量。

### 1.4 完整初态

完整初态为

$$
\boxed{
\boldsymbol X_0=
\left(
\{\boldsymbol r_{i0}(S),\boldsymbol v_{i0}(S)\}_{i\in\mathcal B_s},
\boldsymbol r_{J0},\boldsymbol v_{J0},
\boldsymbol r_{m0},\boldsymbol v_{m0}
\right).
}
\tag{F.6}
$$

必须满足端点位置与速度相容：

$$
\boxed{
\begin{aligned}
\boldsymbol r_{A0}(0)&=A(0),&
\boldsymbol v_{A0}(0)&=\dot A(0),\\
\boldsymbol r_{B0}(0)&=B(0),&
\boldsymbol v_{B0}(0)&=\dot B(0),\\
\boldsymbol r_{A0}(L_A^0)&=\boldsymbol r_{J0},&
\boldsymbol v_{A0}(L_A^0)&=\boldsymbol v_{J0},\\
\boldsymbol r_{B0}(L_B^0)&=\boldsymbol r_{J0},&
\boldsymbol v_{B0}(L_B^0)&=\boldsymbol v_{J0},\\
\boldsymbol r_{\ell0}(0)&=\boldsymbol r_{J0},&
\boldsymbol v_{\ell0}(0)&=\boldsymbol v_{J0},\\
\boldsymbol r_{\ell0}(L_\ell^0)&=\boldsymbol r_{m0},&
\boldsymbol v_{\ell0}(L_\ell^0)&=\boldsymbol v_{m0}.
\end{aligned}
}
\tag{F.7}
$$

定义可由输入本身检查的强初态迹空间

$$
\boxed{
\begin{aligned}
\mathcal X_{F,0}^{\mathrm{str}}
=\big\{\boldsymbol X_0:\;&
\boldsymbol r_{i0},\boldsymbol v_{i0}
\in H^2(0,L_i^0;\mathbb R^3),\\
&
N_{i0}\boldsymbol t_{i0}
\in H^1(0,L_i^0;\mathbb R^3),\\
&\text{式 (F.7) 的位置、速度迹相容成立},\\
&
\operatorname*{ess\,inf}_S\lambda_{i0}
>\lambda_{\min},\\
&
(\lambda_{i0},\dot\lambda_{i0})
\in\mathcal D_i^{\mathrm{mat}}
\quad\text{对每支几乎处处成立}
\big\}.
\end{aligned}
}
$$

这里的 \(\lambda_{i0},\dot\lambda_{i0},\boldsymbol t_{i0},N_{i0}\)
均按第 2 节本构由
\((\boldsymbol r_{i0},\boldsymbol v_{i0})\)
计算。局部强解是否实际存在不是一个可由静态输入格式检查替代的条件，
而由第 6.2 节的最大唯一强解寿命处理。

### 1.5 完整一次预测输入

规范物理输入为

$$
\boxed{
\mathcal I_F=
\left(
\texttt{FWD-CABLE-1.0},
\boldsymbol\Theta_F,
\boldsymbol X_0,
\boldsymbol U_F|_{[0,T]},
\mathcal G_{\mathrm{exit}},
T
\right).
}
\tag{F.8}
$$

要求 \(T>0\)。定义穷尽式输入合法谓词

$$
\boxed{
\begin{aligned}
\mathsf{Valid}_F(\mathcal I_F)
\Longleftrightarrow{}&
\big[\text{模型 ID 正确}\big]\\
&\land\big[\text{第 1.2 节全部参数的类型、SI 单位、
有限性、符号及材料域开集条件成立}\big]\\
&\land\big[\text{第 1.3 节全部外部输入和守卫的
类型、有限性、定义域及正则性成立}\big]\\
&\land\big[\boldsymbol X_0\in
\mathcal X_{F,0}^{\mathrm{str}}\big]\\
&\land\big[g_k^{\mathrm{exit}}(\boldsymbol X_0,0)>0
\ \text{对全部 }k\big]\\
&\land[0<T<+\infty].
\end{aligned}
}
$$

这里“有限性”包括所有标量和向量分量为有限实数；函数输入在其声明定义域内取有限值。
任何未列入 \(\mathcal I_F\) 的物理量不得在看到预测或实验轨迹后临时加入。

---

## 2. 状态、运动学与仅受拉本构

### 2.1 完整状态

令

$$
\boldsymbol r_i=\boldsymbol r_i(S,t),
\qquad
\boldsymbol v_i=\partial_t\boldsymbol r_i.
$$

完整状态为

$$
\boxed{
\boldsymbol X(t)=
\left(
\{\boldsymbol r_i(\cdot,t),\boldsymbol v_i(\cdot,t)\}_{i\in\mathcal B_s},
\boldsymbol r_J,\boldsymbol v_J,
\boldsymbol r_m,\boldsymbol v_m
\right).
}
\tag{F.9}
$$

张力、伸长、能量、受拉区和观测量由 \(\boldsymbol X\) 与输入唯一派生，不重复作为独立状态。

### 2.2 伸长比、切向与伸长率

定义

$$
\boxed{
\lambda_i=|\boldsymbol r_{i,S}|,
\qquad
\boldsymbol t_i=\frac{\boldsymbol r_{i,S}}{\lambda_i},
\qquad
\dot\lambda_i=\boldsymbol t_i\cdot\boldsymbol v_{i,S}.
}
\tag{F.10}
$$

\(\lambda_i=1\) 对应无载参考长度；\(\lambda_i<1\) 允许相邻材料点靠近，但柔索不提供轴向压力。条件 \(\lambda_i>\lambda_{\min}\) 保证单位切向有定义。

### 2.3 平滑仅受拉激活函数

对规范分支的 \(\delta>0\)，定义

$$
\mathcal P_\delta(x)=
\begin{cases}
0,&x\le0,\\[1mm]
\dfrac{x^2(2\delta-x)}{\delta^2},&0<x<\delta,\\[2mm]
x,&x\ge\delta,
\end{cases}
$$

$$
\boxed{
\mathcal P_\delta'(x)=
\begin{cases}
0,&x\le0,\\[1mm]
\dfrac{4x}{\delta}-\dfrac{3x^2}{\delta^2},&0<x<\delta,\\[2mm]
1,&x\ge\delta.
\end{cases}
}
\tag{F.11}
$$

\(\mathcal P_\delta\in C^1(\mathbb R)\)，且 \(\mathcal P_\delta,\mathcal P_\delta'\ge0\)。张紧起点的切线模量趋于零；本文不假设整个受拉区存在虚假的统一正切线模量下界。

### 2.4 规范轴向本构

弹性候选张力、黏性候选张力和物理张力为

$$
N_{e,i}=EA_i\mathcal P_{\delta_i}(\lambda_i-1),
$$

$$
N_{v,i}=C_{a,i}\mathcal P_{\delta_i}'(\lambda_i-1)\dot\lambda_i,
$$

$$
\boxed{
N_i=[N_{e,i}+N_{v,i}]_+\ge0,
\qquad [x]_+=\max(x,0).
}
\tag{F.12}
$$

受拉区与松弛区定义为

$$
\boxed{
\mathcal A_i(t)=\{S:N_i(S,t)>0\},
\qquad
\mathcal S_i(t)=\{S:N_i(S,t)=0\}.
}
\tag{F.13}
$$

受拉、松弛和重新受拉由同一式 (F.12) 决定。这里没有把无质量结点模型和有限质量冲量模型拼接起来；连续有限刚度模型始终保持同一状态空间。若解在张紧—松弛界面丧失本文要求的正则性，则按第 6 节返回 `REGULARITY_LOSS`。

### 2.5 空气相对速度与阻力

相对空气速度为

$$
\boldsymbol u_i=
\boldsymbol v_i-\boldsymbol u_a(\boldsymbol r_i,t).
$$

定义

$$
\mathsf P_{\parallel i}=\boldsymbol t_i\boldsymbol t_i^{\mathsf T},
\qquad
\mathsf P_{\perp i}=I-\mathsf P_{\parallel i},
$$

$$
\boldsymbol u_{\parallel i}=\mathsf P_{\parallel i}\boldsymbol u_i,
\qquad
\boldsymbol u_{\perp i}=\mathsf P_{\perp i}\boldsymbol u_i.
$$

单位参考长度阻力为

$$
\boxed{
\begin{aligned}
\boldsymbol f_{d,i}={}&
-c_{\parallel i}\boldsymbol u_{\parallel i}
-c_{\perp i}\boldsymbol u_{\perp i}\\
&-d_{\parallel i}|\boldsymbol u_{\parallel i}|\boldsymbol u_{\parallel i}
-d_{\perp i}|\boldsymbol u_{\perp i}|\boldsymbol u_{\perp i}.
\end{aligned}
}
\tag{F.14}
$$

摆球相对空气速度和阻力为

$$
\boldsymbol u_b=
\boldsymbol v_m-\boldsymbol u_a(\boldsymbol r_m,t),
$$

$$
\boxed{
\boldsymbol F_{d,b}
=-c_{1b}\boldsymbol u_b-c_{2b}|\boldsymbol u_b|\boldsymbol u_b.
}
\tag{F.15}
$$

规范分支忽略三支柔索和连接结点的排空气体积、浮力与附加质量，只保留摆球浮力；空气密度在装置尺度上视为均匀。

---

## 3. 控制方程、边界条件与初始条件

### 3.1 柔索连续场方程

对每支 \(i\in\mathcal B_s\) 及 \(0<S<L_i^0\)，

$$
\boxed{
\begin{aligned}
\partial_t\boldsymbol r_i&=\boldsymbol v_i,\\
\mu_i\partial_t\boldsymbol v_i
&=\partial_S(N_i\boldsymbol t_i)
+\mu_i g\boldsymbol e_z
+\boldsymbol f_{d,i}
+\boldsymbol f_{\mathrm{ext},i}.
\end{aligned}
}
\tag{F.16}
$$

### 3.2 连接结点方程

按第 1.1 节材料方向，连接结点满足

$$
\boxed{
\begin{aligned}
\dot{\boldsymbol r}_J&=\boldsymbol v_J,\\
m_J\dot{\boldsymbol v}_J
&=m_Jg\boldsymbol e_z
-N_A(L_A^0)\boldsymbol t_A(L_A^0)
-N_B(L_B^0)\boldsymbol t_B(L_B^0)\\
&\quad
+N_\ell(0)\boldsymbol t_\ell(0)
+\boldsymbol F_{\mathrm{ext},J}.
\end{aligned}
}
\tag{F.17}
$$

### 3.3 摆球方程

摆球浮力为

$$
\boldsymbol F_{\mathrm{buoy}}
=-\rho_aV_{\mathrm{bob}}g\boldsymbol e_z.
$$

点质量摆球满足

$$
\boxed{
\begin{aligned}
\dot{\boldsymbol r}_m&=\boldsymbol v_m,\\
m\dot{\boldsymbol v}_m
&=(m-\rho_aV_{\mathrm{bob}})g\boldsymbol e_z
+\boldsymbol F_{d,b}
+\boldsymbol F_{\mathrm{ext},b}\\
&\quad
-N_\ell(L_\ell^0)\boldsymbol t_\ell(L_\ell^0).
\end{aligned}
}
\tag{F.18}
$$

### 3.4 端点耦合条件

$$
\boxed{
\begin{aligned}
\boldsymbol r_A(0,t)&=A(t),&
\boldsymbol v_A(0,t)&=\dot A(t),\\
\boldsymbol r_B(0,t)&=B(t),&
\boldsymbol v_B(0,t)&=\dot B(t),\\
\boldsymbol r_A(L_A^0,t)&=\boldsymbol r_J(t),&
\boldsymbol v_A(L_A^0,t)&=\boldsymbol v_J(t),\\
\boldsymbol r_B(L_B^0,t)&=\boldsymbol r_J(t),&
\boldsymbol v_B(L_B^0,t)&=\boldsymbol v_J(t),\\
\boldsymbol r_\ell(0,t)&=\boldsymbol r_J(t),&
\boldsymbol v_\ell(0,t)&=\boldsymbol v_J(t),\\
\boldsymbol r_\ell(L_\ell^0,t)&=\boldsymbol r_m(t),&
\boldsymbol v_\ell(L_\ell^0,t)&=\boldsymbol v_m(t).
\end{aligned}
}
\tag{F.19}
$$

### 3.5 初始条件

$$
\boxed{
\begin{aligned}
\boldsymbol r_i(S,0)&=\boldsymbol r_{i0}(S),&
\boldsymbol v_i(S,0)&=\boldsymbol v_{i0}(S),\\
\boldsymbol r_J(0)&=\boldsymbol r_{J0},&
\boldsymbol v_J(0)&=\boldsymbol v_{J0},\\
\boldsymbol r_m(0)&=\boldsymbol r_{m0},&
\boldsymbol v_m(0)&=\boldsymbol v_{m0}.
\end{aligned}
}
\tag{F.20}
$$

式 (F.3)–(F.20) 是 `FWD-CABLE-1.0` 唯一规范物理合同。本文不在后文再给第二套略有不同的“完整参数集”或“最终方程”。

---

## 4. 强解类、弱式与条件前向算子

### 4.1 本文实际声称的解类

在任意区间 \([0,t')\) 上，本文把
\(\mathscr C_F^{\mathrm{str}}([0,t'))\)
定义为满足下列解析条件的强 Sobolev 轨迹：

$$
\boxed{
\begin{aligned}
\boldsymbol r_i&\in
C^1([0,t');H^2(0,L_i^0;\mathbb R^3))
\cap C^2([0,t');L^2(0,L_i^0;\mathbb R^3)),\\
N_i\boldsymbol t_i&\in
C^0([0,t');H^1(0,L_i^0;\mathbb R^3)),\\
\boldsymbol r_J,\boldsymbol r_m&\in C^2([0,t');\mathbb R^3).
\end{aligned}
}
\tag{F.21}
$$

闭区间记号 \(\mathscr C_F^{\mathrm{str}}([0,t])\)
按同一正则性定义，只把上式的半开时间区间替换为闭区间。

此外要求：

1. 每个紧子区间上都有
   \(\operatorname*{ess\,inf}_{i,S}\lambda_i>0\)，从而单位切向有定义；
2. 式 (F.16) 在 \(L^2\) 意义下几乎处处成立；
3. 式 (F.17)–(F.20) 及相应端点迹成立。

这个正则性足以定义 \(\boldsymbol v_{i,S}\)、端点速度迹和端点牵引迹。本文不声称已证明退化张紧—松弛自由边界问题在最弱 \(H^1\times L^2\) 能量空间中全局存在且唯一；该空间本身不足以点式定义 Kelvin–Voigt 项中的 \(\boldsymbol v_{i,S}\) 和所需端点迹。

人为选择的 \(\lambda_{\min}\)、材料有效域和模型外守卫不属于解析函数空间；
它们只属于第 6.3 节的物理有效集。这样，正常的物理退出不会被重复误报为正则性丧失。

### 4.2 弱式接口

弱式用于明确整体动力学和能量符号，并作为后续数值理论的连续方程接口；本节不指定任何离散方法。

对所有在规定支点处虚位移为零、并在结点和摆球端点连续的试函数，

$$
\boxed{
\begin{aligned}
&\sum_i\int_0^{L_i^0}
\mu_i\ddot{\boldsymbol r}_i\cdot\delta\boldsymbol r_i\,dS
+m_J\ddot{\boldsymbol r}_J\cdot\delta\boldsymbol r_J
+m\ddot{\boldsymbol r}_m\cdot\delta\boldsymbol r_m\\
&\quad
+\sum_i\int_0^{L_i^0}
N_i\boldsymbol t_i\cdot\delta\boldsymbol r_{i,S}\,dS\\
&=
\sum_i\int_0^{L_i^0}
(\mu_i g\boldsymbol e_z+\boldsymbol f_{d,i}
+\boldsymbol f_{\mathrm{ext},i})
\cdot\delta\boldsymbol r_i\,dS\\
&\quad
+(m_Jg\boldsymbol e_z+\boldsymbol F_{\mathrm{ext},J})
\cdot\delta\boldsymbol r_J\\
&\quad
+\big((m-\rho_aV_{\mathrm{bob}})g\boldsymbol e_z
+\boldsymbol F_{d,b}+\boldsymbol F_{\mathrm{ext},b}\big)
\cdot\delta\boldsymbol r_m .
\end{aligned}
}
\tag{F.22}
$$

对式 (F.22) 分部积分，恢复式 (F.16)–(F.18) 和相同的端点力符号。

### 4.3 条件前向算子

对满足输入相容性，且在 \([0,t]\) 上存在唯一
\(\mathscr C_F^{\mathrm{str}}([0,t])\) 解的输入，定义

$$
\boxed{
\boldsymbol X(t)=
\mathscr S_t^F
\left(
\boldsymbol\Theta_F,\boldsymbol X_0,
\boldsymbol U_F|_{[0,t]},
\mathcal G_{\mathrm{exit}}
\right).
}
\tag{F.23}
$$

式 (F.23) 是“完整输入在有效域内决定完整状态”的模型声明，不是省略证明条件的全局 PDE 定理。其最大返回区间和失败语义由第 6 节给出。

---

## 5. 能量、功率与耗散恒等式

### 5.1 储能与机械能

定义

$$
\Phi_\delta(x)=\int_0^x\mathcal P_\delta(u)\,du.
$$

总动能为

$$
\boxed{
T_{\mathrm{kin}}=
\frac12\sum_i\int_0^{L_i^0}
\mu_i|\boldsymbol v_i|^2\,dS
+\frac12m_J|\boldsymbol v_J|^2
+\frac12m|\boldsymbol v_m|^2.
}
\tag{F.24}
$$

重力、浮力和轴向势能为

$$
V_g=
-\sum_i\int_0^{L_i^0}
\mu_i g\boldsymbol e_z\cdot\boldsymbol r_i\,dS
-m_Jg\boldsymbol e_z\cdot\boldsymbol r_J
-mg\boldsymbol e_z\cdot\boldsymbol r_m,
$$

$$
V_{\mathrm{buoy}}
=\rho_aV_{\mathrm{bob}}g\boldsymbol e_z\cdot\boldsymbol r_m,
$$

$$
\boxed{
V_{\mathrm{ax}}=
\sum_iEA_i\int_0^{L_i^0}
\Phi_{\delta_i}(\lambda_i-1)\,dS.
}
\tag{F.25}
$$

总机械能为

$$
\boxed{
E_F=T_{\mathrm{kin}}+V_g+V_{\mathrm{buoy}}+V_{\mathrm{ax}}.
}
\tag{F.26}
$$

### 5.2 轴向和空气耗散

轴向耗散率为

$$
\boxed{
D_{\mathrm{ax}}=
\sum_i\int_0^{L_i^0}
(N_i-N_{e,i})\dot\lambda_i\,dS\ge0.
}
\tag{F.27}
$$

非负性包括式 (F.12) 最外层的正部截断：候选总张力非负时，被积项为 \(C_{a,i}\mathcal P_{\delta_i}'\dot\lambda_i^2\)；候选总张力为负并被截断时，必有 \(\dot\lambda_i<0\)，故 \(-N_{e,i}\dot\lambda_i\ge0\)。

空气耗散为

$$
D_{\mathrm{string}}
=-\sum_i\int_0^{L_i^0}
\boldsymbol f_{d,i}\cdot\boldsymbol u_i\,dS\ge0,
$$

$$
\boxed{
D_b=-\boldsymbol F_{d,b}\cdot\boldsymbol u_b\ge0.
}
\tag{F.28}
$$

### 5.3 外部功率与基座功率

按材料方向，规定支点对柔索的力为

$$
\boldsymbol R_A=-N_A(0)\boldsymbol t_A(0),
\qquad
\boldsymbol R_B=-N_B(0)\boldsymbol t_B(0).
$$

基座功率为

$$
\boxed{
P_{\mathrm{base}}
=\boldsymbol R_A\cdot\dot A
+\boldsymbol R_B\cdot\dot B.
}
\tag{F.29}
$$

移动空气对系统的功率为

$$
\boxed{
P_{\mathrm{air}}=
\sum_i\int_0^{L_i^0}
\boldsymbol f_{d,i}\cdot
\boldsymbol u_a(\boldsymbol r_i,t)\,dS
+\boldsymbol F_{d,b}\cdot
\boldsymbol u_a(\boldsymbol r_m,t).
}
\tag{F.30}
$$

外力功率为

$$
\boxed{
\begin{aligned}
P_{\mathrm{ext}}={}&
\sum_i\int_0^{L_i^0}
\boldsymbol f_{\mathrm{ext},i}\cdot\boldsymbol v_i\,dS\\
&+\boldsymbol F_{\mathrm{ext},J}\cdot\boldsymbol v_J
+\boldsymbol F_{\mathrm{ext},b}\cdot\boldsymbol v_m.
\end{aligned}
}
\tag{F.31}
$$

### 5.4 功率平衡

对规范 Kelvin–Voigt 分支的 \(\mathscr C_F^{\mathrm{str}}\) 解，

$$
\boxed{
\dot E_F=
-D_{\mathrm{ax}}-D_{\mathrm{string}}-D_b
+P_{\mathrm{air}}+P_{\mathrm{base}}+P_{\mathrm{ext}}.
}
\tag{F.32}
$$

固定支点、静止空气、无外力时，

$$
\boxed{\dot E_F\le0.}
\tag{F.33}
$$

式 (F.25)–(F.33) 只属于已冻结的 Kelvin–Voigt 材料，不推广到未定义自由能和耗散势的一般内变量材料。

### 5.5 派生输出的冻结 schema

式 (F.1) 中的派生输出不是开放式“其他量”容器，而固定为

$$
\boxed{
\begin{aligned}
\boldsymbol D_F(t)=\big(
&\{\lambda_i,\dot\lambda_i,\boldsymbol t_i,
N_{e,i},N_{v,i},N_i,
\mathcal A_i,\mathcal S_i,L_i^{\mathrm{load}},
\boldsymbol f_{d,i}\}_{i\in\mathcal B_s},\\
&\boldsymbol F_{d,b},
T_{\mathrm{kin}},V_g,V_{\mathrm{buoy}},V_{\mathrm{ax}},E_F,\\
&D_{\mathrm{ax}},D_{\mathrm{string}},D_b,
\boldsymbol R_A,\boldsymbol R_B,
P_{\mathrm{base}},P_{\mathrm{air}},P_{\mathrm{ext}}
\big).
\end{aligned}
}
$$

后续程序可以另外缓存中间量，但不能在不提升模型版本的情况下改变
\(\boldsymbol D_F\) 的这些规范字段、物理含义或单位。

---

## 6. 有效域、最大解与终止语义

### 6.1 初始输入拒绝

若且唯若
\(\neg\mathsf{Valid}_F(\mathcal I_F)\)，
不开始演化并返回 `INVALID_INPUT`。诊断必须把失败项归入下列穷尽分类：

1. `model_id` 不是 `FWD-CABLE-1.0`，或 \(T\notin(0,+\infty)\)；
2. 参数不满足第 1.2 节类型、有限性、符号、单位或材料域开集条件；
3. \(\boldsymbol X_0\notin\mathcal X_{F,0}^{\mathrm{str}}\)；
4. 外部输入或退出守卫缺少定义，或不满足第 1.3 节类型、有限性、定义域或正则性；
5. 初始时刻任一退出守卫不为正。

拒绝结果必须按
\(\mathcal R_{F,\mathrm{invalid}}^{\mathrm{phys}}\)
列出全部失败谓词，不能静默投影、补点或修补初态。

### 6.2 观察窗内的唯一强解寿命

外部输入只在 \([0,T]\) 上给定，因此本文不询问 \(T\) 之后的解。
对合法输入定义

$$
\mathcal T_F^{\mathrm{str}}
=
\{0\}\cup
\left\{
t\in(0,T]:
\begin{array}{l}
\text{对每个 }0<s\le t,\text{ 式 (F.16)–(F.20) 在 }[0,s]\text{ 上}\\
\text{存在唯一 }
\mathscr C_F^{\mathrm{str}}([0,s])\text{ 解}
\end{array}
\right\},
$$

$$
\boxed{
\tau_{\mathrm{reg}}
=
\begin{cases}
+\infty,&T\in\mathcal T_F^{\mathrm{str}},\\
\sup\mathcal T_F^{\mathrm{str}},
&T\notin\mathcal T_F^{\mathrm{str}}.
\end{cases}
}
\tag{F.34}
$$

相应的解析可用时间集为

$$
\mathbb I_{\mathrm{str}}=
\begin{cases}
[0,T],&T\in\mathcal T_F^{\mathrm{str}},\\
[0,\tau_{\mathrm{reg}}),
&T\notin\mathcal T_F^{\mathrm{str}}.
\end{cases}
$$

这里 \(\tau_{\mathrm{reg}}=+\infty\) 只表示“整个观察窗内没有正则性退出”，
不声称 \(T\) 之后仍存在解。若没有任何正长度闭区间强解，
\(\tau_{\mathrm{reg}}=0\)。

### 6.3 物理有效集与退出时刻

沿 \(\mathbb I_{\mathrm{str}}\) 上的唯一强解，定义瞬时物理有效集

$$
\mathcal V_F(t)=
\left\{
\boldsymbol X:
\begin{array}{l}
\operatorname*{ess\,inf}_{i,S}\lambda_i(S,t)>\lambda_{\min},\\
(\lambda_i,\dot\lambda_i)\in\mathcal D_i^{\mathrm{mat}}
\quad\text{对每支几乎处处成立},\\
g_k^{\mathrm{exit}}(\boldsymbol X,t)>0
\quad\text{对全部 }k
\end{array}
\right\}.
$$

物理退出时刻为

$$
\boxed{
\tau_{\mathrm{phys}}
=
\inf\left\{
t\in\mathbb I_{\mathrm{str}}\cap(0,T]:
\boldsymbol X(t)\notin\mathcal V_F(t)
\right\}.
}
\tag{F.35}
$$

规定空集的下确界为 \(+\infty\)。连接处滑移、材料断裂、接触和自交不属于状态方程；若实验可能发生它们，必须通过式 (F.5) 的几何或材料守卫在首发时刻终止。守卫之后的数据不得继续解释为本模型预测。

当 \(0<\tau_{\mathrm{reg}}\le T\) 时，另定义
\(\mathcal E_{\mathrm{phys}}^-(\tau_{\mathrm{reg}})\)
为所有在 \(t\uparrow\tau_{\mathrm{reg}}\) 时左极限到达物理有效集边界的谓词集合。
若该集合非空，则事件记录并列保留 `OUT_OF_SCOPE` 与
`REGULARITY_LOSS`。能量不爆破不自动证明强解正则性、
张紧—松弛界面唯一性或全时间延拓。
当 \(\tau_{\mathrm{reg}}=0\) 时规定
\(\mathcal E_{\mathrm{phys}}^-=\varnothing\)。

### 6.4 最大返回区间与状态码

令

$$
\boxed{
\tau=\min(T,\tau_{\mathrm{phys}},\tau_{\mathrm{reg}}).
}
\tag{F.36}
$$

状态判定固定为：

| 条件 | \(\mathsf S\) | \(\mathcal E_\tau\) |
|---|---|---|
| \(T<\min(\tau_{\mathrm{phys}},\tau_{\mathrm{reg}})\) | \(\{\texttt{COMPLETED}\}\) | 空集 |
| \(\tau_{\mathrm{phys}}\le T\) 且 \(\tau_{\mathrm{phys}}<\tau_{\mathrm{reg}}\) | \(\{\texttt{OUT_OF_SCOPE}\}\) | 全部同刻物理守卫 |
| \(\tau_{\mathrm{reg}}\le T\)、\(\tau_{\mathrm{reg}}<\tau_{\mathrm{phys}}\)，且 \(\mathcal E_{\mathrm{phys}}^-=\varnothing\) | \(\{\texttt{REGULARITY_LOSS}\}\) | 最大强解终止原因 |
| \(\tau_{\mathrm{reg}}\le T\)、\(\tau_{\mathrm{reg}}\le\tau_{\mathrm{phys}}\)，且 \(\big[\tau_{\mathrm{phys}}=\tau_{\mathrm{reg}}\ \text{或}\ \mathcal E_{\mathrm{phys}}^-\ne\varnothing\big]\) | \(\{\texttt{OUT_OF_SCOPE},\texttt{REGULARITY_LOSS}\}\) | 全部同刻原因 |

若退出恰好发生在 \(T\)，仍返回相应退出标志，而不把它静默标为 `COMPLETED`。规范映射为

$$
\boxed{
\mathcal I_F
\longmapsto
\mathcal R_F^{\mathrm{phys}}
=
(\mathsf S,\tau,
\boldsymbol X|_{\mathbb I_{\mathrm{ret}}},
\boldsymbol D_F|_{\mathbb I_{\mathrm{ret}}},
\mathcal E_\tau).
}
\tag{F.37}
$$

状态在退出时刻的左极限和触发守卫值应进入事件记录；本文不规定退出后的续接。

---

## 7. 初态制备合同

### 7.1 两种互斥输入方式

一次预测必须在打开验证数据之前冻结以下两种方式之一：

1. `DIRECT_STATE`：直接给出式 (F.6) 的完整场初态；
2. `STATIC_HOLD_RELEASE`：由规定保持约束和静态平衡生成候选初态。

不能只给摆球位置，看到后续轨迹后再反推更合适的初始绳形或速度场。

### 7.2 静态保持—释放

设 \(\mathcal C_{\mathrm{hold}}\) 是释放前保持装置施加的完整几何约束集合。对固定支点、静止空气、无外力的规范材料，静态候选形状定义为

$$
\boxed{
\{\boldsymbol r_{i0},\boldsymbol r_{J0},\boldsymbol r_{m0}\}
\in
\operatorname*{arg\,min}_{\mathcal C_{\mathrm{hold}}}
(V_g+V_{\mathrm{buoy}}+V_{\mathrm{ax}}),
\qquad
\boldsymbol v_0=0.
}
\tag{F.38}
$$

本模型没有弯曲能；在松弛区，式 (F.38) 可能有多个中心线极小形状。若极小值不唯一，`STATIC_HOLD_RELEASE` 不产生唯一初态，必须采用以下之一：

- 独立测量并给出实际完整绳形；
- 给出使制备唯一的额外保持约束；
- 在预测前把全部候选初态冻结为不确定集合。

不得从该集合中事后挑选最贴合验证轨迹的成员。

规范释放律为：在 \(t=0\) 瞬时撤去 \(\mathcal C_{\mathrm{hold}}\)，不施加额外冲量，因此

$$
\boxed{
\boldsymbol X(0^+)=\boldsymbol X(0^-),
\qquad
\boldsymbol v(0^+)=\boldsymbol v(0^-)=0.
}
\tag{F.39}
$$

若真实释放器产生可分辨冲量，必须把其结果作为预测前测量的初速度写入 `DIRECT_STATE`，不能吸收到事后拟合阻尼。

### 7.3 参考长度与受载长度不可混用

在 `FWD-CABLE-1.0` 中，\(L_i^0\) 始终是无载材料参考长度，是独立输入。任意时刻的受载弧长

$$
\boxed{
L_i^{\mathrm{load}}(t)
=\int_0^{L_i^0}\lambda_i(S,t)\,dS
}
\tag{F.40}
$$

是由状态派生的输出。

第 9 节 `FWD-TORUS-1.0` 使用的 \(s_A,s_B,\ell\) 是另一个理想模型中的固定受载几何输入。除非以后另行建立协调的不可伸长极限族，不得把它们与 \(L_A^0,L_B^0,L_\ell^0\) 默认为同一组量。

---

## 8. 观测合同与图样定义

### 8.1 物理状态、理想观测和实际测量分层

物理预测只需要 \(\mathcal I_F\)。实验可比的理论观测还必须给出

$$
\boxed{
\mathcal I_{\mathrm{obs}}
=
\left(
\mathcal I_F,\mathcal O,
\boldsymbol p_{\mathrm{obs}},
\{t_k^{\mathrm{rec}}\},
t_0^{\mathrm{obs}}
\right),
\qquad
t_k=t_0^{\mathrm{obs}}+t_k^{\mathrm{rec}}.
}
\tag{F.41}
$$

其中 \(\mathcal O\) 是观测算子，\(\boldsymbol p_{\mathrm{obs}}\) 是其参数，\(t_k^{\mathrm{rec}}\) 是记录设备时标，\(t_0^{\mathrm{obs}}\) 把记录时标映射到模型时间。定义穷尽式静态观测输入谓词

$$
\boxed{
\begin{aligned}
\mathsf{Valid}_{\mathrm{obs}}(\mathcal I_{\mathrm{obs}})
\Longleftrightarrow{}&
\big[\mathcal O\text{ 已注册且与所选物理模型的状态类型兼容}\big]\\
&\land\big[\boldsymbol p_{\mathrm{obs}}
\text{ 满足该算子的完整 schema、定义域和有限性条件}\big]\\
&\land\big[t_0^{\mathrm{obs}},\{t_k^{\mathrm{rec}}\}
\text{ 全部为有限实数}\big].
\end{aligned}
}
$$

若该谓词成立，则
\(\mathsf S_{\mathrm{obs}}
=\{\texttt{OBSERVATION_INPUT_VALID}\}\)；
否则
\(\mathsf S_{\mathrm{obs}}
=\{\texttt{INVALID_OBSERVATION_INPUT}\}\)、
\(\mathcal K_{\mathrm{valid}}=\varnothing\)，
并在 \(\mathcal E_{\mathrm{obs}}\) 中列出全部失败项。
物理结果在两种情况下均保持不变。规范时间选择由下列返回索引统一规定。

规范采样索引为

$$
\mathcal K_{\mathrm{ret}}
=\{k:t_k\in\mathbb I_{\mathrm{ret}}\}.
$$

因此，完成运行允许 \(0\le t_k\le T\)；提前退出只允许
\(0\le t_k<\tau\)。超出返回时间集的有限时标不是静态输入错误，
但相应索引不进入预测，并必须在
\(\mathcal E_{\mathrm{obs}}\) 中记录。

理想无噪时序为

$$
\boxed{
\overline{\boldsymbol Y}_k
=\mathcal O[
\boldsymbol X(t_0^{\mathrm{obs}}+t_k^{\mathrm{rec}});
\boldsymbol p_{\mathrm{obs}}
],
\qquad
k\in\mathcal K_{\mathrm{valid}}.
}
\tag{F.42}
$$

实际测量写为

$$
\boxed{
\boldsymbol Y_k^{\mathrm{meas}}
=\overline{\boldsymbol Y}_k
+\boldsymbol b_k+\boldsymbol\varepsilon_k,
\qquad
k\in\mathcal K_{\mathrm{valid}}.
}
\tag{F.43}
$$

其中 \(\boldsymbol b_k\) 是预先界定的系统偏差，\(\boldsymbol\varepsilon_k\) 是随机噪声或受界扰动。测量噪声不改变物理状态的确定性，但决定实验是否足以拒绝预测。

### 8.2 默认观测点

规范主模型中的摆球是点质量，默认观测点为摆球质心：

$$
\boldsymbol r_{\mathrm{obs}}=\boldsymbol r_m.
$$

灯点、笔尖、喷口或漏沙落点不自动等于质心。若实际记录这些对象，其姿态偏置、喷射速度、粒子飞行或接触规律必须进入另一个观测模型。

为固定算子类型，位置观测算子记为

$$
\mathcal O_{\mathrm{pos}}:
(\boldsymbol r_{\mathrm{obs}},\boldsymbol p_{\mathrm{obs}})
\longmapsto\boldsymbol Y,
$$

主模型的默认算子是复合映射

$$
\mathcal O_F[\boldsymbol X;\boldsymbol p_{\mathrm{obs}}]
:=
\mathcal O_{\mathrm{pos}}
[\boldsymbol r_m(\boldsymbol X);\boldsymbol p_{\mathrm{obs}}].
$$

第 8.3 节的相机算子和第 8.4 节的正交算子均是
\(\mathcal O_{\mathrm{pos}}\) 的具体选择。

### 8.3 三维相机映射

令世界坐标到相机坐标的旋转为 \(\mathsf R_c\)，相机中心为 \(\boldsymbol c_c\)。定义

$$
\boxed{
\begin{pmatrix}X_c\\Y_c\\Z_c\end{pmatrix}
=\mathsf R_c(\boldsymbol r_{\mathrm{obs}}-\boldsymbol c_c),
\qquad
x_n=\frac{X_c}{Z_c},
\qquad
y_n=\frac{Y_c}{Z_c},
\qquad
r_n^2=x_n^2+y_n^2.
}
\tag{F.44}
$$

要求 \(Z_c>0\)。Brown–Conrady 畸变为

$$
\begin{aligned}
x_d={}&x_n(1+k_1r_n^2+k_2r_n^4+k_3r_n^6)
+2p_1x_ny_n+p_2(r_n^2+2x_n^2),\\
y_d={}&y_n(1+k_1r_n^2+k_2r_n^4+k_3r_n^6)
+p_1(r_n^2+2y_n^2)+2p_2x_ny_n.
\end{aligned}
\tag{F.45}
$$

像素坐标为

$$
\boxed{
u=f_xx_d+c_x,
\qquad
v=f_yy_d+c_y.
}
\tag{F.46}
$$

相机观测输入的合法域必须满足

$$
\boxed{
\mathsf R_c\in SO(3),
\qquad
\boldsymbol c_c\in\mathbb R^3,
\qquad
f_x>0,\quad f_y>0,
}
$$

且全部内参和畸变系数为有限实数。预先标定的归一化像平面有效域
\(\Omega_{\mathrm{cal}}\subset\mathbb R^2\)
也属于 \(\boldsymbol p_{\mathrm{obs}}\)。规范 schema 只有下列一套：

$$
\boldsymbol p_{\mathrm{obs}}
=
(\mathsf R_c,\boldsymbol c_c,
f_x,f_y,c_x,c_y,k_1,k_2,k_3,p_1,p_2,
\Omega_{\mathrm{cal}}).
$$

上述 schema、有限性、\(SO(3)\)、正焦距和非空标定域条件共同定义
\(\mathsf{Valid}_{\mathrm{cam,obs}}(\boldsymbol p_{\mathrm{obs}})\)。
它只是第 8.1 节
\(\mathsf{Valid}_{\mathrm{obs}}\)
的相机参数子谓词；最终观测状态仍由包含算子类型和全部时标的总谓词决定。
对满足总谓词的输入，某个样本只有在
\(Z_c>0\) 且 \((x_n,y_n)\in\Omega_{\mathrm{cal}}\)
时才进入 \(\mathcal K_{\mathrm{valid}}\)；否则记录逐样本观测无效原因。

$$
\mathcal K_{\mathrm{valid}}
=
\left\{
k\in\mathcal K_{\mathrm{ret}}:
Z_c(t_k)>0,\ 
(x_n(t_k),y_n(t_k))\in\Omega_{\mathrm{cal}}
\right\}.
$$

上式属于相机算子；其他 \(\mathcal O\) 必须在其独立 schema 中冻结自己的定义域，
正交投影的 \(\mathcal K_{\mathrm{valid}}=\mathcal K_{\mathrm{ret}}\)。
任何观测无效都不改变 \(\mathcal R_F^{\mathrm{phys}}\)。

对连续观测，定义

$$
\mathbb I_{\mathcal O,\mathrm{valid}}
=
\{t\in\mathbb I_{\mathrm{ret}}:
\boldsymbol X(t)\in\operatorname{Dom}(\mathcal O)\}.
$$

相机和正交投影分别满足

$$
\mathbb I_{\mathrm{cam,valid}}
=
\{t\in\mathbb I_{\mathrm{ret}}:
Z_c(t)>0,\ (x_n(t),y_n(t))\in\Omega_{\mathrm{cal}}\},
$$

$$
\mathbb I_{\mathrm{ortho,valid}}=\mathbb I_{\mathrm{ret}}.
$$

### 8.4 图样是时序观测的派生物

本文把理论像素时序 \(\{(t_k,u_k,v_k)\}\) 作为规范观测。连续理想图样集合

$$
\boxed{
\Gamma_{[t_a,t_b]}
=\{(u(t),v(t)):t_a\le t\le t_b\},
\qquad
[t_a,t_b]\subseteq\mathbb I_{\mathrm{cam,valid}}.
}
\tag{F.47}
$$

只是由时序派生的集合；它丢失访问顺序、速度、停留时间和相位信息，不能代替完整时序预测。

正交水平投影是另一个明确观测算子，例如

$$
\boldsymbol p_{\mathrm{ortho}}
=(\boldsymbol e_1,\boldsymbol e_2),
\qquad
|\boldsymbol e_1|=|\boldsymbol e_2|=1,
\qquad
\boldsymbol e_1\cdot\boldsymbol e_2=0,
\qquad
\boldsymbol e_a\cdot\boldsymbol e_z=0
\quad(a=1,2).
$$

这两个有限实向量是该观测算子的冻结参数，不从后续轨迹反推。定义

$$
\mathcal O_{\mathrm{pos,ortho}}
[\boldsymbol r_{\mathrm{obs}};
\boldsymbol p_{\mathrm{ortho}}]
=
(\boldsymbol r_{\mathrm{obs}}\cdot\boldsymbol e_1,
\boldsymbol r_{\mathrm{obs}}\cdot\boldsymbol e_2).
$$

主模型上的复合形式为

$$
\mathcal O_{F,\mathrm{ortho}}[\boldsymbol X]
=
\mathcal O_{\mathrm{pos,ortho}}
[\boldsymbol r_m(\boldsymbol X);
\boldsymbol p_{\mathrm{ortho}}].
$$

官方题面没有规定必须使用哪一种记录方式。

### 8.5 输入不确定性与预测集合

若参数、初态、外部输入或相机参数不是精确值，应在预测前冻结联合允许集合或联合分布

$$
\mathfrak U
\subseteq
\{(\boldsymbol\Theta_F,\boldsymbol X_0,
\boldsymbol U_F,\mathcal G_{\mathrm{exit}},
\boldsymbol p_{\mathrm{obs}},t_0^{\mathrm{obs}})\}.
$$

\(\mathfrak U\) 的每个成员必须满足
\(\mathsf{Valid}_F\) 和相应观测算子的静态合法谓词；
不合法候选应进入无效输入统计，不能混入物理预测集合。

相应理想预测集合定义为

$$
\boxed{
\begin{aligned}
\mathfrak P_Y(t^{\mathrm{rec}})=
\big\{&
\mathcal O[
\mathscr S_{\,t_0^{\mathrm{obs}}+t^{\mathrm{rec}}}^{F}
(\Theta,X_0,U,\mathcal G);
p_{\mathrm{obs}}]:
\\[-1mm]
&(\Theta,X_0,U,\mathcal G,p_{\mathrm{obs}},
t_0^{\mathrm{obs}})
\in\mathfrak U,\\[-1mm]
&t^{\mathrm{rec}}\in\mathbb R\text{ 为有限值},\\[-1mm]
&t_0^{\mathrm{obs}}+t^{\mathrm{rec}}
\in\mathbb I_{\mathcal O,\mathrm{valid}}
(\Theta,X_0,U,\mathcal G,p_{\mathrm{obs}})
\big\}.
\end{aligned}
}
\tag{F.48}
$$

式 (F.48) 在记录时标 \(t^{\mathrm{rec}}\) 上定义预测，并对每个不确定性成员显式使用自己的观测时间零点。它只收集相应模型时刻尚未退出且观测算子有定义的集合成员；退出状态和观测无效原因必须另外保留，不能从不确定性结果中删去。如何计算该集合属于数值计算理论。参数相关性必须保留，不能把强相关量各自独立取极值后伪装成联合不确定性。

---

## 9. 解析降阶模型 `FWD-TORUS-1.0`

### 9.1 独立输入合同

该模型从 \(t=0\) 起固定采用：

- 两个固定、等高支点；
- 两条独立定长上支 \(s_A,s_B\)；
- 定长下支 \(\ell\)；
- 无质量绳、无质量连接结点、点质量摆球；
- 无阻尼、无外力、无空气修正；
- 三支严格正张力。

状态和输入为

$$
\boxed{
\boldsymbol X_{\mathrm{tor}}
=(\varphi,\theta,\dot\varphi,\dot\theta),
}
\tag{T.1}
$$

其中 \((\varphi,\theta)\in\mathbb T^2\)，即两个角坐标按
\(2\pi\) 等同；角速度属于 \(\mathbb R^2\)。

$$
\boxed{
\mathcal I_{\mathrm{tor}}
=
(\texttt{FWD-TORUS-1.0},
A,B,\boldsymbol e_z,g,m,s_A,s_B,\ell,
\boldsymbol X_{\mathrm{tor},0},T).
}
\tag{T.2}
$$

要求

$$
d=|B-A|>0,
\qquad
(B-A)\cdot\boldsymbol e_z=0,
$$

$$
\boxed{
|s_A-s_B|<d<s_A+s_B,
\qquad
s_A,s_B,\ell,m,g,T>0,
\qquad |\boldsymbol e_z|=1.
}
\tag{T.3}
$$

此外要求 \(A,B,\boldsymbol e_z\) 的全部分量、
\(\boldsymbol X_{\mathrm{tor},0}\) 的全部实数代表元和所有标量输入均为有限实数。

### 9.2 上部几何

取

$$
O=\frac{A+B}{2},
\qquad
\boldsymbol e_x=\frac{B-A}{d},
\qquad
\boldsymbol e_y=\boldsymbol e_z\times\boldsymbol e_x.
$$

定义交圆中心相对 \(O\) 的带符号轴向偏移

$$
\boxed{
x_C=\frac{s_A^2-s_B^2}{2d},
}
\tag{T.4}
$$

以及

$$
a_A=x_C+\frac d2,
\qquad
a_B=\frac d2-x_C,
\qquad
a_A+a_B=d.
\tag{T.5}
$$

\(a_A,a_B\) 在一般相交球几何中是带符号量。本文研究的悬垂正张力工作带额外要求

$$
\boxed{a_A>0,\qquad a_B>0.}
\tag{T.6}
$$

交圆半径为

$$
\boxed{
h=\sqrt{s_A^2-a_A^2}
=\sqrt{s_B^2-a_B^2}>0.
}
\tag{T.7}
$$

### 9.3 无质量结点的共面约束

令

$$
\boldsymbol u_A=\frac{A-J}{s_A},
\qquad
\boldsymbol u_B=\frac{B-J}{s_B},
\qquad
\boldsymbol n=\frac{\boldsymbol r_m-J}{\ell}.
$$

无质量连接结点的三力平衡为

$$
\boxed{
T_A\boldsymbol u_A+T_B\boldsymbol u_B+T_\ell\boldsymbol n=0.
}
\tag{T.8}
$$

严格三角不等式给出

$$
|(A-J)\times(B-J)|=dh>0.
$$

当 \(T_\ell>0\) 时，以 \((A-J)\times(B-J)\) 点乘式 (T.8)，得到 \(A,B,J,\boldsymbol r_m\) 瞬时共面。

### 9.4 环面参数化

定义

$$
\boldsymbol e_r(\theta)
=\sin\theta\,\boldsymbol e_y
+\cos\theta\,\boldsymbol e_z,
$$

$$
\boldsymbol e_\theta(\theta)
=\cos\theta\,\boldsymbol e_y
-\sin\theta\,\boldsymbol e_z.
$$

连接结点和下支方向为

$$
J=O+x_C\boldsymbol e_x+h\boldsymbol e_r(\theta),
$$

$$
\boldsymbol n
=\sin\varphi\,\boldsymbol e_x
+\cos\varphi\,\boldsymbol e_r(\theta).
$$

令

$$
R(\varphi)=h+\ell\cos\varphi.
$$

摆球位置为

$$
\boxed{
\boldsymbol r_m
=O+(x_C+\ell\sin\varphi)\boldsymbol e_x
+R(\varphi)\boldsymbol e_r(\theta).
}
\tag{T.9}
$$

物理工作带要求 \(R>0\)。线元为

$$
\boxed{ds^2=\ell^2d\varphi^2+R^2d\theta^2.}
\tag{T.10}
$$

令

$$
x=(\boldsymbol r_m-O)\cdot\boldsymbol e_x,
$$

$$
r_\perp=
\sqrt{
[(\boldsymbol r_m-O)\cdot\boldsymbol e_y]^2
+[(\boldsymbol r_m-O)\cdot\boldsymbol e_z]^2
},
$$

$$
Q_T=(x-x_C)^2+r_\perp^2+h^2-\ell^2.
$$

物理环面等价于

$$
\boxed{
(x-x_C)^2+(r_\perp-h)^2=\ell^2,
\qquad
Q_T=2hr_\perp.
}
\tag{T.11}
$$

若使用平方多项式形式，必须保留伪分支排除条件：

$$
\boxed{
Q_T^2=4h^2r_\perp^2,
\qquad
Q_T\ge0.
}
\tag{T.12}
$$

### 9.5 拉格朗日量与精确运动方程

动能与势能取

$$
T_{\mathrm{tor}}
=\frac m2(\ell^2\dot\varphi^2+R^2\dot\theta^2),
\qquad
U_{\mathrm{tor}}=-mgR\cos\theta.
$$

Euler–Lagrange 方程为

$$
\boxed{
\ell\ddot\varphi
+R\sin\varphi\,\dot\theta^2
+g\sin\varphi\cos\theta=0,
}
\tag{T.13}
$$

$$
\boxed{
R\ddot\theta
-2\ell\sin\varphi\,\dot\varphi\dot\theta
+g\sin\theta=0.
}
\tag{T.14}
$$

第二式亦可写为

$$
R\ddot\theta+2\dot R\dot\theta+g\sin\theta=0.
$$

以最低点为零势能，机械能为

$$
\boxed{
E_{\mathrm{tor}}
=\frac m2(\ell^2\dot\varphi^2+R^2\dot\theta^2)
+mg[(h+\ell)-R\cos\theta],
\qquad
\dot E_{\mathrm{tor}}=0.
}
\tag{T.15}
$$

### 9.6 三支张力与有效域

下支张力为

$$
\boxed{
T_\ell=m\left[
\ell\dot\varphi^2
+R\cos\varphi\,\dot\theta^2
+g\cos\varphi\cos\theta
\right].
}
\tag{T.16}
$$

上支张力为

$$
\boxed{
T_A=\frac{s_AT_\ell}{d}
\left(
\sin\varphi+\frac{a_B}{h}\cos\varphi
\right),
}
\tag{T.17}
$$

$$
\boxed{
T_B=\frac{s_BT_\ell}{d}
\left(
\frac{a_A}{h}\cos\varphi-\sin\varphi
\right).
}
\tag{T.18}
$$

悬垂平衡 \((\varphi,\theta,\dot\varphi,\dot\theta)=(0,0,0,0)\) 的张力为

$$
T_{\ell0}=mg,
\qquad
T_{A0}=\frac{mgs_Aa_B}{dh},
\qquad
T_{B0}=\frac{mgs_Ba_A}{dh}.
$$

初态必须满足 \(R>0\) 和三支张力严格为正。定义首次退出时刻

$$
\boxed{
\tau_{\mathrm{tor}}
=\inf\left\{
t>0:
R(\varphi(t))\le0
\ \text{或}\
\min(T_A,T_B,T_\ell)\le0
\right\}.
}
\tag{T.19}
$$

规定空集的下确界为 \(+\infty\)，并令

$$
\widehat\tau_{\mathrm{tor}}=\min(T,\tau_{\mathrm{tor}}),
$$

$$
\mathbb I_{\mathrm{tor,ret}}=
\begin{cases}
[0,T],&T<\tau_{\mathrm{tor}},\\
[0,\tau_{\mathrm{tor}}),&\tau_{\mathrm{tor}}\le T.
\end{cases}
$$

冻结的派生输出为

$$
\boldsymbol D_{\mathrm{tor}}
=
(J,\boldsymbol r_m,T_A,T_B,T_\ell,E_{\mathrm{tor}}).
$$

正式结果元组为

$$
\boxed{
\mathcal R_{\mathrm{tor}}
=
\left(
\mathsf S_{\mathrm{tor}},
\widehat\tau_{\mathrm{tor}},
\boldsymbol X_{\mathrm{tor}}|_{\mathbb I_{\mathrm{tor,ret}}},
\boldsymbol D_{\mathrm{tor}}|_{\mathbb I_{\mathrm{tor,ret}}},
\mathcal E_{\mathrm{tor}}
\right).
}
$$

定义穷尽式环面输入合法谓词

$$
\boxed{
\begin{aligned}
\mathsf{Valid}_{\mathrm{tor}}(\mathcal I_{\mathrm{tor}})
\Longleftrightarrow{}&
\big[\text{模型 ID、输入类型和全部有限性条件成立}\big]\\
&\land\big[d=|B-A|>0,\ 
(B-A)\cdot\boldsymbol e_z=0,\ |\boldsymbol e_z|=1\big]\\
&\land\big[\text{式 (T.3) 与式 (T.6) 成立}\big]\\
&\land\big[\boldsymbol X_{\mathrm{tor},0}
\in\mathbb T^2\times\mathbb R^2\big]\\
&\land\big[R(\varphi_0)>0,\ 
\min(T_A(0),T_B(0),T_\ell(0))>0\big].
\end{aligned}
}
$$

若且唯若
\(\neg\mathsf{Valid}_{\mathrm{tor}}(\mathcal I_{\mathrm{tor}})\)，则

$$
\mathcal R_{\mathrm{tor,invalid}}
=
\left(
\{\texttt{INVALID_INPUT}\},0,
\varnothing,\varnothing,
\mathcal E_{\mathrm{tor,input}}
\right),
\qquad
\mathbb I_{\mathrm{tor,ret}}=\varnothing,
$$

其中 \(\mathcal E_{\mathrm{tor,input}}\) 列出全部失败谓词，不做静默投影。
若 \(T<\tau_{\mathrm{tor}}\)，则
\(\mathsf S_{\mathrm{tor}}=\{\texttt{COMPLETED}\}\)
且 \(\mathcal E_{\mathrm{tor}}=\varnothing\)；
若 \(\tau_{\mathrm{tor}}\le T\)，则
\(\mathsf S_{\mathrm{tor}}=\{\texttt{OUT_OF_SCOPE}\}\)，
并在 \(\mathcal E_{\mathrm{tor}}\) 中报告全部同刻为零的张力或几何退化条件。
环面模型的实验观测由式 (T.9) 给出的 \(\boldsymbol r_m\)
与第 8 节的观测算子组合得到。其正式观测输入和结果不是主模型对象的别名，而定义为

$$
\mathcal I_{\mathrm{tor,obs}}
=
(\mathcal I_{\mathrm{tor}},\mathcal O_{\mathrm{pos}},
\boldsymbol p_{\mathrm{obs}},
\{t_k^{\mathrm{rec}}\},t_0^{\mathrm{obs}}),
$$

$$
\mathcal K_{\mathrm{tor,ret}}
=
\left\{
k:
t_0^{\mathrm{obs}}+t_k^{\mathrm{rec}}
\in\mathbb I_{\mathrm{tor,ret}}
\right\}.
$$

令 \(\mathcal K_{\mathrm{tor,valid}}\) 再满足第 8 节对应观测算子的定义域条件，则

$$
\mathcal O_{\mathrm{tor}}
[\boldsymbol X_{\mathrm{tor}};\boldsymbol p_{\mathrm{obs}}]
:=
\mathcal O_{\mathrm{pos}}
[\boldsymbol r_m(\boldsymbol X_{\mathrm{tor}});
\boldsymbol p_{\mathrm{obs}}].
$$

$$
\boxed{
\mathcal R_{\mathrm{tor}}^{\mathrm{obs}}
=
\left(
\mathcal R_{\mathrm{tor}},
\mathsf S_{\mathrm{obs}},
\left\{
\mathcal O_{\mathrm{tor}}[
\boldsymbol X_{\mathrm{tor}}
(t_0^{\mathrm{obs}}+t_k^{\mathrm{rec}});
\boldsymbol p_{\mathrm{obs}}
]
\right\}_{k\in\mathcal K_{\mathrm{tor,valid}}},
\mathcal E_{\mathrm{obs}}
\right).
}
$$

这里第 8 节所有 \(\mathcal I_F,\mathcal R_F^{\mathrm{phys}},
\mathbb I_{\mathrm{ret}},\mathcal K_{\mathrm{ret}}\)
分别替换为
\(\mathcal I_{\mathrm{tor}},\mathcal R_{\mathrm{tor}},
\mathbb I_{\mathrm{tor,ret}},\mathcal K_{\mathrm{tor,ret}}\)；
相机合法域、无效观测输入和逐样本失败规则保持不变。
若某个观测算子还需要柔索场等环面状态不含有的量，则它与
`FWD-TORUS-1.0` 类型不兼容，必须返回
`INVALID_OBSERVATION_INPUT`，不得临时补状态。

特别地，\(T_\ell=0\) 时式 (T.17)–(T.18) 同时给出 \(T_A=T_B=0\)。无质量结点随后没有惯性方程选择其运动，因此本模型必须终止，不能临时拼接到有限质量冲量模型。

### 9.7 环面坐标反演

在 \(R>0\) 且物理分支条件成立时，

$$
\boxed{
\varphi=
\operatorname{atan2}(x-x_C,r_\perp-h),
\qquad
\theta=
\operatorname{atan2}
\left(
(\boldsymbol r_m-O)\cdot\boldsymbol e_y,
(\boldsymbol r_m-O)\cdot\boldsymbol e_z
\right).
}
\tag{T.20}
$$

广义速度为

$$
\boxed{
\dot\varphi
=\frac{
\dot{\boldsymbol r}_m\cdot
\partial_\varphi\boldsymbol r_m
}{\ell^2},
\qquad
\dot\theta
=\frac{
\dot{\boldsymbol r}_m\cdot
\partial_\theta\boldsymbol r_m
}{R^2}.
}
\tag{T.21}
$$

`FWD-TORUS-1.0` 到此为止。主频、频率比、有限振幅频移、可公度闭合、共振和稳定性不属于本前向方程合同，将在结构性理论阶段由理论与模拟共同研究。

---

## 10. 向后三个交付物导出的严格接口

### 10.1 `FWD_TO_SOLVER`

前向数值计算理论只能从本文取得：

1. 规范参数、状态、单位和完整输入；
2. 强式 (F.16)–(F.20)；
3. 弱式 (F.22)；
4. 本构 (F.10)–(F.15)；
5. 能量与功率恒等式 (F.24)–(F.33)；
6. 输入拒绝和退出谓词 (F.34)–(F.36)；
7. 观测映射 (F.41)–(F.48)；
8. 环面方程与张力 (T.13)–(T.19)，仅作为独立解析分支和一致性基准。

本文没有规定：

- 空间网格、节点或形函数；
- 一致或集中质量矩阵；
- 时间积分方法；
- 步长、容差、非线性求解器；
- 自适应、事件定位和误差控制；
- 收敛阶及可信度判定。

这些必须写入独立的“前向预测理论的数值计算理论” Markdown。不得反过来改写本文的物理本构以迁就某个求解器。

### 10.2 `FWD_TO_HF`

高保真后端与 `FWD-CABLE-1.0` 只共享：

- 装置几何、材料原始输入与 SI 单位；
- 支点、初态和外部环境；
- 观测定义、采样时基与输出 schema；
- 比较时间窗和有效域标志。

高保真后端必须从更局部、更少解析约化的物理规律建立，例如包含局部转动的杆/柔索、有限连接件、有限尺寸摆球和明确接触规律。仅把式 (F.22) 划分得更细仍然只是 `Solve(FWD-CABLE-1.0)`，不能同时作为独立高保真证据。

本文不提前写高保真控制方程，也不把未闭合的 Cosserat、接触或刚体片段伪装成已完成分支。

### 10.3 `FWD_TO_STRUCTURE`

结构性研究只从前述计算阶段取得原始量：

$$
\boxed{
\boldsymbol X(t),\quad
\boldsymbol D_F(t),\quad
\overline{\boldsymbol Y}(t),\quad
\mathsf S,\tau,\mathcal E_\tau.
}
\tag{F.49}
$$

频率提取、模式分类、相位、旋转数、闭合指标、参数依赖、共振、稳定性、分岔和混沌不在本文中定义为结论。结构性理论必须在两个计算后端和验证结果完成后重新研究。

---

## 11. 参数来源、冻结与可证伪性合同

### 11.1 参数身份必须唯一

每个输入字段在一次研究中必须属于且只属于一类：

| 类别 | 定义 | 验证运行中是否可调 |
|---|---|---|
| `DIRECT` | 由独立仪器或几何测量直接得到 | 否；只能输入该运行预先允许的实测值 |
| `CALIBRATED_GLOBAL` | 只用校准集估计的全局材料或阻力参数 | 否 |
| `PER_RUN_MEASURED` | 每次完整释放前可独立测量的初态或环境量 | 可输入，但不可用该运行后续轨迹回调 |
| `DERIVED` | 由已冻结字段按明确公式派生 | 否；不能同时再当拟合参数 |
| `FIXED_CONVENTION` | 模型 ID、坐标、单位、观测定义和退出规则 | 否 |

同一长度不能一会儿作为参考长度输入，一会儿作为受载轨迹拟合结果；同一阻尼不能既由独立衰减实验标定，又在每条验证轨迹上自由重调。

### 11.2 校准集与验证集

校准和验证必须按完整释放或完整几何条件划分，不能把同一视频的相邻帧随机拆成训练与验证数据。至少应保留一个未参与参数估计的完整初态或完整几何；资源允许时同时保留跨振幅、跨几何或跨材料条件。

一条完整运行被查看后，如果据此改变模型、本构、参数、初态获取、观测或数据处理，该运行自动降为新一轮校准数据；更新后的合同必须再接受新的未见完整运行。

### 11.3 打开验证数据前必须冻结

至少冻结：

1. `model_id` 与本文版本身份；
2. 方程、本构、单位与有效域；
3. 参数身份、数值和联合不确定性；
4. 初态制备方式；
5. 外部输入和时间零点；
6. 观测点、相机模型和采样时刻；
7. 输出指标及其单位；
8. `COMPLETED` 与各退出状态规则；
9. 预测区间或允许集合；
10. 预先声明的拒绝阈值。

禁止在看到验证轨迹后使用“内部波可见”“弯曲显著”“似乎需要另一阻尼”等未冻结主观判断改变本次预测合同。

### 11.4 合格预测的最小元组

每条用于实验检验的前向预测必须写成

$$
\boxed{
\Pi=
(\text{model_id},\text{输入},\text{适用域},
\text{观察窗},\text{观测算子},
\text{预测集合},\text{拒绝规则},\text{合法退出规则}).
}
\tag{F.50}
$$

本理论直接允许预测：

- 摆球、结点和三支柔索的完整时序状态；
- 局部伸长比与非负张力场；
- 受拉/松弛区域随时间的演化；
- 能量和外功率账；
- 规定相机下的像素时序；
- 观察窗内完成或提前退出的状态与时刻。

“图样看起来相似”不是拒绝规则。验收量、距离、时间对齐方式和阈值必须在验证前冻结；其数值计算方法属于后续计算或分析层。

### 11.5 误差来源不得混称

后续比较必须分别报告：

1. 前向物理模型差异；
2. 前向方程数值离散误差；
3. 高保真模型自身的物理近似与数值误差；
4. 参数和初态不确定性；
5. 观测标定与测量误差；
6. 实验中发生的模型外事件。

单条轨迹贴合不能证明这些误差已经分别受控。

---

## 12. 阶段 1 验收与诚实结论

### 12.1 合同检查

| 要求 | 本文位置 | 状态 |
|---|---|---|
| 官方题意与自选装置分开 | 0.1 | 已定义 |
| 单一规范主模型 | 0.3、1 | `FWD-CABLE-1.0` |
| 完整状态与参数 | 1.2、1.4、2.1 | 已定义一次 |
| 外部输入与退出守卫 | 1.3 | 已进入输入合同 |
| 本构关系 | 2.3–2.4 | 已冻结 |
| 控制方程 | 3.1–3.3 | 已定义 |
| 边界、初态及相容性 | 1.4、3.4–3.5 | 已定义 |
| 可检查的强初态迹空间 | 1.4 | 已定义，未与未来存在性循环引用 |
| 强解类与条件算子 | 4 | 已明确，不冒充全局定理 |
| 能量、功率和耗散 | 5 | 已定义 |
| 派生输出有限 schema | 5.5 | 已逐项冻结 |
| 初态制备与非唯一性 | 7 | 已定义 |
| 受拉、松弛与重新受拉 | 2.4 | 同一状态空间 |
| 模型外事件 | 6 | 明确终止 |
| 解析寿命与物理有效域 | 4、6.2–6.3 | 已分离，不重复报码 |
| 状态集合与无效输入结果 | 0.4、6.4 | 已定义 |
| 物理输出和观测输出 | 0.4、8 | 已分开 |
| 不确定性对象 | 8.5 | 已定义集合，不指定算法 |
| 校准—验证冻结 | 11 | 已定义 |
| 解析降阶模型 | 9 | 独立状态、方程和终止合同 |
| 数值理论隔离 | 0.2、10.1 | 已隔离 |
| 高保真隔离 | 0.2、10.2 | 已隔离 |
| 结构性理论隔离 | 0.2、10.3 | 已隔离 |

### 12.2 可以声称

> 对给定的 `FWD-CABLE-1.0` 完整输入，只要唯一 \(\mathscr C_F^{\mathrm{str}}\) 强解存在并保持在声明的物理与正则有效域内，式 (F.3)–(F.20) 原则上确定三支柔索、连接结点和点质量摆球的完整状态；仅受拉本构同时决定受拉、松弛和重新受拉。输出要么覆盖整个观察窗，要么按预先定义的原因终止，不需要运行途中临时补充物理规则。

> 对给定的 `FWD-TORUS-1.0` 完整输入，只要 \(R>0\) 且三支张力严格为正，式 (T.13)–(T.18) 规定环面状态；首次失张或几何退化时该模型终止。

### 12.3 不能声称

- 已证明退化连续柔索在最弱能量空间中的全局存在唯一性；
- 当前模型覆盖接触、滑移、断裂、弯曲、扭转、有限刚体姿态或动态支架；
- 环面模型失张后可无信息损失地切换到连续柔索状态；
- 完全非弹性冲量律已由有限刚度模型唯一导出；
- 本文已经给出任何网格、积分器、计算收敛证据或可运行程序；
- 本文已经得到频率设计、共振、稳定性、分岔或其他结构性结论；
- 一条拟合轨迹已经验证模型的前向预测能力。

### 12.4 阶段门判定

按“模型规格是否在声明适用域内形成确定的输入—状态合同”判定，本阶段为 **条件性 GO**：

- `FWD-CABLE-1.0` 对唯一强解存在且未退出有效域的输入为 GO；
- `FWD-TORUS-1.0` 对首次失张或几何退化之前的输入为 GO；
- 退化弱解唯一性、接触、断裂等模型外续接为 NO-GO，并已转换为明确终止语义。

这个结论完成的是前向理论合同，不等于数值实现、高保真验证或实验验证已经完成。下一交付物只能以本文件为物理基线，不得恢复本文件已隔离的结构性内容。

---

## 附录 A：解析与物理一致性检查合同

以下是后续实现必须满足的理论检查，不代表数值程序当前已经通过：

1. **单位一致性**：式 (F.16) 每一项均为单位参考长度力；式 (F.17)–(F.18) 每一项均为力。
2. **端力符号**：上支对结点的力为 \(-N_A\boldsymbol t_A-N_B\boldsymbol t_B\)，下支对结点为 \(+N_\ell\boldsymbol t_\ell\)，对摆球为 \(-N_\ell\boldsymbol t_\ell\)。
3. **单边性**：所有状态均有 \(N_i\ge0\)；\(\lambda_i\le1\) 时不产生弹性压缩力。
4. **轴向耗散**：式 (F.27) 的被积项逐点非负。
5. **静止空气耗散**：固定支点、无外力时满足式 (F.33)。
6. **无阻尼守恒**：所有黏性和阻力系数为零、固定支点、无外力时，强解满足 \(\dot E_F=0\)。
7. **端点相容**：式 (F.19) 在整个返回区间成立，初态满足式 (F.7)。
8. **平移协变**：同时平移装置、初态、空气场和世界坐标，不改变内部伸长与张力。
9. **上支标签交换**：交换 \(A\leftrightarrow B\) 及对应支路参数，只交换相应输出标签。
10. **环面物理分支**：`FWD-TORUS-1.0` 输出满足式 (T.11) 的未平方关系和 \(Q_T\ge0\)，不能只满足平方多项式。
11. **环面能量**：首次退出前满足式 (T.15)。
12. **环面张力**：首次退出前式 (T.16)–(T.18) 严格为正，首个零张力时刻终止。
13. **环面平衡张力**：悬垂平衡恢复 \(T_{\ell0}=mg\)、\(T_{A0}=mgs_Aa_B/(dh)\)、\(T_{B0}=mgs_Ba_A/(dh)\)。
14. **退出并列性**：同刻多个守卫触发时必须全部记录，不能依赖代码中的任意检查顺序。

---

## 附录 B：主要符号

| 符号 | 含义 |
|---|---|
| \(A(t),B(t)\) | 两个规定运动上支点 |
| \(\mathcal B_s=\{A,B,\ell\}\) | 三支柔索标签 |
| \(S,L_i^0\) | 材料坐标、无载参考长度 |
| \(\mu_i,EA_i,C_{a,i},\delta_i\) | 线密度、轴向刚度、轴向黏性、张紧平滑宽度 |
| \(\boldsymbol r_i,\boldsymbol v_i\) | 柔索中心线位置与速度场 |
| \(\boldsymbol r_J,\boldsymbol v_J\) | 连接结点位置与速度 |
| \(\boldsymbol r_m,\boldsymbol v_m\) | 点质量摆球位置与速度 |
| \(\lambda_i,\boldsymbol t_i,\dot\lambda_i\) | 伸长比、单位切向、伸长率 |
| \(N_i\) | 非负轴向张力 |
| \(\mathcal A_i,\mathcal S_i\) | 受拉区、松弛区 |
| \(\boldsymbol u_a\) | 空气速度场 |
| \(E_F\) | 规范主模型机械能 |
| \(\boldsymbol D_F\) | 第 5.5 节冻结的主模型派生输出 |
| \(\mathcal X_{F,0}^{\mathrm{str}}\) | 可由输入检查的强初态迹空间 |
| \(\mathscr C_F^{\mathrm{str}}\) | 本文声明的解析强解轨迹类 |
| \(\mathcal V_F(t)\) | 与解析强解类分离的瞬时物理有效集 |
| \(\tau_{\mathrm{phys}},\tau_{\mathrm{reg}}\) | 物理和正则性退出时刻 |
| \(\mathsf S,\mathcal E_\tau\) | 状态标志集合与同刻事件集合 |
| \(\mathcal O,\boldsymbol p_{\mathrm{obs}}\) | 观测算子及其参数 |
| \(\overline{\boldsymbol Y},\boldsymbol Y^{\mathrm{meas}}\) | 理想观测与实际测量 |
| \(s_A,s_B,\ell\) | 环面模型三支固定长度 |
| \(d,x_C,a_A,a_B,h\) | 环面上部几何量 |
| \(\varphi,\theta,R\) | 环面模型两个坐标与径向函数 |
| \(T_A,T_B,T_\ell\) | 环面模型三支张力 |

---

## 参考文献与来源

1. International Young Physicists’ Tournament, “Problems for the 40th IYPT 2027,” Problem 5, “Y-shaped pendulum,” approved by the IOC on 14 July 2026. [Official webpage](https://iypt.org/iypt-2027-problems/); [official final PDF](https://iypt.org/wp-content/uploads/2026/07/IYPT-Problems-for-2027-final-edition-web.pdf).
2. James Dean, “Investigation of the Apparent Motion of the Earth Viewed from the Moon, Arising from the Moon’s Librations,” *Memoirs of the American Academy of Arts and Sciences* **3**, Part II, 241–245 (1815). [Public-domain original scan](https://archive.org/details/mobot31753002119169/page/n248/mode/2up).
3. Nathaniel Bowditch, “On the Motion of a Pendulum Suspended from Two Points,” *Memoirs of the American Academy of Arts and Sciences* **3**, Part II, 413–436 (1815). [Public-domain original scan](https://archive.org/details/mobot31753002119169/page/n420/mode/2up).
4. A. D. Crowell, “Motion of the Earth as Viewed from the Moon and the Y-Suspended Pendulum,” *American Journal of Physics* **49**(5), 452–454 (1981). [DOI: 10.1119/1.12477](https://doi.org/10.1119/1.12477).
5. Robert J. Whitaker, “A Note on the Blackburn Pendulum,” *American Journal of Physics* **59**(4), 330–333 (1991). [DOI: 10.1119/1.16543](https://doi.org/10.1119/1.16543).
6. Jules Antoine Lissajous, “Mémoire sur l’étude optique des mouvements vibratoires,” *Annales de chimie et de physique*, 3rd series, **51**, 147–231 (1857). [Gallica original scan](https://gallica.bnf.fr/ark:/12148/bpt6k34792z/f146.item).
7. T. Lee, M. Leok and N. H. McClamroch, “Computational Dynamics of a 3D Elastic String Pendulum Attached to a Rigid Body and an Inertially Fixed Reel Mechanism,” *Nonlinear Dynamics* **64**, 97–115 (2011). [DOI: 10.1007/s11071-010-9849-5](https://doi.org/10.1007/s11071-010-9849-5).
8. J. A. Hanna and C. D. Santangelo, “Slack Dynamics on an Unfurling String,” *Physical Review Letters* **109**, 134301 (2012). [DOI: 10.1103/PhysRevLett.109.134301](https://doi.org/10.1103/PhysRevLett.109.134301).

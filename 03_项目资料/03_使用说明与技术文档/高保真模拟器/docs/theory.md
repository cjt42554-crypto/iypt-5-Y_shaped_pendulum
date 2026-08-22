# 当前规范物理模型摘要

本包的阶段 3 规范模型是 `HF-DISCRETE-ROD-RIGID-BOB-1.0`。完整推导见仓库上一级的[第一性原理高保真模拟理论与程序说明](../../IYPT_2027_Y_Pendulum_第一性原理高保真模拟理论与程序说明.md)。

旧 `full`/H1 轴向 cable/truss 路径只为兼容和回归保留，不再称为独立高保真模型。

## 独立状态

每条材料支路使用有限质量材料珠和局部连接。完整状态包含全部材料珠与有限质量结点的位置/速度，以及球形刚体摆球的质心、标量在前的四元数和世界角速度。下支终点连接到随姿态运动的偏心材料点，而不是摆球质心。

## 局部轴向力

对局部连接 \(j\)，双边 Kelvin–Voigt 试算力及单边投影为

\[
F_j^{\rm B}=k_j\delta_j+c_j\dot\delta_j,
\qquad
F_j^{\rm U}=
\begin{cases}
F_j^{\rm B}, & \delta_j>0,\ F_j^{\rm B}>0,\\
0, & \text{其他},
\end{cases}
\]

\[
k_j=\frac{EA}{\ell_j^0},
\qquad
c_j=\frac{\eta A}{\ell_j^0}.
\]

被动凸组合及非负张力定义为

\[
F_j=(1-\alpha)F_j^{\rm U}+\alpha F_j^{\rm B},
\qquad
T_j=\max(F_j,0),
\qquad
0\le\alpha\le1.
\]

\(F_j\) 是动力学使用的有符号轴力，\(T_j\) 是事件与图像使用的非负张力。正式 HF 目标取 \(\alpha=1\)，即允许有限压缩力的离散杆；\(\alpha\to0\) 只属于明确标记的受控极限。程序分别保存 `signed_axial_force` 与 `tension`。

## 三点中心线弯曲

对相邻两段切向 \((\boldsymbol t_-,\boldsymbol t_+)\)，采用

\[
U_b=
\frac12\frac{EI}{\bar\ell}
\left\lVert\boldsymbol t_+-\boldsymbol t_-\right\rVert^2,
\qquad
EI=E\frac{\pi d^4}{64}.
\]

力由 \(-\partial U_b/\partial\boldsymbol x\) 解析计算。模型保留中心线弯曲，但没有材料 director 和扭转，不能冒充完整 Cosserat/DER。

## 有限刚体

球形摆球惯量为

\[
I_b=\kappa_I m_bR_b^2.
\]

偏心连接臂 \(\boldsymbol a=R(q)\boldsymbol a_b\)，连接力矩与角速度方程为

\[
\boldsymbol\tau=\boldsymbol a\times\boldsymbol F_C,
\qquad
I_b\dot{\boldsymbol\omega}=\boldsymbol\tau.
\]

四元数满足世界角速度下的 Hamilton 运动学，并对范数漂移作显式诊断。

## 能量与有效域

输出包含材料珠/摆球平动能、摆球转动能、重力势能、轴向弹性能、弯曲能、轴向/气动耗散、气流功和支点功。验证器可从规范状态独立重算第一律残差。

摆球—杆和非相邻杆—杆接触只作为有效域终止守卫；当前没有接触后动力学。定位首根时返回半开有效区间并标记 `OUT_OF_SCOPE / SUCCESS_EVENT`。未独立排除接受步内相切根时，原始无根轨迹保守标为 `UNDETERMINED / SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED`。

## 初态

正式共享目标采用 `held_endpoint_equilibrium_release`：固定用户给定的 \(J\)、摆球质心和连接姿态，仅优化内部材料珠；多种子候选必须同时通过自由珠力残差和自由坐标势能 Hessian 稳定性检查。端点弦长小于材料长度时，`geometric_direct_release` 失败关闭，不吞掉多余弧长。

## 独立性

HF 专属物理由非零弯曲、有限偏心刚体和排除几何构成。受控极限同步缩小这些 HF 专属作用，同时保持公共质量、重力、轴向材料、初态和数值合同不变；它检验新增物理是否可分离，但不把极限冒充冻结前向模型。


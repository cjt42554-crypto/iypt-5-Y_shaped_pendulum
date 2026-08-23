# 已退休的旧理论快照（不得作为当前物理基线）

> 当前前向理论位于 `../../理论/IYPT_2027_Y_Pendulum.md`，冻结 SHA-256 为 `7eaf18e30087438507aef73c481b49e5b1427a146d79c0fd2b35ca10dc02cdb2`。本文件仅为旧 Ritz 原型的历史依赖，未按当前层级边界和模型合同验收。

# IYPT 2027 Problem 5：Y-shaped Pendulum 的统一闭合预测理论

> **目标**：建立一套物理自洽、可计算、可证伪、可逐级升级且数学闭合的 Y-Pendulum 理论。除明确装置拓扑、有限振幅基准、单边张力与非理想量级之外，本文最终给出一个固定低阶的 Ritz 柔索—结点—摆球母方程，使完整参数向量与完整初始状态能够唯一决定整个有限观察窗内的绳形、张力、摆球轨迹、松弛与重新受拉过程。
>
> **统一记号**：本文用 $\varphi$ 表示沿两上支点连线方向的快模角，用 $\theta$ 表示整个瞬时 Y 平面绕支点连线转动的慢模角；下绳长度记为 $\ell$，结点到支点轴的平衡垂距记为 $h$，慢模有效长度为 $H=h+\ell$。
>
> **版本**：3.0，2026-08-18。

---

## 摘要

Y-shaped pendulum 的核心不是“两只互不相关的单摆”，而是一个由三段只能受拉的柔索构成的三维单边约束系统。对于两个固定且等高的上支点、两条上支材料段分别定长、无质量结点、无质量不可伸长绳、点质量摆球、三根绳始终具有正张力的基准装置，无质量结点处的三力平衡强制三段绳瞬时共面，摆球严格约束在绕两支点连线生成的一张环面上。该系统可精确约化为两个自由度：

$$
\ell\ddot\varphi+R(\varphi)\sin\varphi\,\dot\theta^2
+g\sin\varphi\cos\theta=0,
$$

$$
R(\varphi)\ddot\theta
-2\ell\sin\varphi\,\dot\varphi\dot\theta
+g\sin\theta=0,
\qquad
R(\varphi)=h+\ell\cos\varphi.
$$

小振幅下，两主频为

$$
\boxed{\omega_\parallel=\sqrt{\frac g\ell}},
\qquad
\boxed{\omega_\perp=\sqrt{\frac gH}},
\qquad
\boxed{\rho\equiv\frac{\omega_\parallel}{\omega_\perp}
=\sqrt{1+\frac h\ell}}.
$$

因此零振幅目标频率比 $p:q$ 的几何设计律是

$$
\boxed{\frac h\ell=\left(\frac pq\right)^2-1}.
$$

有限振幅时，两个方向不再独立。远离强 $1:1$ 内共振区，双模平均频率为

$$
\Omega_\parallel=
\omega_\parallel\left(1-\frac{A_\varphi^2}{16}
+\frac{A_\theta^2}{8}\right)+O(A^4),
$$

$$
\Omega_\perp=
\omega_\perp\left(1-\frac{A_\theta^2}{16}
+\frac{\ell}{8H}A_\varphi^2\right)+O(A^4).
$$

三根绳的瞬时张力可由主模型显式计算。任一张力到零都不是“小修正”，而是约束拓扑改变：某一上支松弛时，系统切换为绕另一固定支点、总长为“剩余上支长加下绳长”的球摆；下绳松弛时则进入自由飞行/松弛链阶段，此时无质量结点极限欠定，必须引入结点或绳的惯性。上支换支与下绳重新拉直也必须区分：前者在理想对称边界可无速度冲量连续切换，后者通常需要冲量律或有限惯性—弹性正则化。

本文在上述主线之外建立了统一的量级判据。对目标 $p:q$ 图样，若希望经过 $N$ 个慢模周期后共振相位误差不超过 $\Phi_{\rm tol}$，任何未建模机制对频率比的相对修正必须满足

$$
\boxed{
\left|\frac{\delta\rho}{\rho}\right|
\lesssim
\epsilon_{\rm req}
\equiv
\frac{\Phi_{\rm tol}}{2\pi pN}.
}
$$

这一标准通常远严于“单周期内看不出差别”。例如 $3:2$ 图样、观测 30 个慢周期、容许相位误差 $0.20\ \mathrm{rad}$ 时，要求 $|\delta\rho/\rho|\lesssim3.54\times10^{-4}$。在这种长期闭合任务中，几度的有限振幅、亚克量级结点质量、上支总绳质量、上支轴向柔度、透视误差和阻尼导致的振幅演化都可能重要；而自由点连接下的扭转、致密小球的浮力与附加质量、远离两主频简并时的桌面尺度地球自转效应，以及远离内部共振的纵向波动力学通常可以直接忽略。

为使“给定参数和初态后预测完整运动”不再只是口号，本文进一步把每条绳用一个二次 Ritz 内部形状节点表示，解析装配绳质量的一致质量矩阵，并加入有限结点质量、单边轴向黏弹本构、必要的弯曲能、空气阻力和支架自由度。固定支点的最低全局状态为 15 个广义坐标，统一写成

$$
\dot{\boldsymbol X}=\boldsymbol F(\boldsymbol X;\boldsymbol p).
$$

有限质量、有限刚度和有限接合宽度使松弛与重新受拉由同一方程连续决定；在明确的正则性条件下，该向量场对状态局部 Lipschitz，所以完整参数与完整初态唯一决定任意有限观察窗内的运动。原来的环面二自由度方程则作为这一母模型在全张紧、高刚度、轻绳与轻结点极限下的严格慢流形约化。

---

## 0. 核心结论与建模合同

### 0.1 本文研究的装置

基准装置是三段材料绳在一个可运动材料结点 $J$ 汇合的固定结 Y 摆：

```text
A ●------------------------------● B   两个固定、等高支点
   \                            /
    \      上支 s_A, s_B       /
     \                        /
              ● J                    可运动材料结点
              |
              |  下绳 ℓ
              |
              ● m                    摆球质心
```

“固定结”表示三段绳在结点处的材料位置固定，不相互滑动；并不表示结点固定在实验室中。

若上部实际上是一根可以穿过小环或结点自由滑动的连续绳，则约束是

$$
|J-A|+|J-B|=\text{常数},
$$

而不是两个独立的定长约束。它的自由度、约束流形、张力分配和动力学都不同，本文的环面主模型不能直接套用。装置拓扑必须在建模之前确认，它不是可以通过“小修正参数”弥补的细节。

### 0.2 图样的定义

除非另行说明，“图样”指摆球**质心**在水平面上的正交投影

$$
\Gamma_{[0,T]}=\{(x(t),y(t)):0\le t\le T\}.
$$

观察窗 $T$ 必须同时给出。真实有阻尼或失谐的轨迹通常不会永久闭合；“近似闭合”必须配合相位容差或状态闭合误差定义。

灯点、笔尖、喷口和漏沙落点都不自动等于质心投影。它们可能混入摆球姿态、透视、接触力或粒子飞行时间，必须另写观测映射。

### 0.3 推荐的模型层级

| 层级 | 模型 | 使用条件 | 主要输出 |
|---:|---|---|---|
| M0 | 两个线性简谐模态 | 小振幅、全张紧、短时间 | 频率比、理想 Lissajous、初相位 |
| M1 | 精确二自由度环面 ODE | 三绳正张力、结点/绳质量可忽略 | 有限振幅、几何耦合、精确张力 |
| M2 | M1 + 经标定的阻尼与低阶修正 | 修正量小、无约束切换 | 包络、啁啾、慢漂移 |
| M3 | 有限结点质量三自由度模型 | 出现第三峰或可见结点相对运动 | 内部高频模态、非共面瞬态 |
| M4 | 环面—单支球摆混合模型 | 某一上支可能松弛 | 换支、张力阶跃、事件时刻 |
| M5 | 单边约束 DAE / 弹性绳模型 | 下绳松弛、重新拉直、冲击 | 自由飞行、捕获、张力脉冲 |
| U | 二次 Ritz 单边柔索统一闭合模型 | 需要由参数与完整初态预测全观察窗，或出现松弛/重拉直 | 绳形、局部张力、完整轨迹、自动接合与各低阶模型的统一极限 |
| M6 | 有质量柔索 PDE / Cosserat 杆 | 绳内模态、弯扭和力矩传递显著 | 分布式波、弯曲边界层、扭转 |

新增复杂度只有在以下条件同时满足时才有意义：效应大于实验不确定度；参数可独立测量或辨识；能消除有结构的残差；能改善未见条件的预测，而不是只改善一条轨迹的拟合。

### 0.4 先给出的实际结论

在一个经过合理设计的桌面 Y 摆中：

- **不能默认忽略**：有限振幅、三根张力的正性、阻尼导致的振幅演化、上支轴向柔度、结点质量、上支总绳质量、支点/相机几何误差。
- **通常可通过测量后吸收到几何量中**：静态伸长、静态支架挠度、摆球连接点到质心的固定偏置。
- **满足明确结构条件后可直接忽略**：自由点连接下的摆球转动和绳扭转；致密小球的浮力和附加质量对频率比的共同因子；远离 $1:1$ 时的 Coriolis 耦合；无冲击、远离内部模态的低频纵向波传播。
- **绝不能在环面模型中用量级分析“平滑过去”**：滑动结与固定结的拓扑差异、任一张力过零、下绳真正松弛、重新拉直事件；这些过程必须进入第 13 节统一闭合模型或等价的显式单边模型。

---

## 1. 上部几何

### 1.1 坐标系与参数

取两固定上支点为

$$
A=\left(-\frac d2,0,0\right),
\qquad
B=\left(\frac d2,0,0\right),
$$

其中 $x$ 轴沿两支点连线，$z$ 轴竖直向下，重力加速度为 $+g\mathbf e_z$。设：

- 左、右上支材料长度分别为 $s_A,s_B$；
- 下绳从结点到摆球质心的长度为 $\ell$；
- 支点间距为 $d$；
- 摆球质量为 $m$。

两上支不可伸长时，结点满足

$$
|J-A|=s_A,
\qquad
|J-B|=s_B.
$$

两个球面的交线是一条位于固定平面 $x=x_C$ 内的圆，其中

$$
\boxed{x_C=\frac{s_A^2-s_B^2}{2d}}.
$$

定义

$$
a_A=x_C+\frac d2,
\qquad
a_B=\frac d2-x_C,
\qquad a_A+a_B=d,
$$

则交圆半径为

$$
\boxed{
h=\sqrt{s_A^2-a_A^2}
=\sqrt{s_B^2-a_B^2}.
}
$$

几何存在要求

$$
|s_A-s_B|<d<s_A+s_B.
$$

若还要求悬垂平衡时两上支都以正张力承重，则需 $a_A>0,a_B>0$。

对称情形为

$$
s_A=s_B=s,
\qquad a_A=a_B=a=\frac d2,
\qquad x_C=0,
$$

$$
\boxed{h=\sqrt{s^2-a^2}=\sqrt{s^2-d^2/4}}.
$$

定义慢模总有效长度

$$
\boxed{H=h+\ell}.
$$

慢模看到的是垂直落差 $H$，不是上支斜长 $s$，也不是绳路总长 $s+\ell$。

### 1.2 上支不等长的含义

在支点等高、结点无质量、三绳全张紧时，上支不等长主要造成：

1. 环面中心沿 $x$ 方向平移到 $x_C$；
2. 通过改变 $h$ 改变慢模频率；
3. 左右上支张力和松弛阈值变得不对称。

若两套装置具有相同 $h/\ell$，它们在理想小振幅下具有相同的归一化低频动力学，但松绳边界未必相同。

---

## 2. 无质量结点为何强制共面

令从结点指向左右支点和摆球的单位向量分别为

$$
\boldsymbol u_A=\frac{A-J}{s_A},
\qquad
\boldsymbol u_B=\frac{B-J}{s_B},
\qquad
\boldsymbol n=\frac{r-J}{\ell}.
$$

三根绳张力为 $T_A,T_B,T_\ell$。结点无质量且无其他外力时，三绳全张紧要求瞬时力平衡

$$
T_A\boldsymbol u_A+T_B\boldsymbol u_B+T_\ell\boldsymbol n=0.
$$

$\boldsymbol u_A,\boldsymbol u_B$ 位于由 $A,B,J$ 决定的平面内。用该平面的法向

$$
\boldsymbol N=(A-J)\times(B-J)
$$

点乘力平衡式，得

$$
T_\ell\boldsymbol n\cdot\boldsymbol N=0.
$$

只要 $T_\ell>0$，就有

$$
\boldsymbol n\cdot\boldsymbol N=0.
$$

因此 $A,B,J$ 与摆球瞬时共面。这个平面可以绕 $AB$ 转动，并不是固定竖直平面。

共面性同时依赖：结点无质量、没有额外法向力、下绳具有正张力。有限结点质量、导轨作用、结点扭簧或任一绳松弛都会恢复第三个自由度。

---

## 3. 环面参数化与精确主模型

### 3.1 正交基与摆球位置

定义

$$
\boldsymbol e_x=(1,0,0),
$$

$$
\boldsymbol e_r(\theta)=(0,\sin\theta,\cos\theta),
\qquad
\boldsymbol e_\theta(\theta)=(0,\cos\theta,-\sin\theta).
$$

$\theta$ 描述整个瞬时 Y 平面绕支点轴的转角。结点位置为

$$
J=x_C\boldsymbol e_x+h\boldsymbol e_r(\theta).
$$

令 $\varphi$ 为下绳在瞬时 Y 平面内相对 $\boldsymbol e_r$ 的偏角，正方向沿 $+x$，则

$$
\boldsymbol n=
\sin\varphi\,\boldsymbol e_x
+\cos\varphi\,\boldsymbol e_r.
$$

定义

$$
R(\varphi)=h+\ell\cos\varphi.
$$

摆球位置为

$$
\boxed{
\boldsymbol r=
(x_C+\ell\sin\varphi)\boldsymbol e_x
+R(\varphi)\boldsymbol e_r(\theta).
}
$$

即

$$
\boxed{
\begin{aligned}
x&=x_C+\ell\sin\varphi,\\
y&=R(\varphi)\sin\theta,\\
z&=R(\varphi)\cos\theta.
\end{aligned}}
$$

### 3.2 约束曲面

在物理工作带 $R>0$ 内，消去角度得

$$
\boxed{
(x-x_C)^2+
\left(\sqrt{y^2+z^2}-h\right)^2=\ell^2.
}
$$

这是绕 $x$ 轴生成的环面，主半径为 $h$，管半径为 $\ell$。完整代数隐式式为

$$
\boxed{
\left[(x-x_C)^2+y^2+z^2+h^2-\ell^2\right]^2
=4h^2(y^2+z^2).
}
$$

当 $h<\ell$ 时，形式参数曲面包含 spindle torus 的另一分支；真实三绳正张力运动只使用悬垂平衡附近的物理可达带，不能把整个数学曲面都当作柔索可实现区域。

曲面线元为

$$
\boxed{ds^2=\ell^2d\varphi^2+R(\varphi)^2d\theta^2}.
$$

平衡点的两个主曲率半径正好是 $\ell$ 与 $H=h+\ell$，这预示了两个小振幅有效摆长。

### 3.3 动能、势能与拉格朗日量

由正交参数化，

$$
|\dot{\boldsymbol r}|^2
=\ell^2\dot\varphi^2+R^2\dot\theta^2.
$$

因此

$$
T=\frac m2\left(\ell^2\dot\varphi^2+R^2\dot\theta^2\right),
$$

$$
U=-mgR\cos\theta,
$$

$$
\boxed{
\mathcal L=
\frac m2\left(\ell^2\dot\varphi^2+R^2\dot\theta^2\right)
+mgR\cos\theta.
}
$$

### 3.4 精确非线性运动方程

Euler–Lagrange 方程给出

$$
\boxed{
\ell\ddot\varphi
+R\sin\varphi\,\dot\theta^2
+g\sin\varphi\cos\theta=0,
}
\tag{3.1}
$$

$$
\boxed{
R\ddot\theta
-2\ell\sin\varphi\,\dot\varphi\dot\theta
+g\sin\theta=0.
}
\tag{3.2}
$$

等价地，因 $\dot R=-\ell\sin\varphi\dot\varphi$，第二式可写为

$$
R\ddot\theta+2\dot R\dot\theta+g\sin\theta=0.
$$

这两式在基准假设和正张力域内是有限振幅精确方程，不是经验性的“两只非线性单摆”。耦合来自两点：$R$ 随 $\varphi$ 改变；环面曲率产生 $\dot\varphi\dot\theta$ 和 $\dot\theta^2$ 型几何惯性项。

### 3.5 能量与 Hamilton 形式

以最低点为零势能，

$$
\boxed{
E=\frac m2\left(\ell^2\dot\varphi^2+R^2\dot\theta^2\right)
+mg\left[H-R\cos\theta\right].
}
$$

无耗散且未松绳时 $E$ 守恒。共轭动量为

$$
p_\varphi=m\ell^2\dot\varphi,
\qquad
p_\theta=mR^2\dot\theta,
$$

$$
\mathcal H=
\frac{p_\varphi^2}{2m\ell^2}
+\frac{p_\theta^2}{2mR^2}
+mg[H-R\cos\theta].
$$

保守数值解必须同时检查能量和张力。能量守恒并不能排除“让绳承受负张力”的伪解。

### 3.6 无量纲化

令

$$
\eta=\frac h\ell,
\qquad
\tau=t\sqrt{\frac g\ell},
$$

撇号表示对 $\tau$ 求导，则

$$
\boxed{
\varphi''+(\eta+\cos\varphi)\sin\varphi\,\theta'^2
+\sin\varphi\cos\theta=0,
}
$$

$$
\boxed{
(\eta+\cos\varphi)\theta''
-2\sin\varphi\,\varphi'\theta'
+\sin\theta=0.
}
$$

在预先限定的三绳正张力区间内，无量纲向量场除初值外只依赖 $\eta=h/\ell$。质量只缩放张力，$g$ 与 $\ell$ 只设定时间和空间尺度。若要预测松弛，还必须额外保留 $a_A/h,a_B/h$。

### 3.7 两个精确不变模态

若

$$
\theta(0)=\dot\theta(0)=0,
$$

则始终 $\theta=0$，且

$$
\boxed{\ell\ddot\varphi+g\sin\varphi=0}.
$$

这是长度 $\ell$ 的普通单摆。

若

$$
\varphi(0)=\dot\varphi(0)=0,
$$

则始终 $\varphi=0$，且

$$
\boxed{H\ddot\theta+g\sin\theta=0}.
$$

这是长度 $H$ 的普通单摆。两条关系是检验任意数值程序和修正模型的首要单元测试。

---

## 4. 小振幅 Lissajous 理论

### 4.1 线性化与两个主频

在 $|\varphi|,|\theta|\ll1$ 时，

$$
\ddot\varphi+\frac g\ell\varphi=0,
\qquad
\ddot\theta+\frac gH\theta=0.
$$

定义水平主轴位移

$$
X=x-x_C\simeq\ell\varphi,
\qquad
Y=y\simeq H\theta.
$$

于是

$$
\boxed{
X(t)=A_X\cos(\omega_\parallel t+\delta_X),
\qquad
Y(t)=A_Y\cos(\omega_\perp t+\delta_Y),
}
$$

其中

$$
\boxed{
\omega_\parallel=\sqrt{\frac g\ell},
\qquad
\omega_\perp=\sqrt{\frac gH}.
}
$$

频率比为

$$
\boxed{
\rho=\frac{\omega_\parallel}{\omega_\perp}
=\sqrt{\frac H\ell}
=\sqrt{1+\frac h\ell}>1.
}
$$

最强的零参数检验是

$$
\boxed{\rho^2=1+h/\ell}.
$$

理想模型中频率与摆球质量无关；改变上部三角形但保持 $h/\ell$ 不变，归一化低频轨迹应塌缩。

### 4.2 振幅和初相

若任一模态 $Q=X,Y$ 在 $t=0$ 有 $Q_0,V_0$，则

$$
A_Q=\sqrt{Q_0^2+\left(\frac{V_0}{\omega_Q}\right)^2},
$$

$$
\delta_Q=\operatorname{atan2}\!\left(-\frac{V_0}{\omega_Q},Q_0\right).
$$

二维静止释放使两个模态都从转折点开始，只覆盖有限的相位族。任意抛放必须同时描述初位置和初速度。

### 4.3 闭合条件与共振相位

若

$$
\rho=\frac pq,
\qquad \gcd(p,q)=1,
$$

则可写

$$
\omega_\parallel=p\Omega,
\qquad
\omega_\perp=q\Omega.
$$

完整状态的共同周期为

$$
\boxed{
T_{\rm close}=\frac{2\pi}{\Omega}
=\frac{2\pi p}{\omega_\parallel}
=\frac{2\pi q}{\omega_\perp}.
}
$$

特殊相位和图形对称性可能使最短几何重复时间成为其约数，但上式是可靠的相空间重复时间。

固定 $p:q$ 后，不能通过平移时间消去的相位组合为

$$
\boxed{
\Psi_{pq}^{(0)}=q\delta_X-p\delta_Y\pmod{2\pi}.
}
$$

同一频率比、不同振幅比 $A_X/A_Y$ 和 $\Psi_{pq}^{(0)}$，可得到不同的长宽比、交点结构和朝向。

### 4.4 零振幅几何设计律

目标

$$
\omega_\parallel:\omega_\perp=p:q,
\qquad p>q,
$$

要求

$$
\boxed{
\frac h\ell=\left(\frac pq\right)^2-1.
}
$$

常见比例如下：

| $p:q$ | $h/\ell$ | $H/\ell$ |
|---:|---:|---:|
| $4:3$ | $7/9$ | $16/9$ |
| $3:2$ | $5/4$ | $9/4$ |
| $5:3$ | $16/9$ | $25/9$ |
| $2:1$ | $3$ | $4$ |

对称上支中，给定 $a=d/2$ 后

$$
s=\sqrt{h^2+a^2}.
$$

几何设计仍必须同时检查平衡张力和上支松弛角。仅把 $h/\ell$ 调到整数比并不能保证真实轨迹长期闭合。

### 4.5 失谐与慢漂移

定义

$$
\boxed{
\Delta_{pq}=q\Omega_\parallel-p\Omega_\perp.
}
$$

共振相位满足

$$
\Psi_{pq}(t)=\Psi_{pq}(0)+\Delta_{pq}t.
$$

图样相对目标整数比完整漂移一周的尺度为

$$
\boxed{
T_{\rm drift}=\frac{2\pi}{|q\Omega_\parallel-p\Omega_\perp|}.
}
$$

经过 $N$ 个慢模周期 $T_\perp=2\pi/\Omega_\perp$ 后，若实际频率比为 $\rho+\delta\rho$，相对名义 $p:q$ 的相位误差近似为

$$
\boxed{
|\Delta\Psi_N|
\simeq2\pi Nq|\delta\rho|
\simeq2\pi Np\left|\frac{\delta\rho}{\rho}\right|.
}
$$

这条式子是后文量级分析的核心：微小频率误差会按观测周期数线性累积。

### 4.6 几何灵敏度与反演

由

$$
\rho=\sqrt{\frac{H}{\ell}}
$$

得

$$
\boxed{
\frac{\delta\rho}{\rho}
=\frac{\delta h}{2H}
-\frac{h\,\delta\ell}{2\ell H}.
}
$$

对称上支

$$
h=\sqrt{s^2-d^2/4},
$$

$$
\delta h=\frac{s}{h}\delta s-\frac{d}{4h}\delta d.
$$

所以浅 Y 极限 $h\to0$ 同时具有几何病态和张力病态：$h$ 对 $s,d$ 的灵敏度发散，而上支平衡张力也按 $1/h$ 增大。

从测得的两主频可反演动力学有效长度

$$
\boxed{
\ell_{\rm dyn}=\frac g{\omega_\parallel^2},
\qquad
H_{\rm dyn}=\frac g{\omega_\perp^2},
\qquad
h_{\rm dyn}=H_{\rm dyn}-\ell_{\rm dyn}.
}
$$

若动力学值与静态尺量系统不符，应依次检查有限振幅、加载状态下的实际长度、上支轴向柔度、结点/绳质量、支架运动和观测投影。

---
## 5. 有限振幅、非线性频移与频谱

### 5.1 两个纯模态的精确周期

在对应的不变模态内，系统严格退化为普通单摆。若长度为 $L_i$、最大角振幅为 $A_i<\pi$，数学周期为

$$
\boxed{
T_i(A_i)=4\sqrt{\frac{L_i}{g}}
K\!\left(\sin\frac{A_i}{2}\right),
}
$$

其中 $L_i=\ell$ 或 $H$，且

$$
K(k)=\int_0^{\pi/2}\frac{du}{\sqrt{1-k^2\sin^2u}}.
$$

小振幅展开为

$$
\frac{T_i(A_i)}{T_{i0}}
=1+\frac{A_i^2}{16}
+\frac{11A_i^4}{3072}+O(A_i^6),
$$

$$
\boxed{
\frac{\omega_i(A_i)}{\omega_{i0}}
=1-\frac{A_i^2}{16}
+\frac{A_i^4}{3072}+O(A_i^6).
}
$$

但 $A_i<\pi$ 只是刚性圆周约束的数学范围，不是柔索 Y 摆的物理有效域。对从转点静止释放的纯模：

- 慢模转点处下绳张力为 $mg\cos A_\theta$，故至少要求 $A_\theta<\pi/2$；
- 快模还必须满足两上支的张力边界，见第 6 节。

### 5.2 三次运动方程

令 $\varphi,\theta=O(\varepsilon_A)$，把精确方程展开到三次：

$$
\boxed{
\begin{aligned}
\ddot\varphi+\frac g\ell\varphi
&-\frac{g}{6\ell}\varphi^3
-\frac{g}{2\ell}\varphi\theta^2
+\frac H\ell\varphi\dot\theta^2
=O(\varepsilon_A^5),
\end{aligned}}
\tag{5.1}
$$

$$
\boxed{
\begin{aligned}
\ddot\theta+\frac gH\theta
&-\frac{g}{6H}\theta^3
+\frac{g\ell}{2H^2}\varphi^2\theta
-\frac{2\ell}{H}\varphi\dot\varphi\dot\theta
=O(\varepsilon_A^5).
\end{aligned}}
\tag{5.2}
$$

第一类非线性是普通单摆软化；第二类来自环面几何，使一模态的振幅改变另一模态的平均频率。

### 5.3 双模平均频率

设

$$
\varphi\simeq A_\varphi\cos(\Omega_\parallel t+\delta_\varphi),
\qquad
\theta\simeq A_\theta\cos(\Omega_\perp t+\delta_\theta).
$$

若远离需要保留慢共振项的 $1:1$ 区域，例如满足

$$
\frac{|\omega_\parallel-\omega_\perp|}{\bar\omega}
\gg A_\varphi^2+A_\theta^2,
$$

四阶平均或正规形给出

$$
\boxed{
\Omega_\parallel=
\omega_\parallel
\left(1-\frac{A_\varphi^2}{16}
+\frac{A_\theta^2}{8}\right)
+O(\varepsilon_A^4),
}
\tag{5.3}
$$

$$
\boxed{
\Omega_\perp=
\omega_\perp
\left(1-\frac{A_\theta^2}{16}
+\frac{\ell}{8H}A_\varphi^2\right)
+O(\varepsilon_A^4).
}
\tag{5.4}
$$

因此

$$
\boxed{
\frac{\Omega_\parallel}{\Omega_\perp}
=\rho\left[
1-
\left(\frac1{16}+\frac{\ell}{8H}\right)A_\varphi^2
+\frac{3}{16}A_\theta^2
\right]+O(\varepsilon_A^4).
}
\tag{5.5}
$$

直接预测为：

1. 增大快模振幅 $A_\varphi$ 通常降低频率比；
2. 增大慢模振幅 $A_\theta$ 通常提高频率比；
3. 两模阻尼率不同时，振幅衰减会使频率比和漂移方向随时间改变；
4. 零振幅几何精确满足整数比，并不保证有限振幅图样闭合。

不能依赖两项偶然抵消来宣称非线性可忽略；释放误差会破坏这种抵消。量级筛查应比较两项绝对值之和，而不是只看某一次工况中的净值。

### 5.4 有限振幅几何预补偿

若 $h_0$ 已在零振幅满足目标 $p:q$，希望在给定小振幅下抵消式 (5.5) 的首阶失谐，可在固定 $\ell$ 时取

$$
\boxed{
\delta h\simeq
\left(\frac H8+\frac\ell4\right)A_\varphi^2
-\frac{3H}{8}A_\theta^2.
}
\tag{5.6}
$$

该式只适用于小振幅、远离强 $1:1$ 共振且三绳始终张紧的条件。较大振幅应直接积分式 (3.1)–(3.2)，扫描 $h/\ell$ 并最小化固定观察窗内的共振相位漂移。

### 5.5 频谱签名

坐标展开为

$$
x-x_C=\ell\left(\varphi-\frac{\varphi^3}{6}+\cdots\right),
$$

$$
y=H\theta-\frac H6\theta^3
-\frac\ell2\varphi^2\theta+\cdots,
$$

$$
z=H-\frac\ell2\varphi^2-\frac H2\theta^2+O(\varepsilon_A^4).
$$

仅由坐标映射就会出现：

- $x$ 中的 $3\omega_\parallel$；
- $y$ 中的 $3\omega_\perp$ 与 $2\omega_\parallel\pm\omega_\perp$；
- $z$ 中的 $2\omega_\parallel,2\omega_\perp$。

运动方程中的 $\varphi\theta^2$、$\varphi\dot\theta^2$ 等项还会驱动 $\omega_\parallel\pm2\omega_\perp$ 型模态边带，使其进一步出现在 $x(t)$ 中。看到组合峰并不能单独证明模态能量交换；它们可能只是几何非线性和受迫边带。

### 5.6 有理比不等于强内共振

理想系统分别在

$$
(\varphi,p_\varphi)\mapsto(-\varphi,-p_\varphi),
\qquad
(\theta,p_\theta)\mapsto(-\theta,-p_\theta)
$$

下对称。因此 Hamiltonian 对每个模态只含偶总次数。对 $p:q$ 内共振，首个允许共振项一般至少具有总阶数 $2(p+q)$：

- $1:1$ 可在四阶出现；
- $2:1$ 通常到六阶才出现；
- $3:2$ 通常到十阶才出现。

所以常见 $2:1$、$3:2$ Lissajous 闭合首先是运动学相位可公度，不自动意味着低阶强能量交换。要声称内共振，至少应观察可重复的反相模态能量交换、慢相位有界、随失谐变化的有限锁定区，并排除阻尼和投影边带。

---

## 6. 三根绳张力与主模型有效域

### 6.1 下绳张力

将摆球 Newton 方程沿下绳方向投影，得

$$
\boxed{
T_\ell=m\left[
\ell\dot\varphi^2
+R\cos\varphi\,\dot\theta^2
+g\cos\varphi\cos\theta
\right].
}
\tag{6.1}
$$

环面模型要求

$$
T_\ell>0.
$$

计算得到 $T_\ell<0$ 的含义不是绳产生“负张力”，而是下绳已经松弛，当前模型失效。

### 6.2 一般不对称上支张力

无质量结点力平衡给出

$$
\boxed{
T_A=\frac{s_A T_\ell}{d}
\left(
\sin\varphi+\frac{a_B}{h}\cos\varphi
\right),
}
\tag{6.2}
$$

$$
\boxed{
T_B=\frac{s_B T_\ell}{d}
\left(
\frac{a_A}{h}\cos\varphi-\sin\varphi
\right).
}
\tag{6.3}
$$

在悬垂平衡附近 $\cos\varphi>0$ 时，三绳共同绷紧的几何带为

$$
\boxed{
-\arctan\frac{a_B}{h}
<\varphi<
\arctan\frac{a_A}{h},
\qquad T_\ell>0.
}
\tag{6.4}
$$

两套装置即使具有相同 $h/\ell$ 和相同主频，也可因 $a_A,a_B$ 不同而具有不同松绳阈值。

### 6.3 对称装置

令

$$
a_A=a_B=a,
\qquad
s_A=s_B=s,
$$

并定义上支相对竖直角

$$
\alpha=\arctan\frac ah,
\qquad
\sin\alpha=\frac as,
\qquad
\cos\alpha=\frac hs.
$$

则

$$
\boxed{|\varphi|<\varphi_{\rm slack}=\alpha=\arctan(a/h)}.
$$

水平位移阈值为

$$
\boxed{|x-x_C|<x_{\rm slack}=\ell\sin\alpha=\frac{\ell a}{s}}.
$$

平衡时

$$
T_{\ell0}=mg,
\qquad
\boxed{T_{A0}=T_{B0}=\frac{mgs}{2h}}.
$$

若设计要求 $|\varphi|\le A_{\varphi,\max}$ 始终张紧，则至少需

$$
\frac ah>\tan A_{\varphi,\max}.
$$

这体现一个直接折衷：增大 $a/h$ 扩大快模允许振幅，却提高上支静张力；减小 $a/h$ 降低上支张力，却容易发生换支。$h\to0$ 的精确 $1:1$ 极限在机械上是奇异的，因为上支平衡张力按 $1/h$ 发散。

### 6.4 张力安全裕量

定义一条轨迹上的无量纲张力裕量

$$
\boxed{
\eta_T=\frac{1}{mg}
\min_{0\le t\le T}
\{T_\ell(t),T_A(t),T_B(t)\}.
}
$$

- $\eta_T<0$：所用全张紧解在物理上错误；
- $\eta_T\approx0$：事件时刻对几何误差、弹性和数值容差高度敏感，必须使用混合模型；
- $\eta_T$ 显著大于所有张力不确定度时，才可把换支从目标观察窗内排除。

“显著”应由载荷传感器精度、参数不确定度和模型残差确定，不能用固定百分比替代误差传播。

---

## 7. 松弛后的混合动力学

本节给出不可伸长、零接合宽度极限下的混合系统结构，用于理解活动约束和冲量极限。第 13 节在此基础上保留有限绳质量、有限刚度和有限接合宽度，把这些分段相位正则化为一套全局闭合方程。两者分别是理想非光滑极限和实际低阶确定性闭包，不应混为同一层级。

### 7.1 某一上支松弛：环面切换为单支球摆

若右上支松弛而左上支与下绳仍张紧，无质量结点只受两股张力。两力必须共线且反向，因此

$$
A,\,J,\,\text{摆球}
$$

三点共线。摆球成为绕左支点 $A$ 的球摆，总长度为

$$
\boxed{L_A=s_A+\ell}.
$$

左上支松弛时同理，摆球绕右支点 $B$ 运动，总长度 $L_B=s_B+\ell$。

这不是对环面方程加一个小阻尼项，而是约束曲面从环面变为以单支点为球心的球面。

### 7.2 理想上支换支不必产生速度冲量

在对称装置的松绳边界，环面与对应单支球面具有相同法向，因此两约束面相切。在严格的无质量结点、无质量刚绳极限中，可以保持：

- 摆球位置连续；
- 摆球速度连续；
- 摆球动能和总机械能连续。

通常跳变的是加速度和张力，而不是必然的速度。因此不能预先规定“每次上支重新绷紧都发生非弹性碰撞”。真实装置的结点质量、绳质量、轴向柔度、摩擦和下垂会把理想张力阶跃正则化为有限宽度脉冲，是否损能应由数据和具体模型决定。

数值上最稳妥的状态传递是直接保持笛卡尔位置 $\boldsymbol r$ 和速度 $\dot{\boldsymbol r}$ 连续，而不是原样复制两个坐标系中的角速度。

对称装置中，设单支球摆总长 $L_s=s+\ell$，经向角为 $\chi$。从环面进入单支相位时，速度连续给出

$$
\boxed{
\dot\chi^+=\frac{\ell}{L_s}\dot\varphi^-,
\qquad
\dot\theta^+=\dot\theta^-.
}
$$

无冲量切回环面时

$$
\boxed{
\dot\varphi^+=\frac{L_s}{\ell}\dot\chi^-,
\qquad
\dot\theta^+=\dot\theta^-.
}
$$

错误地原样复制 $\dot\varphi$ 会凭空改变经向动能。

### 7.3 下绳松弛：无质量结点极限终止

若 $T_\ell\to0$ 且将变负，摆球进入自由飞行或松弛链阶段。此时两上支张力也随 $T_\ell$ 趋零。没有下绳拉力后，两根不共线上支无法唯一决定一个无惯性结点的运动；纯无质量刚绳模型欠定。

要继续预测，至少需要一种明确惯性机制：

- 有限结点质量；
- 分布式绳质量；
- 其他具有惯性的结点/导向件。

轴向弹性可以与上述惯性联合使用来平滑重新接合，但**单独**给所有无质量绳加入弹性，在它们均松弛时仍不能唯一决定结点轨迹和重新接合时刻。

### 7.4 单边约束与互补条件

对每根绳定义端点距离 $d_i$、最大/自然长度 $L_i$ 和松弛间隙

$$
g_i=L_i-d_i.
$$

理想不可伸长柔索满足

$$
\boxed{
g_i\ge0,
\qquad T_i\ge0,
\qquad T_i g_i=0.
}
\tag{7.1}
$$

含义为：

- $g_i=0,T_i>0$：绳绷紧；
- $g_i>0,T_i=0$：绳松弛；
- 活跃约束算出 $T_i<0$：释放该约束；
- 松绳到达 $g_i=0$ 且端点距离继续增大：发生重新接合。

擦触情形 $g_i=0,\dot d_i=0$ 还要检查未约束预测的间隙加速度；只有自由运动将进入不可行的 $g_i<0$ 区域时才激活约束。

### 7.5 状态转换表

| 当前相位 | 事件与方向条件 | 下一相位 | 状态处理 |
|---|---|---|---|
| 三绳环面 | $T_A=0$、$T_\ell,T_B>0$，且乘子将趋负 | 绕 $B$ 的单支球摆 | 传递 $\boldsymbol r,\dot{\boldsymbol r}$ |
| 三绳环面 | $T_B=0$、$T_\ell,T_A>0$，且乘子将趋负 | 绕 $A$ 的单支球摆 | 传递 $\boldsymbol r,\dot{\boldsymbol r}$ |
| 单支球摆 | 松支到达 $g_i=0$、$\dot d_i>0$ | 捕获则回环面；反弹则仍单支 | 相切时可速度连续；否则用冲量/弹性律 |
| 任一绷紧相位 | $T_\ell=0$ 且将趋负 | 下绳松弛/自由飞行 | 启用有限结点或绳惯性模型 |
| 松弛链 | $g_\ell=0$、$\dot d_\ell>0$ | 捕获或反弹 | 联立冲量律，或由有限惯性—弹性模型决定 |

### 7.6 单边 Kelvin–Voigt 正则化

比任意指定一个恢复系数更接近真实绳的低阶模型是

$$
\boxed{
T_i=
\begin{cases}
0,&d_i<L_i,\\[1mm]
\left[k_i(d_i-L_i)+c_i\dot d_i\right]_+,&d_i\ge L_i,
\end{cases}
\qquad [u]_+=\max(u,0).
}
\tag{7.2}
$$

阻尼项只在绳已经拉直/伸长后生效，不能让松绳提前传力。接合时间尺度约为

$$
t_c\sim\sqrt{\frac{m_{\rm eff}}{k_i}}
$$

（欠阻尼/临界区）；强过阻尼时还必须解析 $m_{\rm eff}/c_i$ 与 $c_i/k_i$ 两个尺度。

---

## 8. 有限结点质量、通用 DAE 与冲量

### 8.1 有限结点质量恢复第三自由度

令结点质量为 $m_J$。结点仍受两上支约束，在半径 $h$ 的圆上运动：

$$
\boldsymbol r_J=x_C\boldsymbol e_x+h\boldsymbol e_r(\chi_J).
$$

下绳方向现在可为任意单位向量 $\boldsymbol n\in S^2$：

$$
\boldsymbol r=\boldsymbol r_J+\ell\boldsymbol n.
$$

精确拉格朗日量可写为

$$
\mathcal L=
\frac{m_J}{2}|\dot{\boldsymbol r}_J|^2
+\frac m2|\dot{\boldsymbol r}_J+\ell\dot{\boldsymbol n}|^2
+g\mathbf e_z\cdot
\left[m_J\boldsymbol r_J+m(\boldsymbol r_J+\ell\boldsymbol n)\right],
$$

并附加 $|\boldsymbol n|=1$。此时一般不再严格共面，共有三个自由度。直接把 $m_J=0$ 塞入普通三自由度质量矩阵是奇异极限；有意义的无质量正张力分支应回到环面降维模型。

### 8.2 小振幅固有频率

沿支点轴的快模仍为

$$
\omega_\parallel^2=\frac g\ell
$$

（这里仍假定上支不可伸长）。垂直方向取结点小角 $\chi_J$ 与下绳绝对角 $\beta$，质量和刚度矩阵为

$$
\boxed{
M_\perp=
\begin{pmatrix}
(m_J+m)h^2&m h\ell\\
m h\ell&m\ell^2
\end{pmatrix},
\qquad
K_\perp=
\begin{pmatrix}
(m_J+m)gh&0\\
0&mg\ell
\end{pmatrix}.
}
$$

定义

$$
\epsilon=\frac{m_J}{m_J+m},
$$

则两个横向频率满足

$$
\epsilon h\ell\,\omega^4-gH\omega^2+g^2=0,
$$

$$
\boxed{
\omega_\pm^2=
\frac{g\left[H\pm\sqrt{H^2-4\epsilon h\ell}\right]}
{2\epsilon h\ell}.
}
$$

低根的数值稳定形式为

$$
\boxed{
\omega_-^2=
\frac{2g}{H+\sqrt{H^2-4\epsilon h\ell}}.
}
$$

轻结点极限 $m_J/m\ll1$ 下，

$$
\boxed{
\omega_-^2\simeq\frac gH
\left[1+\frac{m_J}{m}\frac{h\ell}{H^2}\right],
}
\tag{8.1}
$$

$$
\omega_+^2\sim
\frac{gH}{(m_J/m)h\ell}.
$$

低频模态恢复结点与下绳近似共同转动；高频模态中结点与下绳反相，轻结点时其频率按 $m_J^{-1/2}$ 上升。额外高频峰和慢模轻微上移是结点质量的直接签名。

### 8.3 通用笛卡尔 DAE

保留

$$
q=(\boldsymbol r_J,\boldsymbol r)\in\mathbb R^6,
\qquad
\mathsf M=\operatorname{diag}(m_JI_3,mI_3).
$$

对当前活跃的不可伸长约束，定义

$$
\Phi_A=\frac12(|\boldsymbol r_J-A|^2-s_A^2),
$$

$$
\Phi_B=\frac12(|\boldsymbol r_J-B|^2-s_B^2),
$$

$$
\Phi_\ell=\frac12(|\boldsymbol r-\boldsymbol r_J|^2-\ell^2),
$$

$$
\boldsymbol\Phi(q)=0,
\qquad
\mathsf J=\frac{\partial\boldsymbol\Phi}{\partial q}.
$$

若 $m_J>0$，可解 KKT 系统

$$
\boxed{
\begin{pmatrix}
\mathsf M&\mathsf J^{\mathsf T}\\
\mathsf J&0
\end{pmatrix}
\begin{pmatrix}
\ddot q\\ \boldsymbol\lambda
\end{pmatrix}
=
\begin{pmatrix}
\boldsymbol F\\-\dot{\mathsf J}\dot q
\end{pmatrix}.
}
\tag{8.2}
$$

初值必须满足

$$
\boldsymbol\Phi(q_0)=0,
\qquad
\mathsf J(q_0)\dot q_0=0.
$$

普通 KKT 系统要求质量矩阵非奇异，不能把 $m_J=0$ 直接代入普通求解器或冲量投影。无质量极限应使用环面降维，或专门处理奇异质量矩阵的高指标 DAE 方法。

### 8.4 重新接合的联立冲量

设冲击前仍活跃的约束为 $\mathcal O$，新接触约束为 $\mathcal N$，候选活跃集

$$
\mathcal A=\mathcal O\cup\mathcal N.
$$

以归一化距离 Jacobian $\widehat{\mathsf J}_i$ 表示径向相对速度，可用

$$
\mathsf M(\boldsymbol v^+-\boldsymbol v^-)
=-\widehat{\mathsf J}_{\mathcal A}^{\mathsf T}
\boldsymbol P_{\mathcal A},
$$

$$
\widehat{\mathsf J}_{\mathcal O}\boldsymbol v^+=0,
\qquad
\widehat{\mathsf J}_{\mathcal N}\boldsymbol v^+
=-e\widehat{\mathsf J}_{\mathcal N}\boldsymbol v^-,
\qquad0\le e\le1.
$$

已有绷紧绳也必须参加动量跳跃，因为新绳冲量通常会改变结点速度。若联立解要求某个约束产生负拉力冲量，应由活动集算法释放它并重算。

还必须区分反弹与捕获：当 $e>0$ 时，新绳冲击后通常立即向松弛侧离开，不能无条件转入持续绷紧状态。只有冲击后速度条件与加速度级乘子都支持正张力时，才捕获为等式约束。多绳同时接合必须联立求解，不能按任意顺序逐根投影。

---
## 9. 非理想效应的统一低阶模型

本节不把所有因素同时塞进主方程，而是给出每种机制的独立参数、首个可观测后果和升级条件。刚度与耗散必须分开：$EA,EI,GJ$ 的实部改变平衡和频率；材料损耗、空气阻力与摩擦才使能量衰减。把弯曲或扭转刚度整体并入阻尼在物理上不等价。

### 9.1 绳质量

有质量柔绳本质上是连续体。远离绳内模态、绳保持近似直线且总绳质量远小于摆球质量时，可先用 Rayleigh 低阶修正。

#### 9.1.1 下绳质量对快模

设下绳均匀质量为 $M_\ell$。快模中结点线性阶不动，近似有

$$
I_\parallel=m\ell^2+\frac13M_\ell\ell^2,
$$

$$
C_\parallel=g\ell\left(m+\frac12M_\ell\right).
$$

因此

$$
\boxed{
\omega_\parallel^2\simeq
\frac g\ell
\frac{m+M_\ell/2}{m+M_\ell/3},
}
$$

$$
\boxed{
\frac{\delta\omega_\parallel}{\omega_\parallel}
\simeq\frac{M_\ell}{12m}
\qquad(M_\ell/m\ll1).
}
\tag{9.1}
$$

均匀摆绳的自重矩与转动惯量以不同权重增加，因此频率低阶上略微升高；“绳有质量必然使周期变长”并不普遍成立。

#### 9.1.2 慢模的整体共同转动近似

设两上支总质量为 $M_u$，下绳质量为 $M_\ell$，结点质量为 $m_J$。若低频慢模中整个 Y 结构近似共同绕支点轴转动，重力一阶矩和惯量为

$$
C_\perp=
 mH+m_Jh
+M_\ell\left(h+\frac\ell2\right)
+\frac12M_uh,
$$

$$
I_\perp=
 mH^2+m_Jh^2
+M_\ell\left(h^2+h\ell+\frac{\ell^2}{3}\right)
+\frac13M_uh^2.
$$

于是

$$
\boxed{
\omega_\perp^2\simeq g\frac{C_\perp}{I_\perp}.
}
\tag{9.2}
$$

令

$$
x=\frac\ell H,
\qquad
y=\frac hH,
\qquad x+y=1.
$$

对小质量比展开，得到

$$
\boxed{
\frac{\delta\omega_\perp}{\omega_\perp}
\simeq
\frac{m_J}{m}\frac{xy}{2}
+\frac{M_\ell}{m}\left(\frac x4-\frac{x^2}{6}\right)
+\frac{M_u}{m}\left(\frac y4-\frac{y^2}{6}\right).
}
\tag{9.3}
$$

结合式 (9.1)，频率比修正近似为

$$
\boxed{
\begin{aligned}
\frac{\delta\rho}{\rho}
\simeq{}&
-\frac{m_J}{m}\frac{xy}{2}\\
&+\frac{M_\ell}{m}
\left(\frac1{12}-\frac x4+\frac{x^2}{6}\right)\\
&-\frac{M_u}{m}
\left(\frac y4-\frac{y^2}{6}\right).
\end{aligned}}
\tag{9.4}
$$

这条新的一阶预算式显示：在某些几何中，下绳质量对两个频率的修正会部分抵消，而上支总质量主要只进入慢模，因而对频率比更敏感。是否可忽略必须按目标观测量判断：对频率比可小，但对绝对快模频率仍有 $M_\ell/(12m)$ 修正。

#### 9.1.3 绳内波动

定义摆频 $\omega_p$、相关绳长 $L_s$、纵向波速 $c_L$ 和张力主导的横波速度 $c_T$：

$$
c_L\simeq\sqrt{\frac E{\rho_s}},
\qquad
c_T\simeq\sqrt{\frac T\mu_s}.
$$

筛查量为

$$
\epsilon_{Lw}=\frac{\omega_pL_s}{c_L},
\qquad
\epsilon_{Tw}=\frac{\omega_pL_s}{c_T}.
$$

远离内部共振时，波动动力学对低频模态的影响通常还乘以绳质量参与因子；若绳内模态接近摆频或组合频率，则即使总绳质量小也不能忽略。重新拉直冲击包含远高于摆频的载荷频谱，不能用低频 $\epsilon_{Lw},\epsilon_{Tw}$ 直接排除波传播。

### 9.2 轴向弹性

#### 9.2.1 静态加载几何

小应变下

$$
\epsilon_i=\frac{\Delta L_i}{L_{i0}}
\simeq\frac{T_i}{E_iA_i}.
$$

轴向伸长首先改变实际 $s_A,s_B,\ell,h,H$。因此理论输入应优先使用**工作载荷下的实际长度**，或把静态伸长显式算入，而不是把未加载长度直接代入刚绳模型。

对称上支、固定 $d$ 时，

$$
\frac{\delta h}{h}
=\frac{s^2}{h^2}\frac{\delta s}{s}.
$$

浅 Y 几何会把很小的上支应变按 $s^2/h^2$ 放大。使用加载长度能吸收平均静态偏置，但不能自动消除动态柔度。

#### 9.2.2 上支差动柔度对快模的线性软化

这是长期闭合预测中容易漏掉的效应。快模小位移时，结点若沿支点轴移动 $u$，左右上支一伸一缩。对一般两上支，结点沿轴的线性等效刚度为

$$
\boxed{
K_x=
\sum_{i=A,B}
\left(
\frac{E_iA_i a_i^2}{s_i^3}
+\frac{T_{i0}h^2}{s_i^3}
\right).
}
\tag{9.5}
$$

第一项是材料轴向刚度投影，第二项是预张力几何刚度。对称装置退化为

$$
\boxed{
K_x=
\frac{2}{s^3}
\left(EA_u a^2+T_{u0}h^2\right).
}
\tag{9.6}
$$

在下绳使用加载长度 $\ell$、纵向响应可视为准静态、结点与上支质量可忽略时，摆球的重力横向刚度 $mg/\ell$ 与上部柔度近似串联。定义顺应性长度

$$
\ell_c=\frac{mg}{K_x},
$$

则

$$
\boxed{
\omega_\parallel^2
\simeq\frac{g}{\ell+\ell_c},
\qquad
\frac{\delta\omega_\parallel}{\omega_\parallel}
\simeq-\frac{mg}{2K_x\ell}.
}
\tag{9.7}
$$

这项是线性频率修正，不一定带有振幅平方因子。即使 $T/EA$ 看起来很小，几何杠杆 $s^3/a^2$ 也可能使 $\ell_c/\ell$ 达到可测量水平。它还预测频率随摆球质量系统变化，是区分轴向柔度与纯几何误差的有力实验。

慢模的理想共同转动不改变两上支长度；在对称、低频、无径向内模条件下，轴向柔度对慢模线性频率通常弱得多。下绳张力在小角线性阶近似为常数，因此其动态伸长主要在二阶及更高阶出现。靠近绳纵向模态、松弛或重新接合时，这些结论失效。

#### 9.2.3 何时可用准静态弹性

若

$$
\frac{\omega_pL_s}{c_L}\ll1,
$$

且上支差动内模满足

$$
\boxed{
\epsilon_{x,\rm dyn}
=\omega_p\sqrt{\frac{m_{x,\rm eff}}{K_x}}\ll1,
}
$$

其中 $m_{x,\rm eff}$ 是结点和上支在差动伸缩模态中的参与惯量，则轴向伸长可近似随瞬时张力准静态调整。若这些比值不小、频谱出现额外轴向峰，或接合脉冲含有接近纵向本征频率的谱功率，应使用有限结点—弹簧模型、离散弹簧—质量链或弹性绳 PDE。

### 9.3 弯曲刚度

真实细线具有弯曲刚度 $EI$。在恒定预张力 $T$ 下，小横向挠度满足

$$
\rho A w_{tt}+EIw_{ssss}-Tw_{ss}=0.
$$

定义弯曲边界层长度

$$
\boxed{\ell_b=\sqrt{\frac{EI}{T}}}
$$

和无量纲比

$$
\epsilon_b=\frac{\ell_b}{L_s}.
$$

若 $\epsilon_b\ll1$，大部分绳长仍表现为理想柔索；弯曲主要集中在夹持端、结点和摆球连接处，可低阶等效为：有效转轴偏移 $O(\ell_b)$、边界转动刚度和少量频率偏移。

弯曲修正的系数强烈依赖边界是夹持、打结、穿环还是近似铰接，不能只凭材料 $EI$ 给出普适频移。最稳妥的筛查是比较 $C_b\ell_b/L_s$ 与目标精度，其中 $C_b$ 由具体边界模型或纯模频率标定得到。

若写成复模量 $E^*=E'(1+i\tan\delta_b)$，$E'$ 决定保守刚度，$\tan\delta_b$ 才描述内耗。把整个 $EI$ 替换为速度阻尼会丢失静态曲率、边界条件和频率偏移。

### 9.4 扭转刚度

扭转刚度由 $GJ$ 控制。对于圆截面柔绳、点质量摆球、作用线通过质心、连接可自由转动且不传递力矩的装置，轴向扭转与摆球质心平动在最低阶**结构性解耦**。此时即使 $GJ$ 不为零，也可从质心 Lissajous 主模型中直接删除。

扭转只有在以下条件下才进入平动：

1. 摆球连接偏心；
2. 摆球姿态被约束，连接传递力矩；
3. 绳截面弯曲各向异性；
4. 扭转改变结点几何或摩擦；
5. 扭转模态接近摆频并发生共振。

保守能量为

$$
U_{\rm torsion}=\frac12\int GJ\kappa_3^2\,ds,
$$

损耗需另加粘性项或复剪切模量。扭转刚度不能整体等同于阻尼。

### 9.5 有限摆球、连接偏心与物理摆

$\ell$ 必须量到摆球**质心**。若柔绳只传递力且作用线通过质心，摆球自转与质心平动在最低阶解耦，质点模型成立，球半径只通过空气阻力、浮力和成像进入。

若连接刚性锁定摆球姿态，绕某一轴的小振动为物理摆：

$$
\boxed{
\omega^2=\frac{mgr}{mr^2+I_{\rm CM}},
}
$$

其中 $r$ 为转轴到质心距离。小转动惯量修正为

$$
\frac{\delta\omega}{\omega}
\simeq-\frac{I_{\rm CM}}{2mr^2}.
$$

对实心球 $I_{\rm CM}=2mR_b^2/5$，故

$$
\frac{\delta\omega}{\omega}
\simeq-\frac15\left(\frac{R_b}{r}\right)^2.
$$

这项只有在姿态确实被锁定时才成立；柔性点连接下不能机械套用物理摆公式。

### 9.6 阻尼

#### 9.6.1 从实际力到广义力

若摆球阻力为

$$
\boldsymbol F_d=-c_1\boldsymbol v-c_2|\boldsymbol v|\boldsymbol v,
$$

因环面坐标正交，

$$
Q_\varphi=-(c_1+c_2v)\ell^2\dot\varphi,
$$

$$
Q_\theta=-(c_1+c_2v)R^2\dot\theta,
$$

并有严格功率关系

$$
\boxed{
\dot E=Q_\varphi\dot\varphi+Q_\theta\dot\theta
=-c_1v^2-c_2v^3\le0.
}
$$

结点和支点摩擦可另用黏性矩与库仑摩擦描述。刚度项不能混入这些耗散广义力。

#### 9.6.2 线性阻尼的两个不同影响

单模线性弱阻尼满足

$$
\ddot q+2\Gamma\dot q+\omega_0^2q=0,
$$

$$
A(t)=A_0e^{-\Gamma t},
\qquad
\omega_d=\sqrt{\omega_0^2-\Gamma^2}.
$$

定义 $Q=\omega_0/(2\Gamma)$，则

$$
\boxed{
\frac{\omega_d-\omega_0}{\omega_0}
\simeq-\frac1{8Q^2},
}
$$

而经过 $N$ 个该模态周期后

$$
\boxed{
\frac{A_N}{A_0}=e^{-\pi N/Q}.
}
$$

所以直接阻尼频移常可忽略，但包络变化可能远大得多。包络又通过式 (5.5) 改变非线性频率比，因此不能由“$1/Q^2$ 很小”推出阻尼对长期图样无关。

#### 9.6.3 二次阻力与干摩擦

对单一近正弦模态、以水平位移振幅 $A_x$ 表示，二次阻力的平均包络满足

$$
\dot A_x\simeq
-\frac{4c_2\omega}{3\pi m}A_x^2,
$$

$$
A_x(t)=\frac{A_{x0}}{1+t/\tau_q},
\qquad
\tau_q=\frac{3\pi m}{4c_2\omega A_{x0}}.
$$

诊断上：$\ln A$ 对 $t$ 近直线提示线性黏性阻尼；$1/A$ 对 $t$ 近直线提示二次阻力；峰值振幅对周期数近线性下降且可能突然停止提示库仑摩擦。

### 9.7 支点倾斜、一般线性不对称与支架动力学

#### 9.7.1 支点轴不水平

令支点轴单位向量为 $\boldsymbol e_x$，竖直向下单位向量分解为

$$
\boldsymbol e_g=
\gamma_g\boldsymbol e_x+
\eta_g\boldsymbol e_2,
\qquad
\eta_g=\sqrt{1-\gamma_g^2},
$$

其中 $\boldsymbol e_2\perp\boldsymbol e_x$，并令 $\theta=0$ 时 $\boldsymbol e_r=\boldsymbol e_2$。忽略与运动无关的常数，势能为

$$
\boxed{
U=-mg\left[\ell\gamma_g\sin\varphi
+\eta_gR\cos\theta\right].
}
$$

运动方程变为

$$
\boxed{
\ell\ddot\varphi+R\sin\varphi\,\dot\theta^2
+g\eta_g\sin\varphi\cos\theta
-g\gamma_g\cos\varphi=0,
}
$$

$$
\boxed{
R\ddot\theta+2\dot R\dot\theta
+g\eta_g\sin\theta=0.
}
$$

轴倾斜使平衡点沿快模方向偏移；对小倾角，静态偏移是一阶，而平衡点附近频率变化通常从二阶开始。实验中应直接测量两个支点的三维坐标，不要把这种静态偏移误拟合为初相位。

#### 9.7.2 通用小振幅曲率诊断

对任意轻微不对称装置，在真实平衡点附近取两个正交切向位移 $\boldsymbol\xi=(X,Y)^{\mathsf T}$，若势能展开为

$$
V=V_0+\frac{mg}{2}
\boldsymbol\xi^{\mathsf T}\mathsf C_g\boldsymbol\xi
+O(|\boldsymbol\xi|^3),
$$

且平动质量矩阵在该坐标中近似为 $mI$，则

$$
\boxed{
\ddot{\boldsymbol\xi}+g\mathsf C_g\boldsymbol\xi=0.
}
$$

理想 Y 摆对应

$$
\mathsf C_{g0}=
\begin{pmatrix}
1/\ell&0\\
0&1/H
\end{pmatrix}.
$$

一般对称曲率矩阵的两个频率为

$$
\boxed{
\omega_\pm^2=g\left[
\frac{C_{xx}+C_{yy}}2
\pm\sqrt{
\left(\frac{C_{xx}-C_{yy}}2\right)^2+C_{xy}^2
}
\right],
}
$$

主轴转角满足

$$
\boxed{
\tan2\psi=\frac{2C_{xy}}{C_{xx}-C_{yy}}.
}
$$

这是一层诊断模型：非零 $C_{xy}$ 可来自支点不等高、连接弯曲刚度、支架耦合或相机坐标旋转。它能描述实测主轴和频率，但不能在不解释来源的情况下替代几何主模型。尤其当两理想频率接近时，很小的交叉项也会显著旋转主轴。

#### 9.7.3 支架动力学

若支架自由度为 $u_s$，可写

$$
M_s\ddot u_s+C_s\dot u_s+K_su_s=F_{\rm string}.
$$

静态位移尺度为

$$
\epsilon_{s,\rm stat}=\frac{mg}{K_s\ell}.
$$

若加载后的实际支点位置已测量，平均静挠度可吸收到几何中；动态支点运动仍会产生惯性激励。远离支架共振时，低阶频移通常按

$$
\text{参与因子}\times
\text{质量比}\times
\left(\frac{\omega_p}{\omega_s}\right)^2
$$

缩放。若支架模态接近摆频，必须联立建模，不能只改一个有效长度。共同平移的规定支点运动可通过把重力替换为 $\boldsymbol g_{\rm eff}=\boldsymbol g-\ddot{\boldsymbol r}_s(t)$ 处理；两支点非共同运动则必须保留支架变形自由度。

### 9.8 空气浮力、附加质量与地球自转

对体积为 $V$ 的摆球，单模绝对频率可估为

$$
\omega^2\simeq
\frac{m-\rho_aV}{m+C_a\rho_aV}
\frac g{L_{\rm eff}}.
$$

若两模使用同一摆球平动质量，该流体因子近似共同乘在两个频率上，因此在频率比中首阶抵消。对致密小球，$\rho_aV/m\ll1$，通常连绝对频率都可忽略；对轻质大球则需检查。

地球自转引入

$$
\boldsymbol F_C=-2m\boldsymbol\Omega_E\times\boldsymbol v.
$$

远离两频近简并时，可用

$$
\epsilon_\Omega=
\frac{2\Omega_E}{|\omega_\parallel-\omega_\perp|}
$$

筛查模态混合，并检查 $\Omega_ET_{\rm obs}$ 是否小于允许相位误差。普通桌面 $3:2$、$4:3$ 装置和分钟内观察通常可忽略；长摆、近 $1:1$ 和长时间拍动实验需重新评估。

### 9.9 观测映射不是动力学附注

#### 顶视相机

普通透视相机距装置有效距离为 $D$ 时，竖直位移 $\Delta z$ 会产生约 $\Delta z/D$ 的比例调制。由

$$
\Delta z\sim
\frac\ell2A_\varphi^2+
\frac H2A_\theta^2
$$

可先估算

$$
\boxed{
\epsilon_{\rm persp}
\sim
\frac{\ell A_\varphi^2+HA_\theta^2}{2D}.
}
$$

若它大于目标轨迹精度，必须做三维标定、逐帧深度修正、远心/近正交成像或双相机重建。单一平面单应性不能自动消除随时间变化的深度误差。

#### 灯点、笔尖和砂迹

若观测点固定在摆球上，

$$
\boldsymbol r_{\rm obs}(t)=
\boldsymbol r_{\rm CM}(t)+
\mathsf Q(t)\boldsymbol\rho_{\rm obs}.
$$

偏离质心的灯点会混入摆球转动。笔尖接触纸面会增加法向约束、摩擦和杆件弹性。砂粒或液滴离开喷口后还要经历弹道飞行，落点并非释放时刻的质心投影。用于定量动力学时必须显式建模，而不是把记录器当作完全被动。

---
## 10. 量级分析：哪些非理想因素可以忽略

“可忽略”不是一个与研究目标无关的绝对判断。对只画两三个周期的定性花纹，$10^{-3}$ 的频率误差可能看不出来；对几十周期后的闭合，相同误差会累积成明显相位漂移。因此必须先定义目标观测量和允许误差，再比较各修正对该观测量的传播结果。

### 10.1 长期闭合的精度预算

对目标 $p:q$，设实际频率比为

$$
\rho_{\rm act}=\rho_0(1+\epsilon_\rho),
\qquad
\rho_0=\frac pq.
$$

经过 $N$ 个慢模周期后，共振相位误差为

$$
|\Delta\Psi_N|
\simeq2\pi pN|\epsilon_\rho|.
$$

若允许相位误差为 $\Phi_{\rm tol}$，则

$$
\boxed{
|\epsilon_\rho|
=\left|\frac{\delta\rho}{\rho}\right|
\lesssim
\epsilon_{\rm req}
\equiv
\frac{\Phi_{\rm tol}}{2\pi pN}.
}
\tag{10.1}
$$

对单一绝对频率，若经过 $N_i$ 个该模态周期后容许相位误差 $\Phi_{i,\rm tol}$，则

$$
\boxed{
\left|\frac{\delta\omega_i}{\omega_i}\right|
\lesssim
\frac{\Phi_{i,\rm tol}}{2\pi N_i}.
}
\tag{10.2}
$$

对轨迹位置，应另定义

$$
\epsilon_x=\frac{\sigma_x}{A_{\rm traj}},
$$

其中 $\sigma_x$ 是允许的二维位置误差，$A_{\rm traj}$ 是代表性轨迹尺度。频率、包络、张力事件和位置可能要求不同的精度预算。

### 10.2 “可忽略”的严格定义

一个候选效应只有同时满足以下条件，才可从目标模型中删除：

1. 它对所有目标观测量的**上界**均小于相应误差预算；
2. 判断不依赖两个未知修正的偶然符号抵消；
3. 它不会改变约束拓扑、活跃约束集或接合事件；
4. 它不在摆频、组合频率或载荷脉冲附近发生共振；
5. 删除后残差中没有该机制特有的质量、振幅、频率或空间结构。

因此，张力过零、滑动结、下绳松弛和支架共振不是普通微扰；即使事件前的偏差很小，也不能按线性误差预算忽略。

### 10.3 关键无量纲参数

建议至少计算：

$$
\eta=\frac h\ell
\quad\text{（理想几何）},
$$

$$
\kappa_A=\frac{a_A}{h},
\qquad
\kappa_B=\frac{a_B}{h}
\quad\text{（上支张紧范围）},
$$

$$
\epsilon_A=\max(|A_\varphi|,|A_\theta|)
\quad\text{（有限振幅）},
$$

$$
\epsilon_J=\frac{m_J}{m},
\qquad
\epsilon_{m\ell}=\frac{M_\ell}{m},
\qquad
\epsilon_{mu}=\frac{M_u}{m},
$$

$$
\epsilon_e=\max_i\frac{T_i}{E_iA_i}
\quad\text{（轴向应变）},
$$

$$
\epsilon_c=\frac{mg}{K_x\ell}
\quad\text{（上支差动顺应性）},
$$

$$
\epsilon_{x,\rm dyn}
=\omega_p\sqrt{\frac{m_{x,\rm eff}}{K_x}}
\quad\text{（上支差动内模时标）},
$$

$$
\epsilon_b=\max_i\frac1{L_i}\sqrt{\frac{E_iI_i}{T_i}},
$$

$$
\epsilon_{Lw}=\max_i\frac{\omega_pL_i}{c_{L,i}},
\qquad
\epsilon_{Tw}=\max_i\frac{\omega_pL_i}{c_{T,i}},
$$

$$
\epsilon_d=Q^{-1},
\qquad
\epsilon_s=\frac{mg}{K_s\ell},
$$

$$
\epsilon_{\rm air}=\frac{\rho_aV}{m},
\qquad
\epsilon_\Omega=\frac{2\Omega_E}{|\omega_\parallel-\omega_\perp|},
$$

$$
\epsilon_{\rm persp}
\sim\frac{\ell A_\varphi^2+HA_\theta^2}{2D},
$$

以及张力裕量 $\eta_T$。

这些小量不能一律直接与 $\epsilon_{\rm req}$ 比较；必须乘上几何灵敏度、模态参与因子和观测映射系数。下表给出首阶传播。

### 10.4 各机制对主要观测量的首阶量级

| 机制 | 对频率比或轨迹的首阶影响 | 可以忽略的充分趋势 |
|---|---|---|
| 有限振幅 | $\left(\frac1{16}+\frac\ell{8H}\right)A_\varphi^2+\frac3{16}A_\theta^2$ | 该上界 $\ll\epsilon_{\rm req}$ |
| 几何误差 | $\delta\rho/\rho=\delta h/(2H)-h\delta\ell/(2\ell H)$ | 传播不确定度 $\ll\epsilon_{\rm req}$ |
| 结点质量 | $\lvert\delta\rho/\rho\rvert\simeq(m_J/m)h\ell/(2H^2)$ | 小于预算且无第三峰 |
| 下绳质量 | 快模绝对频移 $M_\ell/(12m)$；比值见式 (9.4) | 两种观测都小于预算，无绳内峰 |
| 上支总质量 | $\lvert\delta\rho/\rho\rvert\simeq(M_u/m)(y/4-y^2/6)$ | 小于预算，无明显上支摆动 |
| 上支轴向柔度 | $\lvert\delta\rho/\rho\rvert\approx mg/(2K_x\ell)$（慢模低阶不变） | $mg/(2K_x\ell)\ll\epsilon_{\rm req}$，且 $\epsilon_{x,\rm dyn}\ll1$ |
| 静态伸长 | 通过实际 $h,\ell$ 进入 | 用工作载荷下几何测量后可吸收 |
| 纵向波动力学 | 远离共振常为质量参与因子乘 $\epsilon_{Lw}^2$ | $\epsilon_{Lw}\ll1$，且无接合脉冲 |
| 弯曲刚度 | 常为 $C_b\ell_b/L$ | 经边界标定后 $C_b\epsilon_b\ll\epsilon_{\rm req}$ |
| 扭转 | 自由点连接下最低阶为零 | 作用线过质心、连接不传矩、无扭转共振 |
| 刚性摆球转动 | $I_{\rm CM}/(2mr^2)$ | 柔性点连接时结构性为零；否则小于预算 |
| 线性阻尼直接频移 | $O(Q^{-2})$ | $1/(8Q_i^2)\ll\epsilon_{\rm req}$ |
| 阻尼包络 | $1-e^{-\pi N/Q}$，并改变非线性失谐 | 包络变化及其频移传播均小于预算 |
| 支点柔性 | 静态 $mg/(K_s\ell)$；动态含 $(\omega/\omega_s)^2$ | 支点实测运动与传播频移均小于预算 |
| 浮力/附加质量 | 绝对频率 $O(\rho_aV/m)$，频率比首阶共同抵消 | 致密小球且只研究比值时通常可忽略 |
| Coriolis | 模态混合 $2\Omega_E/\lvert\Delta\omega\rvert$ | 远离 $1:1$，且 $\Omega_ET_{\rm obs}\ll\Phi_{\rm tol}$ |
| 相机透视 | $\Delta z/D$ | 三维修正后低于位置预算 |
| 任一张力过零 | 改变约束流形 | **不能按小量忽略** |
| 滑动结 | 改变约束方程和自由度 | **不能按小量忽略** |

### 10.5 代表性 $3:2$ 设计的数值预算

考虑一套用于展示量级的对称装置：

$$
\ell=0.300\ \mathrm m,
\qquad
h=0.375\ \mathrm m,
\qquad
H=0.675\ \mathrm m,
$$

$$
a=0.150\ \mathrm m,
\qquad
d=0.300\ \mathrm m,
\qquad
s=\sqrt{h^2+a^2}=0.403887\ \mathrm m,
$$

$$
m=0.200\ \mathrm{kg}.
$$

零振幅频率为

$$
\omega_\parallel=5.71839\ \mathrm{rad\,s^{-1}},
\qquad
\omega_\perp=3.81226\ \mathrm{rad\,s^{-1}},
$$

$$
\rho=1.50000,
\qquad
T_\perp=1.64815\ \mathrm s.
$$

对称上支的几何松弛角为

$$
\varphi_{\rm slack}=\arctan(a/h)
=0.38051\ \mathrm{rad}=21.80^\circ.
$$

后文采用的 $A_\varphi=8.59^\circ$、$A_\theta=5.73^\circ$ 在纯几何上仍处于三绳正张力带内；实际双模轨迹仍应逐时计算张力，而不能只比较峰值角。

设目标为经过 $N=30$ 个慢周期后，共振相位误差不超过

$$
\Phi_{\rm tol}=0.20\ \mathrm{rad}.
$$

由式 (10.1)，

$$
\boxed{
\epsilon_{\rm req}=3.54\times10^{-4}
=0.0354\%.
}
$$

这意味着“单周期看起来完全一样”的效应，在长期闭合问题中仍可能必须保留。

#### 10.5.1 几何测量要求

若只有 $h$ 有误差，要求

$$
|\delta h|<2H\epsilon_{\rm req}
=0.477\ \mathrm{mm}.
$$

若只有 $\ell$ 有误差，要求

$$
|\delta\ell|<
\frac{2\ell H}{h}\epsilon_{\rm req}
=0.382\ \mathrm{mm}.
$$

因此毫米级粗测不够，而亚毫米加载几何测量基本可满足这组相位目标。若 $h$ 由 $s,d$ 间接计算，还要传播二者的相关不确定度。

#### 10.5.2 有限振幅

取

$$
A_\varphi=0.150\ \mathrm{rad}=8.59^\circ,
\qquad
A_\theta=0.100\ \mathrm{rad}=5.73^\circ.
$$

式 (5.5) 给出

$$
\frac{\delta\rho_A}{\rho}
=-7.81\times10^{-4},
$$

约为允许预算的 $2.21$ 倍，**不能忽略**。

若要求两个非线性项分别都小于预算，而不依赖抵消，则需近似满足

$$
A_\varphi<0.0547\ \mathrm{rad}=3.14^\circ,
$$

$$
A_\theta<0.0434\ \mathrm{rad}=2.49^\circ.
$$

所以“十度以内都算小角度”对几十周期闭合并不成立。

#### 10.5.3 结点质量

若 $m_J=0.30\ \mathrm g$，则

$$
\frac{\delta\rho_J}{\rho}
\simeq-\frac12\frac{m_J}{m}\frac{h\ell}{H^2}
=-1.85\times10^{-4}.
$$

它单独低于预算，但已占 $52\%$，属于**边界项**。在此设计中，要让结点质量单项低于预算，需

$$
m_J<0.573\ \mathrm g.
$$

若还有上支绳质量、柔度或几何误差，不能把多个“各自略小”项全部删除。

#### 10.5.4 绳质量

设下绳质量 $M_\ell=0.25\ \mathrm g$，两上支总质量 $M_u=0.60\ \mathrm g$。式 (9.4) 给出

$$
\frac{\delta\rho_{\rm string}}{\rho}
=-2.56\times10^{-4}.
$$

仍低于单项预算，但占 $72\%$。结点与绳质量合并后约为

$$
-4.41\times10^{-4},
$$

已经超过预算。因此在这组长期目标下，应加入式 (9.4) 的低阶质量修正，或增大摆球质量、减轻结点和上支。

对绝对快模频率，$M_\ell/(12m)=1.04\times10^{-4}$。若要求同样的相对绝对频率精度，下绳质量上限约为 $0.849\ \mathrm g$。

#### 10.5.5 上支轴向柔度

平衡上支张力为

$$
T_{u0}=\frac{mgs}{2h}=1.057\ \mathrm N.
$$

若每条上支的实测轴向刚度为

$$
EA_u=10.0\ \mathrm{kN},
$$

式 (9.6) 给出

$$
K_x=6.835\times10^3\ \mathrm{N\,m^{-1}},
$$

$$
\ell_c=\frac{mg}{K_x}=0.287\ \mathrm{mm},
$$

$$
\frac{\delta\rho_e}{\rho}
\simeq-\frac{\ell_c}{2\ell}
=-4.78\times10^{-4}.
$$

即使 $EA_u$ 达到 $10\ \mathrm{kN}$，该效应仍超过长期闭合预算。此例中需要约

$$
EA_u\gtrsim13.5\ \mathrm{kN}
$$

才使上支差动柔度单项低于 $3.54\times10^{-4}$；实际绳和结的刚度应直接加载测量，因为纤维束、编织结构和结扣常表现为非线性顺应性。

这不意味着必须使用完整弹性 PDE。若 $\omega L/c_L\ll1$，可先用式 (9.7) 的等效顺应性长度；只有出现纵向峰、明显相位滞后或接合脉冲时才升级连续体模型。

#### 10.5.6 弯曲刚度

若边界系数 $C_b\sim1$，要让弯曲边界层修正低于预算，需要大致

$$
\ell_b<\epsilon_{\rm req}\ell
\simeq0.106\ \mathrm{mm}.
$$

这一要求对柔软编织线可能满足，对较粗单丝、金属丝或刚性夹持端未必满足。由于 $C_b$ 依赖结和夹持方式，弯曲刚度不能仅凭“线很细”直接排除；应比较不同自由铰接/夹持方式下的纯模频率，或测量连接处曲率尺度。

#### 10.5.7 摆球转动

若半径 $R_b=10\ \mathrm{mm}$ 的实心球被刚性锁定，取 $r\approx\ell$，物理摆修正约为

$$
-\frac15\left(\frac{R_b}{\ell}\right)^2
=-2.22\times10^{-4}.
$$

它低于但接近预算。若绳通过柔性点连接且作用线通过质心，该项最低阶为零，可直接忽略。此例说明：连接拓扑比球半径本身更重要。

#### 10.5.8 阻尼

若慢模 $Q_\perp=1000$，且各向同性线性平移阻力使快模 $Q_\parallel\approx1500$，则阻尼对频率比的直接修正仅约

$$
6.94\times10^{-8},
$$

可忽略。但 30 个慢周期后包络为

$$
A/A_0=e^{-\pi N/Q_\perp}=0.910,
$$

下降约 $9.0\%$。因此**直接阻尼频移可忽略，阻尼包络不可忽略**；后者会改变图样纵横比，并通过有限振幅频移改变 $\Delta_{pq}(t)$。

对半径 $10\ \mathrm{mm}$ 的致密球，取空气密度 $1.2\ \mathrm{kg\,m^{-3}}$、示例阻力系数 $C_D=0.47$（仅作为中等 Reynolds 数球体的量级假设），并取水平振幅约 $45\ \mathrm{mm}$，仅摆球二次空气阻力给出的几十周期包络变化在千分量级；若实测衰减明显更大，优先检查绳阻力、结点摩擦和支架损耗，而不是强行增大球的 $C_D$。

#### 10.5.9 支架、Coriolis、浮力与透视

- 若支点动态位移上界为 $30\ \mu\mathrm m$，相对 $\ell$ 为 $1.0\times10^{-4}$，且支架模态远离摆频，则可忽略动态支架修正。
- 本例 $2\Omega_E/|\omega_\parallel-\omega_\perp|=7.65\times10^{-5}$，而 30 个慢周期内 $\Omega_ET_{\rm obs}=3.61\times10^{-3}\ \mathrm{rad}$，Coriolis 可忽略。
- 取 $\rho_a=1.2\ \mathrm{kg\,m^{-3}}$ 时，半径 $10\ \mathrm{mm}$、质量 $0.200\ \mathrm{kg}$ 的致密球有 $\rho_aV/m\approx2.5\times10^{-5}$，且两模共同因子在比值中抵消，可忽略。
- 上述双模振幅的竖直变化尺度为约 $6.75\ \mathrm{mm}$。普通相机若距装置 $D=2.0\ \mathrm m$，未修正透视约为
  $$
  \epsilon_{\rm persp}\simeq3.38\times10^{-3},
  $$
  对应约 0.34% 的时变比例畸变。若轨迹位置也要求达到与频率比预算相近的分数精度，则它约大 9.5 倍；若只靠增大距离压到该量级，需要约 $D>19\ \mathrm m$，并不现实；因此必须做三维/深度修正，而不是把投影误差归因于非线性动力学。

#### 10.5.10 累积预算，而不是逐项“都略小”

若把本例中的有限振幅、结点/绳质量和上支差动柔度全部错误地删除，它们的一阶净修正约为

$$
\frac{\delta\rho_{\rm omitted}}{\rho}
\simeq
-7.81\times10^{-4}
-4.41\times10^{-4}
-4.78\times10^{-4}
=-1.70\times10^{-3}.
$$

这约为允许预算的 $4.8$ 倍，并会在 30 个慢周期后累积出约

$$
|\Delta\Psi_{30}|\simeq
2\pi\times3\times30\times1.70\times10^{-3}
\approx0.96\ \mathrm{rad}
$$

的共振相位误差。该相加只保留一阶项，忽略了质量—柔度等交叉修正；其目的不是给出最终校正值，而是说明多个“各自不算很大”的机制不能被分别删除。确定性未建模项应按保守绝对和控制，统计测量误差则按协方差传播。

### 10.6 本代表性设计的保留/忽略结论

在上述 $3:2$、30 个慢周期、$0.20\ \mathrm{rad}$ 相位容差的任务中，建议：

#### 必须保留

- 精确环面有限振幅动力学；
- 三根瞬时张力和松弛事件；
- 阻尼包络及其引起的时变非线性失谐；
- 加载状态下的真实几何；
- 相机三维/透视观测模型。

#### 至少加入低阶修正或专项测量

- 结点质量；
- 上支总绳质量；
- 上支差动轴向柔度；
- 连接处弯曲边界层；
- 若姿态被锁定，则摆球转动惯量；
- 支点动态位移。

#### 在明确条件下可直接忽略

- 自由点连接下的绳扭转与摆球自转；
- 致密小球的浮力和附加质量对频率比的影响；
- 普通桌面 $3:2$ 装置的 Coriolis 力；
- 无冲击、远离内模态时的纵向波传播；
- 仅摆球本体的微弱二次空气阻力，如果实测包络证实其影响低于预算。

### 10.7 更一般的快速决策树

1. **先问拓扑**：固定结还是滑动绳？任一张力会不会到零？若答案不确定，不能停在光滑二自由度模型。
2. **确定目标精度**：用式 (10.1) 把观察周期数和相位容差换成 $\epsilon_{\rm req}$。
3. **用加载几何计算理想频率与张力**：先排除几何和模型入口错误。
4. **检查有限振幅**：它通常是第一大修正。
5. **称质量、测轴向刚度、测支点运动**：用式 (9.4)、(9.7) 做无拟合预算。
6. **测纯模包络**：区分直接频移与振幅演化。
7. **只有残差要求时才升级弯扭、绳 PDE 或完整 DAE**。

---
## 11. 可证伪预测与参数辨识

一套具有预测能力的理论应在改变参数前给出方向、标度和定量结果，而不是只在看到轨迹后重新拟合。下表汇总主模型与低阶扩展的核心预测。

| 编号 | 控制量 | 预测 | 若失败优先检查 |
|---:|---|---|---|
| P1 | 下绳加载长度 $\ell$ | $T_\parallel^2=4\pi^2\ell/g$ | 上支柔度、下绳质量、质心长度 |
| P2 | $H=h+\ell$ | $T_\perp^2=4\pi^2H/g$ | 结点/绳质量、支架运动 |
| P3 | $h/\ell$ | $\rho^2=1+h/\ell$ | 有限振幅、弹性顺应、错误拓扑 |
| P4 | 摆球质量 $m$ | 理想频率不变 | 上支柔度、伸长、阻力/质量、支架 |
| P5 | 同 $h/\ell$、不同上三角形 | 归一化低频轨迹相同，松绳阈值不同 | 支点不等高、结点摩擦 |
| P6 | 目标 $p:q$ | $h/\ell=(p/q)^2-1$ | 几何误差、有限振幅、非理想频移 |
| P7 | 失谐 | $T_{\rm drift}=2\pi/\lvert q\Omega_\parallel-p\Omega_\perp\rvert$ | 啁啾、时钟误差、约束切换 |
| P8 | 纯模振幅 | $T/T_0-1\simeq A^2/16$ | 干摩擦、释放初速度、松绳 |
| P9 | 双模振幅 | 式 (5.3)–(5.5) 的二维频移面 | 近 $1:1$、高阶项、弹性 |
| P10 | 上支半距 $a$ | 主频在固定 $h,\ell$ 时不变，松弛阈值改变 | 轴向柔度、支点倾斜 |
| P11 | 结点质量 | 第三模态；轻结点时 $\omega_+\propto m_J^{-1/2}$ | 绳横向模态、相机带宽 |
| P12 | 上支轴向刚度 | 快模软化且随 $m/EA$ 增强 | 支架差动柔度、结点滑移 |
| P13 | 阻尼机制 | 指数、反比例或近线性峰值包络 | 混合阻尼、气流、静摩擦 |
| P14 | 三维轨迹 | 环面残差为零；$z$ 主含双频 | 透视、伸长、有限结点质量 |
| P15 | 上支张力 | 在式 (6.4) 边界降为零 | 载荷传感器偏置、结点惯性 |
| P16 | 初相/初速度 | 图样由 $A_X/A_Y,\Psi_{pq}$ 改变 | 释放不可重复、观测时间零点 |

### 11.1 最强的无拟合检验

以下关系几乎不需要新增拟合参数：

1. 只激发快模时，周期符合长度 $\ell$ 的单摆椭圆积分，直至上支张力边界；
2. 只激发慢模时，周期符合长度 $H$ 的单摆椭圆积分，直至下绳张力边界；
3. 小振幅 $\omega_\parallel^2\ell/g=1$、$\omega_\perp^2H/g=1$；
4. 改变摆球质量时，理想刚绳主频不变；若快模按质量降低，优先检查式 (9.7) 的上支柔度；
5. 由轨迹计算的 $T_A,T_B,T_\ell$ 必须全为正；任一过零后不能继续使用同一全张紧方程；
6. 双相机重建的质心坐标应满足环面约束残差
   $$
   \mathcal R_T(t)=
   \frac{(x-x_C)^2+[\sqrt{y^2+z^2}-h]^2-\ell^2}{\ell^2}
   $$
   在误差范围内为零。

### 11.2 参数可辨识性

仅从一条二维轨迹通常可稳定识别：

- 两主频及其慢漂移；
- 两个水平振幅；
- 共振相位；
- 阻尼包络；
- 组合频率。

但以下机制在单一工况中可能混淆：

- 几何长度误差、上支柔度和支点差动柔度都可改变快模有效长度；
- 结点质量与上支绳质量都可改变慢模；
- 摆球空气阻力、绳阻力和结点摩擦都可产生衰减；
- 几何主轴旋转与相机坐标旋转可能外观相同；
- 质心连接偏置与错误长度定义会共同改变绝对频率。

区分机制应利用标度差异：

- 改变摆球质量：轴向顺应修正近似随 $m/EA$ 增长，理想几何频率不变；
- 改变结点质量：第三峰按 $m_J^{-1/2}$ 移动；
- 改变振幅：几何非线性按 $A^2$ 变化；
- 改变上部三角形但保持 $h/\ell$：理想频率塌缩，松弛边界与柔度系数改变；
- 改变摆球直径和质量：空气阻力与质量比、浮力和转动惯量具有不同标度。

无法分离时应报告可辨识参数组合或上限，而不是给多个虚假的高精度单参数。

### 11.3 不确定度传播

若参数向量为 $\boldsymbol p$，协方差为 $\Sigma_p$，预测量 $f$ 的一阶方差为

$$
\boxed{
\sigma_f^2\simeq
\nabla f^{\mathsf T}\Sigma_p\nabla f.
}
$$

对频率比，

$$
\frac{\partial\rho}{\partial h}
=\frac{1}{2\ell\rho},
\qquad
\frac{\partial\rho}{\partial\ell}
=-\frac{h}{2\ell^2\rho}.
$$

对共振失谐

$$
\Delta_{pq}=q\Omega_\parallel-p\Omega_\perp,
$$

$$
\boxed{
\sigma_{\Delta_{pq}}^2
=q^2\sigma_{\Omega_\parallel}^2
+p^2\sigma_{\Omega_\perp}^2
-2pq\operatorname{Cov}(\Omega_\parallel,\Omega_\perp).
}
$$

若两个频率由同一时钟和同一时间序列联合估计，其误差通常相关，不能简单按独立误差相加。

常频率近似下，共振相位不确定度随时间近似二次增长：

$$
\sigma_\Psi^2(t)
=\sigma_{\Psi_0}^2
+2t\operatorname{Cov}(\Psi_0,\Delta_{pq})
+t^2\sigma_{\Delta_{pq}}^2.
$$

有阻尼和幅度啁啾时，应使用

$$
\Psi_{pq}(t)=\Psi_{pq}(0)+
\int_0^t\Delta_{pq}(t';\boldsymbol\vartheta)\,dt'
$$

并对完整参数向量做联合传播。接近 $\Delta_{pq}=0$、松绳时刻、张力峰和非线性轨迹时，一阶传播失效，应使用 Monte Carlo。

---

## 12. 数值求解、闭合指标与验证流程

### 12.1 环面相位积分

取状态

$$
y=(\varphi,\theta,\dot\varphi,\dot\theta).
$$

每个积分步同步计算

$$
R>0,
\qquad
T_\ell>0,
\qquad
T_A>0,
\qquad
T_B>0.
$$

任一张力从正值降到零时必须定位事件并停止或切换模型。删除事件函数继续积分得到的是允许柔绳受压的非物理解。

建议：

- 一般高精度积分使用 DOP853，`rtol` 至少 $10^{-9}$；
- 长时保守相图优先使用变分/辛方法；
- 检查能量误差和步长收敛；
- 事件时刻要对容差收敛；
- 不要把求解器相位漂移误判为物理失谐。

### 12.2 状态闭合误差

对目标 $p:q$，名义闭合时间可取

$$
T_{pq}^{(0)}=\frac{2\pi p}{\omega_\parallel}
=\frac{2\pi q}{\omega_\perp}.
$$

定义归一化状态闭合误差

$$
\boxed{
\mathcal C_{pq}
=\frac{\|W[y(t_0+T)-y(t_0)]\|}
{\|Wy(t_0)\|+\epsilon},
}
$$

其中 $W$ 把角度和角速度按相应频率归一化。验证时，$T$ 的定义必须在看测试轨迹前冻结，不能在测试数据上重新搜索“最闭合时间”。

对有阻尼轨迹，也可先按预先冻结的包络模型去包络，再计算固定名义闭合时间下的水平轨迹误差；必须明确这不是耗散相空间中的真实周期轨道。

### 12.3 瞬时相位与漂移率

在线性或弱非线性区，对带通后的模态坐标构造解析信号

$$
z_i(t)=q_i(t)+i\mathcal H[q_i(t)],
$$

其中 $\mathcal H$ 为 Hilbert 变换。瞬时相位为

$$
\phi_i(t)=\arg z_i(t),
$$

共振相位为

$$
\Psi_{pq}(t)=q\phi_\parallel(t)-p\phi_\perp(t).
$$

- 近似直线斜率给出失谐 $\Delta_{pq}$；
- 周期起伏提示非线性调制；
- 张力事件处跳变提示约束切换；
- 随振幅衰减而过零提示阻尼引起的非线性失谐反向。

### 12.4 Poincaré 取样

每当慢模以固定方向通过 $Y=0$ 时记录归一化快模状态。在线性无阻尼模型中：

- $\rho=p/q$ 时截面有有限个离散点；
- 无理比时点沿圆周推进；
- 近有理比时按 $n\bmod q$ 分组后缓慢漂移。

复杂二维图样不等于混沌。要声称混沌，至少应检查完整四维状态的 Poincaré 截面、有限时 Lyapunov 指数、邻近初值分离和数值收敛；混合系统还要把事件盐跃矩阵纳入变分演化。

### 12.5 参数扫描的最小输出

对每组 $(h/\ell,A_\varphi,A_\theta,\Psi_{pq})$，至少输出：

1. 两主频及组合频率；
2. $\min T_A,\min T_B,\min T_\ell$；
3. 状态闭合误差；
4. 共振相位漂移率；
5. 能量/功率平衡误差；
6. 是否触发松弛事件；
7. 各非理想修正相对 $\epsilon_{\rm req}$ 的预算占比。

### 12.6 校准与盲验证原则

参数应按机制独立标定：

- 几何、质量和轴向刚度由静态测量；
- 两个纯模给出基准频率、有限振幅周期和包络；
- 上支载荷或视频给出松弛边界；
- 只有出现第三峰、明显结点相对运动或张力脉冲时才启用更高层级。

验证集应按整次运行或整套几何划分，不能把同一视频的相邻帧一部分用于拟合、一部分用于“验证”。在打开验证数据前冻结：方程、阻尼形式、参数、初值估计规则、预处理、闭合指标和允许误差。

---

## 13. 统一闭合预测方程：二次 Ritz 柔索—结点—摆球模型

前面的环面方程、有限结点质量模型、绳质量修正、轴向顺应性、弯曲边界层和单边约束分析，分别回答了不同局部问题，但尚未自动组成一个“输入参数和初态后即可唯一产生整条轨迹”的方程。本节补上这一预测闭包。

最终采用的不是把所有效应强行塞入两个角变量的经验修正式，也不是把每根绳离散成大量质点的高维直接仿真，而是一个**固定低阶、保守部分变分一致、可逐模态升级的 Ritz 柔索模型**。每根物理绳只保留一个内部形状节点，即一个二次空间模态；三根绳合计只增加三个三维内部节点。它由连续柔索的动能、重力、轴向应变能和弯曲能解析投影得到。

该模型具有以下性质：

1. 在三绳全张紧、绳和结点质量趋零、轴向刚度趋于无穷的奇异极限中，恢复第 3 节的二自由度环面方程；
2. 在有限质量和有限刚度下，绳的伸长、松弛、重新受拉和最低内部模态均由同一组方程连续决定；
3. 不需要在张力过零时人为猜测下一阶段；“绷紧/松弛”由局部拉伸和单边本构自动判定；
4. 给定完整参数向量与完整初始状态后，右端向量场局部 Lipschitz，因而在每个有限观察窗内具有唯一解；
5. 当量级分析表明内部自由度很快时，可以从母方程系统地绝热消去，得到修正后的低维慢流形方程，而不是事后添加互不相容的频移补丁。

### 13.1 “闭合”的精确定义

设全部模型参数组成向量

$$
\boldsymbol p=
\left(
A,B,
L_A^0,L_B^0,L_\ell^0,
M_A,M_B,M_\ell,
m_J,m,
EA_i,\eta_iA_i,EI_i,
\boldsymbol p_{\rm air},
\boldsymbol p_{\rm support},
\delta_\epsilon,\varepsilon_t,\varepsilon_\kappa
\right).
$$

这里 $L_i^0$ 是各材料支路的无载参考长度，$M_i$ 是各支路总质量，$EA_i$ 是轴向刚度，$\eta_iA_i$ 是轴向黏弹系数，$EI_i$ 是等效弯曲刚度；最后三个小参数分别控制受拉激活宽度、切向/伸长率正则化和曲率分母正则化。它们必须在验证数据打开前固定。

这里的 $L_A^0,L_B^0,L_\ell^0$ 是材料无载参考长度，不等同于前文理想环面模型中直接测得的工作长度 $s_A,s_B,\ell$。有限刚度模型的工作长度由静态平衡自动产生；只有在不可伸长极限中才有 $L_A^0=s_A$、$L_B^0=s_B$、$L_\ell^0=\ell$。

完整状态记为

$$
\boldsymbol X(t)=
\begin{pmatrix}
\boldsymbol q(t)\\
\dot{\boldsymbol q}(t)
\end{pmatrix}.
$$

所谓统一闭合，是存在由理论显式定义的向量场

$$
\boxed{
\dot{\boldsymbol X}
=\boldsymbol F(\boldsymbol X;\boldsymbol p),
\qquad
\boldsymbol X(0)=\boldsymbol X_0,
}
\tag{13.1}
$$

使 $\boldsymbol p$ 与 $\boldsymbol X_0$ 一经给定，以下量全部被唯一决定：

$$
\boldsymbol r_J(t),\quad
\boldsymbol r_m(t),\quad
\boldsymbol r_i(\xi,t),\quad
N_i(\xi,t),\quad
E(t),\quad
\Gamma_{[0,T]},
$$

以及每根支路何处绷紧、何处松弛、何时重新受拉。

本闭合模型默认绳与自身、支架、摆球之间没有额外碰撞或摩擦接触，摆球也不接触纸面或其他障碍物。若这些接触实际发生，接触间隙、摩擦律和相应状态必须显式追加；否则“完整运动”只指当前无接触模型合同内的完整运动。

若保留绳质量和内部形状，只有摆球初位置与初速度并不足以构成完整初态。绳的初始形状和内部速度也是状态的一部分；第 13.12 节给出从常见“静止释放”条件构造一致初态的方法。

### 13.2 为什么统一方程不能仍然只有 $\varphi,\theta$

在无质量、不可伸长、全张紧极限中，无质量结点的三力平衡把系统压缩到环面上的两个自由度。但以下任一机制都会恢复被消去的状态：

- 有限结点质量允许下绳方向短时偏离上部 Y 平面；
- 有限绳质量允许绳内速度分布与端点速度不同；
- 轴向柔度允许材料长度与端点距离不同；
- 松弛支路需要自身形状与惯性来决定下一次接合；
- 弯曲边界层需要至少一个曲率自由度。

因此，一对处处光滑的 $\varphi,\theta$ 方程不可能在不丢失状态信息的情况下同时覆盖全张紧、松弛和重新拉直。正确做法是先给出一个全局闭合的有限维母模型，再在相应参数区间内降阶回 $\varphi,\theta$。

### 13.3 每根绳的二次 Ritz 参数化

对每条物理支路 $i\in\{A,B,\ell\}$，取材料坐标 $\xi\in[0,1]$。使用二次 Lagrange 形函数

$$
N_0(\xi)=2\left(\xi-\frac12\right)(\xi-1),
$$

$$
N_1(\xi)=4\xi(1-\xi),
$$

$$
N_2(\xi)=2\xi\left(\xi-\frac12\right).
$$

它们满足

$$
N_a(\xi_b)=\delta_{ab},
\qquad
(\xi_0,\xi_1,\xi_2)=\left(0,\frac12,1\right).
$$

第 $i$ 条绳的中心线近似为

$$
\boxed{
\boldsymbol r_i(\xi,t)
=N_0(\xi)\boldsymbol r_{i0}(t)
+N_1(\xi)\boldsymbol c_i(t)
+N_2(\xi)\boldsymbol r_{i1}(t).
}
\tag{13.2}
$$

其中 $\boldsymbol c_i$ 是该支路唯一保留的内部形状节点。三条支路的端点关系为

$$
(\boldsymbol r_{A0},\boldsymbol r_{A1})=(A,\boldsymbol r_J),
$$

$$
(\boldsymbol r_{B0},\boldsymbol r_{B1})=(B,\boldsymbol r_J),
$$

$$
(\boldsymbol r_{\ell0},\boldsymbol r_{\ell1})=(\boldsymbol r_J,\boldsymbol r_m).
$$

固定支点情况下，最小全局广义坐标为

$$
\boxed{
\boldsymbol q=
\begin{pmatrix}
\boldsymbol c_A\\
\boldsymbol c_B\\
\boldsymbol r_J\\
\boldsymbol c_\ell\\
\boldsymbol r_m
\end{pmatrix}
\in\mathbb R^{15}.
}
\tag{13.3}
$$

这 15 个坐标不是任意网格自由度：每条整绳只保留一个最低非平凡空间形状模态。若频谱没有绳内峰，继续增加节点没有物理收益；若出现内部峰，再按第 13.16 节增加 Ritz 阶数。

对每条支路定义装配矩阵 $\mathsf B_i(\xi)$ 和已知支点项 $\boldsymbol a_i(\xi)$，使

$$
\boldsymbol r_i(\xi,t)
=\mathsf B_i(\xi)\boldsymbol q(t)
+\boldsymbol a_i(\xi).
$$

于是

$$
\boldsymbol r_{i,\xi}
=\mathsf B_{i,\xi}\boldsymbol q
+\boldsymbol a_{i,\xi},
\qquad
\dot{\boldsymbol r}_i
=\mathsf B_i\dot{\boldsymbol q}.
$$

### 13.4 绳质量的解析一致质量矩阵

对均匀支路 $i$，将连续动能投影到式 (13.2)：

$$
T_i
=\frac12M_i\int_0^1
\left|\dot{\boldsymbol r}_i(\xi,t)\right|^2d\xi.
$$

局部一致质量矩阵可解析积分为

$$
\boxed{
\mathsf M_i^{\rm loc}
=\frac{M_i}{30}
\begin{pmatrix}
4&2&-1\\
2&16&2\\
-1&2&4
\end{pmatrix}
\otimes I_3.
}
\tag{13.4}
$$

装配三条支路并加入结点与摆球质量后，按坐标顺序

$$
(\boldsymbol c_A,\boldsymbol c_B,
\boldsymbol r_J,\boldsymbol c_\ell,
\boldsymbol r_m)
$$

得到

$$
\boxed{
\mathsf M=\mathsf M_{\rm scal}\otimes I_3,
}
$$

其中

$$
\mathsf M_{\rm scal}=
\begin{pmatrix}
\frac{8M_A}{15}&0&\frac{M_A}{15}&0&0\\[1mm]
0&\frac{8M_B}{15}&\frac{M_B}{15}&0&0\\[1mm]
\frac{M_A}{15}&\frac{M_B}{15}&
 m_J+\frac{2(M_A+M_B+M_\ell)}{15}&
 \frac{M_\ell}{15}&-\frac{M_\ell}{30}\\[1mm]
0&0&\frac{M_\ell}{15}&\frac{8M_\ell}{15}&\frac{M_\ell}{15}\\[1mm]
0&0&-\frac{M_\ell}{30}&\frac{M_\ell}{15}&
 m+\frac{2M_\ell}{15}
\end{pmatrix}.
\tag{13.5}
$$

因此总动能为

$$
\boxed{
T=\frac12\dot{\boldsymbol q}^{\mathsf T}
\mathsf M\dot{\boldsymbol q}.
}
\tag{13.6}
$$

只要装配后的动态子空间具有正质量，$\mathsf M$ 正定。若人为同时令 $m_J=M_A=M_B=M_\ell=0$，质量矩阵退化；这正是无质量结点理想模型的奇异极限，必须先做约束降维，不能直接在母方程中代零。

### 13.5 重力与浮力

取 $z$ 轴竖直向下。二次形函数的积分为

$$
\int_0^1(N_0,N_1,N_2)d\xi
=\left(\frac16,\frac23,\frac16\right).
$$

故绳的重力势能为

$$
V_{g,i}
=-M_i g\boldsymbol e_z\cdot
\left(
\frac16\boldsymbol r_{i0}
+\frac23\boldsymbol c_i
+\frac16\boldsymbol r_{i1}
\right).
$$

总重力势能为

$$
\boxed{
V_g=
-m_Jg\boldsymbol e_z\cdot\boldsymbol r_J
-mg\boldsymbol e_z\cdot\boldsymbol r_m
+\sum_iV_{g,i}.
}
\tag{13.7}
$$

若摆球体积为 $V_{\rm bob}$，浮力作为外力

$$
\boldsymbol F_{\rm buoy}
=-\rho_aV_{\rm bob}g\boldsymbol e_z
$$

作用在摆球质心。若只研究两模频率比且浮力是共同因子，可按第 10 节量级判据将其删除；母方程允许保留它。

### 13.6 局部伸长率与单边黏弹本构

第 $i$ 条支路的参考弧长为 $L_i^0$。为避免二次中心线在极端折叠时出现零切向除法，定义

$$
\bar L_i^0
=\sqrt{(L_i^0)^2+\varepsilon_t^2},
\qquad
s_{i,\varepsilon}
=\sqrt{\left|\boldsymbol r_{i,\xi}\right|^2
+\varepsilon_t^2}.
$$

正则化局部伸长率为

$$
\boxed{
\lambda_i(\xi,t)
=\frac{s_{i,\varepsilon}}{\bar L_i^0}.
}
\tag{13.8}
$$

直线、无伸长构型仍严格满足 $\lambda_i=1$。定义正则化切向

$$
\widehat{\boldsymbol t}_i
=\frac{\boldsymbol r_{i,\xi}}{s_{i,\varepsilon}},
$$

则

$$
\boxed{
\dot\lambda_i
=\frac{
\widehat{\boldsymbol t}_i\cdot
\dot{\boldsymbol r}_{i,\xi}}
{\bar L_i^0}.
}
\tag{13.9}
$$

在 $\varepsilon_t/L_i^0\ll\epsilon_{\rm req}$ 时，该正则化对目标动力学不可见，只消除非物理的零切向坐标奇点。

为同时满足“只能受拉”和“右端向量场局部 Lipschitz”，定义 $C^1$ 单边激活函数

$$
\mathcal P_\delta(x)=
\begin{cases}
0,&x\le0,\\[1mm]
\dfrac{x^2(2\delta-x)}{\delta^2},&0<x<\delta,\\[2mm]
x,&x\ge\delta.
\end{cases}
\tag{13.10}
$$

其导数为

$$
\mathcal P_\delta'(x)=
\begin{cases}
0,&x\le0,\\[1mm]
\dfrac{4x}{\delta}-\dfrac{3x^2}{\delta^2},&0<x<\delta,\\[2mm]
1,&x\ge\delta.
\end{cases}
$$

因此真正松弛区 $\lambda_i\le1$ 内，弹性项与黏性项均严格为零；在宽度 $\delta_\epsilon$ 的接合带内，张力平滑建立；超过接合带后恢复普通线性黏弹关系。

在低阶 Ritz 截断中，$\lambda_i<1$ 不解释为材料真正承受压缩，而解释为未被当前空间模态解析的细尺度弯折、起皱或松垂。此时中心线是绳形包络，局部轴力仍严格为零。若需要解析松绳的更细折叠形状，应增加 Ritz 阶数，而不是允许负张力。

局部弹性张力与黏性张力候选值为

$$
N_{e,i}
=E_iA_i\,
\mathcal P_{\delta_\epsilon}(\lambda_i-1),
$$

$$
N_{v,i}
=\eta_iA_i\,
\mathcal P_{\delta_\epsilon}'(\lambda_i-1)
\dot\lambda_i.
$$

为禁止快速卸载时出现压应力，最终轴力定义为

$$
\boxed{
N_i(\xi,t)
=\left[N_{e,i}+N_{v,i}\right]_+
\equiv
\max\!\left(0,N_{e,i}+N_{v,i}\right)
\ge0.
}
\tag{13.11}
$$

正部函数虽然在零点不可微，但它是全局 Lipschitz 的，因此不会破坏常微分方程解的唯一性。有限 $\delta_\epsilon$ 描述真实纤维逐步拉直和结扣压紧；有限质量与有限 $EA$ 则把理想瞬时冲量展开为有限宽度张力脉冲。

局部轴力对广义坐标的总作用为

$$
\boxed{
\boldsymbol f_{\rm ax}
=-\sum_{i\in\{A,B,\ell\}}
\frac{L_i^0}{\bar L_i^0}
\int_0^1
N_i(\xi,t)
\mathsf B_{i,\xi}^{\mathsf T}
\widehat{\boldsymbol t}_i
\,d\xi.
}
\tag{13.12}
$$

式 (13.12) 已包含三支路相互耦合，因为两条上支和下支都通过同一个结点坐标 $\boldsymbol r_J$ 装配到 $\boldsymbol q$ 中。它不是三个独立弹簧力的事后叠加，而是统一广义力。

若候选总轴力为正，式 (13.11) 给出 $N_i=N_{e,i}+N_{v,i}$，轴向黏性功率为 $-\eta_iA_i\mathcal P_{\delta_\epsilon}^{\prime}(\lambda_i-1)\dot\lambda_i^2\le0$；若候选总轴力将变负，正部函数把轴力截为零，而此时支路正在卸载，储存弹性能同样下降。因此该本构严格不会由绳内部产生机械能。

### 13.7 轴向储能与静态加载长度

定义

$$
\Phi_\delta(x)
=\int_0^x\mathcal P_\delta(u)\,du.
$$

纯弹性部分的轴向势能为

$$
\boxed{
V_{\rm ax}
=\sum_iE_iA_iL_i^0
\int_0^1
\Phi_{\delta_\epsilon}
(\lambda_i-1)d\xi.
}
\tag{13.13}
$$

当 $\lambda_i-1\ge\delta_\epsilon$ 时，式 (13.13) 与通常的二次轴向能只差一个不影响力的常数。静态伸长不再需要另行塞入有效长度：给定无载长度 $L_i^0$、$EA_i$ 和重力后，工作载荷下的实际几何由平衡方程自动产生。

实验若直接测得工作载荷下的长度，可以反演无载长度或把静态平衡态作为参考；但不能把同一伸长既写进 $L_i^0$ 又写进 $EA_i$，否则会重复计数。

式 (13.13) 的梯度严格给出弹性候选轴力 $N_{e,i}$；实际运动方程以式 (13.11) 截断后的总轴力为准。两者之差属于黏弹耗散与单边卸载广义力，不能再重复写入势能。

### 13.8 弯曲刚度与连接边界层

二次中心线允许非零曲率。定义正则化曲率

$$
\boxed{
\kappa_i(\xi)
=\frac{
\left|\boldsymbol r_{i,\xi}
\times\boldsymbol r_{i,\xi\xi}\right|}
{\left(
\left|\boldsymbol r_{i,\xi}\right|^2
+\varepsilon_\kappa^2
\right)^{3/2}}.
}
\tag{13.14}
$$

弯曲势能取为

$$
\boxed{
V_{\rm bend}
=\frac12\sum_iE_iI_iL_i^0
\int_0^1\kappa_i(\xi)^2d\xi
+V_{\rm bend,end}.
}
\tag{13.15}
$$

$V_{\rm bend,end}$ 描述支点、结扣或摆球连接处的转角弹簧。例如某端期望切向为 $\widehat{\boldsymbol t}_{i,*}$ 时，可取

$$
V_{\rm bend,end}^{(i)}
=\frac12K_{\alpha,i}
\left|
\widehat{\boldsymbol t}_{i,\rm end}
-\widehat{\boldsymbol t}_{i,*}
\right|^2.
$$

若量级分析证明 $C_b\sqrt{EI/T}/L$ 小于预算，可令 $EI_i=K_{\alpha,i}=0$。若不小，则式 (13.15) 直接进入同一方程，而不再把弯曲刚度误当作阻尼。

本节默认连接不传递绕绳轴的力矩，且研究对象是摆球质心运动。在此前提下，扭转与质心平动结构性解耦，故不需要隐藏的扭转变量。若实验连接确实传矩，则必须显式增加摆球姿态和每条支路的扭转 Ritz 坐标；不能在保持当前 15 维状态不变的同时声称包含扭转耦合。

### 13.9 空气阻力、局部损耗与支架运动

摆球空气阻力可写为

$$
\boldsymbol F_{d,b}
=-c_{1b}\dot{\boldsymbol r}_m
-c_{2b}\left|\dot{\boldsymbol r}_m\right|
\dot{\boldsymbol r}_m.
$$

绳的分布式速度为

$$
\boldsymbol v_i(\xi)=\mathsf B_i(\xi)\dot{\boldsymbol q}.
$$

相对局部切向分解为

$$
\boldsymbol v_{\parallel i}
=(\boldsymbol v_i\cdot\widehat{\boldsymbol t}_i)
\widehat{\boldsymbol t}_i,
\qquad
\boldsymbol v_{\perp i}
=\boldsymbol v_i-\boldsymbol v_{\parallel i}.
$$

采用线性—二次各向异性阻力密度

$$
\boldsymbol f_{d,i}
=-c_{\parallel i}\boldsymbol v_{\parallel i}
-c_{\perp i}\boldsymbol v_{\perp i}
-d_{\parallel i}
\left|\boldsymbol v_{\parallel i}\right|
\boldsymbol v_{\parallel i}
-d_{\perp i}
\left|\boldsymbol v_{\perp i}\right|
\boldsymbol v_{\perp i}.
$$

其广义力为

$$
\boxed{
\boldsymbol Q_{d,\rm string}
=\sum_iL_i^0\int_0^1
\mathsf B_i^{\mathsf T}
\boldsymbol f_{d,i}\,d\xi.
}
\tag{13.16}
$$

摆球阻力通过摆球坐标选择矩阵 $\mathsf B_m$ 装配为 $\boldsymbol Q_{d,b}=\mathsf B_m^{\mathsf T}\boldsymbol F_{d,b}$；浮力同理。局部结点摩擦和其他已标定外力统一装配为 $\boldsymbol Q_{\rm loc}$。

若附加质量不可忽略，可把摆球平动质量块替换为

$$
\mathsf M_{m,\rm eff}
=mI_3+\mathsf M_{\rm add},
$$

球形摆球的一阶各向同性近似为 $\mathsf M_{\rm add}=C_a\rho_aV_{\rm bob}I_3$。这属于质量矩阵修正，不应伪装成阻尼。

若实验在地球旋转坐标系中需要保留 Coriolis 力，则摆球、结点和绳质量元分别加入

$$
\boldsymbol f_\Omega
=-2\,dm\,\boldsymbol\Omega_E\times\boldsymbol v
-dm\,\boldsymbol\Omega_E\times
(\boldsymbol\Omega_E\times\boldsymbol r).
$$

绳的对应广义力仍由 $\int\mathsf B_i^{\mathsf T}\boldsymbol f_\Omega$ 装配；离心项也可吸收到有效重力势中。故 Coriolis 不是母模型结构上的缺口，只是在通常桌面参数下由第 10 节预算删除。

若支点并非固定，可把支架坐标 $\boldsymbol q_s$ 追加到 $\boldsymbol q$，令

$$
A=A_0+\mathsf S_A\boldsymbol q_s,
\qquad
B=B_0+\mathsf S_B\boldsymbol q_s,
$$

并增加

$$
T_s=\frac12\dot{\boldsymbol q}_s^{\mathsf T}
\mathsf M_{\rm sup}\dot{\boldsymbol q}_s,
$$

$$
V_{\rm sup}=\frac12\boldsymbol q_s^{\mathsf T}
\mathsf K_{\rm sup}\boldsymbol q_s,
\qquad
\boldsymbol Q_s=-\mathsf C_{\rm sup}\dot{\boldsymbol q}_s.
$$

固定支点模型由 $\boldsymbol q_s=0$ 或 $\mathsf K_{\rm sup}\to\infty$ 恢复。支架自由度是否加入，由第 10 节预算和实测支点运动决定。

#### 13.9.1 有限刚体摆球的可选闭包

若下绳作用线不通过质心或连接刚性传矩，则把摆球姿态 $\mathsf R_b\in SO(3)$ 与角速度 $\boldsymbol\omega_b$ 追加到状态，并令下支端点为

$$
\boldsymbol r_{\ell1}
=\boldsymbol r_m
+\mathsf R_b\boldsymbol\rho_{\rm att},
$$

其中 $\boldsymbol\rho_{\rm att}$ 是质心到连接点的刚体系向量。摆球动能改为

$$
T_b
=\frac12m\left|\dot{\boldsymbol r}_m\right|^2
+\frac12\boldsymbol\omega_b^{\mathsf T}
\mathsf I_b\boldsymbol\omega_b.
$$

姿态和转动满足

$$
\dot{\mathsf R}_b
=\mathsf R_b[\boldsymbol\omega_b]_\times,
$$

$$
\mathsf I_b\dot{\boldsymbol\omega}_b
+\boldsymbol\omega_b\times
(\mathsf I_b\boldsymbol\omega_b)
=\boldsymbol\rho_{\rm att}\times
\mathsf R_b^{\mathsf T}\boldsymbol F_\ell
+\boldsymbol\tau_{\rm air}
+\boldsymbol\tau_{\rm conn}.
$$

基准偏心点连接可取 $\boldsymbol\tau_{\rm conn}=0$，此时绳力作用点偏置已经通过第一项产生完整力矩。若连接自身传递弹性或黏性力矩，$\boldsymbol\tau_{\rm conn}$ 必须作为显式本构函数给出，例如由独立标定的相对转角刚度 $K_R$ 和转动阻尼 $C_R$ 构成，不能只写一个未定义的“附加力矩”。

自由点连接且作用线通过质心时，$\boldsymbol\rho_{\rm att}=0$、$\boldsymbol\tau_{\rm conn}=0$，转动重新与质心平动解耦，可删除姿态状态。这说明有限摆球转动不是无法闭合，而是需要相应的初始姿态、角速度和连接本构；在结构性解耦条件下则应主动降阶。

### 13.10 统一闭合运动方程

把重力、轴向力、弯曲力、空气阻力、浮力和局部耗散装配后，固定支点情况下的统一方程为

$$
\boxed{
\mathsf M\ddot{\boldsymbol q}
=
-\nabla_{\boldsymbol q}V_g
+\boldsymbol f_{\rm ax}
-\nabla_{\boldsymbol q}V_{\rm bend}
+\boldsymbol Q_{d,\rm string}
+\boldsymbol Q_{d,b}
+\boldsymbol Q_{\rm buoy}
+\boldsymbol Q_{\rm loc}.
}
\tag{13.17}
$$

定义 $\boldsymbol v=\dot{\boldsymbol q}$，则等价于显式一阶系统

$$
\boxed{
\frac{d}{dt}
\begin{pmatrix}
\boldsymbol q\\
\boldsymbol v
\end{pmatrix}
=
\begin{pmatrix}
\boldsymbol v\\[1mm]
\mathsf M^{-1}
\boldsymbol F(\boldsymbol q,\boldsymbol v;\boldsymbol p)
\end{pmatrix}.
}
\tag{13.18}
$$

式 (13.18) 就是所要求的统一闭合预测方程。它具有固定状态定义、固定参数定义和固定输出映射；所有耦合都通过装配矩阵、局部伸长率、曲率和同一结点坐标显式进入。

与第 7 节的理想互补 DAE 不同，式 (13.18) 不需要在张力为零时切换方程：

- 当某段 $\lambda_i\le1$ 时，式 (13.11) 自动给出 $N_i=0$；
- 当松弛段再次被拉长时，$N_i$ 在接合带内连续恢复；
- 有限质量与有限刚度把理想冲量展开为有限宽度的张力脉冲；
- 内部形状节点在松弛阶段仍有明确惯性和重力，因此不会出现无质量结点模型的欠定。

因此整个观察窗只使用一套方程。“全张紧”“单支”“下绳松弛”不再是不同方程的人工标签，而是同一状态解中不同的张力活动区域。

### 13.11 唯一性与适定性

设以下条件成立：

1. 装配后的 $\mathsf M$ 正定；
2. $\delta_\epsilon>0$、$\varepsilon_t>0$、$\varepsilon_\kappa>0$；
3. 所有材料与阻尼参数有限且非负；
4. 外部支点运动与外力在时间上分段 $C^1$；
5. 初始能量有限。

则 $\mathcal P_\delta$ 及其导数为局部 Lipschitz，正则化伸长率、曲率和阻力项也局部 Lipschitz，故式 (13.18) 的右端对状态局部 Lipschitz。由 Picard–Lindelöf 定理，对任意完整初态 $\boldsymbol X_0$ 存在唯一局部解。

对固定支点、有限刚度和有限初始能量，轴向能在大伸长下增长，重力和阻力不会造成有限时间状态发散；因此解可继续到任意预先给定的有限观察时间 $T$。于是

$$
\boxed{
(\boldsymbol p,\boldsymbol X_0)
\longmapsto
\boldsymbol X(t),
\qquad0\le t\le T,
}
\tag{13.19}
$$

在模型合同内是单值映射。

若把 $\delta_\epsilon$ 直接置零，同时令 $EA\to\infty$，模型会退化为带冲量的非光滑互补系统；多约束同时接合、擦触和零质量极限可能重新出现解选择问题。故有限接合宽度、有限惯性和有限刚度不是纯数值技巧，而是把真实装置的微观接合过程压缩成确定性低阶理论所必需的闭包参数。

### 13.12 初始条件如何给足

完整初态为

$$
\boldsymbol X_0=
(\boldsymbol c_{A0},\boldsymbol c_{B0},
\boldsymbol r_{J0},\boldsymbol c_{\ell0},
\boldsymbol r_{m0};
\dot{\boldsymbol c}_{A0},\dot{\boldsymbol c}_{B0},
\dot{\boldsymbol r}_{J0},\dot{\boldsymbol c}_{\ell0},
\dot{\boldsymbol r}_{m0}).
$$

有三种合法给法。

#### 13.12.1 直接测量完整几何

双相机或多点标记测得三条绳的初始中心线，用二次最小二乘拟合得到三个内部节点；速度由相邻帧拟合。此时不需要额外初始化假设。

#### 13.12.2 静止释放的准静态初始化

若实验在某个宏观位置保持足够久再静止释放，可固定实测的 $\boldsymbol r_{J0},\boldsymbol r_{m0}$，令所有未规定内部坐标取总势能极小值

$$
\boxed{
\boldsymbol q_{\rm free,0}
=
\operatorname*{arg\,min}_{\boldsymbol q_{\rm free}}
\left(V_g+V_{\rm ax}+V_{\rm bend}+V_{\rm sup}\right).
}
\tag{13.20}
$$

并取初速度为零。若保持装置还施加已知导向力，应把导向势能或约束一并加入式 (13.20)。

#### 13.12.3 只给端点速度时的最小动能提升

若已知结点和摆球初速度，但没有内部节点速度，可取

$$
\boxed{
\dot{\boldsymbol q}_{\rm int,0}
=
\operatorname*{arg\,min}_{\dot{\boldsymbol q}_{\rm int}}
\frac12\dot{\boldsymbol q}^{\mathsf T}
\mathsf M\dot{\boldsymbol q}
}
\tag{13.21}
$$

并施加已知端点速度约束。该规则等价于不人为注入未观测的绳内振动。

若式 (13.20) 存在多个局部极小值，说明宏观端点条件不足以唯一确定松绳形状；此时必须提供实际初始形状或明确选择哪一个极小值。理论不能把缺失的初态伪装成“参数误差”。

### 13.13 完整输出映射

解出 $\boldsymbol X(t)$ 后，以下输出全部由解析映射得到。

#### 摆球、结点与绳形

$$
\boldsymbol r_J(t),
\qquad
\boldsymbol r_m(t),
\qquad
\boldsymbol r_i(\xi,t)
=\mathsf B_i(\xi)\boldsymbol q(t)
+\boldsymbol a_i(\xi).
$$

#### 局部张力与松弛区

$$
N_i(\xi,t)
$$

由式 (13.11) 给出。定义

$$
\mathcal A_i(t)
=\{\xi\in[0,1]:N_i(\xi,t)>N_{\rm tol}\}.
$$

它给出每条支路当时的实际受拉区，而不是只用一个支路总张力符号。

#### 能量与功率

纯弹性、无空气阻力和无局部耗散时，机械能为

$$
E=T+V_g+V_{\rm ax}+V_{\rm bend}+V_{\rm sup}.
$$

含黏弹与阻力时，功率平衡由

$$
\dot E
=\dot{\boldsymbol q}^{\mathsf T}
\boldsymbol Q_{\rm noncons}
$$

直接检查。若数值计算得到持续正的内部耗散功率，应检查本构符号、积分精度或参数识别。

#### 环面模态坐标

在三支路近似全张紧、结点接近上部交圆时，可继续使用

$$
\varphi
=\operatorname{atan2}
\left(x-x_C,\sqrt{y^2+z^2}-h\right),
$$

$$
\theta=\operatorname{atan2}(y,z).
$$

但此时 $\varphi,\theta$ 是从完整状态提取的慢变量，而不是全局基本坐标。松弛或明显非共面时，应直接报告笛卡尔/Ritz 状态，不应强行把轨迹投影回环面。

#### 观测量

质心顶视轨迹为

$$
\Gamma_{[0,T]}
=\{(x_m(t),y_m(t)):0\le t\le T\}.
$$

若相机、灯点、笔尖或喷口不位于质心，必须在式 (13.18) 之后附加对应观测映射；观测映射不会反过来改变动力学，除非记录器与装置发生真实接触。

### 13.14 环面主模型作为严格奇异极限

考虑以下极限：

$$
M_A,M_B,M_\ell,m_J\to0,
$$

$$
EA_i\to\infty,
\qquad
EI_i\to0,
$$

$$
\delta_\epsilon,\varepsilon_t,\varepsilon_\kappa\to0,
$$

并限定在三支路始终受拉的解支上。此时：

1. 每条支路的二次中心线退化为直线；
2. 三支路长度固定为 $s_A=L_A^0$、$s_B=L_B^0$、$\ell=L_\ell^0$；
3. 结点惯性消失，结点满足瞬时三力平衡；
4. 三力平衡重新强制 $A,B,J$ 与摆球共面；
5. 结点位于两上支球面的交圆上。

在该奇异约束流形上，用 $\varphi,\theta$ 参数化后，式 (13.17) 约化为

$$
\boxed{
\ell\ddot\varphi
+R\sin\varphi\,\dot\theta^2
+g\sin\varphi\cos\theta=0,
}
$$

$$
\boxed{
R\ddot\theta
-2\ell\sin\varphi\,
\dot\varphi\dot\theta
+g\sin\theta=0,
\qquad
R=h+\ell\cos\varphi.
}
$$

所以第 3 节的环面方程不是被新模型替代，而是统一母方程在低质量、高刚度、全张紧慢流形上的精确极限。两者之间具有明确的渐近关系。

### 13.15 从母方程到修正后的低维慢流形

对多数桌面装置，15 维母方程中的绳内模态频率高于两主摆频。此时可把广义坐标分为

$$
\boldsymbol q
=\begin{pmatrix}
\boldsymbol Q\\
\boldsymbol z
\end{pmatrix},
$$

其中 $\boldsymbol Q$ 表示两主慢变量，$\boldsymbol z$ 表示结点相对运动、绳形和轴向内部变量。在线性化平衡点附近，方程写成

$$
\begin{pmatrix}
M_{QQ}&M_{Qz}\\
M_{zQ}&M_{zz}
\end{pmatrix}
\begin{pmatrix}
\ddot Q\\
\ddot z
\end{pmatrix}
+
\begin{pmatrix}
K_{QQ}&K_{Qz}\\
K_{zQ}&K_{zz}
\end{pmatrix}
\begin{pmatrix}
Q\\z
\end{pmatrix}
=0.
$$

频率域中的精确动态凝聚为

$$
\boxed{
\mathsf K_{\rm dyn}(\omega)
=K_{QQ}-\omega^2M_{QQ}
-
(K_{Qz}-\omega^2M_{Qz})
(K_{zz}-\omega^2M_{zz})^{-1}
(K_{zQ}-\omega^2M_{zQ}).
}
\tag{13.22}
$$

主频由

$$
\det\mathsf K_{\rm dyn}(\omega)=0
$$

确定。式 (13.22) 写的是保守线性化；若保留线性耗散，应把每个 $K_{ab}-\omega^2M_{ab}$ 替换为 $K_{ab}+i\omega C_{ab}-\omega^2M_{ab}$。

若 $\omega$ 远低于内部频率，可取准静态凝聚

$$
\boxed{
z\simeq-K_{zz}^{-1}K_{zQ}Q,
}
$$

$$
\boxed{
K_{\rm eff}
=K_{QQ}-K_{Qz}K_{zz}^{-1}K_{zQ}.
}
\tag{13.23}
$$

式 (13.23) 说明上支轴向柔度为什么表现为快模的附加顺应性；式 (13.22) 则说明靠近绳内模态时为什么不能只改一个有效长度。

在非线性区，定义内部变量的不变慢流形

$$
\boldsymbol z
=\boldsymbol z_*
(\boldsymbol Q,\dot{\boldsymbol Q};\boldsymbol p),
$$

有耗散时该流形可成为吸引慢流形。代回母方程得到

$$
\boxed{
\mathsf M_{\rm eff}(\boldsymbol Q)
\ddot{\boldsymbol Q}
+\boldsymbol f_{\rm geo}
(\boldsymbol Q,\dot{\boldsymbol Q})
+\boldsymbol f_{\rm eff}
(\boldsymbol Q,\dot{\boldsymbol Q};\boldsymbol p)
=0.
}
\tag{13.24}
$$

原文的结点质量、绳质量、上支顺应性和有限振幅频移公式，均应理解为式 (13.24) 在相应小参数下的一阶展开，而不是彼此独立的最终运动方程。

### 13.16 Ritz 阶数如何选择

每条绳一个内部节点是最低可描述曲率、松弛形状和最低内部模态的闭合截断。是否需要更高阶，必须由可观测证据决定。

至少检查：

1. 目标摆频与第一未保留绳内频率之比；
2. 频谱中是否出现当前 15 维模型无法解释的稳定内部峰；
3. 增加一个 Ritz 阶次后，目标轨迹、主频、张力峰和接合时间是否在误差预算内收敛；
4. 新增模态参数是否能独立测量或由多工况共同辨识。

若第 $n$ 与第 $n+1$ 阶模型对目标观测量 $Y$ 满足

$$
\boxed{
\frac{\left\|Y_{n+1}-Y_n\right\|}
{\left\|Y_n\right\|+Y_*}
<\epsilon_{\rm req},
}
\tag{13.25}
$$

则可在目标精度下停止增加空间模态。这里 $Y_*$ 是防止零量归一化发散的预先固定尺度。

因此，“统一闭合”并不意味着声称一个二次模态能精确覆盖任意高频冲击；它意味着对选定截断，方程、参数、初态和输出全部闭合，并且截断误差有可检验的收敛判据。

### 13.17 参数输入表

| 参数组 | 必需输入 | 进入方程的位置 | 推荐测量方式 |
|---|---|---|---|
| 固定几何 | $A,B$ | 支路端点与装配矩阵 | 三维坐标测量 |
| 无载长度 | $L_A^0,L_B^0,L_\ell^0$ | 局部伸长率 | 小预载标定或反演 |
| 集中质量 | $m,m_J$ | 质量矩阵、重力 | 电子天平 |
| 绳质量 | $M_A,M_B,M_\ell$ | 一致质量矩阵、重力 | 分段称量 |
| 轴向本构 | $EA_i,\eta_iA_i$ | 式 (13.11)–(13.13) | 单轴加载—卸载曲线 |
| 弯曲本构 | $EI_i,K_{\alpha,i}$ | 式 (13.15) | 曲率/悬臂或纯模标定 |
| 空气阻力 | $c,d$ 系数 | 式 (13.16) | 多振幅自由衰减 |
| 浮力 | $\rho_a,V_{\rm bob}$ | 外力 | 尺寸与环境测量 |
| 有限刚体摆球（可选） | $\mathsf I_b,\boldsymbol\rho_{\rm att},K_R,C_R$ | 第 13.9.1 节姿态方程 | 尺寸、转动惯量与连接标定 |
| 接合与几何正则化 | $\delta_\epsilon,\varepsilon_t,\varepsilon_\kappa$ | 单边本构与几何正则化 | 材料拉直曲线与阶次/尺度收敛 |
| 初始状态 | $\boldsymbol q_0,\dot{\boldsymbol q}_0$；若启用刚体扩展还需 $\mathsf R_{b0},\boldsymbol\omega_{b0}$ | 式 (13.18)及第 13.9.1 节 | 多点视频或式 (13.20)–(13.21) |

任何未测参数若只从一条目标轨迹自由拟合，都会破坏“从独立输入出发预测”的要求。无法独立分离的参数应报告为可辨识组合，并用未见几何或未见振幅验证。

### 13.18 理论使用流程

统一预测流程应固定为：

1. 测量 $A,B,L_i^0,M_i,m_J,m,EA_i,\eta_iA_i$，按预算决定是否保留 $EI_i$、支架与空气阻力；
2. 由式 (13.20) 或实测中心线构造完整 $\boldsymbol q_0$；
3. 由式 (13.21) 或视频构造完整 $\dot{\boldsymbol q}_0$；
4. 用式 (13.4)–(13.16)装配 $\mathsf M$ 与全部广义力；
5. 唯一积分式 (13.18)，不在张力过零后临时改写物理规则；
6. 从式 (13.11)和第 13.13 节映射输出绳形、张力、轨迹、频率、漂移和能量；
7. 用纯模、环面极限、能量功率和平衡几何做无拟合验证；
8. 只有在式 (13.25)不收敛或出现未解释内部峰时才增加 Ritz 阶数。

### 13.19 可以声称与不能声称的内容

在上述模型合同下，可以严格声称：

> 给定全部模型参数和完整初始状态后，式 (13.18) 在任意有限观察窗内唯一决定摆球、结点、三条绳最低形状模态、局部张力、松弛与重新受拉过程，以及由它们导出的全部观测量。

不能无条件声称：

- 一个内部节点能够解析任意高频绳波和尖锐冲击；
- 只给摆球初位置就足以确定带质量松绳的完整初态；
- 自由点连接模型已经包含刚性偏心连接的摆球姿态和扭转；
- 未经标定的经验阻尼可以替代 $EA,EI$ 等保守结构参数；
- 在同时取不可伸长、零接合宽度和零质量奇异极限后，仍声称理想冲量系统自动具有唯一解；
- 在没有追加接触律时预测绳—绳、绳—支架或摆球—纸面的碰撞。

这些不是理论失败，而是模型状态、参数和适用域必须明确。只要目标精度、Ritz 阶数和连接拓扑被固定，式 (13.18) 已经完成从“参数与初态”到“完整运动”的数学闭包。

---

## 14. 现有 Python 基准程序及其与闭合理论的关系

下面程序保持为第 3–6 节理想全张紧环面模型的基准验证器，**不是**第 13 节统一闭合母方程的实现。它适合检验环面极限、有限振幅轨迹、三根总张力和量级预算；一旦任一张力降到零便停止，以避免把柔绳受压的数学解误当成物理解。

它实现：

- 不等长上支几何；
- 精确全张紧环面方程；
- 可选低阶模态阻尼；
- 三根瞬时张力；
- 首次失张事件停止；
- 能量检查；
- 可选的轨迹、角度与张力绘图（运行时加 `--plot`）；
- 长期闭合精度、有限振幅、质量和上支顺应性的量级预算。

程序故意不自动继续模拟换支和下绳松弛。全观察窗的确定性闭包由第 13 节理论给出；若未来实现该母模型，应另建求解器，而不应把下列 M1 基准程序误标为统一模型。

```python
"""Baseline simulator and order-of-magnitude budget for a fixed-knot Y pendulum.

Model validity:
- two fixed, equal-height supports;
- two separately fixed upper-string material lengths;
- massless junction and strings;
- inextensible strings;
- all three tensions positive.

The integrator stops at the first loss-of-tension event. Continuing after that
requires a hybrid single-support / unilateral-constraint model.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.integrate import solve_ivp


@dataclass(frozen=True)
class Params:
    d: float
    s_a: float
    s_b: float
    ell: float
    m: float
    g: float = 9.81
    gamma_phi: float = 0.0     # fast-mode phenomenological decay rate [s^-1]
    gamma_theta: float = 0.0   # slow-mode phenomenological decay rate [s^-1]

    def validate(self) -> None:
        values = (self.d, self.s_a, self.s_b, self.ell, self.m, self.g)
        if min(values) <= 0.0:
            raise ValueError("All lengths, mass, and g must be positive.")
        if not abs(self.s_a - self.s_b) < self.d < self.s_a + self.s_b:
            raise ValueError("Upper-string geometry violates the strict triangle inequality.")


@dataclass(frozen=True)
class Geometry:
    x_c: float
    a_a: float
    a_b: float
    h: float
    H: float


def geometry(p: Params) -> Geometry:
    p.validate()
    x_c = (p.s_a**2 - p.s_b**2) / (2.0 * p.d)
    a_a = x_c + 0.5 * p.d
    a_b = 0.5 * p.d - x_c
    h2_a = p.s_a**2 - a_a**2
    h2_b = p.s_b**2 - a_b**2
    if h2_a <= 0.0 or h2_b <= 0.0:
        raise ValueError("The junction-circle radius is not real and positive.")
    if not np.isclose(h2_a, h2_b, rtol=1e-10, atol=1e-12):
        raise RuntimeError("Inconsistent upper geometry.")
    h = float(np.sqrt(0.5 * (h2_a + h2_b)))
    if a_a <= 0.0 or a_b <= 0.0:
        raise ValueError("The hanging equilibrium cannot have both upper tensions positive.")
    return Geometry(x_c=x_c, a_a=a_a, a_b=a_b, h=h, H=h + p.ell)


def rhs(_t: float, y: np.ndarray, p: Params) -> np.ndarray:
    """Exact all-taut torus equations with optional modal damping.

    State y = [phi, theta, phi_dot, theta_dot].
    phi: fast angle along the support axis.
    theta: slow rotation of the Y plane about the support axis.
    """
    phi, theta, phi_dot, theta_dot = map(float, y)
    geom = geometry(p)
    R = geom.h + p.ell * np.cos(phi)
    if R <= 0.0:
        raise FloatingPointError("R <= 0: torus chart outside the physical lower branch.")

    phi_ddot = (
        -(R / p.ell) * np.sin(phi) * theta_dot**2
        -(p.g / p.ell) * np.sin(phi) * np.cos(theta)
        -2.0 * p.gamma_phi * phi_dot
    )
    theta_ddot = (
        (2.0 * p.ell * np.sin(phi) / R) * phi_dot * theta_dot
        -(p.g / R) * np.sin(theta)
        -2.0 * p.gamma_theta * theta_dot
    )
    return np.array([phi_dot, theta_dot, phi_ddot, theta_ddot], dtype=float)


def coordinates(y: np.ndarray, p: Params) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map scalar or vectorized state arrays to bob Cartesian coordinates."""
    phi = np.asarray(y[0])
    theta = np.asarray(y[1])
    geom = geometry(p)
    R = geom.h + p.ell * np.cos(phi)
    x = geom.x_c + p.ell * np.sin(phi)
    yy = R * np.sin(theta)
    z = R * np.cos(theta)  # positive downward
    return x, yy, z


def tensions(y: np.ndarray, p: Params) -> tuple[float, float, float]:
    """Return (T_lower, T_A, T_B) in the all-taut massless-junction model."""
    phi, theta, phi_dot, theta_dot = map(float, y)
    geom = geometry(p)
    R = geom.h + p.ell * np.cos(phi)

    t_lower = p.m * (
        p.ell * phi_dot**2
        + R * np.cos(phi) * theta_dot**2
        + p.g * np.cos(phi) * np.cos(theta)
    )
    t_a = (p.s_a * t_lower / p.d) * (
        np.sin(phi) + (geom.a_b / geom.h) * np.cos(phi)
    )
    t_b = (p.s_b * t_lower / p.d) * (
        (geom.a_a / geom.h) * np.cos(phi) - np.sin(phi)
    )
    return float(t_lower), float(t_a), float(t_b)


def energy(y: np.ndarray, p: Params) -> np.ndarray:
    """Mechanical energy relative to the lowest equilibrium; vectorized over columns."""
    phi = np.asarray(y[0])
    theta = np.asarray(y[1])
    phi_dot = np.asarray(y[2])
    theta_dot = np.asarray(y[3])
    geom = geometry(p)
    R = geom.h + p.ell * np.cos(phi)
    kinetic = 0.5 * p.m * (p.ell**2 * phi_dot**2 + R**2 * theta_dot**2)
    potential = p.m * p.g * (geom.H - R * np.cos(theta))
    return kinetic + potential


def _event_factory(index: int, p: Params) -> Callable[[float, np.ndarray], float]:
    def event(_t: float, y: np.ndarray) -> float:
        return tensions(y, p)[index]

    event.terminal = True
    event.direction = -1.0
    return event


def integrate(
    p: Params,
    y0: np.ndarray,
    t_end: float,
    *,
    max_step: float = 0.005,
):
    """Integrate until t_end or the first tension reaches zero from above."""
    y0 = np.asarray(y0, dtype=float)
    if y0.shape != (4,):
        raise ValueError("y0 must have shape (4,): [phi, theta, phi_dot, theta_dot].")
    initial_tensions = tensions(y0, p)
    if min(initial_tensions) <= 0.0:
        raise ValueError(f"Initial state is outside the all-taut regime: {initial_tensions}")

    events = [_event_factory(i, p) for i in range(3)]
    return solve_ivp(
        fun=lambda t, y: rhs(t, y, p),
        t_span=(0.0, float(t_end)),
        y0=y0,
        method="DOP853",
        rtol=1e-10,
        atol=1e-12,
        max_step=max_step,
        events=events,
        dense_output=True,
    )


def plot_solution(sol, p: Params) -> None:
    """Plot trajectory, generalized coordinates, and tensions.

    Matplotlib is imported lazily so the numerical module remains usable in
    headless environments. Run this file with ``--plot`` to display figures.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("Matplotlib is required only for plotting.") from exc

    x, yy, _z = coordinates(sol.y, p)
    geom = geometry(p)
    tension_history = np.array([tensions(sol.y[:, i], p) for i in range(sol.y.shape[1])])

    plt.figure()
    plt.plot(x - geom.x_c, yy)
    plt.xlabel(r"$X=x-x_C$ [m]")
    plt.ylabel(r"$Y$ [m]")
    plt.axis("equal")
    plt.tight_layout()

    plt.figure()
    plt.plot(sol.t, sol.y[0], label=r"$\varphi$")
    plt.plot(sol.t, sol.y[1], label=r"$\theta$")
    plt.xlabel("time [s]")
    plt.ylabel("angle [rad]")
    plt.legend()
    plt.tight_layout()

    plt.figure()
    plt.plot(sol.t, tension_history[:, 0], label=r"$T_\ell$")
    plt.plot(sol.t, tension_history[:, 1], label=r"$T_A$")
    plt.plot(sol.t, tension_history[:, 2], label=r"$T_B$")
    plt.xlabel("time [s]")
    plt.ylabel("tension [N]")
    plt.legend()
    plt.tight_layout()
    plt.show()


def symmetric_design(ell: float, d: float, p_num: int, q_den: int) -> tuple[float, float]:
    """Return (h, upper-string length s) for target omega_parallel:omega_perp."""
    if min(ell, d) <= 0.0 or p_num <= q_den or q_den <= 0:
        raise ValueError("Require ell,d>0 and p_num/q_den>1.")
    h = ell * ((p_num / q_den) ** 2 - 1.0)
    s = float(np.hypot(h, 0.5 * d))
    return float(h), s


def closure_precision(p_num: int, n_slow: int, phase_tolerance: float) -> float:
    """Allowed relative frequency-ratio error for a p:q target after n_slow periods."""
    if p_num <= 0 or n_slow <= 0 or phase_tolerance <= 0.0:
        raise ValueError("Inputs must be positive.")
    return phase_tolerance / (2.0 * np.pi * p_num * n_slow)


def finite_amplitude_ratio_shift(ell: float, h: float, a_phi: float, a_theta: float) -> float:
    """Leading relative shift (rho_eff-rho_0)/rho_0, away from strong 1:1 resonance."""
    H = ell + h
    return -((1.0 / 16.0) + ell / (8.0 * H)) * a_phi**2 + (3.0 / 16.0) * a_theta**2


def mass_ratio_shift(
    ell: float,
    h: float,
    bob_mass: float,
    junction_mass: float,
    lower_string_mass: float,
    upper_string_total_mass: float,
) -> float:
    """First-order Rayleigh estimate of the relative frequency-ratio shift."""
    if min(ell, h, bob_mass) <= 0.0:
        raise ValueError("ell, h, and bob_mass must be positive.")
    H = ell + h
    x = ell / H
    y = h / H
    return (
        -(junction_mass / bob_mass) * x * y / 2.0
        +(lower_string_mass / bob_mass) * (1.0 / 12.0 - x / 4.0 + x**2 / 6.0)
        -(upper_string_total_mass / bob_mass) * (y / 4.0 - y**2 / 6.0)
    )


def upper_compliance_shift_symmetric(p: Params, ea_upper: float) -> tuple[float, float, float]:
    """Return (K_x, compliance_length, relative fast-frequency shift).

    ea_upper is EA for each upper segment [N]. The estimate assumes quasi-static
    axial response, loaded geometry, inextensible lower string, and negligible
    string/junction inertia.
    """
    if ea_upper <= 0.0:
        raise ValueError("ea_upper must be positive.")
    geom = geometry(p)
    if not np.isclose(p.s_a, p.s_b) or not np.isclose(geom.a_a, geom.a_b):
        raise ValueError("This helper is restricted to symmetric upper geometry.")
    s = p.s_a
    a = geom.a_a
    t_u0 = p.m * p.g * s / (2.0 * geom.h)
    k_x = 2.0 * (ea_upper * a**2 + t_u0 * geom.h**2) / s**3
    ell_c = p.m * p.g / k_x
    relative_shift = np.sqrt(p.ell / (p.ell + ell_c)) - 1.0
    return float(k_x), float(ell_c), float(relative_shift)


if __name__ == "__main__":
    ell = 0.300
    d = 0.300
    h, s = symmetric_design(ell=ell, d=d, p_num=3, q_den=2)
    params = Params(d=d, s_a=s, s_b=s, ell=ell, m=0.200)
    geom = geometry(params)

    omega_parallel = np.sqrt(params.g / params.ell)
    omega_perp = np.sqrt(params.g / geom.H)
    print(f"h={geom.h:.6f} m, s={s:.6f} m, rho={omega_parallel / omega_perp:.9f}")
    print(f"all-taut fast-angle band: ({-np.arctan(geom.a_b/geom.h):.4f}, "
          f"{np.arctan(geom.a_a/geom.h):.4f}) rad")

    y0 = np.array([np.deg2rad(8.0), np.deg2rad(5.0), 0.0, 0.0])
    sol = integrate(params, y0, t_end=20.0)
    e = energy(sol.y, params)
    scale = max(abs(float(e[0])), params.m * params.g * params.ell)
    drift = float(np.max(np.abs(e - e[0])) / scale)
    print(f"relative energy drift={drift:.3e}")

    event_names = ("lower", "upper A", "upper B")
    for name, times in zip(event_names, sol.t_events):
        if len(times):
            print(f"integration stopped: {name} tension reached zero at t={times[0]:.6f} s")

    eps_req = closure_precision(p_num=3, n_slow=30, phase_tolerance=0.20)
    amp_shift = finite_amplitude_ratio_shift(ell, h, 0.150, 0.100)
    mass_shift = mass_ratio_shift(ell, h, 0.200, 0.00030, 0.00025, 0.00060)
    k_x, ell_c, elastic_shift = upper_compliance_shift_symmetric(params, ea_upper=10_000.0)
    print(f"closure relative-ratio budget={eps_req:.3e}")
    print(f"finite-amplitude ratio shift={amp_shift:.3e}")
    print(f"junction/string-mass ratio shift={mass_shift:.3e}")
    print(f"K_x={k_x:.3e} N/m, ell_c={ell_c*1e3:.3f} mm, "
          f"elastic ratio shift~{elastic_shift:.3e}")

    import sys
    if "--plot" in sys.argv:
        plot_solution(sol, params)
```

---

## 15. 最终理论结构、预测含义与停止增加复杂度的准则

### 15.1 两个层次必须同时保留

完善后的理论包含两个互相一致、用途不同的动力学层次。

第一层是第 13 节的全局闭合母模型：

$$
\boxed{
\dot{\boldsymbol X}
=\boldsymbol F(\boldsymbol X;\boldsymbol p),
\qquad
\boldsymbol X=(\boldsymbol q,\dot{\boldsymbol q}).
}
$$

它以三条绳的二次 Ritz 中心线、有限结点/绳质量、有限轴向刚度、单边受拉本构和必要的弯曲/耗散项为基础。在这一层上，松弛和重新受拉仍由同一方程决定，因而完成整个观察窗的数学闭包。

第二层是全张紧、低质量、高刚度慢流形上的环面模型：

$$
\boxed{
\ell\ddot\varphi
+R\sin\varphi\,\dot\theta^2
+g\sin\varphi\cos\theta=0,
}
$$

$$
\boxed{
R\ddot\theta
-2\ell\sin\varphi\,
\dot\varphi\dot\theta
+g\sin\theta=0,
\qquad
R=h+\ell\cos\varphi.
}
$$

它提供最清楚的几何解释、主频设计律、有限振幅频移和 Lissajous 相位结构。它不是全局模型的竞争者，而是全局模型在明确极限下的解析降阶。

因此正确的理论关系是

$$
\boxed{
\text{全局 Ritz 单边柔索母模型}
\xrightarrow[\text{全张紧、高刚度、轻绳/轻结点}]
{\text{奇异降阶}}
\text{环面二自由度模型}.
}
$$

### 15.2 最终的参数—初态—运动映射

给定参数

$$
\boldsymbol p
=(A,B,L_i^0,M_i,m_J,m,EA_i,\eta_iA_i,EI_i,
\text{阻力与支架参数},\text{正则化参数})
$$

以及完整初态

$$
\boldsymbol X_0
=(\boldsymbol q_0,\dot{\boldsymbol q}_0),
$$

统一理论唯一产生

$$
\boldsymbol X(t),
\qquad0\le t\le T.
$$

由此再唯一得到

$$
\boxed{
\begin{aligned}
&\text{摆球与结点位置、速度、加速度},\\
&\text{三条绳的低阶中心线形状},\\
&\text{局部伸长率与局部张力},\\
&\text{松弛区、重新受拉时刻与张力脉冲},\\
&\text{能量与耗散功率},\\
&\text{主频、频率比、共振相位与漂移},\\
&\text{质心轨迹及附加观测映射}.
\end{aligned}
}
$$

这就是“给定参数与初始条件后，数学上唯一决定整个运动”的严格含义。它不表示只给几何尺寸而不给初态也能确定轨迹；也不表示在保留绳内模态时只给摆球初位置就足够。

### 15.3 原有各项修正现在处于什么位置

原文各部分不再是互相并列的最终模型，而是统一母方程的不同投影或渐近展开：

- 环面几何、有限振幅耦合：母方程在全张紧慢流形上的非线性主项；
- 结点质量：质量矩阵中结点自由度的直接贡献；
- 绳质量：二次 Ritz 一致质量矩阵的贡献；
- 上支轴向柔度：单边轴向储能与动态凝聚后的等效顺应性；
- 弯曲刚度：曲率势能和端点转角势能；
- 阻尼：轴向黏弹本构、分布式空气阻力和局部耗散广义力；
- 松弛与重拉直：单边轴力的自动激活和有限惯性—有限刚度接合过程；
- 支架运动：把支架坐标追加到同一广义坐标后得到的扩展系统；
- 频率与相位预算：对完整解输出的低维诊断，而不是替代运动方程的补丁。

因此理论结构从原来的

$$
\text{理想主方程}
+\text{多个事后修正公式}
$$

变为

$$
\boxed{
\text{一个全局闭合母方程}
+\text{若干可验证的解析降阶与渐近公式}.
}
$$

### 15.4 普通桌面实验应使用哪一层

对全观察窗均具有明显正张力裕量、绳内峰不可见、接合事件不存在的实验，应优先使用环面模型及其经过母方程推导的低阶修正。这样计算量小、参数少、物理解释最强。

若出现以下任一证据，则必须回到第 13 节母模型：

1. 任一上支或下支张力接近零；
2. 结点出现可见的非共面相对运动；
3. 频谱出现稳定的第三峰或绳内峰；
4. 轴向伸长或支架运动超过长期相位预算；
5. 重拉直张力脉冲对后续轨迹有可见影响；
6. 环面残差具有超过测量误差的结构性偏离。

不能因为母模型更复杂，就默认它在所有工况中更值得使用。若环面慢模型已经在目标精度内通过盲验证，额外自由度只会增加参数退化。反过来，当张力过零或内部峰已经出现时，继续用修正后的二自由度模型也不是“简洁”，而是状态空间不完整。

### 15.5 停止增加复杂度的准则

理论复杂度停止条件应同时满足：

1. 当前 Ritz 阶数的输出对加一阶模型已经按式 (13.25) 收敛；
2. 所有保留参数可独立测量或通过多工况共同辨识；
3. 目标频率、轨迹、张力和事件时刻均在预先规定的不确定度内；
4. 残差中不存在新增机制特有的频率、振幅、质量或空间结构；
5. 未见初态和未见几何上的预测没有因新增自由度而恶化。

高阶模型只有在改善外推预测时才构成理论进步。只改善同一条训练轨迹的拟合，不能证明新增机制真实存在。

### 15.6 最终回答

对固定结 Y-Pendulum，可以建立一套真正闭合的统一预测理论。其最终形式不是一对包含所有现实因素的万能角方程，而是第 13 节的有限维 Ritz 单边柔索系统：

$$
\boxed{
\mathsf M\ddot{\boldsymbol q}
=\boldsymbol F(\boldsymbol q,
\dot{\boldsymbol q};\boldsymbol p).
}
$$

有限质量和有限刚度使松弛、重拉直和内部形状都有确定的状态演化；单边黏弹本构保证绳不承受压力；二次 Ritz 投影把连续柔索压缩为固定的低维状态；有限正则化使右端局部 Lipschitz。于是给定完整参数与完整初态后，模型在无额外接触的合同内，于任意有限观察窗中唯一决定整个运动。

环面二自由度理论仍然是最重要的解析核心，因为它揭示两主曲率、频率比、Lissajous 闭合和有限振幅耦合；但它现在被严格定位为统一母方程的慢流形极限，而不再承担超出自身状态空间的松绳与冲击预测。

这完成了从

$$
\text{“分析各个效应有多大”}
$$

到

$$
\boxed{
\text{“由全部参数与初态唯一产生完整运动”}
}
$$

的理论升级。

---

# 附录 A：新增低阶量级公式的推导

本附录中的上支差动顺应性和一阶质量预算，是在两份基准文档所给主模型与 Rayleigh 框架上进一步整理得到的低阶推导。它们不是高频连续体模型的替代品。

## A.1 上支差动等效刚度

在加载平衡构型中，第 $i$ 条上支的轴向投影为 $a_i$、垂直投影为 $h$、长度为 $s_i$。令结点沿支点轴发生小位移 $u$。该绳长度的展开为

$$
s_i(u)=s_i+s_i'(0)u+\frac12s_i''(0)u^2+O(u^3),
$$

其中符号不同的左右支有

$$
|s_i'(0)|=\frac{a_i}{s_i},
\qquad
s_i''(0)=\frac{h^2}{s_i^3}.
$$

材料轴向刚度为 $k_i=E_iA_i/s_i$。一阶伸长产生的二次弹性能为

$$
\frac12k_i[s_i'(0)u]^2
=\frac12\frac{E_iA_i a_i^2}{s_i^3}u^2.
$$

平衡预张力 $T_{i0}$ 对二阶几何伸长作功，给出

$$
\frac12T_{i0}s_i''(0)u^2
=\frac12\frac{T_{i0}h^2}{s_i^3}u^2.
$$

故两上支沿轴的总线性刚度为

$$
\boxed{
K_x=\sum_{i=A,B}
\left(
\frac{E_iA_i a_i^2}{s_i^3}
+\frac{T_{i0}h^2}{s_i^3}
\right).
}
$$

这同时包含材料刚度和预张力几何刚度；漏掉后一项在极软或近竖直上支中会产生错误极限。

## A.2 为什么顺应性表现为附加长度

令摆球相对实验室的快模水平位移为 $x$，结点位移为 $u$。下绳相对结点的水平偏移为 $x-u$。小角时，下绳对摆球的回复力为

$$
F_x=-\frac{mg}{\ell}(x-u).
$$

无质量结点的准静态水平平衡给出

$$
K_xu=\frac{mg}{\ell}(x-u).
$$

消去 $u$，得到

$$
F_x=-\frac{mgK_x}{K_x\ell+mg}x
=-\frac{mg}{\ell+mg/K_x}x.
$$

所以

$$
\boxed{
\ell_c=\frac{mg}{K_x},
\qquad
\omega_\parallel^2\simeq\frac{g}{\ell+\ell_c}.
}
$$

该结果要求：上支轴向响应对摆频近似准静态；结点和上支惯性可忽略；下绳在线性阶可视为不可伸长；没有接近的轴向或支架共振。若这些条件不满足，应保留相应动态自由度。

## A.3 绳与结点质量对频率比的一阶预算

慢模共同转动近似中，写

$$
\omega_\perp^2=g\frac{C_\perp}{I_\perp},
$$

并令

$$
x=\frac\ell H,
\qquad y=\frac hH,
\qquad x+y=1.
$$

对 $m_J/m,M_\ell/m,M_u/m$ 作一阶展开，有

$$
\frac{\delta\omega_\perp}{\omega_\perp}
\simeq
\frac{m_J}{m}\frac{xy}{2}
+\frac{M_\ell}{m}\left(\frac x4-\frac{x^2}{6}\right)
+\frac{M_u}{m}\left(\frac y4-\frac{y^2}{6}\right).
$$

快模中均匀下绳给出

$$
\frac{\delta\omega_\parallel}{\omega_\parallel}
\simeq\frac{M_\ell}{12m}.
$$

两式相减即得

$$
\boxed{
\begin{aligned}
\frac{\delta\rho}{\rho}
\simeq{}&
-\frac{m_J}{m}\frac{xy}{2}
+\frac{M_\ell}{m}
\left(\frac1{12}-\frac x4+\frac{x^2}{6}\right)\\
&-\frac{M_u}{m}
\left(\frac y4-\frac{y^2}{6}\right).
\end{aligned}}
$$

由于这是一阶展开，不能在质量比不小、绳形显著弯曲或内部模态接近摆频时使用。此时应回到三自由度模型、离散绳链或连续体模型。

## A.4 长期相位预算

若目标频率比为 $\rho_0=p/q$，实际比值为

$$
\rho=\rho_0(1+\epsilon_\rho),
$$

经过一个慢模周期，快模相位相对目标多积累

$$
2\pi(\rho-\rho_0).
$$

经过 $N$ 个慢周期，

$$
|\Delta\Psi_N|
=2\pi Nq|\rho-\rho_0|
=2\pi Np|\epsilon_\rho|.
$$

因此

$$
\boxed{
|\epsilon_\rho|
\le\frac{\Phi_{\rm tol}}{2\pi pN}.
}
$$

这说明可忽略阈值随观察周期数按 $1/N$ 收紧。任何不写明观察窗的“近似闭合”都缺少可重复的精度定义。

---

# 附录 B：坐标反演与数值自检

## B.1 从三维位置反演环面坐标

在全张紧、$R>0$ 的物理带中，给定质心位置 $(x,y,z)$，有

$$
R=\sqrt{y^2+z^2},
$$

$$
\boxed{
\varphi=\operatorname{atan2}(x-x_C,R-h),
\qquad
\theta=\operatorname{atan2}(y,z).
}
$$

广义速度可由正交切向量投影：

$$
\boxed{
\dot\varphi=
\frac{\dot{\boldsymbol r}\cdot\partial_\varphi\boldsymbol r}{\ell^2},
\qquad
\dot\theta=
\frac{\dot{\boldsymbol r}\cdot\partial_\theta\boldsymbol r}{R^2}.
}
$$

该反演适合把双相机三维轨迹转换到理论相空间；靠近 $R=0$ 的坐标奇点或松弛阶段不能使用。

## B.2 最低限度单元测试

任意实现至少应通过：

1. $\theta=\dot\theta=0$ 时恢复长度 $\ell$ 的非线性单摆；
2. $\varphi=\dot\varphi=0$ 时恢复长度 $H$ 的非线性单摆；
3. 小振幅数值频率趋于 $\sqrt{g/\ell}$ 与 $\sqrt{g/H}$；
4. 无耗散、无松弛时能量守恒；
5. 对称装置中，快模松弛边界趋于 $|\varphi|=\arctan(a/h)$；
6. 在事件前缩小时间步和事件容差时，首次失张时刻收敛；
7. 任一张力为负的轨迹不得继续标记为三绳 Y 摆解。

---

# 附录 C：主要符号

| 符号 | 含义 |
|---|---|
| $A,B$ | 两个固定上支点 |
| $d$ | 支点间距 |
| $s_A,s_B$ | 左右上支工作长度 |
| $a_A,a_B$ | 交圆中心到左右支点的轴向距离 |
| $x_C$ | 交圆中心沿支点轴的坐标 |
| $h$ | 支点轴到结点交圆的半径；悬垂时的结点落差 |
| $\ell$ | 结点到摆球质心的下绳工作长度 |
| $H=h+\ell$ | 慢模有效长度 |
| $R=h+\ell\cos\varphi$ | 摆球到支点轴的瞬时径向距离 |
| $m,m_J$ | 摆球质量、结点质量 |
| $\mathsf R_b,\boldsymbol\omega_b,\mathsf I_b$ | 可选刚体摆球的姿态、角速度与质心惯量张量 |
| $\boldsymbol\rho_{\rm att}$ | 摆球质心到下绳连接点的刚体系偏置向量 |
| $M_\ell,M_u$ | 下绳质量、两上支总质量 |
| $L_A^0,L_B^0,L_\ell^0$ | 统一闭合模型中的三支路无载参考长度；与单支相位总长 $L_A,L_B$ 区分 |
| $\boldsymbol c_A,\boldsymbol c_B,\boldsymbol c_\ell$ | 三条绳的二次 Ritz 内部形状节点 |
| $\boldsymbol q,\boldsymbol X$ | 统一母模型的广义坐标与一阶状态 |
| $\lambda_i,N_i$ | 第 $i$ 支路的局部伸长率与非负局部轴力 |
| $\mathsf M$ | Ritz 一致质量矩阵装配后的全局质量矩阵 |
| $V_{\rm ax},V_{\rm bend}$ | 轴向储能与弯曲势能 |
| $\delta_\epsilon$ | 受拉激活宽度；正部函数本身不引入额外拟合参数 |
| $\mathcal P_\delta,[u]_+$ | 平滑受拉激活函数与精确非负正部函数 |
| $\varepsilon_t,\varepsilon_\kappa$ | 切向/伸长率与曲率正则化尺度 |
| $\varphi$ | 沿支点轴方向的快模角 |
| $\theta$ | Y 平面绕支点轴转动的慢模角 |
| $T_\ell,T_A,T_B$ | 下绳及左右上支张力 |
| $\omega_\parallel,\omega_\perp$ | 快、慢小振幅角频率 |
| $\rho$ | 频率比 $\omega_\parallel/\omega_\perp$ |
| $A_\varphi,A_\theta$ | 两广义角振幅 |
| $p:q$ | 目标互素整数频率比 |
| $\Psi_{pq}$ | 共振相位 |
| $\Delta_{pq}$ | 失谐 $q\Omega_\parallel-p\Omega_\perp$ |
| $K_x$ | 两上支沿支点轴的差动线性刚度 |
| $\ell_c=mg/K_x$ | 上支顺应性等效附加长度 |
| $EA,EI,GJ$ | 轴向、弯曲和扭转刚度 |
| $Q$ | 品质因数 |
| $\epsilon_{\rm req}$ | 由观察窗和相位容差确定的未建模频率比预算 |
| $\eta_T$ | 观察窗内最小归一化张力裕量 |

---

# 附录 D：统一闭合母方程的推导与适定性细节

## D.1 二次 Ritz 质量矩阵的解析积分

对任一支路，局部节点向量写为

$$
\boldsymbol q_i^{\rm loc}
=
\begin{pmatrix}
\boldsymbol r_{i0}\\
\boldsymbol c_i\\
\boldsymbol r_{i1}
\end{pmatrix}.
$$

式 (13.2) 可写成

$$
\boldsymbol r_i(\xi)
=\mathsf N(\xi)\boldsymbol q_i^{\rm loc},
\qquad
\mathsf N=(N_0I_3,N_1I_3,N_2I_3).
$$

连续动能为

$$
T_i
=\frac12M_i
\int_0^1
\dot{\boldsymbol q}_i^{{\rm loc},\mathsf T}
\mathsf N^{\mathsf T}\mathsf N
\dot{\boldsymbol q}_i^{\rm loc}
\,d\xi.
$$

因此

$$
\mathsf M_i^{\rm loc}
=M_i\int_0^1
\mathsf N^{\mathsf T}\mathsf N\,d\xi.
$$

三个标量积分满足

$$
\int_0^1N_aN_b\,d\xi
=\frac1{30}
\begin{pmatrix}
4&2&-1\\
2&16&2\\
-1&2&4
\end{pmatrix}_{ab},
$$

从而得到式 (13.4)。该矩阵是标准二次 Ritz 一致质量矩阵，不是把绳质量任意分摊到端点的经验规则。其三个特征值均为正，因此每个有正质量的局部支路在未删除固定支点自由度前具有正定动能。

设局部节点与全局坐标的关系为

$$
\boldsymbol q_i^{\rm loc}
=\mathsf A_i\boldsymbol q+\boldsymbol a_i.
$$

固定支点使 $\dot{\boldsymbol a}_i=0$，故支路对全局质量矩阵的贡献为

$$
\mathsf M_i
=\mathsf A_i^{\mathsf T}
\mathsf M_i^{\rm loc}
\mathsf A_i.
$$

加上集中质量即可得到式 (13.5)。若支点也运动，则把支架坐标加入 $\boldsymbol q$ 后使用同一装配式，无需重写柔索理论。

## D.2 重力一致载荷

由

$$
\int_0^1N_0d\xi=\frac16,
\qquad
\int_0^1N_1d\xi=\frac23,
\qquad
\int_0^1N_2d\xi=\frac16,
$$

连续绳重力势能

$$
-M_ig\int_0^1
\boldsymbol e_z\cdot\boldsymbol r_i(\xi)d\xi
$$

直接给出式 (13.7) 中的 $1:4:1$ 一致重力权重。质量矩阵和重力载荷使用同一 Ritz 基函数，因此不会出现“惯性按一种形状近似、重力按另一种形状近似”的不一致。

## D.3 单边轴力广义力的虚功推导

令

$$
s_{i,\varepsilon}
=\sqrt{\left|\boldsymbol r_{i,\xi}\right|^2
+\varepsilon_t^2},
\qquad
\bar L_i^0
=\sqrt{(L_i^0)^2+\varepsilon_t^2},
$$

$$
\lambda_i=\frac{s_{i,\varepsilon}}{\bar L_i^0},
\qquad
\widehat{\boldsymbol t}_i
=\frac{\boldsymbol r_{i,\xi}}{s_{i,\varepsilon}}.
$$

任意广义位移 $\delta\boldsymbol q$ 引起

$$
\delta\boldsymbol r_{i,\xi}
=\mathsf B_{i,\xi}\delta\boldsymbol q,
$$

因此

$$
\boxed{
\delta\lambda_i
=\frac1{\bar L_i^0}
\widehat{\boldsymbol t}_i\cdot
\mathsf B_{i,\xi}
\delta\boldsymbol q.
}
\tag{D.1}
$$

第 $i$ 支路的参考弧长元为

$$
ds_0=L_i^0d\xi.
$$

非负轴力 $N_i$ 的内力虚功为

$$
\delta W_{\rm ax}^{(i)}
=-\int_0^{L_i^0}
N_i\,\delta\lambda_i\,ds_0.
$$

代入式 (D.1)，得到

$$
\delta W_{\rm ax}^{(i)}
=-\delta\boldsymbol q^{\mathsf T}
\frac{L_i^0}{\bar L_i^0}
\int_0^1
N_i
\mathsf B_{i,\xi}^{\mathsf T}
\widehat{\boldsymbol t}_i
\,d\xi.
$$

所以

$$
\boldsymbol f_{\rm ax}^{(i)}
=-\frac{L_i^0}{\bar L_i^0}
\int_0^1
N_i
\mathsf B_{i,\xi}^{\mathsf T}
\widehat{\boldsymbol t}_i
\,d\xi,
$$

三支路求和即为式 (13.12)。因此式 (13.12) 的耦合系数不是人为指定，而由中心线参数化和虚功唯一确定。

## D.4 轴向储能与弹性候选张力

令

$$
\Phi_\delta'(x)=\mathcal P_\delta(x),
\qquad
\Phi_\delta(0)=0.
$$

轴向储能

$$
V_{\rm ax}^{(i)}
=E_iA_iL_i^0
\int_0^1
\Phi_{\delta_\epsilon}(\lambda_i-1)d\xi
$$

的变分为

$$
\delta V_{\rm ax}^{(i)}
=\frac{L_i^0}{\bar L_i^0}
\int_0^1
N_{e,i}
\widehat{\boldsymbol t}_i\cdot
\mathsf B_{i,\xi}\delta\boldsymbol q
\,d\xi,
$$

其中

$$
N_{e,i}
=E_iA_i\mathcal P_{\delta_\epsilon}(\lambda_i-1).
$$

故 $-\nabla V_{\rm ax}$ 正好给出式 (13.12) 中 $N_i$ 被 $N_{e,i}$ 替代后的弹性部分。黏性项和正部截断属于非保守广义力，不能重复写入势能。

## D.5 单边 Kelvin–Voigt 本构的能量不增性

忽略空气阻力、支架耗散和弯曲内耗，只考察一处材料点。记

$$
y=N_e+N_v,
$$

$$
N=[y]_+,
$$

$$
N_v
=\eta A\mathcal P_{\delta_\epsilon}'(\lambda-1)
\dot\lambda.
$$

轴向内力对“动能加弹性储能”的局部贡献为

$$
\dot{\mathcal E}_{\rm ax}
=(N_e-N)\dot\lambda.
$$

分两种情况。

若 $y>0$，则 $N=N_e+N_v$，所以

$$
\dot{\mathcal E}_{\rm ax}
=-N_v\dot\lambda
=-\eta A
\mathcal P_{\delta_\epsilon}'(\lambda-1)
\dot\lambda^2
\le0.
$$

若 $y\le0$，则 $N=0$。由于 $N_e\ge0$ 且

$$
N_e+
\eta A\mathcal P_{\delta_\epsilon}'(\lambda-1)
\dot\lambda\le0,
$$

在 $\mathcal P_{\delta_\epsilon}'>0$ 时必有 $\dot\lambda\le0$，故

$$
\dot{\mathcal E}_{\rm ax}
=N_e\dot\lambda\le0.
$$

若 $\mathcal P_{\delta_\epsilon}'=0$，则同时有 $N_e=0$，仍有 $\dot{\mathcal E}_{\rm ax}=0$。因此式 (13.11) 在所有分支上都不会注入机械能。

摆球二次阻力满足

$$
\boldsymbol F_{d,b}\cdot\dot{\boldsymbol r}_m
=-c_{1b}\left|\dot{\boldsymbol r}_m\right|^2
-c_{2b}\left|\dot{\boldsymbol r}_m\right|^3
\le0,
$$

绳分布式阻力同理。由此可以把总功率平衡作为统一闭合模型的强数值自检。

## D.6 局部唯一性命题

**命题。** 固定 Ritz 阶数，并假设：

1. 全局质量矩阵 $\mathsf M$ 正定；
2. $\delta_\epsilon,\varepsilon_t,\varepsilon_\kappa>0$；
3. 材料、空气阻力和支架参数有限；
4. 外部规定运动分段 $C^1$。

则式 (13.18) 对任意完整初态存在唯一局部解。

**理由。** $\mathcal P_\delta$ 是 $C^1$ 且导数分段线性，因而 $\mathcal P_\delta$ 与 $\mathcal P_\delta'$ 均局部 Lipschitz；正部函数 $[x]_+$ 是全局 $1$-Lipschitz；$\varepsilon_t>0$ 消除了伸长率和切向中的零分母；$\varepsilon_\kappa>0$ 消除了曲率中的零分母；线性阻力和 $|v|v$ 均局部 Lipschitz。有限个局部 Lipschitz 映射的装配仍局部 Lipschitz，且 $\mathsf M^{-1}$ 存在。因此式 (13.18) 满足 Picard–Lindelöf 条件。

该命题针对的是有限刚度、有限质量的闭合母模型。不可伸长、零质量和零接合宽度的同时极限是奇异极限，不能通过把参数直接设为零来继承同一证明。

## D.7 环面慢流形的拉格朗日拉回

在全张紧、高刚度、内部模态与主频充分分离的区域，设完整坐标可写成慢变量的嵌入

$$
\boldsymbol q
=\boldsymbol\chi(\boldsymbol Q),
\qquad
\boldsymbol Q=(\varphi,\theta)^{\mathsf T}.
$$

则

$$
\dot{\boldsymbol q}
=\mathsf J_\chi(\boldsymbol Q)
\dot{\boldsymbol Q},
\qquad
\mathsf J_\chi
=\frac{\partial\boldsymbol\chi}{\partial\boldsymbol Q}.
$$

母模型动能拉回为

$$
T_{\rm eff}
=\frac12\dot{\boldsymbol Q}^{\mathsf T}
\underbrace{
\left(
\mathsf J_\chi^{\mathsf T}
\mathsf M
\mathsf J_\chi
\right)}_{\mathsf M_{\rm eff}(\boldsymbol Q)}
\dot{\boldsymbol Q}.
$$

势能拉回为

$$
V_{\rm eff}(\boldsymbol Q)
=V\!\left(\boldsymbol\chi(\boldsymbol Q)\right).
$$

所以有效慢变量方程由

$$
\frac{d}{dt}
\frac{\partial(T_{\rm eff}-V_{\rm eff})}
{\partial\dot Q_a}
-
\frac{\partial(T_{\rm eff}-V_{\rm eff})}
{\partial Q_a}
=Q_{a,\rm eff}
$$

唯一得到。理想极限下，$\boldsymbol\chi$ 就是第 3 节的环面嵌入，$\mathsf M_{\rm eff}$ 的两个对角度量系数退化为

$$
m\ell^2,
\qquad
mR(\varphi)^2,
$$

从而恢复精确环面方程。有限绳质量、结点质量和柔度则通过 $\boldsymbol\chi$ 与 $\mathsf M$ 的拉回自动进入 $\mathsf M_{\rm eff}$ 和 $V_{\rm eff}$，这说明它们不应仅被看作事后频率修正。

---

# 参考文献

1. International Young Physicists’ Tournament, **IYPT 2027 Problems**, Problem 5, “Y-shaped pendulum,” 2026.
2. Nathaniel Bowditch, “On the Motion of a Pendulum Suspended from Two Points,” *Memoirs of the American Academy of Arts and Sciences*, vol. 3, part 2, pp. 413–436, 1815.
3. James Dean, “An Investigation of the Apparent Motion of the Earth Viewed from the Moon, Arising from the Moon’s Librations,” *Memoirs of the American Academy of Arts and Sciences*, vol. 3, part 2, pp. 241–245, 1815.
4. R. S. Worland and M. J. Moelter, “Two-Dimensional Pendulum Experiments Using a Spark Generator,” *The Physics Teacher* **38**, 489–492, 2000, DOI: `10.1119/1.1329093`.
5. R. J. Whitaker, “A Note on the Blackburn Pendulum,” *American Journal of Physics* **59**, 330–333, 1991, DOI: `10.1119/1.16543`.
6. R. J. Whitaker, “Harmonographs. I. Pendulum Design,” *American Journal of Physics* **69**, 162–173, 2001, DOI: `10.1119/1.1309521`.
7. R. J. Whitaker, “Types of Two-Dimensional Pendulums and Their Uses in Education,” *Science & Education* **13**, 401–415, 2004, DOI: `10.1023/B:SCED.0000041830.98845.5F`.
8. G. L. Baker and J. A. Blackburn, *The Pendulum: A Case Study in Physics*, Oxford University Press, 2005.
9. R. A. Nelson and M. G. Olsson, “The Pendulum—Rich Physics from a Simple System,” *American Journal of Physics* **54**, 112–121, 1986, DOI: `10.1119/1.14703`.
10. F. M. S. Lima and P. Arun, “An Accurate Formula for the Period of a Simple Pendulum Oscillating Beyond the Small Angle Regime,” *American Journal of Physics* **74**, 892–895, 2006, DOI: `10.1119/1.2215616`.
11. Q. Jia, Y. Luo, H. Zhou, Y. Wang, J. Wan and S. Wang, “Nonlinear Coupling in an Asymmetric Pendulum,” *American Journal of Physics* **90**, 594–603, 2022, DOI: `10.1119/10.0010391`.
12. A. Goriely, P. Boulanger and J. Leroy, “Toy Models: The Jumping Pendulum,” *American Journal of Physics* **74**, 784–788, 2006, DOI: `10.1119/1.2198886`.
13. T. Lee, M. Leok and N. H. McClamroch, “Dynamics of a 3D Elastic String Pendulum,” arXiv:`0903.0332`; “Computational Dynamics of a 3D Elastic String Pendulum Attached to a Rigid Body and an Inertially Fixed Reel Mechanism,” *Nonlinear Dynamics* **64**, 97–115, 2011, DOI: `10.1007/s11071-010-9849-5`.
14. R. Salamon, H. Kamiński and P. Fritzkowski, “Estimation of Parameters of Various Damping Models in Planar Motion of a Pendulum,” *Meccanica* **55**, 1655–1677, 2020, DOI: `10.1007/s11012-020-01197-z`.
15. NIST Digital Library of Mathematical Functions, §22.19(i), “Classical Dynamics: The Pendulum,” and §19.2, “Legendre Elliptic Integrals.”
16. J. P. LaSalle, “Some Extensions of Liapunov’s Second Method,” *IRE Transactions on Circuit Theory* **7**, 520–527, 1960, DOI: `10.1109/TCT.1960.1086720`.

---

## 最终概括

Y-Pendulum 的解析核心仍然是环面上的两自由度运动：双支点和无质量正张力结点把摆球限制在环面上，使沿支点轴和垂直支点轴的局部重力曲率分别对应有效长度 $\ell$ 与 $h+\ell$；Lissajous 图样来自两个模态的相位合成，有限振幅则产生自频移和交叉频移。

但环面方程只在全张紧、轻绳、轻结点和高轴向刚度慢流形上闭合。为了由参数与初态预测整个观察窗，本文最终采用每条绳一个内部节点的二次 Ritz 柔索模型，解析保留绳质量、结点质量、轴向伸长、最低曲率模态和单边受拉本构，并将空气阻力、浮力、支架与局部损耗装配到同一广义坐标系统中。统一方程为

$$
\mathsf M\ddot{\boldsymbol q}
=\boldsymbol F(\boldsymbol q,\dot{\boldsymbol q};\boldsymbol p),
$$

或等价的一阶形式 $\dot{\boldsymbol X}=\boldsymbol F(\boldsymbol X;\boldsymbol p)$。有限质量、有限刚度和有限接合宽度消除了无质量松绳与理想同时冲击的欠定；给定完整参数和完整初始状态后，模型在任意有限观察窗内唯一决定摆球、结点、低阶绳形、局部张力、松弛、重新受拉、能量和观测轨迹。

因此，完善后的理论不再是“一个理想主方程加若干事后频移补丁”，而是“一个全局闭合母方程加一组从它严格导出的慢流形、量级和渐近公式”。在不出现内部峰或松弛时，应优先使用可解释性最强的环面降阶；一旦张力过零、非共面结点运动或绳内峰超过误差预算，则返回统一母模型，并用 Ritz 阶数收敛而不是无止境堆叠机制来控制复杂度。

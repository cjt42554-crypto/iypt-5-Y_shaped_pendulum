# P3R5 四点冻结观测与约化 Hessian 描述图

2026-09-06 路径维护：`config.json` 的两个输入路径已指向现有研究记录，冻结输入的 SHA-256 不变。现存 `outputs/` 仍是原配置绑定的历史输出；复算写入新的目录，不能覆盖它。旧停止口令只反映当时流程，当前规范见根 AGENTS。

## 1. 结论

四张冻结 P3R5 尺度卡中的负方向不是任意六自由度混合，也不是单独的摆球平移。按每张冻结卡的归一化坐标，它只包含：

- 垂直于支点连线的摆球侧向平移 $\delta y/L$；
- 绕支点连线的摆球滚转 $\delta\theta_x$。

四张卡的第三个相关自由度 $\delta\theta_y$ 以及与负方向正交的侧移—滚转组合均保持正曲率。故固定双活动参考的三维支撑切空间在四个已观察尺度点上都是 $(-,+,+)$ 谱符号，即这四个候选参考各自在允许方向上是鞍点，而不是冻结资格定义所需的严格局部极小值。

本文严格区分两层证据：

- `OBSERVED_AT_FOUR_FROZEN_POINTS`：直接来自四张哈希绑定冻结卡的数值；
- `INTERPOLANT_PROPERTY`：只描述用这四点构造的 PCHIP 可视化曲线。

第二层不是未观测尺度上的模型求值、连续稳定性证明或解析定理。

这只是 P3R5 静态、刚性、无摩擦、单边接触候选模型中固定双活动分支的结论。它不是装置不稳定结论，也不是接触律、动态接触或实验验证。

## 2. 数据边界

分析只读取以下两份冻结工件：

- `p3r5_holdout_cards.json`，SHA-256 为 `48f418094ef7ccaa595a63a080f65f82d5b0125eaec0fb25cc58acf823bcb0f0`；
- `p3r5_admissibility_metrics.json`，SHA-256 为 `e93eb9a0cb074ca1cc9a137149b89b8d2c4384f100c9a9eefaf5c0ff79a3f987`。

本分析没有生成新留出卡、没有装配新接触算例、没有运行参考构造器、没有运行 G3R5，也没有修改 P3–P3R5 的任何冻结文件、阈值、目标或状态。

## 3. 坐标和方向解释

冻结六坐标按下列顺序归一化：

$$
\widehat q=
\left(
\frac{\delta x}{L},
\frac{\delta y}{L},
\frac{\delta z}{L},
\delta\theta_x,
\delta\theta_y,
\delta\theta_z
\right).
$$

四张尺度卡的负方向都可写为

$$
v_-(s)=
\left(0,a(s),0,b(s),0,0\right)^{\mathsf T},
\qquad
a(s)^2+b(s)^2=1.
$$

其正交侧移—滚转方向和独立转动方向为

$$
v_+(s)=
\left(0,-b(s),0,a(s),0,0\right)^{\mathsf T},
$$

$$
v_y=
\left(0,0,0,0,1,0\right)^{\mathsf T}.
$$

因此，在每张冻结卡的特征向量中，摆球 $y$ 向侧移与绕 $x$ 轴滚转共同组成负方向，使两个已声明活动的上支—摆球接触满足该卡的一阶切向约束。单独侧移或单独滚转都不是这四张卡记录的特征方向。

## 4. 已观察谱

| 留出卡 | 尺度 $s$ | $a$ | $b$ | $\lambda_-$ | $\lambda_y$ | $\lambda_+$ |
|---|---:|---:|---:|---:|---:|---:|
| `R5_SCALE_H01` | 0.74 | 0.158456 | 0.987366 | -0.0346075 | 0.0292632 | 2.50919 |
| `R5_SCALE_H04` | 0.86 | 0.182383 | 0.983228 | -0.0397383 | 0.0339408 | 2.17527 |
| `R5_SCALE_H02` | 0.99 | 0.207524 | 0.978230 | -0.0450971 | 0.0389873 | 1.90735 |
| `R5_SCALE_H03` | 1.62 | 0.316654 | 0.948541 | -0.0678280 | 0.0631379 | 1.23831 |

所有负方向的矩阵曲率均与独立方向曲率在既有交叉误差内相符。按四点的离散顺序，归一化负模态中的侧移分量增加、滚转分量下降；换算为物理单位后，每米侧移对应的滚转量也逐点下降。这只是 `OBSERVED_AT_FOUR_FROZEN_POINTS` 层的离散趋势，不建立尺度律。

## 5. 描述性 PCHIP 可视化

在三维坐标

$$
\xi=
\left(
\frac{\delta y}{L},
\delta\theta_x,
\delta\theta_y
\right)^{\mathsf T}
$$

中，每个冻结观测点 $s_i$ 的约化 Hessian 可由该点的特征量重构。为画出四点之间的描述曲线，程序分别对 $\lambda_-$、$\lambda_+$、$\lambda_y$ 和模态角 $\alpha=\operatorname{atan2}(b,a)$ 构造 PCHIP。令这些插值量组成

$$
\widetilde V_{\rm desc}(s)=
\begin{bmatrix}
a(s) & -b(s) & 0\\
b(s) & a(s) & 0\\
0 & 0 & 1
\end{bmatrix}.
$$

并定义仅用于描述与绘图的矩阵

$$
\widetilde H_{\rm desc}(s)=
\widetilde V_{\rm desc}(s)
\operatorname{diag}
\left(
\lambda_-(s),
\lambda_+(s),
\lambda_y(s)
\right)
\widetilde V_{\rm desc}(s)^{\mathsf T}.
$$

在四个冻结点 $s_i$ 上，该重构与保存的约化谱一致；在点间，$\widetilde H_{\rm desc}(s)$ 只是 `INTERPOLANT_PROPERTY`，不是重新装配或求解得到的 Hessian。因此不把点间矩阵代入局部势能展开来提出新的物理结论。

参数域严格限制为四张冻结卡的凸包 $0.74\le s\le1.62$。求值函数对任何区间外输入失败关闭，不允许外推。每一段的多项式系数保存在 `outputs/stability_map.json` 中，JSON 和 `parameterized_map.csv` 的每一行都标为 `INTERPOLANT_PROPERTY`；四点原始表和 `observed_modes.csv` 则标为 `OBSERVED_AT_FOUR_FROZEN_POINTS`。

## 6. 图形与解释上限

![四张冻结 P3R5 尺度卡及描述性 PCHIP 曲线](outputs/reduced_hessian_stability_map.png)

`OBSERVED_AT_FOUR_FROZEN_POINTS` 层只支持：四个保存的 $\lambda_-$ 都严格小于零，另外两个保存特征值都为正。`INTERPOLANT_PROPERTY` 层另行记录：所选 PCHIP 在观测凸包上保持相同符号，其机器状态为 `INTERPOLANT_HAS_NO_ZERO_CROSSING_ON_OBSERVED_CONVEX_HULL`。

点间曲线不增加观测点，不能用来报告过零位置、连续尺度区间、分岔类型、装置稳定性或实验行为。可以支持的最窄结论只有：四张冻结尺度卡各自记录了固定双活动候选参考的侧移—滚转负模态；曲线只是这四点的无外推描述图。

## 7. 可复现性与停止门

运行命令为：

```bash
PYTHONPATH=src python -m p3r5_stability_map \
  --config config.json \
  --repository-root ../../../.. \
  --output /tmp/yp5-stability-map-new
```

输出 JSON、CSV、SVG、PNG 和 SHA-256 工件清单。`stability_map.json` 同时记录配置与全部分析源码的源清单、CPython/NumPy/SciPy/Matplotlib 运行时身份及其哈希；工件清单把字节确定性范围限定为同一已记录源码、配置和运行时。本轮在绑定的 CPython 3.12.3、NumPy 1.26.4、SciPy 1.11.4、Matplotlib 3.6.3 环境中完成三份输出逐字节对照。

F0R 完成后，本分析不开放 P3R6、新接触资格卡、G3R5、动力学或动态接触，并停止在 `F0R_PRO_REVIEW`。

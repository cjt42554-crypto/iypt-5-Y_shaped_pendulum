# 第一轮实验预注册

## 1. 目标与状态边界

第一轮先建立能区分模型的低维数据集，不以“漂亮图样”为主要目标。E0 只冻结计划；没有运行任何真实实验。

## 2. 结果型运行矩阵

pilot 运行不计入下表。第一轮计划 70 条结果型运行：

| 几何 | 条件 | 重复 | 条数 |
|---|---|---:|---:|
| 4:3 | 小振幅近纯 fast mode | 5 | 5 |
| 4:3 | 小振幅近纯 slow mode | 5 | 5 |
| 3:2 | 小振幅近纯 fast mode | 5 | 5 |
| 3:2 | 小振幅近纯 slow mode | 5 | 5 |
| 2:1 | 小振幅近纯 fast mode | 5 | 5 |
| 2:1 | 小振幅近纯 slow mode | 5 | 5 |
| 3:2 | 四个混合振幅层 | 每层 5 | 20 |
| 4:3 | 两个低/中混合振幅层 | 每层 5 | 10 |
| 2:1 | 两个低/中混合振幅层 | 每层 5 | 10 |
| 合计 |  |  | 70 |

3:2 nominal release anchor 可使用正式理想图谱已有的 $(0.05,0.04)$、$(0.10,0.08)$、$(0.15,0.10)$ 和 $(0.20,0.12)$ rad，只作为释放目标。4:3 与 2:1 第一轮只使用前两个安全层。真实初始振幅必须由实验轨迹重建，不能把 nominal target 当成测量结果。

## 3. Run 身份

`first_round_plan.template.json` 已为 70 条结果型运行预分配唯一 `run_id` 和首个 `attempt_id`，并将状态固定为 `NOT_RUN`、装置版本固定为 `UNSET_REQUIRES_HUMAN`。采集前人工必须绑定实际 `apparatus_revision`。失败的 ID 永不复用；重试必须生成新 attempt 并记录 `retry_parent_id`。失败或排除的运行仍保留原始数据、哈希和原因。

禁止根据结果重新挑选“最好看的五次”。

## 4. 纳入与降级条件

- 最快周期至少 30 帧，目标为 50 帧以上；
- 目标记录 20 个慢周期，或直到预注册 SNR 下限；
- 主要分析窗中 3D bob 有效样本比例至少 95%；
- 不跨越超过 $0.1$ 个最快周期的连续缺测区间进行科学拟合；
- 展示插值不得改变 `valid_mask=false`；
- primary 过滤器、拟合窗和 estimator 在 full round 前冻结；
- 任一失张、接近、接触或模型守卫事件发生后，理想环面比较在第一事件时刻停止；
- “锁频”必须同时具有频率平台和有界共振相位，二维瓣数单独不构成判据。

## 5. 主要观测量

每条有效运行至少生成：

1. bob 与 junction 三维位置；
2. 可用时的 bob orientation 和支路材料标记点；
3. 两个由小振幅近纯模态运行建立并冻结的实验模态方向；
4. $\Omega_\varphi$、$\Omega_\theta$、频率比和两模态阻尼率；
5. 重建的实际初始振幅；
6. 共振相位 $\Psi(t)$ 与共周期状态闭合误差；
7. 频率和相位对分析窗的敏感性；
8. slack、re-tension、near-contact 和 contact 事件；
9. 有张力传感器时的三支张力和检测下限。

小振幅频率使用加权 damped-sinusoid fit。模态方向冻结后，多振幅运行不得重新旋转模态基底来改善外观。

## 6. 误差预算

| 来源 | 处理 |
|---|---|
| 装置几何与质量 | 参数协方差传播 |
| 相机内外参 | calibration Monte Carlo |
| 2D marker 定位 | 静止 pilot 位置噪声 |
| 双目三角化 | 逐帧 $3\times3$ covariance |
| 相机同步 | 时间偏移与抖动 Monte Carlo |
| release repeatability | 跨 repeat 随机效应 |
| 轨迹拟合窗 | 预注册多窗 sensitivity |
| 滤波与导数估计 | 固定 primary 与 sensitivity variants |
| 前向输入不确定度 | 正式 `run_ensemble` |
| 模型数值误差 | 与实验误差分开记录 |

若分量可以视为独立，比较不确定度为：

$$
u_{\mathrm{cmp}}^2=u_{\mathrm{exp}}^2+u_{\mathrm{model\,input}}^2+u_{\mathrm{numerical}}^2.
$$

长期相位还传播频率比不确定度：

$$
\sigma_\Psi\simeq 2\pi qN\sigma_\rho.
$$

## 7. 预注册比较状态

比较只输出 `CONSISTENT_WITH_CURRENT_UNCERTAINTY`、`SYSTEMATIC_DISCREPANCY`、`INCONCLUSIVE` 或 `OUT_OF_MODEL_DOMAIN`。若建议新增机制，必须在未参与参数设定的 holdout 条件上看到超过合成不确定度的可重复改善；同一数据调参后不能再被称为验证。

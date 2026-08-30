# 相机、同步与轨迹数据合同

## 1. 世界坐标

世界坐标固定定义为：

- $+z$：竖直向上、反重力；
- $+x$：从 A 指向 B 的水平投影；
- $+y=z\times x$；
- 原点：两支点坐标的中点。

若 A/B 不等高，保留实测 $z$ 坐标，不把支点强制投影到等高平面。

## 2. Brown--Conrady 相机约定

E0 复用正式前向求解器的约定：

$$
\mathbf X_c=R_c(\mathbf X_W-\mathbf c_c).
$$

相机记录至少包含 `camera_id`、图像尺寸、nominal fps、时间戳来源、$R_c$、$\mathbf c_c$、$f_x,f_y,c_x,c_y$、$k_1,k_2,k_3,p_1,p_2$、$\Omega_{\mathrm{cal}}$、标定板身份与尺寸、标定时间、重投影 RMS、标定域和原始标定 SHA-256。

`R_c` 必须属于 $SO(3)$；焦距为正；归一化坐标必须位于标定域内。未通过这些条件的投影不得静默返回有效像素。

## 3. 帧时间与同步

每帧必须保存：

- `frame_index`；
- `raw_timestamp_s` 与 `aligned_timestamp_s`；
- `sync_event_id`；
- `sync_offset_s` 与 `sync_uncertainty_s`；
- `dropped_frame_flag`。

frame index 不能替代时间。同步使用公共闪光、硬触发或等价公共事件。pilot 后残余同步误差大于 0.25 frame interval 时，该批次停止进入科学分析。

## 4. 2D 检测

每个 camera、marker 和 frame 保存 $u,v$ 像素坐标、置信度、$2\times2$ 协方差、`valid` 与 `invalid_reason`。遮挡、标定域外、镜头后方、低置信度和缺帧必须保留不同原因码。

## 5. 3D 轨迹 bundle

大型数组写入 `trajectory.npz`；JSON 只保存身份、shape、单位、哈希和不确定度摘要。最低数组集合为：

- `time_s`；
- `r_bob_W_m`；
- `r_junction_W_m`；
- `branch_marker_positions_W_m`；
- `bob_orientation_WB`；
- `position_covariance`；
- `valid_mask`；
- `occlusion_mask`；
- `event_annotations`。

JSON manifest 与 NPZ 必须相互绑定 SHA-256。任何插值都只能生成单独的展示数组，不能把原始无效帧改成有效帧。

## 6. 共同比较接口

实验和正式模型都转换为 `YPS-EXPERIMENT-COMMON-OBSERVABLES-1.0`，最低字段为 identity、time、valid interval、bob/junction 世界坐标、modal basis、fast/slow coordinate、两频率、频率比、两阻尼率、共振相位、闭合误差、事件、不确定度和 domain status。Identity 必须给出 `source_id` 与源文件或正式源码的 `source_sha256`；事件必须给出代码、时间、严重度和检测方法；不确定度必须给出方法、分量与 covariance reference。固定记录拒绝未知字段，可扩展的不确定度分量 map 只接受非负数值。

优先比较世界坐标下可观测物理量，不比较模型内部有限元自由度。

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

相机记录至少包含 `camera_id`、图像尺寸、nominal fps、时间戳来源、$R_c$、$\mathbf c_c$、$f_x,f_y,c_x,c_y$、$k_1,k_2,k_3,p_1,p_2$、$\Omega_{\mathrm{cal}}$、标定板身份与尺寸、标定时间、重投影 RMS、原始标定 SHA-256 和参数 covariance SHA-256。

`R_c` 在 JSON 与消费者中统一为真实 $3\times3$ matrix，必须属于 $SO(3)$；$\mathbf c_c$ 为 3-vector；焦距为正；归一化坐标必须位于标定域内。`MEASURED_CALIBRATION` 的所有 camera 与同步字段必须完整且不含 `null` 或 `UNSET_REQUIRES_HUMAN`。未通过这些条件的投影不得静默返回有效像素。

## 3. 帧时间与同步

每帧必须保存：

- `frame_index`；
- `raw_timestamp_s` 与 `aligned_timestamp_s`；
- `sync_event_id`；
- `sync_offset_s` 与 `sync_uncertainty_s`；
- `dropped_frame_flag`。

frame index 不能替代时间。同步使用公共闪光、硬触发或等价公共事件。rig manifest 必须记录实测 residual fraction、offset、offset uncertainty、jitter uncertainty、alignment method 和原始同步 SHA-256。pilot 后残余同步误差大于 0.25 frame interval 时，该批次停止进入科学分析。

这些字段实际进入 detection NPZ，形状为 `(sample, camera)`，不是只存在于说明文字。每路在场 frame 的 `frame_index` 必须非负且严格递增，`raw_timestamp_s` 必须有限；缺帧位置使用 `frame_index=-1`、`raw_timestamp_s=NaN` 和 `dropped_frame_flag=true`。`aligned_timestamp_s` 必须逐相机严格递增，并在 `sync_uncertainty_s` 内同时满足 `raw_timestamp_s + sync_offset_s` 和公共分析轴 `time_s`。缺帧不允许伪造 raw timestamp。

## 4. 2D 检测

每个 camera、marker 和 frame 保存 $u,v$ 像素坐标、置信度、$2\times2$ 协方差、`valid`、`occlusion` 与 `invalid_reason`。`YPS-E0-DETECTION-2D-BUNDLE-1.1` 同时绑定 camera rig、每路原始视频、detector configuration 和 NPZ SHA-256。固定失效码为 `VALID`、`OCCLUDED`、`LOW_CONFIDENCE`、`DROPPED_FRAME`、`OUTSIDE_CALIBRATION_DOMAIN`、`BEHIND_CAMERA`、`DETECTOR_FAILURE`、`SYNC_INVALID` 和 `OTHER_INVALID`。`VALID` 必须与 `valid_mask=true` 完全同位，`OCCLUDED` 必须与 occlusion mask 完全同位，掉帧相机的全部 marker 必须使用 `DROPPED_FRAME`；这些情况不能被插值改写为有效检测。

每个有效 $2\times2$ covariance 必须有限、对称且半正定。双目重建对四个像素坐标计算数值 Jacobian $J$，并传播：

$$
\Sigma_{3D}=J\,\operatorname{blockdiag}(\Sigma_A,\Sigma_B)J^\mathsf{T}.
$$

传播后的 $3\times3$ covariance 同样必须有限、对称且半正定；重建或 Jacobian 失败时该 marker/sample 保持无效。

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

`position_covariance` 固定为 `(sample, 2, 3, 3)`，第二轴依次为 bob 与 junction；`occlusion_mask` 固定为 `(sample, 2)`。validator 对有效样本检查位置、orientation、covariance 形状、有限性、$SO(3)$、对称性和半正定性。

`YPS-E0-TRAJECTORY-BUNDLE-1.2` 的 JSON manifest 与 NPZ 必须相互绑定 SHA-256，并继续绑定上游 2D detection manifest 与 camera rig。trajectory writer 必须先解析并按 detection schema 验证上游 manifest，核对其 NPZ 实际 SHA-256、字段集合、shape、dtype 和逐帧内容合同，再逐项核对 `data_origin`、`run_id`、`attempt_id`、`apparatus_revision`、`camera_rig_sha256`、sample count 和实际 `time_s` 轴；只有哈希相同但身份或时间轴错绑仍必须失败关闭。任何插值都只能生成单独的展示数组，不能把原始无效帧改成有效帧。

## 6. 共同比较接口

实验和正式模型都转换为 `YPS-EXPERIMENT-COMMON-OBSERVABLES-1.2`。公共 NPZ 最低实际包含：

- `time_s`；
- `r_bob_W_m` 与 `r_junction_W_m`；
- 两行正交的 `modal_basis_W`；
- `q_fast_m` 与 `q_slow_m`；
- `resonant_phase_rad`；
- `valid_mask`。

JSON manifest 绑定 trajectory manifest 与公共 NPZ，记录每个数组的 shape、unit、dtype、模态基底来源运行与方法哈希、native sampling diagnostics、两频率、频率比、两阻尼率、闭合误差、事件、不确定度和 domain status。实验 identity 必须给出 `source_id`、`source_sha256`、`run_id`、`attempt_id`、apparatus revision 和 `camera_rig_sha256`。common writer 必须解析并验证 trajectory manifest，核对其 NPZ 实际 SHA-256、字段集合、shape、dtype 与轨迹内容合同，逐项确认上述 identity 与 trajectory 一致，并要求 `time_s`、bob/junction 世界坐标与上游逐元素相同；common valid mask 可以进一步收紧，但不得恢复上游已经无效的样本。`data_origin=MEASURED` 的 detection、trajectory 与 common manifest 均禁止残留 `UNSET_REQUIRES_HUMAN`。固定记录拒绝未知字段，可扩展的不确定度分量 map 只接受非负数值。

native interval 的最大相对偏差超过 1% 时，damped-mode estimator 必须失败关闭，不得继续用 median $\Delta t$ 假装均匀采样。若另行采用 resampling，必须预注册并绑定 configuration SHA-256。

优先比较世界坐标下可观测物理量，不比较模型内部有限元自由度。

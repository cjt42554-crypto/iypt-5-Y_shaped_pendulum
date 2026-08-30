# 代表几何与低成本 Pilot 协议

## 1. 三类代表几何

理想线性设计律给出：

$$
\eta_0=\frac{h}{\ell}=\left(\frac{p}{q}\right)^2-1.
$$

| 目标比 | 理想无量纲设计中心 $\eta_0$ | 第一轮信息作用 |
|---|---:|---|
| 4:3 | $7/9\approx0.7778$ | 与现有目标配置的结构预报最接近，直接检查 P9 |
| 3:2 | $5/4=1.25$ | 四阶频移、预补偿和长期相位研究最完整 |
| 2:1 | $3$ | 提供明显分离的几何尺度，检查系统偏差 |

这些值是理想模型的无量纲设计中心，不是实测制造尺寸。制造模板禁止接受 `eta_numeric`、`tuned_eta` 或 `numerically_tuned_geometry` 作为 `MEASURED` 或制造值。任何机械调整都创建新的 `apparatus_revision`。

正式图谱中的 5:3 继续保留，但不作为第一轮独立装置；其增量信息小于上述三点。

## 2. Pilot 序列

pilot 首先使用届时已有的一套真实装置，先测清其实际几何，不要求预先制造三套目标几何。

| Pilot ID | 操作 | 重复 | 目的 |
|---|---|---:|---|
| P00 | 标定板与同步闪光，batch start | 1 | 内外参与时间基准 |
| P01 | 完整静止装置录制 60 s | 2 | tracking floor、支架与 marker 漂移 |
| P02 | 小幅近 fast-mode release | 2 | 最快周期、帧率与 fast 方向 |
| P03 | 小幅近 slow-mode release | 2 | slow 方向与记录窗 |
| P04 | 小幅 mixed release | 2 | 双模态分离与相位管线 |
| P05 | 中等 mixed release，条件执行 | 2 | slack/contact、非线性与遮挡筛查 |
| P06 | 标定板，batch end | 1 | 标定漂移 |

只有 P00--P04 的数据质量合格、无安全问题且未见明显模型域失效时才执行 P05。

`pilot_attempts.template.json` 把 repeat 展开为 12 个首轮计划 slot，但模板初始不创建任何实际 attempt。JSON ledger 是机器权威记录；CSV 只是计划视图和现场辅助表，不得被解释成已经尝试或已经取得证据。只有操作真正开始时才创建 actual attempt，并把它绑定到唯一的 `slot_id`。

campaign 可以在尚有未来 slot 为 `PENDING` 时保持 `IN_PROGRESS`。条件前提不满足的 slot 标记为 `SKIPPED_DUE_TO_PREREQUISITE`；硬停止后的未开始 slot 标记为 `NOT_STARTED_DUE_TO_STOP`。这两类 slot，以及仍为 `PENDING` 的 slot，都不得伪造开始/结束时间、raw file、camera rig 哈希或 attempt ID。

实际 attempt 使用 `evidence_state` 区分 `NO_RAW_DATA`、`PARTIAL_RAW_DATA` 和 `COMPLETE_RAW_DATA`。成功完成的 attempt 必须绑定预注册文件、apparatus revision、camera rig SHA-256 和每个原始文件 SHA-256；但 P00 等 setup/calibration 可能在相机 rig 尚未形成、原始文件尚未落盘时失败，此时允许 `FAILED` 或 `ABORTED` attempt 明确记录为 `NO_RAW_DATA`，且 `raw_files=[]`、`camera_rig_sha256=null`。不得用占位哈希假装证据存在。

重试不得覆盖原 attempt。失败后决定重试、但下一次操作尚未开始时，slot 标记为 `RETRY_PENDING`，保留 governing failure，而不提前创建 attempt。新 attempt 只有在实际操作开始时才生成 ID，并通过 `retry_parent_id` 指向同一 slot、同一 repeat 的失败或中止记录，保留完整 lineage。

## 3. 模型遗漏因素筛查

| 因素 | 观测方法 | 处理 |
|---|---|---|
| 支架振动 | support fiducials | 位移超过 2 倍位置标准不确定度时，固定支点假设失效 |
| junction 滑移或穿绳 | 材料 marker 相对 junction 运动 | 超过 2 倍相对位置不确定度时，no-slip 假设失效 |
| 弯曲或形状记忆 | branch centerline curvature | 超过重建噪声时记录为 bending candidate，不启动 HF-v3 |
| bob 自旋或偏心耦合 | rigid fiducials | 与摆动显著相关时降级点质量模型 |
| slack 或波传播 | centerline 与可选张力 | 立即终止该段 Torus 比较 |
| 接近或 contact | 3D 最小表面距离 | 停止幅度升级；先测事件，不开接触求解器 |
| release impulse | 初始速度与方向 | 重复性不足时先修 release mechanism |
| camera occlusion | `valid_mask` | 超过缺失门时重布相机 |
| calibration drift | batch start/end 标定板 | 超过标定不确定度时整批降级 |
| 环境扰动 | 温湿压与可选气流 | 作为 nuisance/assumption，不由拟合吸收 |

## 4. 硬停止码

- `STOP_SAFETY`；
- `STOP_CAMERA_CALIBRATION`；
- `STOP_SYNCHRONIZATION`；
- `STOP_INSUFFICIENT_FRAME_RATE`；
- `STOP_EXCESSIVE_OCCLUSION`；
- `STOP_SUPPORT_NOT_FIXED`；
- `STOP_JUNCTION_SLIP`；
- `STOP_SLACK_OR_CONTACT_ESCALATION`；
- `STOP_DATA_PIPELINE_FAILURE`；
- `CONTINUE_WITH_MODEL_LIMITATION`。

同步残差大于 0.25 frame、最快周期少于 30 samples、主要分析窗 3D bob 有效比例低于 95%，或出现安全问题时，不得进入 full round。

失败运行不删除、不覆盖。重试生成新 attempt ID，并保存 failure stage、reason code、operator note、corrective action、evidence state 和 retry parent ID；只有证据实际存在时才记录 camera rig 与 raw hashes。硬停止发生后，ledger 必须记录 governing stop attempt，并把后续尚未开始的 slot 逐一关闭为 `NOT_STARTED_DUE_TO_STOP`。

## 5. 当前复核门与下一人工门

E0R2 只修正采集台账、逐帧时间信息、跨产物来源绑定和派生输入可核验性，不执行 pilot。本轮实现必须先停止在 `E0R2_ACQUISITION_AND_PROVENANCE_CLOSURE_COMPLETE__STOP_AT_E0R2_PRO_REVIEW`。只有 Pro 接受 E0R2 后，下一门才可提升为 `HUMAN_PILOT_ACQUISITION_REQUIRED`。

届时人工仍必须完成装置与相机的实际操作，返回带原始数据和哈希的资料后，才可单独授权 `E1_PILOT_DATA_INGESTION_AND_MODEL_ASSUMPTION_SCREENING`。

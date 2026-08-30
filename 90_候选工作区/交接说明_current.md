# 当前交接：E0R 真实数据合同修正完成，停止于 Pro 复核

Pro 对初版 E0 的裁决为：

`E0_PRO_REVIEW_SUBSTANTIVE_PASS__HUMAN_PILOT_HOLD_PENDING_E0R_REAL_DATA_CONTRACT_CORRECTIONS`

本轮候选状态为：

`E0R_REAL_DATA_CONTRACT_CORRECTIONS_COMPLETE__STOP_AT_E0R_PRO_REVIEW`

正式高保真总状态继续保持：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

## 已完成

- 只在 `90_候选工作区/current/E0_实验准备与数据合同/` 完成 E0R；实现提交为 `3ab9dc0c4b90c04d39d7a6e5f4b004fe6bf10838`，已推送远程 `main`。
- 装置 schema/template 现可表达支点 XYZ、bob COM 偏置、几何、三主惯量、分支参数等标量或向量；组件标签、每次重复、值、不确定度与 covariance 维数必须一致，covariance 还必须有限、对称且半正定。
- 相机 `R_c` 在 schema 与消费者中统一为 $3\times3$ matrix；完整标定强制图像、时间、内外参、畸变、标定板、重投影、参数 covariance 和同步 residual/offset/jitter/raw hash 全部非空。`MEASURED_CALIBRATION` 与其他实测文档不得残留 `UNSET_REQUIRES_HUMAN`。
- 新增权威 acquisition attempt ledger，并将 pilot convenience CSV 展开为 12 个逐 repeat 首次 attempt；失败/中止保存阶段、原因码、原始哈希、纠正措施，retry 必须指向 ledger 中同一 slot/repeat 的失败 parent。
- 新增 2D detection bundle、逐 camera/marker/sample 的 $2\times2$ pixel covariance 与数值 Jacobian 传播；3D trajectory 固定保存 bob/junction 的 $3\times3$ covariance，并绑定上游视频、camera rig、detection manifest 与 NPZ 哈希。
- `YPS-EXPERIMENT-COMMON-OBSERVABLES-1.1` 的 NPZ 实际保存 time、bob/junction 世界坐标、冻结 modal basis、fast/slow coordinate、共振相位与 valid mask；不再只保存摘要。
- 第一轮 amplitude level 已机器冻结；正式输入不再接受只有来源标签的 map，而是绑定 measurement IDs、measurement bundle、所引记录、derivation、trajectory 和逐项兼容性 evidence 哈希。Torus 三个布尔判断均有独立 evidence SHA-256。
- damped-mode estimator 对 native interval 最大相对偏差大于 1% 的输入失败关闭；若将来使用 resampling，必须另行预注册并绑定配置哈希。
- 新增 `SYNTHETIC_REAL_SHAPE_FIXTURE` 端到端链：真实三维装置字段、完整相机 rig、两个 pilot repeat、失败与 retry、2D covariance 到 3D covariance、trajectory、common arrays、measurement-hash-bound 正式输入。负例覆盖残留 UNSET、缺 uncertainty/raw hash、伪来源标签、不完整标定、错误 retry、非对称/非半正定 covariance 和不规则采样。

## 已执行验证

- 精确 Python 3.12 环境：`35 passed in 9.50s`。
- Ruff 检查通过，28 个 Python 文件格式检查通过；`compileall` 通过。
- 阶段检查为 `E0R_REAL_DATA_CONTRACT_CORRECTIONS_COMPLETE__SYNTHETIC_REAL_SHAPE_FIXTURE_PASS__STOP_AT_E0R_PRO_REVIEW`，精确闭合 48 个文件、10 个 schema、7 个模板和 Git allowlist。
- 合成实形命令入口实际运行通过；双目与 covariance-aware 双目最大误差均约 `8.13e-13 m`，传播 covariance 最小特征值约 `9.38e-8 m^2`，两模态频率与同步恢复通过。
- 0.2.0 wheel 已隔离构建，在全新临时环境安装，并从 site-packages 实际运行同一 self-test 通过。
- 7 份阶段 Markdown 均通过 Pandoc `--from=markdown` 解析；合并文档以 MathML/Chrome 实际渲染为 19 页 PDF，完成全页缩略图与关键公式/表格页视觉检查，未见裁切、缺字或公式失效。
- 正式包源码哈希保持 `cd0dfdc2dbc1e88ef1b9b5b873bc76b403e13b87958a3efd2d842790632b5e0c`；理论哈希保持 `7eaf18e30087438507aef73c481b49e5b1427a146d79c0fd2b35ca10dc02cdb2`。

## 结论边界

最高结论仅为 `IMPLEMENTATION_AND_SYNTHETIC_REAL_SHAPE_FIXTURE_ONLY`。`SYNTHETIC_REAL_SHAPE_FIXTURE` 只证明合同与数组采用真实运行所需形状，不是实测。

没有填写真实装置参数，没有执行材料测量、相机标定、视频采集或 P00--P06，没有真实轨迹、数值资格升级、物理验证或实验验证。正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、F0/F1 和冻结证据均未修改；没有启动 HF-v3、P3R6、G3R5、接触资格重试、P4/P5/P6、动力学、RC1 扩展或无数据真实参数细调。

## 下一步

1. Pro 读取远程 `main` 上的 E0R 实现提交和本交接，独立复核实现、验证证据与结论边界；过程更新或思考摘要不算最终裁决。
2. 若 Pro 无新的阻断项，才可把下一门提升为 `HUMAN_PILOT_ACQUISITION_REQUIRED`。
3. 人工完成真实装置测量、标定、释放、安全判断和 pilot，并返回带原始数据与哈希的资料后，仍需用户另行明确授权，方可进入 `E1_PILOT_DATA_INGESTION_AND_MODEL_ASSUMPTION_SCREENING`。

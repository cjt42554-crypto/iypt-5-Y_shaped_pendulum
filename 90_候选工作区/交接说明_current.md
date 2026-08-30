# 当前交接：E0 实验准备实现完成，等待 Pro 独立复核后进入人工 Pilot 门

当前候选状态为：

`E0_EXPERIMENT_PREPARATION_IMPLEMENTATION_PASS__SYNTHETIC_ONLY__STOP_AT_HUMAN_PILOT_GATE`

正式高保真总状态继续保持：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

## 已完成

- 按 Pro 的只读规划，在 `90_候选工作区/current/E0_实验准备与数据合同/` 新增 41 个文件，形成实验要求复用矩阵、测量登记协议、70 条结果型运行预注册、相机/轨迹合同、Pilot 协议、E0-A1 至 E0-A10 验收矩阵、8 个 Draft 2020-12 schema、6 个未实测模板、候选处理程序、测试和阶段检查器。
- 实现提交为 `d1bb9ce6ce34f06831f6b09df20ae4d40fe177a6`。
- 70 条结果型运行均已预分配唯一 `run_id` 和首个 `attempt_id`；状态全部为 `NOT_RUN`，实际装置版本全部保持 `UNSET_REQUIRES_HUMAN`。
- Brown--Conrady 投影约定与正式求解器一致；双目重建对非有限相机参数、标定域外像素和镜后解失败关闭。
- 正式模型 adapter 只调用正式包公开的 `run_config` 与 `run_ensemble`。Cable 的 `EXPERIMENT_COMPARISON` 必要输入只接受 `MEASURED` 或 `DERIVED_FROM_MEASURED`；假设输入只可用于 `SENSITIVITY_ONLY`。

## 已执行验证

- 精确 Python 3.12 环境：`27 passed in 1.09s`。
- Ruff 检查通过，25 个 Python 文件格式检查通过；`compileall` 通过。
- wheel 构建、全新临时环境安装和安装后的 `yps-experiment self-test --synthetic-only` 实际运行通过。
- 合成自检状态为 `E0_SYNTHETIC_SELF_TEST_PASS__NOT_EXPERIMENT_EVIDENCE`；双目最大重建误差约 `8.13e-13 m`，两模态频率和同步偏移恢复通过。
- 阶段检查为 `E0_STAGE_CHECK_PASS__SYNTHETIC_ONLY`，精确闭合 41 个文件、8 个 schema、6 个模板和 Git allowlist。
- 正式包源码哈希为 `cd0dfdc2dbc1e88ef1b9b5b873bc76b403e13b87958a3efd2d842790632b5e0c`；理论哈希为 `7eaf18e30087438507aef73c481b49e5b1427a146d79c0fd2b35ca10dc02cdb2`。
- 7 份 E0 Markdown 均通过 Pandoc `--from=markdown` 解析；合并文档以 MathML/Chrome 实际渲染成 18 页 PDF，Pandoc 警告为零，并完成逐页抽查。

## 结论边界

最高结论仅为 `IMPLEMENTATION_AND_SYNTHETIC_FIXTURE_ONLY`。没有填写真实装置参数，没有执行材料测量、相机标定、视频采集或 P00--P06，没有真实轨迹、物理验证或实验验证。正式 `01_最终理论/**`、`02_模拟程序/**` 和顶层 `AGENTS.md` 未修改；没有启动 HF-v3、P3R6、G3R5、接触资格重试、P4/P5/P6、动力学、RC1 扩展或无数据真实参数细调。

## 下一步

1. Pro 读取远程 `main` 上的 E0 实现提交和本交接，独立复核实现、证据与结论边界；不得把思考摘要当成最终裁决。
2. 若 Pro 复核无阻断项，代码工作停止在 `HUMAN_PILOT_ACQUISITION_REQUIRED`。
3. 人工随后必须填写装置几何/质量/材料测量、相机 rig 与标定、原始文件哈希和不确定度，并实际执行 P00--P06。真实 Pilot 数据返回且用户另行明确授权以前，不得进入 `E1_PILOT_DATA_INGESTION_AND_MODEL_ASSUMPTION_SCREENING`。

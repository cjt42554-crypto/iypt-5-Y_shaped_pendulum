# 交接说明（current）

更新时间：2026-08-27 17:45 +0800（HF-v2 G2R 候选完成，退役残留已清理，等待 Pro 复审）

## 1. 当前裁决状态

G2R 候选已完成，机器证据状态为：

`G2R_CANDIDATE_PASS_PENDING_PRO_REVIEW`

允许的最高表述为：

`G2R_CANDIDATE_PASS_PENDING_PRO_REVIEW__HF_NUMERICAL_QUALIFICATION_NO_GO`

这不是 Pro 批准。正式数值资格仍为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

P3 静态硬接触、P4 动力学、P5 活动集、P6 动态接触和后续阶段均为：

`CLOSED_PENDING_PRO_REVIEW`

## 2. 本轮完成事项

1. 以本地提交 `7a19702` 在任何 G2R 目标运行前冻结身份、中心线、无量纲诊断和历史等价性协议。
2. 保留历史 `G2_REPORT.md`、`g2_metrics.json`、G2 冻结协议和验收清单字节不变；版本化披露原 G2 模块清单变化和闭合审计后验修正。
3. 将兼容字段名 `layout_token` 的语义修正为坐标解释与完整静态物理组装的单一 SHA-256 身份，覆盖节点种类/附件、切片、参考姿态、旋转图、支点、材料、质量、摆球和环境。
4. 增加四类真实跨组装测试：参考姿态、连接/规定节点身份、支点位置和重力。所有变体 token 均改变，外来坐标均失败关闭。
5. BFGS 调用显式传入 `c1=1e-4`、`c2=0.9` 及其余冻结选项；测试实际捕获传入映射。
6. 首次试用历史 SciPy 1.11.4 时发现其忽略 `c1`、`c2` 并报告未知选项。该 `/tmp` 运行整体作废。以本地提交 `8adc7f5` 在第一次有效重跑前冻结 G2R-A1：最低 SciPy 修正为 1.12，未知求解器选项失败关闭，有效目标环境绑定 CPython 3.12.3、NumPy 2.5.2、SciPy 1.18.1。
7. 在每条支路 129 个公共归一化材料坐标点上比较完整中心线。左、右、下支 4→8/2→4 差值比分别约为 `0.2497244`、`0.2497244`、`0.2489830`，全部 PASS。
8. 增加逐段工程应变、当前长度中的伸长占比和当前长/静长比。三网格全部有限，代数恒等式最大误差 `1.7347e-18`。
9. 修正前后能量、宏观形状、全部段张力、两支点反力和最小非规范 Hessian 特征值在三个网格上均为精确浮点零差，满足预冻结等价门。
10. 没有改变物理方程、Y 形锚点、三个种子、2/4/8 网格、BFGS 方法、选择规则或既有通过阈值。

## 3. 证据与复现

主要工件：

- `90_候选工作区/current/HF-v2-core/contracts/G2R_FROZEN_PROTOCOL.md`；
- `90_候选工作区/current/HF-v2-core/contracts/G2R_PROTOCOL_DEVIATIONS.md`；
- `90_候选工作区/current/HF-v2-core/contracts/G2R_RUNTIME_AMENDMENT.md`；
- `90_候选工作区/current/HF-v2-core/contracts/g2r_acceptance_manifest.json`；
- `90_候选工作区/current/HF-v2-core/contracts/g2r_runtime_amendment.json`；
- `90_候选工作区/current/HF-v2-core/reports/g2r_metrics.json`；
- `90_候选工作区/current/HF-v2-core/reports/G2R_REPORT.md`。

`g2r_metrics.json` 的 SHA-256 为：

`c9fa31a59ab68ce83eae24760dfdf07be818dc10d2d79ce8487260de3c8967df`

在 `90_候选工作区/current/HF-v2-core/` 使用绑定环境复现：

```bash
python tools/generate_g2r_evidence.py --check
python -m pytest -q
ruff check src tests tools
python -m compileall -q src tests tools
```

已完成：

- G2R 证据逐字节 `--check`：PASS；
- 全量测试：`72 passed`；
- Ruff、`compileall`、JSON、`git diff --check`：PASS；
- 新增/实质改写 Markdown 的 Pandoc `markdown` reader 解析：PASS；
- Pandoc standalone HTML 生成：PASS。

未完成浏览器视觉截图检查：命令行 Chrome 三次没有生成截图文件，内置浏览器安全策略拒绝本地 `file://` 页面且禁止换表面绕过。没有把 HTML 生成写成视觉验收通过。

## 4. 下一次唯一任务：Pro G2R 独立复审

下一次只允许 Pro 独立复审当前 G2R 候选，重点核对：

1. 单一完整 token 的字段是否完备，四类真实跨组装互拒是否覆盖裁决反例；
2. SciPy 1.11.4 作废试算和 G2R-A1 运行时附录的时间顺序是否可接受；
3. `c1`、`c2` 是否在受支持运行时中实际进入 BFGS；
4. 历史 G2 工件是否保持不变，协议偏离是否披露充分；
5. 129 点三支路中心线趋势、无量纲段诊断和历史等价性是否足以关闭 G2R；
6. 是否批准状态 `G2R_PRO_REVIEW_PASS__NO_CONTACT_STATIC_ALGORITHM_ONLY`。

在 Pro 明确批准且用户再次明确要求继续之前，不得实现或运行 P3，也不得把 G2R 候选 PASS 提升为正式数值资格、物理验证或实验验证。

## 5. 仓库与外部状态

- 正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、UI、公共 API 和 HDF5 均未修改。
- 现行候选写入只发生在 `90_候选工作区/current/HF-v2-core/**` 和两份交接文件。
- 经用户明确授权，已将整个退役旧目录 `current/三锚点高保真资格/` 移入系统回收站。清理前该目录约 `2.1 GiB`，含 12,009 个普通文件和 4 个符号链接；工作区中已不存在该路径。
- 未推送异常提交 `c08cfa6` 曾将其中 388 个生成文件、106,580 行文本误纳入本地历史。该提交已从 `main` 撤下，未进入远端；其父提交 `ff02bee` 及此前两个 G2R 提交保持不变。
- 撤下异常提交后，普通 `git push origin main` 已成功将预期 G2R 提交链从 `5612940` 推送至 `ff02bee`。先前界面显示的 `pre-receive hook declined` 是 GitHub 远端拒绝当时聚合更新，不是仓库 `AGENTS.md` 或本地 Git hook；缺失完整 `remote:` 诊断，未臆测具体远端规则。

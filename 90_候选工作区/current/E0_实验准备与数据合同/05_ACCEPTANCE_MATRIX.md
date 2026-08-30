# E0R2 验收矩阵

## 1. 验收门

| 门 | Codex 必须证明 | 不代表什么 |
|---|---|---|
| E0-A1 | 全部 schema 通过 Draft 2020-12 自校验，未知字段失败关闭 | 不代表已有实验数据 |
| E0-A2 | 全部模板合法且没有伪造实测值 | 不代表装置可制造 |
| E0-A3 | 合成 Brown--Conrady 双目重建恢复已知轨迹 | 不代表真实相机标定通过 |
| E0-A4 | 合成频率、相位、阻尼和闭合量恢复通过 | 不代表真实模态已测 |
| E0-A5 | Torus/Cable adapter 只加载正式 forward package | 不代表两个模型正确 |
| E0-A6 | 缺失输入与模型域退出全部失败关闭 | 不代表已获得完整 Cable 输入 |
| E0-A7 | 不确定度与 comparison 输出合同闭合 | 不代表物理验证 |
| E0-A8 | pilot 协议和第一轮计划已经预注册 | 不代表 pilot 已执行 |
| E0-A9 | Markdown、Pandoc、代码和实际渲染检查完成 | 不代表科学结论 |
| E0-A10 | Git 差分严格位于 allowlist | 不代表正式树发生变化 |
| E0R-A11 | 向量装置量与相机 $3\times3$ rotation 在 schema/consumer 中形状一致 | 不代表已有真实尺寸或标定 |
| E0R-A12 | pilot repeat、失败、纠正措施和 retry lineage 由 attempt ledger 闭合 | 不代表任何 pilot 已执行 |
| E0R-A13 | 合成实形 fixture 闭合 2D covariance 到 3D covariance、trajectory 和 common arrays | 不代表真实 tracking uncertainty 已测 |
| E0R-A14 | 正式输入绑定 measurement IDs、bundle/record/derivation/trajectory/evidence 哈希 | 不代表正式模型通过物理验证 |
| E0R-A15 | 不规则采样、残留 UNSET、缺失 uncertainty/raw hash 和伪来源标签失败关闭 | 不代表真实数据质量合格 |
| E0R2-A16 | 12 个计划 slot 与实际 attempt 分层记录；未开始 slot 无伪时间、raw、camera hash 或 attempt ID，campaign 可在未来 slot 或 `RETRY_PENDING` 待执行时保持 `IN_PROGRESS` | 不代表已经开始 pilot |
| E0R2-A17 | P00 等 setup/calibration 可在尚无有效 rig 或 raw file 时以 `NO_RAW_DATA_CREATED` 失败；硬停止后的未来 slot 以 `NOT_STARTED_DUE_TO_STOP` 关闭 | 不代表失败可以丢失原因或 lineage |
| E0R2-A18 | 每个 sample 和 camera 都机器记录 frame index、raw/aligned timestamp、sync event、offset、uncertainty、drop flag 与可区分 invalid reason | 不代表真实同步精度已经合格 |
| E0R2-A19 | detection 到 trajectory、trajectory 到 common observables 都解析并验证上游 manifest，核对实际 NPZ 哈希、字段、时间/位置轴与 run/attempt/apparatus/camera/origin 身份 | 不代表链上数据本身物理正确 |
| E0R2-A20 | 任一 `data_origin=MEASURED` 产物残留 `UNSET_REQUIRES_HUMAN` 时失败关闭；派生正式输入的哈希绑定实际 canonical derivation 内容、方法和输入记录 | 不代表派生方法已经通过实验验证 |
| E0R2-A21 | 错误 camera hash、run、attempt、apparatus，空上游 `{}`、measured+UNSET、P00 无证据失败和 pilot 中途硬停止均有正向或负向自动测试 | 不代表已覆盖所有未来现场故障 |

## 2. 建议验证命令

```bash
E0='90_候选工作区/current/E0_实验准备与数据合同'

python3 -m pytest -q "$E0/tests"
ruff check "$E0"
python3 -m compileall -q "$E0/src" "$E0/tests" "$E0/tools"

PYTHONPATH="$E0/src" \
python3 -m yps_experiment_pipeline self-test --synthetic-only

python3 "$E0/tools/check_stage.py" --repository-root .

find "$E0" -type f -name '*.md' -print0 | \
while IFS= read -r -d '' file; do
  pandoc --from=markdown --to=json "$file" >/dev/null || \
    exit 1
done

git diff --check
git status --short
```

`check_stage.py` 同时检查精确文件闭包、模板来源、冻结 amplitude matrix、计划 slot/实际 attempt 分层、P00 无证据失败和 pilot 中途硬停止 fixture、逐帧时间字段、跨产物来源绑定、派生内容哈希、合成实形 fixture、禁止伪造 `MEASURED`、正式包只读适配、无第二套 ODE、状态上限、文档越界措辞和 Git allowlist。

## 3. 停止门

全部 E0-A1 至 E0-A10、E0R-A11 至 E0R-A15 与 E0R2-A16 至 E0R2-A21 通过后，本轮最高状态固定为：

`E0R2_ACQUISITION_AND_PROVENANCE_CLOSURE_COMPLETE__STOP_AT_E0R2_PRO_REVIEW`

Pro 接受 E0R2 后，下一门才可提升为 `HUMAN_PILOT_ACQUISITION_REQUIRED`。在人工 pilot 返回以前继续禁止 HF-v3、P3R6、G3R5 重启、静态接触认证重试、P4/P5/P6、RC1 扩展、动力学或接触资格升级、无数据真实参数细调，以及任何物理或实验 PASS。

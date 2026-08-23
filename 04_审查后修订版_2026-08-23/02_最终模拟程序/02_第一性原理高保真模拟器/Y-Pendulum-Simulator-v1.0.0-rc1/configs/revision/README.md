# 修订模型配置与执行边界

`hf-bilateral-explicit-ei-baseline.yaml` 只把旧后端隐含的几何
`EI=Eπd⁴/64` 显式写出，便于消融和审计。它不是实验标定结果，
也不能让运行自动获得 `CODE_VERIFIED`。

overlay 的 `requested_analysis_level` 只表达用户请求的分析目标。运行包会独立输出：

```text
model_claim_ceiling
requested_analysis_level
actual_evidence_level
evidence_bundle_sha256
downgrade_reasons
```

无同提交、全绿且身份完整的机器证据包时，
`actual_evidence_level` 必须是 `MODEL_CONSISTENT`。禁用接触护栏、工作树脏、
源码提交不匹配或输入哈希不完整都会失败关闭。

单次 HF 运行：

```bash
PYTHONPATH=src python -m ypendulum.scientific_revision run-hf \
  --config configs/examples/high_fidelity_shared_forward_window.yaml \
  --overlay configs/revision/hf-bilateral-explicit-ei-baseline.yaml \
  --output runs/revision/hf-explicit-ei
```

它会把已验证的 overlay 原始字节、规范 JSON、配置原始字节及各自 SHA-256
封存在运行包 `inputs/` 内。GUI worker 之后只向子进程传递该封存副本。

低成本 M0–M5 和事件矩阵必须从运行前生成的计划执行：

```bash
python scripts/materialize_corrective_smoke_plans.py /tmp/yps-smoke-plans

python -m ypendulum.scientific_revision execute-ablation \
  --plan /tmp/yps-smoke-plans/ablation/ablation-plan.yaml \
  --output /tmp/yps-ablation-smoke

python -m ypendulum.scientific_revision execute-event-qualification \
  --plan /tmp/yps-smoke-plans/event/event-plan.yaml \
  --output /tmp/yps-event-smoke
```

两个执行器要求干净工作树且计划 `git_commit` 与当前提交完全一致。
M0 调用 FWD，M1–M5 读取同一份封存 HF 离散材料状态。事件执行器
直接生成 N/2N/4N、时间、输出和 Radau/BDF 矩阵；已有运行的比较命令
`compare-event-runs` 只是诊断器。

上述 1–2 ms 运行仅证明执行、身份绑定、白名单和失败关闭路径可用；
不是生产数值资格、实验验证或预测资格。


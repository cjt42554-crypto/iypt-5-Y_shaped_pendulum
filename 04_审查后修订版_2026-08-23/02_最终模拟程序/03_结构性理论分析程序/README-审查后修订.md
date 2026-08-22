# 结构性理论审查后工具

原 `torus_structure_analysis.py` 保留。新增 `structural_evidence_audit.py` 只审计有限窗证据边界，不重新计算原结果。

示例：

```bash
python structural_evidence_audit.py \
  '../../03_项目资料/05_验证证据与研究结果/结构性理论/results/structural_analysis_results.json' \
  structural-evidence-audit.json
```

输出始终把“有限窗闭合”“锁频”“不变环面证明”和“连续参数域证明”分开。

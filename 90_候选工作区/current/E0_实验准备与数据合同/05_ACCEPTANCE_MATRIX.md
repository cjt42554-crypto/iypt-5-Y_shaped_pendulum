# E0 验收矩阵

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

`check_stage.py` 同时检查精确文件闭包、模板来源、禁止伪造 `MEASURED`、正式包只读适配、无第二套 ODE、状态上限、文档越界措辞和 Git allowlist。

## 3. 停止门

全部 E0-A1 至 E0-A10 通过后，最高状态固定为：

`E0_EXPERIMENT_PREPARATION_IMPLEMENTATION_PASS__SYNTHETIC_ONLY__STOP_AT_HUMAN_PILOT_GATE`

下一门为 `HUMAN_PILOT_ACQUISITION_REQUIRED`。在人工 pilot 返回以前继续禁止 HF-v3、P3R6、G3R5 重启、静态接触认证重试、P4/P5/P6、RC1 扩展、动力学或接触资格升级、无数据真实参数细调，以及任何物理或实验 PASS。

# 当前交接

更新时间：2026-08-26T18:45:38+08:00

## 已完成

- 在完整仓库环境执行 `compression_limit/build_alpha_specific_candidate.py`。正式 `validation.py` 与 `solver.py` 的两个预冻结 Git blob 均匹配，五个源码替换点各唯一命中；隔离覆盖层可导入，`alpha=1e-2`、`1e-4`、`1e-6` 三份 `OUT_OF_SCOPE` 配置均通过覆盖层配置验证。
- 按统一局部尺度原则完成全部 11 项正式公开守卫的候选 v2 分类和实现：逐段长度/弦长按对应材料静长，实体净空按本地所需中心距，套筒材料余量按套筒静长，摆球套筒径向点积按局部方向余弦；转角与投影开口保留原生无量纲尺度 1。
- 在任何新准备态运行前冻结 `guard_contract_v2/full_spec.json`、`guard_contract_v2_full.py` 与 `tests/test_guard_contract_v2_full.py`。规格、实现和测试 SHA-256 分别为 `5b5547df...`、`148c81bf...`、`10feaaa9...`；冻结时新 `alpha` 准备态数量为 0。
- 重新制备 `4:3`、`3:2`、`2:1` 的三层 `alpha=1` 状态，并用冻结完整 v2 复核。九个状态全部通过；最小观测裕量为 `4:3` 粗层的 `ROD_SELF_CLEARANCE = 6.9949148466e-3`。合同和正式源码身份在运行前后稳定。
- 冻结并执行三个 `alpha<1` 的同端点、多种子、无跨尺度热启动准备态计划。通过数为 `0/3`，所以 `dynamic_gate_open=false`，动态运行数为 0：
  - `alpha=1e-2`：三个种子达到 `1e-8 N` 残差门，最小 Hessian 特征值约 `+8.577e-3 N/m`，但原始 `ROD_SELF_CLEARANCE` 约为 `-0.07665 mm`；
  - `alpha=1e-4`：四个种子均耗尽迭代，最好残差约 `2.424e-5 N`，原始杆自净空约 `-0.834` 至 `-1.399 mm`；
  - `alpha=1e-6`：四个种子均耗尽迭代，最好残差约 `2.428e-5 N`，原始杆自净空约 `-0.878` 至 `-1.383 mm`。
- 完成只增加失败审计字段的隔离复现。三个尺度所有种子的唯一非正原始分量均为 `ROD_SELF_CLEARANCE`；能量、残差、Hessian 摘要和首轮逐项一致。该复现不改变目标函数、优化器、守卫判定、候选选择或异常行为。
- 用完整根因报告重生成旧两分量 `evaluation.json`，修复此前隔离环境因缺少根因文件而跳过后未暴露的生成器--保存文本不一致；数值和状态未改变。
- 在任何中间 `alpha` 结果出现前冻结 10 点预接触边界图：`[1e-2,1]` 两端加 8 次几何中点二分，每点使用新进程、相同多种子、无跨尺度热启动，动力学数为 0。10 点均有 3 个力平衡半正定候选，主判据保持失败到通过的单调次序。
- 完整候选准备态资格边界为失败 `0.03924189758484536` / 通过 `0.039954205589498866`；原始杆自净空边界为非正 `0.03651741272548377` / 正 `0.03924189758484536`。后一个上界虽原始余量约 `+0.556 μm`，候选归一化裕量仍只有 `1.7375e-4`。
- 对最低采样合格上界独立重制备并完成正式残差、完整 v2、三步长 240 维梯度 Hessian 和独立能量曲率交叉检查。精确状态残差 `9.4954e-10 N`，三步长最小特征值均约 `+0.00756243 N/m`，初态候选最小裕量 `3.41483e-4`。
- 冻结并执行唯一一次该精确状态的 `0.12 s` 无接触动力学。15,361 个展示样本和 16,274 个接受态完整返回，未出现正式原始守卫零事件；候选 v2 最后通过/首次失败区间为 `0.0248359375--0.02484375 s`，失败分量为 `ROD_SELF_CLEARANCE`。未运行接触后延拓。

## 主要新增证据

- `90_候选工作区/current/三锚点高保真资格/guard_contract_v2/full_spec.json`
- `90_候选工作区/current/三锚点高保真资格/guard_contract_v2/prefreeze.json`
- `90_候选工作区/current/三锚点高保真资格/guard_contract_v2/full_mesh_audit.json`
- `90_候选工作区/current/三锚点高保真资格/guard_contract_v2_full.py`
- `90_候选工作区/current/三锚点高保真资格/compression_limit/alpha_specific_preparation_run_plan.json`
- `90_候选工作区/current/三锚点高保真资格/compression_limit/alpha_specific_preparation_results.json`
- `90_候选工作区/current/三锚点高保真资格/compression_limit/failed_preparation_guard_diagnostic.json`
- `90_候选工作区/current/三锚点高保真资格/compression_limit/precontact_boundary_spec.json`
- `90_候选工作区/current/三锚点高保真资格/compression_limit/precontact_boundary_results.json`
- `90_候选工作区/current/三锚点高保真资格/compression_limit/precontact_upper_gate/preparation_result.json`
- `90_候选工作区/current/三锚点高保真资格/compression_limit/precontact_valid_prefix_dynamic_results.json`
- `90_候选工作区/current/三锚点高保真资格/decision.md`

## 已执行验证

- `.venv/bin/python -m pytest -q tests`：`44 passed`。
- 新增 Python 文件均通过 `.venv/bin/python -m py_compile`。
- 完整 v2 先验冻结前定向测试：`7 passed`；覆盖全部 11 分量、正式原始值复算、相似缩放、材料细化和原始零/负值失败关闭。
- 九个 `alpha=1` 准备态均重新运行并通过完整候选 v2；三个 `alpha<1` 准备态和三次观测性失败复现均已执行。
- 10 点静态边界图、最低合格上界重制备和唯一一次 `0.12 s` 动力学均按各自预冻结计划执行；所有运行前后绑定检查通过。
- 动力学 HDF5 与积分检查点分别约 158.1 MB 和 126.5 MB，SHA-256 与结果 JSON 一致；HDF5 模型、状态、有效区间和样本维数已重新读取核对。
- 正式源码、生成覆盖层源码、冻结候选输入和各运行计划的运行前后身份检查均通过。
- `decision.md` 与候选 `README.md` 使用 Pandoc 3.1.3 的 `--from=markdown --fail-if-warnings` 解析为独立 HTML，通过；使用 Google Chrome 无头渲染并实际检查表格和正文布局。
- `rg -n '[[:blank:]]+$|\t' decision.md README.md` 无输出。
- Ruff 0.16.4 全目录扫描已执行但未全通过：共 34 项，分别为导入排序 19 项、既有脚本 shebang 与执行位不一致 8 项、现代类型导入 2 项、未使用局部变量 2 项、有意失败关闭的宽异常捕获 1 项、相邻配对风格 1 项和无效 `noqa` 1 项。新增边界与动力学文件单独扫描通过；为保持既有冻结结果与预运行字节哈希绑定，本轮未在看到结果后批量改写旧文件。

## 未执行或未通过

- 原定 `alpha=1e-2`、`1e-4`、`1e-6` 三目标准备态均未通过，因此原计划仍未执行任何目标尺度动力学；后续边界协议只对另行合格的 `alpha=0.039954205589498866` 执行了一条单次短窗动力学。
- 原定三个目标尺度的三步长 240 维 Hessian 与独立能量方向曲率交叉检查没有取得结果：三个尺度都在进入该门前失败。`alpha=1e-2` 仅由既有正式准备器对三个力平衡种子完成单步 Hessian 审计；另行合格的边界上界已经完成三步长交叉检查。
- 未运行 `SHARED_ALPHA1_STATE_CONSTITUTIVE_QUENCH` 敏感度；它不是主制备身份。
- 未重跑正式程序全测试套件；正式程序字节未修改，本轮验证集中于候选覆盖层、实际准备态和候选测试。
- 未重跑历史空间动力学、连续接受步证书、时间细化、双积分器矩阵、长窗模态、实验校准或盲验证。
- 边界动力学没有连续候选守卫证书；`0.0248359375--0.02484375 s` 只是展示网格失败括号。正式返回仍为 `UNDETERMINED / SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED`。
- Ruff 全规则未通过，具体 34 项如上；未安装或执行 Black。
- 暂存后的全量 `git diff --check` 有 1 项：预冻结文件 `tests/test_precontact_boundary_map.py` 末尾多一个空行。该测试的精确 SHA-256 `7b18ae73...` 已在任何边界样本出现前绑定到 `precontact_boundary_prefreeze.json`，为保持先验冻结证据未在结果出现后改写；排除该文件后的其余暂存差异检查通过。

## 当前结论

- 正式高保真数值资格仍为 `HF_NUMERICAL_QUALIFICATION_NO_GO`。完整候选 v2 的九准备态 PASS 不改变历史空间 Cauchy 超限、`4:3` 事件不稳定、连续证书不完整和历史源码端点探针无效。
- 完整 11 分量局部尺度候选合同已实现并完成 `alpha=1` 九网格准备态审计，但尚未获授权提升到正式程序或正式验证规格，也未获得连续动态资格证书。
- 当前无接触约束的 `ALPHA_SPECIFIC_HELD_EQUILIBRIUM` 主路线在三个 `alpha<1` 尺度均为准备态 `NO-GO`。`alpha=1e-2` 的决定性失败是力平衡、正 Hessian 形态进入正式杆自接触域；增加迭代数不能解决该原始几何失败。
- 当前无接触准备态资格边界已定位在约 `0.03924--0.03995`。最低合格上界的单次释放虽然全窗未触发原始接触零事件，但在约 `24.84 ms` 失去候选数值裕量；这不构成完整动态资格。
- `alpha=0` 仍只是数学本构端点；没有实现严格单边绳索互补问题，也没有数值压缩极限趋势。
- 正式理论、正式模拟程序、顶层 `AGENTS.md` 和既有目录结构均未修改。

## 下一步

1. 需要用户或模型负责人裁决：终止于当前无接触边界；建立含静态 KKT 反力和动态互补/冲量的硬接触模型；或建立带刚度、阻尼、摩擦参数及校准要求的柔顺接触模型。只在静态制备增加不穿透约束、释放后仍使用无接触动力学是不自洽的。
2. 若需要第二条敏感度实验，可单独冻结并运行 `SHARED_ALPHA1_STATE_CONSTITUTIVE_QUENCH`；必须明确它回答瞬时材料律突变，不能替代各 `alpha` 自身平衡初态。
3. 若要把完整守卫 v2 或任何接触模型提升到正式程序，先取得用户对 `02_模拟程序/**` 和正式验证规格的明确修改授权，然后从头重跑连续动态资格；候选覆盖层不得暗中替代正式代码。
4. 继续扫描更大的 `alpha` 不会解决目标 `1e-2`、`1e-4`、`1e-6` 已位于当前无接触准备态域之外的问题，故不列为自动后续。
5. 历史数值主线仍需修复探针后重跑空间诊断、取得连续接受步证书，并补时间细化、双积分器、长窗及实验校准/盲验证。

## 已知的非本轮失败

此前包含桌面应用与问题插件的扩展定向回归为 26 项通过、1 项失败。失败由正式前向程序缺少 `validation/delivery_root.json` 引起，触发点是 `configs/unified_shared_forward_case.yaml`；本轮未复跑，也未伪造或补写该验证证据。

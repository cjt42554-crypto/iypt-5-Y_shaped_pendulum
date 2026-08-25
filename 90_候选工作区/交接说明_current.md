# 当前交接

更新时间：2026-08-26T04:00:41+09:00

## 已完成

- 在 `90_候选工作区/current/三锚点高保真资格/` 冻结 `4:3`、`3:2`、`2:1` 三个锚点的 `0.12 s` 生产配置；每锚点 53 项柔索--高保真共享输入审计通过。
- 对三个锚点的 `6/6/8`、`12/12/16`、`24/24/32` 三个正式验证空间层级完成准备态审计和 9 个动态运行。三个锚点均为 `SPACE_CAUCHY_DIAGNOSTIC_NOT_DEMONSTRATED`；历史空间包装器的源码端点探针因重复拼接 `src/` 而实际哈希空树，原始空间结果未追写。
- 完成九个准备态的守卫根因分解。所有 `ROD_SELF_CLEARANCE` 极小值均来自下支同支局部材料排除边界，原始净空为正；`2:1` 还存在 `BOB_SOCKET_RADIAL_MONOTONICITY` 的全局长度平方归一化失败，但原始点积和局部径向增量余弦均为正。
- 完成 `4:3` 压缩正则化预检。正式配置与制备合同拒绝 `alpha<1` 的定端平衡；保持同一端点的几何直置因下支弦长比材料静长短 `1.580 mm` 而不可用。上一轮只做过同一 `alpha=1` 状态上的瞬时本构重算，没有生成非法配置或运行动态。

## 本轮新增

- 在 `decision.md` 裁决守卫资格的设计原则：保持原始守卫、接触域、零穿越语义和数值阈值 `3e-4` 不变；资格裕量应按定义该失效模式的局部几何尺度无量纲化，而不是按无关的整机特征长度归一化。
- 新增 `guard_contract_v2.py`、`guard_contract_v2/spec.json` 和 `guard_contract_v2/evaluation.json`，可复现地重算两项已有完整局部根因数据的分量：
  - `ROD_SELF_CLEARANCE` 使用原始净空除以相应局部所需中心距；
  - `BOB_SOCKET_RADIAL_MONOTONICITY` 保留每单元 `r·Δr>0` 原始符号门，并使用局部方向余弦作为无量纲裕量。
- 九个准备态在“两项局部重归一化 + 其余 v1 元数据”的混合诊断下全部通过。不过这不是完整 v2 合同通过：其余分量尚未完成统一的网格客观性审计，尤其 `MINIMUM_SEGMENT_LENGTH` 与 `AERODYNAMIC_CHORD_LENGTH` 也是逐单元量。禁止只因当前失败已消失就提升正式资格。
- 裁决 `4:3` 的 `alpha<1` 主制备身份为 `ALPHA_SPECIFIC_HELD_EQUILIBRIUM`：固定两支点、接点、摆球质心、姿态与附件端点，在每个 `alpha` 下独立执行确定性多种子保守能量最小化。`SHARED_ALPHA1_STATE_CONSTITUTIVE_QUENCH` 仅作为第二条敏感度实验；改变端点的制备不作为主方案。
- 新增隔离候选实现 `compression_limit/build_alpha_specific_candidate.py`。它不会修改正式目录；只在忽略的 `generated/` 覆盖层中，对已冻结的正式 Git blob 做精确单次替换：
  - `ypendulum/config/validation.py`：`7b66ae8c54a507c974d69be9ded05267dbb21439`；
  - `ypendulum/hf/solver.py`：`325ad43aa8088a55defeae9851c9ccfa508fe936`。
- 冻结三个 `OUT_OF_SCOPE` 候选配置：`alpha=1e-2`、`1e-4`、`1e-6`。相对 `configs/4to3.yaml` 只允许改变运行名、输出目录、声明等级、压缩正则化尺度和受控极限标志；初态端点、网格、物理参数与求解器容差均保持不变。
- 冻结 `compression_limit/alpha_specific_protocol.json` 与 `alpha_specific_plan.json`。对 `alpha<=1e-4` 额外要求 Hessian 符号对有限差分步长或独立负曲率方向探针稳定，避免沿用 `alpha=1` 刚度尺度掩盖近零压缩模态。
- 更新候选 `MANIFEST.sha256`，纳入本轮所有脚本、规格、计划、配置、评价和测试文件。

## 已执行验证

- `pytest -q tests/test_candidate_contracts.py`：`6 passed, 2 skipped`。
- 两项跳过均为当前隔离工作目录缺少完整仓库运行材料：
  1. 未挂载 `results/guard_root_cause.json`，因此没有在本地重新生成并逐字比较保存的两分量评价；保存评价由已冻结机器可读根因数据构造，仓库内测试会在完整目录中执行该一致性检查。
  2. 未挂载正式 `02_模拟程序/**` 源码树，因此没有在本地执行精确 blob 覆盖层的实际构建与导入验证；脚本只接受上述两个冻结 blob，漂移即失败关闭。
- 新增 Python 文件均通过 `python -m py_compile`。
- 三个 YAML 配置已解析，并验证相对基准只改变五个预冻结叶字段。
- 未安装或未执行 `ruff`、`black`。
- 未执行覆盖层配置验证、`alpha<1` 平衡制备、动态积分、连续守卫证书、空间重跑或长窗分析。

## 当前结论

- 正式高保真数值资格仍为 `HF_NUMERICAL_QUALIFICATION_NO_GO`。两分量候选重归一化不改变既有空间 Cauchy 超限、`4:3` 事件不稳定、连续证书不完整和历史源码端点探针无效。
- 守卫裁决目前只达到“局部尺度原则已确定、两项已实现并完成准备态混合诊断”。全分量网格客观性审计完成前，不得称为完整 v2 资格合同，更不得把九个历史准备态追溯改判为正式 PASS。
- `4:3` 的 `alpha<1` 已完成制备身份裁决、候选覆盖层实现和配置预冻结，但覆盖层尚未在完整仓库环境执行，三个 `alpha<1` 平衡和动态轨迹均为未运行。不得声称压缩极限趋势已经得到数值结果。
- `alpha=0` 仍只作为数学本构端点；现有可执行候选的最小正尺度是 `1e-6`，不把光滑正则化极限等同于已经实现的严格单边绳索互补问题。
- 正式理论、正式模拟程序和顶层 `AGENTS.md` 均未修改。

## 下一步

1. 在完整仓库运行 `compression_limit/build_alpha_specific_candidate.py`，先验证两个正式 blob 身份、精确替换唯一性、覆盖层可导入性以及三个候选配置可通过受控极限验证；任何源码漂移或多重匹配均失败关闭。
2. 按统一局部尺度原则审计全部守卫分量，至少补齐逐单元长度/弦长、摆球--杆净空、套筒材料余量与接点套筒净空的网格客观归一化；在看到新运行结果前冻结完整规格和测试。
3. 只运行三个 `alpha<1` 的定端准备态，不先跑动态。逐尺度核验自由材料力残差、多种子最低能量选择、Hessian PSD 与小 `alpha` 条件数敏感性、原始守卫正性、完整候选资格和制备审计身份。
4. 只有准备态全部通过后，才运行 `0.12 s` 主制备动态，并与共享 `alpha=1` 状态的本构突变敏感度严格分开；比较压缩物质区间、事件、能量账和外部轨迹。
5. 若候选结果支持正式提升，必须先取得用户对 `02_模拟程序/**` 的明确修改授权，再实施正式补丁并从头重跑资格；候选覆盖层不得暗中替代正式程序。
6. 后续仍需用已修复探针重跑空间诊断、取得可返回的连续接受步证书，再补时间细化、双积分器矩阵、长窗模态收敛及实验校准/盲验证。

详细证据与复现入口见 `90_候选工作区/current/三锚点高保真资格/decision.md`、`guard_contract_v2/`、`compression_limit/alpha_specific_protocol.json`、`compression_limit/alpha_specific_plan.json` 和 `tests/test_candidate_contracts.py`。

## 已知的非本轮失败

此前包含桌面应用与问题插件的扩展定向回归为 26 项通过、1 项失败。失败由正式前向程序缺少 `validation/delivery_root.json` 引起，触发点是 `configs/unified_shared_forward_case.yaml`；本轮未复跑，也未伪造或补写该验证证据。

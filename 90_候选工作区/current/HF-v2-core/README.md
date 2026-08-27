# HF-v2 候选核心与 G2R 无接触静力学修正

本目录是模型 `HFV2-DISCRETE-CORD-RIGID-BOB-0.2-CANDIDATE` 的独立候选包。它与正式 RC1 后端并行存在，不修改或替代 `HF-DISCRETE-ROD-RIGID-BOB-1.0`。原 `0.1-CANDIDATE` 的 G1 工件、Pro 已接受的 `0.2-CANDIDATE` G1R 工件和未获 Pro 批准的 G2 工件均作为历史证据保留。

当前完成范围是 P2 无接触静力学的 G2R 修正候选。静态硬接触、时间积分、活动集、动态接触、公共 API 适配、HDF5、UI 和正式资格认证均未实现。

## 当前状态

G2R 本地候选证据状态为：

`G2R_CANDIDATE_PASS_PENDING_PRO_REVIEW__HF_NUMERICAL_QUALIFICATION_NO_GO`

该状态只表示 G2R 预冻结门在绑定的本机环境中通过，不是 Pro 批准。正式高保真数值资格仍为 `HF_NUMERICAL_QUALIFICATION_NO_GO`；P3 及后续阶段保持关闭。

## G2R 修正

- `layout_token` 保留兼容字段名，但现在是坐标解释与完整静态物理组装的单一 SHA-256 身份，绑定节点种类、连接节点、切片、参考姿态、旋转图、规定支点、材料、质量、摆球和环境。
- 真实跨组装测试分别改变参考摆球姿态、连接/规定节点身份、支点位置和重力；外来坐标全部失败关闭。
- SciPy BFGS 调用显式传入 `gtol`、`maxiter`、`xrtol`、`norm`、`disp`、`c1` 和 `c2`；未知求解器选项警告被提升为异常。
- 候选包最低 SciPy 版本修正为 1.12，因为 SciPy 1.11.4 不接受 BFGS 的 `c1`、`c2` 选项。第一次带未知选项警告的临时运行已明确作废。
- 三条支路都在 129 个公共归一化材料坐标点上重采样并比较完整分段线性中心线。
- 每段新增工程应变、当前长度中的伸长占比和当前长/静长比诊断；这些量不替换既有绝对伸长、张力或段长门。
- 新结果与历史 G2 的能量、宏观形状、张力、反力和最小非规范 Hessian 特征值使用预冻结容差比较。

## 合同与证据

- `contracts/G2R_FROZEN_PROTOCOL.md`：原 G2R 预冻结协议；
- `contracts/G2R_PROTOCOL_DEVIATIONS.md`：原 G2 模块清单和闭合审计的后验修正披露；
- `contracts/G2R_RUNTIME_AMENDMENT.md`：SciPy 1.11.4 未知选项试算作废及第一次有效重跑环境；
- `contracts/g2r_acceptance_manifest.json`：中心线、诊断和历史等价性冻结门；
- `contracts/g2r_runtime_amendment.json`：机器可读运行时附录；
- `reports/g2r_metrics.json`：确定性 G2R 证据；
- `reports/G2R_REPORT.md`：人类可审查报告。

历史 `reports/G2_REPORT.md` 和 `reports/g2_metrics.json` 保持字节不变。由于 G2R 源码和测试已经演进，历史 `tools/generate_g2_evidence.py --check` 不再是当前源码的有效验收入口；这不修改历史 G2 工件，也不把它重新描述为无偏预注册证据。

## 当前证据入口

在本目录、使用合同绑定的 CPython 3.12.3、NumPy 2.5.2、SciPy 1.18.1 环境运行：

```bash
python tools/generate_g2r_evidence.py --check
ruff check src tests tools
python -m compileall -q src tests tools
python -m pytest -q
```

完整测试中的既有 RC1 表征用例还需要正式程序依赖；这些依赖只用于测试，不进入 HF-v2 候选物理核心。

## 结论上限与停止门

G2R 没有实现或验证：

- 静态硬接触与 KKT；
- 平滑或非光滑动力学；
- 单边活动集和动态接触；
- 正式程序、公共 API、HDF5 和 UI 适配；
- 装置级物理验证；
- 实验验证。

因此 G2R 完成后必须停止并交回 Pro。只有 Pro 再审通过且用户随后再次明确要求继续，才可讨论 P3。

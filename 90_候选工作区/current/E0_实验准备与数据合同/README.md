# E0R 真实数据合同、Pilot 溯源与复核门

阶段身份：`E0R_REAL_DATA_CONTRACT_AND_PILOT_PROVENANCE_CORRECTIONS`

本阶段的最高允许状态为：

`E0R_REAL_DATA_CONTRACT_CORRECTIONS_COMPLETE__STOP_AT_E0R_PRO_REVIEW`

正式高保真总状态继续保持：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

## 1. 目的

E0 把既有的[实验门最小测量清单](../F0_正式整理与解析稳定性图谱/07_实验门最小测量清单/EXPERIMENT_GATE_MINIMUM_MEASUREMENTS.md)转换为可执行、可预注册、可追踪且失败关闭的数据入口。E0R 针对首次 Pro 复核发现的真实数据形状与溯源缺口，补齐向量测量、完整相机标定、逐次采集、2D 检测、2D 到 3D 协方差、公共数组和正式模型输入绑定。

E0R 不产生真实实验数据，也不为任何真实装置填写参数。`SYNTHETIC_REAL_SHAPE_FIXTURE` 只表示字段和数组采用真实运行所需的维度与关系；它仍只能支持实现级验证，不能支持物理验证或实验验证。

## 2. 写入与读取边界

本阶段新增内容只位于本目录。阶段完成后，只允许额外更新：

- `90_候选工作区/交接说明_current.md`；
- `90_候选工作区/交接说明_history.md`。

正式理论、正式程序、F0/F1、HF-v2、冻结的 P3--P3R5/G3 证据和根 README 均保持只读。既有实验门清单也是只读规范输入，不在 E0 中复制成第二份测量清单。

## 3. 文件结构

- `00_EXISTING_GATE_REUSE_MATRIX.md`：既有实验门要求与 E0 执行层的映射；
- `01_MEASUREMENT_REGISTER_PROTOCOL.md`：装置、材料和不确定度登记合同；
- `02_FIRST_ROUND_PREREGISTRATION.md`：70 条结果型运行的第一轮预注册；
- `03_CAMERA_TRAJECTORY_DATA_CONTRACT.md`：世界坐标、相机、同步、2D 检测和 3D 轨迹合同；
- `04_GEOMETRY_AND_PILOT_PROTOCOL.md`：三类代表几何与低成本 pilot；
- `05_ACCEPTANCE_MATRIX.md`：E0-A1 至 E0-A10 验收门；
- `schemas/`：测量、标定、采集 attempt、2D 检测、3D 轨迹、公共观测量和模型输入的 Draft 2020-12 合同；
- `templates/`：只含待人工填写项的装置、相机、pilot attempt、第一轮和误差预算模板；
- `src/yps_experiment_pipeline/`：合成实形数据、协方差传播、正式适配、观测量和比较程序；
- `tests/`：严格合同、完整合成实形链、失败/重试、同步、模态和失败关闭测试；
- `tools/check_stage.py`：阶段闭包与越界检查器。

## 4. 数据来源与状态上限

允许的数据来源类型为：

- `MEASURED`：必须绑定原始记录与 SHA-256；
- `DERIVED_FROM_MEASURED`：必须绑定输入测量 ID、公式和源哈希；
- `THEORY_DESIGN_CENTER`：只表示无量纲理论设计中心；
- `ASSUMPTION_SENSITIVITY_ONLY`：只用于敏感性分析；
- `UNSET_REQUIRES_HUMAN`：尚未实测。
- `SYNTHETIC_REAL_SHAPE_FIXTURE`：只用于真实字段形状与完整溯源链的合成验证。

提交模板中的全部实物制造值、装置版本、相机参数和实测字段都使用 `UNSET_REQUIRES_HUMAN`；第一轮计划中只有无量纲理想设计中心和明确标识的释放目标使用理论来源。测试夹具使用 `SYNTHETIC` 或 `SYNTHETIC_REAL_SHAPE_FIXTURE`，其装置版本必须带 `SYNTHETIC_` 前缀。程序禁止用合成数据生成实验或物理验证结论。

第一轮模型比较只允许输出：

- `CONSISTENT_WITH_CURRENT_UNCERTAINTY`；
- `SYSTEMATIC_DISCREPANCY`；
- `INCONCLUSIVE`；
- `OUT_OF_MODEL_DOMAIN`。

这些状态都不等于“模型已被物理验证”。

## 5. 正式模型复用

`forward_adapter.py` 只从仓库正式前向求解器加载公开的 `run_config` 和 `run_ensemble`，并记录正式包路径、模型身份、理论哈希和源码哈希。E0 不保存第二套环面或柔索方程，不调用第二个 ODE 积分器，也不修改正式求解器。

实验、`FWD-TORUS-1.0` 和 `FWD-CABLE-1.0` 先转换到共同可观测量合同 `YPS-EXPERIMENT-COMMON-OBSERVABLES-1.1`。公共 NPZ 必须实际包含 time、bob/junction 世界坐标、冻结 modal basis、fast/slow coordinate、共振相位和 valid mask；JSON 只保存这些数组的 shape、单位、哈希和摘要。

Cable adapter 明确区分 `EXPERIMENT_COMPARISON` 与 `SENSITIVITY_ONLY`：前者的必要输入只接受 `MEASURED` 或 `DERIVED_FROM_MEASURED`，任何 `ASSUMPTION_SENSITIVITY_ONLY` 输入都会失败关闭，不能据此进入实验比较。

`model_input_binding` 不再接受只有来源标签的 map。每个参数必须给出 measurement IDs、measurement bundle SHA-256、所引记录 SHA-256，并在派生量上给出 derivation SHA-256；整个 binding 还必须绑定 trajectory bundle。Torus 的 geometry embedding、initial-state mapping 和 domain-window 三个布尔判断各自绑定 evidence SHA-256，兼容性对象本身再绑定 canonical SHA-256。

## 6. 本地验证

从仓库根运行：

```bash
E0='90_候选工作区/current/E0_实验准备与数据合同'

python3 -m pytest -q "$E0/tests"
ruff check "$E0"

python3 -m compileall -q "$E0/src" "$E0/tests" "$E0/tools"

PYTHONPATH="$E0/src" \
python3 -m yps_experiment_pipeline self-test --synthetic-only

python3 "$E0/tools/check_stage.py" --repository-root .
```

这些命令只验证候选实现、机器合同和合成实形夹具。人工完成装置测量、相机标定、视频采集和 pilot 以前，不得进入 E1。

## 7. 当前复核门与后续人工门

Codex 可以完成文档、schema、模板、严格验证器、合成双目/模态夹具、正式模型只读适配、误差传播和 pilot attempt ledger。

本轮先在以下门停止：

`E0R_REAL_DATA_CONTRACT_CORRECTIONS_COMPLETE__STOP_AT_E0R_PRO_REVIEW`

只有 Pro 接受 E0R 的真实数据合同后，才可把下一门提升为 `HUMAN_PILOT_ACQUISITION_REQUIRED`。即使提升，实际装置制造或装夹、尺量、称量、材料试验、相机布置与标定、释放、视频采集、安全判断和 pilot 仍必须由人工完成。

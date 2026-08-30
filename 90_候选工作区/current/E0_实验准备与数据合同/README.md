# E0 实验准备、数据合同与 Pilot 门

阶段身份：`E0_EXPERIMENT_PREPARATION_AND_DATA_CONTRACTS`

本阶段的最高允许状态为：

`E0_EXPERIMENT_PREPARATION_IMPLEMENTATION_PASS__SYNTHETIC_ONLY__STOP_AT_HUMAN_PILOT_GATE`

正式高保真总状态继续保持：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

## 1. 目的

E0 把既有的[实验门最小测量清单](../F0_正式整理与解析稳定性图谱/07_实验门最小测量清单/EXPERIMENT_GATE_MINIMUM_MEASUREMENTS.md)转换为可执行、可预注册、可追踪且失败关闭的数据入口。它提供测量登记合同、第一轮实验预注册、相机与轨迹数据合同、低成本 pilot 协议、合成数据处理程序和验收检查器。

E0 不产生真实实验数据，也不为任何真实装置填写参数。合成夹具只能支持实现级验证，不能支持物理验证或实验验证。

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
- `schemas/`：Draft 2020-12 机器合同；
- `templates/`：只含待人工填写项的模板；
- `src/yps_experiment_pipeline/`：合成数据、适配、观测量和比较程序；
- `tests/`：严格合同、合成双目、同步、模态和失败关闭测试；
- `tools/check_stage.py`：阶段闭包与越界检查器。

## 4. 数据来源与状态上限

允许的数据来源类型为：

- `MEASURED`：必须绑定原始记录与 SHA-256；
- `DERIVED_FROM_MEASURED`：必须绑定输入测量 ID、公式和源哈希；
- `THEORY_DESIGN_CENTER`：只表示无量纲理论设计中心；
- `ASSUMPTION_SENSITIVITY_ONLY`：只用于敏感性分析；
- `UNSET_REQUIRES_HUMAN`：尚未实测。

提交模板中的全部实物制造值、装置版本、相机参数和实测字段都使用 `UNSET_REQUIRES_HUMAN`；第一轮计划中只有无量纲理想设计中心使用 `THEORY_DESIGN_CENTER`。测试夹具全部使用 `SYNTHETIC`，其派生状态必须带 `SYNTHETIC_` 前缀。程序禁止用合成数据生成实验或物理验证结论。

第一轮模型比较只允许输出：

- `CONSISTENT_WITH_CURRENT_UNCERTAINTY`；
- `SYSTEMATIC_DISCREPANCY`；
- `INCONCLUSIVE`；
- `OUT_OF_MODEL_DOMAIN`。

这些状态都不等于“模型已被物理验证”。

## 5. 正式模型复用

`forward_adapter.py` 只从仓库正式前向求解器加载公开的 `run_config` 和 `run_ensemble`，并记录正式包路径、模型身份、理论哈希和源码哈希。E0 不保存第二套环面或柔索方程，不调用第二个 ODE 积分器，也不修改正式求解器。

实验、`FWD-TORUS-1.0` 和 `FWD-CABLE-1.0` 先转换到共同可观测量合同 `YPS-EXPERIMENT-COMMON-OBSERVABLES-1.0`。比较对象是世界坐标下的可观测量，而不是把不同模型的内部自由度强行逐点等同。

Cable adapter 明确区分 `EXPERIMENT_COMPARISON` 与 `SENSITIVITY_ONLY`：前者的必要输入只接受 `MEASURED` 或 `DERIVED_FROM_MEASURED`，任何 `ASSUMPTION_SENSITIVITY_ONLY` 输入都会失败关闭，不能据此进入实验比较。

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

这些命令只验证候选实现、机器合同和合成夹具。人工完成装置测量、相机标定、视频采集和 pilot 以前，不得进入 E1。

## 7. 人工门

Codex 可以完成文档、schema、模板、严格验证器、合成双目/模态夹具、正式模型只读适配、误差传播和 pilot run sheet。

人工必须完成实际装置制造或装夹、全部尺量/称量/材料试验、相机布置与标定、释放、视频采集、安全判断和 pilot。E0 完成后下一门固定为：

`HUMAN_PILOT_ACQUISITION_REQUIRED`

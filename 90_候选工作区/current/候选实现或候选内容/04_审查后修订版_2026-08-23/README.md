# Y 形摆审查后修订版（2026-08-23）

> **仓库布局 v2 说明（2026-08-24）**
>
> 本目录现位于 `90_候选工作区/current/候选实现或候选内容/`，仍是尚未晋升的候选。下文的提交、路径和机器证据可能描述治理迁移前的纠正阶段；当前操作入口以 [当前任务 README](../../README.md) 和 [项目状态](../../../../00_项目控制/STATUS.md) 为准。

本候选内部仍保留形成证据时的目录名，例如 `01_最终理论/`、`02_最终模拟程序/` 和 `03_项目资料/`。这些是候选快照内部路径；仓库根成熟程序路径已经统一为 `02_模拟程序/`。

## 当前可声明状态

```text
MODEL_CONSISTENT = PASS
CODE_VERIFIED = PASS（仅由 04_纠正证据_2026-08-23/evidence-manifest.json 的同源码提交机器证据授予）
READY_FOR_NUMERICAL_QUALIFICATION = true
NUMERICALLY_QUALIFIED = false
EXPERIMENTALLY_VALIDATED = false
PREDICTIVE = false
```

`CODE_VERIFIED` 不是文档自授状态。运行器会根据证据包、源码提交、工作树、输入哈希和接触护栏重新派生实际等级；任一必要条件不满足时应降级。

## 本次纠正

1. 恢复并绑定原成熟理论归档。
2. 消除活动 FWD/HF/GUI 路径对已删除 NumPy 积分别名的依赖。
3. 使用仓库内相对路径和内容哈希重建 FWD 冻结交付根。
4. 分离 `model_claim_ceiling`、`requested_analysis_level` 和 `actual_evidence_level`。
5. GUI 和 runner 只使用封存 overlay 原始字节，并保存规范表示、配置和共同初态哈希。
6. 将“比较已有运行”降为诊断器，增加预冻结数值资格执行器。
7. 实现可执行 M0–M5 并统一冻结离散材料状态。
8. 添加双环境、干净 checkout、移植、篡改、证据降级和事件网格的机器证据。

## 科学边界

- FWD 是仅受拉柔索—点摆球模型。
- 修订 HF 是离散柔性杆—有限刚体摆球模型，可承受压缩并含弯曲能。
- `HF` 名称不自动意味着更接近实验。
- 既有弯曲刚度只是显式化旧几何参数，不是三支独立弯曲标定。
- 短时 M0–M5 和事件矩阵是代码路径冒烟，不是生产数值资格。
- 本轮未使用封存真实实验数据，因此不得宣称实验验证或预测有效。

## 入口

以下命令从本候选目录执行：

```bash
cd '02_最终模拟程序/02_第一性原理高保真模拟器/Y-Pendulum-Simulator-v1.0.0-rc1'
./启动Y形摆审查后修订版.sh
python -m ypendulum.scientific_revision --help
```

执行器、证据等级和封存输入的具体命令见 `02_最终模拟程序/02_第一性原理高保真模拟器/Y-Pendulum-Simulator-v1.0.0-rc1/configs/revision/README.md`。

# Y 形摆审查后修订版（2026-08-23）

本目录是仓库原项目的独立副本与纠正层。仓库根目录的
`01_最终理论/`、`02_最终模拟程序/`、`03_项目资料/` 和 `本地审查结果/`
未在本轮修改。

## 当前可声明状态

```text
MODEL_CONSISTENT = PASS
CODE_VERIFIED = PASS（仅由 04_纠正证据_2026-08-23/evidence-manifest.json 的同源码提交机器证据授予）
READY_FOR_NUMERICAL_QUALIFICATION = true
NUMERICALLY_QUALIFIED = false
EXPERIMENTALLY_VALIDATED = false
PREDICTIVE = false
```

`CODE_VERIFIED` 不是 overlay 字段或文档宣称。runner 会根据证据包、源码提交、
工作树、输入哈希和接触护栏在运行时重新派生实际等级。任一条件不满足
会降级到 `MODEL_CONSISTENT`。

## 本次纠正

1. 恢复仓库根 `01_最终理论.tar.xz`，并绑定预期 Git blob。
2. 消除活动 FWD/HF/GUI 路径对已删除 NumPy 积分别名的依赖，不再在 worker 中 monkeypatch。
3. 使用仓库内相对路径和内容哈希重建 FWD 冻结交付根，支持干净 checkout 和整目录迁移。
4. 分离 `model_claim_ceiling`、`requested_analysis_level` 和 `actual_evidence_level`。
5. GUI 和 runner 只使用封存的 overlay 原始字节；同时封存规范表示、配置和共同初态哈希。
6. 将“比较已有运行”明确降为诊断器，新增从预冻结计划直接生成
   N/2N/4N、时间、输出与 Radau/BDF 轴的事件资格执行器。
7. 实现可执行 M0–M5：M0 调用 FWD，M1–M5 调用修订 HF 并共用一份冻结离散材料状态。
8. 添加 NumPy 双环境、干净 checkout、移植、篡改、证据降级、overlay TOCTOU、
   消融和事件赁格的可重现机器证据。

## 科学边界

- FWD 是仅受拉柔索—点摆球模型。
- 修订 HF 是离散柔性杆—有限刚体摆球模型，可承受压缩并含弯曲能。
- `HF` 名称不表示它自动比 FWD 更接近实验。
- baseline 的 `6.75e-6 N*m²` 只是显式化旧几何 EI，不是三支独立弯曲标定。
- 1–2 ms M0–M5 和事件矩阵是代码路径全流程冒烟，不是生产数值资格。
- 本轮未使用封存真实实验数据，因此不得宣称实验验证或预测有效。

## 入口

```bash
cd '02_最终模拟程序/02_第一性原理高保真模拟器/Y-Pendulum-Simulator-v1.0.0-rc1'
./启动Y形摆审查后修订版.sh
python -m ypendulum.scientific_revision --help
```

执行器、证据等级和封存输入的具体命令见
`02_最终模拟程序/02_第一性原理高保真模拟器/Y-Pendulum-Simulator-v1.0.0-rc1/configs/revision/README.md`。

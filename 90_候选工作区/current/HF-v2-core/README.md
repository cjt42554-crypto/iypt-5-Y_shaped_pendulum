# HF-v2 纯物理核候选实现

本目录是模型 `HFV2-DISCRETE-CORD-RIGID-BOB-0.2-CANDIDATE` 的独立候选包。它与正式 RC1 后端并行存在，不修改或替代 `HF-DISCRETE-ROD-RIGID-BOB-1.0`。原 `0.1-CANDIDATE` 的 G1 报告、指标和合同保留为历史证据。

当前范围仅是 Pro G1 审查要求的 G1R 局部模型合同修订。这里没有静态求解器、时间积分器、接触求解器、公共 API 适配、HDF5、UI 或正式资格认证。

## 0.2 模型合同

- 轴向材料是只传递拉力的单边 Kelvin--Voigt 材料；压缩段的最终轴力严格为零。
- 弯曲项采用三点离散曲率二次能，并由闭式解析负梯度给出节点力。非零刚度下，精确反平行是曲率分母本身的域边界；零刚度分支在计算该分母前返回精确零能和零力。
- 材料坐标是 SI 参考弧长，材料段静长只能由 `material_end - material_start` 派生。
- 状态和自由节点质量都绑定不可变的 `free_node_ids` 顺序；数量相同但顺序错配会失败关闭。
- 摆球惯量同时满足对称正定和主惯量三角不等式；线动量接口拒绝非有限速度和非有限结果。
- 摆球姿态由 `SO(3)` 指数映射和群乘法推进，输入、乘法输出、状态和审计共用同一舍入容差，不使用姿态归一化或投影。
- 质量、重力、浮力和显式启用的各向同性空气阻力仍是无 I/O 的纯物理接口。
- 静态接触和动态接触均未实现；动态接触仍是 `CLOSED_PENDING_PRO_REVIEW`。

## 证据入口

在本目录运行：

```bash
python tools/generate_g1r_evidence.py --check
python -m pytest -q
python -m ruff check src tests tools
python -m compileall -q src tests tools
```

`contracts/g1r_acceptance_manifest.json` 冻结门槛与样例，`contracts/g1r_module_manifest.json` 对包内每个 Python 模块分类，`reports/g1r_metrics.json` 由上述单一证据命令复算。自动发现但未分类的模块会直接使架构门失败。

这些命令只能支持：

`G1R_LOCAL_MODEL_CONTRACT_VERIFIED__HF_NUMERICAL_QUALIFICATION_NO_GO`

它们不证明静态或动力学数值算法获得资格，不证明三锚点结果，也不构成物理或实验验证。

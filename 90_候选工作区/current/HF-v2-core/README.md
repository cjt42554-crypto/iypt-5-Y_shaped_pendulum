# HF-v2 候选核心与无接触静力学

本目录是模型 `HFV2-DISCRETE-CORD-RIGID-BOB-0.2-CANDIDATE` 的独立候选包。它与正式 RC1 后端并行存在，不修改或替代 `HF-DISCRETE-ROD-RIGID-BOB-1.0`。原 `0.1-CANDIDATE` 的 G1 工件和 Pro 已接受的 `0.2-CANDIDATE` G1R 工件均作为历史证据保留。

当前完成范围到 P2 无接触静力学 G2 候选门。静态硬接触、时间积分、活动集、动态接触、公共 API 适配、HDF5、UI 和正式资格认证均未实现。

## 0.2 模型合同

- 轴向材料是只传递拉力的单边 Kelvin--Voigt 材料；压缩段的最终轴力严格为零。
- 弯曲项采用三点离散曲率二次能，并由闭式解析负梯度给出节点力。非零刚度下，精确反平行是曲率分母本身的域边界；零刚度分支在计算该分母前返回精确零能和零力。
- 材料坐标是 SI 参考弧长，材料段静长只能由 `material_end - material_start` 派生。
- 状态和自由节点质量绑定不可变的 `free_node_ids` 顺序；数量相同但顺序错配会失败关闭。
- 摆球惯量满足对称正定和主惯量三角不等式；摆球姿态使用 `SO(3)` 指数映射和群乘法，不使用姿态归一化或投影。
- P2 静态组装在构造时强制绑定拓扑、状态、质量、材料段顺序和广义坐标切片，并以 `layout_token` 拒绝身份错配。
- 参考段质量和排液体积各向两个材料端点集总一半；支点、共享结点和摆球连接点的贡献保持各自真实位置。
- P2 总势能只含单边轴向能、离散弯曲能、重力势能、浮力势能和刚体偏心连接运动学。
- P2 唯一求解器是固定容差的 BFGS。净空只作解后域审计，不进入势能、广义力或求解分支。
- 静态接触和动态接触均未实现；动态硬接触仍是 `CLOSED_PENDING_PRO_REVIEW`。

## 当前证据入口

在本目录运行：

```bash
python3 tools/generate_g2_evidence.py --check
ruff check src tests tools
python3 -m compileall -q src tests tools
```

完整测试还需要既有 RC1 表征测试的正式程序依赖。本机本轮使用：

```bash
uv run --no-project \
  --with pytest \
  --with numpy \
  --with scipy \
  --with pydantic \
  --with PyYAML \
  --with h5py \
  --with pandas \
  --with matplotlib \
  --with pint \
  python -m pytest -q
```

`contracts/g2_acceptance_manifest.json` 是目标结果前冻结的质量、求解器、种子、锚点和 G2 门；`contracts/g2_module_manifest.json` 完整分类当前包源码并执行规范导入依赖矩阵；`reports/g2_metrics.json` 由单一命令确定性生成；`reports/G2_REPORT.md` 给出人类可审查解释。

G1R 工件保持字节不变，但不再针对 P2 新源码重算。当前 G2 证据支持的最高结论只有：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED__HF_NUMERICAL_QUALIFICATION_NO_GO`

它不证明接触或动力学数值资格，不证明三锚点结果，不构成装置级物理验证或实验验证。达到 G2 后必须停止，等待 Pro 复审与用户新的明确指令。

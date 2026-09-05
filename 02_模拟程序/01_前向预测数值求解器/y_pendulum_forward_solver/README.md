# 前向预测求解器

一个入口执行三种独立模型：`FWD-CABLE-1.0`（有质量、可伸长柔索）、`FWD-TORUS-1.0`（理想环面）和 `YP-FWD-J3-v1`（有限结点质量、无质量定长绳）。配置中的模型 ID 与理论哈希须相符；J3 的哈希与两个旧分支不同。数值收敛、标定和实验有效性分别判断，见[当前交接](../../../00_项目管理/交接说明_current.md)。

从仓库根目录安装和运行（Python 3.10 或以上）：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '02_模拟程序/01_前向预测数值求解器/y_pendulum_forward_solver'
.venv/bin/python '02_模拟程序/01_前向预测数值求解器/y_pendulum_forward_solver/run.py' run \
  '02_模拟程序/01_前向预测数值求解器/y_pendulum_forward_solver/configs/junction_example.json' \
  --output runs/junction-example
```

另两个示例是同目录的 `torus_example.json`、`cable_example.json`。输出目录必须为空；每次复算用新目录。导出包括输入快照、身份/状态/事件/诊断 JSON、轨迹与观测 NPZ、CSV 和图。只要输入被拒绝或数值未判定，就应查看具体原因，不能使用一条返回曲线宣称预测完成。J3/环面不导出材料应变或绳波能量。

J3 初态为 `[theta, nu, n_x, n_y, n_z, eta_x, eta_y, eta_z]`，其中方向 `n` 和方向速度 `eta` 均用全局坐标；输入须单位长、切向且三张力为正。实际最大步长同时受快模态频率限制。首次失张或指定障碍接触终止，不延拓松绳接触轨迹。

柔索有限时间撤力在 `STATIC_HOLD_RELEASE` 配置中增加：

```json
"hold_release": {
  "source": "initial_static_reaction",
  "start": 0.0,
  "duration": 0.01,
  "history": "smoothstep_c1"
}
```

该对象放在 `inputs` 中。保持力来自生产静力求解得到的结点/摆球反力，以 `1-3u²+2u³` 撤去；实际保持力功率 `P_hold` 和接受步累计外功 `W_hold` 随结果导出。瞬时释放用 `history: "instantaneous"`、`duration: 0`；省略整个字段保留旧输入的零时刻瞬时释放语义。`start` 和 `duration` 是物理输入，不随积分容差改变。

四类受载三模型对照可从仓库根目录用一条命令完成配置、正式求解、导出、观测回读和误差比较：

```bash
OPENBLAS_NUM_THREADS=1 .venv/bin/python \
  '03_研究记录/维护/2026-09-06_理论程序对齐/5-03/compare_models.py' \
  runs/matched-models
```

默认比较四个工况的两秒窗口；运行前会保存合成参数、网格/步长档位、观察窗和误差预算。对照区分无载材料长度、受载弧长和定长模型的端点弦长；频率与累计相位是给定窗内的观测量估计。材料参数和释放方式换成实测值后，须重新验证所选分支及其数值误差，不能把合成误差界直接当装置精度。开始实测前按[实验准备](../../../04_实验与数据/实验前准备与首轮验证.md)填写输入、固定标定和留出批次。

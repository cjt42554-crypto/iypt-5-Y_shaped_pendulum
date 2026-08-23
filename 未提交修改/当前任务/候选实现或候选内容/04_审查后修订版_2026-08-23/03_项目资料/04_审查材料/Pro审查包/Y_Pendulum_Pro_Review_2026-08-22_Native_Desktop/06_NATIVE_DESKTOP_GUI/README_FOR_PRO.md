# 原生本地桌面 GUI：给 Pro 的独立审查说明

## 1. 本目录解决什么问题

本目录是阶段 3 模拟程序的用户界面与短链路证据，不新增物理方程，也不改写阶段 1、阶段 2 或阶段 4。

最终默认入口是 `tkinter + Matplotlib` 原生桌面窗口：

- 不启动浏览器；
- 不监听 HTTP 端口；
- 不需要邮箱、账号、登录或联网；
- FWD、HF、同输入双后端都调用各自既有求解器；
- Streamlit 只保留为显式 `ui-web` 开发备份。

请先看 `native_desktop_gui.png`，再读 `NATIVE_DESKTOP_GUI.md` 和 `source/`。

## 2. 参数覆盖和运行控制

启动默认快照经构造性冒烟测试确认：

| 项目 | 数量/结果 |
|---|---:|
| FWD 配置叶字段 | 237 |
| FWD 可见可编辑/只读身份控件 | 237 |
| HF 配置叶字段 | 115 |
| HF 可见可编辑/只读身份控件 | 115 |
| 后端模式 | forward / high_fidelity / both |
| 工作流 | single / repeat / batch / sweep / same_input_dual |
| 网络服务 | false |

标量、枚举、布尔、向量、矩阵和结构化 FWD 退出守卫都有 UI 控件。启动即有可运行短算例；YAML/JSON 只用于保存、载入和复现实验，不是正常使用的前置条件。

任务在独立进程组中运行。窗口提供开始、暂停、继续、停止、阶段进度、任务表和实时日志。独立批次可选择 1–12 个 CPU 任务；单条自适应隐式积分的数学顺序不因 GUI 改变。

## 3. 窗口内科学结果

同一窗口直接显示：

1. 三维 Y 形材料路径、结点和有限半径摆球；
2. 摆球位移、速度；
3. 有符号轴力和事件用非负张力；
4. 能量、耗散、空气/基座功率与账本余量；
5. 全部守卫分量和事件；
6. 频谱与相图；
7. 同输入 FWD/HF 位置、速度差；
8. 当前图、下采样 CSV 或完整规范结果目录导出。

## 4. 随包短算例

`evidence/short_both_run/` 是 GUI worker 真实执行的 `0.2 ms`、`12/12/20` 双后端短算例，不是伪造视图数据。

| 指标 | 结果 |
|---|---:|
| 总墙钟 | 20.25 s |
| 平均 CPU 占用 | 1609% |
| 峰值 RSS | 263672 KiB |
| FWD / HF presentation samples | 81 / 81 |
| FWD 状态 | COMPLETED / SUCCESS_SINGLE_RUN |
| HF 原始状态 | UNDETERMINED / SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED |
| 位置 RMS 差 | 8.442120512569845e-8 m |
| 位置最大差 | 1.869811678041161e-7 m |
| 速度 RMS 差 | 1.08269823585388e-3 m/s |
| 速度最大差 | 1.8685541512412915e-3 m/s |

HF 原始状态是有意保守保留的：轨迹可供个人科研读取，但短 GUI 运行没有把可选全窗连续守卫资格写成已完成。GUI 将这个事实显示出来，没有升级为虚假的科学成功状态。

## 5. 当前回归

在同一最终源码快照上执行：

- 原生 GUI 构造冒烟：通过；
- GUI 配置、结果读取、进程控制、插件和 CLI 状态、HF 核心定向回归：`62 passed in 16.02 s`；
- 阶段 2 FWD `test_cable.py`：`30 passed in 16.59 s`；
- 阶段 2 `test_cable.py + test_convergence.py`：`61 passed, 9 subtests passed in 17.72 s`；
- 真实 FWD 桌面 worker 兼容运行：`COMPLETED / SUCCESS_SINGLE_RUN`，81 samples。

其中 NumPy 2.5 删除 `np.trapz` 的兼容只存在于桌面子进程启动适配层；阶段 2 的冻结 `cable.py` 与 `convergence.py` 已恢复原始 SHA，没有为 GUI 修改其方程或源文件身份。

## 6. 应当怎样审查

请回答：

1. GUI 是否确实只是编排/查看层，没有把新的物理公式混入界面；
2. 所有当前实际计算参数是否可在窗口中查看和编辑；
3. 三个后端模式、五个工作流、长任务控制是否构成个人科研所需的闭环；
4. signed axial force 与 tension 是否在界面和数据层保持不同语义；
5. 科学失败/未决状态是否会被 UI 伪装成完成；
6. 哪些改动会直接改善日常科研可用性或可修改性。

请不要把代码签名、账号体系、Web 部署、安装包发布或多用户恢复机制当成本个人科研原型的阻断项。

## 7. 已知限制

- 可选提供者的不同结构通常通过载入一个有效配置模板来切换；当前界面保证当前已解析配置的所有叶字段有控件，不声称为任意未来 schema 自动生成语义化向导。
- 自适应 Radau/BDF 的单轨迹积分仍在 CPU；GUI 的 1–12 并行用于相互独立的重复、批量和扫描成员。
- 默认 `0.2 ms` 案例是安装与整链冒烟，不是长窗物理结论。
- 截图是在离线 Xvfb 桌面中生成；真实 Tk 窗口和 Matplotlib canvas 均已构造，但这不是跨所有桌面主题的像素级验收。

## 8. 本目录关键源码身份

| 文件 | SHA-256 |
|---|---|
| `desktop_app.py` | `4eae377e941716c0f17131f1dd5fe3305df615b41b20ad7bc240a23dc133528e` |
| `desktop_config.py` | `1fe4e17db164a4496fa9ffb00eb231a13c1d0ee3186cc0f691245c64d4eb0849` |
| `desktop_results.py` | `de881a650f4664a5eb765555f44f88e7af87ba00cf9cb75ad0b6f6520b1efcd5` |
| `desktop_worker.py` | `0cc31c4221f7e503c89fb2c084f43994c084506106bd5e76627bfcffda24f750` |
| `platform.py` | `fcf9607c439074b9f2603c10d9aec5657c41f78e60034ad65804f26cbf4aaca8` |
| `native_desktop_gui.png` | `a1189fbaf567665ab5cbfe228e7c8ad76f49c8a5f771440fd42a98780894e322` |


# 已退休：`LEGACY-RITZ-V1.1`

> 本目录不是当前冻结前向理论的活动实现。请先阅读 `LEGACY_STATUS.md`；当前活动程序位于 `../y_pendulum_forward_solver/`。下文仅保留历史原型原说明。

# Y-Pendulum 统一闭合理论计算程序 v1.1

本程序直接实现 `IYPT_2027_Y_Pendulum_Unified_Closed_Predictive_Theory_v3.md` 第 13 节的固定支点、质点摆球、二次 Ritz 闭合母方程：

\[
q=(c_A,c_B,r_J,c_\ell,r_m)\in\mathbb R^{15},
\qquad
M\ddot q=F(q,\dot q;p).
\]

每条物理绳只保留一个二次 Ritz 内部节点。程序不是把绳离散成大量质点—弹簧后重新做第一性原理仿真；它直接积分理论给出的 15 广义坐标、30 一阶状态变量闭合系统。

## 1. 所有输入参数都集中在程序最前面

打开 `y_pendulum_closed.py` 后，只需要修改文件开头标有

```python
# 用户只需要修改这里：统一输入参数区
USER_INPUTS = { ... }
```

的一个区块。该区块同时包含：

- 两个固定支点坐标；
- 摆球、结点和三条绳的质量；
- 三条绳的无载长度、`EA`、`etaA`、`EI` 和阻力；
- 单边接合正则化参数；
- 初始位置、角度和速度；
- 数值积分精度与时长；
- 数值输出、静态图和 3D 动画设置；
- 俯视相机的透视开关和相机距离。

程序后文不再另设一套示例物理参数；`example_configuration()` 只是对顶部 `USER_INPUTS` 的深拷贝。

直接运行时不需要配置文件：

```bash
python y_pendulum_closed.py
```

输出目录由顶部的

```python
USER_INPUTS["output"]["directory"]
```

决定。

仍然可以用外部 JSON 做批量计算：

```bash
python y_pendulum_closed.py example_config.json
```

外部 JSON 会完整覆盖顶部配置。生成与顶部配置相同的 JSON：

```bash
python y_pendulum_closed.py --make-example example_config.json
```

## 2. 俯视 3D 动画

数值求解结束后，程序从已经求出的三维 Ritz 状态

\[
r_A(\xi,t),\quad r_B(\xi,t),\quad r_\ell(\xi,t),\quad r_J(t),\quad r_m(t)
\]

渲染俯视动画。动画只负责观测映射，不增加任何新的力学模拟。

默认输出：

```text
y_pendulum_3d_top_view.mp4
```

动画开关位于顶部：

```python
"animation_3d": {
    "enabled": True,
    ...
}
```

### 2.1 正交俯视与针孔透视切换

只需修改：

```python
"perspective": {
    "enabled": True,
    "camera_distance": 1.50,
    "principal_point": "support_midpoint",
}
```

- `enabled = False`：正交俯视，无深度比例变化；
- `enabled = True`：针孔透视投影，较低的摆球和绳段向图像主点收缩；
- `camera_distance`：相机光心到两个上支点中点的竖直距离，单位 m。距离越近，透视效应越强。

这里必须区分两个概念：相机光心不能放在两个上支点中点，否则不可能形成俯视成像。程序采用的物理几何是：

\[
P=\frac{A+B}{2},
\qquad
C_{\rm camera}=P-D\,e_z,
\]

其中本程序的 `z` 轴向下，`D=camera_distance`。相机位于支点中点正上方，光轴穿过支点中点。因此两个上支点中点是图像的**主点/光轴落点**，而不是相机光心。

在针孔透视模式下，支点中点平面保持单位比例；某点相对该平面的向下深度为 `z_rel` 时，其投影比例为

\[
S=\frac{D}{D+z_{\rm rel}}.
\]

这实现的是几何透视投影，不包含未经标定的桶形或枕形镜头畸变。

### 2.2 动画参数

顶部动画配置还可修改：

- `format`：`mp4` 或 `gif`；
- `fps`：视频帧率；
- `playback_speed`：播放倍速；
- `max_frames`：最大帧数；
- `trail_seconds`：摆球俯视轨迹尾迹长度；
- `figure_size_inches`、`dpi`：画面尺寸和分辨率；
- `line_width` 与各标记尺寸；
- `show_time`：是否显示模拟时间；
- `show_principal_point`：是否标出支点中点对应的主点；
- `fallback_to_gif`：系统没有 FFmpeg 时是否自动改写 GIF；
- `fail_on_error`：动画失败时是否让整个程序报错退出。

## 3. 安装

建议 Python 3.11 或更高版本：

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

依赖：

- NumPy；
- SciPy；
- Matplotlib；
- Pillow。

输出 MP4 还需要系统安装 FFmpeg。若 FFmpeg 不可用且 `fallback_to_gif=True`，程序会自动生成 GIF。

## 4. 运行方式

使用顶部统一输入区：

```bash
python y_pendulum_closed.py
```

指定输出目录：

```bash
python y_pendulum_closed.py --output results/run_001
```

使用外部 JSON：

```bash
python y_pendulum_closed.py example_config.json --output results/run_002
```

运行理论一致性自检：

```bash
python y_pendulum_closed.py --self-test
```

## 5. 核心物理输入

所有单位采用 SI。

### 5.1 固定几何

```python
"supports": {
    "A": [-0.15, 0.0, 0.0],
    "B": [ 0.15, 0.0, 0.0],
}
```

坐标约定：`z` 轴竖直向下。

### 5.2 摆球和结点

```python
"junction_mass": 0.002,
"bob": {
    "mass": 0.200,
    "volume": 4.18879e-6,
    "added_mass_coefficient": 0.0,
    "drag": {"linear": 0.001, "quadratic": 0.015},
}
```

### 5.3 三条绳

每条绳均输入：

```python
{
    "rest_length": 0.40248,
    "mass": 0.005,
    "EA": 300.0,
    "etaA": 0.20,
    "EI": 0.0,
    "drag": {
        "c_parallel": 0.0,
        "c_perpendicular": 0.0008,
        "d_parallel": 0.0,
        "d_perpendicular": 0.002,
    },
    "end_bending": [],
}
```

- `rest_length=L_i^0`：无载材料参考长度；
- `mass=M_i`：整条支路质量；
- `EA`：轴向刚度，N；
- `etaA`：轴向黏弹系数，N·s；
- `EI`：等效弯曲刚度，N·m²；
- 阻力系数按参考长度计。

工作载荷下的长度由闭合理论的静态平衡自动产生。不要把同一静态伸长同时计入 `rest_length` 和 `EA`。

## 6. 初始条件

默认模式为 `ideal_torus_release`：

```python
"initial_condition": {
    "mode": "ideal_torus_release",
    "working_lengths": {"A": ..., "B": ..., "lower": ...},
    "phi": 5.0,
    "theta": 3.0,
    "phi_dot": 0.0,
    "theta_dot": 0.0,
    "relax_internal_nodes": True,
    "internal_velocity": "minimum_kinetic",
}
```

它先用环面慢流形构造宏观释放位置，再按闭合理论对三个内部 Ritz 节点做准静态势能极小化。也支持：

- `full_state`：直接给完整 `q0,v0`；
- `fixed_endpoints_static`：给结点和摆球位置，求内部绳形；
- `static_equilibrium`：求完整静态悬垂平衡。

## 7. 输出文件

数值输出：

- `full_motion_state.npz`：完整 30 维状态、加速度、三条绳形、局部伸长、局部张力、曲率和能量；
- `state_summary.csv`：逐时刻摘要；
- `run_summary.json`：积分、能量、张力和动画元数据；
- `input_config.json`：本次实际使用的完整输入。

静态图片：

- `trajectory_xy.png`；
- `bob_coordinates.png`；
- `tension_envelopes.png`；
- `energy_balance.png`。

动画：

- 默认 `y_pendulum_3d_top_view.mp4`；
- FFmpeg 不可用时可回退为 GIF。

`run_summary.json` 会记录：

- 使用正交还是针孔透视；
- 支点中点主点的三维坐标；
- 相机光心坐标；
- 相机距离；
- 帧数、帧率、视频时长和实际播放倍速。

## 8. 适用范围

当前版本对应：

- 固定支点；
- 质点摆球；
- 连接作用线过质心且不传递力矩；
- 每条绳一个二次 Ritz 内部节点；
- 无绳—绳、绳—支架、摆球—纸面等额外碰撞。

动画是上述三维理论状态的观测映射。它不会补充移动支架、刚体摆球姿态、扭转或额外接触等理论中尚未启用的自由度。

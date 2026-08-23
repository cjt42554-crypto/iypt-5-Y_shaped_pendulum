# YP-FPSim 旧候选接续记录（历史，不是当前验收清单）

> 2026-08-21 更正：本文的 41 项测试、旧 H1 高保真范围、缺失 Streamlit 环境及发布候选证据均已陈旧。当前阶段 3 以 `HF-DISCRETE-ROD-RIGID-BOB-1.0`、统一双后端平台和最终冻结后重新生成的证据为准。本文仅保留历史问题来源，不得据此宣称当前完成或失败。

> 文档状态：2026-08-18，针对 `1.0.0rc1` 开发候选。  
> 目的：把当前容器无法完成的依赖、UI、干净安装和高成本性能工作独立交给 Codex，不把它们伪装成已验收。

## 1. 当前代码状态

工作树已经包含：A0/A1/H1、单边有限质量柔索、Radau/BDF/Newmark、静力稳定性审计、受拉相容初始速度投影、相机前向模型、实验比较、自动量级/声明门控、独立轴向与阻尼标定、HDF5、CLI、Streamlit UI 源码、配置/验证清单 schema、41 项自动测试、V-001–V-013 和数值回归基线。

当前可在已有环境中执行：

```bash
python -m pip install -e . --no-deps --no-build-isolation
pytest -q
ypendulum validate-suite --fast
ypendulum validate-suite
ypendulum diagnose configs/examples/full_quick_3to2.yaml --skip-equilibrium
```

已实际得到：

- `41 passed`；
- 完整 V-001–V-013：13/13 PASS；
- editable wheel 构建并安装成功；
- CLI 在不设置 `PYTHONPATH` 时可用；
- 小系统 N/2N、production/reference、Radau/BDF 收敛矩阵通过。

## 2. 当前环境缺失的包

当前容器中缺少或不可执行：

```text
pint
streamlit
hypothesis
ruff
mypy
python-build（`python -m build` 不可执行）
```

`uv 0.10.0` 可执行，但 `uv lock --offline` 因缓存中缺少 `h5py` 等依赖而无法解析；当前网络受限，因此没有伪造 `uv.lock`。

已安装：NumPy、SciPy、Pydantic、PyYAML、h5py、pandas、Matplotlib、Plotly、pytest。

影响：

1. 核心单位系统使用受限后备解析器通过测试，但正式发布仍应在 Pint 存在时重跑全部单位测试。
2. Streamlit 源码可编译，但无法启动浏览器级 UI 验收。
3. Hypothesis 属性测试尚未在正式 Hypothesis 引擎下扩展；当前有确定性随机属性测试。
4. Ruff/mypy 未执行。
5. `pip wheel --no-build-isolation` 已生成并隔离安装验证 wheel；但标准 `python -m build` 入口不可执行，正式 wheel+sdist 双产物仍需在干净环境重建。

## 3. Codex 必做任务（不得跳过）

### C-001：干净 Python 3.11 安装

在无预装项目依赖的 Python 3.11 环境：

```bash
python -m venv .venv-clean
source .venv-clean/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev,ui]'
pytest -q
ypendulum validate-suite --output-directory validation/clean311
```

保存完整安装日志、`pip freeze`、Python/OS/CPU 信息。失败必须修复，不得使用 `--no-deps` 作为最终验收替代。

### C-002：Pint 双路径审查

在安装 Pint 后重新执行所有配置、单位、schema 和示例测试。特别检查：

- `N*s/m`、`Pa*s`、`m/s^2`、角度与频率；
- 数组量；
- 错误量纲必须拒绝；
- Pint 路径与 fallback 路径解析后的 SI 值一致。

若不一致，修正 fallback 或 Pint 实现并增加回归测试。

### C-003：UI 浏览器级验收

执行：

```bash
streamlit run src/ypendulum/ui/app.py --server.headless true
```

至少完成：

1. 默认 YAML 加载与静力预览；
2. 量级/声明诊断显示；
3. A0、A1、H1 各一次仿真；
4. H1 轨迹、张力、能量、事件和可靠性显示；
5. 运行目录 ZIP 下载；
6. 错误配置给出可理解的错误；
7. 短记录不能显示伪精确主频。

保存 UI health probe、控制台日志和至少一张截图。不得在 UI 中重新实现物理公式。

### C-004：代码质量工具

```bash
ruff check src tests scripts benchmarks
ruff format --check src tests scripts benchmarks
mypy src/ypendulum
```

Ruff 必须通过。mypy 可分阶段修复，但最终剩余错误要在 `validation/release_audit.md` 逐条列出，不能全局忽略。

### C-005：正式构建和安装产物

```bash
python -m build
python -m pip install --force-reinstall dist/ypendulum-1.0.0rc1-py3-none-any.whl
ypendulum --version
pytest -q
```

检查 sdist/wheel 内包含 UI、schema、必要包数据和许可证；不得依赖源码工作树中的未打包文件。

### C-005b：锁文件与离线复现

在联网的干净 Python 3.11 环境执行：

```bash
uv lock
uv sync --all-extras --frozen
pytest -q
```

提交真实生成的 `uv.lock`，记录 `uv --version`。不得手工拼接或提交无法通过 `uv sync --frozen` 的占位锁文件。

### C-006：Docker

```bash
docker build -t ypendulum:1.0.0rc1 .
docker run --rm ypendulum:1.0.0rc1 --version
docker run --rm -v "$PWD/configs:/configs:ro" ypendulum:1.0.0rc1 \
  validate-config /configs/examples/full_quick_3to2.yaml
```

若需要 UI 容器，另建 profile，不要让核心镜像强制依赖 Streamlit。

### C-007：高刚度性能审查

当前主要工程瓶颈是 `20/20/30`、高 `E/rho`、一致质量、长时 H1。必须比较：

- Radau exact/partial/sparse preconditioner Jacobian；
- BDF（只用于覆盖小系统）；
- Newmark；
- 一致质量与经验证的集总质量；
- 不同 `EA`、网格和释放平滑时间。

禁止通过删除绳质量、任意降低 E、添加未标定数值阻尼或放宽误差来宣布“加速”。任何降阶/多速率方法必须对目标观测量做 N/2N、时间、能量和事件收敛。

### C-008：重新受拉专门收敛

现有事件已经输出：事件时刻、局部峰值、固定窗口冲量、FWHM、半高样本数和分辨率警告。还需要构造至少一组独立、物理参数明确的重新受拉工况，扫描：

- N/2N/4N；
- `max_step`、`output_dt`；
- Radau/Newmark；
- `EA` 和独立标定的轴向黏性；
- 传感器带宽卷积。

只有峰值和冲量差均满足冻结门槛，才可标记 `retension_peak_prediction_ready=true`。

### C-009：对抗性物理审查

逐项检查：

- 单边本构在卸载剪裁时的能量账本；
- 规定支点一致质量边界惯性项；
- 气动力相对空气速度、功率符号和 Jacobian；
- 表格材料网格客观性和外推标志；
- 预紧自然长度不相交几何；
- 静力稳定性特征值符号；
- 串联绳局部松弛即失去端到端传力；
- 频率分析在短窗、啁啾、结构切换和绳模态下拒绝错误声明；
- 实验 nuisance 参数不得逐条验证轨迹重新拟合。

### C-010：最终发布

全部门槛通过后：

1. 将版本从 `1.0.0rc1` 改为 `1.0.0`；
2. 更新 CHANGELOG、验证报告、性能报告和发布审计；
3. 运行 `scripts/run_release_checks.py --full-validation`；
4. 运行 `scripts/build_release.py`；
5. 生成正式 wheel、sdist、完整 ZIP 和 SHA-256；
6. 在全新目录解压 ZIP 后再次安装和运行五个示例。

## 4. 不应由 Codex 擅自扩大的物理范围

首版仍是固定材料结、轴向柔索、质心点质量摆球。下列内容不能仅靠“加代码”宣称支持：Cosserat 弯扭、偏心刚体、滑动上绳、自接触、柔性支架双向耦合、完整 CFD、笔尖接触、漏沙/颗粒。若开发这些功能，应建立 H2 规范、参数可辨识性和独立验证矩阵。

## 5. 实验状态

当前没有封存真实实验数据。因此即使全部软件门槛通过，也只能称数值实现 `VERIFIED`。不得生成假的 validation manifest，不得把仿真对仿真比较称为 `VALIDATED`，不得把示例曲线外观称为 `PREDICTIVE`。

## 6. 接续完成判据

Codex 接续任务只有同时交付以下证据才算完成：

- 干净 3.11 安装日志；
- 完整 pytest/validation/ruff/mypy 结果；
- UI health + 实际运行证据；
- wheel/sdist/Docker/ZIP 安装证据；
- 更新后的收敛和性能报告；
- 重新受拉峰值收敛或明确未收敛；
- 对抗性审查问题与修复记录；
- 所有产物 SHA-256。

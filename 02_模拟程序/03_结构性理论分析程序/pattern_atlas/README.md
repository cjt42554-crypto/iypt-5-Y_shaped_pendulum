# 理想环面参数—图样图谱 1.1

## 1. 正式身份与结论边界

本目录是仓库内的正式结构性理论分析程序，程序身份为：

`YPS-IDEAL-TORUS-PATTERN-ATLAS-1.1`

Python distribution 为 `y-pendulum-pattern-atlas==1.1.0`。本程序只在本仓库 checkout 内运行，不是可脱离仓库使用的 standalone wheel：它必须按仓库相对路径读取正式前向理论，并调用正式前向求解器中的 `FWD-TORUS-1.0` 后端。

本程序不保存第二套环面方程，也不自行调用另一个 ODE 积分器。数值调谐的解释固定为：

`ideal_model_internal_not_experimental_calibration`

因此，本程序只能支持理想、对称、无质量、不可伸长且始终张紧的环面模型内部图谱，不能给出真实装置校准、连续柔索验证、高保真资格或实验验证。

## 2. 程序结构

- `configs/atlas_v1.json`：目标比、振幅、观察窗、容差和数值设置；
- `schemas/atlas_config.schema.json`：从顶层到每个嵌套对象均关闭的严格输入合同，不接受字符串或小数型 $p,q$；
- `schemas/atlas_output.schema.json`：覆盖全部结果字段且逐层关闭的确定性输出合同；
- `schemas/atlas_run_evidence.schema.json`：运行证据、优化器状态和诊断合同；
- `schemas/source_manifest_lock.schema.json`：正式源码和精确运行时锁的关闭合同；
- `contracts/source_manifest_lock.json`：在冻结环境中生成，绑定正式理论、正式 contracts、正式 torus 后端、全部生产源码、配置、schema、构建元数据和运行时身份；
- `src/y_pendulum_pattern_atlas/backend.py`：只负责绑定正式环面后端及其 SHA-256，并在导入后逐字恢复 `sys.path`；
- `src/y_pendulum_pattern_atlas/atlas.py`：相位拟合、调谐、闭合诊断、图表和确定性工件；
- `tests/test_atlas.py`：正式根发现、正式后端身份、全 production tree 无重复 ODE、纯模态周期、能量、步长、张紧守卫、严格 schema、故意源漂移、运行时漂移、导入路径污染和字节确定性检查；
- `tools/verify_full_repeats.py`：核验多次全量运行的工件集合、逐字节一致性、schema 和语义计数。

输出中不写运行时钟时间。相同源码、配置、正式后端和锁定运行环境应生成字节相同的 JSON、CSV、SVG、PNG、运行证据与工件清单。任一绑定文件、绑定文件集合或运行时身份变化都会在结果运行前 fail closed。

## 3. 冻结运行环境

后续正式源锁生成和结果证据复算使用以下环境合同：

- CPython `3.12.3`，项目兼容范围 `>=3.12,<3.13`；
- `jsonschema==4.10.3`；
- `matplotlib==3.8.4`；
- `numpy==1.26.4`；
- `scipy==1.11.4`；
- 开发验证另使用 `pytest==8.4.2` 和 `ruff==0.16.5`。

`matplotlib==3.6.3` 在本机 CPython 3.12 clean venv 中没有可用 wheel，源码构建又缺少 Python headers，因此不属于正式环境合同。`matplotlib==3.8.4` 是本正式包冻结的可安装版本。

## 4. 从仓库 checkout 运行

构建出的 wheel 只用于元数据、导入和包装边界检查，不是可执行的独立图谱。从 checkout 外启动 wheel 中的 CLI，或尝试用 `--repository-root` 使 wheel 绕过正式源码布局，都必须在读取配置或写入输出前以明确的 `repository-bound` 错误失败关闭。

从仓库根目录进入本目录：

```bash
cd '02_模拟程序/03_结构性理论分析程序/pattern_atlas'
```

建议在 checkout 外建立干净环境，安装 `pyproject.toml` 中精确固定的依赖，并始终用 checkout 的 `src` 运行：

```bash
python3.12 -m venv /tmp/yps-pattern-atlas-1.1-venv
/tmp/yps-pattern-atlas-1.1-venv/bin/python -m pip install \
  'jsonschema==4.10.3' 'matplotlib==3.8.4' 'numpy==1.26.4' \
  'scipy==1.11.4' 'pytest==8.4.2' 'ruff==0.16.5'
```

源锁只能在正式源码、配置、schema 和环境全部冻结后显式生成。生成器会向上查找同时含 `AGENTS.md` 与正式 `FWD-TORUS-1.0` 后端的仓库根，不依赖固定父目录层数：

```bash
PYTHONPATH=src /tmp/yps-pattern-atlas-1.1-venv/bin/python \
  tools/generate_source_manifest_lock.py
PYTHONPATH=src /tmp/yps-pattern-atlas-1.1-venv/bin/python \
  tools/generate_source_manifest_lock.py --check
```

运行全量图谱时把生成输出写到正式源码树之外：

```bash
PYTHONPATH=src /tmp/yps-pattern-atlas-1.1-venv/bin/python \
  -m y_pendulum_pattern_atlas \
  --config configs/atlas_v1.json \
  --output /tmp/yps-pattern-atlas-run/full
```

快速子集增加 `--smoke`。如需显式指定仓库根，从本目录使用 `--repository-root ../../..`。

全量复算完成后，可对至少两份独立输出执行：

```bash
/tmp/yps-pattern-atlas-1.1-venv/bin/python tools/verify_full_repeats.py \
  /path/to/repeat-1 /path/to/repeat-2 /path/to/repeat-3 \
  --project-root . \
  --output /tmp/yps-pattern-atlas-full-repeat-verification.json
```

## 5. 验证层级

测试和图谱复算属于实现级测试与理想模型数值验证。它们不覆盖：

- 连续柔索或离散杆动力学；
- RC1 或 HF-v2 高保真数值资格；
- 静态或动态接触；
- 装置参数定值；
- 实验验证。

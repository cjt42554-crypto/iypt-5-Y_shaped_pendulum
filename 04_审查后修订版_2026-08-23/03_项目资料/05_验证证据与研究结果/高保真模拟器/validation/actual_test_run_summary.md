# 实际测试运行摘要：YP-FPSim 1.0.0rc1

## 状态结论

当前候选版本在冻结的轴向柔索范围内达到 `VERIFIED`：解析/半解析基准、守恒与功率、数值收敛、跨求解器一致性、安装包完整性和源码 ZIP 完整性均已实际执行。没有封存的真实实验数据，因此没有标记为 `VALIDATED` 或 `PREDICTIVE`。

## 运行环境

- Python：3.13.5，GCC 14.2.0；
- 平台：Linux 6.18.35 x86_64，glibc 2.41；
- 核心依赖：NumPy、SciPy、Pydantic、PyYAML、h5py、pandas、Matplotlib、Plotly、pytest；
- 未在本环境完成：Pint 主路径、Streamlit 浏览器、Hypothesis、Ruff、mypy、标准 `python -m build`、联网 `uv lock`、Docker 构建。

完整环境缺口见 `CODEX_CONTINUATION_AND_ENVIRONMENT_GAPS.md`。

## 自动测试

实际命令：

```bash
pytest -q
```

结果：

```text
41 passed
```

没有跳过或预期失败测试。覆盖内容包括：

- 单边 Kelvin–Voigt、本构能量梯度、解析切线和网格客观性；
- 一致/集总质量、气动力、相机、曝光与随机噪声；
- 局部松绳导致串联传力链断开；
- 静力平衡、局部稳定性、弹性预紧几何；
- Radau 与稀疏二阶 Newmark；
- HDF5 单位/说明合同与重启元数据；
- 非零释放速度的受拉相容投影；
- 规定支点运动的边界惯性和支点功—能闭合；
- 连续主频细化、短记录拒绝、H1 线性模态；
- 实验前向比较及显式 nuisance 参数恢复；
- 数值回归和发布版本元数据一致性。

## V-001 至 V-013

实际命令：

```bash
ypendulum validate-suite --output-directory validation/generated/final_full
```

结果：13/13 PASS。主要数值：

| 案例 | 指标 | 阈值 |
|---|---:|---:|
| V-001 单元拉伸 | 8.88e-16 | 1e-8 |
| V-002 有质量悬链线 | 4.07e-3 | 1e-2 |
| V-003 纵波速度 | 1.14e-4 | 1e-2 |
| V-006 H1 环面极限 | 1.84e-5 | 5e-4 |
| V-007 有限结点特征值 | 4.66e-12 | 2e-3 |
| V-010 松弛—重新受拉 | 7.40e-6 | 1e-3 |
| V-011 镜像对称 | 6.10e-10 | 2e-4 |
| V-012 质量缩放 | 9.52e-5 | 1e-4 |
| V-013 相机/曝光 | 2.22e-16 | 1e-10 |

完整数据见 `validation/validation_report.json` 和 `.md`。

## 收敛与跨求解器

实际命令：

```bash
ypendulum converge configs/examples/convergence_bdf_small.yaml
```

总体 PASS：

| 检查 | 轨迹归一化 RMS | 低频相对差 | 最大张力相对差 | 能量残差差 |
|---|---:|---:|---:|---:|
| 空间 N/2N | 8.69e-4 | 4.05e-6 | 2.89e-5 | 5.01e-17 |
| 时间精度 | 2.25e-10 | 0 | 1.12e-14 | 6.52e-17 |
| Radau/BDF | 1.44e-5 | 0 | 1.24e-13 | 9.24e-14 |

该小系统矩阵用于快速回归；高刚度、长时间、重新受拉峰值仍须对每个正式实验配置单独做网格、步长和输出带宽收敛。

## 安装与归档审计

已经实际执行：

1. editable 安装后运行全部测试；
2. `pip wheel --no-build-isolation` 构建 wheel；
3. 卸载 editable 版本，只安装 wheel，并在源码树之外运行 41 项测试：全部通过；
4. 用 setuptools PEP 517 后端构建 sdist，解压后运行 41 项测试：全部通过；
5. 构建完整项目 ZIP，校验内部 213 项文件 SHA-256 清单；
6. 连续构建两次完整 ZIP，字节级 SHA-256 相同；
7. 解压完整 ZIP，在解压目录运行 41 项测试和发布检查：全部通过。

完整 ZIP 的最终哈希不能写进 ZIP 内部摘要而不形成自引用，因此由同目录外部 `.sha256.txt` 记录。

## 尚未完成的验收

- 安装全部 extras 的干净 Python 3.11；
- Pint 与后备单位解析器双路径一致性；
- Streamlit 浏览器级交互；
- Ruff、mypy、Hypothesis；
- 标准 `python -m build` 双产物；
- `uv lock` 与 `uv sync --frozen`；
- Docker 实际构建；
- 高刚度长时生产网格的工程性能；
- 重新受拉峰值的专门空间/时间/采样带宽收敛；
- 封存真实实验验证。

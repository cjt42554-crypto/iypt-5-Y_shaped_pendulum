# 发布候选审计

## 当前已通过

- [x] 完整源码树恢复并可 editable 安装；
- [x] wheel 脱离源码树安装后通过全部测试；
- [x] 受拉相容初始速度投影与规定支点功—能测试；
- [x] 可重复完整 ZIP 构建与内部清单验证脚本；
- [x] 实际测试运行摘要和环境清单；
- [x] 两次完整 ZIP 构建得到相同 SHA-256；
- [x] 完整 ZIP 解压后通过全部测试和发布检查；
- [x] sdist 解压后通过全部测试；
- [x] 41 项自动测试；
- [x] V-001–V-013 全部通过；
- [x] A0/A1/H1 与解析极限；
- [x] 单边张力、静力残差和局部稳定性；
- [x] 功—能账本；
- [x] 小系统 N/2N、production/reference、Radau/BDF；
- [x] 配置/验证清单 schema；
- [x] CLI、HDF5、实验 CSV、标定、诊断、消融和不确定度源码；
- [x] 用户、API、理论、数值、限制与 ADR 文档；
- [x] LICENSE、CHANGELOG、Dockerfile、CI 和完整 ZIP 构建脚本。

## 当前未通过或未在本环境验证

- [ ] 安装全部依赖的全新 Python 3.11 环境；
- [ ] Pint 主路径测试；
- [ ] Streamlit 浏览器级运行；
- [ ] Ruff；
- [ ] mypy；
- [ ] `python -m build` 正式 wheel/sdist；
- [ ] `uv.lock` 联网解析及 `uv sync --frozen`；
- [ ] Docker 实际构建；
- [ ] 高刚度长时生产 H1 工程可用性；
- [ ] 重新受拉峰值专门 N/2N/时间/带宽收敛；
- [ ] 真实封存实验验证。

## 科学状态

当前允许：`DERIVED`、`VERIFIED`；具有独立参数文件的个别运行可标记 `CALIBRATED`。没有真实验证清单时不得标记 `VALIDATED` 或 `PREDICTIVE`。

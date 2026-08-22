# 原生桌面 GUI 最终短测记录

日期：2026-08-22（Asia/Singapore）  
定位：个人科研计算原型；没有运行新的长窗 HF 算例。

## 构造与覆盖

命令：

```bash
xvfb-run -a .venv/bin/python -m ypendulum.cli ui --smoke-test
```

结果：

```json
{
  "backend_modes": ["both", "forward", "high_fidelity"],
  "forward_leaf_fields": 237,
  "forward_visible_fields": 237,
  "high_fidelity_leaf_fields": 115,
  "high_fidelity_visible_fields": 115,
  "native_windowing": "tkinter",
  "network_service": false,
  "workflow_modes": ["batch", "repeat", "same_input_dual", "single", "sweep"]
}
```

## Python 回归

在项目源码通过 `PYTHONPATH=src` 运行：

```text
tests/unit/test_desktop_config.py
tests/unit/test_desktop_results.py
tests/unit/test_ui_platform.py
tests/unit/test_ui_problem_plugins.py
tests/unit/test_cli_status_contract.py
tests/unit/test_high_fidelity_model.py
```

结果：

```text
62 passed in 16.02 s
```

Ruff 对所有新增/修改 GUI Python 文件与测试：

```text
All checks passed!
```

## 真实进程控制

独立假后端任务由 GUI 同一 `PersistentJobManager` 运行：

```text
START  RUNNING
PAUSE PAUSED
RESUME RUNNING
FINAL  COMPLETED  exit=0  terminal_reason=COMPLETE
```

控制使用独立进程组 `SIGSTOP / SIGCONT / SIGTERM`；这项测试没有修改求解器状态。

## 真实双后端短链路

见 `short_both_run/`：

- FWD：`COMPLETED / SUCCESS_SINGLE_RUN`；
- HF：`UNDETERMINED / SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED`；
- 两端各 81 个 presentation samples；
- comparison：`COMPARISON_COMPLETE`；
- 规范 FWD NPZ、HF HDF5、能量图、张力图、守卫、事件和比较 NPZ 均随包提供。

窗口截图不是绘制的 UI mockup：它由同一 `YPendulumDesktopApp` 构造并加载该真实结果目录后，在离线 Xvfb 显示器中抓取。


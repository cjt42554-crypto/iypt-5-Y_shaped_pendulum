#!/usr/bin/env python3
"""Layout-v2 entrypoint for the preserved corrective evidence generator."""

from __future__ import annotations

from pathlib import Path

import run_corrective_evidence_impl as _impl

# Preserve the reviewed generator implementation and adapt only its repository
# location contract. All evidence gates and calculations continue to execute in
# the imported implementation module with these globals replaced before main().
_impl.REVISION = (
    "90_候选工作区/current/候选实现或候选内容/"
    "04_审查后修订版_2026-08-23"
)
_impl.SIM_RELATIVE = Path(
    _impl.REVISION
    + "/02_最终模拟程序/02_第一性原理高保真模拟器/"
    "Y-Pendulum-Simulator-v1.0.0-rc1"
)
_impl.FWD_RELATIVE = Path(
    _impl.REVISION
    + "/02_最终模拟程序/01_前向预测数值求解器/"
    "y_pendulum_forward_solver"
)

main = _impl.main


def __getattr__(name: str):
    return getattr(_impl, name)


if __name__ == "__main__":
    raise SystemExit(main())

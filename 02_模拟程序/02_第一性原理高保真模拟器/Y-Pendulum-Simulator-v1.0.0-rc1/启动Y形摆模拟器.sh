#!/usr/bin/env bash
set -euo pipefail

simulator_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${YPENDULUM_PYTHON:-}" ]]; then
  runtime_python="$YPENDULUM_PYTHON"
elif [[ -x "$simulator_root/.venv/bin/python" ]]; then
  runtime_python="$simulator_root/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  runtime_python="$(command -v python3)"
else
  printf '未找到可用的 Python 3。可设置 YPENDULUM_PYTHON，或在模拟器目录创建 .venv。
' >&2
  exit 1
fi

if [[ ! -x "$runtime_python" ]]; then
  printf '指定的 Python 不可执行：%s
' "$runtime_python" >&2
  exit 1
fi

export PYTHONPATH="$simulator_root/src${PYTHONPATH:+:$PYTHONPATH}"
cd -- "$simulator_root"
exec "$runtime_python" -m ypendulum.cli ui

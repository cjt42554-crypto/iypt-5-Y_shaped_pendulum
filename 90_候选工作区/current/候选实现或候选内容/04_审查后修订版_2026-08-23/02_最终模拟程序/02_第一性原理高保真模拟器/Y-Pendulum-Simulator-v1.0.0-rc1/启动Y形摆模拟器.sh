#!/usr/bin/env bash
set -euo pipefail

simulator_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_root="$(cd -- "$simulator_root/../../.." && pwd)"
runtime_python="$workspace_root/03_项目资料/09_本机环境与缓存/高保真模拟器_venv/bin/python"

if [[ ! -x "$runtime_python" ]]
then
  printf '未找到高保真模拟器 Python 环境：%s\n' "$runtime_python" >&2
  exit 1
fi

export PYTHONPATH="$simulator_root/src${PYTHONPATH:+:$PYTHONPATH}"
cd -- "$simulator_root"
exec "$runtime_python" -m ypendulum.cli ui

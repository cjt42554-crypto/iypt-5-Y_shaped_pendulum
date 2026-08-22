"""Persistent-job adapter that routes the copied GUI to the revised HF runner."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from ypendulum.ui.desktop_config import (
    DesktopYPendulumAdapter,
    _load_json,
    canonical_json_sha256,
    validate_desktop_request,
)

from .desktop_contract import user_scan_coordinates


class RevisedDesktopYPendulumAdapter(DesktopYPendulumAdapter):
    """Use the inherited request/result contract but a revised child worker."""

    def build_command(
        self, config_path: Path, *, backend: str, output_directory: Path
    ) -> list[str]:
        request = _load_json(config_path)
        identity = validate_desktop_request(request)
        if identity["backend"] != backend:
            raise ValueError(
                f"Run-plan backend {backend!r} differs from request backend "
                f"{identity['backend']!r}."
            )
        return [
            sys.executable,
            "-m",
            "ypendulum.scientific_revision.revised_desktop_worker",
            str(config_path.resolve()),
            "--backend",
            backend,
            "--output",
            str(output_directory.resolve()),
        ]

    def validate_scan_coordinates(
        self, path: Path, coordinates: dict[str, Any]
    ) -> dict[str, Any]:
        request = _load_json(path)
        validate_desktop_request(request)
        request_coordinates = user_scan_coordinates(request)
        if canonical_json_sha256(request_coordinates) != canonical_json_sha256(coordinates):
            raise ValueError("扫描坐标与 GUI 生成的运行请求不一致。")
        return deepcopy(coordinates)

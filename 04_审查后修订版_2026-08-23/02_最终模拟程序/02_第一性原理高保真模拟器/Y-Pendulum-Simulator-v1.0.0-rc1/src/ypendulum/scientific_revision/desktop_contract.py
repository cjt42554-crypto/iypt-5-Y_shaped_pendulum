"""Reserved desktop-request metadata for the scientific revision layer."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

OVERLAY_PATH_KEY = "__scientific_revision_overlay_path__"
OVERLAY_SHA256_KEY = "__scientific_revision_overlay_sha256__"
RESERVED_SCAN_COORDINATE_KEYS = frozenset({OVERLAY_PATH_KEY, OVERLAY_SHA256_KEY})


def scientific_revision_metadata(request: Mapping[str, Any]) -> dict[str, str]:
    coordinates = request.get("scan_coordinates", {})
    if not isinstance(coordinates, Mapping):
        raise ValueError("scan_coordinates 必须是映射。")
    path = coordinates.get(OVERLAY_PATH_KEY)
    digest = coordinates.get(OVERLAY_SHA256_KEY)
    if not isinstance(path, str) or not path.strip():
        raise ValueError("桌面请求缺少科学修订 overlay 路径。")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("桌面请求缺少有效的 overlay SHA-256。")
    return {"overlay_path": path, "overlay_sha256": digest.lower()}


def user_scan_coordinates(request: Mapping[str, Any]) -> dict[str, Any]:
    coordinates = request.get("scan_coordinates", {})
    if not isinstance(coordinates, Mapping):
        raise ValueError("scan_coordinates 必须是映射。")
    return {
        str(key): deepcopy(value)
        for key, value in coordinates.items()
        if key not in RESERVED_SCAN_COORDINATE_KEYS
    }

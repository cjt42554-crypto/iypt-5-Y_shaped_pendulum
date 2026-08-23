"""Pre-frozen event qualification executor and existing-run diagnostics."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .numerics import trapezoid_integral

DIAGNOSTIC_SCHEMA = "YPS-EVENT-DIAGNOSTIC-2.0"
EXECUTION_SCHEMA = "YPS-EVENT-QUALIFICATION-EXECUTION-2.0"
LEGACY_DIAGNOSTIC_SCHEMA = "YPS-EVENT-QUALIFICATION-1.1"
QUALIFICATION_SCHEMA = DIAGNOSTIC_SCHEMA


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_worktree_clean() -> bool:
    try:
        status = subprocess.check_output(
            ["git", "status", "--porcelain=v1"],
            cwd=Path(__file__).resolve().parent,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return not bool(status.strip())


@dataclass(frozen=True)
class Thresholds:
    trajectory_normalized_rms: float = 1.0e-3
    event_time_absolute_s: float = 1.0e-4
    event_time_relative: float = 5.0e-3
    peak_tension_relative: float = 2.0e-2
    tension_impulse_relative: float = 2.0e-2
    energy_residual_absolute: float = 1.0e-7

    def __post_init__(self) -> None:
        for item in fields(self):
            value = float(getattr(self, item.name))
            if not np.isfinite(value) or value < 0.0:
                raise ValueError(f"阈值 {item.name} 必须是有限非负数。")


@dataclass(frozen=True, order=True)
class EventIdentity:
    branch: str
    material_coordinate_or_segment: str
    event_type: str
    direction: str
    ordinal: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunData:
    label: str
    path: Path
    summary: dict[str, Any]
    events: list[dict[str, Any]]
    time: np.ndarray
    bob_position: np.ndarray
    branch_tension: dict[str, np.ndarray]
    balance_residual: np.ndarray | None


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 根节点必须是映射。")
    return payload


def _load_events(path: Path) -> list[dict[str, Any]]:
    qualified = path / "qualification-events.json"
    if qualified.is_file():
        payload = json.loads(qualified.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ValueError(f"{qualified} 必须是事件对象列表。")
        return [dict(item) for item in payload]
    source = path / "events.csv"
    if not source.is_file():
        return []
    with source.open("r", encoding="utf-8", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _finite_array(name: str, value: Any) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} 含非有限值。")
    return array


def _load_run(label: str, path: Path) -> RunData:
    summary = _load_mapping(path / "summary.json")
    with np.load(path / "trajectory.npz", allow_pickle=False) as archive:
        time = _finite_array("time", archive["time"])
        bob_position = _finite_array("bob_position", archive["bob_position"])
        branch_tension = {
            key.removeprefix("tension_"): _finite_array(key, archive[key])
            for key in archive.files
            if key.startswith("tension_")
        }
        balance = (
            _finite_array("energy_balance_residual", archive["energy_balance_residual"])
            if "energy_balance_residual" in archive
            else (
                _finite_array("energy_balance", archive["energy_balance"])
                if "energy_balance" in archive
                else None
            )
        )
    if time.ndim != 1 or time.size < 2 or np.any(np.diff(time) <= 0.0):
        raise ValueError(f"{path} 的 time 必须是一维严格递增序列。")
    if bob_position.shape != (time.size, 3):
        raise ValueError(f"{path} 的 bob_position 形状不兼容。")
    if not branch_tension:
        raise ValueError(f"{path} 缺少事件局部支路张力数组。")
    for name, values in branch_tension.items():
        if values.ndim == 1:
            values = values[:, None]
            branch_tension[name] = values
        if values.ndim != 2 or values.shape[0] != time.size:
            raise ValueError(f"{path} 的 tension_{name} 形状不兼容。")
    if balance is not None and balance.shape != (time.size,):
        raise ValueError(f"{path} 的 energy_balance_residual 形状不兼容。")
    return RunData(
        label=label,
        path=path,
        summary=summary,
        events=_load_events(path),
        time=time,
        bob_position=bob_position,
        branch_tension=branch_tension,
        balance_residual=balance,
    )


def _event_time(event: Mapping[str, Any]) -> float | None:
    value = event.get("time_s", event.get("time"))
    if value in {None, ""}:
        return None
    try:
        scalar = float(value)
    except (TypeError, ValueError):
        return None
    return scalar if np.isfinite(scalar) else None


def _selector(event: Mapping[str, Any]) -> str:
    explicit = event.get("material_coordinate_or_segment")
    if explicit not in {None, ""}:
        return str(explicit)
    coordinate = event.get("material_coordinate")
    if coordinate not in {None, ""}:
        return f"coordinate:{float(coordinate):.17g}"
    segment = event.get("material_segment")
    if segment not in {None, ""}:
        return f"segment:{int(segment)}"
    return ""


def _event_identity(event: Mapping[str, Any], fallback_ordinal: int) -> EventIdentity:
    ordinal_value = event.get("ordinal", fallback_ordinal)
    try:
        ordinal = int(ordinal_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"事件 ordinal 非法：{ordinal_value!r}") from exc
    identity = EventIdentity(
        branch=str(event.get("branch", "")),
        material_coordinate_or_segment=_selector(event),
        event_type=str(event.get("event_type", event.get("type", ""))),
        direction=str(event.get("direction", "")),
        ordinal=ordinal,
    )
    if (
        not identity.branch
        or not identity.material_coordinate_or_segment
        or not identity.event_type
        or not identity.direction
        or identity.ordinal < 1
    ):
        raise ValueError(
            "事件身份必须包含 branch、material_coordinate_or_segment、"
            "event_type、direction 和正 ordinal。"
        )
    return identity


def _ordered_timed_events(run: RunData) -> list[tuple[float, EventIdentity, dict[str, Any]]]:
    values: list[tuple[float, EventIdentity, dict[str, Any], int]] = []
    counters: dict[tuple[str, str, str, str], int] = {}
    for index, event in enumerate(run.events):
        time = _event_time(event)
        if time is None:
            continue
        selector = _selector(event)
        counter_key = (
            str(event.get("branch", "")),
            selector,
            str(event.get("event_type", event.get("type", ""))),
            str(event.get("direction", "")),
        )
        counters[counter_key] = counters.get(counter_key, 0) + 1
        identity = _event_identity(event, counters[counter_key])
        values.append((time, identity, dict(event), index))
    values.sort(key=lambda item: (item[0], item[3]))
    return [(time, identity, event) for time, identity, event, _index in values]


def _event_time_comparison(left: RunData, right: RunData) -> dict[str, Any]:
    left_events = _ordered_timed_events(left)
    right_events = _ordered_timed_events(right)
    nonempty = bool(left_events) and bool(right_events)
    count_equal = len(left_events) == len(right_events)
    order_equal = count_equal and [item[1] for item in left_events] == [
        item[1] for item in right_events
    ]
    differences = (
        [abs(a[0] - b[0]) for a, b in zip(left_events, right_events, strict=True)]
        if nonempty and order_equal
        else []
    )
    maximum = max(differences, default=0.0)
    duration = max(
        min(left.time[-1], right.time[-1]) - max(left.time[0], right.time[0]),
        np.finfo(float).tiny,
    )
    return {
        "event_set_nonempty": nonempty,
        "event_identities_equal": order_equal,
        "event_counts_equal": count_equal,
        "event_order_equal": order_equal,
        "maximum_event_time_absolute_s": maximum if nonempty and order_equal else None,
        "maximum_event_time_relative": (
            maximum / duration if nonempty and order_equal else None
        ),
    }


def _trajectory_nrms(left: RunData, right: RunData) -> float:
    start = max(float(left.time[0]), float(right.time[0]))
    stop = min(float(left.time[-1]), float(right.time[-1]))
    if stop <= start:
        raise ValueError("比较运行没有共同时间窗。")
    sample_time = left.time[(left.time >= start) & (left.time <= stop)]
    if sample_time.size < 2:
        sample_time = np.linspace(start, stop, 2)
    left_position = np.column_stack(
        [
            np.interp(sample_time, left.time, left.bob_position[:, component])
            for component in range(3)
        ]
    )
    right_position = np.column_stack(
        [
            np.interp(sample_time, right.time, right.bob_position[:, component])
            for component in range(3)
        ]
    )
    difference = np.linalg.norm(left_position - right_position, axis=1)
    all_position = np.vstack((left_position, right_position))
    scale = max(
        float(np.linalg.norm(np.ptp(all_position, axis=0))),
        float(
            np.max(
                np.linalg.norm(all_position - np.mean(all_position, axis=0), axis=1)
            )
        ),
        1.0e-12,
    )
    return float(np.sqrt(np.mean(difference**2)) / scale)


def _relative_difference(left: float, right: float) -> float:
    return abs(left - right) / max(abs(left), abs(right), 1.0e-12)


def _segment_index(selector: str, segment_count: int) -> int:
    if selector.startswith("segment:"):
        index = int(selector.split(":", 1)[1])
    elif selector.startswith("coordinate:"):
        coordinate = float(selector.split(":", 1)[1])
        if not 0.0 <= coordinate <= 1.0:
            raise ValueError("事件材料坐标必须位于归一化区间 [0,1]。")
        index = min(int(np.floor(coordinate * segment_count)), segment_count - 1)
    else:
        raise ValueError(f"未知事件材料定位规则：{selector!r}")
    if not 0 <= index < segment_count:
        raise ValueError(f"事件材料段 {index} 越出 [0,{segment_count})。")
    return index


def _windowed_series(
    time: np.ndarray,
    values: np.ndarray,
    start: float,
    stop: float,
) -> tuple[np.ndarray, np.ndarray]:
    if not time[0] <= start < stop <= time[-1]:
        raise ValueError(
            f"事件窗 [{start:.9g},{stop:.9g}] 越出运行区间 "
            f"[{time[0]:.9g},{time[-1]:.9g}]。"
        )
    interior = time[(time > start) & (time < stop)]
    selected_time = np.concatenate(([start], interior, [stop]))
    selected_values = np.interp(selected_time, time, values)
    return selected_time, selected_values


def _local_event_metrics(run: RunData) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for event_time, identity, event in _ordered_timed_events(run):
        before = float(event.get("window_before_s", event.get("delta_before_s", np.nan)))
        after = float(event.get("window_after_s", event.get("delta_after_s", np.nan)))
        if not np.isfinite(before) or not np.isfinite(after) or before <= 0.0 or after <= 0.0:
            raise ValueError("每个资格事件必须预先冻结正的前后事件窗。")
        if identity.branch not in run.branch_tension:
            raise ValueError(f"运行缺少事件支路张力：{identity.branch}")
        tension = run.branch_tension[identity.branch]
        index = _segment_index(identity.material_coordinate_or_segment, tension.shape[1])
        local_time, local_tension = _windowed_series(
            run.time,
            tension[:, index],
            event_time - before,
            event_time + after,
        )
        metrics.append(
            {
                "identity": identity.to_dict(),
                "time_s": event_time,
                "window_before_s": before,
                "window_after_s": after,
                "resolved_segment": index,
                "local_peak_tension_N": float(np.max(local_tension)),
                "local_tension_impulse_N_s": float(
                    trapezoid_integral(local_tension, local_time)
                ),
            }
        )
    return metrics


def _summary_energy(run: RunData) -> float:
    if run.balance_residual is not None:
        return float(np.max(np.abs(run.balance_residual)))
    value = run.summary.get("max_abs_energy_balance_residual", np.nan)
    try:
        scalar = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return scalar if np.isfinite(scalar) else float("nan")


def compare_runs(left: RunData, right: RunData, thresholds: Thresholds) -> dict[str, Any]:
    event = _event_time_comparison(left, right)
    trajectory = _trajectory_nrms(left, right)
    local_left = _local_event_metrics(left)
    local_right = _local_event_metrics(right)
    local_comparable = event["event_identities_equal"] and len(local_left) == len(local_right)
    peak_differences = (
        [
            _relative_difference(
                left_item["local_peak_tension_N"], right_item["local_peak_tension_N"]
            )
            for left_item, right_item in zip(local_left, local_right, strict=True)
        ]
        if local_comparable
        else []
    )
    impulse_differences = (
        [
            _relative_difference(
                left_item["local_tension_impulse_N_s"],
                right_item["local_tension_impulse_N_s"],
            )
            for left_item, right_item in zip(local_left, local_right, strict=True)
        ]
        if local_comparable
        else []
    )
    energy_left = _summary_energy(left)
    energy_right = _summary_energy(right)
    metrics = {
        "trajectory_normalized_rms": trajectory,
        "peak_tension_relative_difference": max(peak_differences, default=float("inf")),
        "tension_impulse_relative_difference": max(
            impulse_differences, default=float("inf")
        ),
        "maximum_energy_residual": max(abs(energy_left), abs(energy_right)),
        "event_local_metrics_left": local_left,
        "event_local_metrics_right": local_right,
        **event,
    }
    checks = {
        "event_set_nonempty": bool(metrics["event_set_nonempty"]),
        "event_identities_equal": bool(metrics["event_identities_equal"]),
        "event_counts_equal": bool(metrics["event_counts_equal"]),
        "event_order_equal": bool(metrics["event_order_equal"]),
        "event_time_absolute": bool(
            metrics["maximum_event_time_absolute_s"] is not None
            and metrics["maximum_event_time_absolute_s"]
            <= thresholds.event_time_absolute_s
        ),
        "event_time_relative": bool(
            metrics["maximum_event_time_relative"] is not None
            and metrics["maximum_event_time_relative"]
            <= thresholds.event_time_relative
        ),
        "trajectory": trajectory <= thresholds.trajectory_normalized_rms,
        "peak_tension": metrics["peak_tension_relative_difference"]
        <= thresholds.peak_tension_relative,
        "tension_impulse": metrics["tension_impulse_relative_difference"]
        <= thresholds.tension_impulse_relative,
        "energy_residual": np.isfinite(metrics["maximum_energy_residual"])
        and metrics["maximum_energy_residual"] <= thresholds.energy_residual_absolute,
    }
    return {
        "left": left.label,
        "right": right.label,
        "metrics": metrics,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _write_report(output: Path, report: dict[str, Any]) -> None:
    (output / "event-qualification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 事件工况资格报告",
        "",
        f"- 总体：`{'PASS' if report['passed'] else 'FAIL'}`",
        f"- 工具角色：`{report['tool_role']}`",
        "- 张力冲量：运行前冻结事件窗、支路和材料位置的局部积分",
        "- 数值资格：`false`（本报告不自动授予生产资格）",
        "",
        "| 比较 | 类型 | 状态 | 轨迹 NRMS | 事件时间差/s | 局部峰值张力差 | 局部冲量差 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in report["comparisons"]:
        metric = item["metrics"]
        event_time = metric["maximum_event_time_absolute_s"]
        lines.append(
            f"| {item['left']} → {item['right']} | {item['kind']} | "
            f"{'PASS' if item['passed'] else 'FAIL'} | "
            f"{metric['trajectory_normalized_rms']:.6g} | "
            f"{event_time if event_time is not None else '—'} | "
            f"{metric['peak_tension_relative_difference']:.6g} | "
            f"{metric['tension_impulse_relative_difference']:.6g} |"
        )
    lines.extend(["", report["interpretation"], ""])
    (output / "event-qualification.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def compare_event_runs(
    plan_path: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    """Diagnostic comparator for runs that already exist."""

    plan_source = Path(plan_path).expanduser().resolve()
    plan = _load_mapping(plan_source)
    if plan.get("schema_version") not in {
        DIAGNOSTIC_SCHEMA,
        LEGACY_DIAGNOSTIC_SCHEMA,
    }:
        raise ValueError(f"event diagnostic schema 必须是 {DIAGNOSTIC_SCHEMA}。")
    thresholds = Thresholds(**dict(plan.get("thresholds", {})))
    raw_runs = plan.get("runs")
    if not isinstance(raw_runs, list) or len(raw_runs) < 2:
        raise ValueError("runs 至少需要两个运行。")
    runs: dict[str, RunData] = {}
    for item in raw_runs:
        if not isinstance(item, dict) or not {"label", "path"}.issubset(item):
            raise ValueError("每个 run 必须包含 label 和 path。")
        label = str(item["label"])
        path = Path(item["path"]).expanduser()
        if not path.is_absolute():
            path = (plan_source.parent / path).resolve()
        if label in runs:
            raise ValueError(f"重复运行标签：{label}")
        runs[label] = _load_run(label, path)
    raw_comparisons = plan.get("comparisons")
    if raw_comparisons is None:
        labels = list(runs)
        raw_comparisons = [
            {"left": left, "right": right, "kind": "adjacent"}
            for left, right in zip(labels[:-1], labels[1:], strict=True)
        ]
    if not isinstance(raw_comparisons, list) or not raw_comparisons:
        raise ValueError("comparisons 必须是非空列表。")
    comparisons: list[dict[str, Any]] = []
    for item in raw_comparisons:
        if not isinstance(item, dict) or not {"left", "right"}.issubset(item):
            raise ValueError("每个 comparison 必须包含 left 和 right。")
        left = str(item["left"])
        right = str(item["right"])
        if left not in runs or right not in runs:
            raise ValueError(f"未知比较运行：{left}, {right}")
        result = compare_runs(runs[left], runs[right], thresholds)
        result["kind"] = str(item.get("kind", "unspecified"))
        comparisons.append(result)
    report = {
        "schema_version": DIAGNOSTIC_SCHEMA,
        "tool_role": "diagnostic_comparator_existing_runs",
        "thresholds": asdict(thresholds),
        "comparisons": comparisons,
        "passed": all(item["passed"] for item in comparisons),
        "numerically_qualified": False,
        "interpretation": (
            "这是已有运行的诊断比较；它没有生成矩阵，不能单独构成数值资格。"
        ),
    }
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    _write_report(output, report)
    return report


def qualify_event_plan(plan_path: str | Path, output_directory: str | Path) -> dict[str, Any]:
    """Backward-compatible name for the explicitly diagnostic comparator."""

    return compare_event_runs(plan_path, output_directory)


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value):
            child = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(value[key], child))
        return result
    return {prefix: value}


_AXIS_WHITELISTS = {
    "space": {
        "cables.upper_A.elements",
        "cables.upper_B.elements",
        "cables.lower.elements",
    },
    "time": {"solver.max_step.value"},
    "output": {"solver.output_dt.value"},
    "solver": {"solver.method"},
}


def validate_axis_variant(
    base: Mapping[str, Any],
    candidate: Mapping[str, Any],
    axis: str,
) -> tuple[str, ...]:
    if axis not in _AXIS_WHITELISTS:
        raise ValueError(f"未知资格矩阵轴：{axis}")
    left = _flatten(dict(base))
    right = _flatten(dict(candidate))
    changed = tuple(
        sorted(
            key
            for key in left.keys() | right.keys()
            if left.get(key, object()) != right.get(key, object())
        )
    )
    unexpected = sorted(set(changed) - _AXIS_WHITELISTS[axis])
    if unexpected:
        raise ValueError(f"{axis} 轴出现白名单外参数漂移：{unexpected}")
    return changed


def _resolve_input(plan_source: Path, value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f"{name} 必须是计划目录内的非空相对路径。")
    if ".." in Path(value).parts:
        raise ValueError(f"{name} 不得越出计划目录。")
    root = plan_source.parent.resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise ValueError(f"{name} 不是计划目录内的普通文件。")
    return path


def _quantity(value: float, unit: str) -> dict[str, Any]:
    return {"value": float(value), "unit": unit}


def _validate_matrix_axes(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {"space", "time", "output", "solver"}:
        raise ValueError("matrix_axes 必须且只能包含 space、time、output、solver。")
    space = raw["space"]
    time_axis = raw["time"]
    output = raw["output"]
    solver = raw["solver"]
    if not isinstance(space, dict) or space.get("factors") != [1, 2, 4]:
        raise ValueError("space 轴必须预冻结为 N/2N/4N，即 factors: [1,2,4]。")
    if not isinstance(time_axis, dict) or len(time_axis.get("max_step_s", [])) != 2:
        raise ValueError("time 轴必须包含两个独立 max_step 加密值。")
    if not isinstance(output, dict) or len(output.get("output_dt_s", [])) != 2:
        raise ValueError("output 轴必须包含两个独立 output_dt 加密值。")
    if not isinstance(solver, dict) or solver.get("methods") != ["Radau", "BDF"]:
        raise ValueError("solver 轴必须预冻结为 Radau/BDF 交叉检查。")
    for name, values in (
        ("time.max_step_s", time_axis["max_step_s"]),
        ("output.output_dt_s", output["output_dt_s"]),
    ):
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and np.isfinite(float(value))
            and float(value) > 0.0
            for value in values
        ):
            raise ValueError(f"{name} 必须是有限正数列表。")
        if not float(values[1]) < float(values[0]):
            raise ValueError(f"{name} 的第二个值必须严格加密。")
    return raw


def _planned_events(raw: Any, duration: float) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("planned_events 必须是非空事件列表。")
    events: list[dict[str, Any]] = []
    identities: set[EventIdentity] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError("planned_events 每项必须是对象。")
        event = dict(item)
        identity = _event_identity(event, index)
        if identity in identities:
            raise ValueError(f"重复预冻结事件身份：{identity}")
        identities.add(identity)
        time = _event_time(event)
        before = float(event.get("window_before_s", np.nan))
        after = float(event.get("window_after_s", np.nan))
        if (
            time is None
            or not np.isfinite(before)
            or not np.isfinite(after)
            or before <= 0.0
            or after <= 0.0
            or time - before < 0.0
            or time + after > duration
        ):
            raise ValueError("预冻结事件时间和局部窗必须完整位于运行区间内。")
        event.update(identity.to_dict())
        event["time_s"] = time
        event["window_before_s"] = before
        event["window_after_s"] = after
        events.append(event)
    return events


def _members(base: dict[str, Any], axes: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    members: list[tuple[str, str, dict[str, Any]]] = []
    explicit_cables = base.get("cables", {})
    if any(
        not isinstance(explicit_cables.get(name), dict)
        or "elements" not in explicit_cables[name]
        for name in ("upper_A", "upper_B", "lower")
    ):
        raise ValueError("事件资格 base_config 必须显式给出三支 elements，不能使用 inherit。")
    for factor in axes["space"]["factors"]:
        candidate = deepcopy(base)
        for name in ("upper_A", "upper_B", "lower"):
            candidate["cables"][name]["elements"] = (
                int(base["cables"][name]["elements"]) * int(factor)
            )
        members.append((f"space-{factor}N", "space", candidate))
    for index, value in enumerate(axes["time"]["max_step_s"], start=1):
        candidate = deepcopy(base)
        candidate["solver"]["max_step"] = _quantity(float(value), "s")
        members.append((f"time-{index}", "time", candidate))
    for index, value in enumerate(axes["output"]["output_dt_s"], start=1):
        candidate = deepcopy(base)
        candidate["solver"]["output_dt"] = _quantity(float(value), "s")
        members.append((f"output-{index}", "output", candidate))
    for method in axes["solver"]["methods"]:
        candidate = deepcopy(base)
        candidate["solver"]["method"] = method
        members.append((f"solver-{method.lower()}", "solver", candidate))
    return members


def _comparison_plan() -> list[dict[str, str]]:
    return [
        {"left": "space-1N", "right": "space-2N", "kind": "space"},
        {"left": "space-2N", "right": "space-4N", "kind": "space"},
        {"left": "time-1", "right": "time-2", "kind": "time"},
        {"left": "output-1", "right": "output-2", "kind": "output"},
        {
            "left": "solver-radau",
            "right": "solver-bdf",
            "kind": "solver",
        },
    ]


def execute_event_qualification(
    plan_path: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    """Generate and compare a small matrix directly from one immutable plan."""

    from ypendulum.config.units import to_si

    from .runner import run_revised_high_fidelity

    plan_source = Path(plan_path).expanduser().resolve()
    raw_plan = plan_source.read_bytes()
    plan = _load_mapping(plan_source)
    if plan.get("schema_version") != EXECUTION_SCHEMA:
        raise ValueError(f"event executor schema 必须是 {EXECUTION_SCHEMA}。")
    if not isinstance(plan.get("plan_id"), str) or not plan["plan_id"].strip():
        raise ValueError("plan_id 必须是非空字符串。")
    live_commit = _git_commit()
    if live_commit is None or plan.get("git_commit") != live_commit:
        raise ValueError(
            f"计划源码提交与当前提交不一致：plan={plan.get('git_commit')}, live={live_commit}"
        )
    if not _git_worktree_clean():
        raise ValueError("事件资格执行器要求干净工作树，以便将运行绑定到确切提交。")
    base_config_path = _resolve_input(plan_source, plan.get("base_config"), "base_config")
    overlay_path = _resolve_input(plan_source, plan.get("overlay"), "overlay")
    initial_state_path = _resolve_input(
        plan_source, plan.get("initial_state"), "initial_state"
    )
    identities = {
        "base_config_sha256": _sha256(base_config_path.read_bytes()),
        "overlay_sha256": _sha256(overlay_path.read_bytes()),
        "initial_state_sha256": _sha256(initial_state_path.read_bytes()),
    }
    for name, actual in identities.items():
        if plan.get(name) != actual:
            raise ValueError(f"{name} 与计划输入不一致。")
    base = _load_mapping(base_config_path)
    initial_state = _load_mapping(initial_state_path)
    if _canonical_bytes(base.get("initial_condition")) != _canonical_bytes(initial_state):
        raise ValueError("base_config.initial_condition 与封存 initial_state 不一致。")
    if base.get("run", {}).get("mode") != "high_fidelity":
        raise ValueError("事件资格 base_config 必须使用 high_fidelity 模式。")
    duration = float(to_si(base["solver"]["t_end"], default_unit="s"))
    if not 0.0 < duration <= 0.002:
        raise ValueError("本纠正任务的事件冒烟运行时长必须位于 (0, 2 ms]。")
    axes = _validate_matrix_axes(plan.get("matrix_axes"))
    thresholds = Thresholds(**dict(plan.get("thresholds", {})))
    planned_events = _planned_events(plan.get("planned_events"), duration)

    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    raw_sha = _sha256(raw_plan)
    canonical_plan = _canonical_bytes(plan)
    canonical_sha = _sha256(canonical_plan)
    (output / "qualification-plan.raw").write_bytes(raw_plan)
    (output / "qualification-plan.raw.sha256").write_text(raw_sha + "\n", encoding="ascii")
    (output / "qualification-plan.canonical.json").write_bytes(canonical_plan)
    (output / "qualification-plan.canonical.sha256").write_text(
        canonical_sha + "\n", encoding="ascii"
    )
    plan_created_at = _utc_now()
    run_root = output / "runs"
    config_root = output / "member-configs"
    run_root.mkdir()
    config_root.mkdir()
    run_data: dict[str, RunData] = {}
    member_records: list[dict[str, Any]] = []
    for label, axis, candidate in _members(base, axes):
        changed_paths = validate_axis_variant(base, candidate, axis)
        config_path = config_root / f"{label}.yaml"
        config_path.write_text(
            yaml.safe_dump(candidate, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        member_config_sha = _sha256(config_path.read_bytes())
        started = _utc_now()
        execution_identity = {
            "schema_version": EXECUTION_SCHEMA,
            "plan_id": plan["plan_id"],
            "raw_plan_sha256": raw_sha,
            "canonical_plan_sha256": canonical_sha,
            "git_commit": live_commit,
            **identities,
            "member_label": label,
            "matrix_axis": axis,
            "changed_paths": list(changed_paths),
            "member_config_sha256": member_config_sha,
            "plan_created_at_utc": plan_created_at,
            "member_started_at_utc": started,
        }
        run_path = run_root / label
        run_revised_high_fidelity(
            config_path,
            overlay_path,
            run_path,
            execution_identity=execution_identity,
        )
        (run_path / "qualification-events.json").write_text(
            json.dumps(planned_events, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        data = _load_run(label, run_path)
        run_data[label] = data
        member_records.append(
            {
                **execution_identity,
                "member_ended_at_utc": _utc_now(),
                "run_directory": f"runs/{label}",
                "event_count": len(data.events),
                "event_local_metrics": _local_event_metrics(data),
            }
        )

    comparisons: list[dict[str, Any]] = []
    for comparison in _comparison_plan():
        result = compare_runs(
            run_data[comparison["left"]],
            run_data[comparison["right"]],
            thresholds,
        )
        result["kind"] = comparison["kind"]
        comparisons.append(result)
    source_unchanged = _git_commit() == live_commit and _git_worktree_clean()
    plan_unchanged = _sha256(plan_source.read_bytes()) == raw_sha
    report = {
        "schema_version": EXECUTION_SCHEMA,
        "tool_role": "pre_frozen_executor_generated_runs",
        "plan_id": plan["plan_id"],
        "raw_plan_sha256": raw_sha,
        "canonical_plan_sha256": canonical_sha,
        "plan_created_at_utc": plan_created_at,
        "plan_unchanged_after_runs": plan_unchanged,
        "git_commit": live_commit,
        **identities,
        "thresholds": asdict(thresholds),
        "matrix_axes": axes,
        "members": member_records,
        "comparisons": comparisons,
        "plan_frozen": plan_unchanged,
        "executor_generated_runs": True,
        "event_local_impulse": True,
        "source_unchanged_after_runs": source_unchanged,
        "passed": (
            plan_unchanged
            and source_unchanged
            and all(item["passed"] for item in comparisons)
        ),
        "actual_evidence_level": "MODEL_CONSISTENT",
        "maximum_permitted_smoke_level": "CODE_VERIFIED",
        "numerically_qualified": False,
        "experimentally_validated": False,
        "predictive": False,
        "interpretation": (
            "这是 2 ms 以内、使用计划局部张力探针事件的执行器全流程冒烟；"
            "它证明身份、生成、比较与失败关闭机制，不是生产数值资格或实验验证。"
        ),
    }
    _write_report(output, report)
    if not report["passed"]:
        raise RuntimeError("低成本事件资格执行器冒烟矩阵未通过。")
    return report

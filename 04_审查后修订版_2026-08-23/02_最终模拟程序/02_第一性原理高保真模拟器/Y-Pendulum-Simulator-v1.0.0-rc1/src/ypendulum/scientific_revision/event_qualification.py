"""Event-rich space/time/output refinement qualification for revised runs."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

QUALIFICATION_SCHEMA = "YPS-EVENT-QUALIFICATION-1.1"


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


@dataclass
class RunData:
    label: str
    path: Path
    summary: dict[str, Any]
    events: list[dict[str, str]]
    time: np.ndarray
    bob_position: np.ndarray
    max_tension: np.ndarray
    balance_residual: np.ndarray | None


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 根节点必须是映射。")
    return payload


def _load_events(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as stream:
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
        if "max_tension" in archive:
            max_tension = _finite_array("max_tension", archive["max_tension"])
        else:
            branch_keys = [key for key in archive.files if key.startswith("tension_")]
            if not branch_keys:
                raise ValueError(f"{path} 缺少 max_tension 或分支张力数组。")
            max_tension = np.max(
                np.concatenate(
                    [_finite_array(key, archive[key]) for key in branch_keys], axis=1
                ),
                axis=1,
            )
        balance = (
            _finite_array("energy_balance_residual", archive["energy_balance_residual"])
            if "energy_balance_residual" in archive
            else None
        )
    if time.ndim != 1 or time.size < 2 or np.any(np.diff(time) <= 0.0):
        raise ValueError(f"{path} 的 time 必须是一维严格递增序列。")
    if bob_position.shape != (time.size, 3):
        raise ValueError(f"{path} 的 bob_position 形状不兼容。")
    if max_tension.shape != (time.size,):
        raise ValueError(f"{path} 的 max_tension 形状不兼容。")
    if balance is not None and balance.shape != (time.size,):
        raise ValueError(f"{path} 的 energy_balance_residual 形状不兼容。")
    return RunData(
        label=label,
        path=path,
        summary=summary,
        events=_load_events(path / "events.csv"),
        time=time,
        bob_position=bob_position,
        max_tension=max_tension,
        balance_residual=balance,
    )


def _event_key(event: Mapping[str, str]) -> tuple[str, str, str]:
    return (
        str(event.get("type", "")),
        str(event.get("branch", "")),
        str(event.get("material_segment", "")),
    )


def _event_time(event: Mapping[str, str]) -> float | None:
    value = event.get("time", event.get("time_s"))
    if value in {None, ""}:
        return None
    try:
        scalar = float(value)
    except (TypeError, ValueError):
        return None
    return scalar if np.isfinite(scalar) else None


def _ordered_timed_events(run: RunData) -> list[tuple[float, tuple[str, str, str]]]:
    values: list[tuple[float, tuple[str, str, str], int]] = []
    for index, event in enumerate(run.events):
        time = _event_time(event)
        if time is not None:
            values.append((time, _event_key(event), index))
    values.sort(key=lambda item: (item[0], item[2]))
    return [(time, key) for time, key, _index in values]


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
    comparable = nonempty and order_equal
    return {
        "event_set_nonempty": nonempty,
        "event_keys_equal": order_equal,
        "event_counts_equal": count_equal,
        "event_order_equal": order_equal,
        "maximum_event_time_absolute_s": maximum if comparable else None,
        "maximum_event_time_relative": maximum / duration if comparable else None,
    }


def _trajectory_nrms(left: RunData, right: RunData) -> float:
    start = max(float(left.time[0]), float(right.time[0]))
    stop = min(float(left.time[-1]), float(right.time[-1]))
    if stop <= start:
        raise ValueError("比较运行没有共同时间窗。")
    sample_time = left.time[(left.time >= start) & (left.time <= stop)]
    if sample_time.size < 2:
        sample_time = np.linspace(start, stop, 2)
    right_position = np.column_stack(
        [
            np.interp(sample_time, right.time, right.bob_position[:, component])
            for component in range(3)
        ]
    )
    left_position = np.column_stack(
        [
            np.interp(sample_time, left.time, left.bob_position[:, component])
            for component in range(3)
        ]
    )
    difference = np.linalg.norm(left_position - right_position, axis=1)
    all_position = np.vstack((left_position, right_position))
    scale = max(
        float(np.linalg.norm(np.ptp(all_position, axis=0))),
        float(
            np.max(
                np.linalg.norm(
                    all_position - np.mean(all_position, axis=0), axis=1
                )
            )
        ),
        1.0e-12,
    )
    return float(np.sqrt(np.mean(difference**2)) / scale)


def _relative_difference(left: float, right: float) -> float:
    return abs(left - right) / max(abs(left), abs(right), 1.0e-12)


def _tension_impulse(run: RunData) -> float:
    integrate = getattr(np, "trapezoid", np.trapz)
    return float(integrate(run.max_tension, run.time))


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
    peak_left = float(np.max(left.max_tension))
    peak_right = float(np.max(right.max_tension))
    impulse_left = _tension_impulse(left)
    impulse_right = _tension_impulse(right)
    energy_left = _summary_energy(left)
    energy_right = _summary_energy(right)
    metrics = {
        "trajectory_normalized_rms": trajectory,
        "peak_tension_relative_difference": _relative_difference(peak_left, peak_right),
        "tension_impulse_relative_difference": _relative_difference(
            impulse_left, impulse_right
        ),
        "maximum_energy_residual": max(abs(energy_left), abs(energy_right)),
        **event,
    }
    checks = {
        "event_set_nonempty": bool(metrics["event_set_nonempty"]),
        "event_keys_equal": bool(metrics["event_keys_equal"]),
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


def qualify_event_plan(plan_path: str | Path, output_directory: str | Path) -> dict[str, Any]:
    plan_source = Path(plan_path).expanduser().resolve()
    plan = _load_mapping(plan_source)
    if plan.get("schema_version") != QUALIFICATION_SCHEMA:
        raise ValueError(f"event qualification schema 必须是 {QUALIFICATION_SCHEMA}。")
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
            for left, right in zip(labels[:-1], labels[1:])
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
        "schema_version": QUALIFICATION_SCHEMA,
        "thresholds": asdict(thresholds),
        "thresholds_source": "pre_frozen_plan_file",
        "comparisons": comparisons,
        "passed": all(item["passed"] for item in comparisons),
        "interpretation": (
            "这是事件富集离散运行的经验资格证据；不是连续 PDE 误差证明，也不是实验验证。"
        ),
    }
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "event-qualification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 事件工况数值资格报告",
        "",
        f"- 总体：`{'PASS' if report['passed'] else 'FAIL'}`",
        "- 阈值来源：运行前冻结的 plan 文件",
        "",
        "| 比较 | 类型 | 状态 | 轨迹 NRMS | 事件时间差/s | 峰值张力差 | 张力冲量差 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in comparisons:
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
    lines.extend(["", report["interpretation"]])
    (output / "event-qualification.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return report

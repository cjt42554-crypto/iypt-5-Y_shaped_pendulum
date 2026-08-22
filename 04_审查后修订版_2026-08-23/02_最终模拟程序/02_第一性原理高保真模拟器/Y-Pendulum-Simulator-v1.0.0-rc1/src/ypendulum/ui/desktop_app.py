"""Offline native Tk desktop application for the Y-pendulum research tools.

This module is intentionally a user-interface and orchestration layer.  It
contains no equations of motion and starts no HTTP service.  The complete FWD
and HF parameter trees are generated from resolved configuration snapshots so
new scientific parameters remain visible and editable without hand-editing
YAML or JSON.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import queue
import shutil
import threading
import time
import tkinter as tk
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

import numpy as np
from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # type: ignore[import-untyped]

from ypendulum.ui.desktop_config import (
    DESKTOP_PLUGIN_ID,
    INITIAL_RELEASE_FIELD_NAMES,
    PROJECT_ROOT,
    DesktopYPendulumAdapter,
    InitialReleaseParameters,
    ParameterField,
    apply_initial_release_to_forward,
    apply_initial_release_to_hf,
    apply_parameter_values,
    default_desktop_configuration,
    estimate_reference_periods,
    format_parameter_value,
    get_path,
    initial_release_from_forward,
    initial_release_from_hf,
    load_desktop_request,
    load_forward_profile,
    load_hf_profile,
    make_desktop_request,
    numeric_sweep_values,
    parameter_fields,
    parse_parameter_text,
    synchronize_shared_forward_to_hf,
    validate_desktop_request,
    write_desktop_request,
)
from ypendulum.ui.desktop_results import (
    BackendPlotData,
    DesktopPlotBundle,
    common_geometry_time_window,
    endpoint_chord_paths,
    geometry_paths_at_time,
    geometry_scene_cube,
    interpolate_vector_series,
    load_desktop_output,
    trajectory_plane_square,
)
from ypendulum.ui.platform import (
    ACTIVE_STATES,
    PersistentJobManager,
    PluginRegistry,
    RunPlanItem,
    SweepPoint,
    expand_run_plan,
)

BACKEND_LABELS = {
    "前向预测 (FWD)": "forward",
    "高保真 (HF)": "high_fidelity",
    "同输入双后端": "both",
}
BACKEND_NAMES = {value: key for key, value in BACKEND_LABELS.items()}
MODE_LABELS = {
    "单次": "single",
    "重复": "repeat",
    "批量": "batch",
    "参数扫描": "sweep",
    "同输入双后端": "same_input_dual",
}
MODE_NAMES = {value: key for key, value in MODE_LABELS.items()}

SCENE_COLORS = {
    "forward": "#111111",
    "high_fidelity": "#d9822b",
}
PLOT_COLORS = ("#111111", "#555555", "#929292", "#c1c1c1")
PLOT_STYLES = {"forward": "-", "high_fidelity": "--"}
PLOT_BACKEND_NAMES = {"forward": "FWD", "high_fidelity": "HF"}
BRANCH_COLOR_INDEX = {"A": 0, "upper_A": 0, "B": 1, "upper_B": 1, "lower": 2}
GEOMETRY_TICK_MS = 20
READABLE_RESULT_STATES = frozenset({"COMPLETED", "OUT_OF_SCOPE_PREFIX"})
WAITABLE_JOB_STATES = frozenset({"QUEUED", *ACTIVE_STATES})

FORWARD_DERIVED_INITIAL_PATHS = frozenset(
    {
        "initial_state.r_J",
        "initial_state.v_J",
        "initial_state.r_m",
        "initial_state.v_m",
        "initial_state.branches.A.position.coefficients",
        "initial_state.branches.A.velocity.coefficients",
        "initial_state.branches.B.position.coefficients",
        "initial_state.branches.B.velocity.coefficients",
        "initial_state.branches.lower.position.coefficients",
        "initial_state.branches.lower.velocity.coefficients",
    }
)
HF_DERIVED_INITIAL_PATHS = frozenset(
    {
        "initial_condition.junction_position",
        "initial_condition.junction_velocity",
        "initial_condition.bob_position",
        "initial_condition.bob_velocity",
        "initial_condition.bob_angular_velocity",
    }
)


def _physical_playback_fraction(
    start_fraction: float,
    elapsed_s: float,
    speed: float,
    physical_duration_s: float,
) -> float:
    """Advance an animation fraction using physical, rather than clip, time."""

    values = (start_fraction, elapsed_s, speed, physical_duration_s)
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("Playback timing values must be finite.")
    if elapsed_s < 0.0 or speed <= 0.0 or physical_duration_s <= 0.0:
        raise ValueError("Playback elapsed time must be non-negative; speed/duration positive.")
    return float(start_fraction) + float(elapsed_s) * float(speed) / float(
        physical_duration_s
    )

INITIAL_RELEASE_FIELD_SPECS: tuple[
    tuple[str, str, str, str, str], ...
] = (
    (
        "geometry",
        "upper_a_length_m",
        "上支 A 几何长度",
        "m",
        "支点 A 到结点的释放瞬间距离；这是几何长度，不是材料静长 L₀。",
    ),
    (
        "geometry",
        "upper_b_length_m",
        "上支 B 几何长度",
        "m",
        "支点 B 到结点的释放瞬间距离；两条上支必须与支点间距组成非退化三角形。",
    ),
    (
        "geometry",
        "junction_roll_deg",
        "结点绕轴角 ψ",
        "°",
        "0° 位于重力向下平面；正方向按 A→B 支点轴的右手定则。",
    ),
    (
        "geometry",
        "lower_branch_length_m",
        "下支长度 ℓ",
        "m",
        "Y 形摆的下支有效几何长度；FWD 的点摆球端点采用该参考长度，HF 的有限球面附件偏置由高保真后端独立处理。",
    ),
    (
        "geometry",
        "lower_polar_deg",
        "摆球偏角 α",
        "°",
        "摆球方向偏离结点局部向下方向的夹角；0° 表示摆球在结点正下方。",
    ),
    (
        "geometry",
        "lower_azimuth_deg",
        "摆球方位角 β",
        "°",
        "偏角在局部切平面中的方向；0° 指向 A→B，正方向朝绕轴切向。",
    ),
    (
        "rates",
        "upper_a_length_rate_m_s",
        "上支 A 几何长度率",
        "m/s",
        "释放瞬间支点 A—结点距离的变化率。",
    ),
    (
        "rates",
        "upper_b_length_rate_m_s",
        "上支 B 几何长度率",
        "m/s",
        "释放瞬间支点 B—结点距离的变化率。",
    ),
    (
        "rates",
        "junction_roll_rate_deg_s",
        "结点绕轴角速度 ψ̇",
        "°/s",
        "结点绕 A→B 支点轴的释放角速度。",
    ),
    (
        "rates",
        "lower_length_rate_m_s",
        "下支长度率 ℓ̇",
        "m/s",
        "释放瞬间下支有效几何长度的变化率。",
    ),
    (
        "rates",
        "lower_polar_rate_deg_s",
        "摆球偏角速度 α̇",
        "°/s",
        "摆球偏角的释放角速度。",
    ),
    (
        "rates",
        "lower_azimuth_rate_deg_s",
        "摆球方位角速度 β̇",
        "°/s",
        "摆球方位角的释放角速度；偏角为 0° 时方位率不可辨识并按 0 处理。",
    ),
    (
        "spin",
        "bob_spin_support_deg_s",
        "HF 摆球自旋：沿支点轴",
        "°/s",
        "有限刚体摆球绕 A→B 支点轴的自旋；FWD 点质量模型不消费该量。",
    ),
    (
        "spin",
        "bob_spin_radial_deg_s",
        "HF 摆球自旋：沿局部径向",
        "°/s",
        "有限刚体摆球沿结点局部向下径向的自旋。",
    ),
    (
        "spin",
        "bob_spin_tangent_deg_s",
        "HF 摆球自旋：沿绕轴切向",
        "°/s",
        "有限刚体摆球沿结点绕轴切向的自旋。",
    ),
)


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("文件根节点必须是对象。")
    return value


def _backend_legend_handles(backends: list[BackendPlotData]) -> list[Line2D]:
    """Compact backend key for plots where colour already identifies a quantity."""

    return [
        Line2D(
            [],
            [],
            color="#222222",
            linestyle=PLOT_STYLES[data.backend],
            linewidth=1.5,
            label=PLOT_BACKEND_NAMES[data.backend],
        )
        for data in backends
    ]


def _compact_guard_label(backend: str, name: str) -> str:
    """Make the external guard index readable without hiding exact exported names."""

    prefix = PLOT_BACKEND_NAMES[backend]
    parts = name.split(":")
    quantity_names = {
        "lambda_upper": "λ+",
        "lambda_lower": "λ−",
        "rate_upper": "dλ+",
        "rate_lower": "dλ−",
    }
    if len(parts) == 5 and parts[0] == "MATERIAL_DOMAIN" and parts[3] == "element":
        return f"{prefix} {parts[1]} {quantity_names.get(parts[2], parts[2])} e{parts[4]}"
    if len(parts) == 4 and parts[0] == "LAMBDA_MIN" and parts[2] == "element":
        return f"{prefix} λmin {parts[1]} e{parts[3]}"
    aliases = {
        "lambda": "λ",
        "material_lambda": "λ(material)",
        "material_rate": "dλ/dt(material)",
        "AERODYNAMIC_CHORD_LENGTH": "aero chord",
        "BENDING_TURN_CLEARANCE": "bend-turn gap",
        "BOB_ROD_CLEARANCE": "bob-rod gap",
        "BOB_SOCKET_CUT_CLEARANCE": "bob socket-cut gap",
        "BOB_SOCKET_MATERIAL_EXTENT": "bob socket extent",
        "BOB_SOCKET_RADIAL_MONOTONICITY": "bob socket radial",
        "JUNCTION_SOCKET_CUT_CLEARANCE": "junction cut gap",
        "JUNCTION_SOCKET_MATERIAL_EXTENT": "junction extent",
        "JUNCTION_SOCKET_PROJECTIVE_OPENING": "junction opening",
        "MINIMUM_SEGMENT_LENGTH": "min segment length",
        "ROD_SELF_CLEARANCE": "rod self gap",
    }
    compact = aliases.get(name, name.lower().replace("_", " "))
    if len(compact) > 28:
        compact = compact[:27] + "…"
    return f"{prefix} {compact}"


def _sphere_faces(
    centre: np.ndarray,
    radius: float,
    *,
    longitude_count: int = 20,
    latitude_count: int = 12,
) -> list[np.ndarray]:
    """Return persistent 3-D polygon faces for a physical-radius bob sphere."""

    centre_array = np.asarray(centre, dtype=float)
    if centre_array.shape != (3,) or not np.all(np.isfinite(centre_array)):
        raise ValueError("Sphere centre must be a finite three-vector.")
    if not math.isfinite(radius) or radius <= 0.0:
        raise ValueError("Sphere radius must be finite and positive.")
    if longitude_count < 3 or latitude_count < 3:
        raise ValueError("Sphere mesh needs at least three longitude and latitude samples.")

    longitude = np.linspace(0.0, 2.0 * np.pi, longitude_count, endpoint=False)
    latitude = np.linspace(0.0, np.pi, latitude_count)

    def point(longitude_value: float, latitude_value: float) -> np.ndarray:
        sin_latitude = math.sin(latitude_value)
        return centre_array + radius * np.asarray(
            (
                math.cos(longitude_value) * sin_latitude,
                math.sin(longitude_value) * sin_latitude,
                math.cos(latitude_value),
            )
        )

    faces: list[np.ndarray] = []
    for longitude_index, longitude_value in enumerate(longitude):
        next_longitude = longitude[(longitude_index + 1) % longitude_count]
        for latitude_index in range(latitude_count - 1):
            lower = latitude[latitude_index]
            upper = latitude[latitude_index + 1]
            faces.append(
                np.asarray(
                    (
                        point(longitude_value, lower),
                        point(next_longitude, lower),
                        point(next_longitude, upper),
                        point(longitude_value, upper),
                    )
                )
            )
    return faces


class GuardDetailDialog(simpledialog.Dialog):
    """Structured editor for one FWD physical exit guard."""

    KINDS = (
        "bob_plane",
        "bob_sphere_inside",
        "bob_sphere_outside",
        "node_distance",
    )

    def __init__(self, parent: tk.Misc, initial: dict[str, Any] | None = None) -> None:
        self.initial = deepcopy(initial or {})
        self.result: dict[str, Any] | None = None
        super().__init__(parent, title="物理退出守卫")

    def body(self, master: tk.Misc) -> tk.Widget:
        self.variables: dict[str, tk.StringVar] = {}
        labels = (
            ("kind", "类型"),
            ("name", "名称"),
            ("normal", "平面法向 (x,y,z)"),
            ("offset", "平面偏置 (m)"),
            ("center", "球心 (x,y,z)"),
            ("radius", "球半径 (m)"),
            ("node_1", "结点 1 索引"),
            ("node_2", "结点 2 索引"),
            ("minimum", "最小距离 (m)"),
        )
        defaults = {
            "kind": "bob_plane",
            "name": "guard_1",
            "normal": "0, 0, 1",
            "offset": "1",
            "center": "0, 0, 0",
            "radius": "1",
            "node_1": "0",
            "node_2": "1",
            "minimum": "0.01",
        }
        for row, (key, label) in enumerate(labels):
            ttk.Label(master, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=4)
            value = self.initial.get(key, defaults[key])
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            variable = tk.StringVar(value=str(value))
            self.variables[key] = variable
            if key == "kind":
                widget: tk.Widget = ttk.Combobox(
                    master,
                    textvariable=variable,
                    values=self.KINDS,
                    state="readonly",
                    width=28,
                )
            else:
                widget = ttk.Entry(master, textvariable=variable, width=30)
            widget.grid(row=row, column=1, sticky="ew", padx=6, pady=4)
        master.columnconfigure(1, weight=1)
        return master

    @staticmethod
    def _vector(text: str) -> list[float]:
        values = [float(item.strip()) for item in text.split(",") if item.strip()]
        if len(values) != 3 or not all(math.isfinite(item) for item in values):
            raise ValueError("向量需要 3 个有限分量。")
        return values

    def validate(self) -> bool:
        try:
            kind = self.variables["kind"].get()
            name = self.variables["name"].get().strip()
            if kind not in self.KINDS or not name:
                raise ValueError("守卫类型和名称必填。")
            if kind == "bob_plane":
                self.result = {
                    "kind": kind,
                    "name": name,
                    "normal": self._vector(self.variables["normal"].get()),
                    "offset": float(self.variables["offset"].get()),
                }
            elif kind in {"bob_sphere_inside", "bob_sphere_outside"}:
                self.result = {
                    "kind": kind,
                    "name": name,
                    "center": self._vector(self.variables["center"].get()),
                    "radius": float(self.variables["radius"].get()),
                }
            else:
                self.result = {
                    "kind": kind,
                    "name": name,
                    "node_1": int(self.variables["node_1"].get()),
                    "node_2": int(self.variables["node_2"].get()),
                    "minimum": float(self.variables["minimum"].get()),
                }
            numeric_values = [
                item
                for item in self.result.values()
                if isinstance(item, (int, float)) and not isinstance(item, bool)
            ]
            if not all(math.isfinite(float(item)) for item in numeric_values):
                raise ValueError("所有数值必须有限。")
            return True
        except (TypeError, ValueError) as exc:
            messagebox.showerror("守卫参数错误", str(exc), parent=self)
            return False


class GuardListDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        guards: list[dict[str, Any]],
        callback: Callable[[list[dict[str, Any]]], None],
    ) -> None:
        super().__init__(parent)
        self.title("退出守卫编辑器")
        self.geometry("680x360")
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.guards = deepcopy(guards)
        self.callback = callback
        self.tree = ttk.Treeview(self, columns=("kind", "detail"), show="tree headings")
        self.tree.heading("#0", text="名称")
        self.tree.heading("kind", text="类型")
        self.tree.heading("detail", text="参数")
        self.tree.column("#0", width=150)
        self.tree.column("kind", width=170)
        self.tree.column("detail", width=320)
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)
        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(controls, text="新增", command=self._add).pack(side="left", padx=3)
        ttk.Button(controls, text="编辑", command=self._edit).pack(side="left", padx=3)
        ttk.Button(controls, text="删除", command=self._delete).pack(side="left", padx=3)
        ttk.Button(controls, text="完成", command=self._finish).pack(side="right", padx=3)
        ttk.Button(controls, text="取消", command=self.destroy).pack(side="right", padx=3)
        self.tree.bind("<Double-1>", lambda _event: self._edit())
        self._refresh()

    def _refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, guard in enumerate(self.guards):
            detail = ", ".join(
                f"{key}={value}" for key, value in guard.items() if key not in {"name", "kind"}
            )
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                text=str(guard.get("name", f"guard_{index + 1}")),
                values=(guard.get("kind", ""), detail),
            )

    def _selected_index(self) -> int | None:
        selected = self.tree.selection()
        return None if not selected else int(selected[0])

    def _add(self) -> None:
        dialog = GuardDetailDialog(self)
        if dialog.result is not None:
            self.guards.append(dialog.result)
            self._refresh()

    def _edit(self) -> None:
        index = self._selected_index()
        if index is None:
            messagebox.showinfo("选择守卫", "请先选择要编辑的守卫。", parent=self)
            return
        dialog = GuardDetailDialog(self, self.guards[index])
        if dialog.result is not None:
            self.guards[index] = dialog.result
            self._refresh()

    def _delete(self) -> None:
        index = self._selected_index()
        if index is not None:
            del self.guards[index]
            self._refresh()

    def _finish(self) -> None:
        names = [str(item.get("name", "")) for item in self.guards]
        if len(names) != len(set(names)):
            messagebox.showerror("守卫冲突", "守卫名称必须唯一。", parent=self)
            return
        self.callback(deepcopy(self.guards))
        self.destroy()


class ScrollableDetailBox(ttk.Frame):
    """Bounded, scrollable inline diagnostic details.

    The original inline ``ttk.Label`` requested one row per wrapped error line.
    A validation payload could therefore enlarge the workflow panel until the
    action buttons fell below the window.  This component deliberately keeps a
    fixed text viewport while preserving the existing ``configure(text=...)``
    call surface used throughout the application.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        height: int = 4,
        on_change: Callable[[bool], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._value = ""
        self._on_change = on_change
        self._dialog: tk.Toplevel | None = None
        self._dialog_text: tk.Text | None = None
        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, text="详细信息（可滚动）", foreground="#b3261e").pack(
            side="left"
        )
        ttk.Button(header, text="复制", width=5, command=self._copy).pack(
            side="right", padx=(3, 0)
        )
        ttk.Button(header, text="清除", width=5, command=self._clear).pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="x", pady=(2, 0))
        self.text = tk.Text(
            body,
            height=height,
            wrap="word",
            foreground="#b3261e",
            relief="solid",
            borderwidth=1,
            padx=5,
            pady=4,
            undo=False,
        )
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set, state="disabled")
        self.text.pack(side="left", fill="x", expand=True)
        scroll.pack(side="right", fill="y")

    def _copy(self) -> None:
        if not self._value:
            return
        self.clipboard_clear()
        self.clipboard_append(self._value)

    def _clear(self) -> None:
        self.configure(text="")

    def show_dialog(self, parent: tk.Misc | None = None) -> None:
        """Open the full diagnostic in a bounded, independently scrollable window."""

        if self._dialog is not None and self._dialog.winfo_exists():
            self._dialog.deiconify()
            self._dialog.lift()
            self._dialog.focus_force()
            return
        dialog = tk.Toplevel(parent or self)
        dialog.title("运行与验证详细信息")
        dialog.geometry("820x440")
        dialog.minsize(540, 280)
        dialog.transient(self.winfo_toplevel())
        body = ttk.Frame(dialog, padding=(10, 10, 10, 6))
        body.pack(fill="both", expand=True)
        text_widget = tk.Text(body, wrap="word", foreground="#b3261e", padx=7, pady=7)
        scroll = ttk.Scrollbar(body, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=scroll.set)
        text_widget.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        controls = ttk.Frame(dialog, padding=(10, 0, 10, 10))
        controls.pack(fill="x")
        ttk.Button(controls, text="复制全部", command=self._copy).pack(side="left")
        ttk.Button(controls, text="关闭", command=dialog.destroy).pack(side="right")
        self._dialog = dialog
        self._dialog_text = text_widget
        self._update_dialog_text()
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

    def _update_dialog_text(self) -> None:
        if self._dialog_text is None or not self._dialog_text.winfo_exists():
            self._dialog_text = None
            return
        self._dialog_text.configure(state="normal")
        self._dialog_text.delete("1.0", "end")
        self._dialog_text.insert("1.0", self._value or "当前没有详细信息。")
        self._dialog_text.configure(state="disabled")
        self._dialog_text.yview_moveto(0.0)

    def set_text(self, value: object) -> None:
        self._value = str(value) if value is not None else ""
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if self._value:
            self.text.insert("1.0", self._value)
        self.text.configure(state="disabled")
        self.text.yview_moveto(0.0)
        self._update_dialog_text()
        if self._value:
            self.grid()
        else:
            self.grid_remove()
            if self._dialog is not None and self._dialog.winfo_exists():
                self._dialog.destroy()
            self._dialog = None
            self._dialog_text = None
        if self._on_change is not None:
            self._on_change(bool(self._value))

    def configure(self, cnf: Any | None = None, **kwargs: Any) -> Any:
        if isinstance(cnf, str):
            if cnf == "text":
                return self._value
            return super().configure(cnf)
        options: dict[str, Any] = {}
        if cnf is not None:
            options.update(dict(cnf))
        options.update(kwargs)
        sentinel = object()
        value = options.pop("text", sentinel)
        result = super().configure(**options) if options else None
        if value is not sentinel:
            self.set_text(value)
        return result

    config = configure


class ParameterTreeEditor(ttk.Frame):
    """Hierarchical all-leaf parameter table with one typed editor."""

    def __init__(
        self,
        parent: tk.Misc,
        config: dict[str, Any],
        backend: str,
        *,
        on_change: Callable[[], None] | None = None,
        derived_paths: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.on_change = on_change
        self.derived_paths = derived_paths
        self.base_config: dict[str, Any] = {}
        self.fields: dict[str, ParameterField] = {}
        self.values: dict[str, Any] = {}
        self.errors: dict[str, str] = {}
        self.selected_path: str | None = None

        search_row = ttk.Frame(self)
        search_row.pack(fill="x", padx=4, pady=4)
        ttk.Label(search_row, text="搜索参数").pack(side="left")
        self.search_var = tk.StringVar()
        search = ttk.Entry(search_row, textvariable=self.search_var)
        search.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(search_row, text="清空", command=lambda: self.search_var.set("")).pack(
            side="right"
        )

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=4)
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("value", "unit"),
            show="tree headings",
            selectmode="browse",
        )
        self.tree.heading("#0", text="分类 / 参数")
        self.tree.heading("value", text="当前值")
        self.tree.heading("unit", text="单位")
        self.tree.column("#0", width=205, minwidth=140)
        self.tree.column("value", width=190, minwidth=100)
        self.tree.column("unit", width=72, minwidth=55, anchor="center")
        vertical = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.tree.tag_configure("error", foreground="#b3261e")
        self.tree.tag_configure("locked", foreground="#707070")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        editor = ttk.LabelFrame(self, text="选中参数")
        editor.pack(fill="x", padx=4, pady=5)
        self.editor_title = ttk.Label(editor, text="请从上方选择参数")
        self.editor_title.grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=(5, 2))
        self.path_label = ttk.Label(editor, text="", foreground="#52616b")
        self.path_label.grid(row=1, column=0, columnspan=3, sticky="w", padx=6)
        self.text_var = tk.StringVar()
        self.entry = ttk.Entry(editor, textvariable=self.text_var)
        self.entry.grid(row=2, column=0, sticky="ew", padx=6, pady=5)
        self.choice = ttk.Combobox(editor, textvariable=self.text_var, state="readonly")
        self.bool_var = tk.BooleanVar()
        self.bool_widget = ttk.Checkbutton(editor, text="启用", variable=self.bool_var)
        self.guard_button = ttk.Button(editor, text="编辑守卫列表…", command=self._edit_guards)
        self.apply_button = ttk.Button(editor, text="应用", command=self.commit_selected)
        self.apply_button.grid(row=2, column=1, sticky="e", padx=6, pady=5)
        self.description = ttk.Label(editor, text="", wraplength=430, justify="left")
        self.description.grid(row=3, column=0, columnspan=3, sticky="ew", padx=6)
        self.range_label = ttk.Label(editor, text="", foreground="#52616b", wraplength=430)
        self.range_label.grid(row=4, column=0, columnspan=3, sticky="ew", padx=6, pady=(1, 4))
        self.error_label = ttk.Label(editor, text="", foreground="#b3261e", wraplength=430)
        self.error_label.grid(row=5, column=0, columnspan=3, sticky="ew", padx=6, pady=(0, 5))
        editor.columnconfigure(0, weight=1)
        self.entry.bind("<Return>", lambda _event: self.commit_selected())
        self.entry.bind("<FocusOut>", lambda _event: self.commit_selected(quiet=True))
        self.choice.bind("<<ComboboxSelected>>", lambda _event: self.commit_selected())
        self.bool_widget.configure(command=self._commit_bool)
        self.search_var.trace_add("write", lambda *_args: self._rebuild_tree())
        self.set_config(config)

    def set_config(self, config: dict[str, Any]) -> None:
        self.base_config = deepcopy(config)
        generated = parameter_fields(config, self.backend)
        self.fields = {field.path: field for field in generated}
        self.values = {field.path: deepcopy(field.value) for field in generated}
        self.errors.clear()
        self.selected_path = None
        self._rebuild_tree()

    def set_derived_paths(self, paths: frozenset[str]) -> None:
        """Switch generated coordinate leaves between audit-only and expert editing."""

        selected_path = self.selected_path
        self.derived_paths = paths
        self._rebuild_tree()
        selected_iid = f"field::{selected_path}" if selected_path is not None else ""
        if selected_iid and self.tree.exists(selected_iid):
            self.tree.selection_set(selected_iid)
            self.tree.focus(selected_iid)
            self.tree.see(selected_iid)
            self._on_select()

    def _row_tags(self, path: str) -> tuple[str, ...]:
        field = self.fields[path]
        if path in self.errors:
            return ("error",)
        if not field.editable or path in self.derived_paths:
            return ("locked",)
        return ()

    def _rebuild_tree(self) -> None:
        query = self.search_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        sections: dict[str, str] = {}
        for field in self.fields.values():
            haystack = f"{field.section} {field.label} {field.path}".lower()
            if query and query not in haystack:
                continue
            parent = sections.get(field.section)
            if parent is None:
                parent = f"section::{len(sections)}"
                sections[field.section] = parent
                self.tree.insert("", "end", iid=parent, text=field.section, open=bool(query))
            value = format_parameter_value(self.values[field.path])
            if len(value) > 70:
                value = value[:67] + "…"
            self.tree.insert(
                parent,
                "end",
                iid=f"field::{field.path}",
                text=field.label,
                values=(value, field.unit),
                tags=self._row_tags(field.path),
            )

    def _on_select(self, _event: object | None = None) -> None:
        selected = self.tree.selection()
        if not selected or not selected[0].startswith("field::"):
            return
        path = selected[0][len("field::") :]
        self.selected_path = path
        field = self.fields[path]
        value = self.values[path]
        editable = field.editable and path not in self.derived_paths
        self.editor_title.configure(text=f"{field.label}  [{field.unit}]")
        self.path_label.configure(text=path)
        description = field.description
        if path in self.derived_paths:
            description = (
                "由“初始状态（长度/角度）”页确定性生成，仅供坐标审计；"
                "如需修改，请回到长度/角度页。\n" + description
            )
        self.description.configure(text=description)
        self.range_label.configure(text="合法范围：" + field.legal_range)
        self.error_label.configure(text=self.errors.get(path, ""))
        for widget in (self.entry, self.choice, self.bool_widget, self.guard_button):
            widget.grid_remove()
        if field.kind == "bool":
            self.bool_var.set(bool(value))
            self.bool_widget.configure(state="normal" if editable else "disabled")
            self.bool_widget.grid(row=2, column=0, sticky="w", padx=6, pady=5)
        elif field.kind == "guards":
            self.guard_button.configure(state="normal" if editable else "disabled")
            self.guard_button.grid(row=2, column=0, sticky="w", padx=6, pady=5)
        elif field.choices:
            self.text_var.set(format_parameter_value(value))
            self.choice.configure(values=field.choices)
            self.choice.configure(state="readonly" if editable else "disabled")
            self.choice.grid(row=2, column=0, sticky="ew", padx=6, pady=5)
        else:
            self.text_var.set(format_parameter_value(value))
            self.entry.configure(state="normal" if editable else "disabled")
            self.entry.grid(row=2, column=0, sticky="ew", padx=6, pady=5)
        self.apply_button.configure(state="normal" if editable else "disabled")

    def _commit_bool(self) -> None:
        if self.selected_path is not None:
            self.values[self.selected_path] = bool(self.bool_var.get())
            self.errors.pop(self.selected_path, None)
            self._refresh_selected_row()
            if self.on_change is not None:
                self.on_change()

    def _edit_guards(self) -> None:
        if self.selected_path is None:
            return

        def replace(value: list[dict[str, Any]]) -> None:
            assert self.selected_path is not None
            self.values[self.selected_path] = value
            self.errors.pop(self.selected_path, None)
            self._refresh_selected_row()
            if self.on_change is not None:
                self.on_change()

        GuardListDialog(self, deepcopy(self.values[self.selected_path]), replace)

    def _refresh_selected_row(self) -> None:
        if self.selected_path is None:
            return
        iid = f"field::{self.selected_path}"
        if self.tree.exists(iid):
            field = self.fields[self.selected_path]
            value = format_parameter_value(self.values[self.selected_path])
            self.tree.item(
                iid,
                values=((value[:67] + "…") if len(value) > 70 else value, field.unit),
                tags=self._row_tags(self.selected_path),
            )
        self.error_label.configure(text=self.errors.get(self.selected_path, ""))

    def commit_selected(self, quiet: bool = False) -> bool:
        path = self.selected_path
        if path is None:
            return True
        field = self.fields[path]
        if (
            not field.editable
            or path in self.derived_paths
            or field.kind in {"guards", "bool"}
        ):
            return True
        try:
            self.values[path] = parse_parameter_text(field, self.text_var.get())
            self.errors.pop(path, None)
            self._refresh_selected_row()
            if self.on_change is not None:
                self.on_change()
            return True
        except (TypeError, ValueError) as exc:
            self.errors[path] = str(exc)
            self._refresh_selected_row()
            if not quiet:
                messagebox.showerror("参数错误", f"{path}\n{exc}", parent=self)
            return False

    def get_config(self) -> dict[str, Any]:
        if not self.commit_selected(quiet=True):
            raise ValueError(f"参数 {self.selected_path} 无效。")
        if self.errors:
            raise ValueError("仍有未修正的字段：" + ", ".join(sorted(self.errors)))
        return apply_parameter_values(self.base_config, self.values)

    def numeric_paths(self) -> tuple[str, ...]:
        return tuple(
            field.path
            for field in self.fields.values()
            if field.editable
            and field.path not in self.derived_paths
            and field.kind in {"int", "float"}
        )

    def set_path_value(self, path: str, value: Any) -> None:
        if path not in self.fields:
            raise KeyError(path)
        self.values[path] = deepcopy(value)
        self.errors.pop(path, None)
        self._rebuild_tree()
        if self.on_change is not None:
            self.on_change()


class InitialReleaseEditor(ttk.Frame):
    """Length/angle editor that owns the user-facing release parameterization."""

    def __init__(
        self,
        parent: tk.Misc,
        parameters: InitialReleaseParameters,
        *,
        on_apply: Callable[[], None],
        on_mode_change: Callable[[bool], None],
        on_change: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_apply = on_apply
        self.on_mode_change = on_mode_change
        self.on_change = on_change
        self.variables: dict[str, tk.StringVar] = {}
        self.labels = {name: label for _group, name, label, _unit, _help in INITIAL_RELEASE_FIELD_SPECS}
        if set(self.labels) != set(INITIAL_RELEASE_FIELD_NAMES):
            raise RuntimeError("初始状态编辑器字段与参数合同不一致。")

        canvas_shell = ttk.Frame(self)
        canvas_shell.pack(fill="both", expand=True, padx=4, pady=2)
        self.canvas = tk.Canvas(
            canvas_shell,
            background="#ffffff",
            highlightthickness=0,
            borderwidth=0,
        )
        scroll = ttk.Scrollbar(canvas_shell, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        content = ttk.Frame(self.canvas)
        content_window = self.canvas.create_window((0, 0), window=content, anchor="nw")

        def update_region(_event: object | None = None) -> None:
            bounds = self.canvas.bbox("all")
            if bounds is not None:
                self.canvas.configure(scrollregion=bounds)

        def fit_width(event: tk.Event[tk.Misc]) -> None:
            self.canvas.itemconfigure(content_window, width=event.width)

        content.bind("<Configure>", update_region)
        self.canvas.bind("<Configure>", fit_width)

        group_titles = {
            "geometry": "释放几何（长度 / 角度）",
            "rates": "初始运动（长度率 / 角速度）",
            "spin": "HF 有限刚体摆球自旋",
        }
        group_frames: dict[str, ttk.LabelFrame] = {}
        group_counts: dict[str, int] = {name: 0 for name in group_titles}
        group_rows = {"geometry": 0, "rates": 3, "spin": 4}
        for group, title in group_titles.items():
            frame = ttk.LabelFrame(content, text=title, style="Card.TLabelframe")
            frame.grid(row=group_rows[group], column=0, sticky="ew", padx=3, pady=3)
            frame.columnconfigure(0, weight=1)
            frame.columnconfigure(1, weight=1)
            group_frames[group] = frame
        content.columnconfigure(0, weight=1)

        for group, name, label, unit, _help_text in INITIAL_RELEASE_FIELD_SPECS:
            index = group_counts[group]
            group_counts[group] += 1
            field = ttk.Frame(group_frames[group], padding=(5, 1))
            field.grid(row=index // 2, column=index % 2, sticky="nsew", padx=2, pady=1)
            field.columnconfigure(1, weight=1)
            ttk.Label(field, text=label).grid(row=0, column=0, sticky="w", padx=(0, 4))
            variable = tk.StringVar()
            self.variables[name] = variable
            entry = ttk.Entry(field, textvariable=variable, width=10)
            entry.grid(row=0, column=1, sticky="ew")
            ttk.Label(field, text=unit, foreground="#52616b").grid(
                row=0, column=2, sticky="w", padx=(4, 0)
            )
            entry.bind("<Return>", lambda _event: self.on_apply())
            entry.bind("<FocusOut>", self._changed)

        controls = ttk.Frame(content, padding=(6, 2))
        controls.grid(row=1, column=0, sticky="ew")
        ttk.Button(
            controls,
            text="应用长度/角度到 FWD 与 HF",
            style="Primary.TButton",
            command=self.on_apply,
        ).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(
            controls,
            text="设为静止释放",
            command=self.zero_rates,
        ).pack(side="left", padx=(3, 0))

        intro = ttk.Frame(content, padding=(8, 2))
        intro.grid(row=2, column=0, sticky="ew")
        self.angle_mode_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            intro,
            text="使用长度/角度生成初态（推荐）",
            variable=self.angle_mode_var,
            command=lambda: self.on_mode_change(bool(self.angle_mode_var.get())),
        ).pack(anchor="w", pady=(0, 2))
        ttk.Label(
            intro,
            text=(
                "坐标自动生成并在 FWD/HF 页只读审计。基准：支点轴 A→B；"
                "ψ=0 向下；α=0 正下方；β=0 沿 A→B。"
                "ℓ 为下支有效几何长度，HF 球面附件偏置由后端处理。"
            ),
            wraplength=370,
            justify="left",
            style="Subheader.TLabel",
        ).pack(anchor="w")

        self.preview_var = tk.StringVar(value="尚未生成坐标预览。")
        ttk.Label(
            content,
            textvariable=self.preview_var,
            wraplength=370,
            justify="left",
            foreground="#52616b",
            padding=(7, 2, 7, 6),
        ).grid(row=5, column=0, sticky="ew")
        self.set_parameters(parameters)

    def _changed(self, _event: object | None = None) -> None:
        if self.on_change is not None:
            self.on_change()

    def get_parameters(self) -> InitialReleaseParameters:
        values: dict[str, float] = {}
        for name in INITIAL_RELEASE_FIELD_NAMES:
            text_value = self.variables[name].get().strip()
            try:
                value = float(text_value)
            except ValueError as exc:
                raise ValueError(f"{self.labels[name]} 需要有限实数。") from exc
            if not math.isfinite(value):
                raise ValueError(f"{self.labels[name]} 需要有限实数。")
            values[name] = value
        return InitialReleaseParameters(**values)

    def set_parameters(self, parameters: InitialReleaseParameters) -> None:
        for name in INITIAL_RELEASE_FIELD_NAMES:
            self.variables[name].set(f"{float(getattr(parameters, name)):.12g}")

    def zero_rates(self) -> None:
        for name in INITIAL_RELEASE_FIELD_NAMES:
            if name.endswith("_rate_m_s") or name.endswith("_rate_deg_s") or name.startswith(
                "bob_spin_"
            ):
                self.variables[name].set("0")
        self.on_apply()

    def numeric_paths(self) -> tuple[str, ...]:
        return tuple(f"initial_release.{name}" for name in INITIAL_RELEASE_FIELD_NAMES)

    def is_angle_mode(self) -> bool:
        return bool(self.angle_mode_var.get())

    def set_angle_mode(self, enabled: bool) -> None:
        self.angle_mode_var.set(bool(enabled))

    def set_preview(self, value: str) -> None:
        self.preview_var.set(value)


class YPendulumDesktopApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("IYPT 2027 第 5 题 · Y 形摆研究平台")
        width = min(1540, max(1000, self.root.winfo_screenwidth() - 40))
        height = min(940, max(680, self.root.winfo_screenheight() - 70))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(1180, 720)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._style()
        rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
        rcParams["axes.unicode_minus"] = False
        rcParams["figure.facecolor"] = "#ffffff"
        rcParams["axes.facecolor"] = "#ffffff"
        rcParams["axes.edgecolor"] = "#bdbdbd"
        rcParams["axes.labelcolor"] = "#333333"
        rcParams["text.color"] = "#111111"
        rcParams["xtick.color"] = "#555555"
        rcParams["ytick.color"] = "#555555"
        rcParams["grid.color"] = "#d5d5d5"

        self.state_root = PROJECT_ROOT / "runs" / ".native_desktop"
        self.request_root = self.state_root / "requests"
        self.output_root = PROJECT_ROOT / "runs" / "desktop"
        self.request_root.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.manager = PersistentJobManager(
            self.state_root,
            PluginRegistry([DesktopYPendulumAdapter()]),
            max_parallel=1,
        )
        self.batch_cases: list[dict[str, Any]] = []
        self.current_bundle: DesktopPlotBundle | None = None
        self.current_job_id: str | None = None
        self._load_generation = 0
        self._loading_result_directory: Path | None = None
        self._loaded_result_directory: Path | None = None
        self._failed_result_directories: set[Path] = set()
        self._result_load_queue: queue.Queue[
            tuple[int, Path, DesktopPlotBundle | None, Exception | None]
        ] = queue.Queue()
        self.figures: dict[str, Figure] = {}
        self.canvases: dict[str, FigureCanvasTkAgg] = {}
        self._geometry_scene_limits: tuple[np.ndarray, np.ndarray] | None = None
        self._trajectory_scene_limits: tuple[np.ndarray, np.ndarray] | None = None
        self._geometry_axis: Any | None = None
        self._geometry_top_axis: Any | None = None
        self._geometry_artists: dict[str, dict[str, Any]] = {}
        self._geometry_scene_signature: tuple[Any, ...] | None = None
        self._geometry_after_id: str | None = None
        self._geometry_playing = False
        self._geometry_autoplay_pending = False
        self._geometry_autoplay_output_directory: Path | None = None
        self._geometry_scale_internal = False
        self._geometry_clock_start = 0.0
        self._geometry_fraction_start = 0.0
        self._geometry_view = (22.0, -62.0, 0.0)

        forward, hf = default_desktop_configuration()
        self.forward_config = forward
        self.hf_config = hf
        self._build_ui()
        self._refresh_sweep_paths()
        self._update_window_summary()
        self._poll_jobs()

    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        ink = "#111111"
        muted = "#5b5b5b"
        line = "#cfcfcf"
        soft = "#f5f5f5"
        white = "#ffffff"
        style.configure(".", font=("Noto Sans CJK SC", 10))
        style.configure("TFrame", background=white)
        style.configure("TLabel", background=white, foreground=ink)
        style.configure("TLabelframe", background=white, bordercolor=line, relief="solid")
        style.configure(
            "TLabelframe.Label",
            background=white,
            foreground=ink,
            font=("Noto Sans CJK SC", 10, "bold"),
        )
        style.configure("Card.TLabelframe", background=white, bordercolor=line, relief="solid")
        style.configure(
            "Card.TLabelframe.Label",
            background=white,
            foreground=ink,
            font=("Noto Sans CJK SC", 10, "bold"),
        )
        style.configure(
            "Eyebrow.TLabel",
            font=("DejaVu Sans Mono", 9, "bold"),
            foreground=ink,
        )
        style.configure(
            "Header.TLabel",
            font=("Noto Sans CJK SC", 25, "bold"),
            foreground=ink,
        )
        style.configure("Subheader.TLabel", foreground=muted)
        style.configure(
            "IdentityKey.TLabel",
            font=("Noto Sans CJK SC", 9),
            foreground="#777777",
        )
        style.configure(
            "IdentityValue.TLabel",
            font=("DejaVu Sans Mono", 9, "bold"),
            foreground=ink,
        )
        style.configure(
            "Status.TLabel",
            font=("Noto Sans CJK SC", 9, "bold"),
            foreground=ink,
            bordercolor="#777777",
            borderwidth=1,
            relief="solid",
            padding=(8, 3),
        )
        style.configure(
            "Primary.TButton",
            font=("Noto Sans CJK SC", 10, "bold"),
            foreground=white,
            background=ink,
            bordercolor=ink,
            padding=(10, 6),
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#333333"), ("disabled", "#b8b8b8")],
            foreground=[("disabled", "#efefef")],
        )
        style.configure(
            "Secondary.TButton",
            foreground=ink,
            background=soft,
            bordercolor="#777777",
            padding=(8, 5),
        )
        style.map("Secondary.TButton", background=[("active", "#e9e9e9")])
        style.configure(
            "TButton",
            foreground=ink,
            background=soft,
            bordercolor="#888888",
            padding=(7, 5),
        )
        style.map("TButton", background=[("active", "#e8e8e8")])
        style.configure("TEntry", fieldbackground=white, foreground=ink, bordercolor="#777777")
        style.configure("TCombobox", fieldbackground=white, foreground=ink, bordercolor="#777777")
        style.configure("TNotebook", background=white, bordercolor=line)
        style.configure(
            "TNotebook.Tab",
            background=soft,
            foreground=ink,
            bordercolor=line,
            padding=(10, 6),
        )
        style.map("TNotebook.Tab", background=[("selected", white)])
        style.configure(
            "Treeview",
            background=white,
            fieldbackground=white,
            foreground=ink,
            bordercolor=line,
            rowheight=25,
        )
        style.configure(
            "Treeview.Heading",
            background=soft,
            foreground=ink,
            font=("Noto Sans CJK SC", 9, "bold"),
            bordercolor=line,
        )
        style.map("Treeview", background=[("selected", "#dddddd")], foreground=[("selected", ink)])
        style.configure("Horizontal.TProgressbar", background=ink, troughcolor="#dedede")
        self.root.option_add("*Text.background", white)
        self.root.option_add("*Text.foreground", ink)
        self.root.option_add("*Text.insertBackground", ink)
        self.root.configure(background=white)

    def _build_ui(self) -> None:
        header = ttk.Frame(self.root, padding=(20, 14, 20, 12))
        header.pack(fill="x")
        heading = ttk.Frame(header)
        heading.pack(side="left", fill="x", expand=True)
        ttk.Label(
            heading,
            text="IYPT 2027  ·  PROBLEM 5  ·  RESEARCH EXECUTABLE",
            style="Eyebrow.TLabel",
        ).pack(anchor="w")
        ttk.Label(heading, text="Y 形摆", style="Header.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Label(
            heading,
            text="前向预测数值后端与第一性原理高保真后端共用输入合同；理论、求解与证据状态分别呈现。",
            style="Subheader.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        identity = ttk.Frame(header)
        identity.pack(side="right", anchor="ne", padx=(20, 0), pady=(8, 0))
        for row, (key, value) in enumerate(
            (
                ("模型", "FWD-CABLE / HF-ROD"),
                ("界面", "native dashboard 2.0"),
            )
        ):
            ttk.Label(identity, text=key, style="IdentityKey.TLabel").grid(
                row=row, column=0, sticky="e", padx=(0, 10), pady=2
            )
            ttk.Label(identity, text=value, style="IdentityValue.TLabel").grid(
                row=row, column=1, sticky="w", pady=2
            )
        self.top_status = ttk.Label(identity, text="就绪", style="Status.TLabel")
        self.top_status.grid(row=2, column=0, columnspan=2, sticky="e", pady=(8, 0))

        ttk.Separator(self.root, orient="horizontal").pack(fill="x")
        main = ttk.Panedwindow(self.root, orient="horizontal")
        main.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        left = ttk.Frame(main, width=420)
        right = ttk.Frame(main)
        main.add(left, weight=0)
        main.add(right, weight=1)
        self.main_pane = main
        self._build_left(left)
        self._build_right(right)
        self.root.after_idle(lambda: self.main_pane.sashpos(0, 420))

    def _build_left(self, parent: ttk.Frame) -> None:
        selector = ttk.LabelFrame(parent, text="运行配置", style="Card.TLabelframe")
        selector.pack(fill="x", padx=4, pady=4)
        ttk.Label(selector, text="运行后端").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.backend_var = tk.StringVar(value=BACKEND_NAMES["forward"])
        backend = ttk.Combobox(
            selector,
            textvariable=self.backend_var,
            values=tuple(BACKEND_LABELS),
            state="readonly",
        )
        backend.grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        backend.bind("<<ComboboxSelected>>", lambda _event: self._backend_changed())
        quick_row = ttk.Frame(selector)
        quick_row.grid(row=1, column=0, columnspan=2, sticky="ew", padx=2, pady=3)
        ttk.Button(
            quick_row,
            text="恢复多周期研究默认值",
            style="Secondary.TButton",
            command=self._load_defaults,
        ).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(
            quick_row,
            text="FWD → HF 同步共享输入",
            style="Secondary.TButton",
            command=self._sync_configs,
        ).pack(side="left", fill="x", expand=True, padx=2)
        button_row = ttk.Frame(selector)
        button_row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=2, pady=3)
        ttk.Button(button_row, text="载入运行快照", command=self._load_request).pack(
            side="left", fill="x", expand=True, padx=2
        )
        ttk.Button(button_row, text="保存运行快照", command=self._save_request).pack(
            side="left", fill="x", expand=True, padx=2
        )
        profile_row = ttk.Frame(selector)
        profile_row.grid(row=3, column=0, columnspan=2, sticky="ew", padx=2, pady=3)
        ttk.Button(profile_row, text="导入 FWD JSON", command=self._load_forward_config).pack(
            side="left", fill="x", expand=True, padx=2
        )
        ttk.Button(profile_row, text="导入 HF YAML/JSON", command=self._load_hf_config).pack(
            side="left", fill="x", expand=True, padx=2
        )
        self.window_summary_var = tk.StringVar(value="正在读取当前时间窗…")
        ttk.Label(
            selector,
            textvariable=self.window_summary_var,
            style="Subheader.TLabel",
            wraplength=390,
            justify="left",
        ).grid(row=4, column=0, columnspan=2, sticky="ew", padx=6, pady=(5, 7))
        selector.columnconfigure(1, weight=1)

        sidebar_body = ttk.Panedwindow(parent, orient="vertical")
        sidebar_body.pack(fill="both", expand=True, padx=4, pady=4)
        self.sidebar_pane = sidebar_body
        self.parameter_notebook = ttk.Notebook(sidebar_body)
        self.initial_release_editor = InitialReleaseEditor(
            self.parameter_notebook,
            initial_release_from_forward(self.forward_config),
            on_apply=self._apply_initial_release,
            on_mode_change=self._set_initial_input_mode,
            on_change=self._update_window_summary,
        )
        self.forward_form = ParameterTreeEditor(
            self.parameter_notebook,
            self.forward_config,
            "forward",
            on_change=self._update_window_summary,
            derived_paths=FORWARD_DERIVED_INITIAL_PATHS,
        )
        self.hf_form = ParameterTreeEditor(
            self.parameter_notebook,
            self.hf_config,
            "high_fidelity",
            on_change=self._update_window_summary,
            derived_paths=HF_DERIVED_INITIAL_PATHS,
        )
        self.parameter_notebook.add(
            self.initial_release_editor,
            text="初始状态 · 长度/角度",
        )
        self.parameter_notebook.add(self.forward_form, text="FWD 完整参数 · 坐标只读")
        self.parameter_notebook.add(self.hf_form, text="HF 完整参数 · 坐标只读")
        self._update_initial_release_preview(self.forward_config, self.hf_config)
        self.parameter_notebook.bind(
            "<<NotebookTabChanged>>", lambda _event: self._refresh_sweep_paths()
        )
        sidebar_body.add(self.parameter_notebook, weight=1)

        workflow = ttk.LabelFrame(sidebar_body, text="运行控制", style="Card.TLabelframe")
        sidebar_body.add(workflow, weight=0)
        control_shell = ttk.Frame(workflow)
        control_shell.grid(row=2, column=0, sticky="nsew", padx=3, pady=(1, 4))
        self.workflow_canvas = tk.Canvas(
            control_shell,
            height=105,
            background="#ffffff",
            highlightthickness=0,
            borderwidth=0,
        )
        workflow_scroll = ttk.Scrollbar(
            control_shell,
            orient="vertical",
            command=self.workflow_canvas.yview,
        )
        self.workflow_canvas.configure(yscrollcommand=workflow_scroll.set)
        self.workflow_canvas.pack(side="left", fill="both", expand=True)
        workflow_scroll.pack(side="right", fill="y")
        workflow_controls = ttk.Frame(self.workflow_canvas)
        controls_window = self.workflow_canvas.create_window(
            (0, 0),
            window=workflow_controls,
            anchor="nw",
        )

        def update_workflow_scroll_region(_event: object | None = None) -> None:
            bounds = self.workflow_canvas.bbox("all")
            if bounds is not None:
                self.workflow_canvas.configure(scrollregion=bounds)

        def fit_workflow_width(event: tk.Event[tk.Misc]) -> None:
            self.workflow_canvas.itemconfigure(controls_window, width=event.width)

        workflow_controls.bind("<Configure>", update_workflow_scroll_region)
        self.workflow_canvas.bind("<Configure>", fit_workflow_width)
        self.label_var = tk.StringVar(value="desktop_case")
        self.mode_var = tk.StringVar(value=MODE_NAMES["single"])
        self.repeat_var = tk.IntVar(value=2)
        self.parallel_var = tk.IntVar(value=1)
        labels = (
            ("标签", self.label_var),
            ("重复次数", self.repeat_var),
            ("CPU 并行任务", self.parallel_var),
        )
        self.repeat_widgets: list[tk.Widget] = []
        ttk.Label(workflow_controls, text="方式").grid(
            row=0, column=0, sticky="w", padx=5, pady=3
        )
        mode = ttk.Combobox(
            workflow_controls,
            textvariable=self.mode_var,
            values=tuple(MODE_LABELS),
            state="readonly",
        )
        mode.grid(row=0, column=1, sticky="ew", padx=5, pady=3)
        mode.bind("<<ComboboxSelected>>", lambda _event: self._mode_changed())
        for row, (name, variable) in enumerate(labels, start=1):
            field_label = ttk.Label(workflow_controls, text=name)
            field_label.grid(row=row, column=0, sticky="w", padx=5, pady=3)
            if isinstance(variable, tk.IntVar):
                widget: tk.Widget = ttk.Spinbox(
                    workflow_controls,
                    from_=1,
                    to=12 if variable is self.parallel_var else 999,
                    textvariable=variable,
                    width=8,
                )
            else:
                widget = ttk.Entry(workflow_controls, textvariable=variable)
            widget.grid(row=row, column=1, sticky="ew", padx=5, pady=3)
            if variable is self.repeat_var:
                self.repeat_widgets.extend((field_label, widget))
        self.batch_label = ttk.Label(workflow_controls, text="批量案例：0")
        self.batch_label.grid(row=4, column=0, sticky="w", padx=5, pady=3)
        self.batch_buttons = ttk.Frame(workflow_controls)
        self.batch_buttons.grid(row=4, column=1, sticky="ew")
        ttk.Button(self.batch_buttons, text="加入当前", command=self._add_batch_case).pack(
            side="left", fill="x", expand=True, padx=2
        )
        ttk.Button(self.batch_buttons, text="清空", command=self._clear_batch).pack(
            side="left", padx=2
        )

        self.sweep_frame = ttk.Frame(workflow_controls)
        self.sweep_frame.grid(row=5, column=0, columnspan=2, sticky="ew", padx=4, pady=3)
        self.sweep_backend_var = tk.StringVar(value="forward")
        self.sweep_path_var = tk.StringVar()
        self.sweep_start_var = tk.StringVar(value="0.0005")
        self.sweep_stop_var = tk.StringVar(value="0.0015")
        self.sweep_count_var = tk.IntVar(value=3)
        ttk.Label(self.sweep_frame, text="扫描后端").grid(row=0, column=0, sticky="w")
        sweep_backend = ttk.Combobox(
            self.sweep_frame,
            textvariable=self.sweep_backend_var,
            values=("forward", "high_fidelity"),
            state="readonly",
            width=15,
        )
        sweep_backend.grid(row=0, column=1, sticky="ew", padx=3)
        sweep_backend.bind("<<ComboboxSelected>>", lambda _event: self._refresh_sweep_paths())
        ttk.Label(self.sweep_frame, text="参数路径").grid(row=1, column=0, sticky="w")
        self.sweep_path = ttk.Combobox(
            self.sweep_frame,
            textvariable=self.sweep_path_var,
            state="readonly",
            width=36,
        )
        self.sweep_path.grid(row=1, column=1, columnspan=3, sticky="ew", padx=3)
        for column, (label, variable) in enumerate(
            (
                ("起点", self.sweep_start_var),
                ("终点", self.sweep_stop_var),
                ("点数", self.sweep_count_var),
            )
        ):
            ttk.Label(self.sweep_frame, text=label).grid(row=2, column=2 * column, sticky="w")
            ttk.Entry(self.sweep_frame, textvariable=variable, width=9).grid(
                row=2, column=2 * column + 1, sticky="ew", padx=2
            )
        self.sweep_frame.columnconfigure(1, weight=1)
        self.sweep_frame.columnconfigure(3, weight=1)
        self.sweep_frame.columnconfigure(5, weight=1)

        self.workflow_panel = workflow
        action = ttk.Frame(workflow)
        self.action_frame = action
        action.grid(row=0, column=0, sticky="ew", padx=3, pady=4)
        ttk.Button(
            action,
            text="检查参数",
            width=8,
            style="Secondary.TButton",
            command=self._validate_current,
        ).pack(side="left", padx=2)
        self.run_button = ttk.Button(
            action,
            text="运行",
            width=6,
            style="Primary.TButton",
            command=self._start,
        )
        self.run_button.pack(side="left", padx=2)
        ttk.Button(action, text="暂停", width=5, command=self._pause).pack(
            side="left", padx=2
        )
        ttk.Button(action, text="继续", width=5, command=self._resume).pack(
            side="left", padx=2
        )
        ttk.Button(action, text="停止", width=5, command=self._stop).pack(
            side="left", padx=2
        )
        self.error_details_button = ttk.Button(
            action,
            text="错误详情",
            width=8,
            command=lambda: self.inline_error.show_dialog(self.root),
        )
        self.progress = ttk.Progressbar(workflow, mode="determinate", maximum=100.0)
        self.progress.grid(row=1, column=0, sticky="ew", padx=5, pady=(2, 4))
        self.inline_error = ScrollableDetailBox(
            workflow_controls,
            height=4,
            on_change=self._inline_detail_visibility_changed,
        )
        self.inline_error.grid(row=6, column=0, columnspan=2, sticky="ew", padx=5, pady=(2, 5))
        self.inline_error.configure(text="")
        workflow_controls.columnconfigure(1, weight=1)
        workflow.columnconfigure(0, weight=1)
        workflow.rowconfigure(2, weight=1)
        self._mode_changed()
        self._schedule_sidebar_fit()

    def _inline_detail_visibility_changed(self, visible: bool) -> None:
        if not hasattr(self, "error_details_button"):
            return
        if visible:
            if not self.error_details_button.winfo_manager():
                self.error_details_button.pack(side="left", padx=2)
        else:
            self.error_details_button.pack_forget()
        self._schedule_sidebar_fit()

    def _schedule_sidebar_fit(self) -> None:
        """Keep the complete workflow panel inside the minimum-height window."""

        if not all(
            hasattr(self, name)
            for name in ("root", "sidebar_pane", "workflow_panel")
        ):
            return
        self.root.after_idle(self._fit_workflow_panel)

    def _fit_workflow_panel(self) -> None:
        """Allocate extra sidebar height to expanded controls and diagnostics.

        The parameter tree already owns vertical scrolling, whereas the workflow
        panel contains the only run/stop controls.  At the 1180 x 720 minimum
        window, the three-row sweep editor plus a long validation message needs
        more room than the normal single-run panel.  Move the pane sash upward
        for that state, and restore the usual parameter-tree height when the
        panel contracts.
        """

        total_height = int(self.sidebar_pane.winfo_height())
        required_workflow_height = int(self.workflow_panel.winfo_reqheight())
        if total_height <= 1 or required_workflow_height <= 1:
            return
        minimum_parameter_height = 100
        sash_allowance = 8
        target = total_height - required_workflow_height - sash_allowance
        target = max(minimum_parameter_height, min(335, target))
        self.sidebar_pane.sashpos(0, target)

    def _build_right(self, parent: ttk.Frame) -> None:
        command_row = ttk.Frame(parent)
        command_row.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.summary_toggle_button = ttk.Button(
            command_row,
            text="收起可审计摘要",
            command=self._toggle_summary_panel,
        )
        self.summary_toggle_button.pack(side="left", padx=(2, 3))
        self.jobs_toggle_button = ttk.Button(
            command_row,
            text="收起任务队列",
            command=self._toggle_jobs_panel,
        )
        self.jobs_toggle_button.pack(side="left", padx=(0, 8))
        ttk.Button(
            command_row,
            text="刷新结果",
            command=lambda: self._load_selected_result(force=True),
        ).pack(side="left", padx=2)
        ttk.Button(command_row, text="导出当前图", command=self._export_figure).pack(
            side="left", padx=2
        )
        ttk.Button(command_row, text="导出结果数据", command=self._export_data).pack(
            side="left", padx=2
        )
        ttk.Button(command_row, text="复制整个结果目录", command=self._export_directory).pack(
            side="left", padx=2
        )

        self.audit_panel = ttk.Frame(parent)
        self.audit_panel.grid(row=1, column=0, sticky="ew")
        self._summary_panel_expanded = True
        self._jobs_panel_expanded = True
        summary_panel = ttk.LabelFrame(
            self.audit_panel,
            text="可审计摘要",
            style="Card.TLabelframe",
        )
        summary_panel.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.summary_panel = summary_panel
        cards = ttk.Frame(summary_panel)
        cards.pack(fill="x", padx=6, pady=6)
        self.card_vars = {
            "job": tk.StringVar(value="未选择任务"),
            "backend": tk.StringVar(value="—"),
            "status": tk.StringVar(value="就绪"),
            "output": tk.StringVar(value="—"),
        }
        for column, (title, key) in enumerate(
            (("任务", "job"), ("后端", "backend"), ("状态", "status"), ("结果目录", "output"))
        ):
            frame = ttk.LabelFrame(cards, text=title, style="Card.TLabelframe")
            frame.grid(row=0, column=column, sticky="nsew", padx=3)
            ttk.Label(frame, textvariable=self.card_vars[key], wraplength=245).pack(
                fill="both", expand=True, padx=7, pady=5
            )
            cards.columnconfigure(column, weight=1)

        jobs_frame = ttk.LabelFrame(
            self.audit_panel,
            text="任务队列",
            style="Card.TLabelframe",
        )
        jobs_frame.grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        self.jobs_panel = jobs_frame
        self.jobs_tree = ttk.Treeview(
            jobs_frame,
            columns=("label", "backend", "state", "time"),
            show="headings",
            height=4,
        )
        for key, title, width in (
            ("label", "标签", 220),
            ("backend", "后端", 120),
            ("state", "状态", 130),
            ("time", "提交时间", 210),
        ):
            self.jobs_tree.heading(key, text=title)
            self.jobs_tree.column(key, width=width)
        scroll = ttk.Scrollbar(jobs_frame, orient="vertical", command=self.jobs_tree.yview)
        self.jobs_tree.configure(yscrollcommand=scroll.set)
        self.jobs_tree.pack(side="left", fill="x", expand=True)
        scroll.pack(side="right", fill="y")
        self.jobs_tree.bind("<<TreeviewSelect>>", self._job_selected)

        self.result_notebook = ttk.Notebook(parent)
        self.result_notebook.grid(row=2, column=0, sticky="nsew", padx=4, pady=4)
        self.summary_text = self._text_tab("运行摘要")
        self._figure_tab("geometry", "三维 Y 形摆", geometry=True)
        self._figure_tab("trajectory", "俯视轨迹 / 李萨如")
        self._figure_tab("state", "位移与速度")
        self._figure_tab("force", "Signed 轴力 / 非负张力")
        self._figure_tab("energy", "能量与功率")
        self._figure_tab("guards", "全部守卫与事件")
        self._figure_tab("analysis", "频谱与相图")
        self._figure_tab("difference", "双后端差异")
        self.log_text = self._text_tab("实时日志")
        self.result_notebook.bind("<<NotebookTabChanged>>", self._result_tab_changed)
        self.result_notebook.select(1)
        self.audit_panel.columnconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

    def _toggle_summary_panel(self) -> None:
        self._set_summary_panel_expanded(not self._summary_panel_expanded)

    def _toggle_jobs_panel(self) -> None:
        self._set_jobs_panel_expanded(not self._jobs_panel_expanded)

    def _sync_audit_panel_visibility(self) -> None:
        if self._summary_panel_expanded or self._jobs_panel_expanded:
            self.audit_panel.grid()
        else:
            self.audit_panel.grid_remove()

    def _set_summary_panel_expanded(self, expanded: bool) -> None:
        self._summary_panel_expanded = bool(expanded)
        if self._summary_panel_expanded:
            self.summary_panel.grid()
            self.summary_toggle_button.configure(text="收起可审计摘要")
        else:
            self.summary_panel.grid_remove()
            self.summary_toggle_button.configure(text="展开可审计摘要")
        self._sync_audit_panel_visibility()

    def _set_jobs_panel_expanded(self, expanded: bool) -> None:
        self._jobs_panel_expanded = bool(expanded)
        if self._jobs_panel_expanded:
            self.jobs_panel.grid()
            self.jobs_toggle_button.configure(text="收起任务队列")
        else:
            self.jobs_panel.grid_remove()
            self.jobs_toggle_button.configure(text="展开任务队列")
        self._sync_audit_panel_visibility()

    def _text_tab(self, title: str) -> tk.Text:
        frame = ttk.Frame(self.result_notebook)
        self.result_notebook.add(frame, text=title)
        text = tk.Text(frame, wrap="word", background="white", foreground="#263238")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        text.insert("1.0", "尚无结果。")
        text.configure(state="disabled")
        return text

    def _figure_tab(self, key: str, title: str, *, geometry: bool = False) -> None:
        frame = ttk.Frame(self.result_notebook)
        self.result_notebook.add(frame, text=title)
        if geometry:
            controls = ttk.Frame(frame, padding=(6, 5))
            controls.pack(fill="x")
            self.geometry_play_button = ttk.Button(
                controls,
                text="▶ 播放",
                style="Primary.TButton",
                command=self._toggle_geometry_playback,
            )
            self.geometry_play_button.grid(row=0, column=0, padx=(0, 4), sticky="w")
            ttk.Button(
                controls,
                text="■ 停止",
                style="Secondary.TButton",
                command=self._stop_geometry_playback,
            ).grid(row=0, column=1, padx=2)
            ttk.Button(
                controls,
                text="◀",
                width=3,
                command=lambda: self._step_geometry(-1),
            ).grid(row=0, column=2, padx=2)
            ttk.Button(
                controls,
                text="▶",
                width=3,
                command=lambda: self._step_geometry(1),
            ).grid(row=0, column=3, padx=2)
            ttk.Label(controls, text="速度").grid(row=0, column=4, padx=(12, 3))
            self.geometry_speed_var = tk.StringVar(value="1×")
            speed = ttk.Combobox(
                controls,
                textvariable=self.geometry_speed_var,
                values=("0.25×", "0.5×", "1×", "2×", "4×"),
                state="readonly",
                width=6,
            )
            speed.grid(row=0, column=5, padx=2)
            speed.bind("<<ComboboxSelected>>", self._geometry_speed_changed)
            self.geometry_loop_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(controls, text="循环", variable=self.geometry_loop_var).grid(
                row=0, column=6, padx=(10, 4)
            )
            self.geometry_animation_status = ttk.Label(
                controls,
                text="载入结果后可播放 · 1× = 真实物理时间",
                style="Subheader.TLabel",
            )
            self.geometry_animation_status.grid(row=0, column=7, sticky="e", padx=(8, 0))
            controls.columnconfigure(7, weight=1)

            ttk.Label(controls, text="物理时间").grid(
                row=1, column=0, columnspan=2, sticky="w", pady=(7, 0)
            )
            self.geometry_fraction = tk.DoubleVar(value=0.0)
            self.geometry_scale = ttk.Scale(
                controls,
                from_=0.0,
                to=1000.0,
                variable=self.geometry_fraction,
                command=self._geometry_scale_changed,
            )
            self.geometry_scale.grid(
                row=1, column=2, columnspan=5, sticky="ew", padx=5, pady=(7, 0)
            )
            self.geometry_scale.bind("<ButtonPress-1>", self._geometry_scrub_started)
            self.geometry_time_label = ttk.Label(
                controls,
                text="t = —",
                style="IdentityValue.TLabel",
            )
            self.geometry_time_label.grid(row=1, column=7, sticky="e", padx=(8, 0), pady=(7, 0))
            self.geometry_material_path_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                controls,
                text="原始材料路径（审计）",
                variable=self.geometry_material_path_var,
                command=self._geometry_path_mode_changed,
            ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
            ttk.Label(
                controls,
                text="默认端点弦接近实验绷直绳形；审计模式显示后端原始离散节点，不做平滑。",
                style="Subheader.TLabel",
            ).grid(row=2, column=3, columnspan=5, sticky="e", padx=(8, 0), pady=(6, 0))
        figure = Figure(figsize=(9.2, 5.6), dpi=100)
        figure.patch.set_facecolor("#ffffff")
        figure.subplots_adjust(left=0.09, right=0.98, bottom=0.12, top=0.92, hspace=0.34)
        empty_axis = figure.add_subplot(111)
        empty_axis.axis("off")
        empty_axis.text(
            0.5,
            0.5,
            "运行或载入结果后将在此显示可审计计算结果",
            ha="center",
            va="center",
            color="#777777",
            transform=empty_axis.transAxes,
        )
        canvas = FigureCanvasTkAgg(figure, master=frame)
        toolbar = NavigationToolbar2Tk(canvas, frame, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(side="bottom", fill="x")
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self.figures[key] = figure
        self.canvases[key] = canvas
        if geometry:
            canvas.mpl_connect("button_release_event", self._capture_geometry_view)

    def _geometry_scale_changed(self, _value: str | float) -> None:
        if self._geometry_scale_internal:
            return
        self._render_geometry()

    def _geometry_scrub_started(self, _event: object | None = None) -> None:
        if self._geometry_playing:
            self._pause_geometry_playback("已暂停 · 拖动时间轴定位")

    def _geometry_speed_changed(self, _event: object | None = None) -> None:
        if self._geometry_playing:
            self._geometry_fraction_start = float(self.geometry_fraction.get()) / 1000.0
            self._geometry_clock_start = time.monotonic()
        self.geometry_animation_status.configure(
            text=(
                f"{self.geometry_speed_var.get()} 播放 · 1× = 真实物理时间 · "
                f"{self._geometry_path_mode_label()}"
            )
        )

    def _geometry_speed(self) -> float:
        return float(self.geometry_speed_var.get().rstrip("×"))

    def _uses_raw_material_paths(self) -> bool:
        variable = getattr(self, "geometry_material_path_var", None)
        return bool(variable.get()) if variable is not None else False

    def _geometry_path_mode_label(self) -> str:
        return (
            "原始材料路径审计视图"
            if self._uses_raw_material_paths()
            else "实验端点弦视图"
        )

    def _geometry_path_mode_changed(self) -> None:
        self._geometry_scene_limits = None
        self._geometry_axis = None
        self._geometry_top_axis = None
        self._geometry_artists = {}
        self._geometry_scene_signature = None
        self._render_geometry()
        prefix = "正在播放" if self._geometry_playing else "已切换"
        self.geometry_animation_status.configure(
            text=(
                f"{prefix} · {self._geometry_path_mode_label()} · "
                "1× = 真实物理时间"
            )
        )

    def _set_geometry_fraction(self, fraction: float) -> None:
        self._geometry_scale_internal = True
        try:
            self.geometry_fraction.set(1000.0 * min(1.0, max(0.0, float(fraction))))
        finally:
            self._geometry_scale_internal = False
        self._render_geometry()

    def _toggle_geometry_playback(self) -> None:
        if self._geometry_autoplay_pending:
            self._cancel_geometry_autoplay("已取消等待播放")
        elif self._geometry_playing:
            self._pause_geometry_playback("已暂停")
        else:
            self._play_geometry()

    def _queue_geometry_autoplay(self, record: Any) -> None:
        """Remember a play request until the selected job has readable output."""

        self._geometry_autoplay_pending = True
        self._geometry_autoplay_output_directory = (
            Path(record.output_directory).expanduser().resolve()
        )
        state = str(record.state)
        if state == "QUEUED":
            detail = "任务正在排队"
        elif state == "PAUSED":
            detail = "任务已暂停"
        elif state == "RUNNING":
            detail = "任务正在计算"
        else:
            detail = "正在读取结果"
        self.inline_error.configure(text="")
        self.geometry_play_button.configure(text="✕ 取消等待")
        self.geometry_animation_status.configure(
            text=f"{detail} · 完成并载入结果后自动播放；再次点击可取消"
        )

    def _cancel_geometry_autoplay(self, status: str) -> None:
        self._geometry_autoplay_pending = False
        self._geometry_autoplay_output_directory = None
        self.geometry_play_button.configure(text="▶ 播放")
        self.geometry_animation_status.configure(text=status)

    def _play_geometry(self) -> None:
        if self.current_bundle is None:
            identifier = self._selected_job_id()
            if identifier is None:
                self.inline_error.configure(text="请先运行任务或载入已有结果，再播放三维动画。")
                self.geometry_animation_status.configure(text="尚未运行或载入结果")
                return
            try:
                record = self.manager.get(identifier, refresh=False)
            except Exception as exc:
                self.inline_error.configure(text=f"无法读取选中任务状态：{exc}")
                return
            if record.state in WAITABLE_JOB_STATES:
                self._queue_geometry_autoplay(record)
                return
            if record.state in READABLE_RESULT_STATES:
                self._queue_geometry_autoplay(record)
                output_directory = Path(record.output_directory).expanduser().resolve()
                force_reload = (
                    self._loaded_result_directory == output_directory
                    and self._loading_result_directory != output_directory
                )
                self._queue_result_load(record, force=force_reload)
                return
            state_name = {
                "FAILED": "失败",
                "STOPPED": "停止",
            }.get(str(record.state), str(record.state))
            self.inline_error.configure(
                text=f"选中任务已{state_name}，没有产生可播放的三维轨迹。"
            )
            self.geometry_animation_status.configure(text=f"任务{state_name} · 无可播放结果")
            return
        backends = self._backends(self.current_bundle)
        if not backends:
            self.inline_error.configure(text="已载入结果不包含三维摆球轨迹，无法播放动画。")
            return
        start, stop = common_geometry_time_window(backends)
        if stop <= start:
            self.inline_error.configure(text="结果只有一个物理时刻，无法播放动画。")
            return
        self._geometry_autoplay_pending = False
        self._geometry_autoplay_output_directory = None
        self.inline_error.configure(text="")
        fraction = float(self.geometry_fraction.get()) / 1000.0
        if fraction >= 1.0 - 1.0e-9:
            fraction = 0.0
            self._set_geometry_fraction(0.0)
        self._geometry_fraction_start = fraction
        self._geometry_clock_start = time.monotonic()
        self._geometry_playing = True
        self.geometry_play_button.configure(text="❚❚ 暂停")
        self.geometry_animation_status.configure(
            text=(
                f"正在播放 · {self.geometry_speed_var.get()} · "
                f"{self._geometry_path_mode_label()} · 双后端按同一物理时刻插值"
            )
        )
        self._geometry_tick()

    def _pause_geometry_playback(self, status: str = "已暂停") -> None:
        self._geometry_playing = False
        if self._geometry_after_id is not None:
            try:
                self.root.after_cancel(self._geometry_after_id)
            except tk.TclError:
                pass
            self._geometry_after_id = None
        if hasattr(self, "geometry_play_button"):
            self.geometry_play_button.configure(text="▶ 播放")
        if hasattr(self, "geometry_animation_status"):
            self.geometry_animation_status.configure(text=status)

    def _stop_geometry_playback(self) -> None:
        if self._geometry_autoplay_pending:
            self._cancel_geometry_autoplay("已取消等待播放")
            return
        self._pause_geometry_playback("已停止 · 回到起始时刻")
        self._set_geometry_fraction(0.0)

    def _step_geometry(self, direction: int) -> None:
        bundle = self.current_bundle
        if bundle is None:
            self.inline_error.configure(text="尚无可逐帧查看的三维结果。")
            return
        self._pause_geometry_playback("逐帧查看")
        frame_count = max(data.geometry_time.size for data in self._backends(bundle))
        step = 1.0 / max(1, frame_count - 1)
        current = float(self.geometry_fraction.get()) / 1000.0
        self._set_geometry_fraction(current + (1 if direction >= 0 else -1) * step)

    def _geometry_tick(self) -> None:
        if not self._geometry_playing:
            return
        bundle = self.current_bundle
        if bundle is None:
            self._pause_geometry_playback("播放已停止 · 当前结果不可用")
            return
        start, stop = common_geometry_time_window(self._backends(bundle))
        physical_duration = stop - start
        if physical_duration <= 0.0:
            self._pause_geometry_playback("播放已停止 · 结果没有时间跨度")
            return
        elapsed = time.monotonic() - self._geometry_clock_start
        fraction = _physical_playback_fraction(
            self._geometry_fraction_start,
            elapsed,
            self._geometry_speed(),
            physical_duration,
        )
        if fraction >= 1.0:
            if self.geometry_loop_var.get():
                fraction %= 1.0
                self._geometry_fraction_start = fraction
                self._geometry_clock_start = time.monotonic()
            else:
                self._set_geometry_fraction(1.0)
                self._pause_geometry_playback("播放完成")
                return
        self._set_geometry_fraction(fraction)
        self._geometry_after_id = self.root.after(GEOMETRY_TICK_MS, self._geometry_tick)

    def _capture_geometry_view(self, _event: object | None = None) -> None:
        figure = self.figures.get("geometry")
        if figure is None or not figure.axes:
            return
        axis = figure.axes[0]
        self._geometry_view = (
            float(getattr(axis, "elev", self._geometry_view[0])),
            float(getattr(axis, "azim", self._geometry_view[1])),
            float(getattr(axis, "roll", self._geometry_view[2])),
        )

    def _result_tab_changed(self, _event: object | None = None) -> None:
        if (
            self._geometry_playing
            and self.result_notebook.index(self.result_notebook.select()) != 1
        ):
            self._pause_geometry_playback("已暂停 · 三维页已隐藏")

    def _selected_backend(self) -> str:
        return BACKEND_LABELS[self.backend_var.get()]

    def _selected_mode(self) -> str:
        return MODE_LABELS[self.mode_var.get()]

    def _backend_changed(self) -> None:
        backend = self._selected_backend()
        if backend == "forward":
            self.parameter_notebook.select(self.forward_form)
        elif backend == "high_fidelity":
            self.parameter_notebook.select(self.hf_form)
        self._refresh_sweep_paths()

    def _mode_changed(self) -> None:
        mode = self._selected_mode()
        if mode == "same_input_dual":
            self.backend_var.set(BACKEND_NAMES["both"])
        for widget in self.repeat_widgets:
            (widget.grid if mode == "repeat" else widget.grid_remove)()
        for widget in (self.batch_label, self.batch_buttons):
            (widget.grid if mode == "batch" else widget.grid_remove)()
        if mode == "sweep":
            self.sweep_frame.grid()
        else:
            self.sweep_frame.grid_remove()
        if hasattr(self, "workflow_canvas"):
            self.root.after_idle(lambda: self.workflow_canvas.yview_moveto(0.0))
        self._schedule_sidebar_fit()

    def _update_window_summary(self) -> None:
        """Show how much physics the currently committed window can reveal."""

        if not all(
            hasattr(self, name)
            for name in ("window_summary_var", "forward_form", "hf_form")
        ):
            return
        try:
            forward = apply_parameter_values(
                self.forward_form.base_config,
                self.forward_form.values,
            )
            hf = apply_parameter_values(self.hf_form.base_config, self.hf_form.values)
            if (
                hasattr(self, "initial_release_editor")
                and self.initial_release_editor.is_angle_mode()
            ):
                parameters = self.initial_release_editor.get_parameters()
                forward = apply_initial_release_to_forward(forward, parameters)
                hf = apply_initial_release_to_hf(hf, parameters)
            periods = estimate_reference_periods(forward)
            fwd_elements = forward["numerics"]["elements"]
            hf_cables = hf["cables"]
            fwd_mesh = "/".join(str(fwd_elements[name]) for name in ("A", "B", "lower"))
            hf_mesh = "/".join(
                str(hf_cables[name]["elements"])
                for name in ("upper_A", "upper_B", "lower")
            )
            fwd_horizon = float(forward["physical"]["T"])
            hf_horizon = float(hf["solver"]["t_end"])
            preview = bool(hf["solver"].get("allow_subminimum_mesh", False))
            qualifier = "HF 预览" if preview else "HF"
            self.window_summary_var.set(
                f"窗口：FWD {fwd_horizon:.3g} s ≈ {periods['fast_cycles']:.1f} 快 / "
                f"{periods['slow_cycles']:.1f} 慢周期；HF {hf_horizon:.3g} s。\n"
                f"网格：FWD {fwd_mesh}，{qualifier} {hf_mesh}；结论前须加密复核。"
            )
        except (KeyError, TypeError, ValueError) as exc:
            self.window_summary_var.set(f"当前时间窗无法估算：{exc}")

    def _load_defaults(self) -> None:
        if not messagebox.askyesno(
            "恢复默认值",
            "用 8 s 多周期交互研究预览覆盖当前界面参数？",
            parent=self.root,
        ):
            return
        forward, hf = default_desktop_configuration()
        self.initial_release_editor.set_angle_mode(True)
        self._set_initial_input_mode(True, update_summary=False)
        self.forward_form.set_config(forward)
        self.hf_form.set_config(hf)
        self.initial_release_editor.set_parameters(initial_release_from_forward(forward))
        self._update_initial_release_preview(forward, hf)
        self.parameter_notebook.select(self.initial_release_editor)
        self._update_window_summary()
        self.inline_error.configure(text="")
        self.top_status.configure(text="已恢复 8 s 多周期默认值")

    def _collect_configs(self) -> tuple[dict[str, Any], dict[str, Any]]:
        forward = self.forward_form.get_config()
        hf = self.hf_form.get_config()
        if not self.initial_release_editor.is_angle_mode():
            return forward, hf
        parameters = self.initial_release_editor.get_parameters()
        forward = apply_initial_release_to_forward(forward, parameters)
        hf = apply_initial_release_to_hf(hf, parameters)
        return forward, hf

    def _set_initial_input_mode(
        self, enabled: bool, *, update_summary: bool = True
    ) -> None:
        """Select the default angle basis or the lossless expert Cartesian fallback."""

        if not all(
            hasattr(self, name)
            for name in ("initial_release_editor", "forward_form", "hf_form")
        ):
            return
        enabled = bool(enabled)
        self.initial_release_editor.set_angle_mode(enabled)
        self.forward_form.set_derived_paths(
            FORWARD_DERIVED_INITIAL_PATHS if enabled else frozenset()
        )
        self.hf_form.set_derived_paths(
            HF_DERIVED_INITIAL_PATHS if enabled else frozenset()
        )
        suffix = "坐标只读" if enabled else "高级坐标可编辑"
        self.parameter_notebook.tab(self.forward_form, text=f"FWD 完整参数 · {suffix}")
        self.parameter_notebook.tab(self.hf_form, text=f"HF 完整参数 · {suffix}")
        if enabled:
            self.top_status.configure(text="长度/角度模式 · 坐标由界面生成")
        else:
            self.top_status.configure(text="高级笛卡尔模式 · 保留导入配置的原始初态")
        if update_summary:
            self._update_window_summary()

    def _update_initial_release_preview(
        self, forward: dict[str, Any], hf: dict[str, Any]
    ) -> None:
        f_initial = forward["initial_state"]
        h_initial = hf["initial_condition"]

        def vector(value: Any) -> str:
            values = np.asarray(value, dtype=float).reshape(3)
            return "(" + ", ".join(f"{item:.6g}" for item in values) + ")"

        source = (
            "已生成坐标（m，仅供审计）"
            if self.initial_release_editor.is_angle_mode()
            else "当前高级坐标（m，可在完整参数页编辑）"
        )
        lower_branch = forward["physical"]["branches"]["lower"]
        rest_length = float(lower_branch["L0"])
        lower_length = float(
            np.linalg.norm(
                np.asarray(f_initial["r_m"], dtype=float)
                - np.asarray(f_initial["r_J"], dtype=float)
            )
        )
        stretch = lower_length / rest_length
        domain = lower_branch["material_domain"]

        def bound(name: str) -> str:
            value = domain.get(name)
            return "—" if value is None else f"{float(value):.6g}"

        active_material_bounds = any(
            domain.get(name) is not None
            for name in (
                "lambda_lower",
                "lambda_upper",
                "rate_lower",
                "rate_upper",
            )
        )
        domain_text = (
            "未启用默认材料上/速率限制"
            if not active_material_bounds
            else (
                "显式材料边界："
                f"λ下/上={bound('lambda_lower')}/{bound('lambda_upper')}，"
                f"λ̇下/上={bound('rate_lower')}/{bound('rate_upper')}"
            )
        )
        self.initial_release_editor.set_preview(
            f"{source}：\n"
            f"FWD  J={vector(f_initial['r_J'])}，P={vector(f_initial['r_m'])}\n"
            f"HF    J={vector(h_initial['junction_position'])}，"
            f"P={vector(h_initial['bob_position'])}\n"
            f"下支：ℓ={lower_length:.6g} m，L₀={rest_length:.6g} m，"
            f"λ={stretch:.6g}；{domain_text}；"
            f"保留必要守卫 λ>{float(forward['physical']['lambda_min']):.6g}。"
        )

    def _apply_initial_release(self) -> None:
        try:
            parameters = self.initial_release_editor.get_parameters()
            forward = apply_initial_release_to_forward(
                self.forward_form.get_config(), parameters
            )
            hf = apply_initial_release_to_hf(self.hf_form.get_config(), parameters)
            self.initial_release_editor.set_angle_mode(True)
            self._set_initial_input_mode(True, update_summary=False)
            self.forward_form.set_config(forward)
            self.hf_form.set_config(hf)
            self._update_initial_release_preview(forward, hf)
            self._update_window_summary()
            self.inline_error.configure(text="")
            self.top_status.configure(text="初始长度/角度已应用到 FWD 与 HF")
        except Exception as exc:
            self.initial_release_editor.set_preview(f"初始状态无效：{exc}")
            self.inline_error.configure(text=str(exc))
            self.top_status.configure(text="初始长度/角度无效")

    def _sync_configs(self, *, quiet: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
        forward, hf = self._collect_configs()
        synchronize_shared_forward_to_hf(forward, hf)
        self.forward_form.set_config(forward)
        self.hf_form.set_config(hf)
        if not self.initial_release_editor.is_angle_mode():
            self.initial_release_editor.set_parameters(initial_release_from_forward(forward))
        self._update_initial_release_preview(forward, hf)
        self._update_window_summary()
        if not quiet:
            self.top_status.configure(text="共享输入已同步")
        return forward, hf

    def _current_request(self, backend: str | None = None) -> dict[str, Any]:
        selected = backend or self._selected_backend()
        if selected == "both":
            forward, hf = self._sync_configs(quiet=True)
        else:
            forward, hf = self._collect_configs()
        return make_desktop_request(
            label=self.label_var.get().strip() or "desktop_case",
            backend=selected,
            forward_config=forward,
            high_fidelity_config=hf,
        )

    def _validate_current(self) -> None:
        try:
            request = self._current_request()
            identity = validate_desktop_request(request)
            self.inline_error.configure(text="")
            self.top_status.configure(text=f"验证通过 · {identity['request_sha256'][:12]}")
            messagebox.showinfo(
                "验证通过",
                "所选后端的完整参数已通过原求解器配置验证。",
                parent=self.root,
            )
        except Exception as exc:
            self.inline_error.configure(text=str(exc))
            self.top_status.configure(text="参数验证失败")

    def _save_request_file(self, request: dict[str, Any], suffix: str = "") -> Path:
        digest = validate_desktop_request(request)["request_sha256"]
        path = self.request_root / f"{_utc_stamp()}_{digest[:12]}{suffix}.json"
        return write_desktop_request(path, request)

    def _save_request(self) -> None:
        try:
            request = self._current_request()
            path = filedialog.asksaveasfilename(
                parent=self.root,
                title="保存桌面运行快照",
                defaultextension=".json",
                filetypes=(("桌面运行快照", "*.json"),),
                initialfile=f"{request['label']}.desktop.json",
            )
            if path:
                write_desktop_request(path, request)
                self.top_status.configure(text=f"已保存 {Path(path).name}")
        except Exception as exc:
            self.inline_error.configure(text=str(exc))

    def _load_request(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="载入桌面运行快照",
            filetypes=(("桌面运行快照", "*.json"), ("所有文件", "*")),
        )
        if not path:
            return
        try:
            request = load_desktop_request(path)
            # A saved request may carry expert initial branch data that the compact
            # angle basis cannot represent.  Preserve the snapshot byte-for-byte
            # until the user explicitly reapplies the angle/length parameterization.
            self.initial_release_editor.set_angle_mode(False)
            self._set_initial_input_mode(False, update_summary=False)
            self.forward_form.set_config(request["forward_config"])
            self.hf_form.set_config(request["high_fidelity_config"])
            parameters = (
                initial_release_from_hf(request["high_fidelity_config"])
                if request["backend"] == "high_fidelity"
                else initial_release_from_forward(request["forward_config"])
            )
            self.initial_release_editor.set_parameters(parameters)
            self.backend_var.set(BACKEND_NAMES[request["backend"]])
            self.label_var.set(request["label"])
            self._update_window_summary()
            forward, hf = self._collect_configs()
            self._update_initial_release_preview(forward, hf)
            self.inline_error.configure(text="")
            self.top_status.configure(text=f"已载入 {Path(path).name}")
            self._backend_changed()
        except Exception as exc:
            self.inline_error.configure(text=str(exc))

    def _load_forward_config(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="导入 FWD 配置",
            filetypes=(("FWD JSON", "*.json"), ("所有文件", "*")),
        )
        if not path:
            return
        try:
            forward = load_forward_profile(path)
            self.initial_release_editor.set_angle_mode(False)
            self._set_initial_input_mode(False, update_summary=False)
            self.forward_form.set_config(forward)
            self.initial_release_editor.set_parameters(initial_release_from_forward(forward))
            self.parameter_notebook.select(self.forward_form)
            self._update_window_summary()
            self.top_status.configure(text=f"已导入 {Path(path).name}")
        except Exception as exc:
            self.inline_error.configure(text=str(exc))

    def _load_hf_config(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="导入 HF 配置",
            filetypes=(
                ("HF YAML/JSON", "*.yaml *.yml *.json"),
                ("所有文件", "*"),
            ),
        )
        if not path:
            return
        try:
            hf = load_hf_profile(path)
            self.initial_release_editor.set_angle_mode(False)
            self._set_initial_input_mode(False, update_summary=False)
            self.hf_form.set_config(hf)
            self.initial_release_editor.set_parameters(initial_release_from_hf(hf))
            self.parameter_notebook.select(self.hf_form)
            self._update_window_summary()
            self.top_status.configure(text=f"已导入 {Path(path).name}")
        except Exception as exc:
            self.inline_error.configure(text=str(exc))

    def _add_batch_case(self) -> None:
        try:
            request = self._current_request()
            self.batch_cases.append(deepcopy(request))
            self.batch_label.configure(text=f"批量案例：{len(self.batch_cases)}")
            self.top_status.configure(text="已加入当前案例")
        except Exception as exc:
            self.inline_error.configure(text=str(exc))

    def _clear_batch(self) -> None:
        self.batch_cases.clear()
        self.batch_label.configure(text="批量案例：0")

    def _refresh_sweep_paths(self) -> None:
        if not hasattr(self, "sweep_path"):
            return
        form = self.forward_form if self.sweep_backend_var.get() == "forward" else self.hf_form
        values = form.numeric_paths() + self.initial_release_editor.numeric_paths()
        self.sweep_path.configure(values=values)
        if self.sweep_path_var.get() not in values and values:
            preferred = "physical.T" if form is self.forward_form else "solver.t_end"
            self.sweep_path_var.set(preferred if preferred in values else values[0])

    def _build_plan(self) -> tuple[tuple[RunPlanItem, ...], str]:
        mode = self._selected_mode()
        backend = "both" if mode == "same_input_dual" else self._selected_backend()
        if mode in {"single", "repeat", "same_input_dual"}:
            request = self._current_request(backend)
            path = self._save_request_file(request)
            repetitions = self.repeat_var.get() if mode == "repeat" else 1
            return (
                expand_run_plan(
                    mode=mode,
                    base_config=path,
                    backend=backend,
                    repetitions=repetitions,
                ),
                request["label"],
            )
        if mode == "batch":
            if not self.batch_cases:
                raise ValueError("批量列表为空；请先点“加入当前”。")
            paths = [
                self._save_request_file(case, suffix=f"_batch_{index:03d}")
                for index, case in enumerate(self.batch_cases, start=1)
            ]
            return (
                expand_run_plan(
                    mode="batch",
                    base_config=paths[0],
                    backend=backend,
                    batch_configs=paths,
                ),
                self.label_var.get().strip() or "desktop_batch",
            )

        forward, hf = self._collect_configs()
        source_backend = self.sweep_backend_var.get()
        path_key = self.sweep_path_var.get()
        release_field = (
            path_key.removeprefix("initial_release.")
            if path_key.startswith("initial_release.")
            else None
        )
        if release_field is not None and release_field not in INITIAL_RELEASE_FIELD_NAMES:
            raise ValueError(f"未知长度/角度扫描参数：{path_key}")
        if (
            release_field is None
            and source_backend == "high_fidelity"
            and backend == "forward"
        ):
            raise ValueError("单 FWD 扫描不能修改 HF 专有参数。")
        values = numeric_sweep_values(
            float(self.sweep_start_var.get()),
            float(self.sweep_stop_var.get()),
            int(self.sweep_count_var.get()),
        )
        base_release = self.initial_release_editor.get_parameters()
        points: list[SweepPoint] = []
        for index, value in enumerate(values, start=1):
            point_forward = deepcopy(forward)
            point_hf = deepcopy(hf)
            if release_field is not None:
                target_value = float(value)
                point_release = replace(base_release, **{release_field: target_value})
                point_forward = apply_initial_release_to_forward(
                    point_forward, point_release
                )
                point_hf = apply_initial_release_to_hf(point_hf, point_release)
                if backend == "both":
                    synchronize_shared_forward_to_hf(point_forward, point_hf)
                coordinate_name = f"shared.{path_key}"
            else:
                target = point_forward if source_backend == "forward" else point_hf
                current = get_path(target, path_key)
                target_value = (
                    int(round(value)) if isinstance(current, int) else float(value)
                )
                target = apply_parameter_values(target, {path_key: target_value})
                if source_backend == "forward":
                    point_forward = target
                    if backend == "both":
                        synchronize_shared_forward_to_hf(point_forward, point_hf)
                else:
                    point_hf = target
                coordinate_name = f"{source_backend}.{path_key}"
            request = make_desktop_request(
                label=f"{self.label_var.get().strip() or 'sweep'}_{index:03d}",
                backend=backend,
                forward_config=point_forward,
                high_fidelity_config=point_hf,
                scan_coordinates={coordinate_name: target_value},
            )
            request_path = self._save_request_file(request, suffix=f"_sweep_{index:03d}")
            points.append(
                SweepPoint(
                    label=f"{path_key}={target_value:.8g}",
                    config_path=request_path,
                    coordinates={coordinate_name: target_value},
                )
            )
        return (
            expand_run_plan(
                mode="sweep",
                base_config=points[0].config_path,
                backend=backend,
                sweep_points=points,
            ),
            self.label_var.get().strip() or "desktop_sweep",
        )

    def _start(self) -> None:
        try:
            plan, batch_label = self._build_plan()
            workers = int(self.parallel_var.get())
            if not 1 <= workers <= 12:
                raise ValueError("CPU 并行任务数必须在 1–12 之间。")
            self.manager.max_parallel = workers
            identifiers = self.manager.submit_plan(
                DESKTOP_PLUGIN_ID,
                plan,
                output_parent=self.output_root,
                batch_label=batch_label,
            )
            self.current_job_id = identifiers[0]
            if self._geometry_autoplay_pending:
                self._cancel_geometry_autoplay("已提交新任务 · 等待播放已取消")
            self.inline_error.configure(text="")
            self.top_status.configure(text=f"已提交 {len(identifiers)} 个任务")
            self._refresh_jobs(self.manager.list_jobs(refresh=False))
            if self.jobs_tree.exists(self.current_job_id):
                self.jobs_tree.selection_set(self.current_job_id)
                self.jobs_tree.see(self.current_job_id)
        except Exception as exc:
            self.inline_error.configure(text=str(exc))
            self.top_status.configure(text="提交失败")

    def _selected_job_id(self) -> str | None:
        selected = self.jobs_tree.selection()
        return selected[0] if selected else self.current_job_id

    def _pause(self) -> None:
        self._control(self.manager.pause, "暂停")

    def _resume(self) -> None:
        self._control(self.manager.resume, "继续")

    def _stop(self) -> None:
        identifier = self._selected_job_id()
        if identifier is None:
            self.inline_error.configure(text="请先选择任务。")
            return
        if not messagebox.askyesno("停止任务", "停止选中任务及其求解器进程？", parent=self.root):
            return
        self._control(self.manager.stop, "停止")

    def _control(self, operation: Callable[[str], Any], label: str) -> None:
        identifier = self._selected_job_id()
        if identifier is None:
            self.inline_error.configure(text="请先选择任务。")
            return
        try:
            record = operation(identifier)
            self.top_status.configure(text=f"{label}：{record.label}")
            self._refresh_jobs(self.manager.list_jobs(refresh=False))
        except Exception as exc:
            self.inline_error.configure(text=str(exc))

    def _poll_jobs(self) -> None:
        self._drain_result_load_queue()
        try:
            records = self.manager.poll()
            self._refresh_jobs(records)
            self._sync_current_job_result(records)
            active = next((item for item in records if item.state in ACTIVE_STATES), None)
            if active is not None:
                self._show_progress(active)
            elif records:
                self.progress.stop()
                self.progress.configure(mode="determinate", value=100.0)
        except Exception as exc:
            self.inline_error.configure(text=f"任务轮询失败：{exc}")
        self.root.after(650, self._poll_jobs)

    def _drain_result_load_queue(self) -> None:
        """Apply background result-reader completions on Tk's main thread."""

        while True:
            try:
                generation, output_directory, bundle, error = (
                    self._result_load_queue.get_nowait()
                )
            except queue.Empty:
                return
            if generation != self._load_generation:
                continue
            self._loading_result_directory = None
            if error is not None or bundle is None:
                self._failed_result_directories.add(output_directory)
                self.inline_error.configure(text=f"结果读取失败：{error}")
                if output_directory == getattr(
                    self, "_geometry_autoplay_output_directory", None
                ):
                    self._cancel_geometry_autoplay("结果读取失败 · 无法自动播放")
                continue
            self._failed_result_directories.discard(output_directory)
            self._loaded_result_directory = output_directory
            self.current_bundle = bundle
            self._render_bundle(bundle)
            self.top_status.configure(text=f"已加载结果 · {bundle.status}")
            if (
                getattr(self, "_geometry_autoplay_pending", False)
                and output_directory
                == getattr(self, "_geometry_autoplay_output_directory", None)
            ):
                self._geometry_autoplay_pending = False
                self._geometry_autoplay_output_directory = None
                self._play_geometry()

    def _sync_current_job_result(self, records: list[Any]) -> None:
        """Load the just-submitted job once it reaches a readable terminal state."""

        if self.current_job_id is None:
            return
        record = next(
            (item for item in records if item.identifier == self.current_job_id),
            None,
        )
        if record is None:
            return
        output_directory = Path(record.output_directory).expanduser().resolve()
        if record.state in READABLE_RESULT_STATES:
            self._queue_result_load(record, force=False)
            return
        if (
            getattr(self, "_geometry_autoplay_pending", False)
            and output_directory
            == getattr(self, "_geometry_autoplay_output_directory", None)
            and record.state in {"FAILED", "STOPPED"}
        ):
            state_name = "失败" if record.state == "FAILED" else "停止"
            self._cancel_geometry_autoplay(f"任务已{state_name} · 自动播放已取消")
            self.inline_error.configure(
                text=f"任务已{state_name}，没有产生可播放的三维轨迹。"
            )

    def _refresh_jobs(self, records: list[Any]) -> None:
        selected = self._selected_job_id()
        existing = set(self.jobs_tree.get_children())
        incoming: set[str] = set()
        for record in reversed(records[-200:]):
            incoming.add(record.identifier)
            values = (
                record.label,
                BACKEND_NAMES.get(record.backend, record.backend),
                record.state,
                record.submitted_at_utc,
            )
            if self.jobs_tree.exists(record.identifier):
                self.jobs_tree.item(record.identifier, values=values)
            else:
                self.jobs_tree.insert("", "end", iid=record.identifier, values=values)
        for identifier in existing - incoming:
            self.jobs_tree.delete(identifier)
        desired_selection = selected or self.current_job_id
        if (
            desired_selection
            and self.jobs_tree.exists(desired_selection)
            and self.jobs_tree.selection() != (desired_selection,)
        ):
            # Re-selecting an already selected row emits <<TreeviewSelect>> on
            # Tk and used to reload/redraw the same completed result every
            # polling cycle.  Only restore selection when it actually changed.
            self.jobs_tree.selection_set(desired_selection)

    def _show_progress(self, record: Any) -> None:
        path = Path(record.output_directory) / ".desktop_progress.json"
        if path.is_file():
            try:
                payload = _read_json(path)
                self.progress.stop()
                self.progress.configure(
                    mode="determinate", value=100.0 * float(payload["fraction"])
                )
                self.top_status.configure(text=f"{record.state} · {payload.get('detail', '')}")
                return
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                pass
        if str(self.progress["mode"]) != "indeterminate":
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)

    def _job_selected(self, _event: object | None = None) -> None:
        identifier = self._selected_job_id()
        if identifier is None:
            return
        self.current_job_id = identifier
        try:
            record = self.manager.get(identifier, refresh=False)
            output_directory = Path(record.output_directory).expanduser().resolve()
            if output_directory != self._loaded_result_directory:
                self.card_vars["job"].set(record.label)
                self.card_vars["backend"].set(BACKEND_NAMES.get(record.backend, record.backend))
                self.card_vars["status"].set(record.state)
                self.card_vars["output"].set(record.output_directory)
            self._set_text(
                self.log_text,
                self.manager.tail_log(identifier, maximum_bytes=60_000) or "尚无日志。",
            )
            if record.state in READABLE_RESULT_STATES:
                self._load_selected_result(force=False)
        except Exception as exc:
            self.inline_error.configure(text=str(exc))

    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _load_selected_result(self, *, force: bool = True) -> None:
        identifier = self._selected_job_id()
        if identifier is None:
            self.inline_error.configure(text="请先选择已完成任务。")
            return
        try:
            record = self.manager.get(identifier, refresh=False)
            if record.state not in READABLE_RESULT_STATES:
                raise ValueError("选中任务尚未产生完整可读结果。")
        except Exception as exc:
            self.inline_error.configure(text=str(exc))
            return
        self._queue_result_load(record, force=force)

    def _queue_result_load(self, record: Any, *, force: bool) -> bool:
        output_directory = Path(record.output_directory).expanduser().resolve()
        if not force:
            if output_directory in {
                self._loaded_result_directory,
                self._loading_result_directory,
            }:
                return False
            if output_directory in getattr(self, "_failed_result_directories", set()):
                return False
        else:
            self._failed_result_directories.discard(output_directory)
        self._load_generation += 1
        generation = self._load_generation
        self._loading_result_directory = output_directory
        self.top_status.configure(text="正在读取结果…")

        def load() -> None:
            try:
                bundle = load_desktop_output(record.output_directory)
                error: Exception | None = None
            except Exception as exc:  # Viewer failure must not affect run artifacts.
                bundle = None
                error = exc
            self._result_load_queue.put((generation, output_directory, bundle, error))

        threading.Thread(target=load, daemon=True).start()
        return True

    def _render_bundle(self, bundle: DesktopPlotBundle) -> None:
        self._pause_geometry_playback("已载入结果 · 可播放三维动画")
        self._set_summary_panel_expanded(False)
        self._set_jobs_panel_expanded(False)
        self.geometry_fraction.set(0.0)
        self._geometry_scene_limits = geometry_scene_cube(
            self._backends(bundle),
            endpoint_chords=not self._uses_raw_material_paths(),
        )
        self._trajectory_scene_limits = trajectory_plane_square(self._backends(bundle))
        self._geometry_axis = None
        self._geometry_top_axis = None
        self._geometry_artists = {}
        self._geometry_scene_signature = None
        loaded_backend = str(bundle.desktop_result.get("backend", "—"))
        self.card_vars["job"].set(
            str(bundle.desktop_result.get("label", bundle.output_directory.name))
        )
        self.card_vars["backend"].set(BACKEND_NAMES.get(loaded_backend, loaded_backend))
        self.card_vars["status"].set(bundle.status)
        self.card_vars["output"].set(bundle.output_directory.name)
        lines = [
            "IYPT 2027 Y 形摆桌面运行摘要",
            "=" * 44,
            f"运行状态: {bundle.status}",
            f"结果目录: {bundle.output_directory}",
            "",
        ]
        for name in ("forward", "high_fidelity"):
            data = getattr(bundle, name)
            if data is None:
                continue
            lines.extend(
                [
                    f"[{BACKEND_NAMES[name]}]",
                    f"样本数: {data.time.size}",
                    f"返回时间窗: {data.time[0]:.9g} – {data.time[-1]:.9g} s",
                    f"守卫分量: {len(data.guards)}",
                    f"事件数: {len(data.events)}",
                    f"最大速度: {np.max(np.linalg.norm(data.bob_velocity, axis=1)):.9g} m/s",
                    "",
                ]
            )
        comparison = bundle.desktop_result.get("comparison")
        if isinstance(comparison, dict):
            lines.append("[同输入差异]")
            for key, value in comparison.items():
                if key not in {"schema_version", "interpretation"}:
                    lines.append(f"{key}: {value}")
            lines.append(str(comparison.get("interpretation", "")))
        lines.extend(
            [
                "",
                "注：HF 原始 UNDETERMINED/SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED 轨迹是",
                "可用于个人科研的数值结果，不等于已运行可选全窗独立资格证书。",
            ]
        )
        self._set_text(self.summary_text, "\n".join(lines))
        self._render_geometry()
        self._render_trajectory(bundle)
        self._render_state(bundle)
        self._render_force(bundle)
        self._render_energy(bundle)
        self._render_guards(bundle)
        self._render_analysis(bundle)
        self._render_difference(bundle)

    @staticmethod
    def _backends(bundle: DesktopPlotBundle) -> list[BackendPlotData]:
        return [item for item in (bundle.forward, bundle.high_fidelity) if item is not None]

    @staticmethod
    def _selected_geometry_paths(paths: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        return (
            {name: value for name, value in paths.items() if name != "all_nodes"}
            if len(paths) > 1
            else paths
        )

    def _display_geometry_paths(
        self,
        data: BackendPlotData,
        target_time: float,
    ) -> dict[str, np.ndarray]:
        paths = self._selected_geometry_paths(
            geometry_paths_at_time(data, target_time)
        )
        return paths if self._uses_raw_material_paths() else endpoint_chord_paths(paths)

    def _geometry_signature(self, backends: list[BackendPlotData]) -> tuple[Any, ...]:
        return tuple(
            (
                id(data),
                data.backend,
                tuple(self._selected_geometry_paths(data.geometry_paths)),
                data.bob_radius_m,
                self._uses_raw_material_paths(),
            )
            for data in backends
        )

    @staticmethod
    def _geometry_trace(data: BackendPlotData, target_time: float, bob: np.ndarray) -> np.ndarray:
        trace = data.bob_position[data.time <= target_time]
        if trace.size == 0 or not np.allclose(trace[-1], bob, rtol=0.0, atol=1.0e-14):
            trace = np.vstack((trace, bob)) if trace.size else bob[None, :]
        return trace

    def _build_geometry_scene(
        self,
        backends: list[BackendPlotData],
        target_time: float,
    ) -> None:
        """Build the 3-D axes and artists once for flicker-free in-place updates."""

        figure = self.figures["geometry"]
        figure.clear()
        figure.subplots_adjust(left=0.03, right=0.98, bottom=0.18, top=0.86, wspace=0.08)
        grid = figure.add_gridspec(1, 2, width_ratios=(1.0, 1.0), wspace=0.08)
        axis = figure.add_subplot(grid[0, 0], projection="3d")
        top_axis = figure.add_subplot(grid[0, 1])
        artists: dict[str, dict[str, Any]] = {}
        for data in backends:
            color = SCENE_COLORS[data.backend]
            paths = self._display_geometry_paths(data, target_time)
            backend_artists: dict[str, Any] = {"paths": {}}
            for path_index, path_name in enumerate(paths):
                (line,) = axis.plot(
                    [],
                    [],
                    [],
                    color=color,
                    linewidth=2.15,
                    alpha=0.92,
                    label=(
                        (
                            f"{PLOT_BACKEND_NAMES[data.backend]} 原始材料路径"
                            if self._uses_raw_material_paths()
                            else f"{PLOT_BACKEND_NAMES[data.backend]} 绳段（端点弦）"
                        )
                        if path_index == 0
                        else "_nolegend_"
                    ),
                )
                backend_artists["paths"][path_name] = line
            (backend_artists["trace"],) = axis.plot(
                [],
                [],
                [],
                color=color,
                linewidth=1.1,
                alpha=0.38,
                linestyle=":" if data.backend == "high_fidelity" else "--",
                label=f"{PLOT_BACKEND_NAMES[data.backend]} 摆球轨迹",
            )
            (backend_artists["top_full"],) = top_axis.plot(
                data.bob_position[:, 0],
                data.bob_position[:, 1],
                color=color,
                linewidth=0.9,
                alpha=0.20,
                linestyle=PLOT_STYLES[data.backend],
                label=f"{BACKEND_NAMES[data.backend]} · 全轨迹",
            )
            (backend_artists["top_trace"],) = top_axis.plot(
                [],
                [],
                color=color,
                linewidth=1.8,
                alpha=0.96,
                linestyle=PLOT_STYLES[data.backend],
                label=f"{BACKEND_NAMES[data.backend]} · 已经过",
            )
            (backend_artists["top_current"],) = top_axis.plot(
                [],
                [],
                marker="o",
                markersize=5.5,
                color=color,
                markeredgecolor="#ffffff",
                markeredgewidth=0.8,
                linestyle="none",
                label="_nolegend_",
            )
            top_axis.plot(
                [data.bob_position[0, 0]],
                [data.bob_position[0, 1]],
                marker="s",
                markersize=4.5,
                markerfacecolor="#ffffff",
                markeredgecolor=color,
                linestyle="none",
                label="_nolegend_",
            )
            support_points = [
                points[0]
                for name, points in paths.items()
                if name in {"A", "B", "upper_A", "upper_B"}
            ]
            if support_points:
                supports = np.asarray(support_points)
                backend_artists["supports"] = axis.scatter(
                    supports[:, 0],
                    supports[:, 1],
                    supports[:, 2],
                    color="#ffffff",
                    edgecolor=color,
                    marker="s",
                    s=34,
                    linewidth=1.4,
                    depthshade=False,
                )
            backend_artists["junction"] = axis.scatter(
                [],
                [],
                [],
                color="#ffffff",
                edgecolor=color,
                marker="o",
                s=38,
                linewidth=1.5,
                depthshade=False,
            )
            if data.bob_radius_m is None:
                backend_artists["bob"] = axis.scatter(
                    [],
                    [],
                    [],
                    color=color,
                    edgecolor="#ffffff",
                    marker="o",
                    s=72,
                    depthshade=False,
                )
            else:
                bob = interpolate_vector_series(data.time, data.bob_position, target_time)
                bob_surface = Poly3DCollection(
                    _sphere_faces(bob, data.bob_radius_m),
                    facecolors=color,
                    edgecolors="#ffffff",
                    linewidths=0.18,
                    alpha=0.34 if data.backend == "forward" else 0.48,
                )
                axis.add_collection3d(bob_surface)
                backend_artists["bob"] = bob_surface
            artists[data.backend] = backend_artists

        if self._geometry_scene_limits is None:
            self._geometry_scene_limits = geometry_scene_cube(
                backends,
                endpoint_chords=not self._uses_raw_material_paths(),
            )
        low, high = self._geometry_scene_limits
        axis.set_xlim(float(low[0]), float(high[0]))
        axis.set_ylim(float(low[1]), float(high[1]))
        # The model convention is +z in the gravity/downward direction.  Reverse
        # the displayed z limits so supports stay above the junction and bob.
        axis.set_zlim(float(high[2]), float(low[2]))
        axis.set_box_aspect((1, 1, 1))
        axis.set_xlabel("x (m)")
        axis.set_ylabel("y (m)")
        axis.set_zlabel("z 向下 (m)")
        axis.set_title(
            "三维 Y 形摆运动 · 支点 / 结点 / "
            + (
                "原始材料路径 / 摆球轨迹"
                if self._uses_raw_material_paths()
                else "实验端点弦 / 摆球轨迹"
            )
        )
        try:
            axis.view_init(
                elev=self._geometry_view[0],
                azim=self._geometry_view[1],
                roll=self._geometry_view[2],
            )
        except TypeError:
            axis.view_init(elev=self._geometry_view[0], azim=self._geometry_view[1])
        axis.grid(True, alpha=0.2)
        if self._trajectory_scene_limits is None:
            self._trajectory_scene_limits = trajectory_plane_square(backends)
        trajectory_low, trajectory_high = self._trajectory_scene_limits
        top_axis.set_xlim(float(trajectory_low[0]), float(trajectory_high[0]))
        top_axis.set_ylim(float(trajectory_low[1]), float(trajectory_high[1]))
        top_axis.set_aspect("equal", adjustable="box")
        top_axis.set_xlabel("x (m)")
        top_axis.set_ylabel("y (m)")
        top_axis.set_title("俯视 x–y 李萨如 · 淡线=全程，深线=已经过")
        top_axis.set_anchor("C")
        top_axis.grid(True, alpha=0.25)
        handles, labels = axis.get_legend_handles_labels()
        if handles:
            figure.legend(
                handles,
                labels,
                fontsize=7.5,
                loc="lower center",
                bbox_to_anchor=(0.5, 0.015),
                ncol=max(1, len(handles)),
                frameon=False,
            )
        self._geometry_axis = axis
        self._geometry_top_axis = top_axis
        self._geometry_artists = artists
        self._geometry_scene_signature = self._geometry_signature(backends)

    def _render_geometry(self) -> None:
        bundle = self.current_bundle
        if bundle is None or "geometry" not in self.figures:
            return
        backends = self._backends(bundle)
        if not backends:
            return
        fraction = float(self.geometry_fraction.get()) / 1000.0
        start, stop = common_geometry_time_window(backends)
        target_time = start + min(1.0, max(0.0, fraction)) * (stop - start)
        signature = self._geometry_signature(backends)
        if self._geometry_axis is None or self._geometry_scene_signature != signature:
            self._build_geometry_scene(backends, target_time)
        axis = self._geometry_axis
        assert axis is not None
        for data in backends:
            backend_artists = self._geometry_artists[data.backend]
            selected_paths = self._display_geometry_paths(data, target_time)
            for path_name, points in selected_paths.items():
                backend_artists["paths"][path_name].set_data_3d(
                    points[:, 0], points[:, 1], points[:, 2]
                )
            bob = interpolate_vector_series(data.time, data.bob_position, target_time)
            junction = interpolate_vector_series(data.time, data.junction_position, target_time)
            trace = self._geometry_trace(data, target_time, bob)
            backend_artists["trace"].set_data_3d(trace[:, 0], trace[:, 1], trace[:, 2])
            backend_artists["top_trace"].set_data(trace[:, 0], trace[:, 1])
            backend_artists["top_current"].set_data([bob[0]], [bob[1]])
            support_points = [
                points[0]
                for name, points in selected_paths.items()
                if name in {"A", "B", "upper_A", "upper_B"}
            ]
            if support_points:
                supports = np.asarray(support_points)
                backend_artists["supports"]._offsets3d = (
                    supports[:, 0],
                    supports[:, 1],
                    supports[:, 2],
                )
            backend_artists["junction"]._offsets3d = (
                np.asarray([junction[0]]),
                np.asarray([junction[1]]),
                np.asarray([junction[2]]),
            )
            if data.bob_radius_m is None:
                backend_artists["bob"]._offsets3d = (
                    np.asarray([bob[0]]),
                    np.asarray([bob[1]]),
                    np.asarray([bob[2]]),
                )
            else:
                backend_artists["bob"].set_verts(_sphere_faces(bob, data.bob_radius_m))
        self.geometry_time_label.configure(
            text=f"t = {target_time:.7g} / {stop:.7g} s · {100.0 * fraction:.1f}%"
        )
        # A synchronous draw prevents TkAgg from exposing the cleared/back-buffer
        # interval between queued idle redraws.  Artists and axes stay alive.
        self.canvases["geometry"].draw()

    def _render_trajectory(self, bundle: DesktopPlotBundle) -> None:
        """Render the complete equal-scale x-y trajectory as a Lissajous view."""

        figure = self.figures["trajectory"]
        figure.clear()
        figure.subplots_adjust(left=0.10, right=0.96, bottom=0.12, top=0.88)
        axis = figure.add_subplot(111)
        backends = self._backends(bundle)
        for data in backends:
            color = SCENE_COLORS[data.backend]
            name = PLOT_BACKEND_NAMES[data.backend]
            axis.plot(
                data.bob_position[:, 0],
                data.bob_position[:, 1],
                color=color,
                linestyle=PLOT_STYLES[data.backend],
                linewidth=1.35,
                label=f"{name} · 完整轨迹",
            )
            axis.scatter(
                data.bob_position[0, 0],
                data.bob_position[0, 1],
                s=34,
                marker="s",
                facecolor="#ffffff",
                edgecolor=color,
                linewidth=1.2,
                label=f"{name} · 起点",
                zorder=3,
            )
            axis.scatter(
                data.bob_position[-1, 0],
                data.bob_position[-1, 1],
                s=42,
                marker="X",
                facecolor=color,
                edgecolor="#ffffff",
                linewidth=0.7,
                label=f"{name} · 终点",
                zorder=3,
            )
        low, high = self._trajectory_scene_limits or trajectory_plane_square(backends)
        axis.set_xlim(float(low[0]), float(high[0]))
        axis.set_ylim(float(low[1]), float(high[1]))
        axis.set_aspect("equal", adjustable="box")
        axis.set_anchor("W")
        axis.set_xlabel("摆球 x 位移 (m)")
        axis.set_ylabel("摆球 y 位移 (m)")
        axis.set_title("俯视摆球完整轨迹 · x–y 李萨如图形")
        axis.grid(True, alpha=0.25)
        axis.legend(
            fontsize=8.5,
            loc="center left",
            bbox_to_anchor=(1.04, 0.5),
            frameon=False,
        )
        self.canvases["trajectory"].draw_idle()

    def _render_state(self, bundle: DesktopPlotBundle) -> None:
        figure = self.figures["state"]
        figure.clear()
        figure.subplots_adjust(left=0.09, right=0.98, bottom=0.10, top=0.82, hspace=0.30)
        position_axis, velocity_axis = figure.subplots(2, 1, sharex=True)
        backends = self._backends(bundle)
        for data in backends:
            for component, label in enumerate(("x", "y", "z")):
                position_axis.plot(
                    data.time,
                    data.bob_position[:, component],
                    color=PLOT_COLORS[component],
                    linestyle=PLOT_STYLES[data.backend],
                    label=f"{BACKEND_NAMES[data.backend]} {label}",
                    linewidth=1.1,
                )
            velocity_axis.plot(
                data.time,
                np.linalg.norm(data.bob_velocity, axis=1),
                color=PLOT_COLORS[0 if data.backend == "forward" else 1],
                linestyle=PLOT_STYLES[data.backend],
                label=f"{BACKEND_NAMES[data.backend]} |v|",
                linewidth=1.4,
            )
        position_axis.set_ylabel("摆球位置 (m)")
        velocity_axis.set_ylabel("速度 (m/s)")
        velocity_axis.set_xlabel("t (s)")
        component_handles = [
            Line2D([], [], color=PLOT_COLORS[index], linewidth=1.5, label=label)
            for index, label in enumerate(("x", "y", "z"))
        ]
        figure.legend(
            handles=component_handles + _backend_legend_handles(backends),
            loc="upper center",
            bbox_to_anchor=(0.5, 0.995),
            ncol=5,
            fontsize=8,
            frameon=False,
            title="颜色=坐标分量；线型=数值后端",
            title_fontsize=8,
        )
        position_axis.grid(alpha=0.25)
        velocity_axis.grid(alpha=0.25)
        self.canvases["state"].draw_idle()

    def _render_force(self, bundle: DesktopPlotBundle) -> None:
        figure = self.figures["force"]
        figure.clear()
        figure.subplots_adjust(left=0.09, right=0.98, bottom=0.10, top=0.82, hspace=0.30)
        signed_axis, tension_axis = figure.subplots(2, 1, sharex=False)
        backends = self._backends(bundle)
        for data in backends:
            for branch_index, (branch, values) in enumerate(data.signed_axial_force.items()):
                signed_axis.plot(
                    data.time,
                    values[:, 1],
                    color=PLOT_COLORS[
                        BRANCH_COLOR_INDEX.get(branch, branch_index % len(PLOT_COLORS))
                    ],
                    linestyle=PLOT_STYLES[data.backend],
                    label=f"{BACKEND_NAMES[data.backend]} {branch}",
                    linewidth=1.1,
                )
            for branch_index, (branch, values) in enumerate(data.tension.items()):
                tension_axis.plot(
                    data.time,
                    values[:, 1],
                    color=PLOT_COLORS[
                        BRANCH_COLOR_INDEX.get(branch, branch_index % len(PLOT_COLORS))
                    ],
                    linestyle=PLOT_STYLES[data.backend],
                    label=f"{BACKEND_NAMES[data.backend]} {branch}",
                    linewidth=1.1,
                )
        signed_axis.axhline(0.0, color="black", linewidth=0.7)
        tension_axis.axhline(0.0, color="black", linewidth=0.7)
        signed_axis.set_ylabel("signed axial force (N)")
        tension_axis.set_ylabel("tension (N)")
        signed_axis.set_xlabel("t (s)")
        tension_axis.set_xlabel("t (s)")
        branch_handles = [
            Line2D([], [], color=PLOT_COLORS[index], linewidth=1.5, label=label)
            for index, label in enumerate(("上支 A", "上支 B", "下支"))
        ]
        figure.legend(
            handles=branch_handles + _backend_legend_handles(backends),
            loc="upper center",
            bbox_to_anchor=(0.5, 0.995),
            ncol=max(1, len(branch_handles) + len(backends)),
            fontsize=8,
            frameon=False,
            title="颜色=支路；线型=数值后端",
            title_fontsize=8,
        )
        signed_axis.grid(alpha=0.25)
        tension_axis.grid(alpha=0.25)
        self.canvases["force"].draw_idle()

    def _render_energy(self, bundle: DesktopPlotBundle) -> None:
        figure = self.figures["energy"]
        figure.clear()
        figure.subplots_adjust(left=0.09, right=0.58, bottom=0.10, top=0.95, hspace=0.30)
        energy_axis, power_axis = figure.subplots(2, 1, sharex=False)
        for data in self._backends(bundle):
            for index, (name, values) in enumerate(data.energy.items()):
                if np.asarray(values).ndim == 1:
                    energy_axis.plot(
                        data.time,
                        values,
                        color=PLOT_COLORS[index % len(PLOT_COLORS)],
                        linestyle=PLOT_STYLES[data.backend],
                        label=f"{PLOT_BACKEND_NAMES[data.backend]} {name}",
                        linewidth=1.0,
                    )
            for index, (name, values) in enumerate(data.power.items()):
                if np.asarray(values).ndim == 1:
                    power_axis.plot(
                        data.time,
                        values,
                        color=PLOT_COLORS[index % len(PLOT_COLORS)],
                        linestyle=PLOT_STYLES[data.backend],
                        label=f"{PLOT_BACKEND_NAMES[data.backend]} {name}",
                        linewidth=1.0,
                    )
        energy_axis.set_ylabel("能量 (J)")
        power_axis.set_ylabel("功率 / 余量 (W)")
        power_axis.set_xlabel("t (s)")
        energy_axis.legend(
            fontsize=6.0,
            ncol=2,
            loc="center left",
            bbox_to_anchor=(1.02, 0.5),
            frameon=False,
            title="能量分量",
            title_fontsize=7,
            labelspacing=0.35,
            handlelength=1.4,
            handletextpad=0.35,
            columnspacing=0.7,
        )
        power_axis.legend(
            fontsize=6.0,
            ncol=2,
            loc="center left",
            bbox_to_anchor=(1.02, 0.5),
            frameon=False,
            title="功率 / 审计分量",
            title_fontsize=7,
            labelspacing=0.35,
            handlelength=1.4,
            handletextpad=0.35,
            columnspacing=0.7,
        )
        energy_axis.grid(alpha=0.25)
        power_axis.grid(alpha=0.25)
        self.canvases["energy"].draw_idle()

    def _render_guards(self, bundle: DesktopPlotBundle) -> None:
        figure = self.figures["guards"]
        figure.clear()
        figure.subplots_adjust(left=0.09, right=0.54, bottom=0.11, top=0.90)
        axis = figure.add_subplot(111)
        for data in self._backends(bundle):
            for index, (name, values) in enumerate(data.guards.items()):
                if np.asarray(values).ndim == 1:
                    axis.plot(
                        data.time,
                        values,
                        color=PLOT_COLORS[index % len(PLOT_COLORS)],
                        linestyle=PLOT_STYLES[data.backend],
                        label=_compact_guard_label(data.backend, name),
                        linewidth=0.9,
                    )
            for event in data.events:
                time_value = event.get("time", event.get("time_s"))
                if isinstance(time_value, (int, float)):
                    axis.axvline(float(time_value), color="#b3261e", alpha=0.35, linewidth=0.8)
        axis.axhline(0.0, color="black", linewidth=0.8)
        axis.set_xlabel("t (s)")
        axis.set_ylabel("原始守卫裕量（各自单位）")
        axis.set_title("全部返回守卫 · 右侧为紧凑索引；完整字段名保留在原始结果包")
        if axis.lines:
            axis.legend(
                fontsize=5.4,
                ncol=2,
                loc="upper left",
                bbox_to_anchor=(1.01, 1.0),
                frameon=False,
                handlelength=1.5,
                handletextpad=0.35,
                columnspacing=0.8,
                labelspacing=0.25,
                borderaxespad=0.0,
                title="守卫索引（实线 FWD / 虚线 HF）",
                title_fontsize=6.5,
            )
        axis.grid(alpha=0.25)
        self.canvases["guards"].draw_idle()

    def _render_analysis(self, bundle: DesktopPlotBundle) -> None:
        figure = self.figures["analysis"]
        figure.clear()
        figure.subplots_adjust(left=0.08, right=0.98, bottom=0.11, top=0.82, wspace=0.28)
        spectrum_axis, phase_axis = figure.subplots(1, 2)
        backends = self._backends(bundle)
        for data in backends:
            time = data.time
            signal = data.bob_position[:, 0] - np.mean(data.bob_position[:, 0])
            if time.size >= 8 and float(time[-1] - time[0]) > 0.0:
                uniform_time = np.linspace(time[0], time[-1], min(4096, time.size))
                uniform_signal = np.interp(uniform_time, time, signal)
                dt = float(uniform_time[1] - uniform_time[0])
                frequency = np.fft.rfftfreq(uniform_time.size, dt)
                amplitude = np.abs(np.fft.rfft(uniform_signal)) / uniform_time.size
                spectrum_axis.plot(
                    frequency[1:],
                    amplitude[1:],
                    color=PLOT_COLORS[0 if data.backend == "forward" else 1],
                    linestyle=PLOT_STYLES[data.backend],
                    label=BACKEND_NAMES[data.backend],
                    linewidth=1.2,
                )
            phase_axis.plot(
                data.bob_position[:, 0],
                data.bob_velocity[:, 0],
                color=PLOT_COLORS[0 if data.backend == "forward" else 1],
                linestyle=PLOT_STYLES[data.backend],
                label=BACKEND_NAMES[data.backend],
                linewidth=1.0,
            )
        spectrum_axis.set_xlabel("频率 (Hz)")
        spectrum_axis.set_ylabel("x 幅值 (m)")
        spectrum_axis.set_title("摆球 x 频谱")
        phase_axis.set_xlabel("x (m)")
        phase_axis.set_ylabel("v_x (m/s)")
        phase_axis.set_title("摆球 x–v_x 相图")
        figure.legend(
            handles=_backend_legend_handles(backends),
            loc="upper center",
            bbox_to_anchor=(0.5, 0.995),
            ncol=max(1, len(backends)),
            fontsize=8.5,
            frameon=False,
            title="线型=数值后端",
            title_fontsize=8,
        )
        spectrum_axis.grid(alpha=0.25)
        phase_axis.grid(alpha=0.25)
        self.canvases["analysis"].draw_idle()

    def _render_difference(self, bundle: DesktopPlotBundle) -> None:
        figure = self.figures["difference"]
        figure.clear()
        position_axis, velocity_axis = figure.subplots(2, 1, sharex=True)
        if bundle.comparison:
            time = bundle.comparison["time"]
            position_axis.plot(
                time,
                bundle.comparison["position_difference_norm"],
                color=PLOT_COLORS[0],
            )
            velocity_axis.plot(
                time,
                bundle.comparison["velocity_difference_norm"],
                color=PLOT_COLORS[1],
            )
        else:
            position_axis.text(0.5, 0.5, "需要同输入双后端结果", ha="center", va="center")
        position_axis.set_ylabel("|r_HF-r_FWD| (m)")
        velocity_axis.set_ylabel("|v_HF-v_FWD| (m/s)")
        velocity_axis.set_xlabel("t (s)")
        position_axis.grid(alpha=0.25)
        velocity_axis.grid(alpha=0.25)
        self.canvases["difference"].draw_idle()

    def _selected_figure_key(self) -> str | None:
        index = self.result_notebook.index(self.result_notebook.select())
        # Tabs: summary, geometry, trajectory, state, force, energy, guards,
        # analysis, difference, log.
        return {
            1: "geometry",
            2: "trajectory",
            3: "state",
            4: "force",
            5: "energy",
            6: "guards",
            7: "analysis",
            8: "difference",
        }.get(index)

    def _export_figure(self) -> None:
        key = self._selected_figure_key()
        if key is None:
            self.inline_error.configure(text="请先选择一个图形结果页。")
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出当前图",
            defaultextension=".png",
            filetypes=(("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")),
            initialfile=f"y_pendulum_{key}.png",
        )
        if path:
            self.figures[key].savefig(path, dpi=180)
            self.top_status.configure(text=f"已导出 {Path(path).name}")

    def _export_data(self) -> None:
        bundle = self.current_bundle
        if bundle is None:
            self.inline_error.configure(text="尚无已加载结果。")
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出结果概要表",
            defaultextension=".csv",
            filetypes=(("CSV", "*.csv"),),
            initialfile="y_pendulum_dashboard_export.csv",
        )
        if not path:
            return
        rows: list[dict[str, Any]] = []
        for data in self._backends(bundle):
            for index, time_value in enumerate(data.time):
                rows.append(
                    {
                        "backend": data.backend,
                        "time_s": float(time_value),
                        "bob_x_m": float(data.bob_position[index, 0]),
                        "bob_y_m": float(data.bob_position[index, 1]),
                        "bob_z_m": float(data.bob_position[index, 2]),
                        "bob_vx_m_s": float(data.bob_velocity[index, 0]),
                        "bob_vy_m_s": float(data.bob_velocity[index, 1]),
                        "bob_vz_m_s": float(data.bob_velocity[index, 2]),
                    }
                )
        with Path(path).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["backend"])
            writer.writeheader()
            writer.writerows(rows)
        self.top_status.configure(text=f"已导出 {Path(path).name}")

    def _export_directory(self) -> None:
        bundle = self.current_bundle
        if bundle is None:
            self.inline_error.configure(text="尚无已加载结果。")
            return
        parent = filedialog.askdirectory(parent=self.root, title="选择结果导出位置")
        if not parent:
            return
        target = Path(parent) / bundle.output_directory.name
        if target.exists():
            self.inline_error.configure(text=f"目标已存在：{target}")
            return
        shutil.copytree(bundle.output_directory, target)
        self.top_status.configure(text=f"已复制结果到 {target}")

    def coverage_summary(self) -> dict[str, Any]:
        forward_config, hf_config = self._collect_configs()
        return {
            "forward_visible_fields": len(self.forward_form.fields),
            "forward_leaf_fields": len(parameter_fields(forward_config, "forward")),
            "high_fidelity_visible_fields": len(self.hf_form.fields),
            "high_fidelity_leaf_fields": len(parameter_fields(hf_config, "high_fidelity")),
            "backend_modes": sorted(BACKEND_LABELS.values()),
            "workflow_modes": sorted(MODE_LABELS.values()),
            "native_windowing": "tkinter",
            "network_service": False,
            "initial_state_editor": {
                "input_basis": "support_axis_gravity_local_frame",
                "user_inputs": list(INITIAL_RELEASE_FIELD_NAMES),
                "lower_branch_length_semantics": (
                    "effective_y_branch_to_bob_reference"
                ),
                "default_material_limits": (
                    "disabled_unless_explicitly_imported"
                ),
                "mandatory_geometry_guards": [
                    "positive_branch_lengths",
                    "nondegenerate_upper_triangle",
                    "positive_lambda_min",
                ],
                "cartesian_backend_fields": (
                    "derived_read_only_audit"
                    if self.initial_release_editor.is_angle_mode()
                    else "expert_editable_fallback"
                ),
                "default_mode": "length_angle",
                "legacy_snapshot_preservation": "expert_cartesian_fallback",
                "round_trip_snapshots": True,
            },
            "geometry_animation": {
                "controls": ["play_pause", "stop", "step", "scrub", "speed", "loop"],
                "timeline": "shared_physical_time",
                "path_sampling": "linear_interpolation",
                "fixed_scene_bounds": True,
                "coordinate_convention": "+z_down_displayed_downward",
                "top_view_trace": "animated_xy_history_plus_full_path_context",
            },
            "lissajous_view": {
                "plane": "bob_xy_top_view",
                "scope": "complete_returned_time_window",
                "equal_axis_scale": True,
                "start_end_markers": True,
            },
        }

    def _on_close(self) -> None:
        active = [
            item for item in self.manager.list_jobs(refresh=False) if item.state in ACTIVE_STATES
        ]
        if active and not messagebox.askyesno(
            "关闭界面",
            "存在运行中任务。关闭界面不会中止计算，下次启动可恢复任务视图。继续关闭？",
            parent=self.root,
        ):
            return
        self._pause_geometry_playback("界面正在关闭")
        self.root.destroy()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Native offline Y-pendulum desktop GUI")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Construct, validate coverage, and close the native window.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    root = tk.Tk()
    application = YPendulumDesktopApp(root)
    if arguments.smoke_test:
        root.withdraw()
        root.update_idletasks()
        summary = application.coverage_summary()
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        root.destroy()
        return 0
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

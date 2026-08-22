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
import shutil
import threading
import tkinter as tk
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

import numpy as np
from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from ypendulum.ui.desktop_config import (
    DESKTOP_PLUGIN_ID,
    PROJECT_ROOT,
    DesktopYPendulumAdapter,
    ParameterField,
    apply_parameter_values,
    default_desktop_configuration,
    format_parameter_value,
    get_path,
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
from ypendulum.ui.desktop_results import BackendPlotData, DesktopPlotBundle, load_desktop_output
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


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("文件根节点必须是对象。")
    return value


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


class ParameterTreeEditor(ttk.Frame):
    """Hierarchical all-leaf parameter table with one typed editor."""

    def __init__(self, parent: tk.Misc, config: dict[str, Any], backend: str) -> None:
        super().__init__(parent)
        self.backend = backend
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
            tags: tuple[str, ...] = ()
            if field.path in self.errors:
                tags = ("error",)
            elif not field.editable:
                tags = ("locked",)
            self.tree.insert(
                parent,
                "end",
                iid=f"field::{field.path}",
                text=field.label,
                values=(value, field.unit),
                tags=tags,
            )

    def _on_select(self, _event: object | None = None) -> None:
        selected = self.tree.selection()
        if not selected or not selected[0].startswith("field::"):
            return
        path = selected[0][len("field::") :]
        self.selected_path = path
        field = self.fields[path]
        value = self.values[path]
        self.editor_title.configure(text=f"{field.label}  [{field.unit}]")
        self.path_label.configure(text=path)
        self.description.configure(text=field.description)
        self.range_label.configure(text="合法范围：" + field.legal_range)
        self.error_label.configure(text=self.errors.get(path, ""))
        for widget in (self.entry, self.choice, self.bool_widget, self.guard_button):
            widget.grid_remove()
        if field.kind == "bool":
            self.bool_var.set(bool(value))
            self.bool_widget.configure(state="normal" if field.editable else "disabled")
            self.bool_widget.grid(row=2, column=0, sticky="w", padx=6, pady=5)
        elif field.kind == "guards":
            self.guard_button.configure(state="normal" if field.editable else "disabled")
            self.guard_button.grid(row=2, column=0, sticky="w", padx=6, pady=5)
        elif field.choices:
            self.text_var.set(format_parameter_value(value))
            self.choice.configure(values=field.choices)
            self.choice.configure(state="readonly" if field.editable else "disabled")
            self.choice.grid(row=2, column=0, sticky="ew", padx=6, pady=5)
        else:
            self.text_var.set(format_parameter_value(value))
            self.entry.configure(state="normal" if field.editable else "disabled")
            self.entry.grid(row=2, column=0, sticky="ew", padx=6, pady=5)
        self.apply_button.configure(state="normal" if field.editable else "disabled")

    def _commit_bool(self) -> None:
        if self.selected_path is not None:
            self.values[self.selected_path] = bool(self.bool_var.get())
            self.errors.pop(self.selected_path, None)
            self._refresh_selected_row()

    def _edit_guards(self) -> None:
        if self.selected_path is None:
            return

        def replace(value: list[dict[str, Any]]) -> None:
            assert self.selected_path is not None
            self.values[self.selected_path] = value
            self.errors.pop(self.selected_path, None)
            self._refresh_selected_row()

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
                tags=("error",) if self.selected_path in self.errors else (),
            )
        self.error_label.configure(text=self.errors.get(self.selected_path, ""))

    def commit_selected(self, quiet: bool = False) -> bool:
        path = self.selected_path
        if path is None:
            return True
        field = self.fields[path]
        if not field.editable or field.kind in {"guards", "bool"}:
            return True
        try:
            self.values[path] = parse_parameter_text(field, self.text_var.get())
            self.errors.pop(path, None)
            self._refresh_selected_row()
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
            if field.editable and field.kind in {"int", "float"}
        )

    def set_path_value(self, path: str, value: Any) -> None:
        if path not in self.fields:
            raise KeyError(path)
        self.values[path] = deepcopy(value)
        self.errors.pop(path, None)
        self._rebuild_tree()


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
        self.figures: dict[str, Figure] = {}
        self.canvases: dict[str, FigureCanvasTkAgg] = {}

        forward, hf = default_desktop_configuration()
        self.forward_config = forward
        self.hf_config = hf
        self._build_ui()
        self._refresh_sweep_paths()
        self._poll_jobs()

    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#f6f8fa")
        style.configure("TLabel", background="#f6f8fa", foreground="#253238")
        style.configure("TLabelframe", background="#f6f8fa")
        style.configure("TLabelframe.Label", background="#f6f8fa", foreground="#264653")
        style.configure("Header.TLabel", font=("TkDefaultFont", 18, "bold"), foreground="#17324d")
        style.configure("Subheader.TLabel", foreground="#52616b")
        style.configure("Status.TLabel", font=("TkDefaultFont", 10, "bold"), foreground="#0b6e4f")
        style.configure("Accent.TButton", font=("TkDefaultFont", 10, "bold"))
        self.root.configure(background="#f6f8fa")

    def _build_ui(self) -> None:
        header = ttk.Frame(self.root, padding=(14, 9))
        header.pack(fill="x")
        ttk.Label(header, text="IYPT 2027 · Y 形摆本地研究平台", style="Header.TLabel").pack(
            side="left"
        )
        ttk.Label(
            header,
            text="原生桌面 · 离线 · FWD / HF / 同输入比较",
            style="Subheader.TLabel",
        ).pack(side="left", padx=16)
        self.top_status = ttk.Label(header, text="就绪", style="Status.TLabel")
        self.top_status.pack(side="right")

        main = ttk.Panedwindow(self.root, orient="horizontal")
        main.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        left = ttk.Frame(main, width=500)
        right = ttk.Frame(main)
        main.add(left, weight=0)
        main.add(right, weight=1)
        self._build_left(left)
        self._build_right(right)

    def _build_left(self, parent: ttk.Frame) -> None:
        selector = ttk.LabelFrame(parent, text="题目、模型与参数")
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
        ttk.Button(selector, text="恢复可运行默认值", command=self._load_defaults).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=3
        )
        ttk.Button(selector, text="FWD → HF 同步共享输入", command=self._sync_configs).grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=3
        )
        button_row = ttk.Frame(selector)
        button_row.grid(row=3, column=0, columnspan=2, sticky="ew", padx=2, pady=3)
        ttk.Button(button_row, text="载入运行快照", command=self._load_request).pack(
            side="left", fill="x", expand=True, padx=2
        )
        ttk.Button(button_row, text="保存运行快照", command=self._save_request).pack(
            side="left", fill="x", expand=True, padx=2
        )
        profile_row = ttk.Frame(selector)
        profile_row.grid(row=4, column=0, columnspan=2, sticky="ew", padx=2, pady=3)
        ttk.Button(profile_row, text="导入 FWD JSON", command=self._load_forward_config).pack(
            side="left", fill="x", expand=True, padx=2
        )
        ttk.Button(profile_row, text="导入 HF YAML/JSON", command=self._load_hf_config).pack(
            side="left", fill="x", expand=True, padx=2
        )
        selector.columnconfigure(1, weight=1)

        self.parameter_notebook = ttk.Notebook(parent)
        self.parameter_notebook.pack(fill="both", expand=True, padx=4, pady=4)
        self.forward_form = ParameterTreeEditor(
            self.parameter_notebook, self.forward_config, "forward"
        )
        self.hf_form = ParameterTreeEditor(
            self.parameter_notebook, self.hf_config, "high_fidelity"
        )
        self.parameter_notebook.add(self.forward_form, text="FWD 完整参数")
        self.parameter_notebook.add(self.hf_form, text="HF 完整参数")
        self.parameter_notebook.bind(
            "<<NotebookTabChanged>>", lambda _event: self._refresh_sweep_paths()
        )

        workflow = ttk.LabelFrame(parent, text="运行计划与长任务控制")
        workflow.pack(fill="x", padx=4, pady=4)
        self.label_var = tk.StringVar(value="desktop_case")
        self.mode_var = tk.StringVar(value=MODE_NAMES["single"])
        self.repeat_var = tk.IntVar(value=2)
        self.parallel_var = tk.IntVar(value=1)
        labels = (("标签", self.label_var), ("重复次数", self.repeat_var), ("CPU 并行任务", self.parallel_var))
        ttk.Label(workflow, text="方式").grid(row=0, column=0, sticky="w", padx=5, pady=3)
        mode = ttk.Combobox(
            workflow,
            textvariable=self.mode_var,
            values=tuple(MODE_LABELS),
            state="readonly",
        )
        mode.grid(row=0, column=1, sticky="ew", padx=5, pady=3)
        mode.bind("<<ComboboxSelected>>", lambda _event: self._mode_changed())
        for row, (name, variable) in enumerate(labels, start=1):
            ttk.Label(workflow, text=name).grid(row=row, column=0, sticky="w", padx=5, pady=3)
            if isinstance(variable, tk.IntVar):
                widget: tk.Widget = ttk.Spinbox(
                    workflow,
                    from_=1,
                    to=12 if variable is self.parallel_var else 999,
                    textvariable=variable,
                    width=8,
                )
            else:
                widget = ttk.Entry(workflow, textvariable=variable)
            widget.grid(row=row, column=1, sticky="ew", padx=5, pady=3)
        self.batch_label = ttk.Label(workflow, text="批量案例：0")
        self.batch_label.grid(row=4, column=0, sticky="w", padx=5, pady=3)
        batch_buttons = ttk.Frame(workflow)
        batch_buttons.grid(row=4, column=1, sticky="ew")
        ttk.Button(batch_buttons, text="加入当前", command=self._add_batch_case).pack(
            side="left", fill="x", expand=True, padx=2
        )
        ttk.Button(batch_buttons, text="清空", command=self._clear_batch).pack(side="left", padx=2)

        self.sweep_frame = ttk.Frame(workflow)
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
            (("起点", self.sweep_start_var), ("终点", self.sweep_stop_var), ("点数", self.sweep_count_var))
        ):
            ttk.Label(self.sweep_frame, text=label).grid(row=2, column=2 * column, sticky="w")
            ttk.Entry(self.sweep_frame, textvariable=variable, width=9).grid(
                row=2, column=2 * column + 1, sticky="ew", padx=2
            )
        self.sweep_frame.columnconfigure(1, weight=1)
        self.sweep_frame.columnconfigure(3, weight=1)
        self.sweep_frame.columnconfigure(5, weight=1)

        self.inline_error = ttk.Label(workflow, text="", foreground="#b3261e", wraplength=455)
        self.inline_error.grid(row=6, column=0, columnspan=2, sticky="ew", padx=5, pady=3)
        action = ttk.Frame(workflow)
        action.grid(row=7, column=0, columnspan=2, sticky="ew", padx=3, pady=4)
        ttk.Button(action, text="验证", command=self._validate_current).pack(side="left", padx=2)
        ttk.Button(action, text="开始", style="Accent.TButton", command=self._start).pack(
            side="left", padx=2
        )
        ttk.Button(action, text="暂停", command=self._pause).pack(side="left", padx=2)
        ttk.Button(action, text="继续", command=self._resume).pack(side="left", padx=2)
        ttk.Button(action, text="停止", command=self._stop).pack(side="left", padx=2)
        self.progress = ttk.Progressbar(workflow, mode="determinate", maximum=100.0)
        self.progress.grid(row=8, column=0, columnspan=2, sticky="ew", padx=5, pady=(2, 5))
        workflow.columnconfigure(1, weight=1)
        self._mode_changed()

    def _build_right(self, parent: ttk.Frame) -> None:
        cards = ttk.Frame(parent)
        cards.pack(fill="x", padx=4, pady=4)
        self.card_vars = {
            "job": tk.StringVar(value="未选择任务"),
            "backend": tk.StringVar(value="—"),
            "status": tk.StringVar(value="就绪"),
            "output": tk.StringVar(value="—"),
        }
        for column, (title, key) in enumerate(
            (("任务", "job"), ("后端", "backend"), ("状态", "status"), ("结果目录", "output"))
        ):
            frame = ttk.LabelFrame(cards, text=title)
            frame.grid(row=0, column=column, sticky="nsew", padx=3)
            ttk.Label(frame, textvariable=self.card_vars[key], wraplength=245).pack(
                fill="both", expand=True, padx=7, pady=5
            )
            cards.columnconfigure(column, weight=1)

        jobs_frame = ttk.LabelFrame(parent, text="任务队列")
        jobs_frame.pack(fill="x", padx=4, pady=4)
        self.jobs_tree = ttk.Treeview(
            jobs_frame,
            columns=("label", "backend", "state", "time"),
            show="headings",
            height=5,
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

        command_row = ttk.Frame(parent)
        command_row.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(command_row, text="刷新结果", command=self._load_selected_result).pack(
            side="left", padx=2
        )
        ttk.Button(command_row, text="导出当前图", command=self._export_figure).pack(
            side="left", padx=2
        )
        ttk.Button(command_row, text="导出结果数据", command=self._export_data).pack(
            side="left", padx=2
        )
        ttk.Button(command_row, text="复制整个结果目录", command=self._export_directory).pack(
            side="left", padx=2
        )

        self.result_notebook = ttk.Notebook(parent)
        self.result_notebook.pack(fill="both", expand=True, padx=4, pady=4)
        self.summary_text = self._text_tab("运行摘要")
        self._figure_tab("geometry", "三维 Y 形摆", geometry=True)
        self._figure_tab("state", "位移与速度")
        self._figure_tab("force", "Signed 轴力 / 非负张力")
        self._figure_tab("energy", "能量与功率")
        self._figure_tab("guards", "全部守卫与事件")
        self._figure_tab("analysis", "频谱与相图")
        self._figure_tab("difference", "双后端差异")
        self.log_text = self._text_tab("实时日志")

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
            scale_frame = ttk.Frame(frame)
            scale_frame.pack(fill="x")
            ttk.Label(scale_frame, text="几何帧").pack(side="left", padx=4)
            self.geometry_fraction = tk.DoubleVar(value=1000.0)
            self.geometry_scale = ttk.Scale(
                scale_frame,
                from_=0.0,
                to=1000.0,
                variable=self.geometry_fraction,
                command=lambda _value: self._render_geometry(),
            )
            self.geometry_scale.pack(side="left", fill="x", expand=True, padx=4)
            self.geometry_time_label = ttk.Label(scale_frame, text="t = —")
            self.geometry_time_label.pack(side="right", padx=6)
        figure = Figure(figsize=(9.2, 5.6), dpi=100)
        figure.subplots_adjust(left=0.09, right=0.98, bottom=0.12, top=0.92, hspace=0.34)
        canvas = FigureCanvasTkAgg(figure, master=frame)
        toolbar = NavigationToolbar2Tk(canvas, frame, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(side="bottom", fill="x")
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self.figures[key] = figure
        self.canvases[key] = canvas

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
        state = "normal" if mode == "sweep" else "disabled"
        for child in self.sweep_frame.winfo_children():
            try:
                child.configure(state=state)
            except tk.TclError:
                pass

    def _load_defaults(self) -> None:
        if not messagebox.askyesno(
            "恢复默认值", "用可直接运行的 0.2 ms 示例覆盖当前界面参数？", parent=self.root
        ):
            return
        forward, hf = default_desktop_configuration()
        self.forward_form.set_config(forward)
        self.hf_form.set_config(hf)
        self.inline_error.configure(text="")
        self.top_status.configure(text="已恢复默认值")

    def _collect_configs(self) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.forward_form.get_config(), self.hf_form.get_config()

    def _sync_configs(self, *, quiet: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
        forward, hf = self._collect_configs()
        synchronize_shared_forward_to_hf(forward, hf)
        self.forward_form.set_config(forward)
        self.hf_form.set_config(hf)
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
            self.forward_form.set_config(request["forward_config"])
            self.hf_form.set_config(request["high_fidelity_config"])
            self.backend_var.set(BACKEND_NAMES[request["backend"]])
            self.label_var.set(request["label"])
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
            self.forward_form.set_config(load_forward_profile(path))
            self.parameter_notebook.select(self.forward_form)
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
            self.hf_form.set_config(load_hf_profile(path))
            self.parameter_notebook.select(self.hf_form)
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
        values = form.numeric_paths()
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
        if source_backend == "high_fidelity" and backend == "forward":
            raise ValueError("单 FWD 扫描不能修改 HF 专有参数。")
        values = numeric_sweep_values(
            float(self.sweep_start_var.get()),
            float(self.sweep_stop_var.get()),
            int(self.sweep_count_var.get()),
        )
        points: list[SweepPoint] = []
        for index, value in enumerate(values, start=1):
            point_forward = deepcopy(forward)
            point_hf = deepcopy(hf)
            target = point_forward if source_backend == "forward" else point_hf
            current = get_path(target, path_key)
            target_value: Any = int(round(value)) if isinstance(current, int) else float(value)
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
            self.inline_error.configure(text="")
            self.top_status.configure(text=f"已提交 {len(identifiers)} 个任务")
            self._refresh_jobs(self.manager.list_jobs(refresh=False))
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
        try:
            records = self.manager.poll()
            self._refresh_jobs(records)
            active = next((item for item in records if item.state in ACTIVE_STATES), None)
            if active is not None:
                self._show_progress(active)
            elif records:
                self.progress.stop()
                self.progress.configure(mode="determinate", value=100.0)
        except Exception as exc:
            self.inline_error.configure(text=f"任务轮询失败：{exc}")
        self.root.after(650, self._poll_jobs)

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
        if selected and self.jobs_tree.exists(selected):
            self.jobs_tree.selection_set(selected)
        if self.current_job_id and self.jobs_tree.exists(self.current_job_id) and not selected:
            self.jobs_tree.selection_set(self.current_job_id)

    def _show_progress(self, record: Any) -> None:
        path = Path(record.output_directory) / ".desktop_progress.json"
        if path.is_file():
            try:
                payload = _read_json(path)
                self.progress.stop()
                self.progress.configure(mode="determinate", value=100.0 * float(payload["fraction"]))
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
            self.card_vars["job"].set(record.label)
            self.card_vars["backend"].set(BACKEND_NAMES.get(record.backend, record.backend))
            self.card_vars["status"].set(record.state)
            self.card_vars["output"].set(record.output_directory)
            self._set_text(self.log_text, self.manager.tail_log(identifier, maximum_bytes=60_000) or "尚无日志。")
            if record.state in {"COMPLETED", "OUT_OF_SCOPE_PREFIX"}:
                self._load_selected_result()
        except Exception as exc:
            self.inline_error.configure(text=str(exc))

    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _load_selected_result(self) -> None:
        identifier = self._selected_job_id()
        if identifier is None:
            self.inline_error.configure(text="请先选择已完成任务。")
            return
        try:
            record = self.manager.get(identifier, refresh=False)
            if record.state not in {"COMPLETED", "OUT_OF_SCOPE_PREFIX"}:
                raise ValueError("选中任务尚未产生完整可读结果。")
        except Exception as exc:
            self.inline_error.configure(text=str(exc))
            return
        self._load_generation += 1
        generation = self._load_generation
        self.top_status.configure(text="正在读取结果…")

        def load() -> None:
            try:
                bundle = load_desktop_output(record.output_directory)
                error: Exception | None = None
            except Exception as exc:  # Viewer failure must not affect run artifacts.
                bundle = None
                error = exc

            def finish() -> None:
                if generation != self._load_generation:
                    return
                if error is not None or bundle is None:
                    self.inline_error.configure(text=f"结果读取失败：{error}")
                    return
                self.current_bundle = bundle
                self._render_bundle(bundle)
                self.top_status.configure(text=f"已加载结果 · {bundle.status}")

            self.root.after(0, finish)

        threading.Thread(target=load, daemon=True).start()

    def _render_bundle(self, bundle: DesktopPlotBundle) -> None:
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
        self._render_state(bundle)
        self._render_force(bundle)
        self._render_energy(bundle)
        self._render_guards(bundle)
        self._render_analysis(bundle)
        self._render_difference(bundle)

    @staticmethod
    def _backends(bundle: DesktopPlotBundle) -> list[BackendPlotData]:
        return [item for item in (bundle.forward, bundle.high_fidelity) if item is not None]

    def _render_geometry(self) -> None:
        bundle = self.current_bundle
        if bundle is None or "geometry" not in self.figures:
            return
        figure = self.figures["geometry"]
        figure.clear()
        axis = figure.add_subplot(111, projection="3d")
        fraction = float(self.geometry_fraction.get()) / 1000.0
        colors = {"forward": "#2878b5", "high_fidelity": "#d95319"}
        all_points: list[np.ndarray] = []
        times: list[float] = []
        for data in self._backends(bundle):
            frame_count = next(iter(data.geometry_paths.values())).shape[0]
            index = min(frame_count - 1, max(0, int(round(fraction * (frame_count - 1)))))
            time_value = float(data.geometry_time[index])
            times.append(time_value)
            paths = data.geometry_paths
            selected_paths = (
                {name: value for name, value in paths.items() if name != "all_nodes"}
                if len(paths) > 1
                else paths
            )
            for path_name, values in selected_paths.items():
                points = values[index]
                all_points.append(points)
                axis.plot(
                    points[:, 0],
                    points[:, 1],
                    points[:, 2],
                    color=colors[data.backend],
                    linewidth=1.8,
                    alpha=0.78,
                    label=f"{BACKEND_NAMES[data.backend]} {path_name}",
                )
            bob = np.array(
                [np.interp(time_value, data.time, data.bob_position[:, i]) for i in range(3)]
            )
            junction = np.array(
                [np.interp(time_value, data.time, data.junction_position[:, i]) for i in range(3)]
            )
            all_points.extend((bob[None, :], junction[None, :]))
            axis.scatter(*junction, color=colors[data.backend], marker="o", s=28)
            if data.bob_radius_m is None:
                axis.scatter(*bob, color=colors[data.backend], marker="o", s=55)
            else:
                u = np.linspace(0.0, 2.0 * np.pi, 18)
                v = np.linspace(0.0, np.pi, 10)
                radius = data.bob_radius_m
                x = bob[0] + radius * np.outer(np.cos(u), np.sin(v))
                y = bob[1] + radius * np.outer(np.sin(u), np.sin(v))
                z = bob[2] + radius * np.outer(np.ones_like(u), np.cos(v))
                axis.plot_wireframe(x, y, z, color=colors[data.backend], alpha=0.28, linewidth=0.5)
        if all_points:
            cloud = np.concatenate(all_points, axis=0)
            low = np.min(cloud, axis=0)
            high = np.max(cloud, axis=0)
            centre = 0.5 * (low + high)
            radius = max(float(np.max(high - low)) * 0.58, 0.05)
            axis.set_xlim(centre[0] - radius, centre[0] + radius)
            axis.set_ylim(centre[1] - radius, centre[1] + radius)
            axis.set_zlim(centre[2] - radius, centre[2] + radius)
            axis.set_box_aspect((1, 1, 1))
        axis.set_xlabel("x (m)")
        axis.set_ylabel("y (m)")
        axis.set_zlabel("z (m)")
        axis.set_title("Y 形摆材料路径与有限摆球")
        if axis.lines:
            axis.legend(fontsize=7, loc="upper left")
        self.geometry_time_label.configure(
            text=" / ".join(f"t={value:.6g}s" for value in times) if times else "t=—"
        )
        self.canvases["geometry"].draw_idle()

    def _render_state(self, bundle: DesktopPlotBundle) -> None:
        figure = self.figures["state"]
        figure.clear()
        position_axis, velocity_axis = figure.subplots(2, 1, sharex=True)
        styles = {"forward": "-", "high_fidelity": "--"}
        for data in self._backends(bundle):
            for component, label in enumerate(("x", "y", "z")):
                position_axis.plot(
                    data.time,
                    data.bob_position[:, component],
                    styles[data.backend],
                    label=f"{BACKEND_NAMES[data.backend]} {label}",
                    linewidth=1.1,
                )
            velocity_axis.plot(
                data.time,
                np.linalg.norm(data.bob_velocity, axis=1),
                styles[data.backend],
                label=f"{BACKEND_NAMES[data.backend]} |v|",
                linewidth=1.4,
            )
        position_axis.set_ylabel("摆球位置 (m)")
        velocity_axis.set_ylabel("速度 (m/s)")
        velocity_axis.set_xlabel("t (s)")
        position_axis.legend(fontsize=7, ncol=3)
        velocity_axis.legend(fontsize=8)
        position_axis.grid(alpha=0.25)
        velocity_axis.grid(alpha=0.25)
        self.canvases["state"].draw_idle()

    def _render_force(self, bundle: DesktopPlotBundle) -> None:
        figure = self.figures["force"]
        figure.clear()
        signed_axis, tension_axis = figure.subplots(2, 1, sharex=False)
        for data in self._backends(bundle):
            for branch, values in data.signed_axial_force.items():
                signed_axis.plot(
                    data.time,
                    values[:, 1],
                    label=f"{BACKEND_NAMES[data.backend]} {branch}",
                    linewidth=1.1,
                )
            for branch, values in data.tension.items():
                tension_axis.plot(
                    data.time,
                    values[:, 1],
                    label=f"{BACKEND_NAMES[data.backend]} {branch}",
                    linewidth=1.1,
                )
        signed_axis.axhline(0.0, color="black", linewidth=0.7)
        tension_axis.axhline(0.0, color="black", linewidth=0.7)
        signed_axis.set_ylabel("signed axial force (N)")
        tension_axis.set_ylabel("tension (N)")
        signed_axis.set_xlabel("t (s)")
        tension_axis.set_xlabel("t (s)")
        signed_axis.legend(fontsize=7, ncol=3)
        tension_axis.legend(fontsize=7, ncol=3)
        signed_axis.grid(alpha=0.25)
        tension_axis.grid(alpha=0.25)
        self.canvases["force"].draw_idle()

    def _render_energy(self, bundle: DesktopPlotBundle) -> None:
        figure = self.figures["energy"]
        figure.clear()
        energy_axis, power_axis = figure.subplots(2, 1, sharex=False)
        for data in self._backends(bundle):
            for name, values in data.energy.items():
                if np.asarray(values).ndim == 1:
                    energy_axis.plot(
                        data.time,
                        values,
                        label=f"{BACKEND_NAMES[data.backend]} {name}",
                        linewidth=1.0,
                    )
            for name, values in data.power.items():
                if np.asarray(values).ndim == 1:
                    power_axis.plot(
                        data.time,
                        values,
                        label=f"{BACKEND_NAMES[data.backend]} {name}",
                        linewidth=1.0,
                    )
        energy_axis.set_ylabel("能量 (J)")
        power_axis.set_ylabel("功率 / 余量 (W)")
        power_axis.set_xlabel("t (s)")
        energy_axis.legend(fontsize=6, ncol=3)
        power_axis.legend(fontsize=6, ncol=3)
        energy_axis.grid(alpha=0.25)
        power_axis.grid(alpha=0.25)
        self.canvases["energy"].draw_idle()

    def _render_guards(self, bundle: DesktopPlotBundle) -> None:
        figure = self.figures["guards"]
        figure.clear()
        axis = figure.add_subplot(111)
        for data in self._backends(bundle):
            for name, values in data.guards.items():
                if np.asarray(values).ndim == 1:
                    axis.plot(
                        data.time,
                        values,
                        label=f"{BACKEND_NAMES[data.backend]} {name}",
                        linewidth=0.9,
                    )
            for event in data.events:
                time_value = event.get("time", event.get("time_s"))
                if isinstance(time_value, (int, float)):
                    axis.axvline(float(time_value), color="#b3261e", alpha=0.35, linewidth=0.8)
        axis.axhline(0.0, color="black", linewidth=0.8)
        axis.set_xlabel("t (s)")
        axis.set_ylabel("原始守卫裕量（各自单位）")
        axis.set_title("全部返回守卫；红线为事件时刻")
        if axis.lines:
            axis.legend(fontsize=5.5, ncol=3, loc="best")
        axis.grid(alpha=0.25)
        self.canvases["guards"].draw_idle()

    def _render_analysis(self, bundle: DesktopPlotBundle) -> None:
        figure = self.figures["analysis"]
        figure.clear()
        spectrum_axis, phase_axis = figure.subplots(1, 2)
        for data in self._backends(bundle):
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
                    label=BACKEND_NAMES[data.backend],
                    linewidth=1.2,
                )
            phase_axis.plot(
                data.bob_position[:, 0],
                data.bob_velocity[:, 0],
                label=BACKEND_NAMES[data.backend],
                linewidth=1.0,
            )
        spectrum_axis.set_xlabel("频率 (Hz)")
        spectrum_axis.set_ylabel("x 幅值 (m)")
        spectrum_axis.set_title("摆球 x 频谱")
        phase_axis.set_xlabel("x (m)")
        phase_axis.set_ylabel("v_x (m/s)")
        phase_axis.set_title("摆球 x–v_x 相图")
        spectrum_axis.legend(fontsize=8)
        phase_axis.legend(fontsize=8)
        spectrum_axis.grid(alpha=0.25)
        phase_axis.grid(alpha=0.25)
        self.canvases["analysis"].draw_idle()

    def _render_difference(self, bundle: DesktopPlotBundle) -> None:
        figure = self.figures["difference"]
        figure.clear()
        position_axis, velocity_axis = figure.subplots(2, 1, sharex=True)
        if bundle.comparison:
            time = bundle.comparison["time"]
            position_axis.plot(time, bundle.comparison["position_difference_norm"], color="#7b2cbf")
            velocity_axis.plot(time, bundle.comparison["velocity_difference_norm"], color="#d95319")
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
        # Tabs: summary, geometry, state, force, energy, guards, analysis, difference, log.
        return {
            1: "geometry",
            2: "state",
            3: "force",
            4: "energy",
            5: "guards",
            6: "analysis",
            7: "difference",
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
        forward_config = self.forward_form.get_config()
        hf_config = self.hf_form.get_config()
        return {
            "forward_visible_fields": len(self.forward_form.fields),
            "forward_leaf_fields": len(parameter_fields(forward_config, "forward")),
            "high_fidelity_visible_fields": len(self.hf_form.fields),
            "high_fidelity_leaf_fields": len(parameter_fields(hf_config, "high_fidelity")),
            "backend_modes": sorted(BACKEND_LABELS.values()),
            "workflow_modes": sorted(MODE_LABELS.values()),
            "native_windowing": "tkinter",
            "network_service": False,
        }

    def _on_close(self) -> None:
        active = [item for item in self.manager.list_jobs(refresh=False) if item.state in ACTIVE_STATES]
        if active and not messagebox.askyesno(
            "关闭界面",
            "存在运行中任务。关闭界面不会中止计算，下次启动可恢复任务视图。继续关闭？",
            parent=self.root,
        ):
            return
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

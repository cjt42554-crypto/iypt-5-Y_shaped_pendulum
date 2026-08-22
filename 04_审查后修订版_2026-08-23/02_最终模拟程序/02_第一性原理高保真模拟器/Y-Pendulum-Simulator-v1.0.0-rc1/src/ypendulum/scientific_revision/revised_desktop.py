"""Scientific-guarded launcher for the copied dual-backend desktop GUI."""

from __future__ import annotations

import argparse
import hashlib
import json
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

import numpy as np

from ypendulum.ui import desktop_app as base

from .desktop_contract import OVERLAY_PATH_KEY, OVERLAY_SHA256_KEY
from .overlay import load_overlay
from .revised_desktop_adapter import RevisedDesktopYPendulumAdapter
from .scientific_guard import frequency_preview, preview_spectrum


base.DesktopYPendulumAdapter = RevisedDesktopYPendulumAdapter
base.BACKEND_LABELS = {
    "前向仅受拉柔索 (FWD-CABLE)": "forward",
    "显式 EI 双边柔性杆 (HF-ROD)": "high_fidelity",
    "同输入双后端（模型形式差异）": "both",
}
base.BACKEND_NAMES = {value: key for key, value in base.BACKEND_LABELS.items()}
base.PLOT_BACKEND_NAMES = {"forward": "FWD-CABLE", "high_fidelity": "HF-ROD"}

DEFAULT_OVERLAY = (
    base.PROJECT_ROOT
    / "configs"
    / "revision"
    / "hf-bilateral-explicit-ei-baseline.yaml"
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ScientificRevisionDesktopApp(base.YPendulumDesktopApp):
    """Retain the original workflow while executing the explicit-EI HF model."""

    def __init__(self, root: tk.Tk) -> None:
        self._selected_overlay_path = DEFAULT_OVERLAY.resolve()
        super().__init__(root)
        self.root.title("IYPT 2027 第 5 题 · Y 形摆审查后修订研究平台")
        self._replace_legacy_header_text(self.root)
        self._refresh_overlay_description()

    @staticmethod
    def _replace_legacy_header_text(widget: tk.Misc) -> None:
        replacements = {
            (
                "前向预测数值后端与第一性原理高保真后端共用输入合同；"
                "理论、求解与证据状态分别呈现。"
            ): (
                "前向仅受拉柔索与显式 EI 双边柔性杆共用宏观输入；"
                "模型形式、完整初态与证据等级分别呈现。"
            ),
        }
        try:
            text = widget.cget("text")
        except (tk.TclError, AttributeError):
            text = None
        if text in replacements:
            widget.configure(text=replacements[text])
        for child in widget.winfo_children():
            ScientificRevisionDesktopApp._replace_legacy_header_text(child)

    def _build_left(self, parent: ttk.Frame) -> None:
        revision = ttk.LabelFrame(
            parent,
            text="科学修订模型身份 / 独立 EI",
            style="Card.TLabelframe",
        )
        revision.pack(fill="x", padx=4, pady=4)
        self.overlay_path_var = tk.StringVar(value=str(self._selected_overlay_path))
        ttk.Entry(revision, textvariable=self.overlay_path_var).grid(
            row=0, column=0, sticky="ew", padx=5, pady=5
        )
        ttk.Button(revision, text="选择 overlay…", command=self._browse_overlay).grid(
            row=0, column=1, sticky="e", padx=5, pady=5
        )
        self.overlay_description_var = tk.StringVar(value="正在读取显式 EI overlay…")
        ttk.Label(
            revision,
            textvariable=self.overlay_description_var,
            wraplength=390,
            justify="left",
            style="Subheader.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(1, 7))
        revision.columnconfigure(0, weight=1)
        self.overlay_path_var.trace_add("write", lambda *_args: self._overlay_changed())
        super()._build_left(parent)

    def _browse_overlay(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择显式 EI 科学修订 overlay",
            initialdir=str(self._selected_overlay_path.parent),
            filetypes=(
                ("YAML/JSON overlay", "*.yaml *.yml *.json"),
                ("所有文件", "*"),
            ),
        )
        if path:
            self.overlay_path_var.set(path)

    def _overlay_changed(self) -> None:
        self._refresh_overlay_description()
        if hasattr(self, "window_summary_var"):
            self._update_window_summary()

    def _overlay_snapshot(self) -> tuple[Path, Any, str]:
        path = Path(self.overlay_path_var.get()).expanduser().resolve()
        overlay = load_overlay(path)
        digest = _sha256_file(path)
        self._selected_overlay_path = path
        return path, overlay, digest

    def _refresh_overlay_description(self) -> None:
        if not hasattr(self, "overlay_description_var"):
            return
        try:
            path, overlay, digest = self._overlay_snapshot()
            values = ", ".join(
                f"{name}={overlay.branch_bending[name].value_N_m2:.6g} N·m²"
                for name in ("upper_A", "upper_B", "lower")
            )
            self.overlay_description_var.set(
                f"模型：{overlay.model_id}\nEI：{values}\n"
                f"压缩权重：{overlay.compression_scale:.6g}；"
                f"证据上限：{overlay.effective_claim.value}；SHA-256 {digest[:12]}…\n"
                f"文件：{path}"
            )
            if hasattr(self, "inline_error"):
                self.inline_error.configure(text="")
        except Exception as exc:
            self.overlay_description_var.set(f"overlay 无效：{exc}")

    def _augment_request(
        self,
        request: dict[str, Any],
        *,
        preserve_existing: bool = False,
    ) -> dict[str, Any]:
        result = deepcopy(request)
        if result.get("backend") == "forward":
            return result
        coordinates = result.setdefault("scan_coordinates", {})
        if not isinstance(coordinates, dict):
            raise ValueError("scan_coordinates 必须是映射。")
        if (
            preserve_existing
            and isinstance(coordinates.get(OVERLAY_PATH_KEY), str)
            and isinstance(coordinates.get(OVERLAY_SHA256_KEY), str)
        ):
            return result
        path, _overlay, digest = self._overlay_snapshot()
        coordinates[OVERLAY_PATH_KEY] = str(path)
        coordinates[OVERLAY_SHA256_KEY] = digest
        return result

    def _current_request(self, backend: str | None = None) -> dict[str, Any]:
        return self._augment_request(super()._current_request(backend))

    def _save_request_file(self, request: dict[str, Any], suffix: str = "") -> Path:
        return super()._save_request_file(
            self._augment_request(request, preserve_existing=True), suffix=suffix
        )

    @staticmethod
    def _minimum_signed_force(data: Any) -> float:
        values = [np.asarray(item, dtype=float) for item in data.signed_axial_force.values()]
        return float(np.min(np.concatenate(values, axis=1))) if values else 0.0

    @staticmethod
    def _bending_fraction(data: Any) -> float:
        bending = data.energy.get("elastic_bending")
        axial = data.energy.get("elastic_axial")
        if bending is None or axial is None:
            return 0.0
        bending_array = np.asarray(bending, dtype=float)
        axial_array = np.asarray(axial, dtype=float)
        return float(
            np.max(
                bending_array
                / np.maximum(np.abs(bending_array) + np.abs(axial_array), 1.0e-30)
            )
        )

    def _update_window_summary(self) -> None:
        super()._update_window_summary()
        if not hasattr(self, "window_summary_var"):
            return
        text = self.window_summary_var.get().split("\n科学护栏：", 1)[0]
        try:
            _path, overlay, _digest = self._overlay_snapshot()
            ei = "/".join(
                f"{overlay.branch_bending[name].value_N_m2:.3g}"
                for name in ("upper_A", "upper_B", "lower")
            )
            overlay_line = (
                f"HF overlay：{overlay.model_id}；EI(A/B/下)={ei} N·m²。"
            )
        except Exception as exc:
            overlay_line = f"HF overlay 无效：{exc}"
        self.window_summary_var.set(
            text
            + "\n科学护栏：HF-ROD 是显式 EI 柔性杆；有限记录频谱只作预览。\n"
            + overlay_line
        )

    def _render_bundle(self, bundle: Any) -> None:
        hf = bundle.high_fidelity
        compression_active = hf is not None and self._minimum_signed_force(hf) < -1.0e-10
        bending_significant = hf is not None and self._bending_fraction(hf) > 0.05
        if compression_active or bending_significant:
            self.geometry_material_path_var.set(True)
        super()._render_bundle(bundle)

        revision = bundle.desktop_result.get("scientific_revision")
        warnings = [
            "[审查后科学护栏]",
            "FWD-CABLE 与 HF-ROD 是不同模型；差值不是数值误差通过/失败指标。",
            "HF 使用本次运行封存的显式各支路 EI overlay；原 HF 证书不被继承。",
            "普通 FFT 页只作展示预览；正式频率、频率比和锁频必须来自多周期可靠性与数值资格。",
        ]
        if isinstance(revision, dict):
            warnings.append(
                f"运行模型：{revision.get('model_id')}；compression="
                f"{revision.get('compression_scale')}；"
                f"overlay SHA={str(revision.get('sha256', ''))[:12]}…"
            )
        if compression_active:
            warnings.append(
                "HF-ROD 已激活压缩：三维页自动显示原始材料路径，不能按绷直端点弦解释。"
            )
        if bending_significant:
            warnings.append(
                "HF-ROD 弯曲能占比超过 5%；应使用独立测量 EI，而不是仅由拉伸 E 和直径推导。"
            )
        existing = self.summary_text.get("1.0", "end").rstrip()
        self._set_text(
            self.summary_text, existing + "\n\n" + "\n".join(warnings) + "\n"
        )

    def _render_analysis(self, bundle: Any) -> None:
        figure = self.figures["analysis"]
        figure.clear()
        figure.subplots_adjust(
            left=0.08, right=0.98, bottom=0.11, top=0.80, wspace=0.28
        )
        spectrum_axis, phase_axis = figure.subplots(1, 2)
        backends = self._backends(bundle)
        status_lines: list[str] = []
        for data in backends:
            name = base.PLOT_BACKEND_NAMES[data.backend]
            try:
                audit = frequency_preview(data.time, data.bob_position[:, 0])
            except ValueError as exc:
                status_lines.append(f"{name}: UNAVAILABLE; {exc}")
                audit = None
            if audit is not None:
                status_lines.append(
                    f"{name}: {audit.status}; cycles={audit.observed_cycles:.3g}; "
                    f"f={audit.frequency_hz if audit.frequency_hz is not None else '—'} Hz"
                )
                if audit.frequency_hz is not None:
                    frequency, amplitude, _ = preview_spectrum(
                        data.time, data.bob_position[:, 0]
                    )
                    spectrum_axis.plot(
                        frequency[1:],
                        amplitude[1:],
                        color=base.PLOT_COLORS[
                            0 if data.backend == "forward" else 1
                        ],
                        linestyle=base.PLOT_STYLES[data.backend],
                        label=name,
                        linewidth=1.2,
                    )
            phase_axis.plot(
                data.bob_position[:, 0],
                data.bob_velocity[:, 0],
                color=base.PLOT_COLORS[0 if data.backend == "forward" else 1],
                linestyle=base.PLOT_STYLES[data.backend],
                label=name,
                linewidth=1.0,
            )
        spectrum_axis.set_xlabel("频率 (Hz)")
        spectrum_axis.set_ylabel("Hann 窗幅值 (m)")
        spectrum_axis.set_title("有限记录频谱预览（非正式证书）")
        phase_axis.set_xlabel("x (m)")
        phase_axis.set_ylabel("v_x (m/s)")
        phase_axis.set_title("摆球 x–v_x 相图")
        if spectrum_axis.lines:
            spectrum_axis.legend(fontsize=8, frameon=False)
        if phase_axis.lines:
            phase_axis.legend(fontsize=8, frameon=False)
        spectrum_axis.text(
            0.01,
            -0.28,
            "\n".join(status_lines),
            transform=spectrum_axis.transAxes,
            fontsize=7.5,
            va="top",
        )
        spectrum_axis.grid(alpha=0.25)
        phase_axis.grid(alpha=0.25)
        self.canvases["analysis"].draw_idle()

    def coverage_summary(self) -> dict[str, Any]:
        payload = super().coverage_summary()
        try:
            path, overlay, digest = self._overlay_snapshot()
            selected = {
                "path": str(path),
                "sha256": digest,
                "model_id": overlay.model_id,
                "branch_EI_N_m2": {
                    name: overlay.branch_bending[name].value_N_m2
                    for name in ("upper_A", "upper_B", "lower")
                },
            }
        except Exception as exc:
            selected = {"error": str(exc)}
        payload["scientific_revision"] = {
            "model_labels_explicit": True,
            "selected_overlay": selected,
            "hf_worker": "ypendulum.scientific_revision.revised_desktop_worker",
            "frequency_display": (
                "preview_only_with_cycle_and_window_stability_guard"
            ),
            "compression_switches_to_raw_material_path": True,
            "full_model_difference_is_not_pass_fail": True,
        }
        return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scientific-guarded Y-pendulum desktop GUI"
    )
    parser.add_argument("--smoke-test", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    root = tk.Tk()
    application = ScientificRevisionDesktopApp(root)
    if arguments.smoke_test:
        root.withdraw()
        root.update_idletasks()
        print(json.dumps(application.coverage_summary(), ensure_ascii=False, indent=2))
        root.destroy()
        return 0
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

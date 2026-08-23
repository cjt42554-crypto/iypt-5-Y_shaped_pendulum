"""Modular Streamlit front end for the persistent research platform.

Long simulations are always child processes managed by ``PersistentJobManager``.
This module only validates plans, submits commands, controls process groups and
renders plugin-declared data products.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml

from ypendulum.ui.platform import (
    PersistentJobManager,
    ProblemAdapter,
    SweepPoint,
    ViewSchema,
    expand_run_plan,
)
from ypendulum.ui.problem_plugins import default_registry

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASE = PROJECT_ROOT / "configs" / "unified_shared_forward_case.yaml"
DEFAULT_RUN_ROOT = PROJECT_ROOT / "runs" / "unified"
PLATFORM_STATE_ROOT = PROJECT_ROOT / "runs" / ".ui_platform"


def _manager() -> PersistentJobManager:
    if "persistent_research_job_manager" not in st.session_state:
        st.session_state.persistent_research_job_manager = PersistentJobManager(
            PLATFORM_STATE_ROOT,
            REGISTRY,
            max_parallel=1,
        )
    return st.session_state.persistent_research_job_manager


def _resolve_view_source(run: Path, relative: str) -> Path:
    if Path(relative).is_absolute():
        raise ValueError("View source must be relative to the sealed run.")
    path = (run / relative).resolve()
    if not path.is_relative_to(run.resolve()):
        raise ValueError("View source escapes the sealed run.")
    return path


def _lookup(value: Any, dotted: str) -> Any:
    current = value
    for key in dotted.split("."):
        if not isinstance(current, Mapping) or key not in current:
            return "<由后端配置与共享输入审计解析>"
        current = current[key]
    return current


def _configuration_panel(adapter: ProblemAdapter, config_path: Path) -> None:
    document = adapter.read_configuration(config_path)
    case_payload = document.get("case", document)
    tabs = st.tabs([section.label for section in adapter.schema.configuration_sections])
    for tab, section in zip(tabs, adapter.schema.configuration_sections, strict=True):
        with tab:
            st.caption(section.description)
            values: dict[str, Any] = {}
            for path in section.payload_paths:
                if path.split(".", 1)[0] in document:
                    values[path] = _lookup(document, path)
                else:
                    values[path] = _lookup(case_payload, path)
            st.json(values)
    with st.expander("完整解析 case、逐项共享输入审计与实际路径"):
        st.json(document)


def _load_npz(path: Path) -> dict[str, np.ndarray]:
    payload = path.read_bytes()
    with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
        return {key: np.asarray(archive[key]) for key in archive.files}


def _render_npz_trajectory(view: ViewSchema, source: Path) -> None:
    arrays = _load_npz(source)
    options = dict(view.options)
    time = np.asarray(arrays[options["time"]], dtype=float)
    series = {
        label: np.asarray(arrays[key], dtype=float)
        for label, key in dict(options["series"]).items()
    }
    if time.size < 1 or any(values.shape != (time.size, 3) for values in series.values()):
        raise ValueError("Trajectory view received incompatible array shapes.")
    index = st.slider(
        f"{view.label} 时间索引",
        0,
        int(time.size - 1),
        int(time.size - 1),
        key=f"view-{view.identifier}-index",
    )
    figure = go.Figure()
    for label, xyz in series.items():
        figure.add_trace(
            go.Scatter3d(
                x=xyz[: index + 1, 0],
                y=xyz[: index + 1, 1],
                z=xyz[: index + 1, 2],
                mode="lines",
                name=label,
            )
        )
        figure.add_trace(
            go.Scatter3d(
                x=[xyz[index, 0]],
                y=[xyz[index, 1]],
                z=[xyz[index, 2]],
                mode="markers",
                marker={"size": 6},
                name=f"{label} @ {time[index]:.6g} s",
                showlegend=False,
            )
        )
    figure.update_layout(
        title=f"{view.label}，t={time[index]:.8g} s",
        scene={
            "xaxis_title": f"x [{options.get('unit', '1')}]",
            "yaxis_title": f"y [{options.get('unit', '1')}]",
            "zaxis_title": f"z [{options.get('unit', '1')}]",
            "aspectmode": "data",
        },
    )
    st.plotly_chart(figure, use_container_width=True)


def _render_npz_vector_timeseries(view: ViewSchema, source: Path) -> None:
    arrays = _load_npz(source)
    options = dict(view.options)
    time = np.asarray(arrays[options["time"]], dtype=float)
    values = np.asarray(arrays[options["series"]], dtype=float)
    labels = tuple(options.get("components", ()))
    if values.ndim != 2 or values.shape[0] != time.size or values.shape[1] != len(labels):
        raise ValueError("Vector time-series view received incompatible array shapes.")
    figure = go.Figure()
    for index, label in enumerate(labels):
        figure.add_trace(go.Scatter(x=time, y=values[:, index], mode="lines", name=label))
    figure.add_trace(
        go.Scatter(
            x=time,
            y=np.linalg.norm(values, axis=1),
            mode="lines",
            name="norm",
            line={"width": 3},
        )
    )
    figure.update_layout(
        title=view.label,
        xaxis_title="time [s]",
        yaxis_title=f"value [{options.get('unit', '1')}]",
    )
    st.plotly_chart(figure, use_container_width=True)


def _render_hdf5_snapshot(view: ViewSchema, source: Path) -> None:
    options = dict(view.options)
    with h5py.File(source, "r") as h5:
        time = np.asarray(h5[options["time"]], dtype=float)
        if time.size < 1:
            raise ValueError("HDF5 snapshot view has an empty time axis.")
        index = st.slider(
            f"{view.label} 时间索引",
            0,
            int(time.size - 1),
            int(time.size - 1),
            key=f"view-{view.identifier}-index",
        )
        figure = go.Figure()
        scalar_templates = dict(options.get("scalar_templates", {}))
        for label, dataset in dict(options["paths"]).items():
            xyz = np.asarray(h5[dataset][index], dtype=float)
            suffixes: list[str] = []
            for scalar_label, template in scalar_templates.items():
                key = str(template).format(name=label)
                if key in h5:
                    scalar = np.asarray(h5[key][index], dtype=float)
                    if scalar.size:
                        suffixes.append(f"max {scalar_label}={np.max(scalar):.5g}")
                else:
                    suffixes.append(f"{scalar_label}=未提供")
            legend = label if not suffixes else f"{label}; {'; '.join(suffixes)}"
            figure.add_trace(
                go.Scatter3d(
                    x=xyz[:, 0],
                    y=xyz[:, 1],
                    z=xyz[:, 2],
                    mode="lines+markers",
                    name=legend,
                )
            )
        for label, dataset in dict(options.get("points", {})).items():
            xyz = np.asarray(h5[dataset][index], dtype=float)
            figure.add_trace(
                go.Scatter3d(
                    x=[xyz[0]],
                    y=[xyz[1]],
                    z=[xyz[2]],
                    mode="markers",
                    marker={"size": 8},
                    name=label,
                )
            )
        figure.update_layout(
            title=f"{view.label}，t={time[index]:.8g} s",
            scene={"aspectmode": "data"},
        )
        st.plotly_chart(figure, use_container_width=True)


def _render_hdf5_group(view: ViewSchema, source: Path) -> None:
    options = dict(view.options)
    with h5py.File(source, "r") as h5:
        time = np.asarray(h5[options["time"]], dtype=float)
        group_path = str(options["group"])
        if group_path not in h5:
            st.info(f"该产物没有 {group_path} 数据组。")
            return
        group = h5[group_path]
        available = [
            key
            for key in group.keys()
            if isinstance(group[key], h5py.Dataset)
            and group[key].ndim == 1
            and group[key].shape[0] == time.size
        ]
        preferred = [key for key in options.get("preferred", ()) if key in available]
        keys = preferred + [key for key in available if key not in preferred]
        if not keys:
            st.info("该数据组中没有与时间轴一致的一维序列。")
            return
        selected = st.multiselect(
            f"{view.label} 序列",
            keys,
            default=keys[: min(6, len(keys))],
            key=f"view-{view.identifier}-series",
        )
        figure = go.Figure()
        for key in selected:
            dataset = group[key]
            unit = dataset.attrs.get("unit", "1")
            figure.add_trace(
                go.Scatter(
                    x=time,
                    y=np.asarray(dataset, dtype=float),
                    mode="lines",
                    name=f"{key} [{unit}]",
                )
            )
        figure.update_layout(title=view.label, xaxis_title="time [s]")
        st.plotly_chart(figure, use_container_width=True)


def _render_view(view: ViewSchema, run: Path) -> None:
    source = _resolve_view_source(run, view.source)
    if not source.is_file():
        st.info(f"当前运行未生成 {view.label}：{view.source}")
        return
    if view.kind == "npz_trajectory3d":
        _render_npz_trajectory(view, source)
    elif view.kind == "npz_vector_timeseries":
        _render_npz_vector_timeseries(view, source)
    elif view.kind == "hdf5_polyline_snapshot":
        _render_hdf5_snapshot(view, source)
    elif view.kind == "hdf5_group_timeseries":
        _render_hdf5_group(view, source)
    elif view.kind == "json":
        st.json(json.loads(source.read_text(encoding="utf-8")))
    else:
        st.warning(f"未注册的视图种类：{view.kind}")


def _common_analysis(adapter: ProblemAdapter, run: Path) -> None:
    trajectory = next(
        (view for view in adapter.schema.views if view.kind == "npz_trajectory3d"),
        None,
    )
    if trajectory is None:
        return
    source = _resolve_view_source(run, trajectory.source)
    if not source.is_file():
        return
    arrays = _load_npz(source)
    options = dict(trajectory.options)
    time = np.asarray(arrays[options["time"]], dtype=float)
    series = {
        label: np.asarray(arrays[key], dtype=float)
        for label, key in dict(options["series"]).items()
    }
    if time.size < 3 or not np.all(np.diff(time) > 0.0):
        st.warning("通用相图/频谱要求至少三个严格递增时间样本。")
        return
    tabs = st.tabs(["时间序列", "相图", "频谱", "数据导出"])
    with tabs[0]:
        figure = go.Figure()
        for label, xyz in series.items():
            for component, axis in enumerate("xyz"):
                figure.add_trace(
                    go.Scatter(x=time, y=xyz[:, component], mode="lines", name=f"{label}/{axis}")
                )
        figure.update_layout(xaxis_title="time [s]", yaxis_title="position [m]")
        st.plotly_chart(figure, use_container_width=True)
    with tabs[1]:
        figure = go.Figure()
        for label, xyz in series.items():
            velocity_x = np.gradient(xyz[:, 0], time)
            figure.add_trace(go.Scatter(x=xyz[:, 0], y=velocity_x, mode="lines", name=label))
        figure.update_layout(xaxis_title="x [m]", yaxis_title="dx/dt [m/s]")
        st.plotly_chart(figure, use_container_width=True)
        st.caption("速度为展示层对封存位置序列的数值梯度，不替代后端动力学状态。")
    with tabs[2]:
        uniform_time = np.linspace(time[0], time[-1], time.size)
        frequency = np.fft.rfftfreq(time.size, d=float(uniform_time[1] - uniform_time[0]))
        figure = go.Figure()
        for label, xyz in series.items():
            x_uniform = np.interp(uniform_time, time, xyz[:, 0])
            amplitude = np.abs(np.fft.rfft(x_uniform - np.mean(x_uniform)))
            figure.add_trace(go.Scatter(x=frequency[1:], y=amplitude[1:], mode="lines", name=label))
        figure.update_layout(xaxis_title="frequency [Hz]", yaxis_title="FFT amplitude [m]")
        st.plotly_chart(figure, use_container_width=True)
        st.caption("非均匀返回时间会先线性重采样到等距展示网格；此图不作为求解器误差证书。")
    with tabs[3]:
        frame = pd.DataFrame({"time_s": time})
        for label, xyz in series.items():
            safe = label.lower().replace(" ", "_")
            for component, axis in enumerate("xyz"):
                frame[f"{safe}_{axis}_m"] = xyz[:, component]
        st.download_button(
            "导出共同轨迹 CSV",
            frame.to_csv(index=False).encode("utf-8"),
            file_name=f"{run.name}_common_trajectories.csv",
            mime="text/csv",
        )
        st.download_button(
            "导出原始比较 NPZ",
            source.read_bytes(),
            file_name=source.name,
            mime="application/octet-stream",
        )


def _parse_batch(text: str, base: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for raw in text.splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = base.parent / path
        paths.append(path.resolve())
    return tuple(paths)


def _parse_sweep(text: str, base: Path) -> tuple[SweepPoint, ...]:
    payload = yaml.safe_load(text) if text.strip() else None
    if not isinstance(payload, list):
        raise ValueError("参数扫描必须是 YAML 列表。")
    points: list[SweepPoint] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict) or set(item) != {"label", "config", "coordinates"}:
            raise ValueError(f"扫描点 {index} 必须且只能包含 label、config、coordinates。")
        config = Path(item["config"]).expanduser()
        if not config.is_absolute():
            config = base.parent / config
        if not isinstance(item["coordinates"], dict):
            raise ValueError(f"扫描点 {index} 的 coordinates 必须是映射。")
        points.append(
            SweepPoint(
                label=str(item["label"]),
                config_path=config.resolve(),
                coordinates=dict(item["coordinates"]),
            )
        )
    return tuple(points)


REGISTRY = default_registry()

st.set_page_config(page_title="Unified Physics Research Platform", layout="wide")
st.title("统一物理研究计算平台")
st.caption(
    "通用前端只编排问题插件、不可变配置和隔离子进程；题目物理、后端命令、视图与实验观测合同均由插件声明。"
)

schemas = REGISTRY.schemas()
with st.sidebar:
    st.header("问题与模型配置")
    problem_id = st.selectbox(
        "研究题目",
        [schema.identifier for schema in schemas],
        format_func=lambda identifier: next(
            schema.title for schema in schemas if schema.identifier == identifier
        ),
    )
    adapter = REGISTRY.get(problem_id)
    st.caption(adapter.schema.description)
    case_text = st.text_input("配置文件", str(DEFAULT_CASE))
    case_path = Path(case_text).expanduser().resolve()
    backend = st.selectbox(
        "计算模式 / 模型层级",
        [item.identifier for item in adapter.schema.backends],
        format_func=lambda identifier: adapter.schema.backend(identifier).label,
    )
    selected_backend = adapter.schema.backend(backend)
    st.caption(f"{selected_backend.model_level}：{selected_backend.description}")
    mode = st.selectbox(
        "运行计划",
        ("single", "repeat", "batch", "sweep", "same_input_dual"),
        format_func={
            "single": "单次运行",
            "repeat": "同配置重复实验",
            "batch": "批量配置",
            "sweep": "显式参数扫描",
            "same_input_dual": "同一输入双后端",
        }.get,
    )
    repetitions = st.number_input(
        "每个配置重复次数",
        min_value=1,
        max_value=100,
        value=1,
        disabled=mode in {"single", "same_input_dual"},
    )
    batch_text = ""
    sweep_text = ""
    if mode == "batch":
        batch_text = st.text_area("批量配置（每行一个路径）", "")
    elif mode == "sweep":
        sweep_text = st.text_area(
            "参数扫描 YAML",
            "- label: horizon_0p12\n  config: unified_shared_forward_case.yaml\n  coordinates:\n    comparison_horizon: 0.12\n",
            help="每个坐标点必须引用一份独立有效配置；平台不会暗中改写物理参数。",
        )
    output_parent = (
        Path(st.text_input("唯一输出目录的父目录", str(DEFAULT_RUN_ROOT))).expanduser().resolve()
    )
    batch_label = st.text_input("运行标签", datetime.now(UTC).strftime("run_%Y%m%dT%H%M%SZ"))

configuration_identity: Mapping[str, Any] | None = None
try:
    configuration_identity = adapter.validate_configuration(case_path)
    st.success(
        f"配置与依赖身份链通过；原始 case 身份 {configuration_identity.get('case_sha256', '')[:12]}…"
    )
    _configuration_panel(adapter, case_path)
    raw_config = case_path.read_bytes()
    st.download_button(
        "保存 / 导出当前配置原文",
        raw_config,
        file_name=case_path.name,
        mime="text/yaml",
    )
    with st.expander("配置原文编辑与另存（不会覆盖当前文件）"):
        edited = st.text_area(
            "YAML 原文",
            raw_config.decode("utf-8"),
            height=260,
            key=f"raw-config-{case_path}",
        )
        st.download_button(
            "下载编辑后的新配置",
            edited.encode("utf-8"),
            file_name=f"edited_{case_path.name}",
            mime="text/yaml",
        )
        st.caption("载入通过上方路径完成；新文件仍必须经过插件的完整身份与语义校验。")
except Exception as exc:
    st.error(f"配置不可运行：{type(exc).__name__}: {exc}")

control_column, result_column = st.columns([1, 2])
manager = _manager()

with control_column:
    st.subheader("异步运行控制")
    if st.button("验证全计划并提交", type="primary", disabled=configuration_identity is None):
        try:
            batch_configs = _parse_batch(batch_text, case_path) if mode == "batch" else ()
            sweep_points = _parse_sweep(sweep_text, case_path) if mode == "sweep" else ()
            plan = expand_run_plan(
                mode=mode,
                base_config=case_path,
                backend=backend,
                repetitions=int(repetitions),
                batch_configs=batch_configs,
                sweep_points=sweep_points,
            )
            identifiers = manager.submit_plan(
                problem_id,
                plan,
                output_parent=output_parent,
                batch_label=batch_label,
            )
            st.success(f"全计划验证后已提交 {len(identifiers)} 个唯一、不可覆盖作业。")
            st.rerun()
        except Exception as exc:
            st.error(f"计划未提交：{type(exc).__name__}: {exc}")

    records = manager.list_jobs(refresh=True)
    rows = [record.row() for record in records]
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
        selected_id = st.selectbox(
            "选择作业",
            [record.identifier for record in records],
            format_func=lambda identifier: next(
                f"{record.label} | {record.state} | {record.backend}"
                for record in records
                if record.identifier == identifier
            ),
        )
        selected = manager.get(selected_id, refresh=False)
        controls = st.columns(3)
        if controls[0].button("暂停", disabled=selected.state != "RUNNING"):
            try:
                manager.pause(selected_id)
                st.rerun()
            except Exception as exc:
                st.error(f"暂停失败：{exc}")
        if controls[1].button("继续", disabled=selected.state != "PAUSED"):
            try:
                manager.resume(selected_id)
                st.rerun()
            except Exception as exc:
                st.error(f"继续失败：{exc}")
        if controls[2].button(
            "停止",
            disabled=selected.state not in {"QUEUED", "RUNNING", "PAUSED"},
        ):
            try:
                manager.stop(selected_id)
                st.rerun()
            except Exception as exc:
                st.error(f"停止失败：{exc}")
        if st.button("刷新持久状态"):
            manager.poll()
            st.rerun()
        st.code(manager.tail_log(selected_id), language="text")
        with st.expander("严格作业记录、命令/配置身份与状态历史"):
            st.json(selected.to_payload())
    else:
        st.info("尚无持久作业记录。")

with result_column:
    st.subheader("动态物理视图与通用分析")
    result_records = [
        record
        for record in manager.list_jobs(refresh=False)
        if Path(record.output_directory).is_dir()
    ]
    if result_records:
        result_id = st.selectbox(
            "选择封存运行产物",
            [record.identifier for record in result_records],
            format_func=lambda identifier: next(
                f"{record.label} | {record.state} | {record.output_directory}"
                for record in result_records
                if record.identifier == identifier
            ),
        )
        result_record = next(record for record in result_records if record.identifier == result_id)
        result_adapter = REGISTRY.get(result_record.plugin_id)
        run = Path(result_record.output_directory)
        try:
            assessment = manager.audit_output(result_id)
            if assessment.terminal_state == "FAILED":
                st.error(assessment.reason)
            elif assessment.terminal_state == "OUT_OF_SCOPE_PREFIX":
                st.warning(assessment.reason)
            else:
                st.success(assessment.reason)
            view_tabs = st.tabs([view.label for view in result_adapter.schema.views])
            for tab, view in zip(view_tabs, result_adapter.schema.views, strict=True):
                with tab:
                    _render_view(view, run)
            st.subheader("通用时间序列、相图、频谱与数据导出")
            _common_analysis(result_adapter, run)

            batch_records = [
                record.row()
                for record in manager.list_jobs(refresh=False)
                if record.batch_id == result_record.batch_id
            ]
            if any(row["scan_coordinates"] for row in batch_records):
                st.subheader("参数扫描 / 重复实验矩阵")
                st.dataframe(batch_records, use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(f"产物校验或视图加载失败：{type(exc).__name__}: {exc}")
    else:
        st.info("完成或显式前缀产物出现后，将按题目插件动态加载轨迹、场/几何、接触余量和能量视图。")

st.divider()
st.subheader("实验数据导入与 HF / FWD / 实验三方直接对照")
completed_dual = [
    record
    for record in manager.list_jobs(refresh=False)
    if record.state == "COMPLETED" and record.backend == "both"
]
experiment = st.file_uploader(
    "上传题目插件规定的实验文件；Y 形摆要求严格 CSV: time_s,x_m,y_m",
    type=["csv"],
)
if completed_dual:
    experiment_job_id = st.selectbox(
        "双后端完成运行",
        [record.identifier for record in completed_dual],
        format_func=lambda identifier: next(
            record.label for record in completed_dual if record.identifier == identifier
        ),
    )
    if st.button("生成无拟合三方对照", disabled=experiment is None):
        selected = next(
            record for record in completed_dual if record.identifier == experiment_job_id
        )
        adapter = REGISTRY.get(selected.plugin_id)
        temporary_root = Path(tempfile.mkdtemp(prefix="ypendulum_experiment_"))
        experiment_path = temporary_root / "experiment.csv"
        assert experiment is not None
        experiment_path.write_bytes(experiment.getvalue())
        run = Path(selected.output_directory)
        destination = run.parent / f"{run.name}.experiment_comparison_{uuid.uuid4().hex[:10]}"
        try:
            report = adapter.compare_experiment(
                run,
                experiment_path,
                output_directory=destination,
            )
            st.json(report)
            st.success(f"三方对照已写入唯一目录：{destination}")
        except Exception as exc:
            st.error(f"实验对照失败：{type(exc).__name__}: {exc}")
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)
else:
    st.info("需要一个状态为 COMPLETED 的同输入双后端运行，前缀或失败产物不能进入三方比较。")

st.warning(
    "平台严格区分 COMPLETED、OUT_OF_SCOPE_PREFIX、FAILED 与 STOPPED。图形相似、频谱峰或前缀轨迹均不会自动升级为验证结论；结构性理论也不写入本阶段控制器。"
)

"""Problem plugins shipped with the generic research platform.

Only this module binds the reusable UI controller to Y-pendulum concepts.  A
future problem supplies another adapter with the same protocol and declarative
schemas; the queue and lifecycle controller do not change.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ypendulum.ui.platform import (
    AnalysisSchema,
    BackendSchema,
    ConfigurationSectionSchema,
    OutputAssessment,
    PluginRegistry,
    ProblemSchema,
    ViewSchema,
    canonical_json_sha256,
    sha256_file,
)


def _load_json(path: Path) -> Any:
    def object_pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"Duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-finite JSON constant in {path}: {value}")

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )


def _resolve_manifest_path(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("Artifact manifest contains an invalid relative path.")
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError(f"Artifact manifest path escapes run directory: {relative}")
    if not result.is_file():
        raise FileNotFoundError(f"Artifact manifest path is absent: {relative}")
    return result


class YPendulumUnifiedAdapter:
    """Adapter for the identity-bound two-backend Y-pendulum unified case."""

    schema = ProblemSchema(
        identifier="iypt_2027_y_pendulum",
        title="IYPT 2027 第 5 题：Y 形摆",
        description=("同一共享输入合同下的冻结 FWD-CABLE 与独立 HF 局部离散杆/有限刚体摆球后端。"),
        configuration_format="YPS-UNIFIED-CASE-1.0 YAML",
        backends=(
            BackendSchema(
                "both",
                "同输入双后端",
                "FWD + HF",
                "串行运行两条物理上分离的后端，仅在两者都完成时直接比较。",
            ),
            BackendSchema(
                "forward",
                "前向预测后端",
                "FWD-CABLE-1.0",
                "调用已冻结、身份链完整的前向预测数值程序。",
            ),
            BackendSchema(
                "high_fidelity",
                "第一性原理高保真后端",
                "HF-DISCRETE-ROD-RIGID-BOB-1.0",
                "调用具有新自由度和独立验证闭环的高保真模型。",
            ),
        ),
        configuration_sections=(
            ConfigurationSectionSchema(
                "problem",
                "问题与单位",
                "题目身份、配置 schema 和 SI 单位合同。",
                ("schema_version", "problem_id", "units"),
            ),
            ConfigurationSectionSchema(
                "model",
                "模型层级与计算模式",
                "两后端模型身份与严格交付链。",
                ("forward.model_id", "high_fidelity.model_id"),
            ),
            ConfigurationSectionSchema(
                "parameters",
                "物理参数",
                "后端配置内的几何、质量、材料与流体参数；统一 case 记录其哈希。",
                (
                    "forward.config",
                    "forward.expected_config_file_sha256",
                    "high_fidelity.config",
                    "high_fidelity.expected_config_file_sha256",
                    "shared_input_audit.physical_parameters",
                ),
            ),
            ConfigurationSectionSchema(
                "initial_conditions",
                "初始条件",
                "两后端共享初态的语义映射由逐项审计记录给出。",
                (
                    "backend_configuration.forward.initial_state",
                    "backend_configuration.high_fidelity.initial_condition",
                    "shared_input_audit.initial",
                ),
            ),
            ConfigurationSectionSchema(
                "boundary_conditions",
                "边界条件",
                "支点位置/运动与接触有效性边界。",
                (
                    "backend_configuration.forward.inputs.support_A",
                    "backend_configuration.forward.inputs.support_B",
                    "backend_configuration.high_fidelity.supports",
                    "shared_input_audit.supports",
                ),
            ),
            ConfigurationSectionSchema(
                "external_driving",
                "外部驱动",
                "支点运动、外力和空气相对运动的语义开关。",
                (
                    "backend_configuration.forward.inputs",
                    "backend_configuration.high_fidelity.environment",
                    "shared_input_audit.external_drive",
                ),
            ),
            ConfigurationSectionSchema(
                "solver",
                "求解器设置",
                "各后端数值容差属于模式专属字段，不伪装成共享物理输入。",
                (
                    "backend_configuration.forward.numerics",
                    "backend_configuration.high_fidelity.solver",
                ),
            ),
            ConfigurationSectionSchema(
                "interval",
                "仿真区间与观测器",
                "共同时间窗和显式单位观测合同。",
                ("comparison.window_s", "comparison.observer_contract"),
            ),
        ),
        views=(
            ViewSchema(
                "backend_trajectories",
                "双后端三维轨迹",
                "npz_trajectory3d",
                "comparison/comparison_series.npz",
                {
                    "time": "time_s",
                    "series": {
                        "FWD-CABLE": "forward_bob_position_m",
                        "HF": "high_fidelity_bob_position_m",
                    },
                    "unit": "m",
                },
            ),
            ViewSchema(
                "model_difference",
                "HF − FWD 位置差",
                "npz_vector_timeseries",
                "comparison/comparison_series.npz",
                {
                    "time": "time_s",
                    "series": "bob_position_difference_m",
                    "components": ("x", "y", "z"),
                    "unit": "m",
                },
            ),
            ViewSchema(
                "hf_geometry",
                "HF 材料路径与有限刚体摆球",
                "hdf5_polyline_snapshot",
                "high_fidelity/result.h5",
                {
                    "time": "/time",
                    "paths": {
                        "upper_A": "/cables/upper_A/material_path/position",
                        "upper_B": "/cables/upper_B/material_path/position",
                        "lower": "/cables/lower/material_path/position",
                    },
                    "scalar_templates": {
                        "tension": "/cables/{name}/segments/tension",
                        "signed axial force (compression < 0)": (
                            "/cables/{name}/segments/signed_axial_force"
                        ),
                    },
                    "points": {"bob COM": "/bodies/bob/com_position"},
                },
            ),
            ViewSchema(
                "hf_energy",
                "HF 能量收支",
                "hdf5_group_timeseries",
                "high_fidelity/result.h5",
                {
                    "time": "/time",
                    "group": "/energy",
                    "preferred": (
                        "mechanical",
                        "kinetic",
                        "gravitational",
                        "elastic_axial",
                        "elastic_bending",
                        "dissipation_axial",
                        "dissipation_aero",
                        "work_air",
                        "work_support",
                        "balance_residual",
                    ),
                },
            ),
            ViewSchema(
                "hf_validity",
                "HF 接触/几何有效性余量",
                "hdf5_group_timeseries",
                "high_fidelity/result.h5",
                {
                    "time": "/time",
                    "group": "/validity/guard_margin",
                    "preferred": (),
                },
            ),
            ViewSchema(
                "delivery_identity",
                "封存运行身份",
                "json",
                "delivery_root.json",
                {},
            ),
        ),
        analyses=(
            AnalysisSchema("time_series", "时间序列", "generic", "位置、差值和有效性余量。"),
            AnalysisSchema("phase", "相图", "generic", "由封存位置序列与时间差分速度构造。"),
            AnalysisSchema("spectrum", "频谱", "generic", "对严格递增采样进行去均值频谱分析。"),
            AnalysisSchema(
                "parameter_dependence",
                "参数依赖",
                "job_matrix",
                "与扫描坐标、重复编号和产物身份直接绑定。",
            ),
            AnalysisSchema("error", "误差曲线", "generic", "双后端差值分量与模长。"),
            AnalysisSchema(
                "conservation", "守恒量/能量收支", "generic", "显示机械能、功、耗散和平衡残差。"
            ),
            AnalysisSchema(
                "model_difference", "模型间差异", "generic", "仅在双后端完成的共同返回区间内显示。"
            ),
            AnalysisSchema(
                "experiment",
                "实验三方对照",
                "experiment_csv",
                "显式米制观测与 HF/FWD 无拟合直接对照。",
            ),
            AnalysisSchema(
                "import_export",
                "数据导入/导出",
                "generic",
                "导入实验 CSV，导出原始封存报告和序列。",
            ),
        ),
    )

    def validate_configuration(self, path: Path) -> Mapping[str, Any]:
        # Imports remain local so the generic plugin schema can be inspected in
        # lightweight environments without eagerly importing numerical solvers.
        from ypendulum.unified.contracts import (
            load_unified_case,
            verify_unified_case_identities,
        )

        case = load_unified_case(path)
        live = verify_unified_case_identities(case)
        return {
            "adapter_schema": "YPS-UNIFIED-PLUGIN-INPUT-IDENTITY-1.0",
            "case_sha256": case.case_hash_sha256,
            "case_file_sha256": case.case_file_sha256,
            "problem_id": case.payload["problem_id"],
            "units": case.payload["units"],
            "shared_input_audit_passed": case.shared_input_audit["passed"],
            "shared_input_check_count": case.shared_input_audit["check_count"],
            "live_dependency_identity": live,
        }

    def build_command(
        self, config_path: Path, *, backend: str, output_directory: Path
    ) -> Sequence[str]:
        from ypendulum.unified.jobs import unified_job_command

        self.schema.backend(backend)
        return unified_job_command(
            config_path,
            backend=backend,
            output_directory=output_directory,
        )

    def validate_scan_coordinates(
        self, path: Path, coordinates: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        if not coordinates:
            return {}
        from ypendulum.unified.contracts import load_unified_case

        case = load_unified_case(path)
        checks = {
            check["field"]: check
            for check in case.shared_input_audit["checks"]
            if check.get("passed") is True
        }
        for field, declared in coordinates.items():
            if field not in checks:
                raise ValueError(
                    f"Y-pendulum scan coordinate is not a verified shared-input field: {field}"
                )
            actual = checks[field].get("forward_value")
            if canonical_json_sha256(actual) != canonical_json_sha256(declared):
                raise ValueError(
                    f"Declared scan coordinate {field}={declared!r} does not match "
                    f"the independently audited configuration value {actual!r}."
                )
        return dict(coordinates)

    def inspect_output(self, output_directory: Path) -> OutputAssessment:
        run = output_directory.resolve()
        root_path = run / "delivery_root.json"
        manifest_path = run / "artifact_manifest.json"
        if not root_path.is_file() or not manifest_path.is_file():
            return OutputAssessment(
                "FAILED",
                "NO_SEALED_DELIVERY",
                "Unified child exited without a sealed delivery root and artifact manifest.",
                accepted_return_codes=(),
            )
        root = _load_json(root_path)
        if (
            not isinstance(root, dict)
            or root.get("schema_version") != "YPS-UNIFIED-DELIVERY-ROOT-1.0"
        ):
            raise ValueError("Unsupported unified delivery-root schema.")
        manifest_sha = sha256_file(manifest_path)
        if root.get("artifact_manifest_sha256") != manifest_sha:
            raise ValueError("Artifact-manifest hash does not match delivery root.")
        manifest = _load_json(manifest_path)
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != "YPS-UNIFIED-ARTIFACT-MANIFEST-1.0"
        ):
            raise ValueError("Unsupported unified artifact-manifest schema.")
        entries = manifest.get("files")
        if not isinstance(entries, list) or not entries:
            raise ValueError("Unified artifact manifest has no files.")
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"}:
                raise ValueError("Unified artifact entry does not match its strict schema.")
            relative = entry["path"]
            if relative in seen:
                raise ValueError(f"Duplicate unified artifact path: {relative}")
            seen.add(relative)
            artifact = _resolve_manifest_path(run, relative)
            if (
                isinstance(entry["bytes"], bool)
                or not isinstance(entry["bytes"], int)
                or entry["bytes"] < 0
                or artifact.stat().st_size != entry["bytes"]
                or sha256_file(artifact) != entry["sha256"]
            ):
                raise ValueError(f"Unified artifact identity mismatch: {relative}")
        actual_files = {str(path.relative_to(run)) for path in run.rglob("*") if path.is_file()}
        expected_files = seen | {"artifact_manifest.json", "delivery_root.json"}
        if actual_files != expected_files:
            raise ValueError(
                "Unified run contains unmanifested or missing files: "
                f"extra={sorted(actual_files - expected_files)}, "
                f"missing={sorted(expected_files - actual_files)}"
            )
        status = root.get("status")
        if (
            root.get("source_stable_during_run") is not True
            or root.get("input_identity_stable_during_run") is not True
            or root.get("shared_input_audit_passed") is not True
            or root.get("source_hash_start_sha256") != root.get("source_hash_end_sha256")
            or root.get("input_identity_start") != root.get("input_identity_end")
        ):
            raise ValueError("Unified delivery lacks a stable source/input identity certificate.")
        selected_backend = root.get("backend_selection")
        expected_outcomes = (
            {"forward", "high_fidelity"} if selected_backend == "both" else {selected_backend}
        )
        outcomes = root.get("backend_outcomes")
        if (
            selected_backend not in {"forward", "high_fidelity", "both"}
            or not isinstance(outcomes, dict)
            or set(outcomes) != expected_outcomes
        ):
            raise ValueError("Unified delivery backend outcomes do not match its selection.")
        common_evidence = {
            "delivery_root_sha256": sha256_file(root_path),
            "artifact_manifest_sha256": manifest_sha,
            "artifact_count": len(entries),
            "backend_selection": root.get("backend_selection"),
            "comparison_status": root.get("comparison_status"),
        }
        binding = {"case_sha256": root.get("case_sha256")}
        request_binding = {"backend": selected_backend}
        if status == "COMPLETE":
            if root.get("backend_selection") == "both" and (
                root.get("comparison_status") != "COMPLETE"
                or "comparison/comparison_series.npz" not in seen
                or "comparison/comparison.json" not in seen
            ):
                raise ValueError("Completed dual-backend run lacks its comparison contract.")
            return OutputAssessment(
                "COMPLETED",
                "COMPLETE",
                "Sealed unified delivery and every manifested artifact verified.",
                evidence=common_evidence,
                accepted_return_codes=(0,),
                input_identity_binding=binding,
                request_binding=request_binding,
            )
        if status == "OUT_OF_SCOPE_PREFIX":
            return OutputAssessment(
                "OUT_OF_SCOPE_PREFIX",
                "OUT_OF_SCOPE_PREFIX",
                "Sealed run is an explicit out-of-scope physical prefix, not a completed prediction.",
                evidence=common_evidence,
                accepted_return_codes=(3,),
                input_identity_binding=binding,
                request_binding=request_binding,
            )
        return OutputAssessment(
            "FAILED",
            str(status or "UNKNOWN"),
            "Unified delivery root has no accepted terminal scientific status.",
            evidence=common_evidence,
            accepted_return_codes=(),
            input_identity_binding=binding,
            request_binding=request_binding,
        )

    def read_configuration(self, path: Path) -> Mapping[str, Any]:
        from ypendulum.config import resolved_config_dict
        from ypendulum.unified.contracts import load_unified_case

        case = load_unified_case(path)
        checks = case.shared_input_audit["checks"]
        groups = {
            "initial": [item for item in checks if item["field"].startswith("initial.")],
            "supports": [item for item in checks if item["field"].startswith("support_")],
            "external_drive": [
                item
                for item in checks
                if any(
                    token in item["field"]
                    for token in ("external", "air_", "drag", "support_motion")
                )
            ],
        }
        grouped_fields = {item["field"] for values in groups.values() for item in values}
        groups["physical_parameters"] = [
            item for item in checks if item["field"] not in grouped_fields
        ]
        return {
            "case": case.payload,
            "shared_input_audit": {**case.shared_input_audit, **groups},
            "backend_configuration": {
                "forward": case.forward_config,
                "high_fidelity": resolved_config_dict(case.high_fidelity_config),
            },
            "resolved_paths": {
                "case": str(case.source_path),
                "forward_config": str(case.forward_config_path),
                "forward_delivery_root": str(case.forward_delivery_root_path),
                "high_fidelity_config": str(case.high_fidelity_config_path),
            },
        }

    def compare_experiment(
        self,
        run_directory: Path,
        experiment_path: Path,
        *,
        output_directory: Path,
    ) -> Mapping[str, Any]:
        from ypendulum.unified.experiment import compare_experiment_to_unified_run

        return compare_experiment_to_unified_run(
            run_directory,
            experiment_path,
            output_directory=output_directory,
        )


def default_registry() -> PluginRegistry:
    return PluginRegistry((YPendulumUnifiedAdapter(),))

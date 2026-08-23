#!/usr/bin/env python3
"""Build a compact, self-contained review package for a memoryless Pro model.

The package deliberately excludes large binary trajectories while preserving:
the full theory documents, current source/tests/configs, key validation reports,
an HDF5 dataset/value inventory, a downsampled HF table, and transport hashes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import h5py
import numpy as np

PACKAGE_NAME = "Y_Pendulum_Pro_Review_2026-08-21"
PACKAGE_SCHEMA = "YPS-PRO-REVIEW-PACKAGE-1.0"
FIXED_ZIP_TIME = (2026, 8, 21, 12, 0, 0)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def source_hash(package_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(package_root.rglob("*.py")):
        digest.update(str(path.relative_to(package_root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def json_ready(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        return json_ready(value.item())
    if isinstance(value, np.ndarray):
        return [json_ready(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_ready(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def copy_file(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def copy_glob(
    source_root: Path,
    target_root: Path,
    patterns: Iterable[str],
    *,
    excluded_parts: set[str] | None = None,
) -> None:
    excluded_parts = excluded_parts or set()
    seen: set[Path] = set()
    for pattern in patterns:
        for source in sorted(source_root.glob(pattern)):
            if not source.is_file() or source in seen:
                continue
            relative = source.relative_to(source_root)
            if any(part in excluded_parts for part in relative.parts):
                continue
            seen.add(source)
            copy_file(source, target_root / relative)


def canonical_dataset_hash(dataset: h5py.Dataset) -> tuple[str, dict[str, Any]]:
    digest = hashlib.sha256()
    digest.update(str(tuple(dataset.shape)).encode())
    digest.update(str(dataset.dtype).encode())

    numeric = dataset.dtype.kind in "biufc"
    finite_count = 0
    nonfinite_count = 0
    value_count = int(np.prod(dataset.shape, dtype=np.int64)) if dataset.shape else 1
    minimum: float | None = None
    maximum: float | None = None
    running_sum = 0.0

    if dataset.shape == ():
        blocks = [np.asarray(dataset[()])]
    elif dataset.shape[0] == 0:
        blocks = []
    else:
        row_bytes = max(1, int(np.prod(dataset.shape[1:], dtype=np.int64))) * max(
            1, dataset.dtype.itemsize
        )
        rows_per_block = max(1, (8 << 20) // row_bytes)
        blocks = (
            np.asarray(dataset[start : min(dataset.shape[0], start + rows_per_block)])
            for start in range(0, dataset.shape[0], rows_per_block)
        )

    text_values: list[str] = []
    for array in blocks:
        if dataset.dtype.kind in "OUS":
            flattened = np.asarray(array, dtype=object).reshape(-1)
            values = [
                item.decode("utf-8", errors="replace")
                if isinstance(item, bytes)
                else str(item)
                for item in flattened
            ]
            text_values.extend(values)
            digest.update(
                json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            continue

        contiguous = np.ascontiguousarray(array)
        digest.update(contiguous.tobytes(order="C"))
        if numeric:
            if np.iscomplexobj(contiguous):
                finite = np.isfinite(contiguous.real) & np.isfinite(contiguous.imag)
                magnitudes = np.abs(contiguous[finite])
                values_for_stats = magnitudes
            else:
                finite = np.isfinite(contiguous)
                values_for_stats = contiguous[finite].astype(np.float64, copy=False)
            block_finite = int(np.count_nonzero(finite))
            finite_count += block_finite
            nonfinite_count += int(finite.size - block_finite)
            if block_finite:
                block_min = float(np.min(values_for_stats))
                block_max = float(np.max(values_for_stats))
                minimum = block_min if minimum is None else min(minimum, block_min)
                maximum = block_max if maximum is None else max(maximum, block_max)
                running_sum += float(np.sum(values_for_stats, dtype=np.float64))

    statistics: dict[str, Any] = {
        "value_count": value_count,
        "canonical_value_sha256": digest.hexdigest(),
    }
    if numeric:
        statistics.update(
            {
                "finite_count": finite_count,
                "nonfinite_count": nonfinite_count,
                "minimum": minimum,
                "maximum": maximum,
                "mean_of_finite_values": (
                    running_sum / finite_count if finite_count else None
                ),
            }
        )
    else:
        statistics["text_values"] = text_values
    return digest.hexdigest(), statistics


def hdf5_inventory(source: Path, output: Path) -> dict[str, Any]:
    datasets: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    with h5py.File(source, "r") as handle:
        root_attributes = {
            str(key): json_ready(value) for key, value in handle.attrs.items()
        }

        def visitor(name: str, obj: h5py.Group | h5py.Dataset) -> None:
            attributes = {
                str(key): json_ready(value) for key, value in obj.attrs.items()
            }
            if isinstance(obj, h5py.Group):
                groups.append({"path": name or "/", "attributes": attributes})
                return
            _, statistics = canonical_dataset_hash(obj)
            datasets.append(
                {
                    "path": name,
                    "shape": list(obj.shape),
                    "dtype": str(obj.dtype),
                    "compression": obj.compression,
                    "compression_options": json_ready(obj.compression_opts),
                    "chunks": list(obj.chunks) if obj.chunks else None,
                    "attributes": attributes,
                    **statistics,
                }
            )

        handle.visititems(visitor)

    payload = {
        "schema": "YPS-HF-HDF5-INVENTORY-1.0",
        "source_path_at_build_time": str(source),
        "source_size_bytes": source.stat().st_size,
        "source_sha256": sha256_file(source),
        "root_attributes": root_attributes,
        "group_count": len(groups),
        "dataset_count": len(datasets),
        "groups": groups,
        "datasets": datasets,
        "note": (
            "canonical_value_sha256 hashes shape, dtype and logical dataset values; "
            "it is not the on-disk HDF5 byte hash."
        ),
    }
    write_json(output, payload)
    return payload


def downsample_hf(source: Path, output: Path, requested_count: int = 301) -> dict[str, Any]:
    with h5py.File(source, "r") as handle:
        time = np.asarray(handle["time"], dtype=float)
        indices = np.unique(
            np.linspace(0, len(time) - 1, min(requested_count, len(time)), dtype=int)
        )
        bob_position = np.asarray(handle["bodies/bob/com_position"][indices], dtype=float)
        bob_velocity = np.asarray(handle["bodies/bob/com_velocity"][indices], dtype=float)
        junction_position = np.asarray(
            handle["bodies/junction/position"][indices], dtype=float
        )
        junction_velocity = np.asarray(
            handle["bodies/junction/velocity"][indices], dtype=float
        )
        modal_fast = np.asarray(handle["analysis/modal/fast"][indices], dtype=float)
        modal_slow = np.asarray(handle["analysis/modal/slow"][indices], dtype=float)
        mechanical = np.asarray(handle["energy/mechanical"][indices], dtype=float)
        elastic_axial = np.asarray(handle["energy/elastic_axial"][indices], dtype=float)
        elastic_bending = np.asarray(
            handle["energy/elastic_bending"][indices], dtype=float
        )
        kinetic = np.asarray(handle["energy/kinetic"][indices], dtype=float)
        gravitational = np.asarray(handle["energy/gravitational"][indices], dtype=float)
        balance = np.asarray(handle["energy/balance_residual"][indices], dtype=float)

        branches = ("upper_A", "upper_B", "lower")
        branch_data: dict[str, dict[str, np.ndarray]] = {}
        for branch in branches:
            signed = np.asarray(
                handle[f"cables/{branch}/segments/signed_axial_force"][indices],
                dtype=float,
            )
            tension = np.asarray(
                handle[f"cables/{branch}/segments/tension"][indices], dtype=float
            )
            branch_data[branch] = {
                "signed_min": np.min(signed, axis=1),
                "signed_max": np.max(signed, axis=1),
                "tension_min": np.min(tension, axis=1),
                "tension_max": np.max(tension, axis=1),
            }

        guard_group = handle["validity/guard_margin"]
        guard_names = sorted(guard_group.keys())
        guard_data = {
            name: np.asarray(guard_group[name][indices], dtype=float)
            for name in guard_names
        }

    fieldnames = [
        "sample_index",
        "time_s",
        "bob_com_x_m",
        "bob_com_y_m",
        "bob_com_z_m",
        "bob_vx_m_s",
        "bob_vy_m_s",
        "bob_vz_m_s",
        "junction_x_m",
        "junction_y_m",
        "junction_z_m",
        "junction_vx_m_s",
        "junction_vy_m_s",
        "junction_vz_m_s",
        "modal_fast",
        "modal_slow",
        "mechanical_energy_J",
        "elastic_axial_energy_J",
        "elastic_bending_energy_J",
        "kinetic_energy_J",
        "gravitational_energy_J",
        "energy_balance_residual",
    ]
    for branch in branches:
        fieldnames.extend(
            [
                f"{branch}_signed_force_min_N",
                f"{branch}_signed_force_max_N",
                f"{branch}_tension_min_N",
                f"{branch}_tension_max_N",
            ]
        )
    fieldnames.extend(f"guard_{name}" for name in guard_names)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row, index in enumerate(indices):
            record: dict[str, Any] = {
                "sample_index": int(index),
                "time_s": float(time[index]),
                "bob_com_x_m": float(bob_position[row, 0]),
                "bob_com_y_m": float(bob_position[row, 1]),
                "bob_com_z_m": float(bob_position[row, 2]),
                "bob_vx_m_s": float(bob_velocity[row, 0]),
                "bob_vy_m_s": float(bob_velocity[row, 1]),
                "bob_vz_m_s": float(bob_velocity[row, 2]),
                "junction_x_m": float(junction_position[row, 0]),
                "junction_y_m": float(junction_position[row, 1]),
                "junction_z_m": float(junction_position[row, 2]),
                "junction_vx_m_s": float(junction_velocity[row, 0]),
                "junction_vy_m_s": float(junction_velocity[row, 1]),
                "junction_vz_m_s": float(junction_velocity[row, 2]),
                "modal_fast": float(modal_fast[row]),
                "modal_slow": float(modal_slow[row]),
                "mechanical_energy_J": float(mechanical[row]),
                "elastic_axial_energy_J": float(elastic_axial[row]),
                "elastic_bending_energy_J": float(elastic_bending[row]),
                "kinetic_energy_J": float(kinetic[row]),
                "gravitational_energy_J": float(gravitational[row]),
                "energy_balance_residual": float(balance[row]),
            }
            for branch in branches:
                for key, values in branch_data[branch].items():
                    suffix = {
                        "signed_min": "signed_force_min_N",
                        "signed_max": "signed_force_max_N",
                        "tension_min": "tension_min_N",
                        "tension_max": "tension_max_N",
                    }[key]
                    record[f"{branch}_{suffix}"] = float(values[row])
            for name, values in guard_data.items():
                record[f"guard_{name}"] = float(values[row])
            writer.writerow(record)

    return {
        "row_count": len(indices),
        "source_sample_count": len(time),
        "first_source_index": int(indices[0]),
        "last_source_index": int(indices[-1]),
        "column_count": len(fieldnames),
        "output_sha256": sha256_file(output),
    }


def write_exclusions(
    project_root: Path, package_root: Path, paths: list[Path]
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            continue
        entries.append(
            {
                "project_relative_path": str(path.relative_to(project_root)),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "reason": "large or redundant binary; textual/inventory evidence is included",
            }
        )
    write_json(package_root / "07_EVIDENCE" / "EXCLUDED_BINARY_ARTIFACTS.json", entries)
    lines = [
        "# Excluded binary artifacts",
        "",
        "These files exist in the completed local project but are not embedded in the compact Pro upload package.",
        "Their hashes and sizes are recorded below. The package includes textual reports, inventories, CSV extracts, or comparison JSON instead.",
        "",
        "| Project-relative path | Bytes | SHA-256 |",
        "|---|---:|---|",
    ]
    for entry in entries:
        lines.append(
            f"| {entry['project_relative_path']} | {entry['size_bytes']} | {entry['sha256']} |"
        )
    lines.extend(
        [
            "",
            "The omitted HF result.h5 is represented by HF_H5_DATASET_INVENTORY.json and HF_TARGET_DOWNSAMPLED_301.csv.",
            "The omitted Stage-2 cable trajectory NPZ is represented by result.json, series.csv and convergence reports.",
            "Performance NPZ files are represented by the JSON comparison reports and GNU-time logs.",
            "",
        ]
    )
    (package_root / "07_EVIDENCE" / "EXCLUDED_BINARY_ARTIFACTS.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    return entries


def append_markdown_file(
    output_handle: Any,
    title: str,
    source: Path,
    *,
    fenced_language: str | None = None,
) -> None:
    output_handle.write(f"\n\n---\n\n# {title}\n\n")
    if fenced_language is None:
        output_handle.write(source.read_text(encoding="utf-8", errors="replace"))
        output_handle.write("\n")
        return
    output_handle.write(f"~~~~{fenced_language}\n")
    output_handle.write(source.read_text(encoding="utf-8", errors="replace"))
    if not source.read_text(encoding="utf-8", errors="replace").endswith("\n"):
        output_handle.write("\n")
    output_handle.write("~~~~\n")


def build_all_in_one(
    project_root: Path,
    package_root: Path,
    guide: Path,
    requirements: Path,
    master: Path,
    stage1: Path,
    stage2_theory: Path,
    stage2_handoff: Path,
    stage3_theory: Path,
    stage3_handoff: Path,
    stage4_theory: Path,
    stage4_handoff: Path,
    stage2_source: Path,
    stage3_root: Path,
) -> Path:
    output = package_root / "01_ALL_IN_ONE_THEORY_AND_HANDOFF.md"
    critical_stage3 = [
        "src/ypendulum/api.py",
        "src/ypendulum/cli.py",
        "src/ypendulum/config/models.py",
        "src/ypendulum/config/validation.py",
        "src/ypendulum/hf/state.py",
        "src/ypendulum/hf/model.py",
        "src/ypendulum/hf/solver.py",
        "src/ypendulum/hf/reference.py",
        "src/ypendulum/hf/validation.py",
        "src/ypendulum/hf/independence.py",
        "src/ypendulum/analysis/diagnostics.py",
        "src/ypendulum/io/hdf5.py",
        "src/ypendulum/solvers/static.py",
        "src/ypendulum/ui/platform.py",
        "src/ypendulum/ui/problem_plugins.py",
        "src/ypendulum/unified/contracts.py",
        "src/ypendulum/unified/adapters.py",
    ]
    with output.open("w", encoding="utf-8") as handle:
        handle.write(
            "# Y 形摆四层研究：Pro 审查单文件版\n\n"
            "此文件把审查导读、原始需求、四层主文稿、交付说明和关键源码合并，"
            "供无法展开 ZIP 的模型直接读取。完整测试、配置、结果 JSON/CSV 和图片仍在压缩包分层目录中。\n"
        )
        for title, path in [
            ("审查导读", guide),
            ("原始四层需求", requirements),
            ("四层总交付说明", master),
            ("Layer 1 前向理论", stage1),
            ("Layer 2 数值理论", stage2_theory),
            ("Layer 2 验收记录", stage2_handoff),
            ("Layer 3 HF 理论与程序说明", stage3_theory),
            ("Layer 3 交付说明", stage3_handoff),
            ("Layer 4 结构性理论", stage4_theory),
            ("Layer 4 交付说明", stage4_handoff),
        ]:
            append_markdown_file(handle, title, path)

        for source in sorted((stage2_source / "y_pendulum_forward").glob("*.py")):
            append_markdown_file(
                handle,
                f"Layer 2 source: {source.name}",
                source,
                fenced_language="python",
            )
        for relative in critical_stage3:
            source = stage3_root / relative
            append_markdown_file(
                handle,
                f"Layer 3 source: {relative}",
                source,
                fenced_language="python",
            )
        append_markdown_file(
            handle,
            "Layer 4 source: torus_structure_analysis.py",
            project_root / "结构性理论" / "analysis" / "torus_structure_analysis.py",
            fenced_language="python",
        )

        for title, source in [
            (
                "Layer 3 target summary JSON",
                stage3_root / "validation" / "target_hf_0p12_raw" / "summary.json",
            ),
            (
                "Layer 3 target diagnostics JSON",
                stage3_root / "validation" / "target_hf_0p12_raw" / "diagnostics.json",
            ),
            (
                "Layer 3 performance report JSON",
                stage3_root
                / "validation"
                / "performance"
                / "performance_optimization_report.json",
            ),
            (
                "Layer 3 representative sensitivity JSON",
                stage3_root / "validation" / "representative_hf_sensitivity.json",
            ),
            (
                "Layer 4 structural results JSON",
                project_root / "结构性理论" / "results" / "structural_analysis_results.json",
            ),
        ]:
            append_markdown_file(handle, title, source, fenced_language="json")
    return output


def build_manifest(package_root: Path, identities: dict[str, str]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(package_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(package_root)
        if str(relative) in {"MANIFEST.json", "SHA256SUMS.txt"}:
            continue
        files.append(
            {
                "path": str(relative),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "schema": PACKAGE_SCHEMA,
        "package_name": PACKAGE_NAME,
        "scope": "personal scientific-computing prototype review package",
        "identities": identities,
        "file_count_excluding_manifest_and_sums": len(files),
        "total_bytes_excluding_manifest_and_sums": sum(
            item["size_bytes"] for item in files
        ),
        "files": files,
    }
    write_json(package_root / "MANIFEST.json", manifest)

    sum_paths = [
        path
        for path in sorted(package_root.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    lines = [
        f"{sha256_file(path)}  {path.relative_to(package_root)}" for path in sum_paths
    ]
    (package_root / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return manifest


def deterministic_zip(package_root: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(
        zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in sorted(package_root.rglob("*")):
            if not path.is_file():
                continue
            relative = Path(PACKAGE_NAME) / path.relative_to(package_root)
            info = zipfile.ZipInfo(str(relative), FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def verify_zip(package_root: Path, zip_path: Path) -> dict[str, Any]:
    expected = {
        str(Path(PACKAGE_NAME) / path.relative_to(package_root)): sha256_file(path)
        for path in package_root.rglob("*")
        if path.is_file()
    }
    with zipfile.ZipFile(zip_path, "r") as archive:
        names = archive.namelist()
        if set(names) != set(expected):
            missing = sorted(set(expected) - set(names))
            extra = sorted(set(names) - set(expected))
            raise RuntimeError(f"ZIP membership mismatch: missing={missing}, extra={extra}")
        for name in names:
            actual = hashlib.sha256(archive.read(name)).hexdigest()
            if actual != expected[name]:
                raise RuntimeError(f"ZIP content mismatch for {name}")
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP CRC failure at {bad}")
    return {
        "file_count": len(expected),
        "zip_size_bytes": zip_path.stat().st_size,
        "zip_sha256": sha256_file(zip_path),
        "all_member_hashes_match": True,
        "crc_test": "PASS",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace only the exact generated package directory and ZIP",
    )
    args = parser.parse_args()

    material_root = Path(__file__).resolve().parent
    project_root = material_root.parent
    output_parent = project_root / "Pro审查包"
    package_root = output_parent / PACKAGE_NAME
    zip_path = output_parent / f"{PACKAGE_NAME}.zip"

    if package_root.exists() or zip_path.exists():
        if not args.overwrite:
            raise SystemExit(
                "Package already exists; pass --overwrite to replace the exact generated targets"
            )
        if package_root.exists():
            shutil.rmtree(package_root)
        if zip_path.exists():
            zip_path.unlink()
    output_parent.mkdir(parents=True, exist_ok=True)
    package_root.mkdir()

    requirements = Path("/home/cjt/竞赛物理研究四层通用框架与统一计算平台需求说明.md")
    stage1 = project_root / "理论" / "IYPT_2027_Y_Pendulum.md"
    stage2_theory = (
        project_root
        / "前向理论数值计算"
        / "IYPT_2027_Y_Pendulum_前向预测理论的数值计算理论.md"
    )
    stage2_handoff = (
        project_root
        / "前向理论数值计算"
        / "IYPT_2027_Y_Pendulum_前向数值计算阶段2验收记录.md"
    )
    stage2_readme = project_root / "前向理论数值计算" / "README.md"
    stage2_root = project_root / "前向理论数值计算" / "y_pendulum_forward_solver"
    stage3_theory = (
        project_root
        / "第一性原理模拟"
        / "IYPT_2027_Y_Pendulum_第一性原理高保真模拟理论与程序说明.md"
    )
    stage3_handoff = project_root / "第一性原理模拟" / "阶段3交付说明.md"
    stage3_root = (
        project_root / "第一性原理模拟" / "Y-Pendulum-Simulator-v1.0.0-rc1"
    )
    stage4_theory = (
        project_root / "结构性理论" / "IYPT_2027_Y_Pendulum_结构性理论.md"
    )
    stage4_handoff = project_root / "结构性理论" / "阶段4交付说明.md"
    master = project_root / "四层研究总交付说明.md"
    guide = material_root / "00_PRO_REVIEW_GUIDE.md"
    prompt = material_root / "00_COPY_PASTE_PROMPT.md"

    expected_hashes = {
        stage1: "7eaf18e30087438507aef73c481b49e5b1427a146d79c0fd2b35ca10dc02cdb2",
        stage2_theory: "14b9e5bae0778753acbc46757286b4d5e646b120698ddd2bc33e16158efa78a7",
        stage2_root
        / "validation"
        / "delivery_root.json": "dec497d42e0384f403b4c652a40799e389702a94b4299b24a4555f2bd9ea93ef",
        stage3_theory: "67f8b8de88f4aa090825a573e6a34ec8cd35cb0f82ede8722f82114290e6bde9",
        stage3_handoff: "c42c6b257efeb482904ba76963b9461f9bae8b14eade661f2135c37068a2f771",
        stage4_theory: "ae7d3b5ecde45603af4b57426972ae94374c9f0e256da9f4973f834a9f064c6d",
        project_root
        / "结构性理论"
        / "analysis"
        / "torus_structure_analysis.py": "895a1340bdeca678f1d44a783bba15c9fcab7e9489401ecf0b4e581ced0c2020",
        project_root
        / "结构性理论"
        / "results"
        / "structural_analysis_results.json": "f1f0789e6ea6910f4d351d21da01e7a6bb4f91ac34169251d0df13a89a42ace1",
    }
    for path, expected in expected_hashes.items():
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(f"Frozen identity mismatch: {path}: {actual} != {expected}")
    stage3_source_hash = source_hash(stage3_root / "src" / "ypendulum")
    if stage3_source_hash != "e2476a8e77d75feee2630e8619472cdee1e35a364017ce514aa0b227227b14f4":
        raise RuntimeError(f"Stage-3 source tree mismatch: {stage3_source_hash}")

    copy_file(guide, package_root / "00_PRO_REVIEW_GUIDE.md")
    copy_file(prompt, package_root / "00_COPY_PASTE_PROMPT.md")
    copy_file(requirements, package_root / "original_requirements.md")
    copy_file(master, package_root / "master_delivery.md")

    copy_file(stage1, package_root / "02_LAYER_1_FORWARD_THEORY" / "forward_theory.md")

    layer2 = package_root / "03_LAYER_2_NUMERICAL_THEORY_AND_SOLVER"
    copy_file(stage2_theory, layer2 / "numerical_theory.md")
    copy_file(stage2_handoff, layer2 / "stage2_acceptance_record.md")
    copy_file(stage2_readme, layer2 / "layer2_overview.md")
    for name in ("README.md", "pyproject.toml", "requirements.txt", "run.py"):
        copy_file(stage2_root / name, layer2 / "solver" / name)
    copy_glob(
        stage2_root,
        layer2 / "solver",
        [
            "y_pendulum_forward/*.py",
            "tests/*.py",
            "configs/*.json",
        ],
        excluded_parts={"__pycache__"},
    )
    selected_stage2_validation = [
        "validation/delivery_root.json",
        "validation/artifact_manifest.json",
        "validation/cable_convergence.json",
        "validation/torus_convergence.json",
        "validation/cable_convergence_failed_prefine_gate_2026-08-21.json",
        "validation/reference_cable/config.snapshot.json",
        "validation/reference_cable/result.json",
        "validation/reference_cable/series.csv",
        "validation/reference_torus/config.snapshot.json",
        "validation/reference_torus/result.json",
        "validation/reference_torus/series.csv",
        "validation/reference_torus/trajectory.npz",
        "validation/reference_ensemble_torus/ensemble.snapshot.json",
        "validation/reference_ensemble_torus/manifest.json",
    ]
    for relative in selected_stage2_validation:
        copy_file(stage2_root / relative, layer2 / "solver" / relative)

    layer3 = package_root / "04_LAYER_3_HIGH_FIDELITY"
    copy_file(stage3_theory, layer3 / "hf_theory_and_program.md")
    copy_file(stage3_handoff, layer3 / "stage3_handoff.md")
    for name in (
        "README.md",
        "pyproject.toml",
        "CHANGELOG.md",
        "CITATION.cff",
        "LICENSE",
    ):
        copy_file(stage3_root / name, layer3 / "simulator" / name)
    copy_glob(
        stage3_root,
        layer3 / "simulator",
        [
            "src/**/*.py",
            "tests/**/*.py",
            "configs/**/*.yaml",
            "configs/**/*.yml",
            "configs/**/*.json",
            "scripts/*.py",
            "docs/**/*.md",
        ],
        excluded_parts={"__pycache__"},
    )

    target_source = stage3_root / "validation" / "target_hf_0p12_raw"
    target_dest = layer3 / "target_result_evidence"
    copy_glob(
        target_source,
        target_dest,
        ["*.json", "*.yaml", "*.csv", "*.md", "plots/*.png"],
    )
    performance_source = stage3_root / "validation" / "performance"
    copy_glob(
        performance_source,
        layer3 / "performance_evidence",
        ["*.json", "*.txt"],
    )
    copy_file(
        stage3_root / "validation" / "representative_hf_sensitivity.json",
        layer3 / "representative_hf_sensitivity.json",
    )
    copy_file(
        stage3_root / "validation" / "environment_inventory.json",
        layer3 / "environment_inventory.json",
    )

    h5_source = target_source / "result.h5"
    h5_inventory = hdf5_inventory(
        h5_source, target_dest / "HF_H5_DATASET_INVENTORY.json"
    )
    downsample = downsample_hf(
        h5_source, target_dest / "HF_TARGET_DOWNSAMPLED_301.csv"
    )

    layer4 = package_root / "05_LAYER_4_STRUCTURAL_THEORY"
    copy_file(stage4_theory, layer4 / "structural_theory.md")
    copy_file(stage4_handoff, layer4 / "stage4_handoff.md")
    copy_glob(
        project_root / "结构性理论",
        layer4,
        ["analysis/*.py", "results/*.json", "results/*.csv", "figures/*.png"],
        excluded_parts={"__pycache__"},
    )

    all_in_one = build_all_in_one(
        project_root,
        package_root,
        guide,
        requirements,
        master,
        stage1,
        stage2_theory,
        stage2_handoff,
        stage3_theory,
        stage3_handoff,
        stage4_theory,
        stage4_handoff,
        stage2_root,
        stage3_root,
    )

    excluded_paths = [
        h5_source,
        stage2_root / "validation" / "reference_cable" / "trajectory.npz",
        stage3_root / "validation" / "representative_hf_sensitivity_series.npz",
        target_source / "observer_output.npz",
        *sorted(performance_source.glob("*.npz")),
    ]
    exclusions = write_exclusions(project_root, package_root, excluded_paths)

    identities = {
        "stage1_forward_theory_sha256": sha256_file(stage1),
        "stage2_numerical_theory_sha256": sha256_file(stage2_theory),
        "stage2_delivery_root_sha256": sha256_file(
            stage2_root / "validation" / "delivery_root.json"
        ),
        "stage3_theory_sha256": sha256_file(stage3_theory),
        "stage3_handoff_sha256": sha256_file(stage3_handoff),
        "stage3_source_tree_sha256": stage3_source_hash,
        "stage4_theory_sha256": sha256_file(stage4_theory),
        "stage4_analysis_script_sha256": sha256_file(
            project_root / "结构性理论" / "analysis" / "torus_structure_analysis.py"
        ),
        "stage4_results_sha256": sha256_file(
            project_root
            / "结构性理论"
            / "results"
            / "structural_analysis_results.json"
        ),
        "hf_target_h5_sha256": h5_inventory["source_sha256"],
    }
    build_report = {
        "schema": "YPS-PRO-REVIEW-PACKAGE-BUILD-REPORT-1.0",
        "package_name": PACKAGE_NAME,
        "frozen_identities_verified": True,
        "hdf5_dataset_count": h5_inventory["dataset_count"],
        "hdf5_all_numeric_datasets_finite": all(
            item.get("nonfinite_count", 0) == 0
            for item in h5_inventory["datasets"]
            if "nonfinite_count" in item
        ),
        "downsample": downsample,
        "excluded_binary_count": len(exclusions),
        "all_in_one_size_bytes": all_in_one.stat().st_size,
        "scope": "personal scientific-computing prototype",
    }
    write_json(package_root / "07_EVIDENCE" / "PACKAGE_BUILD_REPORT.json", build_report)

    manifest = build_manifest(package_root, identities)
    deterministic_zip(package_root, zip_path)
    zip_verification = verify_zip(package_root, zip_path)
    checksum_path = output_parent / f"{PACKAGE_NAME}.zip.sha256"
    checksum_path.write_text(
        f"{zip_verification['zip_sha256']}  {zip_path.name}\n", encoding="utf-8"
    )
    final_report = {
        "package_directory": str(package_root),
        "zip_path": str(zip_path),
        "zip_checksum_path": str(checksum_path),
        "manifest_file_count": manifest["file_count_excluding_manifest_and_sums"],
        "package_member_count": zip_verification["file_count"],
        "zip_size_bytes": zip_verification["zip_size_bytes"],
        "zip_sha256": zip_verification["zip_sha256"],
        "zip_crc_test": zip_verification["crc_test"],
        "all_member_hashes_match": zip_verification["all_member_hashes_match"],
        "all_in_one_path": str(all_in_one),
        "all_in_one_size_bytes": all_in_one.stat().st_size,
    }
    write_json(output_parent / f"{PACKAGE_NAME}_BUILD_RESULT.json", final_report)
    print(json.dumps(final_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

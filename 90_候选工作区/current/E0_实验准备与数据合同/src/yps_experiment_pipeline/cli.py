"""Command-line entry point for E0 synthetic-only readiness checks."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

import numpy as np

from .camera import project_points, triangulate_two_view
from .comparison import compare_scalar
from .contracts import STAGE_RELATIVE, validate_all_templates, validate_document
from .detections import triangulate_markers_with_covariance
from .forward_adapter import cable_compatibility, formal_identity, torus_compatibility
from .observables import estimate_damped_mode
from .synchronization import estimate_event_offset


def discover_repository_root() -> Path:
    """Find the repository without assuming the command's working directory."""
    starts = (Path.cwd().resolve(), Path(__file__).resolve())
    for start in starts:
        for candidate in (start, *start.parents):
            if (candidate / "02_模拟程序/01_前向预测数值求解器").is_dir() and (
                candidate / "90_候选工作区"
            ).is_dir():
                return candidate
    raise RuntimeError("unable to discover the IYPT-5 repository root")


def _synthetic_camera(center_x: float) -> dict:
    return {
        "R_c": np.eye(3).tolist(),
        "c_c": [center_x, 0.0, 0.0],
        "f_x": 900.0,
        "f_y": 910.0,
        "c_x": 640.0,
        "c_y": 360.0,
        "k1": -0.01,
        "k2": 0.001,
        "k3": 0.0,
        "p1": 0.0002,
        "p2": -0.0001,
        "Omega_cal": [-0.8, 0.8, -0.8, 0.8],
    }


def synthetic_self_test(repository_root: Path) -> dict:
    stage_root = repository_root.resolve() / STAGE_RELATIVE
    schema_root = stage_root / "schemas"
    template_root = stage_root / "templates"
    validate_all_templates(schema_root=schema_root, template_root=template_root)
    camera_a, camera_b = _synthetic_camera(-0.25), _synthetic_camera(0.25)
    time = np.linspace(0.0, 12.0, 1201)
    points = np.column_stack(
        (
            0.08 * np.sin(1.7 * time),
            0.06 * np.sin(1.2 * time + 0.3),
            2.0 + 0.03 * np.cos(1.2 * time),
        )
    )
    pixels_a, valid_a, _ = project_points(points, camera_a)
    pixels_b, valid_b, _ = project_points(points, camera_b)
    reconstructed, valid = triangulate_two_view(
        pixels_a,
        pixels_b,
        camera_a,
        camera_b,
        valid_a=valid_a,
        valid_b=valid_b,
    )
    reconstruction_error = float(
        np.max(np.linalg.norm(reconstructed[valid] - points[valid], axis=1))
    )
    if reconstruction_error > 1e-8:
        raise RuntimeError(f"synthetic stereo reconstruction error: {reconstruction_error}")
    stereo_pixels = np.stack((pixels_a, pixels_b), axis=1)[:, :, None, :]
    stereo_valid = np.stack((valid_a, valid_b), axis=1)[:, :, None]
    pixel_covariance = np.broadcast_to(0.04 * np.eye(2), (time.size, 2, 1, 2, 2)).copy()
    covariance_points, covariance_3d, covariance_valid = triangulate_markers_with_covariance(
        stereo_pixels,
        pixel_covariance,
        stereo_valid,
        camera_a,
        camera_b,
    )
    if not np.all(covariance_valid):
        raise RuntimeError("synthetic covariance-aware stereo reconstruction failed")
    covariance_reconstruction_error = float(
        np.max(np.linalg.norm(covariance_points[:, 0] - points, axis=1))
    )
    covariance_min_eigenvalue = float(np.min(np.linalg.eigvalsh(covariance_3d)))
    if covariance_reconstruction_error > 1e-8 or covariance_min_eigenvalue < -1e-12:
        raise RuntimeError("synthetic 2D-to-3D covariance propagation failed")

    fast_truth, slow_truth = 4.0, 3.0
    fast_signal = 0.15 * np.exp(-0.025 * time) * np.cos(fast_truth * time + 0.2)
    slow_signal = 0.11 * np.exp(-0.015 * time) * np.cos(slow_truth * time - 0.4)
    fast = estimate_damped_mode(time, fast_signal)
    slow = estimate_damped_mode(time, slow_signal)
    if abs(fast.omega_rad_s - fast_truth) > 2e-4 or abs(slow.omega_rad_s - slow_truth) > 2e-4:
        raise RuntimeError("synthetic modal-frequency recovery failed")

    sync = estimate_event_offset(
        np.array([0.5, 2.0, 5.0, 9.0]),
        np.array([0.508, 2.008, 5.008, 9.008]),
    )
    if abs(float(sync["offset_s"]) - 0.008) > 1e-12:
        raise RuntimeError("synthetic synchronization recovery failed")

    comparison = compare_scalar(
        data_origin="SYNTHETIC_REAL_SHAPE_FIXTURE",
        observable="omega_fast_rad_s",
        experimental_value=fast.omega_rad_s,
        model_value=fast_truth,
        experimental_uncertainty=1e-3,
        model_input_uncertainty=1e-3,
        numerical_uncertainty=1e-6,
    )
    validate_document("comparison_result.schema.json", comparison, schema_root=schema_root)
    torus_status = torus_compatibility(
        {
            "torus_evidence": {
                "geometry_embedding": {
                    "decision": True,
                    "evidence_sha256": sha256(b"synthetic-geometry").hexdigest(),
                },
                "initial_state_mapping": {
                    "decision": True,
                    "evidence_sha256": sha256(b"synthetic-initial-state").hexdigest(),
                },
                "domain_window": {
                    "decision": True,
                    "evidence_sha256": sha256(b"synthetic-domain-window").hexdigest(),
                },
                "mapping_residual": 0.2,
                "mapping_standard_uncertainty": 0.5,
            }
        }
    )
    cable_status, _ = cable_compatibility(
        {"purpose": "EXPERIMENT_COMPARISON", "parameter_bindings": []}
    )
    identity = formal_identity(repository_root)
    return {
        "status": "E0R_SYNTHETIC_REAL_SHAPE_SELF_TEST_PASS__NOT_EXPERIMENT_EVIDENCE",
        "data_origin": "SYNTHETIC_REAL_SHAPE_FIXTURE",
        "stereo_max_error_m": reconstruction_error,
        "covariance_stereo_max_error_m": covariance_reconstruction_error,
        "covariance_min_eigenvalue_m2": covariance_min_eigenvalue,
        "omega_fast_error_rad_s": abs(fast.omega_rad_s - fast_truth),
        "omega_slow_error_rad_s": abs(slow.omega_rad_s - slow_truth),
        "sync_offset_error_s": abs(float(sync["offset_s"]) - 0.008),
        "comparison_status": comparison["status"],
        "torus_adapter_status": torus_status,
        "cable_adapter_status": cable_status,
        "formal_identity": identity,
        "claim_ceiling": "IMPLEMENTATION_AND_SYNTHETIC_REAL_SHAPE_FIXTURE_ONLY",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    self_test = subparsers.add_parser("self-test", help="run the E0 synthetic-only closure test")
    self_test.add_argument("--synthetic-only", action="store_true", required=True)
    self_test.add_argument("--repository-root", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "self-test":
        repository_root = args.repository_root or discover_repository_root()
        result = synthetic_self_test(repository_root)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    raise AssertionError("unreachable")

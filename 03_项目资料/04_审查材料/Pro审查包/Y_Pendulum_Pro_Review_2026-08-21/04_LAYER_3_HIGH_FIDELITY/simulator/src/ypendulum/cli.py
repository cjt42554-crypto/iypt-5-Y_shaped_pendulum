"""Command-line interface for YP-FPSim."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ypendulum.analysis import automatic_scale_diagnostics
from ypendulum.analysis.ablation import run_ablation
from ypendulum.analysis.sweep import run_sweep
from ypendulum.analysis.uncertainty import run_uncertainty
from ypendulum.api import (
    analyze_linear_modes,
    analyze_run,
    compare_experiment,
    compare_runs,
    diagnose_config,
    run_convergence_study,
    simulate,
)
from ypendulum.calibration import (
    build_tabulated_tension_extension,
    compare_envelope_models,
    fit_axial_stiffness,
)
from ypendulum.config import load_config, resolved_config_dict
from ypendulum.hf import (
    read_hf_certificate_sidecar,
    run_hf_independence_study,
    run_hf_validation,
)
from ypendulum.io import json_safe, sha256_file, write_json
from ypendulum.models.full_cable import FullCableModel
from ypendulum.solvers.static import solve_static_equilibrium
from ypendulum.unified import load_unified_case, run_unified_case
from ypendulum.version import __version__


def _print(payload) -> None:
    print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False, allow_nan=False))


def cmd_validate_config(args) -> int:
    cfg = load_config(args.config)
    model = FullCableModel(cfg) if cfg.run.mode == "full" else None
    payload = {
        "valid": True,
        "run_name": cfg.run.name,
        "mode": cfg.run.mode,
        "claim_level": cfg.run.claim_level,
        "resolved": resolved_config_dict(cfg),
        "scale_diagnostics": None if model is None else automatic_scale_diagnostics(cfg, model),
    }
    _print(payload)
    return 0


def cmd_diagnose(args) -> int:
    report = diagnose_config(
        args.config,
        solve_equilibrium=not args.skip_equilibrium,
        write_output=args.output,
    )
    _print(report)
    return 0 if report["claim_readiness"]["requested_claim_supported"] else 2


def cmd_equilibrate(args) -> int:
    cfg = load_config(args.config)
    if cfg.run.mode != "full":
        raise ValueError("equilibrate is defined only for full H1 configurations.")
    model = FullCableModel(cfg)
    eq = solve_static_equilibrium(cfg, model)
    output = Path(args.output or (Path(cfg.run.output_directory) / "static_equilibrium.npz"))
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, positions=eq.positions, velocities=eq.velocities)
    meta = {
        "converged": eq.converged,
        "force_residual_max_N": eq.force_residual_max,
        "iterations": eq.iterations,
        "metadata": eq.metadata,
        "output": str(output),
    }
    write_json(output.with_suffix(".json"), meta)
    _print(meta)
    return 0


def cmd_simulate(args) -> int:
    cfg = load_config(args.config)
    hf_validation_spec = getattr(args, "hf_validation_spec", None)
    result = simulate(
        cfg,
        hf_validation_spec=hf_validation_spec,
        hf_checkpoint_path=getattr(args, "hf_checkpoint", None),
        hf_resume_checkpoint=bool(getattr(args, "resume_hf_checkpoint", False)),
    )
    physical = getattr(result, "physical_status", None)
    numerical = getattr(result, "numerical_status", None)
    certificate_summary = None
    if physical is None and numerical is None:
        status = "success"
        return_code = 0
    elif (
        cfg.run.mode == "high_fidelity"
        and physical == "UNDETERMINED"
        and numerical == "SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED"
    ):
        if hf_validation_spec is None:
            status = "raw_scientific_result_guard_uncertified"
            return_code = 0
        else:
            sidecar = read_hf_certificate_sidecar(cfg.run.output_directory)
            certificate = sidecar["certificate"]
            certificate_summary = {
                "schema_version": certificate["schema_version"],
                "passed": certificate["passed"],
                "certification_level": certificate["certification_level"],
                "certified_status_pair": certificate["certified_status_pair"],
                "certificate_sha256": certificate["certificate_sha256"],
            }
            if certificate["passed"] is True:
                read_hf_certificate_sidecar(
                    cfg.run.output_directory, require_full=True
                )
                status = "independently_certified"
                return_code = 0
            else:
                status = "undetermined"
                return_code = 2
    elif physical == "COMPLETED" and numerical == "SUCCESS_SINGLE_RUN":
        status = "success"
        return_code = 0
    elif physical == "OUT_OF_SCOPE" and numerical == "SUCCESS_EVENT":
        status = "out_of_scope_prefix"
        return_code = 3
    else:
        status = "undetermined"
        return_code = 2
    _print({
        "status": status,
        "run_directory": cfg.run.output_directory,
        "model": getattr(result, "model_id", getattr(result, "model_name", "A0")),
        "physical_status": physical,
        "numerical_status": numerical,
        "independent_certificate": certificate_summary,
    })
    return return_code


def cmd_analyze(args) -> int:
    _print(analyze_run(args.run_directory))
    return 0


def cmd_modes(args) -> int:
    report = analyze_linear_modes(args.config, count=args.count)
    if args.output:
        write_json(Path(args.output), report)
    _print(report)
    return 0


def cmd_compare(args) -> int:
    _print(compare_runs(args.run_a, args.run_b))
    return 0


def cmd_compare_experiment(args) -> int:
    report = compare_experiment(
        args.run_directory,
        args.experiment_csv,
        estimate_time_shift=args.estimate_time_shift,
        maximum_time_shift_s=args.maximum_time_shift,
        estimate_translation=args.estimate_translation,
        estimate_planar_rotation=args.estimate_planar_rotation,
        output_directory=args.output_directory,
    )
    _print(report)
    return 0


def cmd_converge(args) -> int:
    _print(run_convergence_study(args.config))
    return 0


def _commit_hf_study_delivery(args, runner, *, delivery_kind: str) -> int:
    target = Path(args.output).expanduser().resolve()
    if target.exists():
        raise FileExistsError(
            f"HF validation delivery directory already exists: {target}."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent)
    )
    try:
        report = runner(staging / "candidates")
        report_path = staging / "report.json"
        report_path.write_text(
            json.dumps(
                json_safe(report),
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        files = [
            {
                "path": str(path.relative_to(staging)),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(staging.rglob("*"))
            if path.is_file()
        ]
        manifest_path = staging / "artifact_manifest.json"
        write_json(
            manifest_path,
            {
                "schema_version": "YPS-HF-VALIDATION-DELIVERY-MANIFEST-1.0",
                "delivery_kind": delivery_kind,
                "files": files,
            },
        )
        write_json(
            staging / "delivery_root.json",
            {
                "schema_version": "YPS-HF-VALIDATION-DELIVERY-ROOT-1.0",
                "delivery_kind": delivery_kind,
                "qualification": report["qualification"],
                "passed": report["passed"],
                "base_config_sha256": report["base_config_sha256"],
                "validation_spec_sha256": report["validation_spec_sha256"],
                **(
                    {
                        "independence_spec_sha256": report[
                            "independence_spec_sha256"
                        ]
                    }
                    if "independence_spec_sha256" in report
                    else {}
                ),
                "source_hash_start_sha256": report[
                    "source_hash_start_sha256"
                ],
                "source_hash_end_sha256": report["source_hash_end_sha256"],
                "runtime_stable_during_study": report[
                    "runtime_stable_during_study"
                ],
                "input_files_stable_during_study": report[
                    "input_files_stable_during_study"
                ],
                "artifact_manifest_sha256": sha256_file(manifest_path),
                "artifact_manifest_bytes": manifest_path.stat().st_size,
                "units": "SI",
            },
        )
        os.replace(staging, target)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    _print(
        {
            "qualification": report["qualification"],
            "passed": report["passed"],
            "delivery_directory": str(target),
            "report": str(target / "report.json"),
            "base_config_sha256": report["base_config_sha256"],
            "validation_spec_sha256": report["validation_spec_sha256"],
            "source_hash_start_sha256": report["source_hash_start_sha256"],
            "source_hash_end_sha256": report["source_hash_end_sha256"],
        }
    )
    return 0 if report["passed"] else 2


def cmd_hf_validate(args) -> int:
    return _commit_hf_study_delivery(
        args,
        lambda artifacts: run_hf_validation(
            args.config,
            args.spec,
            artifact_directory=artifacts,
        ),
        delivery_kind="convergence_and_cross_solver",
    )


def cmd_hf_independence(args) -> int:
    return _commit_hf_study_delivery(
        args,
        lambda artifacts: run_hf_independence_study(
            args.config,
            args.validation_spec,
            args.independence_spec,
            artifact_directory=artifacts,
        ),
        delivery_kind="controlled_physics_limit",
    )


def cmd_unified_audit(args) -> int:
    case = load_unified_case(args.case)
    _print(
        {
            "schema_version": "YPS-UNIFIED-AUDIT-RESULT-1.0",
            "case_sha256": case.case_hash_sha256,
            "problem_id": case.payload["problem_id"],
            "shared_input_audit": case.shared_input_audit,
        }
    )
    return 0


def cmd_unified_run(args) -> int:
    report = run_unified_case(
        args.case,
        backend=args.backend,
        output_directory=args.output,
    )
    _print(report)
    return 0 if report.get("status") == "COMPLETE" else 3


def cmd_ablate(args) -> int:
    _print(run_ablation(args.config))
    return 0


def cmd_sweep(args) -> int:
    _print(run_sweep(args.sweep_yaml))
    return 0


def cmd_uncertainty(args) -> int:
    spec_path = Path(args.spec)
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    config_path = (spec_path.parent / spec["base_config"]).resolve()
    report = run_uncertainty(
        config_path,
        spec["distributions"],
        samples=args.samples or int(spec.get("samples", 100)),
        workers=args.workers,
    )
    _print(report)
    return 0


def cmd_calibrate_axial(args) -> int:
    frame = pd.read_csv(args.csv)
    required = {args.force_column, args.extension_column}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Axial calibration CSV is missing columns: {sorted(missing)}")
    force = frame[args.force_column].to_numpy(dtype=float)
    extension = frame[args.extension_column].to_numpy(dtype=float)
    calibration = fit_axial_stiffness(force, extension, args.rest_length)
    payload = {
        "calibration_type": "independent_axial_loading",
        "source_csv": str(Path(args.csv)),
        "source_csv_sha256": sha256_file(args.csv),
        "force_column": args.force_column,
        "extension_column": args.extension_column,
        **calibration.as_dict(),
        "recommended_config": {
            "young_modulus_note": "The cable model requires E; divide fitted EA by independently measured cross-sectional area.",
            "ea_N": calibration.ea,
            "source": "calibrated_independent",
        },
    }
    if args.table_output:
        curve = build_tabulated_tension_extension(force, extension, args.rest_length)
        table = pd.DataFrame(
            {
                "extension": curve["extension_m"],
                "tension": curve["tension_n"],
            }
        )
        target = Path(args.table_output)
        target.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(target, index=False)
        payload["tabulated_curve"] = str(target)
        payload["tabulated_calibration_length_m"] = curve["calibration_length_m"]
    if args.output:
        write_json(Path(args.output), payload)
    _print(payload)
    return 0


def cmd_calibrate_damping(args) -> int:
    frame = pd.read_csv(args.csv)
    required = {args.time_column, args.amplitude_column}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Damping calibration CSV is missing columns: {sorted(missing)}")
    report = compare_envelope_models(
        frame[args.time_column].to_numpy(dtype=float),
        frame[args.amplitude_column].to_numpy(dtype=float),
    )
    payload = {
        "calibration_type": "independent_modal_envelope_diagnostic",
        "source_csv": str(Path(args.csv)),
        "source_csv_sha256": sha256_file(args.csv),
        "time_column": args.time_column,
        "amplitude_column": args.amplitude_column,
        **report,
    }
    if args.output:
        write_json(Path(args.output), payload)
    _print(payload)
    return 0


def cmd_validate_suite(args) -> int:
    from ypendulum.validation_suite import run_validation_suite

    report = run_validation_suite(fast=args.fast, output_directory=args.output_directory)
    _print(report)
    return 0 if report["passed"] else 2


def cmd_ui(_args) -> int:
    try:
        from streamlit.web import cli as stcli
    except ImportError as exc:
        raise RuntimeError("Streamlit is not installed. Install ypendulum[ui].") from exc
    app_path = Path(__file__).with_name("ui") / "app.py"
    sys.argv = ["streamlit", "run", str(app_path)]
    return int(stcli.main())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ypendulum", description="YP-FPSim first-principles Y-pendulum simulator")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate-config")
    p.add_argument("config")
    p.set_defaults(func=cmd_validate_config)
    p = sub.add_parser("diagnose")
    p.add_argument("config")
    p.add_argument("--skip-equilibrium", action="store_true")
    p.add_argument("--output")
    p.set_defaults(func=cmd_diagnose)
    p = sub.add_parser("equilibrate")
    p.add_argument("config")
    p.add_argument("--output")
    p.set_defaults(func=cmd_equilibrate)
    p = sub.add_parser("simulate")
    p.add_argument("config")
    p.add_argument(
        "--hf-validation-spec",
        help=(
            "Frozen YPS-HF-VALIDATION-1.0 file. Without it a raw HF run "
            "is retained as a personal-research result without the optional "
            "full independent certificate."
        ),
    )
    p.add_argument(
        "--hf-checkpoint",
        help="Integration checkpoint path; defaults beside the output directory.",
    )
    p.add_argument(
        "--resume-hf-checkpoint",
        action="store_true",
        help="Reuse a matching completed integration and rerun only HF post-processing.",
    )
    p.set_defaults(func=cmd_simulate)
    p = sub.add_parser("analyze")
    p.add_argument("run_directory")
    p.set_defaults(func=cmd_analyze)
    p = sub.add_parser("modes")
    p.add_argument("config")
    p.add_argument("--count", type=int, default=2)
    p.add_argument("--output")
    p.set_defaults(func=cmd_modes)
    p = sub.add_parser("compare")
    p.add_argument("run_a")
    p.add_argument("run_b")
    p.set_defaults(func=cmd_compare)
    p = sub.add_parser("compare-experiment")
    p.add_argument("run_directory")
    p.add_argument("experiment_csv")
    p.add_argument("--estimate-time-shift", action="store_true")
    p.add_argument("--maximum-time-shift", type=float, default=0.0, metavar="SECONDS")
    p.add_argument("--estimate-translation", action="store_true")
    p.add_argument("--estimate-planar-rotation", action="store_true")
    p.add_argument("--output-directory")
    p.set_defaults(func=cmd_compare_experiment)
    p = sub.add_parser("converge")
    p.add_argument("config")
    p.set_defaults(func=cmd_converge)
    p = sub.add_parser("hf-validate")
    p.add_argument("config")
    p.add_argument("spec")
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_hf_validate)
    p = sub.add_parser("hf-independence")
    p.add_argument("config")
    p.add_argument("validation_spec")
    p.add_argument("independence_spec")
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_hf_independence)
    p = sub.add_parser("unified-audit")
    p.add_argument("case")
    p.set_defaults(func=cmd_unified_audit)
    p = sub.add_parser("unified-run")
    p.add_argument("case")
    p.add_argument(
        "--backend",
        choices=("forward", "high_fidelity", "both"),
        default="both",
    )
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_unified_run)
    p = sub.add_parser("ablate")
    p.add_argument("config")
    p.set_defaults(func=cmd_ablate)
    p = sub.add_parser("sweep")
    p.add_argument("sweep_yaml")
    p.set_defaults(func=cmd_sweep)
    p = sub.add_parser("uncertainty")
    p.add_argument("spec")
    p.add_argument("--samples", type=int)
    p.add_argument("--workers", type=int, default=1)
    p.set_defaults(func=cmd_uncertainty)
    p = sub.add_parser("calibrate-axial")
    p.add_argument("csv")
    p.add_argument("--rest-length", type=float, required=True, metavar="METRES")
    p.add_argument("--force-column", default="force_N")
    p.add_argument("--extension-column", default="extension_m")
    p.add_argument("--table-output")
    p.add_argument("--output")
    p.set_defaults(func=cmd_calibrate_axial)
    p = sub.add_parser("calibrate-damping")
    p.add_argument("csv")
    p.add_argument("--time-column", default="time_s")
    p.add_argument("--amplitude-column", default="amplitude_m")
    p.add_argument("--output")
    p.set_defaults(func=cmd_calibrate_damping)
    p = sub.add_parser("validate-suite")
    p.add_argument("--fast", action="store_true")
    p.add_argument("--output-directory", default="validation/generated")
    p.set_defaults(func=cmd_validate_suite)
    p = sub.add_parser("ui")
    p.set_defaults(func=cmd_ui)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(json.dumps({"status": "error", "type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

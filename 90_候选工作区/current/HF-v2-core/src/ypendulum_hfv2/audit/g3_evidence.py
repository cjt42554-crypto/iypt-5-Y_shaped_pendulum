"""Deterministic evidence builder for the frozen HF-v2 G3 static-contact gate."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import scipy

from ypendulum_hfv2 import CONTACT_MODEL_ID, MODEL_ID
from ypendulum_hfv2.audit.contact import (
    ContactKKTThresholds,
    audit_contact_kkt,
    contact_action_reaction_audit,
    gap_jacobian_samples,
    independent_contact_hessian_audit,
)
from ypendulum_hfv2.audit.dependency import audit_g2_dependencies
from ypendulum_hfv2.audit.g2r_evidence import build_g2r_evidence
from ypendulum_hfv2.audit.g3_cases import build_target_contact_case
from ypendulum_hfv2.audit.statics import strict_decrease_interval
from ypendulum_hfv2.contact import ContactGeometryError
from ypendulum_hfv2.statics.contact_assembly import ContactStaticEvaluation
from ypendulum_hfv2.statics.contact_solver import (
    ContactSolverSettings,
    solve_contact_seed,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _run_pytest(root: Path, paths: tuple[str, ...]) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *paths],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr
    matches = re.findall(r"(\d+) passed", combined)
    document: dict[str, Any] = {
        "command": [sys.executable, "-m", "pytest", "-q", *paths],
        "test_paths": list(paths),
        "return_code": result.returncode,
        "passed_test_count": int(matches[-1]) if matches else 0,
        "status": "PASS" if result.returncode == 0 else "FAIL",
    }
    if result.returncode != 0:
        document["failure_output"] = combined
    return document


def _runtime_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    expected = manifest["runtime"]
    pytest_output = subprocess.run(
        [sys.executable, "-m", "pytest", "--version"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    ruff_output = subprocess.run(
        ["ruff", "--version"], capture_output=True, text=True, check=True
    ).stdout
    pytest_version = re.search(r"pytest\s+([0-9.]+)", pytest_output)
    ruff_version = re.search(r"ruff\s+([0-9.]+)", ruff_output)
    if pytest_version is None or ruff_version is None:
        raise ValueError("Frozen validation-tool versions could not be parsed.")
    actual = {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "pytest_version": pytest_version.group(1),
        "ruff_version": ruff_version.group(1),
    }
    checks = {
        key: actual[key] == expected[key]
        for key in (
            "python_implementation",
            "python_version",
            "numpy_version",
            "scipy_version",
        )
    }
    checks["pytest_minimum"] = tuple(
        int(value) for value in actual["pytest_version"].split(".")[:2]
    ) >= tuple(int(value) for value in str(expected["pytest_minimum"]).split(".")[:2])
    checks["ruff_version"] = actual["ruff_version"] == expected["ruff_version"]
    return {
        "expected": expected,
        "actual": actual,
        "exact_version_checks": checks,
        "platform": platform.platform(),
        "byteorder": sys.byteorder,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def _contract_binding(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    repository_root = root.parents[2]
    formal_contract_path = root / "contracts" / manifest["formal_registration_contract"]
    formal_contract = _load_json(formal_contract_path)
    formal_sources: dict[str, Any] = {}
    for name, contract in formal_contract["formal_sources"].items():
        source_path = repository_root / contract["path"]
        actual_sha = _sha256(source_path)
        blob = subprocess.run(
            ["git", "hash-object", str(source_path)],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        formal_sources[name] = {
            "path": contract["path"],
            "expected_sha256": contract["sha256"],
            "actual_sha256": actual_sha,
            "expected_git_blob": contract["git_blob"],
            "actual_git_blob": blob,
            "status": (
                "PASS"
                if actual_sha == contract["sha256"] and blob == contract["git_blob"]
                else "FAIL"
            ),
        }
    prefreeze = str(manifest["prefreeze_source_commit"])
    commit_check = subprocess.run(
        ["git", "cat-file", "-e", f"{prefreeze}^{{commit}}"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )
    amendment_path = root / "contracts" / "p3_protocol_amendment_a1.json"
    documents = {
        "acceptance_manifest": {
            "path": "contracts/p3_acceptance_manifest.json",
            "sha256": _sha256(root / "contracts" / "p3_acceptance_manifest.json"),
        },
        "formal_registration": {
            "path": formal_contract_path.relative_to(root).as_posix(),
            "sha256": _sha256(formal_contract_path),
        },
        "protocol": {
            "path": "contracts/P3_FROZEN_PROTOCOL.md",
            "sha256": _sha256(root / "contracts" / "P3_FROZEN_PROTOCOL.md"),
        },
        "amendment_a1": {
            "path": amendment_path.relative_to(root).as_posix(),
            "sha256": _sha256(amendment_path),
        },
        "model_identity": {
            "path": "contracts/model_identity_0_3_contact.json",
            "sha256": _sha256(root / "contracts" / "model_identity_0_3_contact.json"),
        },
    }
    passed = commit_check.returncode == 0 and all(
        source["status"] == "PASS" for source in formal_sources.values()
    )
    return {
        "prefreeze_source_commit": prefreeze,
        "prefreeze_commit_exists": commit_check.returncode == 0,
        "target_results_observed_before_freeze": manifest[
            "contact_target_results_observed_before_freeze"
        ],
        "dynamic_contact_results_observed_before_freeze": manifest[
            "dynamic_contact_results_observed_before_freeze"
        ],
        "documents": documents,
        "formal_sources": formal_sources,
        "status": "PASS" if passed else "FAIL",
    }


def _architecture_metrics(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    audit = audit_g2_dependencies(
        root / "src" / "ypendulum_hfv2",
        root / "contracts" / manifest["architecture"]["module_manifest"],
    )
    line_limit = int(manifest["architecture"]["source_lines_per_module_max_exclusive"])
    line_counts = {
        relative: len(
            (root / "src" / "ypendulum_hfv2" / relative).read_text(encoding="utf-8").splitlines()
        )
        for relative in audit.discovered_files
    }
    oversized = {path: count for path, count in line_counts.items() if count >= line_limit}
    passed = audit.passed and not oversized
    return {
        "module_manifest": manifest["architecture"]["module_manifest"],
        "discovered_file_count": len(audit.discovered_files),
        "unclassified_files": list(audit.unclassified_files),
        "missing_manifest_files": list(audit.missing_manifest_files),
        "dependency_violations": [
            {
                "source_path": item.source_path,
                "source_classification": item.source_classification,
                "imported_name": item.imported_name,
                "target_classification": item.target_classification,
                "reason": item.reason,
            }
            for item in audit.dependency_violations
        ],
        "path_classification_violations": list(audit.path_classification_violations),
        "production_try_statement_count": audit.production_try_statement_count,
        "production_random_call_count": audit.production_random_call_count,
        "line_limit_exclusive": line_limit,
        "maximum_source_line_count": max(line_counts.values()),
        "oversized_modules": oversized,
        "status": "PASS" if passed else "FAIL",
    }


def _kkt_thresholds(manifest: dict[str, Any]) -> ContactKKTThresholds:
    source = manifest["kkt"]
    return ContactKKTThresholds(
        **{name: source[name] for name in ContactKKTThresholds.__dataclass_fields__}
    )


def _validity_document(evaluation: ContactStaticEvaluation) -> dict[str, Any]:
    validity = evaluation.validity
    return {
        "bob_socket_material_extent_m": validity.bob_socket_material_extent_m,
        "bob_socket_radial_monotonicity_m2": validity.bob_socket_radial_monotonicity_m2,
        "bob_socket_cut_gap_m": validity.bob_socket_cut_gap_m,
        "junction_sockets": [
            {
                "registration_id": identity,
                "material_extent_m": extent,
                "projective_opening_margin": opening,
                "cut_gap_m": cut,
            }
            for identity, extent, opening, cut in validity.junction_socket_metrics
        ],
    }


def _witness_documents(evaluation: ContactStaticEvaluation) -> list[dict[str, Any]]:
    return [
        {
            "constraint_id": witness.constraint_id,
            "category": witness.category,
            "first_parameter": witness.first_parameter,
            "second_parameter": witness.second_parameter,
            "first_point_m": witness.first_point_m,
            "second_point_m": witness.second_point_m,
            "distance_m": witness.distance_m,
            "required_center_distance_m": witness.required_center_distance_m,
            "gap_m": witness.gap_m,
            "normal_second_to_first": witness.normal_second_to_first,
            "object_ids": witness.object_ids,
            "object_gap_gradients": witness.object_gap_gradients,
            "active_feature": witness.active_feature,
            "competing_minimizer_count": witness.competing_minimizer_count,
            "unit_interval_parameter_margin": witness.unit_interval_parameter_margin,
        }
        for witness in evaluation.witnesses
    ]


def _initial_seed_document(case: Any, seed: Any) -> dict[str, Any]:
    coordinates = case.assembly.coordinates_from_seed(seed)
    document: dict[str, Any] = {"coordinates": coordinates.values}
    try:
        evaluation = case.assembly.evaluate(coordinates)
    except ContactGeometryError as error:
        document.update(
            {
                "state_valid": False,
                "failure_type": type(error).__name__,
                "failure_message": str(error),
            }
        )
    else:
        document.update(
            {
                "state_valid": True,
                "minimum_gap_m": float(np.min(evaluation.gaps_m)),
                "gaps_m": evaluation.gaps_m,
                "validity": _validity_document(evaluation),
            }
        )
    return _jsonable(document)


def _completed_seed_metrics(
    case: Any,
    result: Any,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    evaluation = result.evaluation
    target = manifest["target_case"]
    thresholds = _kkt_thresholds(manifest)
    kkt = audit_contact_kkt(case.assembly, evaluation, thresholds)
    constraint_ids = evaluation.constraint_ids
    gap_active_ids = [constraint_ids[index] for index in kkt.active_indices]
    supported_ids = [constraint_ids[index] for index in kkt.supported_indices]
    samples = gap_jacobian_samples(
        case.assembly,
        result.coordinates,
        tuple(manifest["gap_jacobian_audit"]["relative_step_sequence"]),
    )
    sample_errors = tuple(sample.maximum_row_relative_error for sample in samples)
    decrease = strict_decrease_interval(
        sample_errors,
        int(manifest["gap_jacobian_audit"]["minimum_strict_decrease_steps"]),
    )
    action = contact_action_reaction_audit(evaluation, kkt.multipliers_N)
    second = manifest["second_order"]
    hessian = independent_contact_hessian_audit(
        case.assembly,
        result.coordinates,
        kkt.multipliers_N,
        kkt.active_indices,
        normalized_step=float(second["normalized_step"]),
        directional_step=float(second["directional_step"]),
        direction_count=int(second["direction_count"]),
        rank_relative_tolerance=float(manifest["kkt"]["active_constraint_rank_relative_tolerance"]),
    )
    expected_position = np.asarray(target["expected_bob_position_m"], dtype=float)
    position_error = float(
        np.linalg.norm(evaluation.base_evaluation.bob_position - expected_position)
    )
    expected_ids = tuple(target["expected_active_constraint_ids"])
    expected_multiplier = float(target["expected_each_multiplier_N"])
    supported_multipliers = kkt.multipliers_N[kkt.supported_indices]
    multiplier_error = (
        float(np.max(np.abs(supported_multipliers - expected_multiplier)))
        if supported_multipliers.size
        else float("inf")
    )
    supported_witnesses = [evaluation.witnesses[index] for index in kkt.supported_indices]
    witness_margin = (
        min(witness.unit_interval_parameter_margin for witness in supported_witnesses)
        if supported_witnesses
        else float("-inf")
    )
    minimum_eigenvalue = (
        float(np.min(hessian.projected_eigenvalues))
        if hessian.projected_eigenvalues.size
        else float("inf")
    )
    minimum_directional = (
        float(np.min(hessian.directional_curvatures))
        if hessian.directional_curvatures.size
        else float("-inf")
    )
    checks = {
        "finite": bool(
            np.all(np.isfinite(result.coordinates.values))
            and np.all(np.isfinite(evaluation.gaps_m))
            and np.all(np.isfinite(evaluation.gap_jacobian))
        ),
        "primal": kkt.primal_violation_m <= float(manifest["kkt"]["primal_penetration_max_m"]),
        "dual": kkt.dual_violation_N <= float(manifest["kkt"]["dual_negative_max_N"]),
        "stationarity": kkt.stationarity_residual_N <= kkt.stationarity_limit_N,
        "complementarity": kkt.complementarity_residual_N_m <= kkt.complementarity_limit_N_m,
        "gap_active_identity": tuple(gap_active_ids) == expected_ids,
        "supported_identity": tuple(supported_ids) == expected_ids,
        "gap_active_full_row_rank": kkt.active_constraint_rank
        == len(kkt.active_indices)
        == int(target["expected_active_rank"]),
        "supported_full_row_rank": kkt.supported_constraint_rank
        == len(kkt.supported_indices)
        == int(target["expected_active_rank"]),
        "position": position_error <= float(target["position_absolute_error_max_m"]),
        "multipliers": multiplier_error <= float(target["multiplier_absolute_error_max_N"]),
        "interior_witnesses": witness_margin
        >= float(target["interior_witness_parameter_margin_min"]),
        "gap_jacobian_final": samples[-1].maximum_row_relative_error
        <= float(manifest["gap_jacobian_audit"]["final_relative_error_max"]),
        "gap_jacobian_decrease": decrease is not None,
        "hessian_asymmetry": hessian.unsymmetrized_relative_asymmetry
        <= float(second["unsymmetrized_relative_asymmetry_max"]),
        "projected_hessian": minimum_eigenvalue
        >= float(second["minimum_projected_normalized_eigenvalue"]),
        "directional_curvature": minimum_directional
        >= float(second["minimum_directional_normalized_curvature"])
        and hessian.directional_curvatures.size == int(second["direction_count"]),
    }
    qualified = all(checks.values())
    return _jsonable(
        {
            "execution_status": "COMPLETED",
            "optimizer": {
                "success": result.optimizer_success,
                "success_used_as_acceptance_gate": False,
                "status": result.optimizer_status,
                "message": result.optimizer_message,
                "iterations": result.iterations,
                "function_evaluations": result.function_evaluations,
                "gradient_evaluations": result.gradient_evaluations,
            },
            "coordinates": result.coordinates.values,
            "bob_position_m": evaluation.base_evaluation.bob_position,
            "total_potential_J": evaluation.total_potential,
            "constraint_ids": constraint_ids,
            "gaps_m": evaluation.gaps_m,
            "gap_active_ids": gap_active_ids,
            "supported_ids": supported_ids,
            "witnesses": _witness_documents(evaluation),
            "validity": _validity_document(evaluation),
            "kkt": {
                "independent_nnls": True,
                "optimizer_multipliers_used": False,
                "audit_passed": kkt.passed,
                "active_indices": kkt.active_indices,
                "supported_indices": kkt.supported_indices,
                "active_constraint_rank": kkt.active_constraint_rank,
                "supported_constraint_rank": kkt.supported_constraint_rank,
                "multipliers_N": kkt.multipliers_N,
                "stationarity_vector_N": kkt.stationarity_vector_N,
                "primal_violation_m": kkt.primal_violation_m,
                "dual_violation_N": kkt.dual_violation_N,
                "stationarity_residual_N": kkt.stationarity_residual_N,
                "stationarity_limit_N": kkt.stationarity_limit_N,
                "complementarity_residual_N_m": kkt.complementarity_residual_N_m,
                "complementarity_limit_N_m": kkt.complementarity_limit_N_m,
            },
            "gap_jacobian_audit": {
                "samples": [sample.__dict__ for sample in samples],
                "strict_decrease_interval": decrease,
            },
            "action_reaction": action.__dict__,
            "second_order": {
                "unsymmetrized_relative_asymmetry": hessian.unsymmetrized_relative_asymmetry,
                "active_constraint_rank": hessian.active_constraint_rank,
                "gauge_dimension": hessian.gauge_dimension,
                "tested_tangent_dimension": hessian.tested_tangent_dimension,
                "projected_eigenvalues": hessian.projected_eigenvalues,
                "directional_curvatures": hessian.directional_curvatures,
            },
            "expectation_errors": {
                "position_l2_error_m": position_error,
                "supported_multiplier_max_absolute_error_N": multiplier_error,
                "minimum_supported_witness_unit_interval_margin": witness_margin,
            },
            "acceptance_gate_checks": checks,
            "qualified_by_independent_gates": qualified,
        }
    )


def _target_metrics(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    formal_sha = _sha256(root / "contracts" / manifest["formal_registration_contract"])
    amendment_sha = _sha256(root / "contracts" / "p3_protocol_amendment_a1.json")
    case = build_target_contact_case(
        manifest,
        formal_sha256=formal_sha,
        amendment_sha256=amendment_sha,
    )
    solver = manifest["primary_solver"]
    settings = ContactSolverSettings(
        method=solver["method"],
        function_tolerance=solver["ftol"],
        maximum_iterations=solver["maximum_iterations"],
    )
    seeds: list[dict[str, Any]] = []
    for seed in case.seeds:
        initial = _initial_seed_document(case, seed)
        try:
            result = solve_contact_seed(case.assembly, seed, settings)
        except ContactGeometryError as error:
            metrics: dict[str, Any] = {
                "execution_status": "FAIL_CLOSED_CONTACT_GEOMETRY",
                "failure_type": type(error).__name__,
                "failure_message": str(error),
                "qualified_by_independent_gates": False,
            }
        except Exception as error:  # pragma: no cover - retained as raw fail-closed evidence
            metrics = {
                "execution_status": "FAIL_CLOSED_UNEXPECTED_EXCEPTION",
                "failure_type": type(error).__name__,
                "failure_message": str(error),
                "qualified_by_independent_gates": False,
            }
        else:
            metrics = _completed_seed_metrics(case, result, manifest)
        seeds.append(
            {
                "seed_id": seed.seed_id,
                "initial": initial,
                **metrics,
            }
        )
    qualified = [seed for seed in seeds if seed["qualified_by_independent_gates"]]
    passing_count = len(qualified)
    required_count = int(manifest["target_case"]["required_passing_seed_count"])
    completed = [seed for seed in seeds if seed["execution_status"] == "COMPLETED"]
    spread: dict[str, Any]
    if len(completed) == len(seeds):
        positions = np.asarray([seed["bob_position_m"] for seed in completed], dtype=float)
        energies = np.asarray([seed["total_potential_J"] for seed in completed], dtype=float)
        position_spread = max(
            float(np.linalg.norm(first - second)) for first in positions for second in positions
        )
        energy_spread = float(np.max(energies) - np.min(energies))
        spread = {
            "available": True,
            "position_spread_m": position_spread,
            "energy_spread_J": energy_spread,
            "position_gate": position_spread
            <= float(manifest["target_case"]["multiseed_position_spread_max_m"]),
            "energy_gate": energy_spread
            <= float(manifest["target_case"]["multiseed_energy_spread_max_J"]),
        }
    else:
        spread = {
            "available": False,
            "reason": "one_or_more_frozen_seeds_failed_closed_before_a_candidate_was_returned",
            "position_gate": False,
            "energy_gate": False,
        }
    gate_checks = {
        "all_frozen_seeds_returned_candidates": len(completed) == len(seeds),
        "required_passing_seed_count": passing_count == required_count,
        "multiseed_position_spread": bool(spread["position_gate"]),
        "multiseed_energy_spread": bool(spread["energy_gate"]),
    }
    return {
        "case_id": case.case_id,
        "role": manifest["target_case"]["role"],
        "contact_assembly_token": case.assembly.contact_assembly_token,
        "formal_registration_id": case.assembly.registry.formal_registration_id,
        "constraint_ids": list(case.assembly.registry.constraint_ids),
        "constraint_count": len(case.assembly.registry.constraint_ids),
        "solver": {
            "method": settings.method,
            "ftol": settings.function_tolerance,
            "maximum_iterations": settings.maximum_iterations,
            "disp": False,
            "fallback_used": False,
            "tolerance_mutated": False,
            "seed_set_mutated": False,
        },
        "seeds": seeds,
        "completed_seed_count": len(completed),
        "qualified_seed_count": passing_count,
        "required_qualified_seed_count": required_count,
        "selection": {
            "rule": manifest["primary_solver"]["selection_rule"],
            "selected_seed_id": None,
            "reason": "no_frozen_seed_passed_every_independent_gate",
        },
        "multiseed_spread": spread,
        "gate_checks": gate_checks,
        "status": "PASS" if all(gate_checks.values()) else "FAIL",
    }


def _p2_regression(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    historical_path = root / "reports" / "g2r_metrics.json"
    historical_sha = _sha256(historical_path)
    expected_sha = manifest["p2_regression"]["historical_g2r_metrics_sha256"]
    no_contact_paths = (
        "tests/unit/test_axial.py",
        "tests/unit/test_bending.py",
        "tests/unit/test_mass_loads.py",
        "tests/unit/test_rigid.py",
        "tests/unit/test_static_assembly.py",
        "tests/unit/test_topology_state.py",
        "tests/characterization/test_p0_contracts.py",
        "tests/characterization/test_rc1_characterization.py",
    )
    no_contact_tests = _run_pytest(root, no_contact_paths)
    rerun = build_g2r_evidence(root)
    equivalence = rerun["historical_g2_equivalence"]
    centerline = rerun["full_material_centerline_trend"]
    case = build_target_contact_case(
        manifest,
        formal_sha256=_sha256(root / "contracts" / manifest["formal_registration_contract"]),
        amendment_sha256=_sha256(root / "contracts" / "p3_protocol_amendment_a1.json"),
    )
    contact_coordinates = case.assembly.coordinates_from_seed(case.seeds[0])
    contact_evaluation = case.assembly.evaluate(contact_coordinates)
    base_coordinates = case.assembly.base_assembly.coordinates_from_values(
        contact_coordinates.values
    )
    base_evaluation = case.assembly.base_assembly.evaluate(base_coordinates)
    potential_bitwise_equal = contact_evaluation.total_potential == base_evaluation.total_potential
    force_bitwise_equal = np.array_equal(
        contact_evaluation.generalized_force,
        base_evaluation.generalized_force,
    )
    base_layer_unchanged = potential_bitwise_equal and force_bitwise_equal
    gates = {
        "historical_g2r_metrics_immutable": historical_sha == expected_sha,
        "base_potential_and_force_layer_unchanged": base_layer_unchanged,
        "existing_no_contact_tests": no_contact_tests["status"] == "PASS",
        "existing_g2r_equivalence_observables": equivalence["status"] == "PASS",
        "existing_g2r_centerline_observables": centerline["status"] == "PASS",
    }
    return {
        "historical_g2r_metrics": {
            "path": "reports/g2r_metrics.json",
            "expected_sha256": expected_sha,
            "actual_sha256": historical_sha,
        },
        "contact_layer_energy_policy": {
            "contact_energy_added": False,
            "contact_force_added_to_base_generalized_force": False,
            "potential_bitwise_equal": potential_bitwise_equal,
            "generalized_force_bitwise_equal": force_bitwise_equal,
            "bitwise_regression_covered_by": "tests/unit/test_contact_assembly.py",
        },
        "no_contact_test_run": no_contact_tests,
        "historical_g2_equivalence": equivalence,
        "full_material_centerline_trend": centerline,
        "gate_checks": gates,
        "status": "PASS" if all(gates.values()) else "FAIL",
    }


def _evidence_binding(root: Path) -> dict[str, Any]:
    named_paths = (
        "contracts/P3_FROZEN_PROTOCOL.md",
        "contracts/P3_PROTOCOL_AMENDMENT_A1.md",
        "contracts/p3_acceptance_manifest.json",
        "contracts/p3_formal_contact_registration.json",
        "contracts/p3_protocol_amendment_a1.json",
        "contracts/p3_module_manifest.json",
        "contracts/model_identity_0_3_contact.json",
        "tools/generate_g3_evidence.py",
        "pyproject.toml",
        "README.md",
    )
    return {
        "named_paths": {relative: _sha256(root / relative) for relative in named_paths},
        "source_sha256": {
            path.relative_to(root).as_posix(): _sha256(path)
            for path in sorted((root / "src" / "ypendulum_hfv2").rglob("*.py"))
        },
        "test_sha256": {
            path.relative_to(root).as_posix(): _sha256(path)
            for path in sorted((root / "tests").rglob("*.py"))
        },
    }


def build_g3_evidence(candidate_root: str | Path) -> dict[str, Any]:
    root = Path(candidate_root).resolve()
    manifest = _load_json(root / "contracts" / "p3_acceptance_manifest.json")
    if manifest["base_model_id"] != MODEL_ID:
        raise ValueError("P3 base model identity differs from the package.")
    if manifest["contact_model_id"] != CONTACT_MODEL_ID:
        raise ValueError("P3 contact model identity differs from the package.")
    contract_binding = _contract_binding(root, manifest)
    runtime = _runtime_metrics(manifest)
    small_benchmarks = _run_pytest(
        root,
        (
            "tests/unit/test_contact_geometry.py",
            "tests/unit/test_contact_registration.py",
            "tests/unit/test_contact_assembly.py",
            "tests/unit/test_contact_solver_audit.py",
        ),
    )
    architecture = _architecture_metrics(root, manifest)
    target = _target_metrics(root, manifest)
    p2_regression = _p2_regression(root, manifest)
    gates = {
        "contract_and_formal_source_binding": contract_binding["status"] == "PASS",
        "exact_runtime": runtime["status"] == "PASS",
        "small_benchmarks_before_target": small_benchmarks["status"] == "PASS",
        "architecture": architecture["status"] == "PASS",
        "p2_regression": p2_regression["status"] == "PASS",
        "frozen_target": target["status"] == "PASS",
    }
    passed = all(gates.values())
    return _jsonable(
        {
            "schema": "YPS-HFV2-G3-EVIDENCE-1.0",
            "base_model_id": MODEL_ID,
            "contact_model_id": CONTACT_MODEL_ID,
            "scope": "static_frictionless_rigid_unilateral_normal_contact_algorithm",
            "status": manifest["pass_status"] if passed else manifest["fail_status"],
            "formal_numerical_qualification": manifest["formal_numerical_qualification"],
            "stop_gate": manifest["mandatory_stop_after_evidence"],
            "optimizer_success_used_as_acceptance_gate": False,
            "gate_summary": gates,
            "contract_binding": contract_binding,
            "runtime": runtime,
            "small_benchmarks": small_benchmarks,
            "architecture": architecture,
            "p2_regression": p2_regression,
            "target": target,
            "forbidden_scope_not_executed": manifest["forbidden"],
            "not_executed": [
                "friction",
                "restitution",
                "penalty_or_compliant_contact",
                "dynamic_contact_or_impulse",
                "contact_time_integration",
                "P4",
                "P5",
                "P6",
                "formal_program_migration",
                "public_api_hdf5_or_ui_change",
                "physical_apparatus_validation",
                "experimental_validation",
            ],
            "evidence_binding": _evidence_binding(root),
        }
    )


def canonical_g3_evidence_text(evidence: dict[str, Any]) -> str:
    return json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n"

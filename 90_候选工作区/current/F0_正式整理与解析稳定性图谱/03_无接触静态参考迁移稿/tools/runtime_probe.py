"""Generate closed evidence for the canonical candidate-only static run."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path
from typing import Any

import jsonschema

SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
for import_root in (SCRIPT_PROJECT_ROOT, SCRIPT_PROJECT_ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from tests.fixtures.static_cases import build_y_anchor_case  # noqa: E402
from ypendulum_static_reference.identity import (  # noqa: E402
    CAPABILITY,
    CLAIM_CEILING,
    MODEL_ID,
    QUALIFICATION_STATUS,
)
from ypendulum_static_reference.interface import (  # noqa: E402
    StaticReferenceAuditThresholds,
    solve_no_contact_static_reference,
)
from ypendulum_static_reference.statics.solver import (  # noqa: E402
    StaticSolverSettings,
)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _source_manifest(project: Path) -> dict[str, Any]:
    inputs: list[tuple[str, Path]] = [
        ("canonical_contract", project / "contracts/static_reference_run_contract.json"),
        ("model_identity", project / "model_identity.json"),
        ("build_metadata", project / "pyproject.toml"),
        ("evidence_schema", project / "schemas/static_run_evidence.schema.json"),
        ("canonical_case_builder", project / "tests/fixtures/static_cases.py"),
        ("evidence_tool", Path(__file__).resolve()),
    ]
    inputs.extend(
        ("production_source", path)
        for path in sorted((project / "src/ypendulum_static_reference").rglob("*.py"))
    )
    entries = []
    for role, path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
        entries.append(
            {
                "role": role,
                "path": path.relative_to(project).as_posix(),
                "sha256": _sha256_file(path),
            }
        )
    entries.sort(key=lambda item: (item["path"], item["role"]))
    return {"schema": "YPS-NO-CONTACT-STATIC-SOURCE-MANIFEST-1.0", "entries": entries}


def _runtime_identity() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "numpy": importlib.metadata.version("numpy"),
        "scipy": importlib.metadata.version("scipy"),
        "pytest": importlib.metadata.version("pytest"),
        "jsonschema": importlib.metadata.version("jsonschema"),
        "executable_name": Path(sys.executable).name,
    }


def build_evidence(project: Path) -> dict[str, Any]:
    contract_path = project / "contracts/static_reference_run_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    case = build_y_anchor_case(contract, 2)
    solver = contract["primary_solver"]
    finite = contract["finite_difference"]
    y_case = contract["y_anchor"]
    settings = StaticSolverSettings(
        method=solver["method"],
        gradient_infinity_tolerance=solver["gradient_infinity_tolerance"],
        maximum_iterations=solver["maximum_iterations"],
        x_relative_tolerance=solver["x_relative_tolerance"],
        armijo_c1=solver["armijo_c1"],
        curvature_c2=solver["curvature_c2"],
    )
    thresholds = StaticReferenceAuditThresholds(
        finite_difference_relative_steps=tuple(finite["relative_step_sequence"]),
        finite_difference_final_relative_error_max=finite[
            "final_relative_error_max"
        ],
        finite_difference_minimum_strict_decrease_steps=finite[
            "minimum_strict_decrease_steps"
        ],
        scaled_generalized_force_residual_max=y_case[
            "scaled_generalized_force_residual_max"
        ],
        scaled_global_force_balance_max=y_case["scaled_global_force_balance_max"],
        scaled_global_moment_balance_max=y_case["scaled_global_moment_balance_max"],
    )
    batch = solve_no_contact_static_reference(
        case.assembly,
        (case.seeds[0],),
        settings,
        thresholds,
    )
    solve = batch.solve_results[0]
    audit = batch.post_audits[0]
    seed_payload = {
        "seed_id": case.seeds[0].seed_id,
        "free_node_ids": list(case.seeds[0].free_node_ids),
        "free_node_positions": case.seeds[0].free_node_positions.tolist(),
        "bob_position": case.seeds[0].bob_position.tolist(),
        "bob_rotation_vector": case.seeds[0].bob_rotation_vector.tolist(),
    }
    source_manifest = _source_manifest(project)
    runtime = _runtime_identity()
    payload = {
        "schema": "YPS-NO-CONTACT-STATIC-RUN-EVIDENCE-1.0",
        "model_identity": {
            "model_id": MODEL_ID,
            "capability": CAPABILITY,
            "claim_ceiling": CLAIM_CEILING,
            "qualification_status": QUALIFICATION_STATUS,
        },
        "claim_limit": contract["claim_limit"],
        "source_manifest": source_manifest,
        "source_manifest_sha256": _sha256_json(source_manifest),
        "runtime": runtime,
        "runtime_identity_sha256": _sha256_json(runtime),
        "case_binding": {
            "contract_path": contract_path.relative_to(project).as_posix(),
            "contract_sha256": _sha256_file(contract_path),
            "case_id": y_case["case_id"],
            "mesh_segments_per_branch": case.mesh_segments_per_branch,
            "assembly_identity_schema": case.assembly.layout.identity_schema,
            "assembly_token": case.assembly.layout.assembly_token,
            "seed_id": solve.seed_id,
            "seed_sha256": _sha256_json(seed_payload),
        },
        "solver_settings": {
            "library": "scipy.optimize.minimize",
            "method": settings.method,
            "jacobian": "analytic_total_potential_gradient",
            "gradient_infinity_tolerance": settings.gradient_infinity_tolerance,
            "maximum_iterations": settings.maximum_iterations,
            "x_relative_tolerance": settings.x_relative_tolerance,
            "armijo_c1": settings.armijo_c1,
            "curvature_c2": settings.curvature_c2,
            "gradient_norm": "infinity",
            "display": False,
        },
        "audit_thresholds": {
            "finite_difference_relative_steps": list(
                thresholds.finite_difference_relative_steps
            ),
            "finite_difference_final_relative_error_max": (
                thresholds.finite_difference_final_relative_error_max
            ),
            "finite_difference_minimum_strict_decrease_steps": (
                thresholds.finite_difference_minimum_strict_decrease_steps
            ),
            "scaled_generalized_force_residual_max": (
                thresholds.scaled_generalized_force_residual_max
            ),
            "scaled_global_force_balance_max": (
                thresholds.scaled_global_force_balance_max
            ),
            "scaled_global_moment_balance_max": (
                thresholds.scaled_global_moment_balance_max
            ),
        },
        "optimizer_state": {
            "success_record_only": solve.optimizer_success,
            "status_record_only": solve.optimizer_status,
            "message_record_only": solve.optimizer_message,
            "iterations": solve.iterations,
            "function_evaluations": solve.function_evaluations,
            "gradient_evaluations": solve.gradient_evaluations,
        },
        "diagnostics": {
            "finite_difference_probe": audit.finite_difference_probe,
            "finite_difference_relative_errors": list(
                audit.finite_difference_relative_errors
            ),
            "scaled_generalized_force_residual": audit.scaled_generalized_force_residual,
            "scaled_global_force_balance": audit.scaled_global_force_balance,
            "scaled_global_moment_balance": audit.scaled_global_moment_balance,
            "independent_checks": audit.independent_checks,
            "implementation_diagnostics_passed": audit.implementation_diagnostics_passed,
        },
        "interpretation": (
            "The optimizer state is record-only. Passing implementation diagnostics "
            "does not carry historical numerical qualification, contact capability, "
            "device validation or experimental validation."
        ),
    }
    schema = json.loads(
        (project / "schemas/static_run_evidence.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=SCRIPT_PROJECT_ROOT)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    project = arguments.project_root.resolve()
    payload = build_evidence(project)
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    if arguments.output is not None:
        output = arguments.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

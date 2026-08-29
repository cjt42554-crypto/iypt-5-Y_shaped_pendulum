"""Generate closed evidence for the formal static-reference run."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import platform
import re
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

import jsonschema

SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODEL_ID = "YPS-NO-CONTACT-STATIC-REFERENCE-1.1"
RELEASE_STATUS = "FORMAL_RELEASE_STATIC_REFERENCE_ONLY"
CAPABILITY = "position_orientation_conservative_no_contact_static_reference_only"
CLAIM_CEILING = "FORMAL_STATIC_REFERENCE_IMPLEMENTATION_AND_RUNTIME_EVIDENCE_ONLY"
QUALIFICATION_STATUS = "NO_FORMAL_NUMERICAL_QUALIFICATION_CARRIED"
CLAIM_LIMIT = (
    "formal static-reference implementation and runtime evidence only; "
    "no formal numerical qualification is carried"
)
MODEL_IDENTITY_SCHEMA = "YPS-NO-CONTACT-STATIC-REFERENCE-MODEL-IDENTITY-1.1"
CONTRACT_SCHEMA = "YPS-NO-CONTACT-STATIC-CANONICAL-RUN-CONTRACT-1.1"
EVIDENCE_SCHEMA = "YPS-NO-CONTACT-STATIC-RUN-EVIDENCE-1.1"
SOURCE_MANIFEST_SCHEMA = "YPS-NO-CONTACT-STATIC-SOURCE-MANIFEST-1.1"

EXPECTED_PRODUCTION_PATHS = (
    "src/ypendulum_static_reference/__init__.py",
    "src/ypendulum_static_reference/audit/__init__.py",
    "src/ypendulum_static_reference/audit/energy_gradient.py",
    "src/ypendulum_static_reference/audit/statics.py",
    "src/ypendulum_static_reference/constitutive/__init__.py",
    "src/ypendulum_static_reference/constitutive/axial.py",
    "src/ypendulum_static_reference/constitutive/bending.py",
    "src/ypendulum_static_reference/identity.py",
    "src/ypendulum_static_reference/interface.py",
    "src/ypendulum_static_reference/loads.py",
    "src/ypendulum_static_reference/mass.py",
    "src/ypendulum_static_reference/rigid/__init__.py",
    "src/ypendulum_static_reference/rigid/attachment.py",
    "src/ypendulum_static_reference/rigid/rotation.py",
    "src/ypendulum_static_reference/state.py",
    "src/ypendulum_static_reference/statics/__init__.py",
    "src/ypendulum_static_reference/statics/assembly.py",
    "src/ypendulum_static_reference/statics/contracts.py",
    "src/ypendulum_static_reference/statics/solver.py",
    "src/ypendulum_static_reference/topology.py",
)

SINGLETON_SOURCE_ROLES = {
    "canonical_contract": "contracts/static_reference_run_contract.json",
    "model_identity": "model_identity.json",
    "build_metadata": "pyproject.toml",
    "evidence_schema": "schemas/static_run_evidence.schema.json",
    "canonical_case_builder": "tests/fixtures/static_cases.py",
    "evidence_tool": "tools/runtime_probe.py",
}


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


def _validated_project_root(project: Path) -> Path:
    requested = project.expanduser().resolve(strict=True)
    if not requested.is_dir():
        raise ValueError(f"project root is not a directory: {requested}")
    if requested != SCRIPT_PROJECT_ROOT:
        raise ValueError(
            "--project-root must resolve to the formal root containing this "
            f"runtime_probe.py: expected {SCRIPT_PROJECT_ROOT}, got {requested}"
        )
    expected_probe = (requested / "tools/runtime_probe.py").resolve(strict=True)
    if Path(__file__).resolve() != expected_probe:
        raise ValueError("runtime probe file is not bound to the requested formal root")
    return requested


def _prepend_bound_import_paths(project: Path) -> None:
    bound = [str(project / "src"), str(project)]
    remaining = []
    for entry in sys.path:
        try:
            resolved = str(Path(entry or ".").resolve())
        except OSError:
            remaining.append(entry)
            continue
        if resolved not in bound:
            remaining.append(entry)
    sys.path[:] = [*bound, *remaining]


def _require_module_file(module: ModuleType, expected: Path, label: str) -> None:
    module_file = getattr(module, "__file__", None)
    if module_file is None:
        raise ImportError(f"{label} has no importable file identity")
    actual = Path(module_file).resolve(strict=True)
    required = expected.resolve(strict=True)
    if actual != required:
        raise ImportError(f"{label} imported from {actual}; expected {required}")


def _load_bound_modules(project: Path) -> dict[str, ModuleType]:
    _prepend_bound_import_paths(project)
    modules = {
        "package": importlib.import_module("ypendulum_static_reference"),
        "identity": importlib.import_module("ypendulum_static_reference.identity"),
        "interface": importlib.import_module("ypendulum_static_reference.interface"),
        "solver": importlib.import_module("ypendulum_static_reference.statics.solver"),
        "static_cases": importlib.import_module("tests.fixtures.static_cases"),
    }
    expected = {
        "package": project / "src/ypendulum_static_reference/__init__.py",
        "identity": project / "src/ypendulum_static_reference/identity.py",
        "interface": project / "src/ypendulum_static_reference/interface.py",
        "solver": project / "src/ypendulum_static_reference/statics/solver.py",
        "static_cases": project / "tests/fixtures/static_cases.py",
    }
    for label, module in modules.items():
        _require_module_file(module, expected[label], label)
    return modules


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _validate_identity_bindings(
    model_identity: dict[str, Any],
    contract: dict[str, Any],
    evidence_schema: dict[str, Any],
    identity_module: ModuleType,
) -> None:
    expected_identity = {
        "model_id": MODEL_ID,
        "status": RELEASE_STATUS,
        "capability": CAPABILITY,
        "claim_ceiling": CLAIM_CEILING,
        "qualification_status": QUALIFICATION_STATUS,
    }
    if model_identity.get("schema") != MODEL_IDENTITY_SCHEMA:
        raise ValueError("model_identity schema is not the frozen formal identity schema")
    for key, expected in expected_identity.items():
        if model_identity.get(key) != expected:
            raise ValueError(f"model_identity.{key} does not match the formal identity")
    if model_identity.get("qualification_carried_by_release") is not False:
        raise ValueError("formal release must not carry historical numerical qualification")

    python_identity = {
        "model_id": getattr(identity_module, "MODEL_ID", None),
        "status": getattr(identity_module, "RELEASE_STATUS", None),
        "capability": getattr(identity_module, "CAPABILITY", None),
        "claim_ceiling": getattr(identity_module, "CLAIM_CEILING", None),
        "qualification_status": getattr(identity_module, "QUALIFICATION_STATUS", None),
    }
    if python_identity != expected_identity:
        raise ValueError("Python identity constants do not match model_identity.json")

    expected_contract_keys = {
        "schema",
        "model_id",
        "release_status",
        "capability",
        "claim_ceiling",
        "qualification_status",
        "claim_limit",
        "coordinate_chart",
        "primary_solver",
        "finite_difference",
        "y_anchor",
    }
    if set(contract) != expected_contract_keys:
        raise ValueError("canonical contract top-level fields are not closed")
    expected_contract_identity = {
        "schema": CONTRACT_SCHEMA,
        "model_id": MODEL_ID,
        "release_status": RELEASE_STATUS,
        "capability": CAPABILITY,
        "claim_ceiling": CLAIM_CEILING,
        "qualification_status": QUALIFICATION_STATUS,
        "claim_limit": CLAIM_LIMIT,
    }
    for key, expected in expected_contract_identity.items():
        if contract.get(key) != expected:
            raise ValueError(f"canonical contract {key} does not match the formal identity")

    jsonschema.Draft202012Validator.check_schema(evidence_schema)
    properties = evidence_schema.get("properties", {})
    if properties.get("schema", {}).get("const") != EVIDENCE_SCHEMA:
        raise ValueError("run-evidence schema identity is not frozen")
    model_properties = properties.get("model_identity", {}).get("properties", {})
    schema_identity = {
        "model_id": model_properties.get("model_id", {}).get("const"),
        "status": model_properties.get("release_status", {}).get("const"),
        "capability": model_properties.get("capability", {}).get("const"),
        "claim_ceiling": model_properties.get("claim_ceiling", {}).get("const"),
        "qualification_status": model_properties.get("qualification_status", {}).get(
            "const"
        ),
    }
    if schema_identity != expected_identity:
        raise ValueError("run-evidence schema constants do not match the formal identity")
    source_schema = (
        properties.get("source_manifest", {})
        .get("properties", {})
        .get("schema", {})
        .get("const")
    )
    if source_schema != SOURCE_MANIFEST_SCHEMA:
        raise ValueError("source-manifest schema identity is not frozen")
    if properties.get("claim_limit", {}).get("const") != CLAIM_LIMIT:
        raise ValueError("run-evidence claim limit is not frozen")


def _path_has_symlink(project: Path, relative: PurePosixPath) -> bool:
    cursor = project
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            return True
    return False


def _validate_source_entries(project: Path, entries: list[dict[str, str]]) -> None:
    expected_paths = set(EXPECTED_PRODUCTION_PATHS) | set(SINGLETON_SOURCE_ROLES.values())
    if len(entries) != len(expected_paths):
        raise ValueError("source manifest does not have the exact formal source count")

    seen_paths: set[str] = set()
    role_paths: dict[str, list[str]] = {}
    for entry in entries:
        if set(entry) != {"role", "path", "sha256"}:
            raise ValueError("source entry fields are not closed")
        role = entry["role"]
        raw_path = entry["path"]
        relative = PurePosixPath(raw_path)
        if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
            raise ValueError(f"source path is not a normalized relative path: {raw_path}")
        if relative.as_posix() != raw_path or "\\" in raw_path:
            raise ValueError(f"source path is not canonical POSIX syntax: {raw_path}")
        if raw_path in seen_paths:
            raise ValueError(f"duplicate source path: {raw_path}")
        seen_paths.add(raw_path)
        role_paths.setdefault(role, []).append(raw_path)

        source = project.joinpath(*relative.parts)
        if _path_has_symlink(project, relative):
            raise ValueError(f"source path contains a symlink: {raw_path}")
        resolved = source.resolve(strict=True)
        try:
            resolved.relative_to(project)
        except ValueError as error:
            raise ValueError(f"source path escapes the formal root: {raw_path}") from error
        if not resolved.is_file():
            raise ValueError(f"source path is not a regular file: {raw_path}")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError(f"source hash is not SHA-256: {raw_path}")
        if _sha256_file(resolved) != entry["sha256"]:
            raise ValueError(f"source hash drift: {raw_path}")

    if seen_paths != expected_paths:
        raise ValueError("source manifest paths do not match the exact formal source set")
    for role, expected_path in SINGLETON_SOURCE_ROLES.items():
        if role_paths.get(role) != [expected_path]:
            raise ValueError(f"source role must occur exactly once: {role}")
    production_paths = role_paths.get("production_source", [])
    if set(production_paths) != set(EXPECTED_PRODUCTION_PATHS):
        raise ValueError("production_source role does not bind the exact production tree")
    unexpected_roles = set(role_paths) - (set(SINGLETON_SOURCE_ROLES) | {"production_source"})
    if unexpected_roles:
        raise ValueError(f"unexpected source roles: {sorted(unexpected_roles)}")


def _source_manifest(project: Path) -> dict[str, Any]:
    package_root = project / "src/ypendulum_static_reference"
    actual_production = {
        path.relative_to(project).as_posix() for path in package_root.rglob("*.py")
    }
    if actual_production != set(EXPECTED_PRODUCTION_PATHS):
        raise ValueError("formal production tree differs from the frozen source set")

    role_by_path = {path: role for role, path in SINGLETON_SOURCE_ROLES.items()}
    entries: list[dict[str, str]] = []
    for raw_path in sorted(set(EXPECTED_PRODUCTION_PATHS) | set(role_by_path)):
        role = role_by_path.get(raw_path, "production_source")
        source = project / raw_path
        entries.append({"role": role, "path": raw_path, "sha256": _sha256_file(source)})
    _validate_source_entries(project, entries)
    return {"schema": SOURCE_MANIFEST_SCHEMA, "entries": entries}


def _release_tuple(version: str, label: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", version)
    if match is None:
        raise ValueError(f"cannot parse {label} version: {version}")
    return tuple(int(part or 0) for part in match.groups())


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


def _validate_runtime_identity(runtime: dict[str, str]) -> None:
    if runtime.get("python_implementation") != "CPython":
        raise ValueError("formal runtime requires CPython")
    python_version = _release_tuple(runtime.get("python", ""), "Python")
    if not ((3, 12, 0) <= python_version < (3, 13, 0)):
        raise ValueError("formal runtime requires Python >=3.12,<3.13")
    numpy_version = _release_tuple(runtime.get("numpy", ""), "NumPy")
    if not ((1, 26, 0) <= numpy_version < (3, 0, 0)):
        raise ValueError("formal runtime requires NumPy >=1.26,<3")
    scipy_version = _release_tuple(runtime.get("scipy", ""), "SciPy")
    if not ((1, 12, 0) <= scipy_version < (2, 0, 0)):
        raise ValueError("formal runtime requires SciPy >=1.12,<2")
    for dependency in ("pytest", "jsonschema", "executable_name"):
        if not runtime.get(dependency):
            raise ValueError(f"runtime identity is missing {dependency}")


def build_evidence(project: Path) -> dict[str, Any]:
    project = _validated_project_root(project)
    modules = _load_bound_modules(project)
    model_identity = _load_json_object(project / "model_identity.json")
    contract_path = project / "contracts/static_reference_run_contract.json"
    contract = _load_json_object(contract_path)
    schema_path = project / "schemas/static_run_evidence.schema.json"
    schema = _load_json_object(schema_path)
    _validate_identity_bindings(model_identity, contract, schema, modules["identity"])

    static_cases = modules["static_cases"]
    interface = modules["interface"]
    solver_module = modules["solver"]
    case = static_cases.build_y_anchor_case(contract, 2)
    solver = contract["primary_solver"]
    finite = contract["finite_difference"]
    y_case = contract["y_anchor"]
    settings = solver_module.StaticSolverSettings(
        method=solver["method"],
        gradient_infinity_tolerance=solver["gradient_infinity_tolerance"],
        maximum_iterations=solver["maximum_iterations"],
        x_relative_tolerance=solver["x_relative_tolerance"],
        armijo_c1=solver["armijo_c1"],
        curvature_c2=solver["curvature_c2"],
    )
    thresholds = interface.StaticReferenceAuditThresholds(
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
    batch = interface.solve_no_contact_static_reference(
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
    _validate_runtime_identity(runtime)
    payload = {
        "schema": EVIDENCE_SCHEMA,
        "model_identity": {
            "model_id": MODEL_ID,
            "release_status": RELEASE_STATUS,
            "capability": CAPABILITY,
            "claim_ceiling": CLAIM_CEILING,
            "qualification_status": QUALIFICATION_STATUS,
        },
        "claim_limit": CLAIM_LIMIT,
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
            "does not carry formal numerical qualification, contact capability, "
            "device validation or experimental validation."
        ),
    }
    jsonschema.Draft202012Validator(schema).validate(payload)
    return payload


def _serialize(payload: dict[str, Any]) -> str:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=SCRIPT_PROJECT_ROOT)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    project = _validated_project_root(arguments.project_root)
    payload = build_evidence(project)
    serialized = _serialize(payload)
    if arguments.output is not None:
        output = arguments.output.expanduser().resolve()
        try:
            output.relative_to(project)
        except ValueError:
            pass
        else:
            raise ValueError("evidence output must be outside the formal project root")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

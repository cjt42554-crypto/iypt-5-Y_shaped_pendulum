"""Generate semantic, per-file lineage for the static-only migration draft."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

SOURCE_ROOT = Path("90_候选工作区/current/HF-v2-core/src/ypendulum_hfv2")
TARGET_ROOT = Path(
    "90_候选工作区/current/F0_正式整理与解析稳定性图谱/"
    "03_无接触静态参考迁移稿/src/ypendulum_static_reference"
)

TRANSFORMS = {
    "__init__.py": "closed_static_public_exports",
    "audit/__init__.py": "retain_conservative_static_audits_only",
    "audit/energy_gradient.py": "preserve_static_energy_gradient_audit",
    "audit/statics.py": "preserve_static_force_balance_and_hessian_audits",
    "constitutive/__init__.py": "export_conservative_constitutive_laws_only",
    "constitutive/axial.py": "extract_unilateral_elastic_static_potential_and_remove_rate_terms",
    "constitutive/bending.py": "preserve_conservative_discrete_bending_energy_and_force",
    "identity.py": "new_candidate_identity_without_historical_qualification_carry",
    "interface.py": "new_threshold_validated_static_solve_interface",
    "loads.py": "extract_separate_gravity_and_buoyancy_static_loads",
    "mass.py": "extract_static_mass_registration_and_remove_dynamic_observables",
    "rigid/__init__.py": "export_static_orientation_and_attachment_geometry_only",
    "rigid/attachment.py": "extract_attachment_geometry_and_static_wrench_mapping",
    "rigid/rotation.py": "retain_SO3_validation_exponential_and_composition_only",
    "state.py": "extract_position_and_orientation_state_only",
    "statics/__init__.py": "retain_static_assembly_contracts_and_solver_exports",
    "statics/assembly.py": "bind_conservative_static_total_potential_without_motion_inputs",
    "statics/contracts.py": "remove_inertial_data_and_bind_static_coordinates",
    "statics/solver.py": "retain_single_deterministic_BFGS_static_algorithm",
    "topology.py": "retain_material_topology_and_position_tangent_map_only",
}

NEW_CANDIDATE_FILES = {"identity.py", "interface.py"}
FORBIDDEN_IDENTIFIER_FRAGMENTS = (
    "hfv2",
    "velocity",
    "kinetic",
    "momentum",
    "drag",
    "dissipation",
    "power",
    "time_step",
    "advance_rotation",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _static_ast_guard(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    identifiers: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            identifiers.append(node.name)
        elif isinstance(node, ast.arg):
            identifiers.append(node.arg)
        elif isinstance(node, ast.Name):
            identifiers.append(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.append(node.attr)
        elif isinstance(node, ast.Import):
            identifiers.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            identifiers.append(node.module or "")
    violations = sorted(
        {
            identifier
            for identifier in identifiers
            if any(
                fragment in identifier.lower()
                for fragment in FORBIDDEN_IDENTIFIER_FRAGMENTS
            )
        }
    )
    if violations:
        raise RuntimeError(f"Static-only AST guard failed for {path}: {violations}")


def build(repository_root: Path) -> dict[str, object]:
    target_root = repository_root / TARGET_ROOT
    actual_targets = {
        path.relative_to(target_root).as_posix() for path in target_root.rglob("*.py")
    }
    if actual_targets != set(TRANSFORMS):
        raise RuntimeError(
            "Production source set drift: "
            f"missing={sorted(set(TRANSFORMS) - actual_targets)}, "
            f"unexpected={sorted(actual_targets - set(TRANSFORMS))}"
        )

    rows: list[dict[str, object]] = []
    for relative in sorted(TRANSFORMS):
        target = target_root / relative
        _static_ast_guard(target)
        row: dict[str, object] = {
            "target": target.relative_to(repository_root).as_posix(),
            "target_sha256": _sha256(target),
            "semantic_transform": TRANSFORMS[relative],
            "byte_identity_claimed": False,
        }
        if relative in NEW_CANDIDATE_FILES:
            row["source"] = None
            row["source_sha256"] = None
            row["lineage_kind"] = "new_candidate_governance_or_interface"
        else:
            source = repository_root / SOURCE_ROOT / relative
            if not source.is_file():
                raise FileNotFoundError(source)
            row["source"] = source.relative_to(repository_root).as_posix()
            row["source_sha256"] = _sha256(source)
            row["lineage_kind"] = "semantic_static_extraction"
        rows.append(row)

    return {
        "schema": "YPS-NO-CONTACT-STATIC-MIGRATION-PROVENANCE-2.0",
        "model_id": "YPS-NO-CONTACT-STATIC-REFERENCE-DRAFT-1.1",
        "formal_promotion_status": "NOT_PROMOTED_CANDIDATE_DRAFT",
        "qualification_carried_by_migration": False,
        "lineage_interpretation": (
            "Semantic static-only extraction; no namespace-only or byte-equivalence "
            "claim is made."
        ),
        "semantic_lineage": rows,
        "production_static_guards": {
            "source_set_exact": True,
            "ast_forbidden_identifiers_absent": True,
            "historical_case_builders_in_test_layer": True,
            "dynamic_and_contact_modules_absent": True,
        },
        "excluded_source_components": [
            "contact/**",
            "statics/contact_assembly.py",
            "statics/contact_solver.py",
            "audit/passivity.py",
            "audit/invariance.py",
            "audit/g2_cases.py",
            "all motion-state and time-advance APIs",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    payload = build(arguments.repository_root.resolve())
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output = arguments.output.resolve()
    if arguments.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != serialized:
            print("migration provenance is stale", file=sys.stderr)
            return 2
        print("migration provenance is current")
        return 0
    output.write_text(serialized, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

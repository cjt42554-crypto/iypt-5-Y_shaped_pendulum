from __future__ import annotations

import json
import shutil
from pathlib import Path

import ypendulum_hfv2
from ypendulum_hfv2.audit.dependency import audit_g2_dependencies

PACKAGE_ROOT = Path(ypendulum_hfv2.__file__).resolve().parent
CANDIDATE_ROOT = PACKAGE_ROOT.parents[1]
MODULE_MANIFEST = CANDIDATE_ROOT / "contracts" / "g2r_module_manifest.json"
ACCEPTANCE = json.loads(
    (CANDIDATE_ROOT / "contracts" / "g2_acceptance_manifest.json").read_text(
        encoding="utf-8"
    )
)


def test_g2r_dependency_matrix_is_manifest_complete_and_passes() -> None:
    audit = audit_g2_dependencies(PACKAGE_ROOT, MODULE_MANIFEST)
    assert audit.passed, audit
    assert audit.unclassified_files == ()
    assert audit.missing_manifest_files == ()
    assert audit.dependency_violations == ()
    assert audit.path_classification_violations == ()
    assert audit.production_try_statement_count == 0
    assert audit.production_random_call_count == 0


def test_relative_imports_are_normalized_to_canonical_package_paths() -> None:
    audit = audit_g2_dependencies(PACKAGE_ROOT, MODULE_MANIFEST)
    imports = dict(audit.canonical_imports)
    assert "ypendulum_hfv2.rigid.rotation" in imports["state.py"]
    assert "ypendulum_hfv2.statics.contracts" in imports["statics/assembly.py"]
    assert "ypendulum_hfv2.audit" not in imports["statics/solver.py"]
    assert "scipy.optimize" in imports["statics/solver.py"]


def test_new_unclassified_module_fails_closed(tmp_path: Path) -> None:
    copied_package = tmp_path / "ypendulum_hfv2"
    shutil.copytree(PACKAGE_ROOT, copied_package)
    (copied_package / "unclassified_new_module.py").write_text("VALUE = 1\n", encoding="utf-8")
    audit = audit_g2_dependencies(copied_package, MODULE_MANIFEST)
    assert audit.passed is False
    assert audit.unclassified_files == ("unclassified_new_module.py",)


def test_production_file_cannot_escape_by_being_classified_as_audit(tmp_path: Path) -> None:
    manifest = json.loads(MODULE_MANIFEST.read_text(encoding="utf-8"))
    solver = next(entry for entry in manifest["modules"] if entry["path"] == "statics/solver.py")
    solver["classification"] = "audit"
    mutated = tmp_path / "manifest.json"
    mutated.write_text(json.dumps(manifest), encoding="utf-8")
    audit = audit_g2_dependencies(PACKAGE_ROOT, mutated)
    assert audit.passed is False
    assert any("statics/solver.py" in value for value in audit.path_classification_violations)


def test_rotation_source_contains_no_normalization_or_projection_path() -> None:
    source = (PACKAGE_ROOT / "rigid" / "rotation.py").read_text(encoding="utf-8").lower()
    assert "normalize" not in source
    assert "normalise" not in source
    assert "svd" not in source
    assert "project_to" not in source


def test_all_classified_source_files_remain_bounded_by_responsibility() -> None:
    audit = audit_g2_dependencies(PACKAGE_ROOT, MODULE_MANIFEST)
    line_limit = ACCEPTANCE["architecture"]["source_lines_per_module_max_exclusive"]
    for relative in audit.discovered_files:
        line_count = len((PACKAGE_ROOT / relative).read_text(encoding="utf-8").splitlines())
        assert line_count < line_limit, relative


def test_candidate_public_namespace_still_exposes_no_solver_or_io() -> None:
    exported = set(ypendulum_hfv2.__all__)
    assert "MODEL_ID" in exported
    assert not any("solver" in name.lower() for name in exported)
    assert not any("validation" in name.lower() for name in exported)
    assert not any("hdf5" in name.lower() for name in exported)

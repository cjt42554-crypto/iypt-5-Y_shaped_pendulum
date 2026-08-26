from __future__ import annotations

import json
import shutil
from pathlib import Path

import ypendulum_hfv2
from ypendulum_hfv2.audit.architecture import (
    FORBIDDEN_IMPORT_PREFIXES,
    FORBIDDEN_SOLVER_IMPORT_PREFIXES,
    audit_physical_core,
)

PACKAGE_ROOT = Path(ypendulum_hfv2.__file__).resolve().parent
CANDIDATE_ROOT = PACKAGE_ROOT.parents[1]
MODULE_MANIFEST = CANDIDATE_ROOT / "contracts" / "g1r_module_manifest.json"
ACCEPTANCE = json.loads(
    (CANDIDATE_ROOT / "contracts" / "g1r_acceptance_manifest.json").read_text(encoding="utf-8")
)


def test_physical_core_has_no_reverse_dependency_or_silent_fallback() -> None:
    audit = audit_physical_core(PACKAGE_ROOT, MODULE_MANIFEST)
    assert audit.passed, audit
    assert audit.forbidden_imports == ()
    assert audit.solver_imports == ()
    assert audit.try_statement_count == 0
    assert audit.random_call_count == 0
    assert audit.unclassified_files == ()
    assert audit.missing_manifest_files == ()
    assert not any(name.startswith("ypendulum_hfv2.audit") for name in audit.imports)


def test_architecture_thresholds_and_forbidden_prefixes_come_from_manifest() -> None:
    contract = ACCEPTANCE["architecture"]
    assert set(contract["forbidden_import_prefixes"]) == set(FORBIDDEN_IMPORT_PREFIXES)
    assert set(contract["forbidden_solver_import_prefixes"]) == set(
        FORBIDDEN_SOLVER_IMPORT_PREFIXES
    )
    assert contract["unclassified_file_count_max"] == 0
    assert contract["missing_manifest_file_count_max"] == 0


def test_new_unclassified_module_fails_closed(tmp_path: Path) -> None:
    copied_package = tmp_path / "ypendulum_hfv2"
    shutil.copytree(PACKAGE_ROOT, copied_package)
    (copied_package / "unclassified_new_module.py").write_text("VALUE = 1\n", encoding="utf-8")
    audit = audit_physical_core(copied_package, MODULE_MANIFEST)
    assert audit.passed is False
    assert audit.unclassified_files == ("unclassified_new_module.py",)


def test_rotation_source_contains_no_normalization_or_projection_path() -> None:
    source = (PACKAGE_ROOT / "rigid" / "rotation.py").read_text(encoding="utf-8").lower()
    assert "normalize" not in source
    assert "normalise" not in source
    assert "svd" not in source
    assert "project_to" not in source


def test_core_files_remain_bounded_by_physical_responsibility() -> None:
    audit = audit_physical_core(PACKAGE_ROOT, MODULE_MANIFEST)
    for relative in audit.files:
        line_count = len((PACKAGE_ROOT / relative).read_text(encoding="utf-8").splitlines())
        assert line_count < 800, relative


def test_candidate_public_namespace_does_not_expose_solver_or_io() -> None:
    exported = set(ypendulum_hfv2.__all__)
    assert "MODEL_ID" in exported
    assert not any("solver" in name.lower() for name in exported)
    assert not any("validation" in name.lower() for name in exported)
    assert not any("hdf5" in name.lower() for name in exported)

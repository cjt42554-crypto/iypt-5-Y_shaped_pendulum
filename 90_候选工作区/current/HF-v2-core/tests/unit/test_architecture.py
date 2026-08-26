from __future__ import annotations

from pathlib import Path

import ypendulum_hfv2
from ypendulum_hfv2.audit.architecture import PHYSICAL_CORE_FILES, audit_physical_core

PACKAGE_ROOT = Path(ypendulum_hfv2.__file__).resolve().parent


def test_physical_core_has_no_reverse_dependency_or_silent_fallback() -> None:
    audit = audit_physical_core(PACKAGE_ROOT)
    assert audit.passed, audit
    assert audit.forbidden_imports == ()
    assert audit.solver_imports == ()
    assert audit.try_statement_count == 0
    assert audit.random_call_count == 0
    assert not any(name.startswith("ypendulum_hfv2.audit") for name in audit.imports)


def test_rotation_source_contains_no_normalization_or_projection_path() -> None:
    source = (PACKAGE_ROOT / "rigid" / "rotation.py").read_text(encoding="utf-8").lower()
    assert "normalize" not in source
    assert "normalise" not in source
    assert "svd" not in source
    assert "project_to" not in source


def test_core_files_remain_bounded_by_physical_responsibility() -> None:
    for relative in PHYSICAL_CORE_FILES:
        line_count = len((PACKAGE_ROOT / relative).read_text(encoding="utf-8").splitlines())
        assert line_count < 800, relative


def test_candidate_public_namespace_does_not_expose_solver_or_io() -> None:
    exported = set(ypendulum_hfv2.__all__)
    assert "MODEL_ID" in exported
    assert not any("solver" in name.lower() for name in exported)
    assert not any("validation" in name.lower() for name in exported)
    assert not any("hdf5" in name.lower() for name in exported)

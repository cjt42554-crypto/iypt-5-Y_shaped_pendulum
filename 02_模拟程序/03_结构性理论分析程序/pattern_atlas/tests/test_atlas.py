from __future__ import annotations

import ast
import copy
import hashlib
import json
import shutil
import sys
import tomllib
from pathlib import Path

import jsonschema
import pytest

from y_pendulum_pattern_atlas import ATLAS_IDENTITY, OUTPUT_SCHEMA, run_atlas
from y_pendulum_pattern_atlas import atlas as atlas_module
from y_pendulum_pattern_atlas import backend as backend_module
from y_pendulum_pattern_atlas.atlas import _load_config
from y_pendulum_pattern_atlas.source_manifest import (
    FORMAL_ATLAS_RELATIVE_PATH,
    FORMAL_BACKEND_RELATIVE_PATH,
    FORMAL_CONTRACTS_RELATIVE_PATH,
    FORMAL_THEORY_RELATIVE_PATH,
    ContractViolation,
    build_source_lock,
    canonical_json_bytes,
    load_json_strict,
    verify_source_manifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = backend_module.find_repository_root(PROJECT_ROOT)
PROJECT_RELATIVE = FORMAL_ATLAS_RELATIVE_PATH
CONFIG = PROJECT_ROOT / "configs" / "atlas_v1.json"
CONFIG_SCHEMA = PROJECT_ROOT / "schemas" / "atlas_config.schema.json"
OUTPUT_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "atlas_output.schema.json"
RUN_EVIDENCE_SCHEMA = PROJECT_ROOT / "schemas" / "atlas_run_evidence.schema.json"
SOURCE_LOCK = PROJECT_ROOT / "contracts" / "source_manifest_lock.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validate(instance: object, schema_path: Path) -> None:
    schema = load_json_strict(schema_path)
    jsonschema.Draft202012Validator(schema).validate(instance)


def _copy_bound_tree(tmp_path: Path) -> tuple[Path, Path]:
    temporary_repository = tmp_path / "repository"
    lock = load_json_strict(SOURCE_LOCK)
    for entry in lock["entries"]:
        source = REPOSITORY_ROOT / entry["path"]
        target = temporary_repository / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    temporary_lock = temporary_repository / PROJECT_RELATIVE / "contracts" / SOURCE_LOCK.name
    temporary_lock.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_LOCK, temporary_lock)
    return temporary_repository, temporary_repository / PROJECT_RELATIVE


def test_atlas_has_distinct_identity_and_closed_formal_backend_binding() -> None:
    assert ATLAS_IDENTITY == "YPS-IDEAL-TORUS-PATTERN-ATLAS-1.1"
    assert OUTPUT_SCHEMA == "YPS-FORMAL-PATTERN-ATLAS-OUTPUT-1.1"
    source_manifest = verify_source_manifest(PROJECT_ROOT, REPOSITORY_ROOT)
    backend = backend_module.load_formal_backend(REPOSITORY_ROOT)
    expected = REPOSITORY_ROOT / backend_module.FORMAL_BACKEND_RELATIVE_PATH
    assert backend.source_path == expected.resolve()
    assert backend.source_sha256 == _sha256(expected)
    assert source_manifest.source_manifest_sha256 == hashlib.sha256(
        canonical_json_bytes(source_manifest.manifest)
    ).hexdigest()
    entries = source_manifest.manifest["entries"]
    assert len(entries) == 15
    formal_prefix = f"{FORMAL_ATLAS_RELATIVE_PATH.as_posix()}/"
    formal_entries = [entry for entry in entries if entry["path"].startswith(formal_prefix)]
    assert len(formal_entries) == 12
    assert all("90_候选工作区" not in entry["path"] for entry in entries)


def test_release_metadata_and_exact_runtime_contract() -> None:
    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]
    assert project["name"] == "y-pendulum-pattern-atlas"
    assert project["version"] == "1.1.0"
    assert project["requires-python"] == ">=3.12,<3.13"
    assert project["dependencies"] == [
        "jsonschema==4.10.3",
        "matplotlib==3.8.4",
        "numpy==1.26.4",
        "scipy==1.11.4",
    ]
    assert project["optional-dependencies"]["dev"] == [
        "pytest==8.4.2",
        "ruff==0.16.5",
    ]


def test_repository_root_discovery_and_formal_checkout_location(tmp_path: Path) -> None:
    assert PROJECT_ROOT == (REPOSITORY_ROOT / FORMAL_ATLAS_RELATIVE_PATH).resolve()
    for start in (
        PROJECT_ROOT,
        CONFIG,
        PROJECT_ROOT / "src/y_pendulum_pattern_atlas/atlas.py",
    ):
        assert backend_module.find_repository_root(start) == REPOSITORY_ROOT
    outside = tmp_path / "not-a-repository" / "nested"
    outside.mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="Could not locate the repository root"):
        backend_module.find_repository_root(outside)
    with pytest.raises(ContractViolation, match="formal atlas must run from"):
        build_source_lock(PROJECT_ROOT, tmp_path)


def test_installed_wheel_layout_fails_closed_before_reading_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed_layout = tmp_path / "venv/lib/python3.12"
    monkeypatch.setattr(atlas_module, "PROJECT_ROOT", installed_layout)
    output = tmp_path / "must-not-exist"
    with pytest.raises(
        ContractViolation,
        match="repository-bound formal atlas must run from the formal repository checkout",
    ):
        run_atlas(
            tmp_path / "missing-config.json",
            output,
            repository_root=REPOSITORY_ROOT,
            smoke=True,
        )
    assert not output.exists()


def test_formal_production_tree_contains_no_second_ode_or_integrator() -> None:
    production_root = PROJECT_ROOT / "src/y_pendulum_pattern_atlas"
    source_paths = sorted(production_root.rglob("*.py"))
    assert source_paths
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        assert "solve_ivp" not in source, path
        assert "odeint" not in source, path
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "scipy.integrate", path
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert not node.name.casefold().endswith("rhs"), path


def test_configuration_schema_is_closed_and_common_period_is_integral() -> None:
    config = _load_config(CONFIG)
    _validate(config, CONFIG_SCHEMA)
    assert config["model_id"] == "FWD-TORUS-1.0"
    assert config["analysis"]["slow_cycles"] == 18
    assert "experimental calibration" in config["scope"]


@pytest.mark.parametrize(
    ("field", "value"),
    (("p", 4.5), ("p", "4"), ("q", 3.5), ("q", "3")),
)
def test_configuration_rejects_fractional_or_string_target_indices(
    tmp_path: Path, field: str, value: object
) -> None:
    config = copy.deepcopy(load_json_strict(CONFIG))
    config["targets"][0][field] = value
    path = tmp_path / "invalid.json"
    _write_json(path, config)
    with pytest.raises(ContractViolation):
        _load_config(path)


def test_configuration_rejects_unknown_nested_key(tmp_path: Path) -> None:
    config = copy.deepcopy(load_json_strict(CONFIG))
    config["analysis"]["unreviewed_switch"] = True
    path = tmp_path / "invalid.json"
    _write_json(path, config)
    with pytest.raises(ContractViolation):
        _load_config(path)


@pytest.mark.parametrize(
    ("document", "message"),
    (
        ('{"key": 1, "key": 2}', "duplicate JSON key"),
        ('{"key": NaN}', "non-finite JSON constant"),
    ),
)
def test_strict_json_loader_rejects_duplicate_keys_and_non_finite_constants(
    tmp_path: Path, document: str, message: str
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(document, encoding="utf-8")
    with pytest.raises(ContractViolation, match=message):
        load_json_strict(path)


def test_backend_import_restores_sys_path_on_success_and_wrong_path_failure() -> None:
    before = list(sys.path)
    backend_module.load_formal_backend(REPOSITORY_ROOT)
    assert sys.path == before
    with pytest.raises(ContractViolation, match="wrong formal backend path"):
        backend_module.load_formal_backend(
            REPOSITORY_ROOT,
            formal_backend_relative_path=Path("02_模拟程序/wrong_backend.py"),
        )
    assert sys.path == before


@pytest.mark.parametrize(
    "relative_path",
    (
        FORMAL_THEORY_RELATIVE_PATH.as_posix(),
        FORMAL_CONTRACTS_RELATIVE_PATH.as_posix(),
        FORMAL_BACKEND_RELATIVE_PATH.as_posix(),
    ),
)
def test_source_manifest_fails_closed_on_theory_contracts_or_torus_drift(
    tmp_path: Path, relative_path: str
) -> None:
    repository, project = _copy_bound_tree(tmp_path)
    drifted = repository / relative_path
    drifted.write_bytes(drifted.read_bytes() + b"\nformal atlas deliberate drift probe\n")
    with pytest.raises(ContractViolation, match="hash_drift"):
        verify_source_manifest(project, repository)


def test_source_manifest_fails_closed_on_runtime_drift(tmp_path: Path) -> None:
    lock = copy.deepcopy(load_json_strict(SOURCE_LOCK))
    lock["runtime_identity"]["python_version"] = "3.12.999"
    lock["runtime_identity_sha256"] = hashlib.sha256(
        canonical_json_bytes(lock["runtime_identity"])
    ).hexdigest()
    drifted_lock = tmp_path / "runtime-drift-lock.json"
    _write_json(drifted_lock, lock)
    with pytest.raises(ContractViolation, match="runtime identity drift"):
        verify_source_manifest(PROJECT_ROOT, REPOSITORY_ROOT, lock_path=drifted_lock)


def test_smoke_output_schemas_and_all_artifacts_are_byte_deterministic(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    payload = run_atlas(CONFIG, first, repository_root=REPOSITORY_ROOT, smoke=True)
    run_atlas(CONFIG, second, repository_root=REPOSITORY_ROOT, smoke=True)

    _validate(payload, OUTPUT_SCHEMA_PATH)
    evidence = load_json_strict(first / "atlas_run_evidence.json")
    _validate(evidence, RUN_EVIDENCE_SCHEMA)
    assert evidence["execution"]["atlas_case_count"] == 1
    assert evidence["execution"]["primary_result_trajectory_count"] == 3

    for relative in (
        "atlas_results.json",
        "atlas_run_evidence.json",
        "atlas_summary.csv",
        "geometry_tolerance.csv",
        "figures/compensation_accuracy.svg",
        "figures/compensation_accuracy.png",
        "artifact_manifest.json",
    ):
        assert (first / relative).read_bytes() == (second / relative).read_bytes(), relative

    payload_with_extra = copy.deepcopy(payload)
    payload_with_extra["unreviewed_output"] = True
    with pytest.raises(jsonschema.ValidationError):
        _validate(payload_with_extra, OUTPUT_SCHEMA_PATH)

    evidence_with_extra = copy.deepcopy(evidence)
    evidence_with_extra["optimizer"]["cases"][0]["unreviewed_state"] = "hidden"
    with pytest.raises(jsonschema.ValidationError):
        _validate(evidence_with_extra, RUN_EVIDENCE_SCHEMA)


def test_smoke_numerical_gates_are_not_physical_or_experimental_qualification(
    tmp_path: Path,
) -> None:
    payload = run_atlas(
        CONFIG,
        tmp_path / "smoke",
        repository_root=REPOSITORY_ROOT,
        smoke=True,
    )
    assert all(payload["validation"]["aggregate_gates"].values())
    assert payload["model_identity"]["backend_model_id"] == "FWD-TORUS-1.0"
    assert payload["model_identity"]["tuning_interpretation"] == (
        "ideal_model_internal_not_experimental_calibration"
    )
    assert "experimental validation" in payload["claim_limit"]
    for case in payload["cases"]:
        for name in ("zero", "quartic", "numeric"):
            assert min(case[name]["minimum_guards"].values()) > 0.0

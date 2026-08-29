from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import jsonschema
import pytest

from ypendulum_static_reference import identity as python_identity

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "schemas/static_run_evidence.schema.json"
PROBE_PATH = PROJECT_ROOT / "tools/runtime_probe.py"

PROBE_SPEC = importlib.util.spec_from_file_location("formal_runtime_probe", PROBE_PATH)
assert PROBE_SPEC is not None
assert PROBE_SPEC.loader is not None
runtime_probe = importlib.util.module_from_spec(PROBE_SPEC)
PROBE_SPEC.loader.exec_module(runtime_probe)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _run_probe(output: Path, project_root: Path = PROJECT_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(PROBE_PATH),
            "--project-root",
            str(project_root),
            "--output",
            str(output),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def formal_probe_runs(tmp_path_factory: pytest.TempPathFactory) -> tuple[bytes, dict]:
    temporary = tmp_path_factory.mktemp("formal-static-evidence")
    first_output = temporary / "first.json"
    second_output = temporary / "second.json"
    first = _run_probe(first_output)
    second = _run_probe(second_output)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    first_bytes = first_output.read_bytes()
    second_bytes = second_output.read_bytes()
    assert first.stdout.encode("utf-8") == first_bytes
    assert second.stdout.encode("utf-8") == second_bytes
    assert first_bytes == second_bytes
    return first_bytes, json.loads(first_bytes)


def test_formal_run_evidence_is_deterministic_closed_and_unqualified(
    formal_probe_runs: tuple[bytes, dict],
) -> None:
    _, evidence = formal_probe_runs
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(evidence)

    assert evidence["schema"] == "YPS-NO-CONTACT-STATIC-RUN-EVIDENCE-1.1"
    assert evidence["model_identity"] == {
        "model_id": "YPS-NO-CONTACT-STATIC-REFERENCE-1.1",
        "release_status": "FORMAL_RELEASE_STATIC_REFERENCE_ONLY",
        "capability": "position_orientation_conservative_no_contact_static_reference_only",
        "claim_ceiling": (
            "FORMAL_STATIC_REFERENCE_IMPLEMENTATION_AND_RUNTIME_EVIDENCE_ONLY"
        ),
        "qualification_status": "NO_FORMAL_NUMERICAL_QUALIFICATION_CARRIED",
    }
    assert evidence["optimizer_state"]["status_record_only"] == 2
    assert evidence["optimizer_state"]["success_record_only"] is False
    assert evidence["diagnostics"]["implementation_diagnostics_passed"] is True
    assert all(evidence["diagnostics"]["independent_checks"].values())

    manifest = evidence["source_manifest"]
    assert evidence["source_manifest_sha256"] == hashlib.sha256(
        _canonical_json_bytes(manifest)
    ).hexdigest()
    assert len(manifest["entries"]) == 26
    assert len({entry["path"] for entry in manifest["entries"]}) == 26
    for entry in manifest["entries"]:
        source = PROJECT_ROOT / entry["path"]
        assert source.resolve().is_relative_to(PROJECT_ROOT)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == entry["sha256"]

    singleton_roles = set(runtime_probe.SINGLETON_SOURCE_ROLES)
    roles = [entry["role"] for entry in manifest["entries"]]
    assert all(roles.count(role) == 1 for role in singleton_roles)
    assert roles.count("production_source") == len(runtime_probe.EXPECTED_PRODUCTION_PATHS)
    assert not (PROJECT_ROOT / "outputs").exists()


@pytest.mark.parametrize(
    ("section", "field", "invalid"),
    (
        ("model_identity", "model_id", "YPS-NO-CONTACT-STATIC-REFERENCE-DRAFT-1.1"),
        ("model_identity", "release_status", "CANDIDATE"),
        ("model_identity", "claim_ceiling", "FORMAL_NUMERICAL_QUALIFICATION"),
        ("model_identity", "qualification_status", "QUALIFIED"),
        ("optimizer_state", "unreviewed_state", "hidden"),
    ),
)
def test_run_evidence_schema_rejects_identity_and_extra_field_drift(
    formal_probe_runs: tuple[bytes, dict],
    section: str,
    field: str,
    invalid: object,
) -> None:
    _, evidence = formal_probe_runs
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    mutated = copy.deepcopy(evidence)
    mutated[section][field] = invalid
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(mutated)


def test_run_evidence_schema_rejects_escaping_source_path(
    formal_probe_runs: tuple[bytes, dict],
) -> None:
    _, evidence = formal_probe_runs
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    mutated = copy.deepcopy(evidence)
    mutated["source_manifest"]["entries"][0]["path"] = "../../outside.py"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(mutated)


@pytest.mark.parametrize("drift_target", ("model_identity", "contract", "schema"))
def test_identity_bindings_fail_closed_in_memory(drift_target: str) -> None:
    identity = json.loads((PROJECT_ROOT / "model_identity.json").read_text(encoding="utf-8"))
    contract = json.loads(
        (PROJECT_ROOT / "contracts/static_reference_run_contract.json").read_text(
            encoding="utf-8"
        )
    )
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if drift_target == "model_identity":
        identity["model_id"] += "-DRIFT"
    elif drift_target == "contract":
        contract["claim_ceiling"] = "FORMAL_NUMERICAL_QUALIFICATION"
    else:
        schema["properties"]["model_identity"]["properties"]["model_id"]["const"] += (
            "-DRIFT"
        )
    with pytest.raises(ValueError):
        runtime_probe._validate_identity_bindings(
            identity,
            contract,
            schema,
            python_identity,
        )


@pytest.mark.parametrize("mutation", ("duplicate_path", "duplicate_role", "escape"))
def test_source_manifest_validation_fails_closed(
    formal_probe_runs: tuple[bytes, dict],
    mutation: str,
) -> None:
    _, evidence = formal_probe_runs
    entries = copy.deepcopy(evidence["source_manifest"]["entries"])
    if mutation == "duplicate_path":
        entries[-1] = copy.deepcopy(entries[0])
    elif mutation == "duplicate_role":
        contract_entry = next(
            entry for entry in entries if entry["role"] == "canonical_contract"
        )
        contract_entry["role"] = "model_identity"
    else:
        entries[0]["path"] = "../outside.py"
    with pytest.raises(ValueError):
        runtime_probe._validate_source_entries(PROJECT_ROOT, entries)


def test_project_root_mismatch_is_rejected_before_evidence_generation(tmp_path: Path) -> None:
    result = _run_probe(tmp_path / "evidence.json", tmp_path)
    assert result.returncode != 0
    assert "--project-root must resolve to the formal root" in result.stderr


def test_import_file_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    external = tmp_path / "external_identity.py"
    external.write_text("# not the formal module\n", encoding="utf-8")
    fake = ModuleType("external_identity")
    fake.__file__ = str(external)
    with pytest.raises(ImportError, match="imported from"):
        runtime_probe._require_module_file(
            fake,
            PROJECT_ROOT / "src/ypendulum_static_reference/identity.py",
            "identity",
        )


def test_runtime_identity_rejects_unsupported_python() -> None:
    runtime = runtime_probe._runtime_identity()
    runtime["python"] = "3.13.0"
    with pytest.raises(ValueError, match="Python"):
        runtime_probe._validate_runtime_identity(runtime)

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import jsonschema

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = PROJECT_ROOT / "outputs/canonical_static_run_evidence.json"
SCHEMA_PATH = PROJECT_ROOT / "schemas/static_run_evidence.schema.json"


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def test_canonical_run_evidence_is_closed_bound_and_status_2_recorded() -> None:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(evidence)
    assert evidence["optimizer_state"]["status_record_only"] == 2
    assert evidence["optimizer_state"]["success_record_only"] is False
    assert evidence["diagnostics"]["implementation_diagnostics_passed"] is True
    assert evidence["model_identity"]["qualification_status"] == (
        "NO_FORMAL_NUMERICAL_QUALIFICATION_CARRIED"
    )

    manifest = evidence["source_manifest"]
    assert evidence["source_manifest_sha256"] == hashlib.sha256(
        _canonical_json_bytes(manifest)
    ).hexdigest()
    for entry in manifest["entries"]:
        path = PROJECT_ROOT / entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]

    production_paths = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "src/ypendulum_static_reference").rglob("*.py")
    }
    bound_production_paths = {
        entry["path"]
        for entry in manifest["entries"]
        if entry["role"] == "production_source"
    }
    assert bound_production_paths == production_paths


def test_run_evidence_schema_rejects_extra_fields() -> None:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    mutated = copy.deepcopy(evidence)
    mutated["optimizer_state"]["unreviewed_state"] = "hidden"
    try:
        jsonschema.Draft202012Validator(schema).validate(mutated)
    except jsonschema.ValidationError:
        return
    raise AssertionError("closed run-evidence schema accepted an extra nested field")

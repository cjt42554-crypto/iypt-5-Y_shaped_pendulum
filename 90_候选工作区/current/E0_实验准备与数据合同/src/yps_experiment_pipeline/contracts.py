"""Strict JSON contracts and provenance helpers for E0."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

STAGE_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = STAGE_ROOT / "schemas"
TEMPLATE_ROOT = STAGE_ROOT / "templates"
STAGE_RELATIVE = Path("90_候选工作区/current/E0_实验准备与数据合同")

TEMPLATE_SCHEMA_MAP = {
    "apparatus_measurements.template.json": "apparatus_measurements.schema.json",
    "material_test_manifest.template.json": "material_test_manifest.schema.json",
    "camera_rig.template.json": "camera_rig.schema.json",
    "first_round_plan.template.json": "experiment_run.schema.json",
}


class ContractError(ValueError):
    """Raised when an E0 machine contract fails closed."""


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_schema(name: str, *, schema_root: Path = SCHEMA_ROOT) -> dict[str, Any]:
    path = schema_root / name
    if not path.is_file():
        raise ContractError(f"schema not found: {name}")
    schema = load_json(path)
    Draft202012Validator.check_schema(schema)
    return schema


def validation_errors(
    schema_name: str,
    document: Any,
    *,
    schema_root: Path = SCHEMA_ROOT,
) -> list[str]:
    validator = Draft202012Validator(load_schema(schema_name, schema_root=schema_root))
    errors = []
    for error in sorted(validator.iter_errors(document), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"{location}: {error.message}")
    return errors


def validate_document(
    schema_name: str,
    document: Any,
    *,
    schema_root: Path = SCHEMA_ROOT,
) -> None:
    errors = validation_errors(schema_name, document, schema_root=schema_root)
    if errors:
        raise ContractError("; ".join(errors))


def validate_all_templates(
    *,
    schema_root: Path = SCHEMA_ROOT,
    template_root: Path = TEMPLATE_ROOT,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for template_name, schema_name in sorted(TEMPLATE_SCHEMA_MAP.items()):
        document = load_json(template_root / template_name)
        validate_document(schema_name, document, schema_root=schema_root)
        result[template_name] = "VALID"
    return result


def iter_source_types(value: Any):
    if isinstance(value, dict):
        if "source_type" in value:
            yield value
        for child in value.values():
            yield from iter_source_types(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_source_types(child)


def assert_no_fake_measurements(document: Any) -> None:
    """Reject measured claims without a real raw-data binding."""

    for record in iter_source_types(document):
        source_type = record.get("source_type")
        if source_type == "MEASURED":
            digest = record.get("raw_data_sha256")
            repeats = record.get("raw_repeats")
            if not isinstance(digest, str) or len(digest) != 64:
                raise ContractError("MEASURED record lacks raw_data_sha256")
            if not isinstance(repeats, list) or not repeats:
                raise ContractError("MEASURED record lacks raw_repeats")
        if source_type == "UNSET_REQUIRES_HUMAN" and record.get("value_si") is not None:
            raise ContractError("UNSET_REQUIRES_HUMAN record contains value_si")


def assert_templates_are_human_unset(*, template_root: Path = TEMPLATE_ROOT) -> None:
    for template_name in TEMPLATE_SCHEMA_MAP:
        document = load_json(template_root / template_name)
        assert_no_fake_measurements(document)
        encoded = canonical_json_bytes(document)
        if b'"source_type":"MEASURED"' in encoded:
            raise ContractError(f"template contains MEASURED claim: {template_name}")

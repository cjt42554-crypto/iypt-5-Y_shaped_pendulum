"""Closed source and runtime binding for the candidate ideal-torus atlas."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

FORMAL_THEORY_RELATIVE_PATH = Path("01_最终理论/01-前向预测理论.md")
FORMAL_CONTRACTS_RELATIVE_PATH = Path(
    "02_模拟程序/01_前向预测数值求解器/"
    "y_pendulum_forward_solver/y_pendulum_forward/contracts.py"
)
FORMAL_BACKEND_RELATIVE_PATH = Path(
    "02_模拟程序/01_前向预测数值求解器/"
    "y_pendulum_forward_solver/y_pendulum_forward/torus.py"
)
CONFIG_RELATIVE_TO_PROJECT = Path("configs/atlas_v1.json")
LOCK_RELATIVE_TO_PROJECT = Path("contracts/source_manifest_lock.json")
LOCK_SCHEMA_RELATIVE_TO_PROJECT = Path("schemas/source_manifest_lock.schema.json")
SOURCE_MANIFEST_SCHEMA = "YPS-FORMAL-PATTERN-ATLAS-SOURCE-MANIFEST-1.0"
SOURCE_LOCK_SCHEMA = "YPS-FORMAL-PATTERN-ATLAS-SOURCE-LOCK-1.0"
ATLAS_IDENTITY = "YPS-IDEAL-TORUS-PATTERN-ATLAS-DRAFT-1.1"
RUNTIME_PACKAGES = ("jsonschema", "matplotlib", "numpy", "scipy")


class ContractViolation(ValueError):
    """Raised when a closed JSON or source/runtime contract is violated."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_canonical_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def load_json_strict(path: Path) -> Any:
    """Load JSON while rejecting duplicate keys and non-finite constants."""

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ContractViolation(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    def reject_constant(token: str) -> None:
        raise ContractViolation(f"non-finite JSON constant {token!r} in {path}")

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as error:
        raise ContractViolation(f"invalid JSON in {path}: {error}") from error


def validate_json_contract(instance: Any, schema_path: Path, *, label: str) -> None:
    schema = load_json_strict(schema_path)
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise ContractViolation(f"{label} contract violation at {location}: {first.message}")


def runtime_identity() -> dict[str, Any]:
    return {
        "schema": "YPS-FORMAL-PATTERN-ATLAS-RUNTIME-IDENTITY-1.0",
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "packages": {
            package: importlib.metadata.version(package) for package in RUNTIME_PACKAGES
        },
    }


def _repository_relative(path: Path, repository_root: Path) -> str:
    try:
        return path.resolve().relative_to(repository_root.resolve()).as_posix()
    except ValueError as error:
        raise ContractViolation(f"bound path escapes repository root: {path}") from error


def discover_source_entries(
    project_root: Path, repository_root: Path
) -> list[dict[str, str]]:
    """Discover every result-bearing source/config/schema input with a stable role."""

    project = project_root.resolve()
    repository = repository_root.resolve()
    candidates: list[tuple[str, Path]] = [
        ("formal_theory", repository / FORMAL_THEORY_RELATIVE_PATH),
        ("formal_contracts", repository / FORMAL_CONTRACTS_RELATIVE_PATH),
        ("formal_backend", repository / FORMAL_BACKEND_RELATIVE_PATH),
        ("configuration", project / CONFIG_RELATIVE_TO_PROJECT),
        ("build_metadata", project / "pyproject.toml"),
    ]
    candidates.extend(
        ("production_source", path)
        for path in sorted((project / "src" / "y_pendulum_pattern_atlas").rglob("*.py"))
    )
    candidates.extend(
        ("schema", path) for path in sorted((project / "schemas").glob("*.json"))
    )

    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for role, path in candidates:
        relative = _repository_relative(path, repository)
        if relative in seen:
            raise ContractViolation(f"duplicate source-manifest path: {relative}")
        seen.add(relative)
        if not path.is_file():
            raise ContractViolation(f"bound source is missing: {relative}")
        entries.append({"role": role, "path": relative, "sha256": sha256_file(path)})
    return sorted(entries, key=lambda item: (item["path"], item["role"]))


def build_source_lock(project_root: Path, repository_root: Path) -> dict[str, Any]:
    runtime = runtime_identity()
    return {
        "schema": SOURCE_LOCK_SCHEMA,
        "atlas_identity": ATLAS_IDENTITY,
        "entries": discover_source_entries(project_root, repository_root),
        "runtime_identity": runtime,
        "runtime_identity_sha256": sha256_canonical_json(runtime),
    }


@dataclass(frozen=True)
class BoundSourceManifest:
    manifest: dict[str, Any]
    lock_path: Path
    lock_sha256: str

    @property
    def source_manifest_sha256(self) -> str:
        return sha256_canonical_json(self.manifest)

    @property
    def entries_by_role(self) -> dict[str, list[dict[str, str]]]:
        grouped: dict[str, list[dict[str, str]]] = {}
        for entry in self.manifest["entries"]:
            grouped.setdefault(str(entry["role"]), []).append(entry)
        return grouped


def verify_source_manifest(
    project_root: Path,
    repository_root: Path,
    *,
    lock_path: Path | None = None,
) -> BoundSourceManifest:
    """Fail closed on any source-set, byte-hash, or runtime-identity drift."""

    project = project_root.resolve()
    repository = repository_root.resolve()
    selected_lock = (
        lock_path.resolve()
        if lock_path is not None
        else (project / LOCK_RELATIVE_TO_PROJECT).resolve()
    )
    lock = load_json_strict(selected_lock)
    validate_json_contract(
        lock,
        project / LOCK_SCHEMA_RELATIVE_TO_PROJECT,
        label="source manifest lock",
    )
    if lock["schema"] != SOURCE_LOCK_SCHEMA or lock["atlas_identity"] != ATLAS_IDENTITY:
        raise ContractViolation("source manifest lock identity mismatch")

    actual_entries = discover_source_entries(project, repository)
    if lock["entries"] != actual_entries:
        locked = {(item["role"], item["path"]): item["sha256"] for item in lock["entries"]}
        actual = {(item["role"], item["path"]): item["sha256"] for item in actual_entries}
        missing = sorted(set(locked) - set(actual))
        unexpected = sorted(set(actual) - set(locked))
        drifted = sorted(key for key in set(locked) & set(actual) if locked[key] != actual[key])
        raise ContractViolation(
            "source manifest drift: "
            f"missing={missing}, unexpected={unexpected}, hash_drift={drifted}"
        )

    actual_runtime = runtime_identity()
    actual_runtime_hash = sha256_canonical_json(actual_runtime)
    if lock["runtime_identity"] != actual_runtime:
        raise ContractViolation("runtime identity drift")
    if lock["runtime_identity_sha256"] != actual_runtime_hash:
        raise ContractViolation("runtime identity hash mismatch")

    manifest = {
        "schema": SOURCE_MANIFEST_SCHEMA,
        "atlas_identity": ATLAS_IDENTITY,
        "entries": actual_entries,
        "runtime_identity": actual_runtime,
        "runtime_identity_sha256": actual_runtime_hash,
    }
    return BoundSourceManifest(
        manifest=manifest,
        lock_path=selected_lock,
        lock_sha256=sha256_file(selected_lock),
    )

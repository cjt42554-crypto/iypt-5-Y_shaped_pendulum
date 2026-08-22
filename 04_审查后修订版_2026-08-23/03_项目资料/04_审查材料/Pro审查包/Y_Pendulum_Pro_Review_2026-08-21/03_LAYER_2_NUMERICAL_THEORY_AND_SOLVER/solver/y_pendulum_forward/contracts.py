"""Shared contracts and result types for the forward numerical backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
from typing import Any

import numpy as np


THEORY_SHA256 = "7eaf18e30087438507aef73c481b49e5b1427a146d79c0fd2b35ca10dc02cdb2"
PROGRAM_VERSION = "2.0.0-research"
CONFIG_SCHEMA_VERSION = "YPS-FWD-CONFIG-1.0"
MIN_SOLVER_RTOL = 100.0 * np.finfo(float).eps
MAX_UNIFORM_SAMPLES = 2_000_001
MAX_NOMINAL_SOLVER_STEPS = 2_000_000
MAX_ELEMENTS_PER_BRANCH = 512
MAX_TOTAL_CABLE_ELEMENTS = 1024
MAX_STATIC_MULTISTART = 32
MAX_STATIC_ITERATIONS = 20_000

PHYSICAL_STATUSES = {
    "COMPLETED",
    "INVALID_INPUT",
    "OUT_OF_SCOPE",
    "REGULARITY_LOSS",
}


@dataclass(frozen=True)
class ValidationIssue:
    """One fail-closed input or observation predicate failure."""

    code: str
    path: str
    actual: Any
    expected: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "actual": json_safe(self.actual),
            "expected": self.expected,
        }


@dataclass
class SimulationResult:
    """Common result container used by both forward-theory backends.

    ``contract_status`` is populated only when the numerical run can map to a
    frozen physical-contract outcome.  A solver failure leaves it empty; it is
    never mislabeled as a physical ``REGULARITY_LOSS``.
    """

    model_id: str
    contract_status: list[str]
    numerical_status: str
    tau: float
    returned_interval: str
    time: np.ndarray
    state: dict[str, Any] = field(default_factory=dict)
    derived: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    observations: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "program_version": PROGRAM_VERSION,
            "numerical_model_id": self.metadata.get("numerical_model_id"),
            "theory_sha256": THEORY_SHA256,
            "units": "SI",
            "contract_status": list(self.contract_status),
            "numerical_status": self.numerical_status,
            "tau": finite_or_string(self.tau),
            "returned_interval": self.returned_interval,
            "sample_count": int(self.time.size),
            "events": json_safe(self.events),
            "diagnostics": diagnostics_summary(self.diagnostics),
            "observations": observation_summary(self.observations),
            "metadata": json_safe(self.metadata),
        }


def finite_or_string(value: float) -> float | str:
    value = float(value)
    if np.isposinf(value):
        return "+inf"
    if np.isneginf(value):
        return "-inf"
    if np.isnan(value):
        return "nan"
    return value


def json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, float):
        return finite_or_string(value)
    return value


def observation_summary(observations: dict[str, Any]) -> dict[str, Any]:
    if not observations:
        return {}
    large_fields = {
        "time",
        "record_time",
        "model_time",
        "values",
        "valid_mask",
        "event_ambiguous_mask",
    }
    result = {
        key: json_safe(value)
        for key, value in observations.items()
        if key not in large_fields
    }
    if "time" in observations:
        result["sample_count"] = int(np.asarray(observations["time"]).size)
    if "valid_mask" in observations:
        mask = np.asarray(observations["valid_mask"], dtype=bool)
        result["valid_count"] = int(mask.sum())
    return result


def diagnostics_summary(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Keep array diagnostics in NPZ while making result.json compact."""

    large_fields = {
        "reaction_algebraic",
        "P_base_algebraic",
        "sampled_guard_series",
        "sampled_guard_component_series",
    }
    result = {
        key: json_safe(value)
        for key, value in diagnostics.items()
        if key not in large_fields
    }
    array_fields: dict[str, Any] = {}
    for key in sorted(large_fields & set(diagnostics)):
        value = diagnostics[key]
        if isinstance(value, dict):
            array_fields[key] = {
                child_key: list(np.asarray(child).shape)
                for child_key, child in value.items()
            }
        else:
            array_fields[key] = list(np.asarray(value).shape)
    if array_fields:
        result["array_fields_in_trajectory_npz"] = array_fields
    return result


def canonical_json_bytes(config: Any) -> bytes:
    return json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def config_sha256(config: Any) -> str:
    return sha256(canonical_json_bytes(config)).hexdigest()


def source_tree_sha256() -> str:
    """Hash every executable/package identity file at the instant a run begins."""

    package_root = Path(__file__).resolve().parent
    project_root = package_root.parent
    paths = [
        *sorted(package_root.glob("*.py")),
        project_root / "run.py",
        project_root / "pyproject.toml",
        project_root / "requirements.txt",
    ]
    digest = sha256()
    for path in sorted(
        paths,
        key=lambda item: item.relative_to(project_root).as_posix(),
    ):
        relative = path.relative_to(project_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "NOT_INSTALLED"


def runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": _package_version("scipy"),
        "matplotlib": _package_version("matplotlib"),
        "platform": platform.platform(),
    }


def _safe_payload_hash(payload: Any) -> str:
    try:
        return config_sha256(payload)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return "UNHASHABLE_INVALID_CONFIG"


def numerical_model_id(config: dict[str, Any]) -> str:
    """Return a closed identifier for the requested discretization family."""

    numerics = config.get("numerics")
    method = numerics.get("method") if isinstance(numerics, dict) else None
    if config.get("model_id") == "FWD-CABLE-1.0":
        if isinstance(numerics, dict) and "method" not in numerics:
            method = "Radau"
        suffix = (
            method
            if isinstance(method, str)
            and method in {"Radau", "BDF", "DOP853"}
            else "UNRESOLVED"
        )
        return f"NUM-FWD-CABLE-P1-{suffix}-1.0"
    if config.get("model_id") == "FWD-TORUS-1.0":
        if isinstance(numerics, dict) and "method" not in numerics:
            method = "DOP853"
        suffix = (
            method
            if isinstance(method, str) and method in {"DOP853", "Radau"}
            else "UNRESOLVED"
        )
        return f"NUM-FWD-TORUS-{suffix}-1.0"
    return "NUM-FWD-UNRESOLVED-1.0"


def run_identity_hashes(config: dict[str, Any]) -> dict[str, Any]:
    physical_keys = {
        "schema_version",
        "model_id",
        "theory_sha256",
        "units",
        "physical",
        "inputs",
        "initial_state",
    }
    physical_payload = {
        key: config[key] for key in sorted(physical_keys) if key in config
    }
    return {
        "program_version": PROGRAM_VERSION,
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "numerical_model_id": numerical_model_id(config),
        "theory_sha256": THEORY_SHA256,
        "units": "SI",
        "config_sha256": _safe_payload_hash(config),
        "physical_input_sha256": _safe_payload_hash(physical_payload),
        "numerical_config_sha256": _safe_payload_hash(config.get("numerics", {})),
        "observation_input_sha256": _safe_payload_hash(config.get("observation")),
        "source_tree_sha256": source_tree_sha256(),
        "runtime_versions": runtime_versions(),
    }


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(
            handle,
            parse_constant=lambda token: _reject_nonstandard_json_constant(
                token
            ),
            object_pairs_hook=_strict_json_object,
        )
    if not isinstance(data, dict):
        raise ValueError("configuration root must be a JSON object")
    return data


def _reject_nonstandard_json_constant(token: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant is forbidden: {token}")


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key is forbidden: {key}")
        result[key] = value
    return result


def is_finite_number(value: Any) -> bool:
    if not isinstance(value, (int, float, np.integer, np.floating)) or isinstance(
        value, bool
    ):
        return False
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return bool(np.isfinite(converted))


def json_input_issues(
    value: Any, path: str = "config"
) -> list[ValidationIssue]:
    """Validate the whole input as finite, acyclic, canonical JSON.

    This is deliberately stricter than accepting arbitrary Python mappings.
    Every successful run must be serializable and hashable as the exact input
    snapshot that was executed.
    """

    issues: list[ValidationIssue] = []
    active_containers: set[int] = set()

    def actual_summary(item: Any) -> Any:
        if isinstance(item, float) and not np.isfinite(item):
            return finite_or_string(item)
        if isinstance(item, int) and not isinstance(item, bool):
            try:
                text = str(item)
            except ValueError:
                return f"<integer bit_length={item.bit_length()}>"
            return item if len(text) <= 128 else f"<integer digits={len(text)}>"
        if isinstance(item, (type(None), bool, str)):
            return item
        return f"<{type(item).__name__}>"

    def visit(item: Any, item_path: str) -> None:
        if item is None or isinstance(item, (bool, str)):
            return
        if isinstance(item, int) and not isinstance(item, bool):
            return
        if isinstance(item, float):
            if not np.isfinite(item):
                issues.append(
                    ValidationIssue(
                        "NONFINITE_JSON_NUMBER",
                        item_path,
                        actual_summary(item),
                        "finite JSON number",
                    )
                )
            return
        if not isinstance(item, (dict, list)):
            issues.append(
                ValidationIssue(
                    "NON_JSON_TYPE",
                    item_path,
                    actual_summary(item),
                    "JSON null, boolean, string, finite number, array, or object",
                )
            )
            return
        identity = id(item)
        if identity in active_containers:
            issues.append(
                ValidationIssue(
                    "CYCLIC_JSON",
                    item_path,
                    f"<{type(item).__name__} cycle>",
                    "acyclic JSON container",
                )
            )
            return
        active_containers.add(identity)
        try:
            if isinstance(item, list):
                for index, child in enumerate(item):
                    visit(child, f"{item_path}[{index}]")
                return
            for key, child in item.items():
                if not isinstance(key, str):
                    issues.append(
                        ValidationIssue(
                            "NON_STRING_JSON_KEY",
                            f"{item_path}.<key>",
                            actual_summary(key),
                            "JSON object key string",
                        )
                    )
                    continue
                visit(child, f"{item_path}.{key}")
        finally:
            active_containers.remove(identity)

    visit(value, path)
    if issues:
        return issues
    try:
        canonical_json_bytes(value)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        issues.append(
            ValidationIssue(
                "CANONICAL_JSON_UNAVAILABLE",
                path,
                f"<{type(exc).__name__}>",
                "canonically serializable finite JSON input",
            )
        )
    return issues


def safe_uniform_sample_count(
    span: Any,
    step: Any,
    *,
    maximum_samples: int = MAX_UNIFORM_SAMPLES,
) -> int | None:
    """Return a safe base-grid count, reserving one optional endpoint sample."""

    if (
        not is_finite_number(span)
        or not is_finite_number(step)
        or float(span) < 0.0
        or float(step) <= 0.0
    ):
        return None
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        ratio = float(np.divide(float(span), float(step)))
    if not np.isfinite(ratio) or ratio < 0.0:
        return None
    count = int(np.floor(ratio + 1e-12)) + 1
    return count if 1 <= count < maximum_samples else None


def safe_nominal_interval_count(
    span: Any,
    step: Any,
    *,
    maximum_intervals: int = MAX_NOMINAL_SOLVER_STEPS,
) -> int | None:
    if (
        not is_finite_number(span)
        or not is_finite_number(step)
        or float(span) < 0.0
        or float(step) <= 0.0
    ):
        return None
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        ratio = float(np.divide(float(span), float(step)))
    if not np.isfinite(ratio) or ratio < 0.0:
        return None
    intervals = int(np.ceil(ratio))
    return intervals if intervals <= maximum_intervals else None


def numerical_time_resource_issues(
    T: Any, max_step: Any, output_dt: Any
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if safe_nominal_interval_count(T, max_step) is None:
        issues.append(
            ValidationIssue(
                "NUMERICAL_RESOURCE_LIMIT",
                "numerics.max_step",
                max_step,
                (
                    "positive finite value with ceil(T/max_step) <= "
                    f"{MAX_NOMINAL_SOLVER_STEPS}"
                ),
            )
        )
    if safe_uniform_sample_count(T, output_dt) is None:
        issues.append(
            ValidationIssue(
                "NUMERICAL_RESOURCE_LIMIT",
                "numerics.output_dt",
                output_dt,
                (
                    "positive finite value yielding at most "
                    f"{MAX_UNIFORM_SAMPLES} output samples including endpoint"
                ),
            )
        )
    return issues


def strict_finite_array(value: Any) -> np.ndarray | None:
    """Convert only genuine finite real scalars; never coerce bool/string JSON."""

    try:
        object_array = np.asarray(value, dtype=object)
    except (TypeError, ValueError):
        return None
    if any(not is_finite_number(item) for item in object_array.flat):
        return None
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    return result if np.all(np.isfinite(result)) else None


def as_vector3(value: Any, path: str, issues: list[ValidationIssue]) -> np.ndarray:
    arr = strict_finite_array(value)
    if arr is None:
        issues.append(ValidationIssue("TYPE", path, value, "three finite real numbers"))
        return np.zeros(3)
    if arr.shape != (3,):
        issues.append(ValidationIssue("TYPE", path, value, "three finite real numbers"))
        return np.zeros(3)
    return arr


def require_number(
    mapping: dict[str, Any],
    key: str,
    path: str,
    issues: list[ValidationIssue],
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> float:
    value = mapping.get(key)
    if not is_finite_number(value):
        issues.append(ValidationIssue("TYPE", f"{path}.{key}", value, "finite real number"))
        return 0.0
    number = float(value)
    if positive and not number > 0.0:
        issues.append(ValidationIssue("SIGN", f"{path}.{key}", number, "> 0"))
    if nonnegative and not number >= 0.0:
        issues.append(ValidationIssue("SIGN", f"{path}.{key}", number, ">= 0"))
    return number


def base_validation(config: dict[str, Any], model_id: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if config.get("schema_version") != CONFIG_SCHEMA_VERSION:
        issues.append(
            ValidationIssue(
                "SCHEMA_VERSION",
                "schema_version",
                config.get("schema_version"),
                CONFIG_SCHEMA_VERSION,
            )
        )
    if config.get("model_id") != model_id:
        issues.append(
            ValidationIssue("MODEL_ID", "model_id", config.get("model_id"), model_id)
        )
    if config.get("theory_sha256") != THEORY_SHA256:
        issues.append(
            ValidationIssue(
                "THEORY_IDENTITY",
                "theory_sha256",
                config.get("theory_sha256"),
                THEORY_SHA256,
            )
        )
    return issues


def reject_unknown_keys(
    mapping: Any,
    allowed: set[str],
    path: str,
    issues: list[ValidationIssue],
) -> None:
    """Fail closed on misspelled physical/schema fields.

    Numerical extension dictionaries may deliberately use their own validator;
    this helper is applied only where the schema is frozen.
    """

    if not isinstance(mapping, dict):
        return
    for key in sorted(set(mapping) - allowed):
        issues.append(
            ValidationIssue(
                "UNKNOWN_FIELD",
                f"{path}.{key}" if path else key,
                mapping[key],
                f"one of {sorted(allowed)}",
            )
        )

"""Finite sampled prediction-set execution with no failed-member filtering."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import json
import re
import tempfile
from typing import Any

import numpy as np

from .contracts import (
    PROGRAM_VERSION,
    THEORY_SHA256,
    SimulationResult,
    config_sha256,
    is_finite_number,
    json_input_issues,
    json_safe,
    run_identity_hashes,
    source_tree_sha256,
)
from .io import write_result
from .runner import run_config


ENSEMBLE_SCHEMA_VERSION = "YPS-FWD-ENSEMBLE-1.0"
SET_KIND = "SAMPLED_PREDICTION_SET"
MEMBER_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
UNCERTAINTY_COMPONENTS = {
    "physical_parameters",
    "initial_state",
    "numerical_error",
    "observation_calibration",
    "experimental_noise",
}


@dataclass(frozen=True)
class EnsembleMemberResult:
    member_id: str
    weight: float
    normalized_weight: float
    components: dict[str, Any]
    config: dict[str, Any]
    result: SimulationResult
    identity_checks: dict[str, bool]

    def manifest_dict(self, result_directory: str) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "weight": self.weight,
            "normalized_weight": self.normalized_weight,
            "uncertainty_components": self.components,
            "config_sha256": self.result.metadata.get("config_sha256"),
            "physical_status": list(self.result.contract_status),
            "numerical_status": self.result.numerical_status,
            "tau": self.result.tau,
            "result_directory": result_directory,
            "result": self.result.summary_dict(),
            "identity_checks": self.identity_checks,
        }


@dataclass(frozen=True)
class SampledPredictionSetResult:
    status: str
    schema_version: str
    set_kind: str
    ensemble_sha256: str
    model_id: str
    weight_semantics: str
    source_tree_sha256_at_start: str
    source_tree_sha256_at_end: str
    members: tuple[EnsembleMemberResult, ...]
    validation_errors: tuple[dict[str, Any], ...] = ()

    def summary_dict(self) -> dict[str, Any]:
        physical_counts: dict[str, int] = {}
        numerical_counts: dict[str, int] = {}
        total_weight = 0.0
        for member in self.members:
            physical_key = "+".join(member.result.contract_status) or "UNDETERMINED"
            physical_counts[physical_key] = physical_counts.get(physical_key, 0) + 1
            numerical_key = member.result.numerical_status
            numerical_counts[numerical_key] = numerical_counts.get(numerical_key, 0) + 1
            total_weight += member.weight
        return {
            "status": self.status,
            "schema_version": self.schema_version,
            "set_kind": self.set_kind,
            "program_version": PROGRAM_VERSION,
            "theory_sha256": THEORY_SHA256,
            "units": "SI",
            "ensemble_sha256": self.ensemble_sha256,
            "model_id": self.model_id,
            "weight_semantics": self.weight_semantics,
            "source_tree_sha256_at_start": self.source_tree_sha256_at_start,
            "source_tree_sha256_at_end": self.source_tree_sha256_at_end,
            "source_tree_stable": (
                self.source_tree_sha256_at_start
                == self.source_tree_sha256_at_end
            ),
            "member_count": len(self.members),
            "total_weight": total_weight,
            "physical_status_counts": physical_counts,
            "numerical_status_counts": numerical_counts,
            "validation_errors": list(self.validation_errors),
        }


def run_ensemble(spec: dict[str, Any]) -> SampledPredictionSetResult:
    """Run every validly-described member and retain every numerical outcome."""

    try:
        frozen = deepcopy(spec)
    except Exception as exc:
        frozen = {"copy_failure": repr(exc)}
    source_start = source_tree_sha256()
    errors = _validate_ensemble_spec(frozen)
    ensemble_hash = _safe_hash(frozen)
    if ensemble_hash == "UNHASHABLE_INVALID_ENSEMBLE" and not errors:
        errors.append(
            _error(
                "ensemble",
                frozen,
                "recursively JSON-safe finite value with a canonical hash",
            )
        )
    if errors:
        return SampledPredictionSetResult(
            status="INVALID_ENSEMBLE_INPUT",
            schema_version=ENSEMBLE_SCHEMA_VERSION,
            set_kind=SET_KIND,
            ensemble_sha256=ensemble_hash,
            model_id=(
                frozen.get("model_id", "UNSPECIFIED")
                if isinstance(frozen, dict)
                else "UNSPECIFIED"
            ),
            weight_semantics=(
                frozen.get("weight_semantics", "UNSPECIFIED")
                if isinstance(frozen, dict)
                else "UNSPECIFIED"
            ),
            source_tree_sha256_at_start=source_start,
            source_tree_sha256_at_end=source_tree_sha256(),
            members=(),
            validation_errors=tuple(errors),
        )

    members: list[EnsembleMemberResult] = []
    weights = [float(member["weight"]) for member in frozen["members"]]
    normalized_weights = _stable_normalized_weights(weights)
    if normalized_weights is None:
        return SampledPredictionSetResult(
            status="INVALID_ENSEMBLE_INPUT",
            schema_version=ENSEMBLE_SCHEMA_VERSION,
            set_kind=SET_KIND,
            ensemble_sha256=ensemble_hash,
            model_id=frozen["model_id"],
            weight_semantics=frozen["weight_semantics"],
            source_tree_sha256_at_start=source_start,
            source_tree_sha256_at_end=source_tree_sha256(),
            members=(),
            validation_errors=(
                _error(
                    "members.weight",
                    weights,
                    "finite positive total and finite positive normalized weights",
                ),
            ),
        )
    execution_exception = False
    identity_failure = False
    for member, normalized_weight in zip(
        frozen["members"], normalized_weights
    ):
        member_config = deepcopy(member["config"])
        # Invalid physical/numerical member configs are intentionally executed:
        # run_config returns their failure status and the member remains present.
        expected_identity = run_identity_hashes(member_config)
        try:
            result = run_config(member_config)
        except Exception as exc:
            execution_exception = True
            source_end_after_exception = source_tree_sha256()
            result = SimulationResult(
                model_id=frozen["model_id"],
                contract_status=[],
                numerical_status="INTERNAL_EXECUTION_FAILURE",
                tau=0.0,
                returned_interval="empty; member execution raised unexpectedly",
                time=np.empty(0),
                events=[
                    {
                        "kind": "member_execution_failure",
                        "message": repr(exc),
                    }
                ],
                metadata={
                    **expected_identity,
                    "source_tree_sha256_at_end": source_end_after_exception,
                    "source_tree_stable_during_run": (
                        source_end_after_exception
                        == expected_identity["source_tree_sha256"]
                    ),
                },
            )
        identity_checks = {
            key: result.metadata.get(key) == expected_identity.get(key)
            for key in (
                "program_version",
                "config_schema_version",
                "numerical_model_id",
                "theory_sha256",
                "units",
                "config_sha256",
                "physical_input_sha256",
                "numerical_config_sha256",
                "observation_input_sha256",
                "source_tree_sha256",
                "runtime_versions",
            )
        }
        identity_checks["source_stable_during_run"] = (
            result.metadata.get("source_tree_stable_during_run") is True
        )
        identity_checks["source_matches_ensemble_start"] = (
            expected_identity["source_tree_sha256"] == source_start
        )
        identity_checks["result_model_matches_set"] = (
            result.model_id == frozen["model_id"]
        )
        if not all(identity_checks.values()):
            identity_failure = True
        members.append(
            EnsembleMemberResult(
                member_id=member["member_id"],
                weight=float(member["weight"]),
                normalized_weight=normalized_weight,
                components=deepcopy(member["uncertainty_components"]),
                config=member_config,
                result=result,
                identity_checks=identity_checks,
            )
        )
    source_end = source_tree_sha256()
    if source_end != source_start or identity_failure:
        status = "SAMPLED_PREDICTION_SET_IDENTITY_UNRESOLVED"
    elif execution_exception:
        status = "SAMPLED_PREDICTION_SET_MEMBER_EXECUTION_FAILURE"
    else:
        status = "SAMPLED_PREDICTION_SET_COMPLETE"
    return SampledPredictionSetResult(
        status=status,
        schema_version=ENSEMBLE_SCHEMA_VERSION,
        set_kind=SET_KIND,
        ensemble_sha256=ensemble_hash,
        model_id=frozen["model_id"],
        weight_semantics=frozen["weight_semantics"],
        source_tree_sha256_at_start=source_start,
        source_tree_sha256_at_end=source_end,
        members=tuple(members),
    )


def write_ensemble(
    output_directory: str | Path,
    spec: dict[str, Any],
    result: SampledPredictionSetResult,
    *,
    plots: bool = False,
) -> Path:
    """Atomically write a new sampled-set directory; never overwrite one."""

    output = Path(output_directory)
    if output.exists():
        raise FileExistsError(
            f"refusing to overwrite ensemble output path: {output}"
        )
    if config_sha256(spec) != result.ensemble_sha256:
        raise ValueError("ensemble spec no longer matches the executed snapshot")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=output.parent, prefix=f".{output.name}.tmp-"
    ) as temporary:
        root = Path(temporary)
        (root / "ensemble.snapshot.json").write_text(
            json.dumps(
                spec,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        member_manifests: list[dict[str, Any]] = []
        member_root = root / "members"
        member_root.mkdir()
        for member in result.members:
            member_directory = member_root / member.member_id
            write_result(
                member_directory,
                member.config,
                member.result,
                plots=plots,
            )
            member_manifests.append(
                member.manifest_dict(f"members/{member.member_id}")
            )
        manifest = {
            **result.summary_dict(),
            "members": member_manifests,
        }
        (root / "manifest.json").write_text(
            json.dumps(
                json_safe(manifest),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        Path(temporary).replace(output)
    return output


def _validate_ensemble_spec(spec: Any) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(spec, dict):
        return [_error("ensemble", spec, "JSON object")]
    json_issues = json_input_issues(spec, "ensemble")
    if json_issues:
        return [issue.as_dict() for issue in json_issues]
    allowed = {
        "schema_version",
        "set_kind",
        "model_id",
        "theory_sha256",
        "units",
        "weight_semantics",
        "members",
        "metadata",
    }
    for key in sorted(set(spec) - allowed):
        errors.append(_error(key, spec[key], f"one of {sorted(allowed)}"))
    if spec.get("schema_version") != ENSEMBLE_SCHEMA_VERSION:
        errors.append(
            _error(
                "schema_version",
                spec.get("schema_version"),
                ENSEMBLE_SCHEMA_VERSION,
            )
        )
    if spec.get("set_kind") != SET_KIND:
        errors.append(_error("set_kind", spec.get("set_kind"), SET_KIND))
    model_id = spec.get("model_id")
    if model_id not in ("FWD-CABLE-1.0", "FWD-TORUS-1.0"):
        errors.append(
            _error(
                "model_id",
                model_id,
                "FWD-CABLE-1.0 or FWD-TORUS-1.0",
            )
        )
    if spec.get("theory_sha256") != THEORY_SHA256:
        errors.append(
            _error("theory_sha256", spec.get("theory_sha256"), THEORY_SHA256)
        )
    if spec.get("units") != "SI":
        errors.append(_error("units", spec.get("units"), "SI"))
    weight_semantics = spec.get("weight_semantics")
    if weight_semantics not in ("probability", "relative"):
        errors.append(
            _error(
                "weight_semantics",
                weight_semantics,
                "probability or relative",
            )
        )
    members = spec.get("members")
    if not isinstance(members, list) or not members:
        errors.append(_error("members", members, "nonempty member list"))
        return errors
    identifiers: list[str] = []
    for index, member in enumerate(members):
        path = f"members[{index}]"
        if not isinstance(member, dict):
            errors.append(_error(path, member, "member object"))
            continue
        allowed_member = {
            "member_id",
            "weight",
            "uncertainty_components",
            "config",
        }
        for key in sorted(set(member) - allowed_member):
            errors.append(
                _error(
                    f"{path}.{key}",
                    member[key],
                    f"one of {sorted(allowed_member)}",
                )
            )
        identifier = member.get("member_id")
        if not isinstance(identifier, str) or not MEMBER_ID_PATTERN.fullmatch(
            identifier
        ):
            errors.append(
                _error(
                    f"{path}.member_id",
                    identifier,
                    "1-64 safe ASCII letters/digits/._- beginning alphanumeric",
                )
            )
        else:
            identifiers.append(identifier)
        weight = member.get("weight")
        if not is_finite_number(weight) or float(weight) <= 0.0:
            errors.append(
                _error(f"{path}.weight", weight, "positive finite JSON real")
            )
        if not isinstance(member.get("config"), dict):
            errors.append(
                _error(f"{path}.config", member.get("config"), "config object")
            )
        else:
            member_config = member["config"]
            for key, expected_value in (
                ("model_id", model_id),
                ("theory_sha256", THEORY_SHA256),
                ("units", "SI"),
            ):
                if member_config.get(key) != expected_value:
                    errors.append(
                        _error(
                            f"{path}.config.{key}",
                            member_config.get(key),
                            str(expected_value),
                        )
                    )
        components = member.get("uncertainty_components")
        if not isinstance(components, dict) or set(components) != UNCERTAINTY_COMPONENTS:
            errors.append(
                _error(
                    f"{path}.uncertainty_components",
                    components,
                    f"exact object keys {sorted(UNCERTAINTY_COMPONENTS)}",
                )
            )
        elif any(not isinstance(value, dict) for value in components.values()):
            errors.append(
                _error(
                    f"{path}.uncertainty_components",
                    components,
                    "each uncertainty category is an object",
                )
            )
    if len(identifiers) != len(set(identifiers)):
        errors.append(_error("members.member_id", identifiers, "unique IDs"))
    valid_weights = [
        float(member["weight"])
        for member in members
        if isinstance(member, dict)
        and is_finite_number(member.get("weight"))
        and float(member["weight"]) > 0.0
    ]
    normalized_weights = (
        _stable_normalized_weights(valid_weights)
        if len(valid_weights) == len(members)
        else None
    )
    if len(valid_weights) == len(members) and normalized_weights is None:
        errors.append(
            _error(
                "members.weight",
                valid_weights,
                "finite positive total and finite positive normalized weights summing to 1",
            )
        )
    if (
        weight_semantics == "probability"
        and len(valid_weights) == len(members)
        and normalized_weights is not None
        and not np.isclose(sum(valid_weights), 1.0, rtol=0.0, atol=1e-12)
    ):
        errors.append(
            _error(
                "members.weight",
                sum(valid_weights),
                "sum to 1 within absolute tolerance 1e-12 for probability weights",
            )
        )
    return errors


def _stable_normalized_weights(weights: list[float]) -> list[float] | None:
    if not weights or not all(
        np.isfinite(value) and value > 0.0 for value in weights
    ):
        return None
    total = float(sum(weights))
    if not np.isfinite(total) or total <= 0.0:
        return None
    maximum = max(weights)
    scaled = np.asarray(weights, dtype=float) / maximum
    scaled_total = float(np.sum(scaled))
    normalized = scaled / scaled_total
    if not (
        np.isfinite(scaled_total)
        and scaled_total > 0.0
        and np.all(np.isfinite(normalized))
        and np.all(normalized > 0.0)
        and np.isclose(float(np.sum(normalized)), 1.0, rtol=0.0, atol=1e-15)
    ):
        return None
    return [float(value) for value in normalized]


def _safe_hash(value: Any) -> str:
    try:
        return config_sha256(value)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return "UNHASHABLE_INVALID_ENSEMBLE"


def _error(path: str, actual: Any, expected: str) -> dict[str, Any]:
    try:
        json.dumps(actual, allow_nan=False)
        safe_actual = json_safe(actual)
    except (TypeError, ValueError, OverflowError, RecursionError):
        if isinstance(actual, int) and not isinstance(actual, bool):
            safe_actual = f"<integer bit_length={actual.bit_length()}>"
        else:
            try:
                safe_actual = repr(actual)
            except (TypeError, ValueError, OverflowError, RecursionError):
                safe_actual = f"<unrepresentable {type(actual).__name__}>"
    return {"path": path, "actual": safe_actual, "expected": expected}

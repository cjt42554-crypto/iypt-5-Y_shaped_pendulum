"""Model dispatch for the two frozen forward-theory numerical backends."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np

from .cable import run_cable
from .contracts import (
    CONFIG_SCHEMA_VERSION,
    SimulationResult,
    THEORY_SHA256,
    ValidationIssue,
    json_input_issues,
    load_json,
    run_identity_hashes,
    source_tree_sha256,
)
from .torus import run_torus


def run_config(config: dict[str, Any]) -> SimulationResult:
    """Run one immutable input snapshot and bind identity at dispatch time.

    The caller's mapping may be mutable.  Copying it before either validation
    or hashing prevents a concurrent mutation from making the reported hash
    describe a different input than the one actually executed.  Backends are
    given the same run-start identity on every return path.
    """

    copy_issue: ValidationIssue | None = None
    try:
        frozen_config = deepcopy(config)
    except Exception as exc:
        copy_issue = ValidationIssue(
            "CONFIG_COPY_FAILURE",
            "config",
            f"<{type(exc).__name__}>",
            "deep-copyable finite JSON object",
        )
        frozen_config = {
            "invalid_root_type": type(config).__name__,
            "copy_failure": type(exc).__name__,
        }
    identity = run_identity_hashes(
        frozen_config
        if isinstance(frozen_config, dict)
        else {"invalid_root_type": type(frozen_config).__name__}
    )
    model_id = (
        frozen_config.get("model_id")
        if isinstance(frozen_config, dict)
        else None
    )
    if copy_issue is not None:
        input_issues = [copy_issue]
    elif not isinstance(frozen_config, dict):
        input_issues = [
            ValidationIssue(
                "CONFIG_ROOT_TYPE",
                "config",
                f"<{type(frozen_config).__name__}>",
                "JSON object",
            )
        ]
    else:
        input_issues = json_input_issues(frozen_config, "config")
    if input_issues:
        namespaces = {_issue_namespace(issue) for issue in input_issues}
        physical_invalid = "physical" in namespaces
        numerical_invalid = "numerics" in namespaces
        observation_invalid = "observation" in namespaces
        numerical_status = (
            "INVALID_NUMERICAL_CONFIG"
            if numerical_invalid
            else "INPUT_REJECTED"
        )
        observations = {}
        if observation_invalid:
            observations = {
                "status": ["INVALID_OBSERVATION_INPUT"],
                "operator": None,
                "time": np.empty(0),
                "values": np.empty((0, 2)),
                "valid_mask": np.empty(0, dtype=bool),
                "errors": [
                    issue.as_dict()
                    for issue in input_issues
                    if _issue_namespace(issue) == "observation"
                ],
            }
        return SimulationResult(
            model_id=(
                model_id if isinstance(model_id, str) else "UNSPECIFIED"
            ),
            # Only malformed physical/model inputs are allowed to establish
            # the frozen theory's INVALID_INPUT result.  A non-canonical
            # numerical, observation, metadata, or envelope field is a
            # software-input rejection, not a physical conclusion.
            contract_status=["INVALID_INPUT"] if physical_invalid else [],
            numerical_status=numerical_status,
            tau=0.0,
            returned_interval="empty",
            time=np.empty(0),
            observations=observations,
            events=[
                {
                    "kind": "input_validation",
                    "invalid_namespaces": sorted(namespaces),
                    "failures": [issue.as_dict() for issue in input_issues],
                }
            ],
            metadata=identity,
        )
    envelope_issues = _config_envelope_issues(frozen_config, model_id)
    if envelope_issues:
        return SimulationResult(
            model_id=(model_id if isinstance(model_id, str) else "UNSPECIFIED"),
            contract_status=[],
            numerical_status="INPUT_REJECTED",
            tau=0.0,
            returned_interval="empty",
            time=np.empty(0),
            events=[
                {
                    "kind": "config_envelope",
                    "failures": [issue.as_dict() for issue in envelope_issues],
                }
            ],
            metadata=identity,
        )
    if model_id == "FWD-CABLE-1.0":
        result = run_cable(frozen_config, identity=identity)
        return _fail_on_source_drift(result, identity)
    if model_id == "FWD-TORUS-1.0":
        result = run_torus(frozen_config, identity=identity)
        return _fail_on_source_drift(result, identity)
    issue = ValidationIssue(
        "MODEL_ID",
        "model_id",
        model_id,
        "FWD-CABLE-1.0 or FWD-TORUS-1.0",
    )
    return SimulationResult(
        model_id=str(model_id) if model_id is not None else "UNSPECIFIED",
        contract_status=["INVALID_INPUT"],
        numerical_status="INPUT_REJECTED",
        tau=0.0,
        returned_interval="empty",
        time=np.empty(0),
        events=[{"kind": "input", "failures": [issue.as_dict()]}],
        metadata=identity,
    )


def _issue_namespace(issue: ValidationIssue) -> str:
    """Map a whole-config JSON issue to the contract layer it belongs to."""

    path = issue.path
    if path == "config.numerics" or path.startswith("config.numerics.") or path.startswith(
        "config.numerics["
    ):
        return "numerics"
    if path == "config.observation" or path.startswith(
        "config.observation."
    ) or path.startswith("config.observation["):
        return "observation"
    physical_roots = (
        "config.physical",
        "config.inputs",
        "config.initial_state",
        "config.model_id",
        "config.units",
    )
    if any(
        path == root or path.startswith(root + ".") or path.startswith(root + "[")
        for root in physical_roots
    ):
        return "physical"
    return "config_envelope"


def _config_envelope_issues(
    config: dict[str, Any], model_id: Any
) -> list[ValidationIssue]:
    """Validate software-envelope identity without declaring physical failure."""

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
    if config.get("theory_sha256") != THEORY_SHA256:
        issues.append(
            ValidationIssue(
                "THEORY_IDENTITY",
                "theory_sha256",
                config.get("theory_sha256"),
                THEORY_SHA256,
            )
        )
    common = {
        "schema_version",
        "model_id",
        "theory_sha256",
        "units",
        "physical",
        "numerics",
        "observation",
        "validation",
        "metadata",
    }
    allowed = set(common)
    if model_id == "FWD-CABLE-1.0":
        allowed.update({"inputs", "initial_state"})
    for key in sorted(set(config) - allowed):
        issues.append(
            ValidationIssue(
                "UNKNOWN_FIELD",
                key,
                config[key],
                f"one of {sorted(allowed)}",
            )
        )
    return issues


def _fail_on_source_drift(
    result: SimulationResult, run_start_identity: dict[str, Any]
) -> SimulationResult:
    """A result cannot be qualified if source files changed during its run."""

    source_end = source_tree_sha256()
    source_start = run_start_identity["source_tree_sha256"]
    result.metadata["source_tree_sha256_at_end"] = source_end
    result.metadata["source_tree_stable_during_run"] = source_end == source_start
    if source_end == source_start:
        return result
    previous_status = {
        "contract_status": list(result.contract_status),
        "numerical_status": result.numerical_status,
    }
    result.contract_status = []
    result.numerical_status = "SOURCE_DRIFT"
    result.returned_interval = "candidate only; source tree changed during run"
    result.events.append(
        {
            "kind": "source_drift",
            "source_tree_sha256_at_start": source_start,
            "source_tree_sha256_at_end": source_end,
            "discarded_status": previous_status,
        }
    )
    return result


def run_file(path: str | Path) -> tuple[dict[str, Any], SimulationResult]:
    config = load_json(path)
    return config, run_config(config)

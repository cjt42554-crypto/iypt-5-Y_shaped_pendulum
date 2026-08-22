from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
import yaml

from ypendulum.config import (
    ConfigurationError,
    auxiliary_input_identities,
    load_config,
    load_validation_manifest,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _model_hash() -> str:
    root = Path(__file__).resolve().parents[2] / "src" / "ypendulum"
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _manifest(tmp_path: Path, claim: str = "VALIDATED") -> dict:
    data = tmp_path / "sealed-data.csv"
    result = tmp_path / "sealed-result-manifest.json"
    data.write_text("time,x\n0,1\n", encoding="utf-8")
    result.write_text('{"sealed":true}\n', encoding="utf-8")
    model_hash = _model_hash()

    def run(run_id: str, *, unseen: bool = False) -> dict:
        return {
            "run_id": run_id,
            "sealed": True,
            "model_definition_hash_sha256": model_hash,
            "data_path": data.name,
            "data_sha256": _sha256(data),
            "result_manifest_path": result.name,
            "result_manifest_sha256": _sha256(result),
            "geometry_was_unseen": unseen,
        }

    return {
        "schema_version": "1.1",
        "frozen": True,
        "passed": True,
        "claim_level": claim,
        "frozen_at_utc": "2026-08-18T00:00:00Z",
        "model_definition_hash_sha256": model_hash,
        "calibration_runs": [run("c1")],
        "validation_runs": [run("v1", unseen=True)],
        "metrics": {
            "frequency_ratio_relative_error": {
                "value": 0.0005,
                "threshold": 0.001,
                "comparison": "less_than_or_equal",
                "passed": True,
            }
        },
        "predictive_scope": {"unseen_conditions_passed": claim == "PREDICTIVE"},
    }


def test_manifest_contract_and_predictive_scope(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(_manifest(tmp_path, "PREDICTIVE")), encoding="utf-8")
    audit = load_validation_manifest(str(path), requested_claim="PREDICTIVE")
    assert audit.passed and audit.validation_run_count == 1

    bad = _manifest(tmp_path, "PREDICTIVE")
    bad["predictive_scope"]["unseen_conditions_passed"] = False
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError):
        load_validation_manifest(str(path), requested_claim="PREDICTIVE")


def test_claim_config_rejects_nonexistent_or_failed_manifest(
    config_dict, tmp_path: Path
) -> None:
    raw = copy.deepcopy(config_dict)
    raw["run"]["claim_level"] = "VALIDATED"
    raw["run"]["validation_manifest"] = str(tmp_path / "missing.yaml")
    with pytest.raises(ConfigurationError):
        load_config(raw)

    path = tmp_path / "failed.yaml"
    failed = _manifest(tmp_path, "VALIDATED")
    failed["passed"] = False
    path.write_text(yaml.safe_dump(failed), encoding="utf-8")
    raw["run"]["validation_manifest"] = str(path)
    with pytest.raises(ConfigurationError):
        load_config(raw)


def test_manifest_recomputes_hashes_and_metric_pass(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    payload = _manifest(tmp_path, "VALIDATED")
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    load_validation_manifest(str(path), requested_claim="VALIDATED")

    payload["validation_runs"][0]["data_sha256"] = "0" * 64
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_validation_manifest(str(path), requested_claim="VALIDATED")

    payload = _manifest(tmp_path, "VALIDATED")
    payload["metrics"]["frequency_ratio_relative_error"]["value"] = 0.01
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="did not pass"):
        load_validation_manifest(str(path), requested_claim="VALIDATED")


def test_manifest_rejects_placeholder_run_even_when_top_level_says_passed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "manifest.yaml"
    payload = _manifest(tmp_path, "VALIDATED")
    payload["validation_runs"] = [{}]
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="run_id"):
        load_validation_manifest(str(path), requested_claim="VALIDATED")


def test_campaign_artifacts_participate_in_execution_identity(
    config_dict, tmp_path: Path
) -> None:
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(_manifest(tmp_path, "VALIDATED")), encoding="utf-8"
    )
    raw = copy.deepcopy(config_dict)
    raw["run"]["claim_level"] = "VALIDATED"
    raw["run"]["validation_manifest"] = str(manifest_path)
    raw["solver"]["allow_subminimum_mesh"] = False
    raw["cables"]["upper_A"]["elements"] = 12
    raw["cables"]["upper_B"]["elements"] = 12
    raw["cables"]["lower"]["elements"] = 20
    cfg = load_config(raw)
    identities = auxiliary_input_identities(cfg)
    assert "run.validation_manifest" in identities
    assert any(key.endswith(".data_path") for key in identities)
    assert any(key.endswith(".result_manifest_path") for key in identities)

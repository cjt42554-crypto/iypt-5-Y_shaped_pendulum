from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ypendulum_hfv2_p3r import P3R_CONTACT_MODEL_ID
from ypendulum_hfv2_p3r2 import (
    P3R2_COMPONENT_SCALE_ID,
    P3R2_COMPOSITE_ALGORITHM_ID,
    P3R2_CONTACT_ASSEMBLY_IDENTITY_SCHEMA,
    P3R2_CONTACT_MODEL_ID,
)
from ypendulum_hfv2_p3r2.cases import build_observed_symmetric_regression

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads(
    (CANDIDATE_ROOT / "contracts" / "p3r2_acceptance_manifest.json").read_text(
        encoding="utf-8"
    )
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_historical_g3_and_g3r_artifacts_are_immutable() -> None:
    for relative, expected in MANIFEST["historical_artifact_sha256"].items():
        assert _sha256(CANDIDATE_ROOT / relative) == expected, relative


def test_p3r2_identity_is_new_and_binds_algorithm_and_scale_contracts() -> None:
    adapter = _sha256(
        CANDIDATE_ROOT / "contracts" / MANIFEST["adapter_contract"]
    )
    protocol = _sha256(
        CANDIDATE_ROOT / "contracts" / MANIFEST["frozen_protocol"]
    )
    case = build_observed_symmetric_regression(
        MANIFEST,
        adapter_contract_sha256=adapter,
        frozen_protocol_sha256=protocol,
    )
    binding = case.assembly.identity_binding
    assert P3R2_CONTACT_MODEL_ID != P3R_CONTACT_MODEL_ID
    assert binding["contact_model_id"] == P3R2_CONTACT_MODEL_ID
    assert binding["identity_schema"] == P3R2_CONTACT_ASSEMBLY_IDENTITY_SCHEMA
    assert binding["composite_algorithm_identity"] == P3R2_COMPOSITE_ALGORITHM_ID
    assert binding["component_scale_identity"] == P3R2_COMPONENT_SCALE_ID
    assert binding["physical_domain_change_from_predecessor"] is False


def test_two_new_targets_and_six_seeds_were_prefrozen_unobserved() -> None:
    targets = MANIFEST["qualification_targets"]
    assert MANIFEST["qualification_target_results_observed_before_freeze"] == 0
    assert len(targets) == 2
    assert [target["qualification_results_observed_before_freeze"] for target in targets] == [0, 0]
    assert [len(target["deterministic_seeds"]) for target in targets] == [3, 3]
    assert targets[0]["expected_supported_multipliers_N"][
        "bob:upper_A:upper_A_s000"
    ] != targets[0]["expected_supported_multipliers_N"][
        "bob:upper_B:upper_B_s000"
    ]
    assert targets[1]["geometry_scale_from_P3R_35_degree"] == 1.4

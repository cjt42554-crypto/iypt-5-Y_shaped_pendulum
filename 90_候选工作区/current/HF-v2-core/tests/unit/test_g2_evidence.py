from __future__ import annotations

import hashlib
import json
from pathlib import Path

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
G2R_ACCEPTANCE = json.loads(
    (CANDIDATE_ROOT / "contracts" / "g2r_acceptance_manifest.json").read_text(
        encoding="utf-8"
    )
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_g2_artifacts_are_immutable_history_after_g2r_opens() -> None:
    historical = G2R_ACCEPTANCE["historical_g2"]
    paths = {
        historical["report_path"]: historical["report_sha256"],
        historical["metrics_path"]: historical["metrics_sha256"],
        historical["frozen_protocol_path"]: historical["frozen_protocol_sha256"],
        historical["acceptance_manifest_path"]: historical[
            "acceptance_manifest_sha256"
        ],
    }
    for relative, expected in paths.items():
        assert _sha256(CANDIDATE_ROOT / relative) == expected, relative


def test_historical_g2_records_the_post_result_protocol_limitation() -> None:
    evidence = json.loads(
        (CANDIDATE_ROOT / "reports" / "g2_metrics.json").read_text(encoding="utf-8")
    )
    assert evidence["schema"] == "YPS-HFV2-G2-EVIDENCE-1.0"
    assert evidence["status"] == "PASS_G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONAL_ONLY"
    assert G2R_ACCEPTANCE["historical_g2"]["treatment"].startswith(
        "immutable_historical_post_deviation_artifacts"
    )

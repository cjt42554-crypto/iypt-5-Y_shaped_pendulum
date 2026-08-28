from __future__ import annotations

from ypendulum_hfv2_p3r3.evidence import render_human_report, render_raw_report


def _metrics() -> dict[str, object]:
    return {
        "generated_at": "2026-08-28T00:00:00+08:00",
        "model_id": "HFV2-DISCRETE-CORD-RIGID-BOB-0.6-CONTACT-CANDIDATE",
        "classification": "NO_GO_G3R3_STATIC_CONTACT_ALGORITHM",
        "classification_components": {
            "contract_binding": "PASS",
            "target_qualification": "ALGORITHM_SEED_FAIL",
        },
        "historical_regressions": [
            {
                "case_id": "history",
                "status": "PASS",
                "seed_execution_count": 1,
            }
        ],
        "qualification_targets": [
            {
                "case_id": "target",
                "status": "ALGORITHM_SEED_FAIL",
                "seed_execution_count": 3,
                "multiseed_spread_dimensionless": 1.0e-5,
                "multiseed_energy_spread_scale_fraction": 1.0e-7,
                "seed_records": [
                    {"seed_id": "seed_0", "status": "PASS"},
                    {"seed_id": "seed_1", "status": "ALGORITHM_SEED_FAIL"},
                ],
            }
        ],
        "formal_numerical_qualification": "HF_NUMERICAL_QUALIFICATION_NO_GO",
        "mandatory_stop": "G3R3_PRO_REVIEW",
    }


def test_reports_preserve_no_go_and_stop_boundaries() -> None:
    metrics = _metrics()
    raw = render_raw_report(metrics)
    human = render_human_report(metrics)
    assert "NO_GO_G3R3_STATIC_CONTACT_ALGORITHM" in raw
    assert "ALGORITHM_SEED_FAIL" in raw
    assert "HF_NUMERICAL_QUALIFICATION_NO_GO" in raw
    assert "G3R3_PRO_REVIEW" in raw
    assert "未通过" in human
    assert "未执行动力学接触" in human
    assert human.endswith("\n")

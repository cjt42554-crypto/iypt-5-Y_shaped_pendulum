from __future__ import annotations

from ypendulum_hfv2_p3r5.evidence import render_human_report, render_raw_report


def _metrics(classification: str) -> dict[str, object]:
    return {
        "generated_at": "2026-08-28T00:00:00+08:00",
        "model_id": "HFV2-DISCRETE-CORD-RIGID-BOB-0.8-CONTACT-CANDIDATE",
        "classification": classification,
        "classification_components": {
            "contract_binding": "PASS",
            "architecture": "PASS",
        },
        "historical_regressions": [
            {"case_id": "HIST", "status": "PASS", "seed_execution_count": 1}
        ],
        "qualification_targets": [
            {
                "case_id": "TARGET",
                "status": "PASS",
                "seed_execution_count": 3,
                "multiseed_spread_dimensionless": 0.0,
                "multiseed_energy_spread_scale_fraction": 0.0,
                "seed_records": [
                    {
                        "seed_id": "S0",
                        "seed_role": "reference_solver_initial_guess",
                        "status": "PASS",
                    }
                ],
            }
        ],
        "formal_numerical_qualification": "HF_NUMERICAL_QUALIFICATION_NO_GO",
        "mandatory_stop": "G3R5_PRO_REVIEW",
    }


def test_reports_preserve_candidate_and_formal_boundaries() -> None:
    metrics = _metrics(
        "G3R5_CANDIDATE_PASS_PENDING_PRO_REVIEW__STATIC_CONTACT_HOLDOUT_REFERENCE_AND_ACTUAL_MULTISEED_ONLY"
    )
    raw = render_raw_report(metrics)
    human = render_human_report(metrics)
    assert "G3R5_PRO_REVIEW" in raw
    assert "HF_NUMERICAL_QUALIFICATION_NO_GO" in raw
    assert "未观察留出目标" in human
    assert "正式高保真数值资格仍为" in human


def test_fail_report_does_not_claim_pass() -> None:
    report = render_human_report(_metrics("NO_GO_G3R5_STATIC_CONTACT_ALGORITHM"))
    assert "未通过" in report
    assert "资格全部通过" not in report

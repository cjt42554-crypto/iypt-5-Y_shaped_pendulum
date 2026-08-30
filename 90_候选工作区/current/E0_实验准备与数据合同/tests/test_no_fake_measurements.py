import json
from pathlib import Path

from yps_experiment_pipeline.cli import discover_repository_root, synthetic_self_test
from yps_experiment_pipeline.contracts import TEMPLATE_ROOT

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def test_repository_root_discovery_is_independent_of_stage_working_directory(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    assert discover_repository_root() == REPOSITORY_ROOT


def test_no_template_contains_forbidden_tuned_manufacturing_fields():
    forbidden = {"eta_numeric", "tuned_eta", "numerically_tuned_geometry"}
    for path in sorted(TEMPLATE_ROOT.iterdir()):
        text = path.read_text(encoding="utf-8")
        assert not any(name in text for name in forbidden), path


def test_first_round_plan_has_exactly_70_planned_runs():
    plan = json.loads(
        (TEMPLATE_ROOT / "first_round_plan.template.json").read_text(encoding="utf-8")
    )
    assert sum(family["planned_runs"] for family in plan["run_families"]) == 70
    assert plan["total_result_runs"] == 70
    registry = plan["run_registry"]
    assert len(registry) == 70
    assert len({item["run_id"] for item in registry}) == 70
    assert len({item["attempt_id"] for item in registry}) == 70
    assert all(item["status"] == "NOT_RUN" for item in registry)
    assert all(item["apparatus_revision"] == "UNSET_REQUIRES_HUMAN" for item in registry)
    assert all(
        item["manufacturing_value_status"] == "UNSET_REQUIRES_HUMAN"
        for item in plan["geometry_designs"]
    )
    for family in plan["run_families"]:
        assert len(family["amplitude_levels"]) == family["amplitude_level_count"]
        assert family["actual_initial_amplitude_source"] == "TRAJECTORY_RECONSTRUCTION_REQUIRED"
        assert [level["level_index"] for level in family["amplitude_levels"]] == list(
            range(1, family["amplitude_level_count"] + 1)
        )


def test_synthetic_self_test_cannot_emit_experiment_pass():
    result = synthetic_self_test(REPOSITORY_ROOT)
    encoded = json.dumps(result, sort_keys=True)
    assert result["data_origin"] == "SYNTHETIC_REAL_SHAPE_FIXTURE"
    assert result["status"].startswith("E0R2_SYNTHETIC_REAL_SHAPE_SELF_TEST_PASS")
    assert "EXPERIMENT_PASS" not in encoded
    assert result["claim_ceiling"] == "IMPLEMENTATION_AND_SYNTHETIC_REAL_SHAPE_FIXTURE_ONLY"

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import jsonschema

from y_pendulum_pattern_atlas import ATLAS_IDENTITY, OUTPUT_SCHEMA, run_atlas
from y_pendulum_pattern_atlas import backend as backend_module
from y_pendulum_pattern_atlas.atlas import _load_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[3]
CONFIG = PROJECT_ROOT / "configs" / "atlas_v1.json"
SCHEMA = PROJECT_ROOT / "schemas" / "atlas_output.schema.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_atlas_has_distinct_identity_and_formal_backend_binding() -> None:
    assert ATLAS_IDENTITY == "YPS-IDEAL-TORUS-PATTERN-ATLAS-DRAFT-1.0"
    assert OUTPUT_SCHEMA == "YPS-FORMAL-PATTERN-ATLAS-OUTPUT-1.0"
    backend = backend_module.load_formal_backend(REPOSITORY_ROOT)
    expected = REPOSITORY_ROOT / backend_module.FORMAL_BACKEND_RELATIVE_PATH
    assert backend.source_path == expected.resolve()
    assert backend.source_sha256 == _sha256(expected)


def test_candidate_contains_no_second_ode_or_solve_ivp() -> None:
    source = inspect.getsource(__import__("y_pendulum_pattern_atlas.atlas", fromlist=["*"]))
    backend_source = inspect.getsource(backend_module)
    assert "solve_ivp" not in source
    assert "solve_ivp" not in backend_source
    assert "def torus_rhs" not in source
    assert "def rhs" not in source


def test_configuration_is_closed_and_common_period_is_integral() -> None:
    config = _load_config(CONFIG)
    assert config["model_id"] == "FWD-TORUS-1.0"
    assert config["analysis"]["slow_cycles"] == 18
    assert "experimental calibration" in config["scope"]


def test_smoke_output_is_schema_valid_and_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    payload = run_atlas(
        CONFIG,
        first,
        repository_root=REPOSITORY_ROOT,
        smoke=True,
    )
    run_atlas(
        CONFIG,
        second,
        repository_root=REPOSITORY_ROOT,
        smoke=True,
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)
    for relative in (
        "atlas_results.json",
        "atlas_summary.csv",
        "geometry_tolerance.csv",
        "figures/compensation_accuracy.svg",
        "figures/compensation_accuracy.png",
        "artifact_manifest.json",
    ):
        assert (first / relative).read_bytes() == (second / relative).read_bytes(), relative


def test_smoke_numerical_gates_are_not_physical_or_experimental_qualification(
    tmp_path: Path,
) -> None:
    payload = run_atlas(
        CONFIG,
        tmp_path / "smoke",
        repository_root=REPOSITORY_ROOT,
        smoke=True,
    )
    assert all(payload["validation"]["aggregate_gates"].values())
    assert payload["model_identity"]["backend_model_id"] == "FWD-TORUS-1.0"
    assert payload["model_identity"]["tuning_interpretation"] == (
        "ideal_model_internal_not_experimental_calibration"
    )
    assert "experimental validation" in payload["claim_limit"]
    for case in payload["cases"]:
        for name in ("zero", "quartic", "numeric"):
            assert min(case[name]["minimum_guards"].values()) > 0.0

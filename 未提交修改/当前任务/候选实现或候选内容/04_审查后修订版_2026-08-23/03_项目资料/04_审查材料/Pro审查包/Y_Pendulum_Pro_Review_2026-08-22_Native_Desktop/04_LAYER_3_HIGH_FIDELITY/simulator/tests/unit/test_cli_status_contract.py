from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import ypendulum.cli as cli


@pytest.mark.parametrize(
    ("physical", "numerical", "expected_status", "expected_code"),
    [
        ("COMPLETED", "SUCCESS_SINGLE_RUN", "success", 0),
        ("OUT_OF_SCOPE", "SUCCESS_EVENT", "out_of_scope_prefix", 3),
        ("UNDETERMINED", "SOLVER_FAILURE", "undetermined", 2),
    ],
)
def test_simulate_cli_preserves_three_way_scientific_status(
    monkeypatch,
    capsys,
    physical: str,
    numerical: str,
    expected_status: str,
    expected_code: int,
) -> None:
    cfg = SimpleNamespace(
        run=SimpleNamespace(output_directory="unused", mode="full")
    )
    result = SimpleNamespace(
        physical_status=physical,
        numerical_status=numerical,
        model_id="HF-DISCRETE-ROD-RIGID-BOB-1.0",
    )
    monkeypatch.setattr(cli, "load_config", lambda _path: cfg)
    monkeypatch.setattr(cli, "simulate", lambda _cfg, **_kwargs: result)

    code = cli.cmd_simulate(SimpleNamespace(config="config.yaml"))
    payload = json.loads(capsys.readouterr().out)
    assert code == expected_code
    assert payload["status"] == expected_status
    assert payload["physical_status"] == physical
    assert payload["numerical_status"] == numerical


@pytest.mark.parametrize(
    ("certificate_passed", "expected_status", "expected_code"),
    [
        (False, "undetermined", 2),
        (True, "independently_certified", 0),
    ],
)
def test_hf_cli_keeps_raw_result_provisional_and_uses_separate_certificate(
    monkeypatch,
    capsys,
    certificate_passed: bool,
    expected_status: str,
    expected_code: int,
) -> None:
    cfg = SimpleNamespace(
        run=SimpleNamespace(output_directory="hf-output", mode="high_fidelity")
    )
    result = SimpleNamespace(
        physical_status="UNDETERMINED",
        numerical_status="SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED",
        model_id="HF-DISCRETE-ROD-RIGID-BOB-1.0",
    )
    certificate = {
        "schema_version": "YPS-HF-SINGLE-BUNDLE-CERTIFICATE-1.0",
        "passed": certificate_passed,
        "certification_level": (
            "FULL_NUMERICAL_AND_GUARD_DOMAIN_CERTIFIED"
            if certificate_passed
            else "GUARD_DOMAIN_CERTIFIED"
        ),
        "certified_status_pair": {
            "physical_status": (
                "COMPLETED_INDEPENDENTLY_CERTIFIED"
                if certificate_passed
                else "GUARD_DOMAIN_CERTIFIED"
            ),
            "numerical_status": (
                "SUCCESS_SINGLE_RUN_GUARDS_CERTIFIED_BY_VALIDATION"
                if certificate_passed
                else "FULL_NUMERICAL_ACCURACY_NOT_CERTIFIED"
            ),
        },
        "certificate_sha256": "1" * 64,
    }
    full_checks: list[bool] = []

    def fake_sidecar(_directory, *, require_full: bool = False):
        full_checks.append(require_full)
        if require_full and not certificate_passed:
            raise AssertionError("An incomplete certificate must not enter full verification.")
        return {"certificate": certificate}

    monkeypatch.setattr(cli, "load_config", lambda _path: cfg)
    monkeypatch.setattr(cli, "simulate", lambda _cfg, **_kwargs: result)
    monkeypatch.setattr(cli, "read_hf_certificate_sidecar", fake_sidecar)

    code = cli.cmd_simulate(
        SimpleNamespace(
            config="config.yaml",
            hf_validation_spec="validation.yaml",
        )
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == expected_code
    assert payload["status"] == expected_status
    assert payload["physical_status"] == "UNDETERMINED"
    assert payload["independent_certificate"]["passed"] is certificate_passed
    assert full_checks == ([False, True] if certificate_passed else [False])


def test_hf_cli_accepts_raw_personal_research_result_without_formal_certificate(
    monkeypatch,
    capsys,
) -> None:
    cfg = SimpleNamespace(
        run=SimpleNamespace(output_directory="hf-output", mode="high_fidelity")
    )
    result = SimpleNamespace(
        physical_status="UNDETERMINED",
        numerical_status="SUCCESS_SINGLE_RUN_GUARDS_UNCERTIFIED",
        model_id="HF-DISCRETE-ROD-RIGID-BOB-1.0",
    )
    monkeypatch.setattr(cli, "load_config", lambda _path: cfg)
    monkeypatch.setattr(cli, "simulate", lambda _cfg, **_kwargs: result)
    monkeypatch.setattr(
        cli,
        "read_hf_certificate_sidecar",
        lambda *_args, **_kwargs: pytest.fail("raw mode must not read a certificate"),
    )

    code = cli.cmd_simulate(SimpleNamespace(config="config.yaml"))
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["status"] == "raw_scientific_result_guard_uncertified"
    assert payload["independent_certificate"] is None


@pytest.mark.parametrize(
    ("scientific_status", "expected_code"),
    [("COMPLETE", 0), ("OUT_OF_SCOPE_PREFIX", 3), ("UNDETERMINED", 3)],
)
def test_unified_cli_only_returns_zero_for_complete_delivery(
    monkeypatch,
    capsys,
    scientific_status: str,
    expected_code: int,
) -> None:
    monkeypatch.setattr(
        cli,
        "run_unified_case",
        lambda *_args, **_kwargs: {"status": scientific_status},
    )
    args = SimpleNamespace(case="case.yaml", backend="both", output="unused")
    assert cli.cmd_unified_run(args) == expected_code
    assert json.loads(capsys.readouterr().out)["status"] == scientific_status

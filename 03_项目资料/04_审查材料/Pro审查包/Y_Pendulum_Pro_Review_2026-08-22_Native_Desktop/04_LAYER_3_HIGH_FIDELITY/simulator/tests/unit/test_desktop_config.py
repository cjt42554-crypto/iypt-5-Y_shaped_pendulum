from __future__ import annotations

from pathlib import Path

from ypendulum.ui.desktop_config import (
    DesktopYPendulumAdapter,
    default_desktop_configuration,
    make_desktop_request,
    numeric_sweep_values,
    parameter_fields,
    parse_parameter_text,
    shared_input_audit,
    validate_desktop_request,
    write_desktop_request,
)


def _independent_leaf_paths(value: object, prefix: str = "") -> set[str]:
    if not isinstance(value, dict):
        return {prefix}
    paths: set[str] = set()
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        paths.update(_independent_leaf_paths(child, path))
    return paths


def test_default_profiles_cover_every_leaf_and_validate_all_backends(tmp_path: Path) -> None:
    forward, high_fidelity = default_desktop_configuration()
    assert {item.path for item in parameter_fields(forward, "forward")} == _independent_leaf_paths(
        forward
    )
    assert {
        item.path for item in parameter_fields(high_fidelity, "high_fidelity")
    } == _independent_leaf_paths(high_fidelity)

    for backend in ("forward", "high_fidelity", "both"):
        request = make_desktop_request(
            label=f"default_{backend}",
            backend=backend,
            forward_config=forward,
            high_fidelity_config=high_fidelity,
        )
        identity = validate_desktop_request(request)
        assert identity["backend"] == backend
        assert len(identity["request_sha256"]) == 64
        path = write_desktop_request(tmp_path / f"{backend}.json", request)
        command = DesktopYPendulumAdapter().build_command(
            path,
            backend=backend,
            output_directory=tmp_path / f"output-{backend}",
        )
        joined = " ".join(command).lower()
        assert "desktop_worker" in joined
        assert "streamlit" not in joined
        assert "http://" not in joined
        assert "https://" not in joined


def test_default_shared_input_audit_passes() -> None:
    forward, high_fidelity = default_desktop_configuration()
    audit = shared_input_audit(forward, high_fidelity)
    assert audit["passed"] is True
    assert audit["check_count"] >= 30


def test_typed_parameter_parser_handles_vectors_matrices_and_text_lists() -> None:
    forward, _high_fidelity = default_desktop_configuration()
    fields = {item.path: item for item in parameter_fields(forward, "forward")}
    assert parse_parameter_text(fields["initial_state.r_J"], "0.1, -0.2, 0.3") == [
        0.1,
        -0.2,
        0.3,
    ]
    assert parse_parameter_text(
        fields["initial_state.branches.A.position.coefficients"],
        "0, 0, 0; 1, 2, 3",
    ) == [[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]]
    assert parse_parameter_text(
        fields["validation.expected_contract_status"], "COMPLETED"
    ) == ["COMPLETED"]


def test_sweep_values_are_explicit_and_deterministic() -> None:
    assert numeric_sweep_values(0.0, 1.0, 5) == (0.0, 0.25, 0.5, 0.75, 1.0)


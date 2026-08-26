from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import build_qualification_configs as builder
import guard_contract_v2_full as full_v2

from ypendulum.config import load_config
from ypendulum.hf import HighFidelityModel


SPEC_PATH = ROOT / "guard_contract_v2" / "full_spec.json"


def _spec() -> dict[str, object]:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def test_full_spec_classifies_exactly_every_public_component() -> None:
    spec = _spec()
    assert full_v2.validate_spec(spec) == pytest.approx(3.0e-4)
    assert set(spec["components"]) == set(full_v2.COMPONENT_NAMES)
    assert len(spec["components"]) == 11
    assert spec["physical_guard_domains_changed"] is False
    assert spec["raw_zero_crossing_semantics_changed"] is False
    assert spec["formal_change_authorized"] is False


def test_local_ratios_are_exactly_similarity_invariant() -> None:
    length = full_v2._candidate("length", 2.4e-4, 3.2e-3)
    length_scaled = full_v2._candidate("length_scaled", 0.24, 3.2)
    assert length["normalized_margin"] == pytest.approx(
        length_scaled["normalized_margin"], abs=1.0e-15
    )

    square = full_v2._candidate("square", 2.4e-8, 3.2e-7)
    square_scaled = full_v2._candidate("square_scaled", 2.4e-2, 3.2e-1)
    assert square["normalized_margin"] == pytest.approx(
        square_scaled["normalized_margin"], abs=1.0e-15
    )


def test_segment_and_chord_local_ratios_do_not_collapse_under_refinement() -> None:
    coarse_x = np.array([0.0, 0.25, 0.75, 1.0])
    coarse = np.column_stack([coarse_x, np.zeros((coarse_x.size, 2))])
    coarse_rest = np.diff(coarse_x)
    fine_x = np.array([0.0, 0.125, 0.25, 0.5, 0.75, 0.875, 1.0])
    fine = np.column_stack([fine_x, np.zeros((fine_x.size, 2))])
    fine_rest = np.diff(fine_x)

    coarse_segment = min(
        item["normalized_margin"]
        for item in full_v2.segment_length_candidates(
            "coarse", coarse, coarse_rest, 1.0e-12
        )
    )
    fine_segment = min(
        item["normalized_margin"]
        for item in full_v2.segment_length_candidates(
            "fine", fine, fine_rest, 1.0e-12
        )
    )
    assert coarse_segment == pytest.approx(1.0, abs=1.0e-11)
    assert fine_segment == pytest.approx(1.0, abs=1.0e-11)

    coarse_chord = min(
        item["normalized_margin"]
        for item in full_v2.aerodynamic_chord_candidates(
            "coarse", coarse, coarse_rest, 1.0e-14
        )
    )
    fine_chord = min(
        item["normalized_margin"]
        for item in full_v2.aerodynamic_chord_candidates(
            "fine", fine, fine_rest, 1.0e-14
        )
    )
    assert coarse_chord == pytest.approx(1.0, abs=1.0e-12)
    assert fine_chord == pytest.approx(1.0, abs=1.0e-12)


def test_radial_cosine_is_invariant_when_a_material_cell_is_split() -> None:
    bob = np.zeros(3)
    coarse = np.array([[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    fine = np.array(
        [[1.0, 0.0, 0.0], [1.5, 0.0, 0.0], [2.0, 0.0, 0.0]]
    )
    coarse_records = full_v2.radial_monotonicity_candidates(coarse, bob)
    fine_records = full_v2.radial_monotonicity_candidates(fine, bob)
    assert min(item["normalized_margin"] for item in coarse_records) == pytest.approx(1.0)
    assert min(item["normalized_margin"] for item in fine_records) == pytest.approx(1.0)
    assert all(item["raw_positive"] for item in coarse_records + fine_records)


def test_raw_zero_and_negative_margins_remain_fail_closed() -> None:
    assert full_v2._candidate("zero", 0.0, 1.0)["raw_positive"] is False
    assert full_v2._candidate("negative", -1.0e-15, 1.0)["raw_positive"] is False


def test_full_live_resolver_reproduces_all_formal_public_raw_guards() -> None:
    cfg = load_config(ROOT / "configs" / "4to3.yaml")
    model = HighFidelityModel(cfg)
    zero_particles = np.zeros_like(model.reference_particle_positions)
    zero3 = np.zeros(3)
    state = model.pack_state(
        model.reference_particle_positions,
        model.reference_bob_position,
        np.array([1.0, 0.0, 0.0, 0.0]),
        zero_particles,
        zero3,
        zero3,
    )
    evaluation = full_v2.evaluate_prepared_state(model, state, _spec())
    assert evaluation["component_count"] == 11
    assert set(evaluation["components"]) == set(full_v2.COMPONENT_NAMES)
    assert evaluation["all_public_raw_guards_resolved"] is True
    for component in evaluation["components"].values():
        assert component["raw_domain_and_zero_preserved"] is True
        assert component["raw_identity_error"] <= component["raw_identity_tolerance"]


def test_full_spec_is_bound_to_current_formal_guard_sources() -> None:
    spec = _spec()
    source = spec["source_binding"]
    formal = builder.HF_SOURCE_ROOT
    expected = {
        "formal_model_py_sha256": formal / "ypendulum" / "hf" / "model.py",
        "formal_reference_py_sha256": formal / "ypendulum" / "hf" / "reference.py",
        "formal_solver_py_sha256": formal / "ypendulum" / "hf" / "solver.py",
        "formal_config_validation_py_sha256": (
            formal / "ypendulum" / "config" / "validation.py"
        ),
    }
    for key, path in expected.items():
        assert source[key] == full_v2.sha256_file(path)

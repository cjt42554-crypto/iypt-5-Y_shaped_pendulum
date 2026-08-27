from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

from ypendulum_hfv2.audit.g3_cases import build_target_contact_case
from ypendulum_hfv2_p3r import (
    P3R_CONTACT_ASSEMBLY_IDENTITY_SCHEMA,
    P3R_CONTACT_MODEL_ID,
)
from ypendulum_hfv2_p3r.assembly import P3RContactAssembly
from ypendulum_hfv2_p3r.critical_cone import _critical_face_directions
from ypendulum_hfv2_p3r.jacobian_audit import validity_jacobian_samples
from ypendulum_hfv2_p3r.kkt import (
    P3RKKTThresholds,
    audit_contact_kkt,
    audit_kkt_arrays,
)

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
OLD_MANIFEST = json.loads(
    (CANDIDATE_ROOT / "contracts" / "p3_acceptance_manifest.json").read_text(
        encoding="utf-8"
    )
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _old_target_with_p3r_assembly() -> tuple[object, P3RContactAssembly]:
    formal = _sha256(CANDIDATE_ROOT / "contracts" / "p3_formal_contact_registration.json")
    amendment = _sha256(CANDIDATE_ROOT / "contracts" / "p3_protocol_amendment_a1.json")
    old_case = build_target_contact_case(
        OLD_MANIFEST,
        formal_sha256=formal,
        amendment_sha256=amendment,
    )
    old = old_case.assembly
    assembly = P3RContactAssembly(
        base_assembly=old.base_assembly,
        surface=old.surface,
        tolerances=old.tolerances,
        adapter_contract_sha256="a" * 64,
        frozen_protocol_sha256="b" * 64,
        contact_gap_scale_m=0.1,
        validity_scale_m=0.1,
        validity_scale_m2=0.01,
        validity_scale_dimensionless=1.0,
        translation_difference_step_m=1.0e-7,
        rotation_difference_step_rad=1.0e-7,
    )
    return old_case, assembly


def _thresholds() -> P3RKKTThresholds:
    old = OLD_MANIFEST["kkt"]
    return P3RKKTThresholds(
        near_active_gap_max_m=old["active_gap_max_m"],
        primal_penetration_max_m=old["primal_penetration_max_m"],
        dual_negative_max_N=old["dual_negative_max_N"],
        stationarity_absolute_max_N=old["stationarity_absolute_max_N"],
        stationarity_force_scale_factor_max=old[
            "stationarity_force_scale_factor_max"
        ],
        complementarity_absolute_max_N_m=old[
            "complementarity_absolute_max_N_m"
        ],
        complementarity_energy_scale_factor_max=old[
            "complementarity_energy_scale_factor_max"
        ],
        supported_multiplier_min_N=old["supported_multiplier_min_N"],
        rank_relative_tolerance=old["active_constraint_rank_relative_tolerance"],
        dual_interval_nonunique_width_N=1.0e-7,
    )


def test_finite_invalid_socket_state_returns_signed_residuals_and_jacobian() -> None:
    case, assembly = _old_target_with_p3r_assembly()
    seed = case.seeds[1]
    evaluation = assembly.evaluate(assembly.coordinates_from_seed(seed))
    assert np.all(np.isfinite(evaluation.contact.gaps_m))
    assert np.all(np.isfinite(evaluation.validity.signed_residuals))
    assert np.all(np.isfinite(evaluation.validity.residual_jacobian))
    assert np.min(evaluation.validity.signed_residuals) < 0.0
    assert any("projective_opening_margin" in item for item in evaluation.validity.constraint_ids)


def test_validity_jacobian_has_independent_five_point_convergence() -> None:
    case, assembly = _old_target_with_p3r_assembly()
    coordinates = assembly.coordinates_from_seed(case.seeds[0])
    samples = validity_jacobian_samples(
        assembly,
        coordinates,
        (1.0e-5, 3.0e-6, 1.0e-6),
    )
    assert samples[-1].maximum_row_relative_error < 2.0e-5
    assert samples[-1].matrix_relative_error < 2.0e-5


def test_p3r_identity_binds_new_model_adapter_protocol_and_validity_numerics() -> None:
    case, assembly = _old_target_with_p3r_assembly()
    old = case.assembly
    assert P3R_CONTACT_MODEL_ID != OLD_MANIFEST["contact_model_id"]
    assert assembly.identity_binding["identity_schema"] == (
        P3R_CONTACT_ASSEMBLY_IDENTITY_SCHEMA
    )
    assert assembly.contact_assembly_token != old.contact_assembly_token
    changed = P3RContactAssembly(
        base_assembly=old.base_assembly,
        surface=old.surface,
        tolerances=old.tolerances,
        adapter_contract_sha256="a" * 64,
        frozen_protocol_sha256="b" * 64,
        contact_gap_scale_m=0.1,
        validity_scale_m=0.1,
        validity_scale_m2=0.01,
        validity_scale_dimensionless=1.0,
        translation_difference_step_m=2.0e-7,
        rotation_difference_step_rad=1.0e-7,
    )
    assert changed.contact_assembly_token != assembly.contact_assembly_token


def test_duplicate_near_active_rows_report_dual_intervals_without_false_licq_failure() -> None:
    audit = audit_kkt_arrays(
        gradient_N=np.array([2.1]),
        gaps_m=np.array([0.0, 0.0]),
        gap_jacobian=np.array([[1.0], [1.0]]),
        force_scale_N=7.0,
        energy_scale_N_m=7.0,
        thresholds=_thresholds(),
    )
    assert audit.passed
    assert audit.near_active_indices.tolist() == [0, 1]
    assert audit.near_active_rank == 1
    assert audit.supported_rank == 1
    assert audit.dual_nonunique
    assert audit.possible_supported_indices.tolist() == [0, 1]
    assert audit.mandatory_supported_indices.size == 0


def test_true_critical_cone_keeps_weak_active_one_sided_direction() -> None:
    hessian = np.diag([-1.0, 2.0])
    equality_rows = np.empty((0, 2))
    weak_active_row = np.array([[1.0, 0.0]])
    directions = _critical_face_directions(
        hessian,
        equality_rows,
        weak_active_row,
        rank_relative_tolerance=1.0e-10,
        cone_feasibility_tolerance=1.0e-10,
        duplicate_direction_tolerance=1.0e-10,
        maximum_enumerated_inequalities=4,
    )
    curvatures = np.einsum("ij,jk,ik->i", directions, hessian, directions)
    assert float(np.min(curvatures)) == pytest.approx(-1.0, abs=1.0e-12)
    equality_only = np.array([[0.0, 1.0]])
    assert float((equality_only @ hessian @ equality_only.T)[0, 0]) == pytest.approx(2.0)


def test_observed_symmetric_regression_preserves_four_near_two_supported_structure() -> None:
    case, assembly = _old_target_with_p3r_assembly()
    evaluation = assembly.evaluate(assembly.coordinates_from_seed(case.seeds[0]))
    audit = audit_contact_kkt(assembly, evaluation, _thresholds())
    constraint_ids = evaluation.contact.constraint_ids
    near_ids = tuple(constraint_ids[index] for index in audit.near_active_indices)
    supported_ids = tuple(constraint_ids[index] for index in audit.supported_indices)
    assert near_ids == (
        "junction:junction:upper_A:upper_A_s000|lower:lower_s000:first_outside",
        "junction:junction:upper_B:upper_B_s000|lower:lower_s000:first_outside",
        "bob:upper_A:upper_A_s000",
        "bob:upper_B:upper_B_s000",
    )
    assert supported_ids == (
        "bob:upper_A:upper_A_s000",
        "bob:upper_B:upper_B_s000",
    )
    assert audit.near_active_rank == 3
    assert audit.supported_rank == 2

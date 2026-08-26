from __future__ import annotations

import numpy as np
import pytest

from hard_contact_candidate import (
    ContactConstraint,
    DegenerateContactGeometry,
    KKTThresholds,
    assemble_gap_system,
    audit_projected_hessian,
    audit_static_kkt,
    closest_segment_pair_witness,
    full_parameter_polygon,
    material_separation_polygon,
    solve_static_contact_problem,
)

def test_static_kkt_audit_accepts_boundary_spring_equilibrium() -> None:
    thresholds = KKTThresholds(primal_gap_m=1e-12, stationarity_N=1e-12, dual_force_N=1e-12, complementarity_Nm=1e-12, active_gap_m=1e-09)
    audit = audit_static_kkt(energy_gradient_N=np.array([2.0]), gaps_m=np.array([0.0]), gap_jacobian=np.array([[1.0]]), multipliers_N=np.array([2.0]), thresholds=thresholds)
    assert audit.passed
    assert audit.active_contact_count == 1
    assert audit.multiplier_supported_contact_count == 1

def test_static_kkt_audit_rejects_penetration_and_tension_contact() -> None:
    audit = audit_static_kkt(energy_gradient_N=np.array([0.0]), gaps_m=np.array([-0.0001]), gap_jacobian=np.array([[1.0]]), multipliers_N=np.array([-1.0]))
    assert not audit.passed
    assert audit.primal_violation_m > 0.0
    assert audit.dual_violation_N > 0.0

def test_generic_static_contact_solver_finds_unilateral_spring_boundary() -> None:
    stiffness = 4.0
    free_position = -0.25

    def objective(state: np.ndarray) -> tuple[float, np.ndarray]:
        displacement = state[0] - free_position
        return (0.5 * stiffness * displacement ** 2, np.array([stiffness * displacement]))

    def gaps(state: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return (np.array([state[0]]), np.array([[1.0]]))
    thresholds = KKTThresholds(primal_gap_m=1e-09, stationarity_N=1e-08, dual_force_N=1e-10, complementarity_Nm=1e-09, active_gap_m=1e-07)
    result = solve_static_contact_problem(objective, gaps, initial_state=np.array([0.2]), thresholds=thresholds)
    assert result.optimizer_success
    assert result.state[0] == pytest.approx(0.0, abs=1e-10)
    assert result.multipliers_N[0] == pytest.approx(1.0, rel=1e-08)
    assert result.kkt.passed

def test_projected_hessian_detects_tangent_instability() -> None:
    hessian = np.diag([2.0, -0.5])
    active_jacobian = np.array([[1.0, 0.0]])
    audit = audit_projected_hessian(hessian, active_jacobian, tolerance_N_per_m=1e-08)
    assert audit.tangent_dimension == 1
    assert audit.minimum_projected_eigenvalue_N_per_m == pytest.approx(-0.5)
    assert not audit.passed

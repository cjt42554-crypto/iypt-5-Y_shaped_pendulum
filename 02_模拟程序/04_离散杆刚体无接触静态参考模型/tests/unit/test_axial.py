from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tests.helpers.invariance import internal_balance, objectivity_audit
from ypendulum_static_reference.audit.energy_gradient import force_gradient_samples
from ypendulum_static_reference.audit.statics import strict_decrease_interval
from ypendulum_static_reference.constitutive.axial import (
    AxialMaterial,
    axial_segment_response,
)
from ypendulum_static_reference.rigid.rotation import exp_so3

FORMAL_PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = json.loads(
    (
        FORMAL_PROJECT_ROOT
        / "tests/fixtures/historical/g1r_acceptance_manifest.json"
    ).read_text(encoding="utf-8")
)
FINITE_DIFFERENCE = ACCEPTANCE["finite_difference"]
RELATIVE_STEPS = tuple(FINITE_DIFFERENCE["relative_step_sequence"])


def _static_response(coordinates: np.ndarray, material: AxialMaterial):
    return axial_segment_response(coordinates[0], coordinates[1], material)


def test_axial_static_force_is_negative_energy_gradient_with_step_convergence() -> None:
    material = AxialMaterial(rest_length=1.1, axial_rigidity=780.0)
    coordinates = np.array([[0.2, -0.3, 0.1], [1.25, 0.35, -0.15]])
    response = _static_response(coordinates, material)
    analytic_force = np.vstack([response.force_on_start, response.force_on_end])
    samples = force_gradient_samples(
        lambda points: _static_response(points, material).stored_energy,
        coordinates,
        analytic_force,
        RELATIVE_STEPS,
        coordinate_scale=material.rest_length,
    )
    errors = [sample.relative_error for sample in samples]
    assert (
        strict_decrease_interval(errors, FINITE_DIFFERENCE["minimum_strict_decrease_steps"])
        is not None
    )
    assert samples[-1].relative_error <= FINITE_DIFFERENCE["final_relative_error_max"]


@pytest.mark.parametrize(
    "end_position",
    (
        np.array([0.8, 0.0, 0.0]),
        np.array([0.99, 0.0, 0.0]),
        np.array([0.5, 0.2, 0.0]),
    ),
)
def test_compression_has_exactly_zero_static_axial_force(end_position: np.ndarray) -> None:
    material = AxialMaterial(rest_length=1.0, axial_rigidity=100.0)
    response = axial_segment_response(np.zeros(3), end_position, material)
    assert response.extension < 0.0
    assert response.active is False
    assert response.tension == 0.0
    np.testing.assert_array_equal(response.force_on_start, np.zeros(3))
    np.testing.assert_array_equal(response.force_on_end, np.zeros(3))
    assert response.stored_energy == 0.0


def test_extension_uses_unilateral_elastic_energy_and_tension() -> None:
    material = AxialMaterial(rest_length=1.0, axial_rigidity=100.0)
    response = axial_segment_response(
        np.zeros(3),
        np.array([1.1, 0.0, 0.0]),
        material,
    )
    assert response.active is True
    assert response.tension == pytest.approx(10.0)
    assert response.stored_energy == pytest.approx(0.5)


def test_axial_action_reaction_and_arbitrary_origin_moment_close() -> None:
    material = AxialMaterial(rest_length=0.9, axial_rigidity=500.0)
    points = np.array([[0.3, -0.4, 0.2], [1.1, 0.3, 0.7]])
    response = axial_segment_response(points[0], points[1], material)
    forces = np.vstack([response.force_on_start, response.force_on_end])
    balance = internal_balance(
        points,
        forces,
        np.array([-0.7, 0.5, 0.9]),
        force_scale=max(response.tension, 1.0),
        length_scale=material.rest_length,
    )
    assert balance.scaled_force_resultant <= 5.0e-13
    assert balance.scaled_moment_resultant <= 2.0e-12


def test_axial_energy_and_force_are_objective() -> None:
    material = AxialMaterial(rest_length=0.7, axial_rigidity=350.0)
    points = np.array([[0.2, -0.1, 0.4], [0.95, 0.35, 0.25]])
    rotation = exp_so3(np.array([0.31, -0.22, 0.47]))

    def energy_and_force(coordinates: np.ndarray) -> tuple[float, np.ndarray]:
        response = _static_response(coordinates, material)
        return response.stored_energy, np.vstack(
            [response.force_on_start, response.force_on_end]
        )

    base_energy, base_force = energy_and_force(points)
    audit = objectivity_audit(
        energy_and_force,
        points,
        rotation,
        np.array([1.7, -2.2, 0.8]),
        energy_scale=max(base_energy, 1.0),
        force_scale=max(float(np.linalg.norm(base_force)), 1.0),
    )
    assert audit.relative_energy_change <= 2.0e-13
    assert audit.relative_force_covariance_error <= 2.0e-12

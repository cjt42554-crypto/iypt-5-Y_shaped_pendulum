from __future__ import annotations

import numpy as np
import pytest

from ypendulum_hfv2.contact import (
    BobSegmentConstraint,
    ContactGeometryError,
    ConvexParameterPolygon,
    DegenerateContactGeometry,
    GeometryTolerances,
    SegmentPairConstraint,
    clip_parameter_polygon,
    closest_bob_segment_witness,
    closest_segment_pair_witness,
    full_parameter_polygon,
)


@pytest.fixture
def tolerances() -> GeometryTolerances:
    return GeometryTolerances(
        collapsed_segment_length_m=1.0e-12,
        zero_witness_distance_m=1.0e-12,
        parameter_merge_absolute=2.0e-11,
        squared_distance_tie_relative=2.0e-11,
        polygon_halfspace_absolute=2.0e-14,
        polygon_area_absolute=1.0e-14,
        socket_radial_monotonicity_min_m2=1.0e-12,
        socket_projective_opening_margin_min=-1.0e-12,
        socket_cut_gap_min_m=-1.0e-10,
    )


def _segment_constraint(
    domains: tuple[ConvexParameterPolygon, ...],
    *,
    category: str = "same_branch_full",
) -> SegmentPairConstraint:
    return SegmentPairConstraint(
        constraint_id="pair:test_a|test_b",
        category=category,
        first_branch_id="first",
        first_segment_id="test_a",
        first_start_node="p0",
        first_end_node="p1",
        second_branch_id="second",
        second_segment_id="test_b",
        second_start_node="q0",
        second_end_node="q1",
        required_center_distance_m=0.2,
        parameter_domains=domains,
    )


def test_interior_point_segment_witness_has_exact_gap_and_gradient(
    tolerances: GeometryTolerances,
) -> None:
    constraint = BobSegmentConstraint(
        constraint_id="bob:guard:s000",
        branch_id="guard",
        segment_id="s000",
        start_node="left",
        end_node="right",
        parameter_min=0.0,
        parameter_max=1.0,
        required_center_distance_m=0.2,
    )
    witness = closest_bob_segment_witness(
        np.array([0.0, 0.3, 0.0]),
        np.array([-1.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
        constraint,
        tolerances,
    )
    assert witness.gap_m == pytest.approx(0.1)
    assert witness.second_parameter == pytest.approx(0.5)
    np.testing.assert_allclose(witness.normal_second_to_first, [0.0, 1.0, 0.0])
    np.testing.assert_allclose(
        witness.object_gap_gradients,
        [[0.0, 1.0, 0.0], [0.0, -0.5, 0.0], [0.0, -0.5, 0.0]],
    )
    np.testing.assert_allclose(np.sum(witness.object_gap_gradients, axis=0), 0.0)


def test_interior_skew_segment_pair_has_exact_endpoint_gradient(
    tolerances: GeometryTolerances,
) -> None:
    witness = closest_segment_pair_witness(
        np.array([-1.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
        np.array([0.0, -1.0, 0.3]),
        np.array([0.0, 1.0, 0.3]),
        _segment_constraint((full_parameter_polygon(),)),
        tolerances,
    )
    assert witness.gap_m == pytest.approx(0.1)
    assert witness.first_parameter == pytest.approx(0.5)
    assert witness.second_parameter == pytest.approx(0.5)
    np.testing.assert_allclose(witness.normal_second_to_first, [0.0, 0.0, -1.0])
    np.testing.assert_allclose(np.sum(witness.object_gap_gradients, axis=0), 0.0)


def test_partial_material_halfspace_forces_a_unique_boundary_witness(
    tolerances: GeometryTolerances,
) -> None:
    partial = clip_parameter_polygon(
        full_parameter_polygon(),
        first_coefficient=-1.0,
        second_coefficient=1.0,
        constant=-0.5,
        tolerances=tolerances,
    )
    assert partial is not None
    witness = closest_segment_pair_witness(
        np.array([0.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
        np.array([0.0, 0.0, 0.3]),
        np.array([0.0, 1.0, 0.3]),
        _segment_constraint((partial,), category="same_branch_partial"),
        tolerances,
    )
    assert witness.first_parameter == pytest.approx(0.0)
    assert witness.second_parameter == pytest.approx(0.5)
    assert witness.distance_m == pytest.approx(np.sqrt(0.34))


def test_multi_polygon_union_selects_one_unique_piece(
    tolerances: GeometryTolerances,
) -> None:
    left = clip_parameter_polygon(
        full_parameter_polygon(),
        first_coefficient=-1.0,
        second_coefficient=0.0,
        constant=0.4,
        tolerances=tolerances,
    )
    right = clip_parameter_polygon(
        full_parameter_polygon(),
        first_coefficient=1.0,
        second_coefficient=0.0,
        constant=-0.6,
        tolerances=tolerances,
    )
    assert left is not None and right is not None
    witness = closest_segment_pair_witness(
        np.array([0.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
        np.array([0.8, -1.0, 0.3]),
        np.array([0.8, 1.0, 0.3]),
        _segment_constraint((left, right), category="junction_socket"),
        tolerances,
    )
    assert witness.first_parameter == pytest.approx(0.8)
    assert witness.second_parameter == pytest.approx(0.5)
    assert witness.active_feature.startswith("domain_1:")


def test_symmetric_socket_union_is_nonsmooth_but_split_pieces_are_unique(
    tolerances: GeometryTolerances,
) -> None:
    first_outside = clip_parameter_polygon(
        full_parameter_polygon(),
        first_coefficient=1.0,
        second_coefficient=0.0,
        constant=-0.2,
        tolerances=tolerances,
    )
    first_inside = clip_parameter_polygon(
        full_parameter_polygon(),
        first_coefficient=-1.0,
        second_coefficient=0.0,
        constant=0.2,
        tolerances=tolerances,
    )
    assert first_inside is not None
    second_outside = clip_parameter_polygon(
        first_inside,
        first_coefficient=0.0,
        second_coefficient=1.0,
        constant=-0.2,
        tolerances=tolerances,
    )
    assert first_outside is not None and second_outside is not None
    angle = np.deg2rad(60.0)
    first_start = np.zeros(3)
    first_end = np.array([1.0, 0.0, 0.0])
    second_start = np.zeros(3)
    second_end = np.array([np.cos(angle), np.sin(angle), 0.0])
    with pytest.raises(DegenerateContactGeometry, match="non-unique"):
        closest_segment_pair_witness(
            first_start,
            first_end,
            second_start,
            second_end,
            _segment_constraint((first_outside, second_outside), category="junction_socket"),
            tolerances,
        )
    first_witness = closest_segment_pair_witness(
        first_start,
        first_end,
        second_start,
        second_end,
        _segment_constraint((first_outside,), category="junction_socket"),
        tolerances,
    )
    second_witness = closest_segment_pair_witness(
        first_start,
        first_end,
        second_start,
        second_end,
        _segment_constraint((second_outside,), category="junction_socket"),
        tolerances,
    )
    assert first_witness.first_parameter == pytest.approx(0.2)
    assert first_witness.second_parameter == pytest.approx(0.1)
    assert second_witness.first_parameter == pytest.approx(0.1)
    assert second_witness.second_parameter == pytest.approx(0.2)


def test_duplicate_convex_piece_is_rejected(tolerances: GeometryTolerances) -> None:
    square = full_parameter_polygon()
    with pytest.raises(ContactGeometryError, match="Duplicate convex pieces"):
        _segment_constraint((square, square))


@pytest.mark.parametrize(
    ("first_start", "first_end", "second_start", "second_end"),
    [
        (
            np.array([0.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),
            np.array([0.2, 0.3, 0.0]),
            np.array([0.8, 0.3, 0.0]),
        ),
        (
            np.array([-1.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),
            np.array([0.0, -1.0, 0.0]),
            np.array([0.0, 1.0, 0.0]),
        ),
    ],
)
def test_parallel_overlap_and_zero_distance_fail_closed(
    first_start: np.ndarray,
    first_end: np.ndarray,
    second_start: np.ndarray,
    second_end: np.ndarray,
    tolerances: GeometryTolerances,
) -> None:
    with pytest.raises(DegenerateContactGeometry):
        closest_segment_pair_witness(
            first_start,
            first_end,
            second_start,
            second_end,
            _segment_constraint((full_parameter_polygon(),)),
            tolerances,
        )


def test_collapsed_segment_fails_closed(tolerances: GeometryTolerances) -> None:
    with pytest.raises(DegenerateContactGeometry, match="collapsed"):
        closest_segment_pair_witness(
            np.zeros(3),
            np.zeros(3),
            np.array([0.0, 1.0, 0.0]),
            np.array([1.0, 1.0, 0.0]),
            _segment_constraint((full_parameter_polygon(),)),
            tolerances,
        )

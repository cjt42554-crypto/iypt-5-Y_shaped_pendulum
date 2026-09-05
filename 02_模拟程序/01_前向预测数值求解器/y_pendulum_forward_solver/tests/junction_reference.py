"""Independent Cartesian reference for the finite-mass junction tests.

This module deliberately does not import :mod:`y_pendulum_forward.junction`.
The production backend eliminates the holonomic constraints in manifold
coordinates.  Here the junction and bob are instead advanced as two Cartesian
particles and the three constraint multipliers are obtained from a 9 by 9 KKT
solve at every right-hand-side evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from scipy.integrate import solve_ivp
from scipy.linalg import eigh


@dataclass(frozen=True)
class CartesianParameters:
    """Physical data and independently reconstructed intersection geometry."""

    A: np.ndarray
    B: np.ndarray
    e_z: np.ndarray
    g: float
    mass: float
    junction_mass: float
    s_A: float
    s_B: float
    lower_length: float
    O: np.ndarray
    e_x: np.ndarray
    e_y: np.ndarray
    d: float
    x_C: float
    a_A: float
    a_B: float
    h: float

    @classmethod
    def from_physical(cls, physical: dict[str, Any]) -> "CartesianParameters":
        A = np.asarray(physical["A"], dtype=float)
        B = np.asarray(physical["B"], dtype=float)
        e_z = np.asarray(physical["e_z"], dtype=float)
        e_z = e_z / np.linalg.norm(e_z)
        support = B - A
        d = float(np.linalg.norm(support))
        e_x = support / d
        e_y = np.cross(e_z, e_x)
        O = 0.5 * (A + B)
        s_A = float(physical["s_A"])
        s_B = float(physical["s_B"])
        x_C = (s_A * s_A - s_B * s_B) / (2.0 * d)
        a_A = x_C + 0.5 * d
        a_B = 0.5 * d - x_C
        h = float(np.sqrt(s_A * s_A - a_A * a_A))
        return cls(
            A=A,
            B=B,
            e_z=e_z,
            g=float(physical["g"]),
            mass=float(physical["mass"]),
            junction_mass=float(physical["junction_mass"]),
            s_A=s_A,
            s_B=s_B,
            lower_length=float(physical["lower_length"]),
            O=O,
            e_x=e_x,
            e_y=e_y,
            d=d,
            x_C=x_C,
            a_A=a_A,
            a_B=a_B,
            h=h,
        )


def moving_frame(params: CartesianParameters, theta: float) -> tuple[np.ndarray, np.ndarray]:
    """Return the intersection-circle radial and tangent vectors."""

    e_r = np.sin(theta) * params.e_y + np.cos(theta) * params.e_z
    e_theta = np.cos(theta) * params.e_y - np.sin(theta) * params.e_z
    return e_r, e_theta


def state_to_cartesian(params: CartesianParameters, state: np.ndarray) -> np.ndarray:
    """Map the eight stored coordinates to two Cartesian particles."""

    state = np.asarray(state, dtype=float)
    theta, nu = state[:2]
    n = state[2:5]
    eta = state[5:8]
    e_r, e_theta = moving_frame(params, float(theta))
    junction = params.O + params.x_C * params.e_x + params.h * e_r
    bob = junction + params.lower_length * n
    v_junction = params.h * nu * e_theta
    v_bob = v_junction + params.lower_length * eta
    return np.concatenate((junction, bob, v_junction, v_bob))


def cartesian_to_state(params: CartesianParameters, cartesian: np.ndarray) -> np.ndarray:
    """Recover manifold coordinates from a constraint-consistent Cartesian state."""

    junction, bob, v_junction, v_bob = np.asarray(cartesian, dtype=float).reshape(4, 3)
    center = params.O + params.x_C * params.e_x
    radial = (junction - center) / params.h
    theta = float(np.arctan2(radial @ params.e_y, radial @ params.e_z))
    _, e_theta = moving_frame(params, theta)
    nu = float(v_junction @ e_theta / params.h)
    n = (bob - junction) / params.lower_length
    eta = (v_bob - v_junction) / params.lower_length
    return np.concatenate(([theta, nu], n, eta))


def constraint_values(params: CartesianParameters, cartesian: np.ndarray) -> np.ndarray:
    junction, bob = np.asarray(cartesian, dtype=float).reshape(4, 3)[:2]
    lower = bob - junction
    return np.array(
        [
            np.linalg.norm(junction - params.A) - params.s_A,
            np.linalg.norm(junction - params.B) - params.s_B,
            np.linalg.norm(lower) - params.lower_length,
        ]
    )


def constraint_velocity_values(
    params: CartesianParameters, cartesian: np.ndarray
) -> np.ndarray:
    junction, bob, v_junction, v_bob = np.asarray(cartesian, dtype=float).reshape(4, 3)
    lower = bob - junction
    return np.array(
        [
            (junction - params.A) @ v_junction / params.s_A,
            (junction - params.B) @ v_junction / params.s_B,
            lower @ (v_bob - v_junction) / params.lower_length,
        ]
    )


def kkt_accelerations(
    params: CartesianParameters, cartesian: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    """Solve Newton's equations and all three differentiated constraints.

    The constraints are half squared lengths.  With the sign convention in
    ``M a + G.T lambda = f``, multiplying each KKT multiplier by its branch
    length gives the physical tensile force.
    """

    junction, bob, v_junction, v_bob = np.asarray(cartesian, dtype=float).reshape(4, 3)
    lower = bob - junction
    relative_velocity = v_bob - v_junction
    G = np.zeros((3, 6))
    G[0, :3] = junction - params.A
    G[1, :3] = junction - params.B
    G[2, :3] = -lower
    G[2, 3:] = lower
    mass_matrix = np.diag(
        [params.junction_mass] * 3 + [params.mass] * 3
    )
    KKT = np.block(
        [[mass_matrix, G.T], [G, np.zeros((3, 3), dtype=float)]]
    )
    gravity = np.concatenate(
        (
            params.junction_mass * params.g * params.e_z,
            params.mass * params.g * params.e_z,
        )
    )
    curvature = -np.array(
        [
            v_junction @ v_junction,
            v_junction @ v_junction,
            relative_velocity @ relative_velocity,
        ]
    )
    solution = np.linalg.solve(KKT, np.concatenate((gravity, curvature)))
    tensions = solution[6:] * np.array(
        [params.s_A, params.s_B, params.lower_length]
    )
    return solution[:6], tensions, float(np.linalg.cond(KKT))


def cartesian_rhs(
    params: CartesianParameters, _time: float, cartesian: np.ndarray
) -> np.ndarray:
    accelerations, _, _ = kkt_accelerations(params, cartesian)
    velocities = np.asarray(cartesian, dtype=float)[6:12]
    return np.concatenate((velocities, accelerations))


def cartesian_energy(params: CartesianParameters, cartesian: np.ndarray) -> float:
    """Mechanical energy from particle positions and velocities only."""

    junction, bob, v_junction, v_bob = np.asarray(cartesian, dtype=float).reshape(4, 3)
    junction_eq = params.O + params.x_C * params.e_x + params.h * params.e_z
    bob_eq = junction_eq + params.lower_length * params.e_z
    kinetic = 0.5 * params.junction_mass * (v_junction @ v_junction)
    kinetic += 0.5 * params.mass * (v_bob @ v_bob)
    potential = -params.junction_mass * params.g * (
        (junction - junction_eq) @ params.e_z
    )
    potential -= params.mass * params.g * ((bob - bob_eq) @ params.e_z)
    return float(kinetic + potential)


def integrate_cartesian(
    params: CartesianParameters,
    initial_state: np.ndarray,
    final_time: float,
    *,
    rtol: float = 2e-12,
    atol: float = 2e-14,
    max_step: float = 0.001,
    dense_output: bool = True,
    events: list[Callable[[float, np.ndarray], float]] | None = None,
):
    return solve_ivp(
        lambda time, value: cartesian_rhs(params, time, value),
        (0.0, float(final_time)),
        state_to_cartesian(params, initial_state),
        method="DOP853",
        rtol=rtol,
        atol=atol,
        max_step=max_step,
        dense_output=dense_output,
        events=events,
    )


def tension_events(params: CartesianParameters):
    """Create independent terminal zero-tension event functions."""

    events = []
    for index in range(3):
        def event(_time, cartesian, component=index):
            return float(kkt_accelerations(params, cartesian)[1][component])

        event.direction = -1
        event.terminal = True
        events.append(event)
    return events


def _small_displacement_positions(
    params: CartesianParameters, q: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Cartesian placement for q=(theta,n_x,n_y) near equilibrium."""

    theta, n_x, n_y = np.asarray(q, dtype=float)
    if n_x * n_x + n_y * n_y >= 1.0:
        raise ValueError("local direction chart left its unit disk")
    n_z = np.sqrt(1.0 - n_x * n_x - n_y * n_y)
    e_r, _ = moving_frame(params, float(theta))
    junction = params.O + params.x_C * params.e_x + params.h * e_r
    direction = n_x * params.e_x + n_y * params.e_y + n_z * params.e_z
    return junction, junction + params.lower_length * direction


def independent_linear_modes(
    params: CartesianParameters,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build M and K from Cartesian particle geometry, then solve K v=w2 M v.

    The Jacobians use centered position differences.  The stiffness is the
    centered finite-difference Hessian of the Cartesian gravitational
    potential; neither matrix is taken from the angular equations in J.8 or
    J.11.
    """

    # Long-double, fourth-order differences control cancellation without
    # importing the production angular mass/stiffness formulas.
    dtype = np.longdouble
    step = dtype("0.001")
    origin = np.zeros(3, dtype=dtype)
    center = np.asarray(params.O + params.x_C * params.e_x, dtype=dtype)
    ex, ey, ez = [np.asarray(x, dtype=dtype) for x in (params.e_x, params.e_y, params.e_z)]

    def positions(q):
        theta, nx, ny = q
        j = center + dtype(params.h) * (np.sin(theta) * ey + np.cos(theta) * ez)
        n = nx * ex + ny * ey + np.sqrt(1 - nx * nx - ny * ny) * ez
        return j, j + dtype(params.lower_length) * n

    j0, b0 = positions(origin)
    def potential(q):
        j, bob = positions(q)
        return -dtype(params.g) * (dtype(params.junction_mass) * ((j-j0) @ ez)
                                  + dtype(params.mass) * ((bob-b0) @ ez))

    jj, jb = np.empty((3, 3), dtype=dtype), np.empty((3, 3), dtype=dtype)
    K = np.empty((3, 3), dtype=dtype)
    for i in range(3):
        delta = origin.copy(); delta[i] = step
        jm2, bm2 = positions(-2*delta); jm1, bm1 = positions(-delta)
        jp1, bp1 = positions(delta); jp2, bp2 = positions(2*delta)
        jj[:,i] = (jm2 - 8*jm1 + 8*jp1 - jp2)/(12*step)
        jb[:,i] = (bm2 - 8*bm1 + 8*bp1 - bp2)/(12*step)
        K[i,i] = (-potential(2*delta)+16*potential(delta)-30*potential(origin)
                  +16*potential(-delta)-potential(-2*delta))/(12*step**2)
        for j in range(i):
            other=origin.copy(); other[j]=step
            mixed=dtype(0)
            for ci,wi in [(-2,1),(-1,-8),(1,8),(2,-1)]:
                for cj,wj in [(-2,1),(-1,-8),(1,8),(2,-1)]:
                    mixed += wi*wj*potential(ci*delta+cj*other)
            K[i,j]=K[j,i]=mixed/(144*step**2)
    M = dtype(params.junction_mass) * jj.T @ jj + dtype(params.mass) * jb.T @ jb
    M, K = np.asarray(M, dtype=float), np.asarray(K, dtype=float)
    eigenvalues, eigenvectors = eigh(K, M)
    return np.sqrt(eigenvalues), eigenvectors, M, K


def local_cartesian_mass(
    params: CartesianParameters, q: np.ndarray, *, step: float = 2e-6
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the local mass matrix and both Cartesian position Jacobians."""

    q = np.asarray(q, dtype=float)
    jac_junction = np.empty((3, 3))
    jac_bob = np.empty((3, 3))
    for index in range(3):
        delta = np.zeros(3)
        delta[index] = step
        jp, bp = _small_displacement_positions(params, q + delta)
        jm, bm = _small_displacement_positions(params, q - delta)
        jac_junction[:, index] = (jp - jm) / (2.0 * step)
        jac_bob[:, index] = (bp - bm) / (2.0 * step)
    mass_matrix = params.junction_mass * jac_junction.T @ jac_junction
    mass_matrix += params.mass * jac_bob.T @ jac_bob
    return mass_matrix, jac_junction, jac_bob


def finite_difference_potential_gradient(
    params: CartesianParameters, q: np.ndarray, *, step: float = 2e-6
) -> np.ndarray:
    """Finite-difference the Cartesian gravitational potential in a local chart."""

    equilibrium_junction, equilibrium_bob = _small_displacement_positions(
        params, np.zeros(3)
    )

    def potential(value):
        junction, bob = _small_displacement_positions(params, value)
        return float(
            -params.junction_mass
            * params.g
            * ((junction - equilibrium_junction) @ params.e_z)
            - params.mass
            * params.g
            * ((bob - equilibrium_bob) @ params.e_z)
        )

    gradient = np.empty(3)
    for index in range(3):
        delta = np.zeros(3)
        delta[index] = step
        gradient[index] = (
            potential(q + delta) - potential(q - delta)
        ) / (2.0 * step)
    return gradient

from __future__ import annotations

import unittest

import numpy as np

from y_pendulum_forward.activation import (
    activation,
    activation_prime,
    activation_primitive,
    tension_components,
)


class ActivationTests(unittest.TestCase):
    def test_piecewise_endpoints_and_primitive(self):
        delta = 0.03
        epsilon = 1e-8
        for point in (0.0, delta):
            left = activation(point - epsilon, delta)
            center = activation(point, delta)
            right = activation(point + epsilon, delta)
            self.assertLess(abs(left - center), 2e-8)
            self.assertLess(abs(right - center), 2e-8)
        x = np.linspace(-0.02, 0.08, 1001)
        derivative = np.gradient(activation_primitive(x, delta), x)
        self.assertLess(np.max(np.abs(derivative[2:-2] - activation(x[2:-2], delta))), 2e-5)

    def test_derivative_matches_activation(self):
        delta = 0.02
        points = np.array([0.003, 0.009, 0.017, 0.03])
        step = 1e-7
        numerical = (activation(points + step, delta) - activation(points - step, delta)) / (2 * step)
        np.testing.assert_allclose(numerical, activation_prime(points, delta), rtol=2e-6, atol=2e-7)

    def test_tension_and_dissipation_are_nonnegative(self):
        stretch = np.array([0.8, 1.0, 1.002, 1.02, 1.05])
        rates = np.array([-2.0, 1.0, -10.0, -20.0, 3.0])
        elastic, viscous, total = tension_components(
            stretch, rates, EA=20.0, Ca=0.2, delta=0.01
        )
        self.assertTrue(np.all(total >= 0))
        self.assertTrue(np.all((total - elastic) * rates >= -1e-13))
        self.assertEqual(elastic[0], 0.0)
        self.assertEqual(total[0], 0.0)


if __name__ == "__main__":
    unittest.main()


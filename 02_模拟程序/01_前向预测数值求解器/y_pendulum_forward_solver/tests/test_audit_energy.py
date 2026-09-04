from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from y_pendulum_forward.cable import CableFEM, parse_cable_physical
from y_pendulum_forward.contracts import load_json
from y_pendulum_forward.energy_ledger import integrate_power_ledger
from y_pendulum_forward.runner import run_config

ROOT = Path(__file__).resolve().parents[1]


class IndependentLedgerTests(unittest.TestCase):
    def test_polynomial_power_exact_on_nonuniform_accepted_mesh(self):
        mesh = np.array([0., .13, .6, 1.])
        samples = np.array([0., .04, .13, .42, 1.])
        work, count = integrate_power_ledger(mesh, samples, lambda t: np.array([t**5, -t**2, 1 + t**4]))
        expected = np.column_stack([samples**6/6, -samples**3/3, samples + samples**5/5])
        np.testing.assert_allclose(work, expected, rtol=2e-14, atol=1e-15)
        self.assertGreater(count, 0)

    def test_final_work_independent_of_output_grid(self):
        mesh = np.array([0., .03, .1, .2, .8, 1.])
        power = lambda t: np.array([np.sin(17*t), np.exp(-t), abs(np.cos(3*t))])
        coarse, _ = integrate_power_ledger(mesh, np.array([0., 1.]), power)
        fine, _ = integrate_power_ledger(mesh, np.linspace(0, 1, 101), power)
        np.testing.assert_array_equal(coarse[-1], fine[-1])

    def test_rejects_extrapolation_and_nonfinite_power(self):
        with self.assertRaises(ValueError):
            integrate_power_ledger(np.array([0., 1.]), np.array([1.1]), lambda t: np.zeros(3))
        with self.assertRaises(FloatingPointError):
            integrate_power_ledger(np.array([0., 1.]), np.array([1.]), lambda t: np.array([1, np.nan, 1]))

    def test_empty_samples_and_zero_time(self):
        work, count = integrate_power_ledger(np.array([0.]), np.array([]), lambda t: np.zeros(3))
        self.assertEqual(work.shape, (0, 3)); self.assertEqual(count, 0)
        work, count = integrate_power_ledger(np.array([0.]), np.array([0.]), lambda t: np.zeros(3))
        np.testing.assert_array_equal(work, np.zeros((1, 3))); self.assertEqual(count, 0)


class CableAuditTests(unittest.TestCase):
    def config(self):
        c = load_json(ROOT / 'configs/cable_example.json')
        c['physical']['T'] = .01
        c['numerics'].update(elements={'A': 2, 'B': 2, 'lower': 2}, max_step=.0005, output_dt=.01)
        c['observation']['record_times']['stop'] = .01
        return c

    def test_spd_condition_number_reuses_eigenspectrum_without_svd(self):
        c = self.config()
        issues, physical = parse_cable_physical(c)
        self.assertEqual(issues, [])
        with patch('numpy.linalg.cond', side_effect=AssertionError('redundant SVD')):
            m = CableFEM(physical, c['numerics'])
        self.assertAlmostEqual(m.mass_diagnostics['condition_number'] / np.linalg.cond(m.M_ff), 1., places=11)

    def test_actual_run_uses_solver_mesh_work_and_explicit_dynamic_scale(self):
        c = self.config()
        coarse = run_config(c)
        c = deepcopy(c); c['numerics']['output_dt'] = .00025
        fine = run_config(c)
        self.assertEqual(coarse.contract_status, ['COMPLETED'])
        self.assertEqual(fine.contract_status, ['COMPLETED'])
        for key in ['power_integral_physical_traction', 'power_integral_algebraic_reaction']:
            self.assertEqual(coarse.diagnostics[key][-1], fine.diagnostics[key][-1])
        self.assertEqual(coarse.diagnostics['power_quadrature_method'], 'accepted_step_dense_output_gauss_legendre_3')
        self.assertGreater(coarse.diagnostics['power_quadrature_evaluations'], 0)
        self.assertGreater(coarse.diagnostics['accepted_steps'], 0)
        self.assertIn('dynamic_energy_scale_resolved', coarse.diagnostics)
        self.assertIn('max_dynamic_relative_energy_power_residual_algebraic_reaction', coarse.diagnostics)
        self.assertLess(coarse.diagnostics['dynamic_energy_scale'], coarse.diagnostics['energy_scale'])
        self.assertTrue(all(t >= 0 for t in coarse.diagnostics['timings_seconds'].values()))


if __name__ == '__main__':
    unittest.main()

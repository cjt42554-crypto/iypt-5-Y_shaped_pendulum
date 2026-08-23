"""Y-shaped pendulum forward-theory numerical backends.

This package is deliberately limited to the numerical implementation of the
frozen forward models.  It contains neither a high-fidelity model nor
structural/reduced-order conclusions.
"""

from .contracts import THEORY_SHA256, PROGRAM_VERSION, SimulationResult
from .runner import run_config, run_file
from .ensemble import SampledPredictionSetResult, run_ensemble, write_ensemble

__all__ = [
    "THEORY_SHA256",
    "PROGRAM_VERSION",
    "SimulationResult",
    "SampledPredictionSetResult",
    "run_config",
    "run_file",
    "run_ensemble",
    "write_ensemble",
]

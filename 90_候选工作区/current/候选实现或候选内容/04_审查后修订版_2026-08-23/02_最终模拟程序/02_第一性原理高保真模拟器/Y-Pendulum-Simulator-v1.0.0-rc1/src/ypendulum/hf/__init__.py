"""Independent high-fidelity Y-pendulum backend."""

from .certificate_io import (
    HF_CERTIFICATE_SIDECAR,
    read_hf_certificate_sidecar,
    write_hf_certificate_sidecar,
)
from .independence import run_hf_independence_study
from .model import HighFidelityModel
from .solver import PreparationResult, prepare_initial_state, simulate_high_fidelity
from .state import HighFidelityResult
from .validation import certify_single_hf_bundle, run_hf_validation

__all__ = [
    "HighFidelityModel",
    "HighFidelityResult",
    "HF_CERTIFICATE_SIDECAR",
    "certify_single_hf_bundle",
    "read_hf_certificate_sidecar",
    "run_hf_independence_study",
    "run_hf_validation",
    "PreparationResult",
    "prepare_initial_state",
    "simulate_high_fidelity",
    "write_hf_certificate_sidecar",
]

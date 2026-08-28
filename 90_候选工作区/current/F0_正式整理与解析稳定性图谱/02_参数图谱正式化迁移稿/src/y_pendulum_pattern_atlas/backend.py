"""Bound adapter to the existing formal FWD-TORUS-1.0 backend.

This module contains no torus equation and no independent ODE integrator.
The temporary import path is restored exactly on success and failure.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .source_manifest import (
    ATLAS_IDENTITY,
    FORMAL_BACKEND_RELATIVE_PATH,
    FORMAL_CONTRACTS_RELATIVE_PATH,
    FORMAL_THEORY_RELATIVE_PATH,
    ContractViolation,
    sha256_file,
)

FORMAL_PROJECT_RELATIVE_PATH = FORMAL_BACKEND_RELATIVE_PATH.parents[1]


@contextmanager
def _temporary_sys_path(path: Path) -> Iterator[None]:
    original = list(sys.path)
    try:
        sys.path.insert(0, str(path.resolve()))
        yield
    finally:
        sys.path[:] = original


@dataclass(frozen=True)
class FormalTorusBackend:
    repository_root: Path
    source_path: Path
    source_sha256: str
    contracts_path: Path
    contracts_sha256: str
    theory_source_path: Path
    theory_source_sha256: str
    embedded_theory_sha256: str
    run_torus: Callable[..., Any]

    def run(self, config: dict[str, Any]) -> Any:
        identity = {
            "consumer": ATLAS_IDENTITY,
            "formal_backend_path": self.source_path.relative_to(
                self.repository_root
            ).as_posix(),
            "formal_backend_sha256": self.source_sha256,
            "formal_contracts_sha256": self.contracts_sha256,
            "formal_theory_source_sha256": self.theory_source_sha256,
            "tuning_interpretation": "ideal_model_internal_not_experimental_calibration",
        }
        result = self.run_torus(config, identity=identity)
        if result.model_id != "FWD-TORUS-1.0":
            raise RuntimeError(f"Unexpected formal model identity: {result.model_id}")
        if result.contract_status != ["COMPLETED"]:
            raise RuntimeError(
                "Formal torus trajectory did not complete its all-taut domain: "
                f"contract={result.contract_status}, numerical={result.numerical_status}, "
                f"events={result.events}"
            )
        if result.numerical_status != "SUCCESS_SINGLE_RUN":
            raise RuntimeError(f"Formal torus backend returned {result.numerical_status}")
        return result


def find_repository_root(start: Path) -> Path:
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "AGENTS.md").is_file() and (
            candidate / FORMAL_BACKEND_RELATIVE_PATH
        ).is_file():
            return candidate
    raise FileNotFoundError(
        "Could not locate the repository root containing AGENTS.md and the "
        "formal FWD-TORUS-1.0 backend."
    )


def load_formal_backend(
    repository_root: Path,
    *,
    formal_backend_relative_path: Path = FORMAL_BACKEND_RELATIVE_PATH,
    expected_source_sha256: str | None = None,
    expected_contracts_sha256: str | None = None,
    expected_theory_source_sha256: str | None = None,
) -> FormalTorusBackend:
    root = repository_root.resolve()
    if formal_backend_relative_path != FORMAL_BACKEND_RELATIVE_PATH:
        raise ContractViolation(
            "wrong formal backend path: "
            f"expected {FORMAL_BACKEND_RELATIVE_PATH}, got {formal_backend_relative_path}"
        )
    source_path = (root / FORMAL_BACKEND_RELATIVE_PATH).resolve()
    contracts_path = (root / FORMAL_CONTRACTS_RELATIVE_PATH).resolve()
    theory_path = (root / FORMAL_THEORY_RELATIVE_PATH).resolve()
    project_path = (root / FORMAL_PROJECT_RELATIVE_PATH).resolve()
    for path in (source_path, contracts_path, theory_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    source_hash = sha256_file(source_path)
    contracts_hash = sha256_file(contracts_path)
    theory_hash = sha256_file(theory_path)
    expected = (
        ("formal backend", expected_source_sha256, source_hash),
        ("formal contracts", expected_contracts_sha256, contracts_hash),
        ("formal theory", expected_theory_source_sha256, theory_hash),
    )
    for label, locked_hash, actual_hash in expected:
        if locked_hash is not None and locked_hash != actual_hash:
            raise ContractViolation(
                f"{label} hash drift: expected {locked_hash}, got {actual_hash}"
            )

    importlib.invalidate_caches()
    with _temporary_sys_path(project_path):
        module = importlib.import_module("y_pendulum_forward.torus")
        contracts = importlib.import_module("y_pendulum_forward.contracts")
    loaded_path = Path(module.__file__).resolve()
    loaded_contracts_path = Path(contracts.__file__).resolve()
    if loaded_path != source_path:
        raise ContractViolation(
            "imported y_pendulum_forward.torus is not the bound formal source: "
            f"loaded={loaded_path}, expected={source_path}"
        )
    if loaded_contracts_path != contracts_path:
        raise ContractViolation(
            "imported y_pendulum_forward.contracts is not the bound formal source: "
            f"loaded={loaded_contracts_path}, expected={contracts_path}"
        )
    return FormalTorusBackend(
        repository_root=root,
        source_path=source_path,
        source_sha256=source_hash,
        contracts_path=contracts_path,
        contracts_sha256=contracts_hash,
        theory_source_path=theory_path,
        theory_source_sha256=theory_hash,
        embedded_theory_sha256=str(contracts.THEORY_SHA256),
        run_torus=module.run_torus,
    )

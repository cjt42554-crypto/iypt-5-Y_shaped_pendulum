"""Bound adapter to the existing formal FWD-TORUS-1.0 backend.

This module deliberately contains no torus equation and no independent ODE
integrator.  Every result-bearing trajectory is produced by the formal
``y_pendulum_forward.torus.run_torus`` entry point.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FORMAL_BACKEND_RELATIVE_PATH = Path(
    "02_模拟程序/01_前向预测数值求解器/y_pendulum_forward_solver/y_pendulum_forward/torus.py"
)
FORMAL_PROJECT_RELATIVE_PATH = FORMAL_BACKEND_RELATIVE_PATH.parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class FormalTorusBackend:
    repository_root: Path
    source_path: Path
    source_sha256: str
    theory_sha256: str
    run_torus: Callable[..., Any]

    def run(self, config: dict[str, Any]) -> Any:
        identity = {
            "consumer": "YPS-IDEAL-TORUS-PATTERN-ATLAS-DRAFT-1.0",
            "formal_backend_path": self.source_path.relative_to(self.repository_root).as_posix(),
            "formal_backend_sha256": self.source_sha256,
            "tuning_interpretation": ("ideal_model_internal_not_experimental_calibration"),
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


def load_formal_backend(repository_root: Path) -> FormalTorusBackend:
    root = repository_root.resolve()
    source_path = (root / FORMAL_BACKEND_RELATIVE_PATH).resolve()
    project_path = (root / FORMAL_PROJECT_RELATIVE_PATH).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    project_text = str(project_path)
    if project_text not in sys.path:
        sys.path.insert(0, project_text)
    module = importlib.import_module("y_pendulum_forward.torus")
    contracts = importlib.import_module("y_pendulum_forward.contracts")
    loaded_path = Path(module.__file__).resolve()
    if loaded_path != source_path:
        raise RuntimeError(
            "The imported y_pendulum_forward.torus is not the bound formal source: "
            f"loaded={loaded_path}, expected={source_path}"
        )
    return FormalTorusBackend(
        repository_root=root,
        source_path=source_path,
        source_sha256=sha256_file(source_path),
        theory_sha256=str(contracts.THEORY_SHA256),
        run_torus=module.run_torus,
    )

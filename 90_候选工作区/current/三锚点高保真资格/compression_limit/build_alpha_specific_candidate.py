#!/usr/bin/env python3
"""Build an isolated alpha-specific held-equilibrium HF candidate overlay.

The formal simulator tree is never edited.  Exact-source-identity replacements
are applied to a generated shadow copy, then three OUT_OF_SCOPE 4:3 controlled
limit configurations are validated against that copy.  This builder performs
no equilibrium solve and no dynamic integration by default.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

SCRIPT_PATH = Path(__file__).resolve()
CANDIDATE_ROOT = SCRIPT_PATH.parents[1]
REPOSITORY_ROOT = CANDIDATE_ROOT.parents[2]
FORMAL_ROOT = (
    REPOSITORY_ROOT
    / "02_模拟程序"
    / "02_第一性原理高保真模拟器"
    / "Y-Pendulum-Simulator-v1.0.0-rc1"
)
FORMAL_SOURCE_ROOT = FORMAL_ROOT / "src"
BASE_CONFIG_PATH = CANDIDATE_ROOT / "configs" / "4to3.yaml"
DEFAULT_OUTPUT_ROOT = CANDIDATE_ROOT / "generated" / "alpha_specific_candidate"
TARGET_SCALES = (1.0e-2, 1.0e-4, 1.0e-6)
EXPECTED_FORMAL_GIT_BLOBS = {
    "ypendulum/config/validation.py": "7b66ae8c54a507c974d69be9ded05267dbb21439",
    "ypendulum/hf/solver.py": "325ad43aa8088a55defeae9851c9ccfa508fe936",
}

VALIDATION_BILATERAL_BLOCK = '''        if (
            cfg.initial_condition.type == "held_endpoint_equilibrium_release"
            and cfg.high_fidelity.compression_regularization_scale != 1.0
        ):
            code = "HF_HELD_PREPARATION_REQUIRES_BILATERAL_ROD"
            details = {
                "compression_regularization_scale": (
                    cfg.high_fidelity.compression_regularization_scale
                ),
                "required": 1.0,
            }
            raise ConfigurationError(
                f"{code}: held endpoint equilibrium preparation is registered only "
                "for the full bilateral rod (compression_regularization_scale=1).",
                code=code,
                details=details,
            )
'''
VALIDATION_ALPHA_REPLACEMENT = '''        # Candidate overlay decision: a controlled alpha<1 limit study may use
        # the same fixed-endpoint conservative preparation.  The pre-existing
        # controlled-limit range and OUT_OF_SCOPE claim checks remain binding.
'''

SOLVER_DOCSTRING_OLD = '''    """Prepare a stable bilateral-rod minimum with all endpoint DOFs held."""'''
SOLVER_DOCSTRING_NEW = '''    """Prepare a stable regularized-rod minimum with all endpoint DOFs held."""'''
SOLVER_BILATERAL_BLOCK = '''    if model.compression_regularization_scale != 1.0:
        raise ValueError(
            "held_endpoint_equilibrium_release requires the bilateral finite-rod "
            "compression_regularization_scale=1."
        )
'''
SOLVER_ALPHA_REPLACEMENT = '''    if not 0.0 < model.compression_regularization_scale <= 1.0:
        raise ValueError(
            "held_endpoint_equilibrium_release requires "
            "0 < compression_regularization_scale <= 1."
        )
'''
SOLVER_PROTOCOL_OLD = '''        "protocol": "HELD_ENDPOINT_STABLE_BILATERAL_EQUILIBRIUM_V1",'''
SOLVER_PROTOCOL_NEW = '''        "protocol": (
            "HELD_ENDPOINT_STABLE_BILATERAL_EQUILIBRIUM_V1"
            if model.compression_regularization_scale == 1.0
            else "HELD_ENDPOINT_STABLE_ALPHA_SPECIFIC_EQUILIBRIUM_V2_CANDIDATE"
        ),
        "compression_regularization_scale": float(
            model.compression_regularization_scale
        ),
        "preparation_identity": (
            "same fixed endpoints; independent deterministic multi-seed energy "
            "minimization under the target constitutive scale"
        ),'''
SOLVER_MODE_OLD = '''        preparation_mode=(
            "held_endpoint_bilateral_stable_equilibrium"
            if not has_prescribed_release_velocity
            else "held_endpoint_stable_equilibrium_with_prescribed_release_velocity"
        ),'''
SOLVER_MODE_NEW = '''        preparation_mode=(
            (
                "held_endpoint_bilateral_stable_equilibrium"
                if model.compression_regularization_scale == 1.0
                else "held_endpoint_alpha_specific_stable_equilibrium_candidate"
            )
            if not has_prescribed_release_velocity
            else (
                "held_endpoint_stable_equilibrium_with_prescribed_release_velocity"
                if model.compression_regularization_scale == 1.0
                else "held_endpoint_alpha_specific_equilibrium_with_prescribed_release_velocity_candidate"
            )
        ),'''

PATCHES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "ypendulum/config/validation.py": (
        (
            "admit controlled alpha-specific held preparation",
            VALIDATION_BILATERAL_BLOCK,
            VALIDATION_ALPHA_REPLACEMENT,
        ),
    ),
    "ypendulum/hf/solver.py": (
        ("generalize preparation docstring", SOLVER_DOCSTRING_OLD, SOLVER_DOCSTRING_NEW),
        (
            "admit positive regularized compression scale",
            SOLVER_BILATERAL_BLOCK,
            SOLVER_ALPHA_REPLACEMENT,
        ),
        ("version preparation audit", SOLVER_PROTOCOL_OLD, SOLVER_PROTOCOL_NEW),
        ("version preparation mode", SOLVER_MODE_OLD, SOLVER_MODE_NEW),
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha1_bytes(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()  # noqa: S324 - Git identity


def git_blob_sha1_file(path: Path) -> str:
    return git_blob_sha1_bytes(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def replace_exact_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Candidate patch {label!r} expected one source match; found {count}."
        )
    return text.replace(old, new, 1)


def patched_source_text(relative_path: str, text: str) -> tuple[str, list[str]]:
    labels: list[str] = []
    for label, old, new in PATCHES[relative_path]:
        text = replace_exact_once(text, old, new, label=label)
        labels.append(label)
    compile(text, relative_path, "exec")
    return text, labels


def audit_formal_source() -> dict[str, Any]:
    records: dict[str, Any] = {}
    for relative_path, expected_blob in EXPECTED_FORMAL_GIT_BLOBS.items():
        source = FORMAL_SOURCE_ROOT / relative_path
        actual_blob = git_blob_sha1_file(source)
        if actual_blob != expected_blob:
            raise RuntimeError(
                f"Formal source drift for {relative_path}: "
                f"expected {expected_blob}, got {actual_blob}."
            )
        patched, labels = patched_source_text(
            relative_path, source.read_text(encoding="utf-8")
        )
        records[relative_path] = {
            "formal_git_blob_sha1": actual_blob,
            "formal_sha256": sha256_file(source),
            "candidate_sha256": hashlib.sha256(
                patched.encode("utf-8")
            ).hexdigest(),
            "replacement_labels": labels,
        }
    return records


def scale_slug(scale: float) -> str:
    mapping = {1.0e-2: "alpha_1e-2", 1.0e-4: "alpha_1e-4", 1.0e-6: "alpha_1e-6"}
    return mapping[float(scale)]


def candidate_config_document(base: dict[str, Any], scale: float) -> dict[str, Any]:
    candidate = copy.deepcopy(base)
    slug = scale_slug(scale)
    candidate["run"]["name"] = f"four_to_three_alpha_specific_held_{slug}"
    candidate["run"]["output_directory"] = (
        f"generated/compression_limit/alpha_specific/{slug}"
    )
    candidate["run"]["claim_level"] = "OUT_OF_SCOPE"
    candidate["high_fidelity"]["compression_regularization_scale"] = float(scale)
    candidate["high_fidelity"]["controlled_limit_study"] = True
    return candidate


def leaf_differences(left: Any, right: Any, prefix: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(leaf_differences(left[key], right[key], child))
        return paths
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [prefix]
        paths: list[str] = []
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            paths.extend(
                leaf_differences(left_item, right_item, f"{prefix}[{index}]")
            )
        return paths
    return [] if left == right else [prefix]


def emit_configs(output_root: Path) -> list[dict[str, Any]]:
    base = yaml.safe_load(BASE_CONFIG_PATH.read_text(encoding="utf-8"))
    config_root = output_root / "configs"
    config_root.mkdir(parents=True, exist_ok=True)
    allowed = {
        "run.name",
        "run.output_directory",
        "run.claim_level",
        "high_fidelity.compression_regularization_scale",
        "high_fidelity.controlled_limit_study",
    }
    records: list[dict[str, Any]] = []
    for scale in TARGET_SCALES:
        slug = scale_slug(scale)
        candidate = candidate_config_document(base, scale)
        differences = leaf_differences(base, candidate)
        if set(differences) != allowed:
            raise RuntimeError(
                f"Unexpected alpha candidate differences for {slug}: {differences}"
            )
        path = config_root / f"{slug}.yaml"
        path.write_text(
            yaml.safe_dump(
                candidate,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
        records.append(
            {
                "scale": scale,
                "slug": slug,
                "path": str(path.relative_to(output_root)),
                "sha256": sha256_file(path),
                "differences_from_alpha1_base": differences,
            }
        )
    return records


def build_overlay(output_root: Path) -> tuple[Path, dict[str, Any]]:
    overlay_source = output_root / "overlay" / "src"
    if overlay_source.parent.exists():
        shutil.rmtree(overlay_source.parent)
    shutil.copytree(FORMAL_SOURCE_ROOT, overlay_source)
    source_records = audit_formal_source()
    for relative_path in PATCHES:
        target = overlay_source / relative_path
        patched, _ = patched_source_text(
            relative_path, target.read_text(encoding="utf-8")
        )
        target.write_text(patched, encoding="utf-8")
        source_records[relative_path]["overlay_sha256"] = sha256_file(target)
        if source_records[relative_path]["overlay_sha256"] != source_records[
            relative_path
        ]["candidate_sha256"]:
            raise RuntimeError(f"Overlay write drift for {relative_path}.")
    return overlay_source, source_records


def validate_with_overlay(
    overlay_source: Path, output_root: Path, config_records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    code = r'''
import json
import sys
from pathlib import Path
from ypendulum.config import load_config, resolved_config_sha256, validate_physical_config
records = []
for raw in sys.argv[1:]:
    path = Path(raw).resolve()
    cfg = load_config(path)
    validate_physical_config(cfg)
    records.append({
        "path": str(path),
        "accepted": True,
        "resolved_config_sha256": resolved_config_sha256(cfg),
        "preparation_type": cfg.initial_condition.type,
        "compression_regularization_scale": cfg.high_fidelity.compression_regularization_scale,
        "controlled_limit_study": cfg.high_fidelity.controlled_limit_study,
        "claim_level": cfg.run.claim_level,
    })
print(json.dumps(records, sort_keys=True))
'''
    paths = [str(output_root / record["path"]) for record in config_records]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(overlay_source),
            environment.get("PYTHONPATH", ""),
        ]
    ).rstrip(os.pathsep)
    completed = subprocess.run(
        [sys.executable, "-c", code, *paths],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        cwd=CANDIDATE_ROOT,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Candidate overlay validation failed:\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def build(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    overlay_source, source_records = build_overlay(output_root)
    config_records = emit_configs(output_root)
    validations = validate_with_overlay(overlay_source, output_root, config_records)
    report = {
        "schema_version": "YPS-4TO3-ALPHA-SPECIFIC-HELD-CANDIDATE-1.0",
        "status": "CANDIDATE_OVERLAY_AND_CONFIGS_READY__PREPARATION_NOT_RUN",
        "primary_preparation_identity": "ALPHA_SPECIFIC_HELD_EQUILIBRIUM",
        "secondary_sensitivity_identity": "SHARED_ALPHA1_STATE_CONSTITUTIVE_QUENCH",
        "formal_tree_modified": False,
        "formal_change_authorized": False,
        "base_config": str(BASE_CONFIG_PATH.relative_to(CANDIDATE_ROOT)),
        "base_config_sha256": sha256_file(BASE_CONFIG_PATH),
        "target_scales": list(TARGET_SCALES),
        "exact_zero_role": "mathematical_endpoint_only",
        "source_patch_audit": source_records,
        "configs": config_records,
        "overlay_validations": validations,
        "runnable_candidate_count": len(validations),
        "prepared_state_count": 0,
        "dynamic_run_count": 0,
        "next_gate": (
            "Run alpha-specific held preparations in the isolated overlay.  Each "
            "target must independently demonstrate residual, PSD stability including the "
            "small-alpha conditioning cross-check, raw guard positivity and the complete "
            "local-scale qualification before release dynamics."
        ),
        "claim_boundary": (
            "The overlay only removes the two bilateral-only admission checks and "
            "versions the preparation audit.  It reuses the existing deterministic "
            "multi-seed energy minimizer; no equilibrium or trajectory has been run."
        ),
    }
    write_json(output_root / "plan.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    report = build(args.output_root)
    print(
        json.dumps(
            {
                "status": report["status"],
                "runnable_candidate_count": report["runnable_candidate_count"],
                "prepared_state_count": report["prepared_state_count"],
                "dynamic_run_count": report["dynamic_run_count"],
                "output_root": str(args.output_root),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

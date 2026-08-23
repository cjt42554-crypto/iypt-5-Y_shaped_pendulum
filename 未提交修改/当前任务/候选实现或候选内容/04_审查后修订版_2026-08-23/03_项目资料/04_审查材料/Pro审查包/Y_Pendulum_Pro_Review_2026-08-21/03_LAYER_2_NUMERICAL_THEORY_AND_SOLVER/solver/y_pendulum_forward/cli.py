"""Command-line interface kept separate from both physics backends."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

from .contracts import json_safe, load_json
from .convergence import run_refinement_study
from .ensemble import run_ensemble, write_ensemble
from .io import write_result
from .runner import run_config


def _load_cli_json(path: Path, *, exit_code: int) -> tuple[dict | None, int]:
    """Load strict JSON and turn all expected input errors into one-line evidence."""

    try:
        return load_json(path), 0
    except (OSError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        payload = {
            "status": "INPUT_REJECTED",
            "path": str(path),
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        print(
            json.dumps(
                json_safe(payload),
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            ),
            file=sys.stderr,
        )
        return None, exit_code


def _report_cli_write_error(exc: Exception, *, output: Path) -> None:
    payload = {
        "status": "OUTPUT_REJECTED",
        "output": str(output),
        "error_type": type(exc).__name__,
        "message": str(exc),
    }
    print(
        json.dumps(
            json_safe(payload),
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        ),
        file=sys.stderr,
    )


def _atomic_write_text(path: Path, text: str) -> None:
    """Commit one report by same-directory atomic replacement."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.tmp-",
            delete=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            temporary_path = Path(handle.name)
        temporary_path.replace(path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="y-pendulum-forward",
        description="Numerical implementation of the frozen Y-pendulum forward theories",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="run one frozen configuration")
    run.add_argument("config", type=Path)
    run.add_argument("--output", type=Path)
    run.add_argument("--overwrite", action="store_true")
    run.add_argument("--no-plots", action="store_true")
    convergence = subparsers.add_parser("converge", help="run three-level refinement studies")
    convergence.add_argument("config", type=Path)
    convergence.add_argument("--output", type=Path, required=True)
    convergence.add_argument("--overwrite", action="store_true")
    ensemble = subparsers.add_parser(
        "ensemble", help="run every member of a finite sampled prediction set"
    )
    ensemble.add_argument("spec", type=Path)
    ensemble.add_argument("--output", type=Path, required=True)
    ensemble.add_argument("--plots", action="store_true")
    subparsers.add_parser("self-test", help="run deterministic unit and short-run tests")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run":
        config, load_status = _load_cli_json(args.config, exit_code=2)
        if config is None:
            return load_status
        result = run_config(config)
        output = args.output
        if output is None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            output = Path("runs") / f"{config.get('model_id','unknown')}_{stamp}"
        print(json.dumps(result.summary_dict(), ensure_ascii=False, indent=2, allow_nan=False))
        if result.metadata.get("config_sha256") == "UNHASHABLE_INVALID_CONFIG":
            return 2
        try:
            write_result(
                output,
                config,
                result,
                overwrite=args.overwrite,
                plots=not args.no_plots,
            )
        except (OSError, TypeError, ValueError, OverflowError) as exc:
            _report_cli_write_error(exc, output=output)
            return 2
        print(f"output: {output.resolve()}")
        return (
            0
            if result.numerical_status
            in {"SUCCESS_SINGLE_RUN", "SUCCESS_EVENT"}
            else 2
        )
    if args.command == "converge":
        config, load_status = _load_cli_json(args.config, exit_code=3)
        if config is None:
            return load_status
        if args.output.exists() and not args.overwrite:
            print(
                f"refusing to overwrite existing convergence report: {args.output}",
                file=sys.stderr,
            )
            return 2
        report = run_refinement_study(config)
        if args.output.exists() and not args.output.is_file():
            print(
                f"convergence output is not a regular file: {args.output}",
                file=sys.stderr,
            )
            return 2
        try:
            report_text = json.dumps(
                json_safe(report),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            _atomic_write_text(args.output, report_text)
        except (OSError, TypeError, ValueError, OverflowError) as exc:
            _report_cli_write_error(exc, output=args.output)
            return 3
        print(json.dumps(json_safe(report), ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if report["qualification"] == "REFINEMENT_SUPPORTED" else 3
    if args.command == "ensemble":
        spec, load_status = _load_cli_json(args.spec, exit_code=4)
        if spec is None:
            return load_status
        if args.output.exists():
            _report_cli_write_error(
                FileExistsError(
                    f"refusing to overwrite ensemble output path: {args.output}"
                ),
                output=args.output,
            )
            return 4
        result = run_ensemble(spec)
        print(
            json.dumps(
                json_safe(result.summary_dict()),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        )
        if (
            result.status == "INVALID_ENSEMBLE_INPUT"
            or result.ensemble_sha256 == "UNHASHABLE_INVALID_ENSEMBLE"
        ):
            return 4
        try:
            write_ensemble(args.output, spec, result, plots=args.plots)
        except (OSError, TypeError, ValueError, OverflowError) as exc:
            _report_cli_write_error(exc, output=args.output)
            return 4
        print(f"output: {args.output.resolve()}")
        return 0 if result.status == "SAMPLED_PREDICTION_SET_COMPLETE" else 4
    if args.command == "self-test":
        start = Path(__file__).resolve().parents[1] / "tests"
        suite = unittest.defaultTestLoader.discover(str(start), pattern="test_*.py")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())

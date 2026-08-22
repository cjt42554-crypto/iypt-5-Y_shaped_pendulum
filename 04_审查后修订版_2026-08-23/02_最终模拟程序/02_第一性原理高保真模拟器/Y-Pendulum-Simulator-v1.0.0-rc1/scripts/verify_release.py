#!/usr/bin/env python3
"""Verify the complete project ZIP, SHA-256 sidecar and internal file manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip_path")
    parser.add_argument("--checksum")
    parser.add_argument("--output")
    args = parser.parse_args()
    zip_path = Path(args.zip_path).resolve()
    checksum_path = (
        Path(args.checksum).resolve()
        if args.checksum
        else zip_path.with_suffix(zip_path.suffix + ".sha256.txt")
    )
    findings: list[str] = []
    actual_zip_sha = sha(zip_path)
    if not checksum_path.exists():
        findings.append(f"checksum sidecar missing: {checksum_path}")
    else:
        expected = checksum_path.read_text(encoding="utf-8").strip().split()[0]
        if expected != actual_zip_sha:
            findings.append("ZIP SHA-256 differs from sidecar")

    with tempfile.TemporaryDirectory(prefix="ypendulum-release-verify-") as tmp:
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            roots = {name.split("/", 1)[0] for name in names if "/" in name}
            if len(roots) != 1:
                findings.append(f"archive must have exactly one root directory, got {sorted(roots)}")
            archive.extractall(tmp)
        root = Path(tmp) / next(iter(roots)) if len(roots) == 1 else Path(tmp)
        manifest_path = root / "PROJECT_FILE_MANIFEST.json"
        if not manifest_path.exists():
            findings.append("PROJECT_FILE_MANIFEST.json missing from archive")
            manifest = {"files": {}}
        else:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded = manifest.get("files", {})
        for relative, metadata in recorded.items():
            path = root / relative
            if not path.is_file():
                findings.append(f"manifest file missing: {relative}")
                continue
            if path.stat().st_size != int(metadata["size_bytes"]):
                findings.append(f"size mismatch: {relative}")
            if sha(path) != metadata["sha256"]:
                findings.append(f"hash mismatch: {relative}")
        actual = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.name != "PROJECT_FILE_MANIFEST.json"
        }
        unrecorded = sorted(actual.difference(recorded))
        absent = sorted(set(recorded).difference(actual))
        if unrecorded:
            findings.append(f"unrecorded archive files: {unrecorded[:20]}")
        if absent:
            findings.append(f"recorded files absent: {absent[:20]}")

    report = {
        "zip": str(zip_path),
        "zip_sha256": actual_zip_sha,
        "checksum_sidecar": str(checksum_path),
        "recorded_file_count": len(recorded),
        "passed": not findings,
        "findings": findings,
    }
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

def test_prefreeze_manifest_matches_frozen_candidate_files() -> None:
    manifest_path = ROOT / 'hard_contact_candidate' / 'prefreeze.json'
    if not manifest_path.exists():
        pytest.skip('prefreeze.json is generated after the candidate files are finalized')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['contact_runs_observed_before_freeze'] == 0
    assert manifest['dynamic_contact_runs_observed_before_freeze'] == 0
    for relative_path, expected in manifest['sha256'].items():
        actual = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
        assert actual == expected

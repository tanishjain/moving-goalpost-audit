"""Integrity verification (separate from analysis reproduction): manifests, inventory and hash drift."""
import json
import subprocess
import sys

import pytest

import reproduce_analyses as ra
import verify_snapshot as vs
from conftest import ROOT

CELLS = "data/signed_release/benchmark/g5_cells_source_text_free.csv"


def test_snapshot_matches_export_manifest():
    assert vs.verify(ROOT) == []


def test_signed_release_verifier_passes_unchanged():
    run = subprocess.run([sys.executable, str(ROOT / "data/signed_release/verify_release.py")],
                         capture_output=True, text=True)
    assert run.returncode == 0 and "17 artifacts" in run.stdout, run.stdout + run.stderr


def test_hash_drift_is_detected_by_both_verifiers_and_blocks_reproduction(snapshot_copy):
    p = snapshot_copy / CELLS
    p.write_bytes(p.read_bytes() + b"\n")
    assert f"hash mismatch: {CELLS}" in vs.verify(snapshot_copy)
    run = subprocess.run([sys.executable, str(snapshot_copy / "data/signed_release/verify_release.py")],
                         capture_output=True, text=True)
    assert run.returncode != 0
    with pytest.raises(ra.ReproductionError, match="hash drift"):
        ra.verify_inputs(snapshot_copy)


def test_unlisted_and_missing_files_are_detected(snapshot_copy):
    (snapshot_copy / "data" / "extra_cases.csv").write_text("case_id\n1\n")
    (snapshot_copy / "docs" / "REPRODUCTION_COVERAGE.md").unlink()
    problems = vs.verify(snapshot_copy)
    assert "unlisted file: data/extra_cases.csv" in problems
    assert "missing: docs/REPRODUCTION_COVERAGE.md" in problems


def test_manifest_records_explicit_provenance_for_every_file():
    man = json.loads((ROOT / "EXPORT_MANIFEST.json").read_text())
    kinds = {"verbatim", "adapted", "extracted", "generated", "new"}
    assert man["status"].startswith("RELEASE 1.0.0")
    for rel, rec in man["files"].items():
        assert rec["provenance"] in kinds, rel
        if rec["provenance"] == "verbatim":
            assert rec["source_sha256"] == rec["sha256"], rel
        if rec["provenance"] in {"adapted", "extracted"}:
            assert rec["source_sha256"] != rec["sha256"] and rec.get("note"), rel
    adapted = {rel for rel, rec in man["files"].items() if rec["provenance"] == "adapted"}
    assert adapted == {"code/scripts/validation/build_error_cascade.py"}
    assert man["files"]["code/scripts/validation/g5_run_ablation.py"]["provenance"] == "extracted"



@pytest.mark.parametrize("kind", ["directory", "file"])
def test_root_git_metadata_is_not_snapshot_content(tmp_path, kind):
    (tmp_path / "EXPORT_MANIFEST.json").write_text(json.dumps({"files": {}}))
    git = tmp_path / ".git"
    if kind == "directory":
        git.mkdir()
        (git / "HEAD").write_text("ref: refs/heads/main\n")
    else:
        git.write_text("gitdir: ../administrative-directory\n")
    assert vs.verify(tmp_path) == []


def test_nested_git_content_is_still_unlisted(tmp_path):
    (tmp_path / "EXPORT_MANIFEST.json").write_text(json.dumps({"files": {}}))
    nested = tmp_path / "data" / ".git"
    nested.mkdir(parents=True)
    (nested / "extra").write_text("unexpected snapshot content")
    assert "unlisted file: data/.git/extra" in vs.verify(tmp_path)

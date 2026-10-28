"""Exact inventory, exact data columns and a fail-closed content screen of the distributed files.

The patterns are written so they do not match their own source text. Patterns naming private archive locations
are deliberately not reproduced here; the private build screen applies them before export."""
import csv
import json
import re

from conftest import ROOT

MANIFEST = json.loads((ROOT / "EXPORT_MANIFEST.json").read_text())
ALLOWED_SUFFIXES = {".cff", ".csv", ".json", ".md", ".py", ".txt", ".toml", ".pdf", ".png", ".svg", ""}
BINARY = {".pdf", ".png"}

SIGNED_COLUMNS = {
    "benchmark/g5_cells_source_text_free.csv": [
        "case_id", "model_identifier", "arm", "terminal_status", "model_gate_a", "model_gate_d", "derived_disposition",
        "human_reference_gate_a", "human_reference_label", "correct"],
    "benchmark/sampling_weights_observed.csv": [
        "nct_id", "pmid", "observed_inclusion", "inclusion_probability_mc", "inclusion_probability_independent_approx",
        "inverse_probability_weight_mc", "inverse_probability_weight_independent_approx", "n_components_eligible"],
    "benchmark/g5_wrong_paper_arm2_responses.csv": [
        "model", "human_reference_gate_a", "arm", "n_cases", "valid_material_change", "valid_no_material_change",
        "valid_unassessable", "invalid", "invalid_schema_fail", "invalid_semantic_fail", "invalid_transport_fail"],
    "cascade_denominators.csv": ["family", "start", "gate_a_pass", "gate_b_pass", "gate_c_pass_raw",
                                 "gate_c_pass_substantive", "target_material"],
}
FORBIDDEN_COLUMN_TOKENS = ("abstract", "prompt", "raw_text", "response_id", "request_id", "rationale", "free_text",
                           "notes", "primary_outcome", "worksheet", "blind")
CONTENT_PATTERNS = {
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.(?:com|edu|org|net|io|ai|uk)\b"),
    "local absolute path": re.compile(r"/(?:Users|home|private/tmp)/[^/\s]+/|[A-Za-z]:\\\\(?:Users|Documents)"),
    "audit blind identifier": re.compile(r"\bG[BCD]\d{2}\b"),
    "credential literal": re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"),
    "private key block": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "provider request header": re.compile(r"x-(?:github-)?request-id", re.I),
    "serialized response identifier": re.compile(r'"response_id"\s*:'),
    "copilot transport": re.compile("api\\.github" + "copilot|Copilot-Integration" + "-Id|Editor-Plugin" + "-Version"),
}
SELF = "tests/test_inventory_and_privacy.py"


def _files():
    return {p.relative_to(ROOT).as_posix(): p for p in ROOT.rglob("*")
            if p.is_file() and p.relative_to(ROOT).parts[0] != ".git"
            and not ({"__pycache__", ".pytest_cache", ".venv", "reproduction_output"}
                                    & set(p.relative_to(ROOT).parts))}


def test_inventory_is_exactly_the_manifest():
    assert set(_files()) == set(MANIFEST["files"]) | {"EXPORT_MANIFEST.json"}


def test_no_unexpected_file_types_or_names():
    for rel in _files():
        assert ("." + rel.rsplit(".", 1)[-1] if "." in rel.rsplit("/", 1)[-1] else "") in ALLOWED_SUFFIXES, rel
        assert not re.search(r"(?i)worksheet|blind_key|hidden|packet|pilot|attempts|\.env|secret|credential|"
                             r"\.jsonl$|\.npz$|\.docx$|\.xlsx$", rel), rel


def test_signed_data_columns_are_exact_and_no_csv_has_text_columns():
    for rel, cols in SIGNED_COLUMNS.items():
        with (ROOT / "data/signed_release" / rel).open(newline="") as fh:
            assert next(csv.reader(fh)) == cols, rel
    for rel, p in _files().items():
        if rel.endswith(".csv"):
            with p.open(newline="") as fh:
                header = next(csv.reader(fh), [])
            assert not [c for c in header if any(t in c.lower() for t in FORBIDDEN_COLUMN_TOKENS)], rel


def test_no_private_or_sensitive_content():
    hits = []
    for rel, p in _files().items():
        if rel == SELF:
            continue
        text = p.read_bytes().decode("latin-1")
        for label, pat in CONTENT_PATTERNS.items():
            if pat.search(text):
                hits.append(f"{rel}: {label}")
    assert hits == []

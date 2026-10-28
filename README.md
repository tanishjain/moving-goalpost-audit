# Moving Goalpost — public code and source-text-free derived data (version 1.0.0)

**Version 1.0.0.** Archive DOI: https://doi.org/10.5281/zenodo.23693399 (Zenodo). Repository:
https://github.com/tanishjain/moving-goalpost-audit. This directory is a history-free, allowlisted snapshot; it is
not a copy of the private working repository.

This snapshot accompanies the manuscript *Publication identity and abstract availability constrained an automated
registry-to-publication outcome audit* (Tanish Jain, Alessandra Casamento). It contains the analysis code, prompt
templates and response schema, and the source-text-free categorical data needed to reproduce the publicly supportable
analyses, together with integrity manifests and offline tests.

- Scientific analysis family: `author_approved_post_audit` v1.0.0 (signed scientific run `2f7a8fcfb09e392a`;
  active presentation run `ff8e426d9e7267cc`).
- All 97 reference cases: 97 → 45 → 30 → 13 raw / 14 substantive → 2. P4-positive cases: 83 → 32 → 17 → 7 / 8 → 2.
  The two denominator families are reported separately and never joined.
- The 97 cases are an enriched, deliberately selected reference sample that was inspected and used throughout the
  study. They are not an untouched external test set, and no population prevalence can be estimated from them.

## Contents

| Path | What it is |
|---|---|
| `data/signed_release/` | The signed source-text-free release package, byte-identical to the approved release (its own `RELEASE_MANIFEST.json`, schema and `verify_release.py`). |
| `data/display_package/` | Approved manuscript tables (CSV and Markdown), figures, captions/data dictionary, audit summary and input pins, byte-identical to the active display package. |
| `code/src/moving_goalpost/` | The index pipeline package (verbatim). It needs external services and keys to run and is provided for transparency. |
| `code/scripts/` | Research scripts that define the reported analyses (verbatim, except one comment erratum and one extracted subset; see `docs/PROVENANCE.md`). |
| `code/prompts/` | Generic pipeline prompt templates, plus the frozen two-arm evaluator templates and JSON response schema with placeholders instead of case text. |
| `reproduce/` | `reproduce_analyses.py` and the approved target values it is checked against. |
| `tests/` | Offline tests: integrity, reproduction, fail-closed input handling, scoring rules and a privacy screen. |
| `docs/` | Reproduction coverage, provenance and errata, data availability. |
| `history/` | Retrospective study-history record (not a prospective registration). |
| `EXPORT_MANIFEST.json`, `SOURCE_TO_EXPORT_MAP.csv` | SHA-256 of every file and its source mapping. |

## Verify and reproduce (offline)

Python 3.11 or later. No network access, private data or credentials are needed after the pinned packages are
installed.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-lock.txt
python verify_snapshot.py                         # integrity of every file in this snapshot
python data/signed_release/verify_release.py      # integrity of the signed release package
python reproduce/reproduce_analyses.py            # analysis reproduction against approved values
python -m pytest -q                               # offline test suite
```

`verify_snapshot.py` and `verify_release.py` check integrity only. `reproduce_analyses.py` recomputes results from the
case-level categorical data with the frozen research functions and compares them with the approved aggregates. What
can and cannot be reproduced from this snapshot is listed in `docs/REPRODUCTION_COVERAGE.md`; the snapshot does not
regenerate every manuscript result.

## What is excluded

Publication abstracts; registry and publication free text; case-rendered prompts and raw model responses; private
reviewer worksheets, notes, emails and the blinded audit key; author-approval records; provider request/response
identifiers, credentials and private operational logs; pilot material; and the private repository history. See
`docs/DATA_AVAILABILITY.md`.

## Licenses and citation

Original code: MIT (`LICENSE`). Derived data and documentation in `data/`, `history/` and `docs/`: CC BY 4.0
(`LICENSE-DATA.md`). Third-party terms: `THIRD_PARTY_NOTICES.md`. Cite using `CITATION.cff`
(DOI 10.5281/zenodo.23693399); the manuscript citation will be added when the article is published.

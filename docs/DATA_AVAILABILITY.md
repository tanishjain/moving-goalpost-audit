# Data and code availability

**Available in this snapshot.** Analysis code, generic prompt templates, the evaluator response schema, source-text-free
derived data, approved aggregate tables and figures, integrity manifests and verifiers, an offline reproduction script
and tests. The derived data comprise the 97 case-level categorical cascade labels with provenance, the 582
case × model × arm categorical evaluator outputs (including all 49 invalid responses), the observed inclusion
probabilities and weights, registry timing codes and dates, and aggregate effect, mechanism, coverage and attrition
tables.

**Excluded.** Publication abstracts; registry and publication free text; case-rendered prompts and raw model responses
that contain that text; private reviewer worksheets, notes and emails; the blinded audit answer key; author-approval
records; provider request and response identifiers; credentials and private operational logs; development pilot
material; and the private working repository and its history. ClinicalTrials.gov and PubMed identifiers are included,
so the public source records can be consulted directly under their own terms.

**Not reproducible from the snapshot.** Source retrieval, human labeling, the full sampling replay, source-dependent
registry-date reselection and the original model calls. Approved aggregates are supplied for these
(`docs/REPRODUCTION_COVERAGE.md`).

**Model provenance.** The evaluator outputs come from model identifiers accessed through GitHub Copilot on
18 August 2026 (`claude-opus-4.6`, `gemini-3.1-pro-preview`, `gpt-5.4`). These are mutable service aliases, not
native-provider builds; no model weights or provider responses are redistributed.

**Persistent identifiers.** Version 1.0.0 archive DOI: https://doi.org/10.5281/zenodo.23693399 (Zenodo). Repository:
https://github.com/tanishjain/moving-goalpost-audit.

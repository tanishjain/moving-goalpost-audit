# Moving Goalpost — error-cascade diagnostic benchmark (prepublication)

This release contains a source-text-free benchmark and reproduction artifacts for a diagnostic study of
an automated registry-to-publication outcome-auditing pipeline. The study examines five distinct validity
conditions that can affect an end-to-end result: publication identity, outcome extraction, registry
timing and content, outcome equivalence, and evaluator-rubric alignment. The 97-case reference sample was
deliberately enriched using pipeline outputs; all performance estimates are sample-specific and must not
be interpreted as population prevalence.

## The cascade (gates)
A publication identity · B outcome extraction · C registry timing/content · D outcome equivalence
(latest-record and prospective-target) · E LLM-evaluator rubric alignment.

## Two denominator families (report both; never merge the system-flagged and reference sets)
- **P4-nested (system-flagged, n=83):** 83 -> 32 Gate-A pass -> 17 Gate-B pass -> 7 raw / 8 substantive
  Gate-C pass -> **2 cascade-terminal material classifications under the available abstract-centered evidence**.
- **All-97 reference sample:** 97 -> 45 -> 30 -> 13 raw / 14 substantive -> **2 cascade-terminal material
  classifications under the available abstract-centered evidence**.
See `cascade_denominators.csv`; the builder asserts these exact values.

## Package family
Analysis family `author_approved_post_audit` (version 1.0.0): the frozen author-coded cascade with four author-approved post-audit revisions after a bounded independent second-coder audit (three Gate-C substantive/wording interpretations to UNCLEAR, which receive no Gate-C credit, and one Gate-D timepoint to SAME). Revised and derived values carry the provenance tags `author_approved_post_audit` and `derived_from_post_audit_revision`. The frozen baseline (all-97 substantive Gate C = 16) is recorded in `RELEASE_MANIFEST.json` under `historical_frozen_denominator_families`.

## Gate-E mechanism analysis (G5 ablation)
Three model identifiers accessed through **GitHub Copilot on 2026-08-18** (`claude-opus-4.6`,
`gemini-3.1-pro-preview`, `gpt-5.4`) evaluated the 97 cases under Arm 1 (publication-identity Gate A +
harmonized Gate D) vs Arm 2 (Gate D only). Adding Gate A raised case-level agreement with the adjudicated
human reference by approximately 0.5 for every model. Without publication-identity assessment, incorrectly
matched publications received the correct disposition in only 0–1 of 47 cases per model; the responses were
mostly unassessable or invalid (`benchmark/g5_wrong_paper_arm2_responses.csv`). Both arms received identical
inputs under the same rubric, and no replacement publication was supplied. The identity step resolved this
upstream failure. Accuracy changed little among correctly matched
publications; the analysis does not indicate improved semantic-equivalence skill. See `benchmark/g5_*.csv`.

## Caveats
Enriched, stratified 97-case reference set (NOT population rates); only 7 reference positives (fragile
positive-class metrics); one model identifier (`gpt-5.4`) produced ~25% content failures — retained, not hidden.
Design-weighted CIs are suppressed (unstable pairwise variance); the unweighted exact table is primary.

All 97 cases were inspected and used in analysis. This is not an untouched external test set. Model tuning on
these cases creates leakage, so this package cannot support an external-validation claim or prevalence estimation.

## What is / isn't here
Included: identifiers, derived gate codes + provenance, registry timing facts/codes, aggregate and categorical
per-cell G5 tables, sampled-case inclusion probabilities/weights,
a standalone integrity verifier, and a hash manifest. **Excluded (never redistributed):** article
abstracts, registry/publication free text, raw prompts/responses, provider request/response IDs, the
blinded second-coder answer key, and contaminated pre-freeze pilots.

## Verify this package
Run `python verify_release.py` with Python 3.11 or later. It verifies every file against
`RELEASE_MANIFEST.json` and requires no private source data or third-party packages. Maintainers can rebuild the
package from the private research archive as described in `REPRODUCE.md`.

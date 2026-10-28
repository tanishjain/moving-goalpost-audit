# Provenance, source mapping and errata

Every file in this snapshot is listed with its SHA-256 in `EXPORT_MANIFEST.json`; `SOURCE_TO_EXPORT_MAP.csv` maps each exported file to its private source path and source SHA-256 where one exists. Provenance classes:

- **verbatim**: byte-identical copy of a pinned, signed source file;
- **adapted**: copy with a documented textual erratum (the export is not byte-identical to its source);
- **extracted**: verbatim definitions selected from a larger source file;
- **generated**: produced deterministically by the snapshot builder from exported content;
- **new**: written for this snapshot (documentation, reproduction code, tests, metadata).

Counts of files listed in `EXPORT_MANIFEST.json` (which does not list itself): adapted 1, extracted 1, generated 5, new 19, verbatim 89.

## Pinned scientific identity

- Analysis family `author_approved_post_audit` v1.0.0; signed scientific run `2f7a8fcfb09e392a`; active presentation run `ff8e426d9e7267cc`.
- `data/signed_release/` is byte-identical to the signed release package (its `RELEASE_MANIFEST.json` SHA-256 `f3f909dd961935cfbb09abc9be4e9673a6b734fe5dcb0cb71f776d2d1314e50f`), which is preserved unchanged as provenance, including its own README, license, citation metadata and verifier. Its citation file predates the confirmed author list; the snapshot's `CITATION.cff` supersedes it for citation.
- `data/display_package/` is byte-identical to the active display package of the presentation run, except that two internal files are not exported: `README.md` (private rebuild/promotion instructions for the signed display package); `VISUAL_INSPECTION.md` (internal QA record of the predecessor figures).
- `code/scripts/validation/g5_analyze.py` is byte-identical to the frozen analysis (SHA-256 `148103015f2cc6ad3b59460654d33143fc0e4b36cf6843ef80dd09e46c69f2e7`, recorded in the study history).

## Erratum E1 — `code/scripts/validation/build_error_cascade.py` (adapted)

Comment-only provenance correction. The signed comment attributed the 2026-08-17 corrections to a human methods reviewer; they came from an AI-assisted internal review and were source-reviewed and approved by the coding author. No code, label, formula, population or failure rule changes. Identifiers and output strings that say 'colleague audit' are unchanged and refer to the same internal review.

- Signed source SHA-256: `5f53d9136aae0abeb2bbc5399b58d782b838c1fd3f7fee1a43ee3b95c7bd74f9`
- Exported SHA-256: `42f674e6907c21b563fd1937cc8dd62411672bbee2c795c4d25257a0df5a85c0`
- The builder verifies that the change is comment-only (identical abstract syntax tree).

```diff
--- signed/scripts/validation/build_error_cascade.py
+++ export/code/scripts/validation/build_error_cascade.py
@@ -284,9 +284,11 @@
 ELEMENT_VALID = {"SAME", "COMPATIBLE", "DIFFERENT", "UNASSESSABLE", "NOT_APPLICABLE", ""}
 SUBST_VALID = {"SUBSTANTIVE_CHANGE", "WORDING_ONLY", "UNCLEAR"}
 
-# --- Colleague-audit corrections (COORD_COLLEAGUE_REVIEW_LOG.md, 2026-08-17), RDA-endorsed.
-# These transcribe a human methods reviewer's adjudication; provenance is tagged distinctly
-# from Tanish's original author-coding and the pre-correction values are kept in the audit file.
+# --- Internal-review corrections of 2026-08-17 ("colleague audit" in the names below).
+# [Public-snapshot erratum E1] These corrections came from an AI-assisted internal review and were
+# source-reviewed and approved by the coding author (approval reconfirmed 2026-10-07); they are not
+# a human methods reviewer's adjudication. Provenance is tagged distinctly from Tanish's original
+# author-coding and the pre-correction values are kept in the audit file.
 
 # Five Gate-C substantive/wording reversals (title-only worksheet corrected against the full
 # cached prospective/latest outcome objects). Corrected split: 20 substantive / 14 wording.
@@ -299,7 +301,7 @@
 }
 
 # Three Gate-D element queries. (expected_original, corrected, reason, still_open_needs_human).
-# Where the colleague left DIFFERENT-vs-UNASSESSABLE open, we apply the endorsed floor
+# Where the internal review left DIFFERENT-vs-UNASSESSABLE open, we apply the endorsed floor
 # (not COMPATIBLE -> UNASSESSABLE) and flag the row for human confirmation.
 GATE_D_QUERY_CORRECTIONS = {
     "NCT01076387": {"aggregation": ("COMPATIBLE", "UNASSESSABLE",
```

## Extraction E2 — `code/scripts/validation/g5_run_ablation.py` (extracted)

The frozen analysis imports the run harness for its strict journal scan, and the cell plan fixes the bootstrap case order. The exported module contains only verbatim copies of these top-level definitions, in source order: `ARMS`, `MODELS`, `MAX_ATTEMPTS`, `ORDER_SEED`, `N_REF`, `SOURCE_FIELDS`, `COMMON_PREAMBLE`, `GATE_A_BLOCK`, `GATE_D_BLOCK`, `SCHEMA_INSTR`, `ELEMENT_KEYS`, `RESPONSE_SCHEMA`, `_VALIDATOR`, `NOT_REPORTED`, `_field`, `case_block`, `render_prompt`, `_sha`, `gate_d_collapse`, `classify_response`, `ordered_plan`, `JournalIntegrityError`, `read_journal`, `scan_journal`. Service transport, authentication and credential handling, run authorization, locking, journal repair, case loading and orchestration are withheld, because they contain a personal contact identifier, local credential-file handling and service-specific client headers. None of the withheld code affects scoring, labels, populations or failure handling in the distributed data.

- Signed source SHA-256: `7f1122682e4b39ccd3c3b73dcc3575f41fb57f74bca7d13847ecc5a74ac3d944`
- Exported SHA-256: `2323bdb27217673d95a9bff22dc10f5874f81dc58e1232c8f10c02b624e67d69`
- `code/prompts/g5/` holds the Arm-1 and Arm-2 templates rendered from the exported literals with placeholders, plus the JSON response schema (generated).

## Not exported

- data/ (all other files) — private research data: source text, worksheets, attempt journals, caches, receipts.
- manuscript/ (drafts, submission documents, authoring notes) — manuscript files are distributed via the journal.
- manuscript/assets/README.md, VISUAL_INSPECTION.md — internal rebuild instructions and QA record.
- registration/ — private versions; a public-safe history copy is authored in history/.
- scripts/validation/g3_*, build_adjudication_sheet.py, apply_two_axis_remapping.py — audit packet/adjudication builders that reference blinded audit material.
- scripts/validation/analysis_families.py, build_public_release.py, audit_public_release.py, g3_final_package.py, check_repository_links.py — private package-maintenance tooling bound to private paths.
- scripts/validation/g5_run_ablation.py (transport/auth/run-control parts) — personal contact identifier, local credential-file handling and service-specific client headers.
- scripts/manuscript/, other scripts/ — private build tooling and historical exploratory scripts.
- prompts/g5_arm0_reconstructed.txt — abandoned, incorrectly sourced historical Arm-0 material.
- tests/ — private suite depends on private data; a public offline suite is authored in tests/.
- COORD_*.md, docs/, notebooks/, dashboard/, .env*, .claude/, .cursor/, pyproject.toml, uv.lock, Git history — private coordination, configuration, environment and history.

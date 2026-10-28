# Reproduction coverage

This table states what the snapshot reproduces from its distributed categorical data, and what it supplies only as
approved aggregates. "Reproduced" means `reproduce/reproduce_analyses.py` recomputes the result from case-level data
with the frozen research functions in `code/` and matches the approved output under the stated rule; the check
identifiers refer to its report. Nothing in the second table is claimed to be regenerated.

## Reproduced from the distributed data

| Result (manuscript location) | Inputs | Frozen function | Check | Rule |
|---|---|---|---|---|
| P4/P5 confusion counts, exact Clopper–Pearson intervals, F1, descriptive kappa (Table 2) | `cascade_labels.csv` | `g2_design_aware_validation.unweighted_metrics` | `G2-table2`, `G2-ledger` | exact at display precision |
| Correct-publication subset, n = 44 (Table 2, row 3) | `cascade_labels.csv` (Gate A PASS with `reference_agreement` provenance, which the frozen Gate-A rule assigns only when both reviewers accepted the match) | as above | `G2-table2` | exact |
| Observed-weight Hájek point estimates and effective sample size (Table 2 supplement) | `cascade_labels.csv`, `sampling_weights_observed.csv` | `g2_design_aware_validation.weighted_metrics` | `G2-weighted`, `G2-weighted-ledger` | exact at display precision; point estimates shown to be independent of the pairwise inclusion matrix |
| Unconditional gate distributions (Table 3) | `cascade_labels.csv` | direct counts | `CAS-marginals`, `CAS-ledger` | exact |
| Nested cascade, all 97 and P4-positive families separately (Figure 1B–C, Table 3, `cascade_denominators.csv`) | `cascade_labels.csv` | `build_error_cascade.compute_panels` | `CAS-nested`, `CAS-nested-display` | exact; families never joined |
| Gate-D element distributions and reference cross-tab, fixed 30-case panel (Supplementary Table S3) | `cascade_labels.csv` | `build_error_cascade.compute_panels` | `CAS-D-elements`, `CAS-D-crosstab` | exact |
| Completeness: 582 cells, 49 invalid responses (36 schema, 13 semantic, 0 transport) | `g5_cells_source_text_free.csv` | strict input validation | `G5-completeness` | exact |
| Disposition and correctness per cell | `g5_cells_source_text_free.csv` (arm, status, gates, human reference) | `g5_analyze.derive_bottom_line` | asserted before any check | must equal the released `derived_disposition` and `correct` columns |
| Model × arm status and determinate coverage (Supplementary Table S4A) | as above | `g5_analyze.run_reference_analysis`, `g5_build_release.table_status_coverage` | `G5-status_coverage`, `G5-S4A` | byte-identical CSV; display exact |
| Paired Arm-1 − Arm-2 contrasts with case-bootstrap intervals (seed 20260818, 10,000 draws) | as above | `g5_analyze.paired_contrast` via `run_reference_analysis` | `G5-primary_effects`, `G5-ledger` | byte-identical CSV |
| Contrasts stratified by the human publication-identity reference (Figure 2) | as above | `g5_build_release.table_mechanism_by_human_gate_a` | `G5-mechanism_by_human_gate_a` | byte-identical CSV |
| Gate-A agreement and conditional Gate D | as above | `g5_analyze.run_reference_analysis` | `G5-gate_a_and_conditional_d` | byte-identical CSV |
| Wrong-paper Arm-2 response composition (Supplementary Table S4B) | as above | `g5_build_release.table_wrong_paper_arm2_responses` | `G5-wrong_paper_arm2_responses`, `G5-S4B` | byte-identical CSV; display exact |

**Bootstrap order.** The case bootstrap resamples positions in the order in which the frozen run recorded its cells:
the seed-20260818 permutation of (case, arm, model) defined by `ordered_plan` in the run harness. The cell file is
sorted by case for readability, so the reproduction restores the frozen order with that same function. Sorting by case
instead changes the GPT-5.4 lower bound from 0.3918 to 0.3814; the report records both, and the released value is the
frozen-order result.

## Supplied as approved aggregates only (not regenerated here)

| Result | Why it cannot be recomputed from this snapshot | What is supplied |
|---|---|---|
| Source flow: 1,243 trials, 1,974 endpoint records, 1,103 matched, 1,099 abstracts, 1,001 compared (Table 1) | Requires registry/PubMed retrieval and stage files containing source text | Table 1; retrieval and pipeline code |
| Full-cohort P4/P5 flag rates (655/1,001; 627/1,001) | Requires full-cohort pipeline outputs containing source text | Table 1 |
| Sampling replay (1,000,000 seeds), pairwise inclusion probabilities, weighted variance and stability diagnostic | Requires the full sampling frame | Observed inclusion probabilities and weights; sampling code; suppressed-interval rule |
| Human reference labeling and inter-reviewer agreement (Table 1) | Reviewer-level judgments are not distributed | Final reference labels and agreement aggregates |
| Author coding of Gate B, Gate-C substantive interpretation and Gate-D elements | Requires source text; coding is human judgment | The resulting codes with provenance |
| Independent second-coder audit agreement and coverage (Supplementary Tables S5A–S5C) | Worksheets and the blinded answer key are excluded | Approved aggregate tables and summary |
| Author-approved post-audit revisions and frozen-baseline comparison (S5D) | The approval record is private | Approved comparison table; provenance tags in the labels |
| Gate-C registry timing derivation and month/year boundary sensitivity (Supplementary Table S2) | Requires registry version histories and outcome text | Timing codes and dates; Table S2; retrieval and sensitivity code |
| The 582 original model evaluations | Original calls cannot be rerun from distributed data, and case-rendered prompts and raw responses are excluded | Frozen templates and schema; response classifier; categorical outputs |
| Inter-model agreement and panel consensus | Computed by the frozen analysis from the cells, but no approved public aggregate is included to compare against | Not claimed |
| Figures | Figure code depends on the private build environment | Rendered figures and the tables they draw on |

# Manuscript display package — captions and data dictionary

Self-contained: every term used in the figures and tables is defined here, so the displays can be read
without any internal coordination file. All values are deterministically regenerated from the controlling
artifacts pinned in `INPUTS_MANIFEST.json`. Derived packaging only; not a new analysis.

## Figure captions

**Figure 1. Study flow and validity cascade.** (A) Trial-level source flow: 1,243
trials retrieved, 1,103 with a pipeline-selected publication (140 with none found), 1,099 with an abstract, and 1,001
with extracted published endpoint text that were compared and classified (98 abstracts yielded no endpoint text). The retrieved trials registered 1,974 primary-endpoint records;
this is a separate descriptive count, not an attrition step. Publication matching is a pipeline
operation, not verified identification of the primary-results publication. (B, C) Two separate nested denominator families for the diagnostic cascade, shown independently
and never merged: (B) all 97 reference cases — 45 passed Gate A,
30 also passed Gate B, and under Gate C 13 passed the raw textual
and 14 the substantive definition; 2 were
cascade-terminal material classifications under the available abstract-centered evidence. (C) the
83 P4-positive cases — 32,
17, 7 raw / 8 substantive,
2. Raw and substantive Gate C are alternative definitions of the same step (the
substantive definition folds wording-only registry changes into concordant and gives unclear changes no credit), not successive attrition.
The dagger (†) marks author-coded fields (Gate B and the Gate-C substantive interpretation); raw Gate C is
a fixed system field. Cohort flow (A) and the diagnostic cascade (B, C) are distinct denominators and are
not connected.

**Figure 2. Paired Gate-A mechanism analysis.** Accuracy of each model identifier under Arm 1
(publication identity assessed before a harmonized Gate-D rubric) and Arm 2 (the same rubric with no
publication-identity step), within the human-reference incorrectly matched publication (n=47) and correctly
matched publication (n=45) strata.
The 5 Gate-A-unassessable cases appear only in the all-97 contrast (47 + 45 + 5 = 97) and are not shown as
a stratum. Without publication-identity assessment, only 0–1 of the 47 incorrectly matched publications per
model received the correct disposition; the responses were mostly unassessable or invalid
(Supplementary Table S4B). Both arms received identical inputs, and no replacement publication was
supplied.
The identity step resolved this upstream failure while changing accuracy among correctly matched publications
little; it does not demonstrate improved semantic-equivalence skill. The all-97 paired differences with
prespecified 95% case-bootstrap intervals are
secondary and shown beneath the panels. Model identifiers accessed through GitHub Copilot on 2026-08-18; not native-provider models. Invalid or
indeterminate responses were counted as incorrect. The main figure is single-column (stacked panels); a
wide side-by-side alternate (`figure2_mechanism_wide`) is optional.

## Table captions

**Table 1.** Cohort, sampling, and human-reference characteristics, with a provenance code on every row.
The count of final-label disagreements resolved by an original reviewer (17) is read from
`system_validation_vs_human_gold.json`.
**Table 2.** Performance of the fixed screen. The unweighted exact-interval table is primary;
design-weighted point estimates, the effective sample size, and the interval-suppression reason are in the
clearly labeled supplement. No formal weighted confidence intervals are displayed.
**Table 3.** Unconditional gate distributions with provenance derived per displayed category and the two
nested denominator families (kept separate).
**Supplementary Table S2.** Gate-C month/year start-date boundary sensitivity (below).
**Supplementary Table S3.** Author-coded Gate-D outcome-element distributions and the historical
latest-registry reference-by-element-material cross-tab among 30 eligible Gate-A/B-pass cases. The
reference-based collapsed label drives nested attrition; elements are descriptive and do not replace or
reconcile the historical human reference.
**Supplementary Table S4A.** Terminal status counts, content failures, and determinate coverage by model
identifier and arm.
**Supplementary Table S4B.** Arm-2 responses among the 47 human-reference incorrectly matched
publications, by model identifier, in four mutually exclusive categories: valid material change,
valid no material change, valid but unassessable, and invalid (non-OK terminal status, assigned
first). The no-material-change count equals Arm-2 correct in this stratum; it does not establish
that the model recognized the identity error.

## Denominator families (report both; never merge the P4-positive and all-97 families)

- All 97 reference cases: 97 -> 45 -> 30 ->
  13 raw / 14 substantive -> 2.
- 83 P4-positive cases: 83 -> 32 -> 17 ->
  7 raw / 8 substantive -> 2.

## Month/year start-date boundary sensitivity

See Supplementary Table S2 (both denominator families).

## Provenance codes

- **REF2** — two-reviewer reference standard (agreement or gate-specific adjudication)
- **SINGLE** — single-reviewer evidence (unassessable under the two-reviewer rule)
- **SYS** — frozen index-pipeline system field
- **AUTH** — author-coded; selected fields independently recoded in the completed bounded audit
- **AUDIT** — Primary-RDA targeted review correction/query of an author code (not independent human coding)
- **MIXED(...)** — more than one provenance within the category (component codes listed)
- **NAPP** — not applicable
- **DESIGN** — fixed by the sampling design
- **REV** — author-approved post-audit revision of an author-coded field, or a status derived from one (not independent coding)

## Abbreviations and terms

- **P4:** stage-4 screening flag (`potential_discrepancy`). **P5:** any non-`CONSISTENT` stage-5
  classification. Both are pipeline flag rates, not outcome-switching prevalence.
- **Gate A** publication identity; **Gate B** outcome availability/extraction; **Gate C** registry timing
  and content (raw textual vs substantive definitions); **Gate D** outcome equivalence on a modified
  SPIRIT-Outcomes/CONSORT-Outcomes scaffold; **Gate E** evaluator-rubric alignment.
- **Arm 1 / Arm 2:** paired evaluator conditions with / without an explicit publication-identity step.
- **CI** confidence interval; **NPV** negative predictive value; **F1** harmonic mean of precision and
  recall; **kappa** Cohen kappa; **ESS** effective sample size; **pp** percentage points.

## Cohort definition (Methods source note)

Source cohort: studies returned by a ClinicalTrials.gov condition search for "cancer", restricted to overall status Completed, a registered phase including Phase 3, and a study completion date from 2018-01-01 to 2023-12-31. Eligibility was search-defined: records were not individually screened for oncology, and design (for example randomization) was not a selection criterion. Shorter label used in tables: ClinicalTrials.gov condition search for cancer; completed; registered phase including Phase 3; study completion date 2018-01-01 to 2023-12-31.

## Supplementary Table S5

S5A independent second-coder agreement; S5B Gate-D element agreement, assessability and frozen-versus-revised panel distributions; S5C independent-audit coverage of cascade-critical Gate-B decisions; S5D frozen baseline versus author-approved post-audit families. A compact narrative is in `AUDIT_SUPPLEMENT.md`.

## Audit status

The bounded independent second-coder audit of Gate B, the Gate-C substantive/wording interpretation and the Gate-D elements is complete; agreement is reported against the original author codes (Supplementary Table S5). Four author-coded cells received author-approved post-audit revisions after source review of the audit disagreements (REV provenance). Original author codes, the independent responses and the two-reviewer reference labels are retained unchanged; the revisions are not independent coding or adjudication.

## Package family

Analysis family `author_approved_post_audit`, version 1.0.0: the frozen author-coded cascade with four author-approved post-audit revisions (REV). The frozen baseline is retained for comparison in Supplementary Table S5D. Identifiers and hashes are in `INPUTS_MANIFEST.json`.

Presentation revision `presentation-r2` (values unchanged; no new coding or approval): Supplementary Table S4B added, the status/coverage table relabelled S4A, and the G5 explanatory captions taken from the versioned G5 presentation revision (`data/validation/g5/g5_release_presentation_r2/CAPTIONS.md`), which supersedes the historical G5 caption wording.

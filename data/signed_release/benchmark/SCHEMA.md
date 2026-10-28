# Benchmark data dictionary (source-text-free)

## cascade_labels.csv — one row per reference case (97)
Identifiers: `nct_id`, `pmid`. All other columns are DERIVED CODES with a `*_provenance` tag whose values
are drawn from: `author_approved_post_audit`, `author_coding`, `author_coding+colleague_audit_query`, `colleague_audit_reversal`, `derived_from_author_coding(colleague rule)`, `derived_from_post_audit_revision`, `not_applicable`, `reference_adjudication`, `reference_agreement`, `single_reviewer_evidence`, `system_field`, `system_field(=raw gate_c)`. `author_approved_post_audit` marks an author-approved post-audit revision of an author-coded field and `derived_from_post_audit_revision` a status derived from one; neither is independent coding or adjudication. The approved family adds `gate_c_effective_provenance`, `gate_d_target_substantive_provenance` and `gate_d_latest_elements_provenance`. Key distinction: **`gate_a` here is the adjudicated HUMAN reference** publication-identity
label — it is NOT a model output. Gates: `gate_a` {PASS,FAIL,UNASSESSABLE}; `gate_b`
{PASS,FAIL,NO_PRIMARY_IN_ABSTRACT}; `gate_c` {CONCORDANT_WITH_PROSPECTIVE, DIFFERS_FROM_PROSPECTIVE,
NO_PROSPECTIVE_VERSION, UNASSESSABLE}; `gate_c_substantive` {NOT_APPLICABLE, SUBSTANTIVE_CHANGE, UNCLEAR, WORDING_ONLY};
`gate_c_effective` {CONCORDANT_WITH_PROSPECTIVE, DIFFERS_FROM_PROSPECTIVE, NO_PROSPECTIVE_VERSION, SUBSTANTIVELY_CONCORDANT_WITH_PROSPECTIVE, UNASSESSABLE} folds WORDING_ONLY into concordant and maps UNCLEAR to UNASSESSABLE (no Gate-C credit); `gate_d_latest_reference` / `gate_d_target`(_substantive)
{MATERIAL_CHANGE, NO_MATERIAL_CHANGE, UNASSESSABLE, NOT_EVALUATED_UPSTREAM_FAILURE, UNASSESSABLE_UNDER_REFERENCE};
`gate_d_latest_*` element codes {SAME, COMPATIBLE, DIFFERENT, UNASSESSABLE, NOT_APPLICABLE}. `system_P4`
(Stage-4 flag), `system_P5` (Stage-5 classification != CONSISTENT), `reference_final_label`
{GENUINE_DISCREPANCY, NO_DISCREPANCY}. No free text.

## gate_c_registry_timing_codes.csv — registry timing facts (no outcome text)
`nct_id`, start dates + granularity, prospective/latest version number+date, `gate_c_code`, `n_versions`,
`changed_after_start`, `needs_human_review`, `retrieval_source`. The prospective/latest primary-outcome
TEXT objects are intentionally omitted from the public export.

## g5_*.csv — aggregate ablation tables (from the audited g5_release/)
`g5_primary_effects.csv` (per-model Arm-1/Arm-2 correctness + paired diff + frozen CI),
`g5_mechanism_by_human_gate_a.csv` (stratified by the HUMAN reference Gate-A — distinct from any model
`arm1_model_gate_a`), `g5_gate_a_and_conditional_d.csv`, `g5_status_coverage.csv`. Aggregates only.

## g5_wrong_paper_arm2_responses.csv — Arm-2 responses in the human wrong-paper stratum (S4B)
One row per `model`; `human_reference_gate_a` = WRONG_PAPER (the HUMAN reference stratum, never a model
call), `arm` = 2, `n_cases` = 47. The four mutually exclusive response columns sum to `n_cases`:
`valid_material_change`, `valid_no_material_change` and `valid_unassessable` (terminal status OK with Gate D
MATERIAL_CHANGE / NO_MATERIAL_CHANGE / UNASSESSABLE; derived GENUINE_DISCREPANCY / NO_DISCREPANCY /
AMBIGUOUS), and `invalid` (any non-OK terminal status, assigned first regardless of a partially parsed
Gate D and never promoted to a label). `invalid_schema_fail`, `invalid_semantic_fail` and
`invalid_transport_fail` split `invalid`. Reproducible from `g5_cells_source_text_free.csv` (rows with
`arm` = 2 and `human_reference_gate_a` = WRONG_PAPER); `valid_no_material_change` equals Arm-2 `correct`
in this stratum. A correct classification does not establish that the model recognized the identity
error. G5 presentation revision r2; values unchanged.

## g5_cells_source_text_free.csv — 582 categorical model-arm-case cells
One row per stable `case_id` × `model_identifier` × `arm`, with terminal status, parsed categorical Gate-A/Gate-D
outputs needed for scoring, `derived_disposition`, human reference publication-match stratum/label, and `correct`.
It is sufficient to reproduce case-level arm contrasts and case-bootstrap intervals. Rationales, rendered prompts,
source text, provider request/response identifiers and headers, usage records, and credentials are excluded.

## sampling_weights_observed.csv — 97 sampled-case probabilities and weights
`nct_id` and `pmid` identify each observed reference case. `inclusion_probability_mc` and
`inverse_probability_weight_mc` are the primary reconstructed pseudo-randomization quantities;
`*_independent_approx` fields are the audit approximation. These reproduce supplementary weighted point estimates
when joined to `cascade_labels.csv`. The reconstruction was not prospectively specified, formal weighted intervals
are suppressed after an unstable pairwise-variance diagnostic, and the weights cannot support prevalence estimation.

All 97 cases were inspected and used. This is not an untouched external test set; tuning on these cases creates
model leakage and precludes an external-validation claim.

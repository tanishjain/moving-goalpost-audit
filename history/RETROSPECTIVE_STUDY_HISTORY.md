# Retrospective study-history and analysis record

**Record type:** retrospective study history, prepared after the principal analyses. **It is not a prospective
registration or preregistration.**

**Prepared:** 26 October 2026, as the public copy for the code-and-data snapshot. **Deposit date:** 2026-10-27
(version 1.0.0, DOI 10.5281/zenodo.23693399). Earlier internal versions were dated 19 August and 4 October 2026; this copy
does not alter the recorded August chronology.

## Status and purpose

This record was created after the principal analyses. It cannot remove hindsight or establish that every decision was
made before results were known. Its purpose is to archive the study chronology, estimands, dated specifications,
deviations, provenance boundaries and known-result state at manuscript preparation.

## Title

Publication identity and abstract availability constrained an automated registry-to-publication outcome audit

## Research question

When an automated system attempts to audit outcome reporting from trial registration through publication, where do
invalid comparisons arise, and how does explicitly assessing publication identity before outcome comparison affect the
disposition of incorrectly matched publications?

## Design

This project combines:

1. a retrospective diagnostic evaluation of an unchanged registry-to-publication pipeline in a deliberately enriched
   97-case human-reference sample;
2. an explanatory, provenance-tagged cascade across publication identity, abstract outcome availability/extraction,
   registry timing/content, and outcome equivalence; and
3. a paired computational task-specification experiment in which the same cases and outcome-comparison rubric were
   evaluated with versus without a preceding publication-identity assessment.

The study does not estimate the population prevalence of undisclosed outcome changes, selective reporting or bias. A
candidate discrepancy is not interpreted as evidence of nondisclosure or selective reporting.

## Estimands

Three estimands are kept separate:

1. **Latest-registry reference performance:** classification performance of the frozen stage-4 and stage-5 screens
   against the original two-reviewer label comparing the pipeline-selected publication with the latest registry record
   supplied to reviewers.
2. **Prospective-target cascade:** observed attrition toward a material difference between the last registry version
   available before enrolment and the primary outcome in the primary-results publication, under available
   abstract-centered evidence. This terminal cascade classification is not an independently labeled
   prospective-registry reference and is not a prevalence estimate.
3. **Paired task-specification effect:** within-model difference in case-level correctness between an arm that
   assesses publication identity before endpoint comparison and an arm that performs endpoint comparison without that
   identity step, in the enriched 97-case set.

## Source cohort and reference sample

The source cohort came from a ClinicalTrials.gov condition search for “cancer,” restricted to completed studies,
registered phase including phase 3, and study completion dates in 2018–2023. Its 1,243 distinct trials included 148
combined phase 2/3 registrations and contained 1,974 registered primary-endpoint records. The pipeline selected
publications for 1,103 trials; 1,099 had abstracts and 1,001 yielded usable extracted endpoints and were
compared/classified. Eligibility was search-defined, without individual confirmation that all trials were oncology
trials or randomized. The 97-case evaluation sample was selected through nine overlapping, output-stratified draws using
a fixed seed. It intentionally enriched pipeline-positive and diagnostically informative cases and is unsuitable for
unqualified population inference.

Two reviewers independently assessed publication identity and latest-registry-to-publication outcome equivalence for
all 97 cases. One original reviewer resolved disagreements after reviewing both assessments; there was no independent
third adjudicator. Later Gate-B, Gate-C substantive/wording and structured Gate-D element fields were coded by one
author under a frozen codebook. A bounded second-coder audit is complete for 20 B, 15 C and 15 D cases: an original
reviewer recoded these selected subsets while blinded to the author codes. This is not external validation or a new
reference standard. Original codings remain locked and separate from subsequent author-approved revisions.

## Chronology and decision state

### Before the retrospective record

- The automated pipeline and its outputs existed before the diagnostic error-cascade analysis.
- The original two-reviewer reference exercise produced a latest-registry/selected-publication label; it did not
  directly label the stricter prospective-registry target.
- The Gate-C date rule and the Gate-D/cascade codebook were fixed before final gate-specific coding and worksheet
  merging on 17 August 2026.
- On 17 August 2026, five Gate-C substantive/wording codes and four Gate-D element codes were corrected. The
  corrections were proposed in an AI-assisted internal review and source-reviewed and approved by the coding author;
  they were not a human methods reviewer's adjudication. The coding author reconfirmed personal review and approval of
  these nine corrections on 7 October 2026. Pre-correction values were retained.
- The paired experiment's two arms, prompts, schemas, input identity, model aliases, decoding/provider settings, retry
  and failure rules, case order, reference mapping and analysis were frozen in commit
  `1c83724487c2c957781f4a166343ac98594ec528` and annotated tag `g5-ablation-freeze-2026-08-18-v1` (private working
  repository) before the reference evaluation.
- A separate authorization bound one run ID, `g5-reference-20260818-v1`, to that frozen identity. The 97 cases × 2 arms
  × 3 model aliases produced 582 terminal evaluations. No result cell was selectively repaired or rerun.
- Manuscript drafting, claim refinement, public-release derivation and this retrospective record occurred after the
  principal results were available.

### Internally frozen before specific downstream steps

- Gate definitions and the provenance hierarchy, before final gate-specific coding.
- The Gate-C first-of-period date rule and the permissive month/year boundary sensitivity.
- The paired experiment's exact arms and common rubric.
- The 97-case input identity and the frozen human-reference mapping.
- The all-case correctness endpoint, the invalid/indeterminate-as-incorrect rule, human-reference Gate-A
  stratification, the fixed-seed case bootstrap, coverage/failure reporting and the panel hierarchy.
- The deterministic retry rule, immutable attempt journal, content-failure handling and prohibition on selective
  repair.

### Audit completion and author-approved revisions (4 October 2026)

- The B return comprises 19 workbook responses and one separately preserved response that the coding author quoted
  from the reviewer's email; the original message headers and send time were not independently retrieved.
  Combined-source completeness is 20/20. C and D are complete at 15/15 each.
- Original independent agreement is B 18/20, C 12/15 and D collapsed 13/15. Per-element D agreement is reported
  separately; the collapsed result does not establish high element-level reproducibility.
- Source review of audit disagreements led to four author-approved revisions: three C interpretations changed from
  wording-only to unclear and one D timepoint from unassessable to same. The original proposal, the author's approval,
  both independent codings and the derived revisions remain distinct. Source-review and analytical assistance are
  described in the manuscript Methods; author approval is not a new independent rating or clinical adjudication.
- The approved all-case nested cascade is 45 → 30 → 13 raw / 14 substantive → 2. The P4-positive chain remains 32 → 17 →
  7 / 8 → 2. Historical substantive eligibility of 16 is preserved only in the frozen-baseline family. No original
  reference label, B code or collapsed D-material flag was changed.
- The terminal count depends on author-coded B availability. Four other identity-passing, reference-positive cases are
  excluded at B; only one of those four and one of the terminal two had independent B audits. Original-coding
  substitution scenarios remain separate from the approved primary family.
- The trial-versus-endpoint and abstract-versus-extraction flow labels were corrected from the saved source records.
  No trial was removed, no source was refreshed, and no screen or model result was rerun.

### Presentation revision and author declarations (October 2026)

- 4–6 October 2026: a presentation-only revision added the wrong-paper Arm-2 response composition (Supplementary
  Table S4B) and corrected explanatory captions. No case label, estimate or evaluation changed.
- 22–23 October 2026: the second author completed review of the shared submission package without requesting
  scientific changes.
- 26 October 2026: author declarations recorded for the manuscript. Authors: Tanish Jain (ORCID 0000-0002-0571-4948;
  no institutional affiliation for this work) and Alessandra Casamento (ORCID 0000-0001-6156-9020; Independent
  Researcher, London, UK). No external funding or institutional support. No competing interests. The study used public
  trial and bibliographic records without individual participant data; no formal ethics-review determination was
  obtained. OpenAI Codex and Anthropic Claude assisted with code development and review, literature and source review,
  analytical interpretation, and manuscript drafting and editing, as described in the manuscript; the authors take
  responsibility for the content. Final approval of the submitted version by both authors is recorded separately and
  is not implied by this record.

### Material development history before the frozen reference run

- The 97 cases had already been inspected and used in the human-reference exercise and historical multi-model work.
  They were not and are not described as an untouched external test set.
- Small pilot calls were made on cases outside the 97 before the reference run to test execution and schema handling.
  Pilot outputs were excluded from the reference analysis and are not distributed.
- Development briefly used an inconsistent three-arm design and incorrectly sourced historical Arm-0 material. That
  design was abandoned and replaced before the frozen reference run. The final two-arm contract was reviewed and
  internally frozen before evaluation; no abandoned-arm or pilot result cell entered the 582-cell reference run or a
  reported contrast.

### What was not prospectively registered or was explanatory/post hoc

- The overall study and full manuscript analysis plan were not publicly prospectively registered.
- The choice to frame the work as an error-cascade methods paper followed review of the original pipeline's
  validation results.
- The cascade is an explanatory decomposition of a completed pipeline evaluation.
- The prospective-target terminal count is derived from combined provenance sources rather than a new independent
  expert reference standard.
- The structured five-element author rubric differs from the historical reviewers' instructions; its divergence from
  the historical label is reported rather than harmonized after the fact.
- A conservative missing-output check for one model alias was post hoc and is treated only as robustness context, not a
  replacement estimand.

## Analysis boundaries

- Report the 7 of 97 cases only as latest-registry reference-positive cases in an enriched reference sample.
- Report the terminal cascade count of 2 only as cascade-terminal material discrepancies under the available
  abstract-centered evidence.
- Do not estimate population prevalence.
- Keep wrong-publication, no-primary-outcome-in-abstract, extraction failure, no prospective registry version,
  wording-only registry differences, substantive registry changes and endpoint nonequivalence distinct.
- Treat wording-only registry differences as concordant for the substantive timing gate, give unclear differences no
  credit, and report the raw textual criterion separately.
- Describe the paired experiment as performance of GitHub-Copilot-accessed mutable aliases on 18 August 2026, not
  immutable native-provider models.
- Count all schema, semantic, refusal, timeout and transport failures according to the frozen rules; do not selectively
  rerun or repair them.

## Immutable experiment identifiers

- Run ID: `g5-reference-20260818-v1`
- Freeze commit (private working repository): `1c83724487c2c957781f4a166343ac98594ec528`
- Annotated freeze tag (private working repository): `g5-ablation-freeze-2026-08-18-v1`
- Freeze digest (SHA-256): `2aac76b974a1b3178728e4b4528496bc7f59a0c35365c555d790397b807dcb8a`
- Attempt journal (SHA-256; not distributed because it contains case-rendered material): `f832e1272d038798682e4369f625d81127a2e87c90ca457c92d4d95cd6dcf9b1`
- Frozen reference (SHA-256): `c393416f2f9cfa6e5d0f162be45de38a682ffe93319cfc3e8fd1db8cf93349b2`
- Frozen analysis (SHA-256): `148103015f2cc6ad3b59460654d33143fc0e4b36cf6843ef80dd09e46c69f2e7`
- Approved analysis family: `author_approved_post_audit` v1.0.0; signed scientific run `2f7a8fcfb09e392a`; active
  presentation run `ff8e426d9e7267cc`.

## Deviations and unresolved items

1. The original human reference used the latest registry text supplied to reviewers, not the last prospectively
   available registry version. The cascade names this as a timing/content validity condition rather than silently
   treating the reference as the stricter target.
2. The 97-case sample is enriched and overlapping; standard exact intervals are descriptive. Design-weighted point
   estimates are supplementary, and unstable weighted intervals are suppressed. No prevalence is estimated.
3. Later cascade fields are author-coded, with independent recoding of selected subsets and four separate
   author-approved post-audit revisions. Audit coverage is incomplete outside those subsets, and element-level
   agreement is substantially lower than collapsed D agreement.
4. One model alias produced substantial schema/semantic failures. Those failures remain in the primary denominator as
   specified and are not repaired.
5. The public release excludes copyrighted source text, rendered prompts/responses containing that text, private
   reviewer materials, provider request identifiers and credentials.

## Data and materials

This record accompanies the source-text-free code-and-data snapshot described in `README.md`. That snapshot permits
independent reproduction of the reported categorical analyses listed in `docs/REPRODUCTION_COVERAGE.md`, without
redistributing publication abstracts, registry source text, rendered prompts, raw model responses, private reviewer
worksheets or provider metadata. Archive DOI: https://doi.org/10.5281/zenodo.23693399; repository:
https://github.com/tanishjain/moving-goalpost-audit.

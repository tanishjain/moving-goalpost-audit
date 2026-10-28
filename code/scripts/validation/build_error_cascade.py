#!/usr/bin/env python3
"""G3 / W2 — Error-cascade assembly under the FROZEN codebook (COORD_G3_codebook.md).

Assembles `data/validation/error_cascade.csv`: one row per reference case, with each
validity gate (A/B/C/D) attributed to existing evidence and a REQUIRED `*_provenance`
tag so reference adjudication and author coding stay distinguishable forever
(codebook governing principle).

What this script codes MECHANICALLY / from the REFERENCE standard (no new judgment):
  - Gate A (publication identity): from `wrong_paper_match_a/b` + gate-specific adjudicator
    notes. 80 concordant -> reference_agreement; 12 contested resolved by an adjudicator
    note that explicitly addresses paper identity -> reference_adjudication; 5 contested with
    no gate-specific adjudication -> UNASSESSABLE + needs_human_review (NOT author-coded here).
  - Gate C: joined verbatim from W1 (`gate_c_registry_timing.csv`) -> system_field.
  - gate_d_latest_reference: from `endpoint_judgment_a/b` + adjudicator, ONLY where Gate A PASS.
  - gate_d_target: inherits gate_d_latest_reference iff Gate C == CONCORDANT_WITH_PROSPECTIVE,
    else UNASSESSABLE_UNDER_REFERENCE (per the RDA-confirmed source-boundary rule).
  - system_P4 / system_P5 / reference_final_label (gold): mechanical / reference.

What this script does NOT code (author-coding = Tanish/RDA per codebook, blinded + audited):
  - Gate B (all 97), Gate D element-level codes (Gate-A-PASS cases), and the 34 Gate-C
    DIFFERS substantive-vs-wording split. These are emitted as BLINDED WORKSHEETS for a human
    to fill; in the cascade they are `PENDING_AUTHOR_CODING`, provenance `author_coding`,
    needs_human_review=TRUE. An LLM must not generate these — the paper's own thesis is that
    LLM judgments cannot stand in for expert reference labels.

Run:
    uv run python scripts/validation/build_error_cascade.py           # assemble + worksheets
    uv run python scripts/validation/build_error_cascade.py --merge   # fold filled worksheets back in

Outputs (data/validation/):
    error_cascade.csv, error_cascade_audit.csv,
    worksheets/gate_b_worksheet.csv, worksheets/gate_d_elements_worksheet.csv,
    worksheets/gate_c_substantive_worksheet.csv, worksheets/BLIND_KEY.csv,
    error_cascade_unconditional_counts.json
"""
from __future__ import annotations

import argparse
import io
import json
from datetime import date

import numpy as np
import pandas as pd

from moving_goalpost.config import VALIDATION_DIR, PROCESSED_DIR
from compute_system_vs_human_gold import _gold  # reuse frozen gold construction

ADJ = VALIDATION_DIR / "manual_validation_adjudication.csv"
GATE_C = VALIDATION_DIR / "gate_c_registry_timing.csv"
STAGE5 = PROCESSED_DIR / "stage5_final_results.csv"
WS_DIR = VALIDATION_DIR / "worksheets"
OUT = VALIDATION_DIR / "error_cascade.csv"
OUT_AUDIT = VALIDATION_DIR / "error_cascade_audit.csv"
OUT_COUNTS = VALIDATION_DIR / "error_cascade_unconditional_counts.json"

CODER = "auto-assembly (claude-coding-agent); reference/mechanical gates only"
TODAY = date.today().isoformat()
PENDING = "PENDING_AUTHOR_CODING"


def _s(v) -> str:
    return str(v).strip().upper()


def read_gate_c() -> pd.DataFrame:
    lines = [ln for ln in open(GATE_C) if not ln.startswith("#")]
    return pd.read_csv(io.StringIO("".join(lines)))


# ---------------------------------------------------------------------------
# Gate A
# ---------------------------------------------------------------------------


def code_gate_a(row) -> tuple[str, str, bool, str]:
    """Returns (gate_a, provenance, needs_review, note)."""
    a, b = _s(row["wrong_paper_match_a"]), _s(row["wrong_paper_match_b"])
    if a == "FALSE" and b == "FALSE":
        return "PASS", "reference_agreement", False, "both reviewers: correct paper"
    if a == "TRUE" and b == "TRUE":
        return "FAIL", "reference_agreement", False, "both reviewers: wrong/secondary paper"
    # contested
    adj_label = _s(row.get("adjudicator_label"))
    note = str(row.get("adjudicator_notes") or "")
    nlow = note.lower()
    if adj_label in {"NO_DISCREPANCY", "GENUINE_DISCREPANCY"} and (
        "match-error rule" in nlow or "randomized trial report" in nlow
        or "primary results" in nlow or "primary analysis" in nlow
    ):
        if "match-error rule" in nlow:
            return "FAIL", "reference_adjudication", False, f"adjudicator (identity): {note[:120]}"
        return "PASS", "reference_adjudication", False, f"adjudicator (identity): {note[:120]}"
    # reviewer disagreement, no gate-specific adjudication of identity
    return ("UNASSESSABLE", "single_reviewer_evidence", True,
            f"reviewers disagree on paper identity (a={a},b={b}); no gate-specific adjudication")


# ---------------------------------------------------------------------------
# Gate D (latest-record reference), only where Gate A PASS
# ---------------------------------------------------------------------------

_EP = {"GENUINE_DISCREPANCY": "MATERIAL_CHANGE", "NO_DISCREPANCY": "NO_MATERIAL_CHANGE",
       "GENUINELY_AMBIGUOUS": "UNASSESSABLE"}


def code_gate_d_latest(row, gate_a: str) -> tuple[str, str, bool, str]:
    if gate_a == "FAIL":
        return "NOT_EVALUATED_UPSTREAM_FAILURE", "system_field", False, "Gate A FAIL"
    if gate_a == "UNASSESSABLE":
        return "UNASSESSABLE", "single_reviewer_evidence", True, "Gate A unresolved"
    ea, eb = _s(row["endpoint_judgment_a"]), _s(row["endpoint_judgment_b"])
    da, db = _EP.get(ea), _EP.get(eb)
    if da and da == db:
        return da, "reference_agreement", False, f"both reviewers endpoint: {ea}"
    # disagreement -> adjudicator if present
    adj = _s(row.get("adjudicator_label"))
    if adj == "GENUINE_DISCREPANCY":
        return "MATERIAL_CHANGE", "reference_adjudication", False, "adjudicated GENUINE"
    if adj == "NO_DISCREPANCY":
        return "NO_MATERIAL_CHANGE", "reference_adjudication", False, "adjudicated NO"
    return ("UNASSESSABLE", "single_reviewer_evidence", True,
            f"endpoint judgments differ (a={ea},b={eb}); no adjudication")


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def assemble() -> pd.DataFrame:
    adj = pd.read_csv(ADJ)
    adj["gold_label"] = adj.apply(_gold, axis=1)
    gc = read_gate_c().set_index("nct_id")
    s5 = pd.read_csv(STAGE5)[["nct_id", "pmid", "potential_discrepancy", "classification",
                              "match_method"]].drop_duplicates(["nct_id", "pmid"])
    adj = adj.merge(s5, on=["nct_id", "pmid"], how="left", validate="one_to_one")

    rows, audit = [], []
    for r in adj.itertuples(index=False):
        rd = r._asdict()
        ga, ga_prov, ga_flag, ga_note = code_gate_a(rd)
        gcc = gc.loc[rd["nct_id"], "gate_c_code"] if rd["nct_id"] in gc.index else "UNASSESSABLE"
        gc_flag = bool(gc.loc[rd["nct_id"], "needs_human_review"]) if rd["nct_id"] in gc.index else True
        gdl, gdl_prov, gdl_flag, gdl_note = code_gate_d_latest(rd, ga)
        gdt = gdl if gcc == "CONCORDANT_WITH_PROSPECTIVE" else "UNASSESSABLE_UNDER_REFERENCE"
        gdt_prov = gdl_prov if gcc == "CONCORDANT_WITH_PROSPECTIVE" else "system_field"

        p4 = _s(rd.get("potential_discrepancy")) == "TRUE"
        p5 = _s(rd.get("classification")) != "CONSISTENT"
        needs = ga_flag or gdl_flag or True  # Gate B/elements always pending -> row needs human

        rows.append({
            "nct_id": rd["nct_id"], "pmid": rd["pmid"],
            "gate_a": ga, "gate_a_provenance": ga_prov,
            "gate_b": PENDING, "gate_b_provenance": "author_coding",
            "gate_c": gcc, "gate_c_provenance": "system_field",
            "gate_d_latest_reference": gdl, "gate_d_latest_reference_provenance": gdl_prov,
            "gate_d_target": gdt, "gate_d_target_provenance": gdt_prov,
            "gate_d_latest_domain": PENDING, "gate_d_latest_measurement": PENDING,
            "gate_d_latest_metric": PENDING, "gate_d_latest_aggregation": PENDING,
            "gate_d_latest_timepoint": PENDING, "gate_d_latest_priority": PENDING,
            "gate_d_latest_addition_omission": PENDING, "gate_d_latest_multiplicity_mapping": PENDING,
            "system_P4": p4, "system_P5": p5,
            "reference_final_label": rd["gold_label"],
            "needs_human_review": needs, "coder_id": CODER, "coding_date": TODAY,
        })
        audit.append({
            "nct_id": rd["nct_id"], "pmid": rd["pmid"],
            "gate_a_note": ga_note, "gate_c_needs_review": gc_flag,
            "gate_d_latest_note": gdl_note,
            "wrong_paper_match_a": rd["wrong_paper_match_a"], "wrong_paper_match_b": rd["wrong_paper_match_b"],
            "endpoint_judgment_a": rd["endpoint_judgment_a"], "endpoint_judgment_b": rd["endpoint_judgment_b"],
            "adjudicator_label": rd.get("adjudicator_label"),
            "reviewer_a_notes": rd.get("reviewer_a_notes"), "reviewer_b_notes": rd.get("reviewer_b_notes"),
        })
    return pd.DataFrame(rows), pd.DataFrame(audit), adj


# ---------------------------------------------------------------------------
# Blinded worksheets (human author-coding inputs; NO system/reference columns)
# ---------------------------------------------------------------------------

WS_INSTR = {
    "gate_b": (
        "# GATE B WORKSHEET — endpoint EXTRACTION correctness (author-coding, BLINDED).\n"
        "# For each row decide, using ONLY the abstract, whether `system_published_endpoint`\n"
        "# faithfully reflects the publication's stated PRIMARY endpoint.\n"
        "# gate_b in {PASS, FAIL, NO_PRIMARY_IN_ABSTRACT}. Do NOT look up P4/P5/model/gold.\n"
        "# Rows are in shuffled (blind) order; join back via blind_id in BLIND_KEY.csv.\n"),
    "gate_d": (
        "# GATE D ELEMENTS WORKSHEET — latest-registry-vs-publication (author-coding, BLINDED).\n"
        "# Code each SPIRIT/CONSORT element in {SAME, COMPATIBLE, DIFFERENT, UNASSESSABLE, NOT_APPLICABLE}:\n"
        "#   domain, measurement, metric, aggregation, timepoint; plus priority, addition_omission,\n"
        "#   multiplicity_mapping. Pure wording/synonym with all SAME/COMPATIBLE = not a change.\n"
        "# Clinically related != equivalent (e.g. TTP vs PFS -> DIFFERENT). Blinded to P4/P5/gold.\n"
        "# Only Gate-A-PASS cases here; drop any whose Gate B = FAIL/NO_PRIMARY_IN_ABSTRACT afterwards.\n"),
    "gate_c": (
        "# GATE C SUBSTANTIVE-vs-WORDING WORKSHEET (author-coding). For each DIFFERS_FROM_PROSPECTIVE\n"
        "# case, judge whether the registry primary-outcome change from the prospective version to the\n"
        "# latest is SUBSTANTIVE_CHANGE, WORDING_ONLY, or UNCLEAR. Registry-only; ignore the publication.\n"),
}


def _write_ws(df: pd.DataFrame, path, instr: str):
    WS_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(instr)
        df.to_csv(fh, index=False)


def emit_worksheets(cascade: pd.DataFrame, adj: pd.DataFrame):
    # blind ids (shuffled, fixed seed) so order doesn't leak information
    rng = np.random.RandomState(20260817)
    blind = adj[["nct_id", "pmid"]].copy()
    blind["blind_id"] = ["B%03d" % i for i in range(len(blind))]
    order = rng.permutation(len(blind))
    key = blind.iloc[order].reset_index(drop=True)
    key.to_csv(WS_DIR / "BLIND_KEY.csv", index=False) if WS_DIR.exists() else None
    WS_DIR.mkdir(parents=True, exist_ok=True)
    key.to_csv(WS_DIR / "BLIND_KEY.csv", index=False)

    a = adj.merge(blind[["nct_id", "pmid", "blind_id"]], on=["nct_id", "pmid"])

    # Gate B: all 97, blinded (only abstract + system extraction)
    gb = a.loc[order, ["blind_id", "published_endpoint", "abstract"]].rename(
        columns={"published_endpoint": "system_published_endpoint"})
    gb["gate_b"] = ""; gb["gate_b_notes"] = ""
    _write_ws(gb, WS_DIR / "gate_b_worksheet.csv", WS_INSTR["gate_b"])

    # Gate D elements: Gate-A-PASS cases only
    pass_ncts = set(cascade.loc[cascade["gate_a"] == "PASS", "nct_id"])
    ad = a[a["nct_id"].isin(pass_ncts)]
    ad_order = rng.permutation(len(ad))
    gd = ad.iloc[ad_order][["blind_id", "registered_endpoint_measures",
                            "registered_endpoint_descriptions", "published_endpoint", "abstract"]].copy()
    for col in ["domain", "measurement", "metric", "aggregation", "timepoint",
                "priority", "addition_omission", "multiplicity_mapping", "notes"]:
        gd[col] = ""
    _write_ws(gd, WS_DIR / "gate_d_elements_worksheet.csv", WS_INSTR["gate_d"])

    # Gate C substantive: the DIFFERS cases, from W1
    gc = read_gate_c()
    diff = gc[gc["gate_c_code"] == "DIFFERS_FROM_PROSPECTIVE"][
        ["nct_id", "prospective_primary_outcome", "current_latest_primary_outcome"]].copy()
    diff["substantive_vs_wording"] = ""; diff["notes"] = ""
    _write_ws(diff, WS_DIR / "gate_c_substantive_worksheet.csv", WS_INSTR["gate_c"])
    return len(gb), len(gd), len(diff)


def unconditional_counts(cascade: pd.DataFrame) -> dict:
    def vc(col):
        return cascade[col].value_counts(dropna=False).to_dict()
    passed_a = cascade["gate_a"] == "PASS"
    conc_c = cascade["gate_c"] == "CONCORDANT_WITH_PROSPECTIVE"
    return {
        "n": int(len(cascade)),
        "gate_a": vc("gate_a"),
        "gate_c": vc("gate_c"),
        "gate_d_latest_reference": vc("gate_d_latest_reference"),
        "gate_d_target": vc("gate_d_target"),
        "reference_final_label": vc("reference_final_label"),
        "sequential_partial": {
            "gate_a_pass": int(passed_a.sum()),
            "gate_a_pass_and_gate_c_concordant": int((passed_a & conc_c).sum()),
            "gate_a_pass_and_c_concordant_and_target_material":
                int((passed_a & conc_c & (cascade["gate_d_target"] == "MATERIAL_CHANGE")).sum()),
            "note": "Gate B (extraction) is pending author-coding, so this sequence omits B; "
                    "full A->B->C->D attrition is completed after worksheets return.",
        },
        "system_positives": {"P4": int(cascade["system_P4"].sum()), "P5": int(cascade["system_P5"].sum())},
    }


# ---------------------------------------------------------------------------
# Merge — fold filled author-coding worksheets back into the cascade
# ---------------------------------------------------------------------------

OUT_PANELS = VALIDATION_DIR / "error_cascade_panels.json"
GATE_B_VALID = {"PASS", "FAIL", "NO_PRIMARY_IN_ABSTRACT"}
ELEMENT_COLS = ["domain", "measurement", "metric", "aggregation", "timepoint",
                "priority", "addition_omission", "multiplicity_mapping"]
ELEMENT_VALID = {"SAME", "COMPATIBLE", "DIFFERENT", "UNASSESSABLE", "NOT_APPLICABLE", ""}
SUBST_VALID = {"SUBSTANTIVE_CHANGE", "WORDING_ONLY", "UNCLEAR"}

# --- Internal-review corrections of 2026-08-17 ("colleague audit" in the names below).
# [Public-snapshot erratum E1] These corrections came from an AI-assisted internal review and were
# source-reviewed and approved by the coding author (approval reconfirmed 2026-10-07); they are not
# a human methods reviewer's adjudication. Provenance is tagged distinctly from Tanish's original
# author-coding and the pre-correction values are kept in the audit file.

# Five Gate-C substantive/wording reversals (title-only worksheet corrected against the full
# cached prospective/latest outcome objects). Corrected split: 20 substantive / 14 wording.
GATE_C_SUBSTANTIVE_CORRECTIONS = {
    "NCT01712789": "SUBSTANTIVE_CHANGE",   # AE window changed (up-to-5yr -> TEAE first-dose..+28d)
    "NCT03581786": "SUBSTANTIVE_CHANGE",   # investigator-assessed PFS -> IRC-assessed (assessor change)
    "NCT05136898": "SUBSTANTIVE_CHANGE",   # all abnormal labs -> thresholded PCS labs; TEAE-caused disc.
    "NCT02213263": "WORDING_ONLY",         # wk26 + response criteria already prospective; title exposes them
    "NCT04852679": "WORDING_ONLY",         # wk24 already prospective time frame; latest moves it into label
}

# Three Gate-D element queries. (expected_original, corrected, reason, still_open_needs_human).
# Where the internal review left DIFFERENT-vs-UNASSESSABLE open, we apply the endorsed floor
# (not COMPATIBLE -> UNASSESSABLE) and flag the row for human confirmation.
GATE_D_QUERY_CORRECTIONS = {
    "NCT01076387": {"aggregation": ("COMPATIBLE", "UNASSESSABLE",
        "broad registered surgical complications vs 90-day grade 2-5; cutoff/aggregation not "
        "COMPATIBLE from registry text (floor UNASSESSABLE, may be DIFFERENT)", True)},
    "NCT02301156": {"addition_omission": ("DIFFERENT", "SAME",
        "CR-with-incomplete-marrow-recovery changes the ORR composite (aggregation stays DIFFERENT) "
        "but adds no separate outcome; addition_omission SAME under the codebook", False)},
    "NCT02772965": {
        "metric": ("COMPATIBLE", "UNASSESSABLE",
            "composite failure indicator vs time-to-failure HR: metric not COMPATIBLE "
            "(DIFFERENT or UNASSESSABLE; floor applied)", True),
        "aggregation": ("COMPATIBLE", "UNASSESSABLE",
            "composite failure indicator vs time-to-failure HR: aggregation not COMPATIBLE "
            "(DIFFERENT or UNASSESSABLE; floor applied)", True)},
}
CONCORDANT_EFFECTIVE = {"CONCORDANT_WITH_PROSPECTIVE", "SUBSTANTIVELY_CONCORDANT_WITH_PROSPECTIVE"}


def _read_ws(path) -> pd.DataFrame:
    """Read a worksheet, skipping ONLY the leading contiguous `#` comment block
    (abstracts contain multi-line quoted text, so we must not drop interior lines)."""
    lines = open(path, encoding="utf-8").readlines()
    i = 0
    while i < len(lines) and lines[i].lstrip().startswith("#"):
        i += 1
    return pd.read_csv(io.StringIO("".join(lines[i:])))


def merge() -> None:
    # Re-derive the mechanical/reference gates deterministically (no worksheet emission,
    # so the filled worksheets are never clobbered).
    cascade, audit, adj = assemble()
    key = pd.read_csv(WS_DIR / "BLIND_KEY.csv")  # nct_id, pmid, blind_id

    # ---- Gate B (all 97) — author-coding; strict rule: never infer PASS ----
    gb = _read_ws(WS_DIR / "gate_b_worksheet.csv")
    gb["gate_b_code"] = gb["gate_b"].map(_s)
    bad = set(gb["gate_b_code"]) - GATE_B_VALID
    if bad:
        raise SystemExit(f"Gate B worksheet has invalid codes: {bad}")
    gb = gb.merge(key[["nct_id", "blind_id"]], on="blind_id", validate="one_to_one")
    cascade["gate_b"] = cascade["nct_id"].map(gb.set_index("nct_id")["gate_b_code"])
    cascade["gate_b_provenance"] = "author_coding"
    uncoded = cascade.loc[~cascade["gate_b"].isin(GATE_B_VALID), "nct_id"].tolist()
    if uncoded:  # strict Gate B rule: a blank is NOT an inferred PASS — it is an error
        raise SystemExit(f"Gate B not explicitly coded for {len(uncoded)} rows: {uncoded[:5]}")

    # ---- Gate D elements (Gate-A-PASS cases) — author-coding ----
    gd = _read_ws(WS_DIR / "gate_d_elements_worksheet.csv").merge(
        key[["nct_id", "blind_id"]], on="blind_id", validate="one_to_one")
    for c in ELEMENT_COLS:
        gd[c] = gd[c].map(_s)
        bad = set(gd[c]) - ELEMENT_VALID
        if bad:
            raise SystemExit(f"Gate D element '{c}' has invalid codes: {bad}")
    pass_ncts = set(cascade.loc[cascade["gate_a"] == "PASS", "nct_id"])
    if not set(gd["nct_id"]).issubset(pass_ncts):
        raise SystemExit("Gate D worksheet contains non-Gate-A-PASS cases; codebook violation.")
    gdi = gd.set_index("nct_id")
    for c in ELEMENT_COLS:
        col = "gate_d_latest_" + c
        cascade[col] = cascade["nct_id"].map(gdi[c])
        cascade.loc[cascade["gate_a"] != "PASS", col] = "NOT_EVALUATED_UPSTREAM"
        cascade[col] = cascade[col].fillna("NOT_EVALUATED_UPSTREAM")
    cascade["gate_d_latest_elements_provenance"] = np.where(
        cascade["gate_a"] == "PASS", "author_coding", "system_field")

    # Apply the three colleague-audit Gate-D element corrections (provenance-tagged; originals
    # retained in the audit file). Verify the pre-correction value first to guard against drift.
    corr_records = []
    gd_query_open = set()
    idx = cascade.set_index("nct_id")
    for nct, fields in GATE_D_QUERY_CORRECTIONS.items():
        for elem, (expect, new, reason, still_open) in fields.items():
            col = "gate_d_latest_" + elem
            cur = idx.at[nct, col]
            if cur != expect:
                raise SystemExit(f"Gate D correction drift: {nct}.{elem} is {cur!r}, "
                                 f"expected {expect!r}")
            cascade.loc[cascade["nct_id"] == nct, col] = new
            corr_records.append({"nct_id": nct, "gate": "D", "field": elem,
                                 "original": expect, "corrected": new,
                                 "provenance": "colleague_audit_query", "reason": reason,
                                 "still_open_needs_human": still_open})
            if still_open:
                gd_query_open.add(nct)
    cascade["gate_d_latest_elements_provenance"] = np.where(
        cascade["nct_id"].isin(GATE_D_QUERY_CORRECTIONS),
        "author_coding+colleague_audit_query", cascade["gate_d_latest_elements_provenance"])

    # Descriptive element-derived material-change flag (reported alongside the reference
    # collapsed value; does NOT drive the cascade). Material iff any assessable element,
    # priority, addition/omission, or multiplicity mapping is DIFFERENT. Only meaningful
    # for Gate-A-PASS & Gate-B-PASS cases.
    def _elem_material(r) -> str:
        if r["gate_a"] != "PASS" or r["gate_b"] != "PASS":
            return "NOT_ASSESSABLE"
        vals = [r["gate_d_latest_" + c] for c in ELEMENT_COLS]
        return "MATERIAL_CHANGE" if any(v == "DIFFERENT" for v in vals) else "NO_MATERIAL_CHANGE"
    cascade["gate_d_latest_elements_material"] = cascade.apply(_elem_material, axis=1)

    # ---- Gate C substantive-vs-wording split (rule b) + five colleague-audit reversals ----
    gcw = _read_ws(WS_DIR / "gate_c_substantive_worksheet.csv")
    gcw["subst"] = gcw["substantive_vs_wording"].map(_s)
    bad = set(gcw["subst"]) - SUBST_VALID
    if bad:
        raise SystemExit(f"Gate C substantive worksheet has invalid codes: {bad}")
    subst_raw = cascade["nct_id"].map(gcw.set_index("nct_id")["subst"]).fillna("NOT_APPLICABLE")
    cascade["gate_c_substantive_worksheet"] = subst_raw  # Tanish's original title-only call
    corrected = subst_raw.copy()
    for nct, new in GATE_C_SUBSTANTIVE_CORRECTIONS.items():
        m = cascade["nct_id"] == nct
        old = subst_raw[m].iloc[0]
        if old == new:
            raise SystemExit(f"Gate C reversal no-op for {nct}: already {new}")
        corrected[m] = new
        corr_records.append({"nct_id": nct, "gate": "C", "field": "substantive_vs_wording",
                             "original": old, "corrected": new,
                             "provenance": "colleague_audit_reversal",
                             "reason": "title-only worksheet corrected vs full prospective/latest "
                                       "outcome objects (measure+description+time frame)",
                             "still_open_needs_human": False})
    cascade["gate_c_substantive"] = corrected
    cascade["gate_c_substantive_provenance"] = np.where(
        cascade["nct_id"].isin(GATE_C_SUBSTANTIVE_CORRECTIONS), "colleague_audit_reversal",
        np.where(subst_raw == "NOT_APPLICABLE", "not_applicable", "author_coding"))

    def _effective_c(r) -> str:
        if r["gate_c"] != "DIFFERS_FROM_PROSPECTIVE":
            return r["gate_c"]
        # Only a SUBSTANTIVE_CHANGE is a real post-enrolment goalpost move. A WORDING_ONLY
        # registry difference is derived to SUBSTANTIVELY_CONCORDANT_WITH_PROSPECTIVE — a
        # distinct label so the raw textual DIFFERS fact is never overwritten (colleague rule).
        if r["gate_c_substantive"] == "WORDING_ONLY":
            return "SUBSTANTIVELY_CONCORDANT_WITH_PROSPECTIVE"
        return "DIFFERS_FROM_PROSPECTIVE"
    cascade["gate_c_effective"] = cascade.apply(_effective_c, axis=1)
    cascade["gate_c_effective_provenance"] = np.where(
        cascade["gate_c"] == "DIFFERS_FROM_PROSPECTIVE",
        "derived_from_author_coding(colleague rule)", "system_field(=raw gate_c)")

    # ---- gate_d_target under both Gate C notions (raw already computed in assemble) ----
    eff_conc = cascade["gate_c_effective"].isin(CONCORDANT_EFFECTIVE)
    cascade["gate_d_target_substantive"] = np.where(
        eff_conc, cascade["gate_d_latest_reference"], "UNASSESSABLE_UNDER_REFERENCE")
    cascade["gate_d_target_substantive_provenance"] = np.where(
        eff_conc, cascade["gate_d_latest_reference_provenance"], "system_field")

    # ---- provenance / review bookkeeping ----
    # Colleague fix #4: don't collapse needs_human_review to Gate-A alone, and don't flood it with
    # the registry flags either — store the W1 Gate-C registry-review flag in a DEDICATED field and
    # keep needs_human_review a crisp structural signal (unresolved identity + open Gate-D queries).
    gc = read_gate_c().set_index("nct_id")
    if "needs_human_review" in gc:
        cascade["gate_c_registry_review_flag"] = cascade["nct_id"].map(
            gc["needs_human_review"].astype(bool)).fillna(True)
    else:
        cascade["gate_c_registry_review_flag"] = True
    cascade["needs_human_review"] = (
        cascade["gate_a"].eq("UNASSESSABLE") | cascade["nct_id"].isin(gd_query_open))
    cascade["coder_id"] = ("merge: reference/mechanical gates auto; Gate B / Gate D elements / "
                           "Gate C substantive = author-coding (Tanish) + colleague-audit corrections")
    cascade["coding_date"] = TODAY

    # ---- preserve author notes + correction records in the audit file ----
    audit = audit.merge(gb.set_index("nct_id")["gate_b_notes"].rename("gate_b_notes"),
                        left_on="nct_id", right_index=True, how="left")
    if "notes" in gcw:
        audit = audit.merge(gcw.set_index("nct_id")["notes"].rename("gate_c_substantive_notes"),
                            left_on="nct_id", right_index=True, how="left")
    if "notes" in gd:
        audit = audit.merge(gd.set_index("nct_id")["notes"].rename("gate_d_element_notes"),
                            left_on="nct_id", right_index=True, how="left")
    OUT_CORR = VALIDATION_DIR / "error_cascade_corrections.csv"
    pd.DataFrame(corr_records).to_csv(OUT_CORR, index=False)

    cascade.to_csv(OUT, index=False)
    audit.to_csv(OUT_AUDIT, index=False)
    panels = compute_panels(cascade)
    OUT_PANELS.write_text(json.dumps(panels, indent=2, default=str))

    print("=== error_cascade.csv MERGED (author-coding folded in) ===")
    print("Gate A:", panels["unconditional"]["gate_a"])
    print("Gate B:", panels["unconditional"]["gate_b"])
    print("Gate C (raw):", panels["unconditional"]["gate_c"])
    print("Gate C substantive split:", panels["unconditional"]["gate_c_substantive"])
    print("Gate C (effective):", panels["unconditional"]["gate_c_effective"])
    print("gate_d_target (raw):", panels["unconditional"]["gate_d_target"])
    print("gate_d_target (substantive):", panels["unconditional"]["gate_d_target_substantive"])
    print("\nSequential attrition — raw Gate C:", panels["sequential_raw_textual_gate_c"])
    print("Sequential attrition — substantive-only Gate C:", panels["sequential_substantive_gate_c"])
    print("\nP4 landing:", panels["p4_landing"])
    print("\nGate-D element panel (primary, n=30):", panels["gate_d_element_panel_primary"]["n"])
    print("Colleague-audit corrections applied:", len(corr_records),
          f"(5 Gate-C reversals + 3 Gate-D element queries) → {OUT_CORR.name}")
    print("Open Gate-D queries flagged needs_human_review:", sorted(gd_query_open))
    print("\nAudit still required:", panels["author_coding_audit"]["required"],
          "— status:", panels["author_coding_audit"]["status"])
    print(f"\nWrote: {OUT}, {OUT_AUDIT}, {OUT_PANELS}, {OUT_CORR}")


def compute_panels(c: pd.DataFrame) -> dict:
    def vc(col):
        return c[col].value_counts(dropna=False).to_dict()

    A = c["gate_a"] == "PASS"
    B = c["gate_b"] == "PASS"
    Craw = c["gate_c"] == "CONCORDANT_WITH_PROSPECTIVE"
    Ceff = c["gate_c_effective"].isin(CONCORDANT_EFFECTIVE)
    Traw = c["gate_d_target"] == "MATERIAL_CHANGE"
    Tsub = c["gate_d_target_substantive"] == "MATERIAL_CHANGE"
    P4 = c["system_P4"].astype(bool)
    P5 = c["system_P5"].astype(bool)

    # Primary Gate-D element panel: the n=30 Gate-A-PASS AND Gate-B-PASS cases only
    # (colleague fix — the unconditional 45/97 panel has the wrong analytic denominator).
    elem_panel = c[A & B]

    seq_raw = {
        "n_total": int(len(c)),
        "1_gate_a_pass": int(A.sum()),
        "2_and_gate_b_pass": int((A & B).sum()),
        "3_and_gate_c_concordant": int((A & B & Craw).sum()),
        "4_and_gate_d_target_material": int((A & B & Craw & Traw).sum()),
    }
    seq_sub = {
        "n_total": int(len(c)),
        "1_gate_a_pass": int(A.sum()),
        "2_and_gate_b_pass": int((A & B).sum()),
        "3_and_gate_c_effective_concordant": int((A & B & Ceff).sum()),
        "4_and_gate_d_target_material": int((A & B & Ceff & Tsub).sum()),
    }
    p4_landing = {
        "P4_total": int(P4.sum()),
        "P4_and_gate_a_fail": int((P4 & (c["gate_a"] == "FAIL")).sum()),
        "P4_and_gate_a_unassessable": int((P4 & (c["gate_a"] == "UNASSESSABLE")).sum()),
        "P4_and_gate_a_pass_but_gate_b_not_pass": int((P4 & A & ~B).sum()),
        "P4_and_gate_c_not_concordant_raw": int((P4 & A & B & ~Craw).sum()),
        "P4_surviving_to_target_material_raw": int((P4 & A & B & Craw & Traw).sum()),
        "P4_surviving_to_target_material_substantive": int((P4 & A & B & Ceff & Tsub).sum()),
    }
    return {
        "note": "Unconditional gate-status counts on all 97 + sequential attrition. Gate C reported "
                "two ways: raw-textual (any registry primary-outcome change) and substantive-only "
                "(WORDING_ONLY differences treated as effectively concordant). Gates B / Gate-D "
                "elements / Gate-C substantive split are author-coding (Tanish), provenance-tagged; "
                "the collapsed gate_d_target that drives the cascade is reference-based.",
        "unconditional": {
            "n": int(len(c)),
            "gate_a": vc("gate_a"),
            "gate_b": vc("gate_b"),
            "gate_c": vc("gate_c"),
            "gate_c_substantive": vc("gate_c_substantive"),
            "gate_c_effective": vc("gate_c_effective"),
            "gate_d_latest_reference": vc("gate_d_latest_reference"),
            "gate_d_target": vc("gate_d_target"),
            "gate_d_target_substantive": vc("gate_d_target_substantive"),
            "gate_d_latest_elements_material": vc("gate_d_latest_elements_material"),
            "reference_final_label": vc("reference_final_label"),
        },
        "gate_d_element_panel_primary": {
            "denominator": "Gate-A-PASS AND Gate-B-PASS",
            "n": int(len(elem_panel)),
            "element_distributions": {
                ("gate_d_latest_" + e): elem_panel["gate_d_latest_" + e].value_counts(dropna=False).to_dict()
                for e in ELEMENT_COLS},
            "elements_material": elem_panel["gate_d_latest_elements_material"].value_counts(dropna=False).to_dict(),
            "note": "Author-coded element panel restricted to the assessable n=30; the reference "
                    "collapsed gate_d_latest_reference and the author element-derived material flag "
                    "answer related but differently-operationalized questions (display both, do not "
                    "reconcile silently — colleague audit).",
        },
        "sequential_raw_textual_gate_c": seq_raw,
        "sequential_substantive_gate_c": seq_sub,
        "p4_landing": p4_landing,
        "system_positives": {"P4": int(P4.sum()), "P5": int(P5.sum())},
        "author_coding_audit": {
            "required": "≥15 cases or 20% of the assessable set (codebook §3/§7), sampled across codes",
            "status": "PENDING — independent auditor (not Tanish, not Alessandra) has not yet returned codes",
            "note": "Author-coding provenance is retained; a second-author audit does not upgrade it "
                    "to reference-standard.",
        },
    }


def _worksheets_already_filled() -> list[str]:
    """Return worksheet files that already contain human codes (so re-emitting blanks would
    destroy the sole author-coding inputs)."""
    checks = {"gate_b_worksheet.csv": "gate_b",
              "gate_d_elements_worksheet.csv": "domain",
              "gate_c_substantive_worksheet.csv": "substantive_vs_wording"}
    filled = []
    for fname, col in checks.items():
        p = WS_DIR / fname
        if not p.exists():
            continue
        try:
            df = _read_ws(p)
            if col in df and df[col].astype(str).str.strip().replace("nan", "").ne("").any():
                filled.append(fname)
        except Exception:
            filled.append(fname)  # unreadable → be conservative, treat as filled
    return filled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge", action="store_true", help="fold filled worksheets back into the cascade")
    ap.add_argument("--force-emit", action="store_true",
                    help="re-emit BLANK worksheets even if filled ones exist (DESTRUCTIVE)")
    args = ap.parse_args()
    if args.merge:
        merge()
        return

    # Guard: the non-merge (assemble) path re-emits blank worksheets. If filled worksheets already
    # exist, refuse — re-emitting would wipe the sole human author-coding inputs. Use --merge to fold
    # them in, or --force-emit to deliberately regenerate blanks.
    filled = _worksheets_already_filled()
    if filled and not args.force_emit:
        raise SystemExit(
            "Refusing to re-emit blank worksheets — these already contain human codes: "
            f"{filled}. Did you mean `--merge`? To regenerate blanks anyway, pass --force-emit "
            "(the filled versions are git-tracked, but working edits would be lost).")

    cascade, audit, adj = assemble()
    cascade.to_csv(OUT, index=False)
    audit.to_csv(OUT_AUDIT, index=False)
    nb, nd, nc = emit_worksheets(cascade, adj)
    counts = unconditional_counts(cascade)
    OUT_COUNTS.write_text(json.dumps(counts, indent=2, default=str))

    print("=== error_cascade.csv assembled (mechanical/reference gates) ===")
    print("Gate A:", counts["gate_a"])
    print("Gate C:", counts["gate_c"])
    print("gate_d_latest_reference:", counts["gate_d_latest_reference"])
    print("gate_d_target:", counts["gate_d_target"])
    print("reference_final_label:", counts["reference_final_label"])
    print("sequential (partial, B pending):", counts["sequential_partial"])
    print(f"\nWorksheets (author-coding, blinded): gate_b={nb} rows, gate_d_elements={nd}, "
          f"gate_c_substantive={nc}")
    print(f"Wrote: {OUT}, {OUT_AUDIT}, {OUT_COUNTS}, and worksheets/ (+ BLIND_KEY.csv)")


if __name__ == "__main__":
    main()

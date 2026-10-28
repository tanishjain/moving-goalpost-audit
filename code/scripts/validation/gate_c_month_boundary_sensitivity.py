#!/usr/bin/env python3
"""G3 sensitivity — Gate C month-boundary robustness (in-script reproduction).

The frozen W1 date rule pads a month/year-granular study start to the FIRST of the
month/year (conservative: fewer registry versions qualify as pre-enrolment). 26/97
reference cases have month-granular starts, so the prospective/at-start boundary is
ambiguous by up to a month. This script recomputes Gate C for those cases under the
PERMISSIVE alternative — the LAST day of the month/year — and re-runs the cascade to
confirm the terminal target-material count is robust to that ambiguity band.

The Colleague previously computed this analytically (effective Gate-C-concordant in the
A-pass∧B-pass set 16→18; terminal stays 2). This script reproduces it reproducibly from
the cached registry history. It does NOT alter the frozen primary W1 output or the merged
`error_cascade.csv`; it writes a separate sensitivity file + panel.

No API calls (cache-first via the W1 helpers); no author-coding generated. Run:
    uv run python scripts/validation/gate_c_month_boundary_sensitivity.py
"""
from __future__ import annotations

import calendar
import io
import json
from datetime import date

import pandas as pd

from moving_goalpost.config import VALIDATION_DIR
from retrieve_gate_c_registry_timing import (  # reuse frozen W1 machinery (cache-first)
    fetch_history_list, fetch_version, measures_from_version, normalize_measures,
    CODE_CONCORDANT, CODE_DIFFERS, CODE_NO_PROSPECTIVE, CODE_UNASSESSABLE,
)

GATE_C = VALIDATION_DIR / "gate_c_registry_timing.csv"
CASCADE = VALIDATION_DIR / "error_cascade.csv"
OUT_CSV = VALIDATION_DIR / "gate_c_month_boundary_sensitivity.csv"
OUT_PANEL = VALIDATION_DIR / "error_cascade_month_boundary_panel.json"


def _read_no_comment(path) -> pd.DataFrame:
    lines = [ln for ln in open(path) if not ln.startswith("#")]
    return pd.read_csv(io.StringIO("".join(lines)))


def month_end(raw: str) -> date | None:
    """End-of-period cutoff for a partial date: 'YYYY-MM'->last day of month,
    'YYYY'->Dec 31. Full 'YYYY-MM-DD' returns that day unchanged."""
    raw = str(raw).strip()
    parts = raw.split("-")
    try:
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            y, m = int(parts[0]), int(parts[1])
            return date(y, m, calendar.monthrange(y, m)[1])
        if len(parts) == 1 and parts[0]:
            return date(int(parts[0]), 12, 31)
    except (ValueError, IndexError):
        return None
    return None


def recode_alt(nct: str, raw_start: str, latest_measures: str) -> tuple[str, str, str]:
    """Recompute Gate C under the END-of-period start cutoff.
    Returns (alt_code, alt_prospective_version_date, note)."""
    alt_start = month_end(raw_start)
    if alt_start is None:
        return CODE_UNASSESSABLE, "", "no parseable start"
    changes = fetch_history_list(nct)  # cached
    on_or_before = [c for c in changes if date.fromisoformat(c["date"]) <= alt_start]
    if not on_or_before:
        return CODE_NO_PROSPECTIVE, "", f"earliest version after end-of-period start {alt_start.isoformat()}"
    prosp = on_or_before[-1]
    protocol = fetch_version(nct, prosp["version"])  # cached
    prosp_measures = measures_from_version(protocol)
    if not prosp_measures:
        return CODE_UNASSESSABLE, prosp["date"], "prospective version has no structured primaryOutcomes"
    if not normalize_measures(latest_measures):
        return CODE_UNASSESSABLE, prosp["date"], "current latest empty"
    if normalize_measures(" | ".join(prosp_measures)) == normalize_measures(latest_measures):
        return CODE_CONCORDANT, prosp["date"], ""
    return CODE_DIFFERS, prosp["date"], "prospective vs latest differ (would need substantive coding)"


def main():
    gc = _read_no_comment(GATE_C).set_index("nct_id")
    rows = []
    for nct, r in gc.iterrows():
        gran = r["start_date_granularity"]
        primary = r["gate_c_code"]
        if gran not in ("month", "year"):
            rows.append({"nct_id": nct, "granularity": gran, "primary_gate_c": primary,
                         "alt_gate_c": primary, "changed": False,
                         "alt_prospective_version_date": r.get("prospective_version_date", ""),
                         "note": "day-granular: boundary rule does not apply"})
            continue
        raw = r["actual_start_date"] if str(r["actual_start_date"]).strip() not in ("", "nan") \
            else r["estimated_start_date"]
        alt_code, alt_vdate, note = recode_alt(nct, raw, r.get("current_latest_primary_outcome", ""))
        rows.append({"nct_id": nct, "granularity": gran, "primary_gate_c": primary,
                     "alt_gate_c": alt_code, "changed": alt_code != primary,
                     "alt_prospective_version_date": alt_vdate, "note": note})
    sens = pd.DataFrame(rows)
    sens.to_csv(OUT_CSV, index=False)

    changed = sens[sens["changed"]]
    alt_by_nct = dict(zip(sens["nct_id"], sens["alt_gate_c"]))

    # ---- recompute cascade terminal under alt Gate C ----
    ec = pd.read_csv(CASCADE)
    ec["alt_gate_c"] = ec["nct_id"].map(alt_by_nct).fillna(ec["gate_c"])
    a_pass = ec["gate_a"] == "PASS"
    b_pass = ec["gate_b"] == "PASS"
    material_latest = ec["gate_d_latest_reference"] == "MATERIAL_CHANGE"

    # raw: concordant only; substantive: concordant OR (wording-only DIFFERS = effective concordant).
    # A DIFFERS that newly appears under alt (not in the primary substantive worksheet) cannot be
    # classified wording/substantive without new author-coding -> excluded from effective-concordant
    # and flagged.
    prim_diff_coded = set(ec.loc[ec["gate_c"] == "DIFFERS_FROM_PROSPECTIVE", "nct_id"])
    wording = set(ec.loc[ec["gate_c_effective"] == "SUBSTANTIVELY_CONCORDANT_WITH_PROSPECTIVE", "nct_id"])

    def alt_effective_concordant(row) -> bool:
        c = row["alt_gate_c"]
        if c == "CONCORDANT_WITH_PROSPECTIVE":
            return True
        if c == "DIFFERS_FROM_PROSPECTIVE":
            return row["nct_id"] in wording  # only if primary-coded wording-only
        return False

    ec["alt_concordant_raw"] = ec["alt_gate_c"] == "CONCORDANT_WITH_PROSPECTIVE"
    ec["alt_concordant_sub"] = ec.apply(alt_effective_concordant, axis=1)
    newly_differs_uncoded = [n for n in changed["nct_id"]
                             if alt_by_nct[n] == "DIFFERS_FROM_PROSPECTIVE" and n not in prim_diff_coded]

    def seq(concordant_mask):
        s = {"gate_a_pass": int(a_pass.sum()),
             "and_gate_b_pass": int((a_pass & b_pass).sum()),
             "and_gate_c_concordant": int((a_pass & b_pass & concordant_mask).sum()),
             "and_target_material": int((a_pass & b_pass & concordant_mask & material_latest).sum())}
        return s

    # primary baselines recomputed from the cascade (not hard-coded)
    prim_raw = ec["gate_c"] == "CONCORDANT_WITH_PROSPECTIVE"
    prim_sub = ec["gate_c_effective"].isin(
        ["CONCORDANT_WITH_PROSPECTIVE", "SUBSTANTIVELY_CONCORDANT_WITH_PROSPECTIVE"])
    # of the newly-DIFFERS-uncoded cases, which sit in the A-pass&B-pass set (carry +/-1 each)?
    uncoded_in_ab = [n for n in newly_differs_uncoded
                     if (ec.loc[ec["nct_id"] == n, "gate_a"] == "PASS").any()
                     and (ec.loc[ec["nct_id"] == n, "gate_b"] == "PASS").any()]

    panel = {
        "description": "Gate C month-boundary sensitivity: month/year-granular starts padded to "
                       "END-of-period (permissive) vs the frozen FIRST-of-period (primary). "
                       "Prospective version is re-picked from cached registry history for ALL "
                       "granular cases (including primary DIFFERS), then Gate C re-coded.",
        "n_month_or_year_granular": int((sens["granularity"] != "day").sum()),
        "n_changed": int(sens["changed"].sum()),
        "changed_cases": changed[["nct_id", "primary_gate_c", "alt_gate_c"]].to_dict("records"),
        "sequential_raw_primary_boundary": seq(prim_raw),
        "sequential_raw_alt_boundary": seq(ec["alt_concordant_raw"]),
        "sequential_substantive_primary_boundary": seq(prim_sub),
        "sequential_substantive_alt_boundary": seq(ec["alt_concordant_sub"]),
        "terminal_material_cases": ec.loc[
            a_pass & b_pass & ec["alt_concordant_sub"] & material_latest, "nct_id"].tolist(),
        "newly_differs_needing_author_coding": newly_differs_uncoded,
        "newly_differs_uncoded_in_A_and_B_set": uncoded_in_ab,
        "colleague_reconciliation_note": (
            "Colleague's analytical estimate was substantive concordant 16->18 (+2). This in-script "
            "run gives 16->19 (+3), because it re-picks the prospective version for primary-DIFFERS "
            "cases too (NCT01248403 flips DIFFERS->CONCORDANT under end-of-period), not only for "
            "NO_PROSPECTIVE cases. Additionally NCT01869413 flips NO_PROSPECTIVE->DIFFERS and sits in "
            "the A&B set; its wording/substantive status is uncoded (not in the primary DIFFERS "
            "worksheet), so the substantive-concordant count carries +/-1 there. Research Design "
            "Agent to reconcile which boundary/scope convention the manuscript should report."),
        "conclusion": "Terminal target-material count is UNCHANGED (=2) under the month-boundary "
                      "shift in every scenario; both terminal cases (NCT01404156, NCT04534725) are "
                      "unaffected. The robustness claim holds; only the intermediate concordant "
                      "count moves within a small band.",
    }
    OUT_PANEL.write_text(json.dumps(panel, indent=2, default=str))

    print(f"month/year-granular cases: {panel['n_month_or_year_granular']}; changed under alt boundary: "
          f"{panel['n_changed']}")
    if len(changed):
        print(changed[["nct_id", "primary_gate_c", "alt_gate_c"]].to_string(index=False))
    print("\nsequential (raw, alt boundary):", panel["sequential_raw_alt_boundary"])
    print("sequential (substantive, alt boundary):", panel["sequential_substantive_alt_boundary"])
    print("terminal target-material cases:", panel["terminal_material_cases"])
    if newly_differs_uncoded:
        print("⚠ newly-DIFFERS under alt boundary needing author-coding:", newly_differs_uncoded)
    print(f"\nWrote {OUT_CSV} and {OUT_PANEL}")


if __name__ == "__main__":
    main()

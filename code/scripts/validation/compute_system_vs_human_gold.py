#!/usr/bin/env python3
"""Compute system performance against the two-independent-human adjudicated gold standard.

Gold standard construction (Option 3, two-axis disentanglement):
  - Per row, each reviewer's judgment is decomposed into wrong_paper_match (bool) and
    endpoint_judgment (GENUINE_DISCREPANCY / NO_DISCREPANCY / GENUINELY_AMBIGUOUS), already stored
    in manual_validation_adjudication.csv.
  - The bottom-line human verdict ("is this a genuine outcome-switching discrepancy?") is:
        wrong_paper_match == True            -> NOT_GENUINE  (match error, not switching)
        endpoint_judgment == GENUINE         -> GENUINE
        endpoint_judgment == NO/AMBIGUOUS    -> NOT_GENUINE
  - gold_label = adjudicator_label where the two reviewers disagreed on the bottom line
    (adjudicator resolved every such row); otherwise the agreed bottom line.

This intentionally does NOT reuse comprehensive_validation.py's raw reviewer_a==reviewer_b cascade,
because the two reviewers used different label CONVENTIONS for wrong-paper matches (TJ -> UNCLEAR,
AC -> NO_DISCREPANCY); a raw-label equality test would drop those ~38 rows as "unresolved" even
though both reviewers agree the paper is a wrong match and hence NOT a genuine discrepancy.

System flag = potential_discrepancy (from the pipeline output in manual_validation_sample.csv).
Positive class = GENUINE_DISCREPANCY.

NOTE ON SAMPLING: the 97-row validation set is STRATIFIED across classification types and judge
scores (not a random draw), so precision/recall here characterize the sample, not population base
rates. Reported as-is.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from moving_goalpost.config import VALIDATION_DIR, PROCESSED_DIR

ADJ = VALIDATION_DIR / "manual_validation_adjudication.csv"
SAMPLE = VALIDATION_DIR / "manual_validation_sample.csv"   # carries system potential_discrepancy
STAGE5 = PROCESSED_DIR / "stage5_final_results.csv"        # carries match_method
OUT_JSON = VALIDATION_DIR / "system_validation_vs_human_gold.json"
OUT_MD = VALIDATION_DIR / "system_validation_vs_human_gold.md"

VALID = {"GENUINE_DISCREPANCY", "NO_DISCREPANCY"}


def _clean(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip().upper()
    return s if s in {"GENUINE_DISCREPANCY", "NO_DISCREPANCY", "UNCLEAR"} else ""


def _bottom_line(wp, ep) -> str:
    if str(wp).strip().upper() == "TRUE" or wp is True:
        return "NOT_GENUINE"
    if ep == "GENUINE_DISCREPANCY":
        return "GENUINE"
    if ep in ("NO_DISCREPANCY", "GENUINELY_AMBIGUOUS"):
        return "NOT_GENUINE"
    return "?"  # NEEDS_ADJUDICATION / unknown -> resolved via adjudicator below


def _gold(row) -> str:
    adj = _clean(row.get("adjudicator_label"))
    if adj:
        return adj
    bl_a = _bottom_line(row.get("wrong_paper_match_a"), row.get("endpoint_judgment_a"))
    bl_b = _bottom_line(row.get("wrong_paper_match_b"), row.get("endpoint_judgment_b"))
    if bl_a == bl_b == "GENUINE":
        return "GENUINE_DISCREPANCY"
    if bl_a == "NOT_GENUINE" and bl_b == "NOT_GENUINE":
        return "NO_DISCREPANCY"
    return ""  # unresolved conflict — must be empty once adjudication is complete


def _binary_kappa(flag: pd.Series, gold_pos: pd.Series) -> float:
    a = flag.astype(bool).to_numpy()
    b = gold_pos.astype(bool).to_numpy()
    n = len(a)
    po = float((a == b).mean())
    pa1, pb1 = a.mean(), b.mean()
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    return float((po - pe) / (1 - pe)) if pe != 1 else float("nan")


def _metrics(sub: pd.DataFrame) -> dict:
    flagged = sub["system_flag"]
    genuine = sub["gold_label"] == "GENUINE_DISCREPANCY"
    tp = int((flagged & genuine).sum())
    fp = int((flagged & ~genuine).sum())
    fn = int((~flagged & genuine).sum())
    tn = int((~flagged & ~genuine).sum())
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall and (precision + recall) else None)
    accuracy = (tp + tn) / len(sub) if len(sub) else None
    specificity = tn / (tn + fp) if (tn + fp) else None
    return {
        "n": int(len(sub)),
        "gold_genuine": int(genuine.sum()),
        "gold_no": int((~genuine).sum()),
        "system_flagged": int(flagged.sum()),
        "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "accuracy": accuracy, "specificity": specificity,
        "cohens_kappa_system_vs_gold": _binary_kappa(flagged, genuine),
    }


def main() -> None:
    adj = pd.read_csv(ADJ)
    adj["gold_label"] = adj.apply(_gold, axis=1)

    unresolved = adj[~adj["gold_label"].isin(VALID)]
    if len(unresolved):
        raise SystemExit(
            f"{len(unresolved)} rows have no gold label — adjudication incomplete: "
            f"{unresolved['nct_id'].tolist()}"
        )

    sample = pd.read_csv(SAMPLE)[["nct_id", "pmid", "potential_discrepancy", "classification"]]
    df = adj.merge(sample, on=["nct_id", "pmid"], how="left", validate="one_to_one")
    df["system_flag"] = df["potential_discrepancy"].astype(str).str.strip().str.upper() == "TRUE"

    # match_method for the NCT-ID-matched subset
    try:
        s5 = pd.read_csv(STAGE5)[["nct_id", "pmid", "match_method"]].drop_duplicates("nct_id")
        df = df.merge(s5, on=["nct_id", "pmid"], how="left")
    except Exception:
        df["match_method"] = np.nan

    overall = _metrics(df)

    by_match = {}
    if df["match_method"].notna().any():
        for mm, sub in df.groupby(df["match_method"].fillna("UNKNOWN")):
            by_match[str(mm)] = _metrics(sub)

    # NCT-ID-matched subset (primary analysis in the manuscript)
    nct_mask = df["match_method"].astype(str).str.contains("nct", case=False, na=False)
    nct_subset = _metrics(df[nct_mask]) if nct_mask.any() else None

    # Classifier-only view: restrict to rows where BOTH reviewers judged the paper a correct
    # match (wrong_paper_match == False for both). This isolates endpoint-classification skill
    # from publication-matching errors.
    def _is_false(v):
        return str(v).strip().upper() == "FALSE" or v is False
    paper_ok = df["wrong_paper_match_a"].map(_is_false) & df["wrong_paper_match_b"].map(_is_false)
    classifier_only = _metrics(df[paper_ok]) if paper_ok.any() else None

    result = {
        "gold_standard": {
            "source": "two independent human reviewers (TJ, AC) + adjudicator (TJ), Option-3 two-axis",
            "n_total": int(len(df)),
            "n_adjudicated_rows": int(adj["adjudicator_label"].notna().sum()),
            "gold_distribution": df["gold_label"].value_counts().to_dict(),
        },
        "system_flag": "potential_discrepancy (pipeline)",
        "positive_class": "GENUINE_DISCREPANCY",
        "sampling_caveat": "97-row set is stratified across classification types/judge scores; "
                           "precision/recall characterize the sample, not population base rates.",
        "overall": overall,
        "nct_id_matched_subset": nct_subset,
        "classifier_only_both_reviewers_paper_correct": classifier_only,
        "by_match_method": by_match,
    }
    OUT_JSON.write_text(json.dumps(result, indent=2, default=str))

    def _fmt(x):
        return f"{x:.3f}" if isinstance(x, float) else str(x)

    L = ["# System vs two-human adjudicated gold standard\n\n"]
    L.append(f"Gold standard: {result['gold_standard']['source']}. "
             f"n = {overall['n']}, adjudicated rows = {result['gold_standard']['n_adjudicated_rows']}, "
             f"gold distribution = {result['gold_standard']['gold_distribution']}.\n\n")
    L.append(f"> {result['sampling_caveat']}\n\n")
    L.append("## Overall (system flag = `potential_discrepancy`, positive = GENUINE_DISCREPANCY)\n\n")
    L.append("| metric | value |\n|---|---|\n")
    for k in ["n", "gold_genuine", "gold_no", "system_flagged", "TP", "FP", "FN", "TN",
              "precision", "recall", "f1", "accuracy", "specificity", "cohens_kappa_system_vs_gold"]:
        L.append(f"| {k} | {_fmt(overall[k])} |\n")
    if nct_subset:
        L.append("\n## NCT-ID-matched subset (manuscript primary analysis)\n\n")
        L.append("| metric | value |\n|---|---|\n")
        for k in ["n", "gold_genuine", "system_flagged", "TP", "FP", "FN", "TN",
                  "precision", "recall", "f1", "accuracy"]:
            L.append(f"| {k} | {_fmt(nct_subset[k])} |\n")
    if classifier_only:
        L.append("\n## Classifier-only view — rows where both reviewers judged the paper a correct match\n\n")
        L.append("Isolates endpoint-classification skill from publication-matching errors.\n\n")
        L.append("| metric | value |\n|---|---|\n")
        for k in ["n", "gold_genuine", "gold_no", "system_flagged", "TP", "FP", "FN", "TN",
                  "precision", "recall", "f1", "accuracy", "specificity"]:
            L.append(f"| {k} | {_fmt(classifier_only[k])} |\n")
    if by_match:
        L.append("\n## By match method\n\n")
        L.append("| match_method | n | gold_genuine | flagged | precision | recall | f1 |\n|---|---|---|---|---|---|---|\n")
        for mm, mt in sorted(by_match.items()):
            L.append(f"| {mm} | {mt['n']} | {mt['gold_genuine']} | {mt['system_flagged']} | "
                     f"{_fmt(mt['precision'])} | {_fmt(mt['recall'])} | {_fmt(mt['f1'])} |\n")
    OUT_MD.write_text("".join(L))

    print(json.dumps({"overall": overall, "nct_id_matched_subset": nct_subset,
                      "classifier_only_both_reviewers_paper_correct": classifier_only,
                      "gold_distribution": result["gold_standard"]["gold_distribution"]},
                     indent=2, default=str))
    print(f"\nWrote {OUT_JSON}\nWrote {OUT_MD}")


if __name__ == "__main__":
    main()

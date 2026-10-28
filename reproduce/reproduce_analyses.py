#!/usr/bin/env python3
"""Reproduce the publicly supportable analyses from the distributed categorical data only.

This is analysis reproduction, separate from integrity verification (`verify_snapshot.py` and
`data/signed_release/verify_release.py`). Every value below is recomputed from the case-level categorical
files in `data/signed_release/benchmark/` with the frozen research functions in `code/`, then compared
with the approved public aggregates in `data/signed_release/benchmark/` and `data/display_package/tables/`
and with the values in `reproduce/approved_values.json` (taken from the manuscript claims ledger).

No network access, private data or model call is needed. Results that cannot be recomputed from the
distributed data are listed in `docs/REPRODUCTION_COVERAGE.md` and are not checked here.

    python reproduce/reproduce_analyses.py --out reproduction_output

Exit status 0 means every check passed; 1 means at least one check failed (see the report).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code"
for _p in (CODE / "scripts" / "validation", CODE / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build_error_cascade as bec  # noqa: E402  frozen cascade panels (compute_panels)
import g2_design_aware_validation as g2  # noqa: E402  frozen exact-interval and Hajek-ratio functions
import g5_analyze as ga  # noqa: E402  frozen G5 analysis contract
import g5_build_release as g5r  # noqa: E402  frozen G5 aggregate-table builders
import g5_run_ablation as runner  # noqa: E402  public subset of the run harness: frozen cell plan order

RELEASE = ROOT / "data" / "signed_release"
BENCH = RELEASE / "benchmark"
DISPLAY = ROOT / "data" / "display_package" / "tables"
MANIFEST = ROOT / "EXPORT_MANIFEST.json"
APPROVED = Path(__file__).resolve().parent / "approved_values.json"

PUBLIC_CELL_COLUMNS = ["case_id", "model_identifier", "arm", "terminal_status", "model_gate_a", "model_gate_d",
                       "derived_disposition", "human_reference_gate_a", "human_reference_label", "correct"]
CASCADE_INPUT_COLUMNS = ["nct_id", "pmid", "gate_a", "gate_a_provenance", "gate_b", "gate_c", "gate_c_substantive",
                         "gate_c_effective", "gate_d_latest_reference", "gate_d_target", "gate_d_target_substantive",
                         "gate_d_latest_elements_material", "system_P4", "system_P5", "reference_final_label"]
ELEMENTS = ["domain", "measurement", "metric", "aggregation", "timepoint", "priority", "addition_omission",
            "multiplicity_mapping"]
G5_TABLES = ["primary_effects", "mechanism_by_human_gate_a", "gate_a_and_conditional_d", "status_coverage",
             "wrong_paper_arm2_responses"]


class ReproductionError(Exception):
    """Input contract violated (malformed, missing, duplicate or drifted data); nothing is reported."""


# --------------------------------------------------------------------------------------------------
# Inputs: hash-pinned, strictly validated
# --------------------------------------------------------------------------------------------------
def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def verify_inputs(root: Path = ROOT) -> None:
    """Fail closed if any distributed data file differs from EXPORT_MANIFEST.json (hash drift)."""
    man = json.loads((root / "EXPORT_MANIFEST.json").read_text())
    for rel, rec in man["files"].items():
        if rel.startswith("data/"):
            p = root / rel
            if not p.is_file() or _sha(p) != rec["sha256"]:
                raise ReproductionError(f"input hash drift or missing file: {rel}")


def _gate(v):
    return None if (v is None or (isinstance(v, float) and np.isnan(v))) else str(v)


def load_public_cells(path: Path = BENCH / "g5_cells_source_text_free.csv"):
    """Return (cells, ref, public) in the frozen analysis schema. Rejects malformed, unknown, missing,
    duplicate or internally inconsistent cells before any analysis."""
    pub = pd.read_csv(path, dtype={"model_gate_a": str, "model_gate_d": str})
    if list(pub.columns) != PUBLIC_CELL_COLUMNS:
        raise ReproductionError(f"unexpected cell columns: {list(pub.columns)}")
    for col in ("case_id", "arm", "correct"):
        if not pd.api.types.is_integer_dtype(pub[col]):
            raise ReproductionError(f"column {col} is not integer-valued")
    if pub.duplicated(["case_id", "model_identifier", "arm"]).any():
        raise ReproductionError("duplicate case x model x arm cells")
    bad = set(pub.terminal_status) - ga.ALLOWED_STATUS
    if bad:
        raise ReproductionError(f"unknown terminal status {sorted(bad)}")
    per_case = pub.groupby("case_id")[["human_reference_gate_a", "human_reference_label"]].nunique(dropna=False)
    if (per_case > 1).any().any():
        raise ReproductionError("a case carries more than one human reference label")
    cells = pd.DataFrame({
        "case_id": pub.case_id.astype(int), "arm": pub.arm.astype(int), "model": pub.model_identifier.astype(str),
        "status": pub.terminal_status.astype(str),
        "gate_a": pd.Series([_gate(v) for v in pub.model_gate_a], dtype=object),
        "gate_d": pd.Series([_gate(v) for v in pub.model_gate_d], dtype=object)})
    ref = (pub.drop_duplicates("case_id")[["case_id", "human_reference_label", "human_reference_gate_a"]]
           .rename(columns={"human_reference_label": "ref_bottom_line", "human_reference_gate_a": "ref_gate_a"})
           .reset_index(drop=True))
    try:
        ga.validate_reference_inputs(cells, ref)   # frozen: 97 cases, 582 cells, paired arms, known values
    except ga.AnalysisInputError as e:
        raise ReproductionError(f"frozen input validation: {e}") from e
    return cells, ref, pub


def frozen_plan_order(cells: pd.DataFrame) -> pd.DataFrame:
    """Order cells as the frozen run recorded them: the seed-20260818 permutation of (case_id, arm, model).
    The case bootstrap resamples positions, so this order is part of the frozen contract."""
    plan = runner.ordered_plan(pd.DataFrame({"case_id": range(1, ga.N_REF + 1)}))
    pos = {k: i for i, k in enumerate(plan)}
    keys = list(zip(cells.case_id, cells.arm, cells.model))
    if set(keys) != set(pos) or len(keys) != len(pos):
        raise ReproductionError("cells do not match the frozen 582-cell plan")
    order = np.argsort([pos[k] for k in keys], kind="stable")
    return cells.iloc[order].reset_index(drop=True)


def recompute_correctness(cells: pd.DataFrame, ref: pd.DataFrame, pub: pd.DataFrame) -> pd.DataFrame:
    """Disposition and correctness from arm/status/gates/reference (frozen rule), never from `correct`;
    then assert agreement with the released `derived_disposition` and `correct` columns."""
    df = cells.merge(ref, on="case_id", how="left", validate="many_to_one")
    df["bl"] = [ga.derive_bottom_line(a, s, x, d) for a, s, x, d in zip(df.arm, df.status, df.gate_a, df.gate_d)]
    df["correct"] = (df.bl == df.ref_bottom_line).astype(int)
    rel = pub.rename(columns={"model_identifier": "model"})[["case_id", "arm", "model", "derived_disposition",
                                                               "correct"]]
    chk = df.merge(rel, on=["case_id", "arm", "model"], suffixes=("", "_released"), validate="one_to_one")
    if len(chk) != len(df) or (chk.bl != chk.derived_disposition).any() or (chk.correct != chk.correct_released).any():
        raise ReproductionError("recomputed disposition/correctness disagrees with the released cell columns")
    return df


def load_cascade(path: Path = BENCH / "cascade_labels.csv",
                 weights: Path = BENCH / "sampling_weights_observed.csv") -> pd.DataFrame:
    ec = pd.read_csv(path)
    missing = set(CASCADE_INPUT_COLUMNS) - set(ec.columns)
    if missing:
        raise ReproductionError(f"cascade labels missing columns {sorted(missing)}")
    if ec.duplicated(["nct_id", "pmid"]).any() or len(ec) != 97:
        raise ReproductionError("cascade labels must hold 97 unique nct_id x pmid cases")
    for col in ("system_P4", "system_P5"):
        if ec[col].dtype != bool:
            raise ReproductionError(f"{col} must be boolean")
    sw = pd.read_csv(weights)
    m = ec.merge(sw, on=["nct_id", "pmid"], how="left", validate="one_to_one")
    if m.inverse_probability_weight_mc.isna().any() or not np.allclose(
            m.inverse_probability_weight_mc, 1 / m.inclusion_probability_mc, rtol=1e-12):
        raise ReproductionError("observed weights missing or inconsistent with inclusion probabilities")
    return m


def assert_families_separate(all97: list, p4: list, n_p4: int) -> None:
    """The two denominator families are computed separately and never joined (no '83 -> 45')."""
    if p4[0] != n_p4 or all97[0] != 97 or p4[1] > all97[1] or p4[0] == all97[0]:
        raise ReproductionError(f"denominator families mixed: all-97 {all97}, P4 {p4}")
    if p4[0] == 83 and p4[1] == all97[1]:
        raise ReproductionError("forbidden mixed-family chain 83 -> all-case Gate-A count")


# --------------------------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------------------------
class Checks:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, check_id: str, area: str, computed, approved, source: str, rule: str = "exact equality"):
        computed, approved = json.loads(json.dumps(computed)), json.loads(json.dumps(approved))
        self.rows.append({"id": check_id, "area": area, "rule": rule, "approved_source": source,
                          "computed": computed, "approved": approved, "pass": computed == approved})


def pct(x: float) -> str:
    """Display rounding used by the manuscript tables (one decimal percentage)."""
    return f"{x * 100:.1f}"


def _perf_row(label: str, p: dict) -> list:
    ci = lambda m: f"{pct(p[m][0])} ({pct(p[m][1])}-{pct(p[m][2])})"  # noqa: E731
    return [label, str(p["TP"]), str(p["FP"]), str(p["FN"]), str(p["TN"]), ci("precision"), ci("recall"),
            ci("specificity"), ci("npv"), ci("accuracy"), f"{p['f1']:.3f}", f"{p['kappa']:.4f}"]


def g2_checks(chk: Checks, m: pd.DataFrame, ledger: dict) -> None:
    gold = (m.reference_final_label == "GENUINE_DISCREPANCY").to_numpy()
    P4, P5 = m.system_P4.to_numpy(bool), m.system_P5.to_numpy(bool)
    # Frozen Gate-A rule: PASS with reference_agreement provenance <=> both reviewers accepted the match.
    paper_ok = ((m.gate_a == "PASS") & (m.gate_a_provenance == "reference_agreement")).to_numpy()
    rows = {"P4 (stage-4 screen), all 97": g2.unweighted_metrics(P4, gold),
            "P5 (stage-5 classification), all 97": g2.unweighted_metrics(P5, gold),
            "P4, both reviewers accepted publication match": g2.unweighted_metrics(P4[paper_ok], gold[paper_ok])}
    t2 = pd.read_csv(DISPLAY / "table2_diagnostic_performance.csv", dtype=str)
    chk.add("G2-table2", "P4/P5 confusion counts, exact intervals, F1, kappa",
            [_perf_row(k, v) for k, v in rows.items()], t2.values.tolist(),
            "data/display_package/tables/table2_diagnostic_performance.csv", "exact equality at display precision")
    p4, p5, rp = rows.values()
    chk.add("G2-ledger", "P4/P5 claims", {
        "P4": {"TP": p4["TP"], "FP": p4["FP"], "FN": p4["FN"], "TN": p4["TN"],
               "precision": _perf_row("", p4)[5], "recall": _perf_row("", p4)[6]},
        "P5": {"flags": int(P5.sum()), "TP": p5["TP"], "precision": _perf_row("", p5)[5]},
        "right_paper": {"n": int(paper_ok.sum()), "P4_positive": int(P4[paper_ok].sum()), "TP": rp["TP"],
                        "precision": _perf_row("", rp)[5]},
        "reference": {"positive": int(gold.sum()), "negative": int((~gold).sum())},
        "sample": {"n": len(m), "P4_positive": int(P4.sum()), "P4_negative": int((~P4).sum()),
                   "P5_positive": int(P5.sum())}},
        {k: ledger[k] for k in ("P4", "P5", "right_paper", "reference", "sample")}, "reproduce/approved_values.json")

    w = m.inverse_probability_weight_mc.to_numpy(float)
    pi = m.inclusion_probability_mc.to_numpy(float)
    ess = float((w.sum() ** 2) / (w ** 2).sum())
    keys = ["precision", "recall", "specificity", "npv", "accuracy"]
    computed, invariant = [], True
    for q, flag in (("P4", P4), ("P5", P5)):
        # Hajek point estimates do not depend on the pairwise inclusion matrix (not distributed); compute with
        # two different matrices and require identical point estimates. Their variances are NOT reported.
        a = g2.weighted_metrics(flag, gold, w, pi, np.diag(pi))
        b = g2.weighted_metrics(flag, gold, w, pi, np.outer(pi, pi) + np.diag(pi - pi ** 2))
        invariant &= all(a[k] == b[k] for k in keys + ["TP_w", "FP_w", "FN_w", "TN_w"])
        computed.append([q] + [pct(a[k]) for k in keys] + [f"{ess:.1f}", "SUPPRESSED"])
    if not invariant:
        raise ReproductionError("weighted point estimates depended on the pairwise matrix")
    ws = pd.read_csv(DISPLAY / "table2_supplement_weighted.csv", dtype=str)
    chk.add("G2-weighted", "observed-weight Hajek point estimates and ESS", computed, ws.values.tolist(),
            "data/display_package/tables/table2_supplement_weighted.csv",
            "exact equality at display precision; weighted intervals suppressed as in the manuscript")
    chk.add("G2-weighted-ledger", "weighted claims",
            {"P4_precision": computed[0][1], "P5_precision": computed[1][1], "P4_recall": computed[0][2],
             "P5_recall": computed[1][2]}, ledger["weighted"], "reproduce/approved_values.json")


GATE_ROWS = {"A — publication identity": "gate_a", "B — outcome availability/extraction": "gate_b",
             "C — registry timing (raw textual)": "gate_c",
             "C — substantive vs wording interpretation": "gate_c_substantive",
             "D — outcome equivalence (latest-registry reference)": "gate_d_latest_reference",
             "D — target construct (collapsed reference)": "gate_d_target"}


def cascade_checks(chk: Checks, ec: pd.DataFrame, ledger: dict) -> None:
    t3 = pd.read_csv(DISPLAY / "table3_gate_distributions_attrition.csv")
    if set(t3.Gate) != set(GATE_ROWS):
        raise ReproductionError(f"unexpected Table 3 gate rows {sorted(set(t3.Gate))}")
    computed = [[g, c, int((ec[GATE_ROWS[g]] == c).sum())] for g, c in zip(t3.Gate, t3.Category)]
    chk.add("CAS-marginals", "unconditional gate distributions (all 97)", computed,
            t3[["Gate", "Category", "n (of 97)"]].values.tolist(),
            "data/display_package/tables/table3_gate_distributions_attrition.csv")
    for gate in GATE_ROWS.values():   # every category is displayed, so the table rows partition the 97
        shown = t3[t3.Gate.map(GATE_ROWS) == gate]["n (of 97)"].sum()
        if shown != 97:
            raise ReproductionError(f"Table 3 rows for {gate} sum to {shown}, not 97")

    def chain(c: pd.DataFrame) -> list:
        p = bec.compute_panels(c)
        r, s = p["sequential_raw_textual_gate_c"], p["sequential_substantive_gate_c"]
        if s["1_gate_a_pass"] != r["1_gate_a_pass"] or s["2_and_gate_b_pass"] != r["2_and_gate_b_pass"]:
            raise ReproductionError("raw and substantive chains disagree before Gate C")
        if r["4_and_gate_d_target_material"] != s["4_and_gate_d_target_material"]:
            raise ReproductionError("raw and substantive terminal counts disagree")
        return [r["n_total"], r["1_gate_a_pass"], r["2_and_gate_b_pass"], r["3_and_gate_c_concordant"],
                s["3_and_gate_c_effective_concordant"], r["4_and_gate_d_target_material"]]

    all97 = chain(ec)
    p4 = chain(ec[ec.system_P4])          # the P4 family is computed inside the P4-positive subset only
    assert_families_separate(all97, p4, int(ec.system_P4.sum()))
    den = pd.read_csv(RELEASE / "cascade_denominators.csv")
    cols = ["start", "gate_a_pass", "gate_b_pass", "gate_c_pass_raw", "gate_c_pass_substantive", "target_material"]
    chk.add("CAS-nested", "nested cascade, two separate denominator families",
            {"all_97": all97, "p4_nested_83": p4},
            {f: den.loc[den.family == f, cols].iloc[0].astype(int).tolist() for f in ("all_97", "p4_nested_83")},
            "data/signed_release/cascade_denominators.csv")
    nest = pd.read_csv(DISPLAY / "table3_nested_attrition.csv")
    chk.add("CAS-nested-display", "nested attrition display table", [all97, p4],
            nest.iloc[:, 1:].astype(int).values.tolist(), "data/display_package/tables/table3_nested_attrition.csv")

    panel = ec[(ec.gate_a == "PASS") & (ec.gate_b == "PASS")]
    dist = bec.compute_panels(ec)["gate_d_element_panel_primary"]["element_distributions"]
    s3 = pd.read_csv(DISPLAY / "table_s3_gate_d_element_distribution.csv")
    parse = lambda s: {kv.rsplit(" ", 1)[0]: int(kv.rsplit(" ", 1)[1]) for kv in s.split(", ")}  # noqa: E731
    chk.add("CAS-D-elements", "Gate-D element distributions in the fixed 30-case panel",
            {e: {k: int(v) for k, v in dist["gate_d_latest_" + e].items()} for e in ELEMENTS},
            {e: parse(s) for e, s in zip(s3.iloc[:, 0], s3.iloc[:, 1])},
            "data/display_package/tables/table_s3_gate_d_element_distribution.csv")
    ref_m = panel.gate_d_latest_reference == "MATERIAL_CHANGE"
    el_m = panel.gate_d_latest_elements_material == "MATERIAL_CHANGE"
    if not (panel.gate_d_latest_reference.isin(["MATERIAL_CHANGE", "NO_MATERIAL_CHANGE"]).all()
            and panel.gate_d_latest_elements_material.isin(["MATERIAL_CHANGE", "NO_MATERIAL_CHANGE"]).all()):
        raise ReproductionError("30-case panel has a non-binary reference or element flag")
    xt = [[int((ref_m & el_m).sum()), int((ref_m & ~el_m).sum())], [int((~ref_m & el_m).sum()), int((~ref_m & ~el_m).sum())]]
    s3x = pd.read_csv(DISPLAY / "table_s3_gate_d_reference_crosstab.csv")
    chk.add("CAS-D-crosstab", "reference vs element-derived material flag (30-case panel)", xt,
            s3x.iloc[:, 1:3].astype(int).values.tolist(), "data/display_package/tables/table_s3_gate_d_reference_crosstab.csv")
    gc = ec.gate_c_substantive.value_counts().to_dict()
    chk.add("CAS-ledger", "cascade claims", {
        "gate_a": {k: int((ec.gate_a == k).sum()) for k in ("PASS", "FAIL", "UNASSESSABLE")},
        "gate_b": {k: int((ec.gate_b == k).sum()) for k in ("PASS", "NO_PRIMARY_IN_ABSTRACT", "FAIL")},
        "gate_c_raw_differences": {"DIFFERS_FROM_PROSPECTIVE": int((ec.gate_c == "DIFFERS_FROM_PROSPECTIVE").sum()),
                                   **{k: int(gc.get(k, 0)) for k in ("SUBSTANTIVE_CHANGE", "WORDING_ONLY", "UNCLEAR")}},
        "nested_all97": all97, "nested_p4": p4,
        "identity_attrition": {"did_not_pass_identity": p4[0] - p4[1], "of": p4[0]},
        "d_panel": {"n": len(panel), "reference_material": int(ref_m.sum()), "reference_nonmaterial": int((~ref_m).sum()),
                    "element_material": int(el_m.sum()), "element_nonmaterial": int((~el_m).sum()),
                    "crosstab": [xt[0][0], xt[0][1], xt[1][0], xt[1][1]]}},
        {k: ledger[k] for k in ("gate_a", "gate_b", "gate_c_raw_differences", "nested_all97", "nested_p4",
                                "identity_attrition", "d_panel")}, "reproduce/approved_values.json")


def g5_checks(chk: Checks, ledger: dict) -> dict:
    cells, ref, pub = load_public_cells()
    df = recompute_correctness(cells, ref, pub)
    status = cells.groupby("model").status.value_counts().unstack(fill_value=0)
    invalid = cells[cells.status != "OK"]
    chk.add("G5-completeness", "582 cells; every invalid response retained", {
        "cells": len(cells), "transport": int((cells.status == "TRANSPORT_FAIL").sum()),
        "schema": int((cells.status == "SCHEMA_FAIL").sum()), "semantic": int((cells.status == "SEMANTIC_FAIL").sum()),
        "invalid_total": len(invalid),
        "invalid_by_model": {mdl: int(status.loc[mdl].drop("OK", errors="ignore").sum()) for mdl in ga.MODEL_ALIASES}},
        ledger["g5_completeness"], "reproduce/approved_values.json")
    ordered = frozen_plan_order(cells)
    an = ga.run_reference_analysis(ordered, ref)          # frozen analysis, seed 20260818, 10,000 draws
    tables = {"primary_effects": g5r.table_primary_effects(an),
              "mechanism_by_human_gate_a": g5r.table_mechanism_by_human_gate_a(df),
              "gate_a_and_conditional_d": g5r.table_gate_a_and_conditional_d(an),
              "status_coverage": g5r.table_status_coverage(df, an),
              "wrong_paper_arm2_responses": g5r.table_wrong_paper_arm2_responses(df)}
    for name in G5_TABLES:
        released = (BENCH / f"g5_{name}.csv").read_bytes()
        chk.add(f"G5-{name}", f"regenerated G5 table {name}", hashlib.sha256(tables[name].to_csv(index=False).encode()).hexdigest(),
                hashlib.sha256(released).hexdigest(), f"data/signed_release/benchmark/g5_{name}.csv",
                "byte-identical CSV (sha256)")
    sc = tables["status_coverage"]
    s4a = pd.read_csv(DISPLAY / "table_s4_g5_status_coverage.csv", dtype=str)
    chk.add("G5-S4A", "status and determinate coverage display table",
            [[r.model, str(r.arm), str(r.n), str(r.OK), str(r.SCHEMA_FAIL), str(r.SEMANTIC_FAIL), str(r.TRANSPORT_FAIL),
              str(r.content_failures), f"{pct(r.determinate_coverage)}%"] for r in sc.itertuples()],
            s4a.values.tolist(), "data/display_package/tables/table_s4_g5_status_coverage.csv")
    wp = tables["wrong_paper_arm2_responses"]
    s4b = pd.read_csv(DISPLAY / "table_s4b_g5_wrong_paper_arm2_responses.csv")
    chk.add("G5-S4B", "wrong-paper Arm-2 response composition display table",
            [[r.model, int(r.valid_material_change), int(r.valid_no_material_change), int(r.valid_unassessable),
              int(r.invalid), int(r.n_cases)] for r in wp.itertuples()],
            s4b.values.tolist(), "data/display_package/tables/table_s4b_g5_wrong_paper_arm2_responses.csv")
    pe = {r["model"]: r for r in an["primary_contrast_arm1_vs_arm2"]}
    mech = tables["mechanism_by_human_gate_a"]
    eff = lambda r: (f"{r['paired_diff_arm1_minus_arm2'] * 100:+.1f} ({pct(r['diff_ci95_bootstrap'][0])}-"  # noqa: E731
                     f"{pct(r['diff_ci95_bootstrap'][1])})")
    stratum = lambda mdl, s: f"{mech[(mech.model == mdl) & (mech.human_reference_gate_a == s)].diff_arm1_minus_arm2.iloc[0] * 100:+.1f}"  # noqa: E731,E501
    chk.add("G5-ledger", "G5 effect, mechanism, coverage and wrong-paper claims", {
        "effects": {mdl: {"arm1": pe[mdl]["arm1_correct"], "arm2": pe[mdl]["arm2_correct"], "diff": eff(pe[mdl])}
                    for mdl in ga.MODEL_ALIASES},
        "mechanism": {"wrong_paper": {mdl: stratum(mdl, "WRONG_PAPER") for mdl in ga.MODEL_ALIASES},
                      "right_paper": {mdl: stratum(mdl, "RIGHT_PAPER") for mdl in ga.MODEL_ALIASES},
                      "strata_n": {s: int(mech[mech.human_reference_gate_a == s].n_cases.iloc[0])
                                   for s in ("WRONG_PAPER", "RIGHT_PAPER", "UNASSESSABLE")}},
        "coverage": {mdl: [pct(sc[(sc.model == mdl) & (sc.arm == a)].determinate_coverage.iloc[0]) for a in (1, 2)]
                     for mdl in ga.MODEL_ALIASES},
        "wrong_paper_arm2": {r.model: [int(r.valid_material_change), int(r.valid_no_material_change),
                                       int(r.valid_unassessable), int(r.invalid)] for r in wp.itertuples()},
        "wrong_paper_unassessable_or_invalid": {r.model: int(r.valid_unassessable + r.invalid) for r in wp.itertuples()}},
        {k: ledger[k] for k in ("effects", "mechanism", "coverage", "wrong_paper_arm2",
                                "wrong_paper_unassessable_or_invalid")}, "reproduce/approved_values.json")
    # Informational: the interval depends on the frozen cell order (documented, not a pass/fail check).
    by_case = ga.paired_contrast(cells.sort_values(["model", "arm", "case_id"]).reset_index(drop=True), ref)
    return {"bootstrap_order_note": {
        r["model"]: {"frozen_plan_order_ci": pe[r["model"]]["diff_ci95_bootstrap"],
                     "case_id_order_ci": r["diff_ci95_bootstrap"]} for r in by_case}}


def run_all(out: Path | None = None) -> dict:
    verify_inputs()
    ledger = json.loads(APPROVED.read_text())["values"]
    chk = Checks()
    m = load_cascade()
    g2_checks(chk, m, ledger)
    cascade_checks(chk, m, ledger)
    notes = g5_checks(chk, ledger)
    report = {
        "snapshot": json.loads(MANIFEST.read_text())["snapshot"],
        "summary": {"checks": len(chk.rows), "passed": sum(r["pass"] for r in chk.rows),
                    "failed": [r["id"] for r in chk.rows if not r["pass"]]},
        "checks": chk.rows, "notes": notes,
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                        "scipy": __import__("scipy").__version__},
    }
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "reproduction_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "reproduction_output")
    args = ap.parse_args()
    try:
        report = run_all(args.out)
    except ReproductionError as e:
        print(f"REPRODUCTION REFUSED: {e}", file=sys.stderr)
        return 2
    s = report["summary"]
    for r in report["checks"]:
        print(f"{'PASS' if r['pass'] else 'FAIL'}  {r['id']:28s} {r['area']}")
    print(f"\n{s['passed']}/{s['checks']} checks passed; report: {args.out / 'reproduction_report.json'}")
    return 0 if not s["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

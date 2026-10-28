#!/usr/bin/env python3
"""G5 — FROZEN prespecified analysis for the two-arm ablation (plan §3; appendix §5/§6).

Prespecified BEFORE the reference results exist and validated on synthetic data
(tests/test_g5_analysis.py). Pure functions operate on a per-cell table
(case_id, arm, model, status, gate_a, gate_d) plus a per-case human-reference table
(case_id, ref_bottom_line, ref_gate_a). Descriptive only — no p-values (plan §7.2).

Implements the second-audit contract (P0-G):
  - §6 hierarchical panel consensus (Gate A THEN Gate D from the RIGHT_PAPER voters only);
    emits gate_a_consensus / gate_d_consensus / bottom_line per case. Never majority-votes
    collapsed bottom lines.
  - Per model/arm over all 97: correctness + precision, recall/sensitivity, specificity,
    balanced accuracy, binary kappa, determinate denominator + coverage; safe zero denominators.
  - Gate-A PRIMARY agreement is BINARY (model WRONG_PAPER vs human wrong-paper) with abstention
    coverage; a ternary view is supplementary only.
  - Conditional Gate-D (human right-paper cases) + false-Gate-A-rejection sensitivity, with
    explicit eligibility denominators.
  - Inter-model agreement, case-level panel table, panel NO_CONSENSUS coverage, panel scoring
    vs the adjudicated reference. Failures/abstentions are no-vote / not-correct, never negative.
  - Strict input validation for the reference analysis: exactly 97 unique reference cases with
    known labels and exactly 582 unique terminal case×arm×model cells; duplicates / missing /
    unknown / missing paired arms are errors (no aggfunc='first', no silent dropna).

Positive class = GENUINE_DISCREPANCY (7 reference positives — estimates are fragile).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys as _sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

_sys.path.insert(0, str(Path(__file__).resolve().parent))
import g5_run_ablation as runner  # reuse the runner's strict journal validation (single source of truth)

BOOTSTRAP_SEED = 20260818
N_BOOT = 10000
POS = "GENUINE_DISCREPANCY"
NEG = "NO_DISCREPANCY"
DETERMINATE = {POS, NEG}
N_REF = 97
ARMS = (1, 2)
N_MODELS = 3
N_CELLS = N_REF * len(ARMS) * N_MODELS  # 582


class AnalysisInputError(Exception):
    """Malformed/incomplete analysis input — never silently tolerated."""


def _safe_div(n, d):
    return (n / d) if d else None


# --------------------------------------------------------------------------- mapping (appendix §5)

def map_gate_d_bottom(gate_d) -> str:
    return {"MATERIAL_CHANGE": POS, "NO_MATERIAL_CHANGE": NEG, "UNASSESSABLE": "AMBIGUOUS"}.get(gate_d, "INDETERMINATE")


def derive_bottom_line(arm: int, status: str, gate_a, gate_d) -> str:
    """One cell -> bottom line. Non-OK -> INDETERMINATE (never silently NO_DISCREPANCY)."""
    if status != "OK":
        return "INDETERMINATE"
    if arm == 1:
        if gate_a == "WRONG_PAPER":
            return NEG
        if gate_a == "UNASSESSABLE":
            return "AMBIGUOUS"
        if gate_a == "RIGHT_PAPER":
            return map_gate_d_bottom(gate_d)
        return "INDETERMINATE"
    return map_gate_d_bottom(gate_d)


def cohen_kappa(a, b) -> float | None:
    a, b = np.array(a), np.array(b)
    if len(a) == 0:
        return None
    labels = sorted(set(a) | set(b))
    po = float((a == b).mean())
    pe = sum(np.mean(a == l) * np.mean(b == l) for l in labels)
    return None if pe == 1 else float((po - pe) / (1 - pe))


# --------------------------------------------------------------------------- per model/arm metrics

def model_arm_metrics(cells: pd.DataFrame, ref: pd.DataFrame) -> list[dict]:
    df = cells.merge(ref, on="case_id", how="left")
    df["bl"] = [derive_bottom_line(a, s, ga, gd) for a, s, ga, gd in zip(df.arm, df.status, df.gate_a, df.gate_d)]
    out = []
    for (model, arm), g in df.groupby(["model", "arm"]):
        n = len(g)
        det = g[g.bl.isin(DETERMINATE)]
        correct_all = int((g.bl == g.ref_bottom_line).sum())  # abstain/indeterminate never match POS/NEG
        # binary metrics among DETERMINATE predictions (positive = POS)
        tp = int(((det.bl == POS) & (det.ref_bottom_line == POS)).sum())
        fp = int(((det.bl == POS) & (det.ref_bottom_line == NEG)).sum())
        tn = int(((det.bl == NEG) & (det.ref_bottom_line == NEG)).sum())
        fn = int(((det.bl == NEG) & (det.ref_bottom_line == POS)).sum())
        sens = _safe_div(tp, tp + fn)
        spec = _safe_div(tn, tn + fp)
        bal_acc = (None if sens is None or spec is None else (sens + spec) / 2)
        out.append({
            "model": model, "arm": int(arm), "n": n, "n_determinate": len(det),
            "coverage": _safe_div(len(det), n), "correctness_all97": _safe_div(correct_all, n),
            "TP": tp, "FP": fp, "TN": tn, "FN": fn,
            "precision": _safe_div(tp, tp + fp), "recall_sensitivity": sens, "specificity": spec,
            "balanced_accuracy": bal_acc,
            "kappa_determinate": cohen_kappa(list(det.bl), list(det.ref_bottom_line)) if len(det) else None,
        })
    return out


# --------------------------------------------------------------------------- PRIMARY contrast Arm1 vs Arm2

def paired_contrast(cells: pd.DataFrame, ref: pd.DataFrame, n_boot: int = N_BOOT) -> list[dict]:
    df = cells.merge(ref, on="case_id", how="left")
    df["bl"] = [derive_bottom_line(a, s, ga, gd) for a, s, ga, gd in zip(df.arm, df.status, df.gate_a, df.gate_d)]
    df["correct"] = (df.bl == df.ref_bottom_line).astype(int)
    out = []
    for model, g in df.groupby("model"):
        a1 = g[g.arm == 1].set_index("case_id")["correct"]
        a2 = g[g.arm == 2].set_index("case_id")["correct"]
        common = a1.index.intersection(a2.index)
        if len(common) != len(a1) or len(common) != len(a2):
            raise AnalysisInputError(f"{model}: arms not paired on identical case sets")
        v1, v2 = a1.loc[common].to_numpy(), a2.loc[common].to_numpy()
        trans = {"a1_correct_a2_correct": int(((v1 == 1) & (v2 == 1)).sum()),
                 "a1_correct_a2_incorrect": int(((v1 == 1) & (v2 == 0)).sum()),
                 "a1_incorrect_a2_correct": int(((v1 == 0) & (v2 == 1)).sum()),
                 "a1_incorrect_a2_incorrect": int(((v1 == 0) & (v2 == 0)).sum())}
        diff = v1 - v2
        rng = np.random.RandomState(BOOTSTRAP_SEED)
        boot = diff[rng.randint(0, len(diff), size=(n_boot, len(diff)))].mean(axis=1)
        # case-level paired records + stratification by the Arm-1 Gate-A disposition driving the change
        g1 = g[g.arm == 1].set_index("case_id")
        records, strat = [], {}
        for cid in common:
            c1, c2 = int(a1.loc[cid]), int(a2.loc[cid])
            change = ("improved" if (c1, c2) == (1, 0) else "regressed" if (c1, c2) == (0, 1) else "unchanged")
            disp = g1.loc[cid, "gate_a"] if cid in g1.index else None
            records.append({"case_id": int(cid), "arm1_correct": c1, "arm2_correct": c2,
                            "change": change, "arm1_gate_a": disp})
            strat.setdefault(disp, {"improved": 0, "regressed": 0, "unchanged": 0})[change] += 1
        out.append({"model": model, "n_paired": int(len(common)),
                    "arm1_correct": int(v1.sum()), "arm2_correct": int(v2.sum()),
                    "paired_diff_arm1_minus_arm2": float(diff.mean()),
                    "diff_ci95_bootstrap": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                    "transition_table": trans,
                    "improved_regressed_unchanged": {
                        "improved": int((diff == 1).sum()), "regressed": int((diff == -1).sum()),
                        "unchanged": int((diff == 0).sum())},
                    "stratified_by_arm1_gate_a": strat, "case_level_records": records})
    return out


# --------------------------------------------------------------------------- Gate-A agreement (binary primary)

def gate_a_agreement(cells: pd.DataFrame, ref: pd.DataFrame) -> list[dict]:
    """PRIMARY binary Gate-A agreement (P0-J item 10). Human eligibility = ref_gate_a in
    {RIGHT_PAPER, WRONG_PAPER}. Within eligible cases, a model is determinate only if status OK AND
    gate_a in {RIGHT_PAPER, WRONG_PAPER}; model UNASSESSABLE/failure is an ABSTENTION (not a
    not-wrong vote) and reduces coverage. Reports totals, coverage-among-eligible, confusion, κ.
    A ternary view is supplementary with its own denominator."""
    df = cells[cells.arm == 1].merge(ref, on="case_id", how="left")
    out = []
    for model, g in df.groupby("model"):
        total = len(g)
        eligible = g[g.ref_gate_a.isin(["RIGHT_PAPER", "WRONG_PAPER"])]
        determinate = eligible[(eligible.status == "OK") & eligible.gate_a.isin(["RIGHT_PAPER", "WRONG_PAPER"])]
        pred_wrong = (determinate.gate_a == "WRONG_PAPER").astype(int).to_numpy()
        ref_wrong = (determinate.ref_gate_a == "WRONG_PAPER").astype(int).to_numpy()
        conf = {"tp_wrong_wrong": int(((pred_wrong == 1) & (ref_wrong == 1)).sum()),
                "fp_wrong_right": int(((pred_wrong == 1) & (ref_wrong == 0)).sum()),
                "fn_right_wrong": int(((pred_wrong == 0) & (ref_wrong == 1)).sum()),
                "tn_right_right": int(((pred_wrong == 0) & (ref_wrong == 0)).sum())}
        binary = {"n_total": total, "n_human_eligible": int(len(eligible)),
                  "n_model_determinate": int(len(determinate)),
                  "coverage_among_eligible": _safe_div(len(determinate), len(eligible)),
                  "raw_agreement": _safe_div(int((pred_wrong == ref_wrong).sum()), len(determinate)),
                  "confusion": conf,
                  "kappa": cohen_kappa(list(pred_wrong), list(ref_wrong)) if len(determinate) else None}
        # SUPPLEMENTARY genuine ternary (item 11): human eligibility now INCLUDES UNASSESSABLE, and a model
        # UNASSESSABLE is a real third category (own eligibility/coverage). Does not alter the binary primary.
        tern_elig = g[g.ref_gate_a.isin(["RIGHT_PAPER", "WRONG_PAPER", "UNASSESSABLE"])]
        tern_det = tern_elig[(tern_elig.status == "OK")
                             & tern_elig.gate_a.isin(["RIGHT_PAPER", "WRONG_PAPER", "UNASSESSABLE"])]
        supp = {"n_human_eligible_ternary": int(len(tern_elig)), "n_model_determinate_ternary": int(len(tern_det)),
                "coverage_among_eligible": _safe_div(len(tern_det), len(tern_elig)),
                "raw_agreement": _safe_div(int((tern_det.gate_a == tern_det.ref_gate_a).sum()), len(tern_det)),
                "kappa_ternary": cohen_kappa(list(tern_det.gate_a), list(tern_det.ref_gate_a)) if len(tern_det) else None}
        out.append({"model": model, "primary_binary_wrong_paper": binary, "supplementary_ternary": supp})
    return out


def panel_gate_a_consensus_agreement(cells: pd.DataFrame, ref: pd.DataFrame) -> dict:
    """Plan §3: panel Gate-A CONSENSUS (Arm 1) vs eligible human Gate A (binary wrong-paper)."""
    panel = panel_table(cells[cells.arm == 1]).merge(ref, on="case_id", how="left")
    elig = panel[panel.ref_gate_a.isin(["RIGHT_PAPER", "WRONG_PAPER"])]
    det = elig[elig.gate_a_consensus.isin(["RIGHT_PAPER", "WRONG_PAPER"])]
    pw = (det.gate_a_consensus == "WRONG_PAPER").astype(int).to_numpy()
    rw = (det.ref_gate_a == "WRONG_PAPER").astype(int).to_numpy()
    return {"n_human_eligible": int(len(elig)), "n_panel_determinate": int(len(det)),
            "coverage_among_eligible": _safe_div(len(det), len(elig)),
            "raw_agreement": _safe_div(int((pw == rw).sum()), len(det)),
            "confusion": {"tp": int(((pw == 1) & (rw == 1)).sum()), "fp": int(((pw == 1) & (rw == 0)).sum()),
                          "fn": int(((pw == 0) & (rw == 1)).sum()), "tn": int(((pw == 0) & (rw == 0)).sum())},
            "kappa": cohen_kappa(list(pw), list(rw)) if len(det) else None}


def conditional_gate_d(cells: pd.DataFrame, ref: pd.DataFrame) -> list[dict]:
    """Among HUMAN right-paper cases: (a) conditional Gate-D agreement where the model produced a
    determinate Gate-D judgment; (b) sensitivity counting a false Gate-A rejection (model WRONG_PAPER
    on a human right-paper case) as incorrect. Explicit eligibility denominators."""
    df = cells.merge(ref, on="case_id", how="left")
    df["bl"] = [derive_bottom_line(a, s, ga, gd) for a, s, ga, gd in zip(df.arm, df.status, df.gate_a, df.gate_d)]
    right = df[df.ref_gate_a == "RIGHT_PAPER"]
    out = []
    for (model, arm), g in right.groupby(["model", "arm"]):
        arm = int(arm)
        # Conditional eligibility (P0-J item 11): Arm 1 requires status OK, model Gate A=RIGHT_PAPER, and
        # Gate D in {MATERIAL, NO_MATERIAL}; Arm 2 requires a determinate Gate D. A false WRONG_PAPER /
        # UNASSESSABLE / failure does NOT enter the conditional denominator — it is not a Gate-D verdict.
        if arm == 1:
            eligible = g[(g.status == "OK") & (g.gate_a == "RIGHT_PAPER")
                         & g.gate_d.isin(["MATERIAL_CHANGE", "NO_MATERIAL_CHANGE"])]
        else:
            eligible = g[(g.status == "OK") & g.gate_d.isin(["MATERIAL_CHANGE", "NO_MATERIAL_CHANGE"])]
        cond_correct = int((eligible.bl == eligible.ref_bottom_line).sum())
        # Separate all-human-right-paper sensitivity: Arm-1 false WRONG_PAPER, UNASSESSABLE, failure, and
        # indeterminate Gate D all count as INCORRECT (a false rejection is an error even if the collapsed
        # bottom line coincidentally matches).
        if arm == 1:
            sens_ok = (g.status == "OK") & (g.gate_a == "RIGHT_PAPER") & g.bl.isin(DETERMINATE) & (g.bl == g.ref_bottom_line)
        else:
            sens_ok = (g.status == "OK") & g.bl.isin(DETERMINATE) & (g.bl == g.ref_bottom_line)
        out.append({"model": model, "arm": arm,
                    "n_human_right_paper": int(len(g)),
                    "conditional_n_eligible": int(len(eligible)),
                    "conditional_correctness": _safe_div(cond_correct, len(eligible)),
                    "sensitivity_denom_all_human_right_paper": int(len(g)),
                    "correctness_counting_false_reject_as_incorrect": _safe_div(int(sens_ok.sum()), len(g))})
    return out


# --------------------------------------------------------------------------- hierarchical panel consensus (§6)

def _majority(votes: list[str]) -> str | None:
    if not votes:
        return None
    vc = pd.Series(votes).value_counts()
    return vc.index[0] if vc.iloc[0] >= 2 else None


def panel_consensus_case(arm: int, rows: pd.DataFrame) -> dict:
    """Hierarchical rule (§6) for one (case, arm). rows = the up-to-3 model rows.
    Failed/invalid calls supply no vote. Returns gate_a_consensus/gate_d_consensus/bottom_line."""
    ok = rows[rows.status == "OK"]
    if arm == 1:
        a_votes = [g for g in ok.gate_a if g in ("RIGHT_PAPER", "WRONG_PAPER", "UNASSESSABLE")]
        a_cons = _majority(a_votes)
        if a_cons is None:
            return {"gate_a_consensus": "NO_CONSENSUS", "gate_d_consensus": "NO_CONSENSUS", "bottom_line": "NO_CONSENSUS"}
        if a_cons == "WRONG_PAPER":
            return {"gate_a_consensus": "WRONG_PAPER", "gate_d_consensus": "NOT_EVALUATED_UPSTREAM_FAILURE", "bottom_line": NEG}
        if a_cons == "UNASSESSABLE":
            return {"gate_a_consensus": "UNASSESSABLE", "gate_d_consensus": "NOT_EVALUATED_UPSTREAM_FAILURE", "bottom_line": "AMBIGUOUS"}
        # RIGHT_PAPER: Gate-D consensus from ONLY the models that individually returned RIGHT_PAPER
        d_votes = [gd for ga, gd in zip(ok.gate_a, ok.gate_d)
                   if ga == "RIGHT_PAPER" and gd in ("MATERIAL_CHANGE", "NO_MATERIAL_CHANGE", "UNASSESSABLE")]
        d_cons = _majority(d_votes)
        if d_cons is None:
            return {"gate_a_consensus": "RIGHT_PAPER", "gate_d_consensus": "NO_CONSENSUS", "bottom_line": "NO_CONSENSUS"}
        return {"gate_a_consensus": "RIGHT_PAPER", "gate_d_consensus": d_cons, "bottom_line": map_gate_d_bottom(d_cons)}
    # arm 2: Gate-D only
    d_votes = [gd for gd in ok.gate_d if gd in ("MATERIAL_CHANGE", "NO_MATERIAL_CHANGE", "UNASSESSABLE")]
    d_cons = _majority(d_votes)
    if d_cons is None:
        return {"gate_a_consensus": "NOT_APPLICABLE", "gate_d_consensus": "NO_CONSENSUS", "bottom_line": "NO_CONSENSUS"}
    return {"gate_a_consensus": "NOT_APPLICABLE", "gate_d_consensus": d_cons, "bottom_line": map_gate_d_bottom(d_cons)}


def panel_table(cells: pd.DataFrame) -> pd.DataFrame:
    """Case-level panel table: one row per (case, arm) with the hierarchical consensus fields."""
    rows = []
    for (case_id, arm), g in cells.groupby(["case_id", "arm"]):
        rows.append({"case_id": case_id, "arm": int(arm), **panel_consensus_case(arm, g)})
    return pd.DataFrame(rows)


def panel_scoring(panel: pd.DataFrame, ref: pd.DataFrame) -> list[dict]:
    """Score panel bottom line vs the adjudicated reference, per arm. NO_CONSENSUS/AMBIGUOUS = not correct;
    report determinate coverage."""
    df = panel.merge(ref, on="case_id", how="left")
    out = []
    for arm, g in df.groupby("arm"):
        n = len(g)
        det = g[g.bottom_line.isin(DETERMINATE)]
        tp = int(((det.bottom_line == POS) & (det.ref_bottom_line == POS)).sum())
        fp = int(((det.bottom_line == POS) & (det.ref_bottom_line == NEG)).sum())
        fn_all = int(((g.bottom_line != POS) & (g.ref_bottom_line == POS)).sum())
        out.append({"arm": int(arm), "n": n, "no_consensus_rate": _safe_div(int((g.bottom_line == "NO_CONSENSUS").sum()), n),
                    "coverage_determinate": _safe_div(len(det), n),
                    "correctness_all": _safe_div(int((g.bottom_line == g.ref_bottom_line).sum()), n),
                    "precision": _safe_div(tp, tp + fp), "recall_over_all_positives": _safe_div(tp, tp + fn_all)})
    return out


def inter_model_agreement(cells: pd.DataFrame) -> list[dict]:
    df = cells.copy()
    df["bl"] = [derive_bottom_line(a, s, ga, gd) for a, s, ga, gd in zip(df.arm, df.status, df.gate_a, df.gate_d)]
    out = []
    for arm, g in df.groupby("arm"):
        piv = g.pivot(index="case_id", columns="model", values="bl")
        for m1, m2 in combinations(sorted(piv.columns), 2):
            pair = piv[[m1, m2]].dropna()
            det = pair[pair[m1].isin(DETERMINATE) & pair[m2].isin(DETERMINATE)]
            out.append({"arm": int(arm), "model_a": m1, "model_b": m2, "n_cases": int(len(pair)),
                        "n_determinate_both": int(len(det)),
                        "coverage_both_determinate": _safe_div(len(det), len(pair)),
                        "raw_agreement": _safe_div(int((det[m1] == det[m2]).sum()), len(det)),
                        "kappa": cohen_kappa(list(det[m1]), list(det[m2])) if len(det) else None})
    return out


# --------------------------------------------------------------------------- strict validation + IO

MODEL_ALIASES = ("claude-opus-4.6", "gemini-3.1-pro-preview", "gpt-5.4")
ALLOWED_STATUS = {"OK", "PARSE_FAIL", "SCHEMA_FAIL", "SEMANTIC_FAIL", "TRANSPORT_FAIL"}
ALLOWED_GATE_A = {"RIGHT_PAPER", "WRONG_PAPER", "UNASSESSABLE", None}
ALLOWED_GATE_D = {"MATERIAL_CHANGE", "NO_MATERIAL_CHANGE", "UNASSESSABLE", None}


def validate_reference_inputs(cells: pd.DataFrame, ref: pd.DataFrame) -> None:
    if ref.case_id.nunique() != N_REF or len(ref) != N_REF:
        raise AnalysisInputError(f"reference must have exactly {N_REF} unique cases, got {len(ref)}/{ref.case_id.nunique()}")
    bad = set(ref.ref_bottom_line) - DETERMINATE
    if bad:
        raise AnalysisInputError(f"reference labels must be in {DETERMINATE}; found {bad}")
    keys = list(zip(cells.case_id, cells.arm, cells.model))
    if len(keys) != len(set(keys)):
        raise AnalysisInputError("duplicate terminal case×arm×model cells")
    if len(cells) != N_CELLS:
        raise AnalysisInputError(f"expected exactly {N_CELLS} terminal cells, got {len(cells)}")
    if set(cells.arm.unique()) != set(ARMS):
        raise AnalysisInputError(f"arms must be exactly {ARMS}")
    if set(cells.model.unique()) != set(MODEL_ALIASES):
        raise AnalysisInputError(f"models must be exactly {MODEL_ALIASES}; got {sorted(cells.model.unique())}")
    if not set(cells.status.unique()) <= ALLOWED_STATUS:
        raise AnalysisInputError(f"unknown status(es): {set(cells.status.unique()) - ALLOWED_STATUS}")
    if not set(cells.gate_a.dropna().unique()) <= (ALLOWED_GATE_A - {None}):
        raise AnalysisInputError("invalid gate_a value(s)")
    if not set(cells.gate_d.dropna().unique()) <= (ALLOWED_GATE_D - {None}):
        raise AnalysisInputError("invalid gate_d value(s)")
    unknown = set(cells.case_id) - set(ref.case_id)
    if unknown:
        raise AnalysisInputError(f"cells reference unknown cases: {sorted(unknown)[:5]}")
    per = cells.groupby("case_id").size()  # every case must have both arms × all models
    if not (per == len(ARMS) * N_MODELS).all():
        raise AnalysisInputError("some case is missing an arm×model cell")


def cells_from_attempts(attempts_path: Path, valid_keys: set | None = None) -> pd.DataFrame:
    """Terminal cell per key via the runner's STRICT journal validation (single source of truth):
    sequence/status/prompt-hash checks + duplicate-terminal + torn/corrupt-line rejection."""
    try:
        terminal_keys, _ = runner.scan_journal(attempts_path, valid_keys=valid_keys)
    except runner.JournalIntegrityError as e:
        raise AnalysisInputError(f"journal integrity: {e}")
    recs = [{"case_id": k[0], "arm": k[1], "model": k[2], "status": t["status"],
             "gate_a": (t.get("parsed") or {}).get("gate_a"), "gate_d": (t.get("parsed") or {}).get("gate_d")}
            for k, t in terminal_keys.items()]
    return pd.DataFrame(recs)


def _sha_text(p: Path) -> str:
    return hashlib.sha256(p.read_text().encode()).hexdigest() if p.exists() else "MISSING"


def _sha_json(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def verify_run_chain(run_dir: Path) -> dict:
    """P0-M items 8/9: verify the full integrity chain BEFORE analysis parses anything. Reject changed/
    missing completion.json, journal, reference extract, run manifest/digest, analysis script, unknown
    prompt hash, or any incomplete/torn/corrupt attempt stream. Returns verified provenance."""
    comp_p, man_p = run_dir / "completion.json", run_dir / "manifest.json"
    attempts, extract = run_dir / "attempts.jsonl", run_dir / "g5_reference_extract.csv"
    for p in (comp_p, man_p, attempts, extract):
        if not p.exists():
            raise AnalysisInputError(f"reference analysis requires {p.name} — missing")
    comp, man = json.loads(comp_p.read_text()), json.loads(man_p.read_text())
    problems = []
    if comp.get("run_id") != run_dir.name:
        problems.append("completion.run_id != run dir")
    if comp.get("n_terminal_cells") != N_CELLS:
        problems.append(f"completion.n_terminal_cells != {N_CELLS}")
    canon = man.get("freeze_canonical") or {}
    canonical_digest = _sha_json(canon)
    if man.get("freeze_digest") != canonical_digest:
        problems.append("run manifest freeze_digest != digest of freeze_canonical")
    if comp.get("freeze_digest") != canonical_digest:
        problems.append("completion.freeze_digest != verified canonical freeze digest")
    if comp.get("attempt_journal_sha256") != hashlib.sha256(attempts.read_bytes()).hexdigest():
        problems.append("attempt-journal sha256 != completion record (journal changed)")
    if canon.get("reference_extract_sha256") != _sha_text(extract):
        problems.append("frozen reference-extract sha256 != manifest canonical")
    if (man.get("doc_sha256") or {}) != canon.get("doc_sha256"):
        problems.append("run manifest document hashes != freeze canonical")
    if (man.get("doc_sha256") or {}).get("analysis_script") != _sha_text(Path(__file__)):
        problems.append("analysis-script hash != frozen-unit identity in manifest")

    # Exact reference identity and frozen invariants—not merely a matching file hash.
    ext = pd.read_csv(extract)
    case_keys = man.get("case_key_manifest") or []
    if len(case_keys) != N_REF or len(set(case_keys)) != N_REF:
        problems.append("run manifest must contain 97 unique case keys")
    elif canon.get("case_key_manifest_sha256") != hashlib.sha256("\n".join(case_keys).encode()).hexdigest():
        problems.append("case-key manifest hash != freeze canonical")
    required_ref = {"case_id", "nct_id", "pmid", "ref_bottom_line", "ref_gate_a", "gate_a_provenance", "source"}
    if not required_ref <= set(ext.columns):
        problems.append("frozen reference extract missing required identity/provenance columns")
    elif len(ext) != N_REF or ext.case_id.nunique() != N_REF:
        problems.append("frozen reference extract is not exactly 97 unique cases")
    else:
        ordered = ext.sort_values("case_id")
        ext_keys = (ordered.nct_id.astype(str) + "|" + ordered.pmid.astype(str)).tolist()
        if ext_keys != case_keys or ordered.case_id.astype(int).tolist() != list(range(1, N_REF + 1)):
            problems.append("frozen reference extract does not match case-key/case-id manifest")
        if ordered.ref_bottom_line.value_counts().to_dict() != {POS: 7, NEG: 90}:
            problems.append("frozen reference bottom-line counts != 7 genuine / 90 no-discrepancy")
        if ordered.ref_gate_a.value_counts().to_dict() != {
                "RIGHT_PAPER": 45, "WRONG_PAPER": 47, "UNASSESSABLE": 5}:
            problems.append("frozen reference Gate-A counts != 45 right / 47 wrong / 5 unassessable")
        if ordered[["gate_a_provenance", "source"]].isna().any().any():
            problems.append("frozen reference provenance is incomplete")

    # Exact 194-entry prompt manifest and exact 582-cell journal Cartesian set.
    rah = man.get("rendered_case_arm_hashes") or {}
    expected_rah_keys = {f"{cid}|{arm}" for cid in range(1, N_REF + 1) for arm in ARMS}
    if set(rah) != expected_rah_keys:
        problems.append("rendered prompt manifest is not the exact 97x2 key set")
    if canon.get("n_rendered_case_arm") != N_REF * len(ARMS):
        problems.append("freeze canonical rendered-prompt count != 194")
    if canon.get("rendered_case_arm_sha256") != _sha_json(rah):
        problems.append("rendered prompt manifest hash != freeze canonical")
    if canon.get("n_case_keys") != N_REF or canon.get("n_planned_cells") != N_CELLS:
        problems.append("freeze canonical case/cell counts != 97/582")
    expected_cells = {(cid, arm, model) for cid in range(1, N_REF + 1)
                      for arm in ARMS for model in MODEL_ALIASES}
    try:
        term, resume = runner.scan_journal(attempts, valid_keys=expected_cells)
    except runner.JournalIntegrityError as e:
        raise AnalysisInputError(f"journal integrity: {e}")
    if set(term) != expected_cells or resume:
        problems.append("attempt journal is not the exact completed 582-cell Cartesian set")
    for (cid, arm, _model), t in term.items():
        exp = rah.get(f"{cid}|{arm}")
        if exp is None or t.get("prompt_sha256") != exp:
            problems.append(f"cell ({cid},{arm}) prompt hash != frozen rendered hash"); break
    if problems:
        raise AnalysisInputError("run-chain verification failed: " + "; ".join(problems))
    return {"run_id": run_dir.name, "verified": True,
            "attempt_journal_sha256": comp["attempt_journal_sha256"],
            "freeze_digest": comp["freeze_digest"],
            "frozen_reference_extract_sha256": _sha_text(extract),
            "analysis_script_sha256": _sha_text(Path(__file__)),
            "completion_verified": True}


def reference_table(manifest_path: Path, cascade_path: Path) -> pd.DataFrame:
    manifest = json.loads(manifest_path.read_text())
    cid = {k: i + 1 for i, k in enumerate(manifest["case_key_manifest"])}
    ec = pd.read_csv(cascade_path)
    ec["key"] = ec.nct_id.astype(str) + "|" + ec.pmid.astype(str)
    gmap = {"PASS": "RIGHT_PAPER", "FAIL": "WRONG_PAPER", "UNASSESSABLE": "UNASSESSABLE"}
    rows = [{"case_id": cid[r["key"]], "ref_bottom_line": r["reference_final_label"],
             "ref_gate_a": gmap.get(r["gate_a"], "UNASSESSABLE")}
            for _, r in ec.iterrows() if r["key"] in cid]
    return pd.DataFrame(rows)


def run_reference_analysis(cells: pd.DataFrame, ref: pd.DataFrame, provenance: dict | None = None) -> dict:
    validate_reference_inputs(cells, ref)
    panel = panel_table(cells)
    return {
        "provenance": provenance or {},
        "per_model_arm_metrics": model_arm_metrics(cells, ref),
        "primary_contrast_arm1_vs_arm2": paired_contrast(cells, ref),
        "gate_a_agreement": gate_a_agreement(cells, ref),
        "panel_gate_a_consensus_agreement": panel_gate_a_consensus_agreement(cells, ref),
        "conditional_gate_d_and_false_reject_sensitivity": conditional_gate_d(cells, ref),
        "inter_model_agreement": inter_model_agreement(cells),
        "panel_case_table": panel.to_dict("records"),
        "panel_scoring_vs_reference": panel_scoring(panel, ref),
        "note": "Positive class GENUINE_DISCREPANCY; 7 reference positives — fragile. Descriptive, no "
                "p-values. AMBIGUOUS/INDETERMINATE/NO_CONSENSUS count as not-correct (never negative).",
    }


def _file_sha(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "MISSING"


def reference_from_extract(extract_path: Path) -> pd.DataFrame:
    """Consume the FROZEN reference extract (P0-I item 7) — NOT the mutable error_cascade.csv."""
    ext = pd.read_csv(extract_path)
    return ext[["case_id", "ref_bottom_line", "ref_gate_a"]].copy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()
    run_dir = Path(args.run_dir)
    provenance = verify_run_chain(run_dir)  # gate: verify the whole chain BEFORE parsing anything
    cells = cells_from_attempts(run_dir / "attempts.jsonl")
    ref = reference_from_extract(run_dir / "g5_reference_extract.csv")
    result = run_reference_analysis(cells, ref, provenance=provenance)
    out = run_dir / "g5_analysis.json"
    out.write_text(json.dumps(result, indent=2, default=str))
    print(f"Wrote {out} (chain verified)")


if __name__ == "__main__":
    main()

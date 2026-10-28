#!/usr/bin/env python3
"""G2 — Design-aware validation of the frozen pipeline's P4/P5 flags.

Implements COORD_G2_estimator_spec.md. Reconstructs the actual overlapping
enrichment design that produced the 97-case reference sample, estimates
Monte-Carlo inclusion probabilities under the exact sampler, and reports
unweighted (Clopper-Pearson) and design-weighted (Horvitz-Thompson / Hajek +
Taylor linearization) diagnostic performance for P4 and P5 separately.

NOT a population prevalence estimate. NOT a repair of the pipeline. Diagnostic only.

Run:
    uv run python scripts/validation/g2_design_aware_validation.py            # full 1e6 MC
    uv run python scripts/validation/g2_design_aware_validation.py --sims 20000 --no-pairwise  # quick

Outputs (data/validation/):
    g2_sampling_probabilities.csv, g2_pairwise_probabilities.npz,
    g2_validation_table.csv, g2_design_diagnostics.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time

import numpy as np
import pandas as pd
from scipy import stats

from moving_goalpost.config import PROCESSED_DIR, VALIDATION_DIR

# Reuse the frozen gold-label construction so G_i is identical to the headline metrics.
from compute_system_vs_human_gold import _gold  # type: ignore

FRAME_CSV = PROCESSED_DIR / "stage5_final_results.csv"
FRAME_SHA = "dddb06f4c2ebbdfffb06b302980ecb3939560e419d2f4b7da2019c0c95ad9340"
ADJ_CSV = VALIDATION_DIR / "manual_validation_adjudication.csv"
SEED = 42

OUT_PROB = VALIDATION_DIR / "g2_sampling_probabilities.csv"
OUT_PAIR = VALIDATION_DIR / "g2_pairwise_probabilities.npz"
OUT_TABLE = VALIDATION_DIR / "g2_validation_table.csv"
OUT_DIAG = VALIDATION_DIR / "g2_design_diagnostics.json"


# ---------------------------------------------------------------------------
# Exact sampler reconstruction (mirrors scripts/create_validation_sample.py)
# ---------------------------------------------------------------------------


def build_component_draws(df: pd.DataFrame) -> list[tuple[str, np.ndarray, int]]:
    """Return the nine (label, eligible-positional-index array, n) component draws,
    in the exact order and with the exact n's create_validation_sample.py uses."""
    js = pd.to_numeric(df["llm_judge_score"], errors="coerce")
    flag = df["potential_discrepancy"].astype(str).str.strip().str.upper() == "TRUE"
    pos = np.arange(len(df))
    draws: list[tuple[str, np.ndarray, int]] = []

    disc = ["MODIFIED", "MULTIPLE_CHANGES", "ADDED", "COMPOSITE_SUBSET",
            "TIMEFRAME_CHANGE", "UNREPORTED_IN_ABSTRACT"]
    for c in disc:
        elig = pos[(df["classification"] == c).to_numpy()]
        if len(elig) == 0:
            continue
        n = min(max(1, int(len(elig) * 0.15)), 20 if c == "MODIFIED" else 10)
        draws.append((f"P5={c}", elig, n))

    cons = pos[(df["classification"] == "CONSISTENT").to_numpy()]
    if len(cons):
        draws.append(("P5=CONSISTENT", cons, 15))

    hi = pos[((js <= 2) & flag).to_numpy()]
    if len(hi):
        draws.append(("P4_pos&score<=2", hi, 20))
    med = pos[((js == 3) & flag).to_numpy()]
    if len(med):
        draws.append(("P4_pos&score==3", med, 15))
    return draws


def draw_once(draws, seed: int) -> np.ndarray:
    """Reproduce one realized sample: union of nine SRSWOR draws sharing `seed`,
    deduped. Returns sorted global positional indices. Mirrors pandas .sample
    (RandomState(seed).choice(N, n, replace=False)) exactly."""
    included: set[int] = set()
    for _label, elig, n in draws:
        rs = np.random.RandomState(seed)
        take = rs.choice(len(elig), size=min(n, len(elig)), replace=False)
        included.update(elig[take].tolist())
    return np.array(sorted(included), dtype=np.int64)


# ---------------------------------------------------------------------------
# Monte-Carlo inclusion probabilities
# ---------------------------------------------------------------------------


def monte_carlo(draws, n_frame: int, obs_pos: np.ndarray, n_sims: int,
                pairwise: bool, seed_offset: int = 0):
    """Estimate pi_i over the frame and pi_ij over the observed units.

    obs_pos: global positional indices of the 97 observed units.
    Returns (counts_frame, co_obs or None, realized_sample_sizes)."""
    counts = np.zeros(n_frame, dtype=np.int64)
    m = len(obs_pos)
    pos_to_obs = -np.ones(n_frame, dtype=np.int64)
    pos_to_obs[obs_pos] = np.arange(m)
    obs_incl = np.zeros((n_sims, m), dtype=np.uint8) if pairwise else None
    sizes = np.empty(n_sims, dtype=np.int32)

    for k in range(n_sims):
        seed = seed_offset + k
        inc = draw_once(draws, seed)
        counts[inc] += 1
        sizes[k] = len(inc)
        if pairwise:
            local = pos_to_obs[inc]
            local = local[local >= 0]
            obs_incl[k, local] = 1

    co = None
    if pairwise:
        # Chunked float32 matmul: float32 is exact for integer counts <= 2^24 (~16.7M),
        # so co (max n_sims <= 1e6) is exact while peak memory stays bounded.
        co = np.zeros((m, m), dtype=np.float64)
        for start in range(0, n_sims, 100_000):
            c = obs_incl[start:start + 100_000].astype(np.float32)
            co += (c.T @ c).astype(np.float64)
    return counts, co, sizes, obs_incl


# ---------------------------------------------------------------------------
# Independent-draw analytic approximation (audit sensitivity)
# ---------------------------------------------------------------------------


def independent_pi(draws, n_frame: int) -> np.ndarray:
    """pi_i(ind) = 1 - prod_over_draws-eligible-for-i (1 - n_d/N_d)."""
    keep = np.ones(n_frame, dtype=np.float64)
    for _label, elig, n in draws:
        p = min(n, len(elig)) / len(elig)
        keep[elig] *= (1.0 - p)
    return 1.0 - keep


# ---------------------------------------------------------------------------
# Estimators
# ---------------------------------------------------------------------------


def clopper_pearson(k: int, n: int, alpha: float = 0.05):
    if n == 0:
        return (None, None, None)
    lo = 0.0 if k == 0 else stats.beta.ppf(alpha / 2, k, n - k + 1)
    hi = 1.0 if k == n else stats.beta.ppf(1 - alpha / 2, k + 1, n - k)
    return (k / n, float(lo), float(hi))


def _cohen_kappa_binary(flag: np.ndarray, gold: np.ndarray) -> float | None:
    """Descriptive (unweighted) Cohen's kappa between the system flag and the gold label."""
    n = len(flag)
    if n == 0:
        return None
    a, b = flag.astype(bool), gold.astype(bool)
    po = float((a == b).mean())
    pa1, pb1 = a.mean(), b.mean()
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    return float((po - pe) / (1 - pe)) if pe != 1 else None


def unweighted_metrics(flag: np.ndarray, gold: np.ndarray) -> dict:
    tp = int((flag & gold).sum()); fp = int((flag & ~gold).sum())
    fn = int((~flag & gold).sum()); tn = int((~flag & ~gold).sum())
    n = tp + fp + fn + tn
    prec = clopper_pearson(tp, tp + fp)
    rec = clopper_pearson(tp, tp + fn)
    spec = clopper_pearson(tn, tn + fp)
    npv = clopper_pearson(tn, tn + fn)
    accuracy = clopper_pearson(tp + tn, n)
    p, r = (prec[0] or 0.0), (rec[0] or 0.0)
    f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "precision": prec, "recall": rec, "specificity": spec, "npv": npv,
            "accuracy": accuracy, "f1": f1, "kappa": _cohen_kappa_binary(flag, gold)}


def weighted_metrics(flag, gold, w, pi, pi_ij) -> dict:
    """Hájek/HT weighted confusion totals and ratio performance estimators with
    Taylor-linearized design SEs (precision, recall, specificity, NPV, accuracy),
    plus a derived weighted F1. `pi_ij` is the m×m pairwise-inclusion matrix for the
    domain subset (diagonal = pi_i). Weights use the full-frame pi (spec §3)."""
    f, g = flag.astype(bool), gold.astype(bool)
    TPw = float((w * (f & g)).sum()); FPw = float((w * (f & ~g)).sum())
    FNw = float((w * (~f & g)).sum()); TNw = float((w * (~f & ~g)).sum())

    def ratio(num_ind, den_ind):
        return _ht_ratio_with_var(num_ind.astype(int), den_ind.astype(int), w, pi, pi_ij, None)

    prec = ratio(f & g, f)
    rec = ratio(f & g, g)
    spec = ratio(~f & ~g, ~g)
    npv = ratio(~f & ~g, ~f)
    acc = ratio((f & g) | (~f & ~g), np.ones_like(f, dtype=bool))
    pe, re = (prec or {}).get("estimate"), (rec or {}).get("estimate")
    f1 = (2 * pe * re / (pe + re)) if (pe and re and (pe + re) > 0) else None
    out = {"TP_w": TPw, "FP_w": FPw, "FN_w": FNw, "TN_w": TNw, "f1": f1}
    for name, r in [("precision", prec), ("recall", rec), ("specificity", spec),
                    ("npv", npv), ("accuracy", acc)]:
        if r:
            out[name] = r["estimate"]; out[name + "_se"] = r["se"]
            out[name + "_variance_invalid"] = r.get("variance_invalid", False)
            # Manuscript rule (readiness decision 2026-08-18): formal weighted CIs are SUPPRESSED —
            # weighted point estimates are supplementary robustness only; the unweighted exact
            # Clopper-Pearson confusion table is primary. The raw logit CI is retained for the
            # diagnostics record but must not enter manuscript tables.
            out[name + "_ci"] = "SUPPRESSED_MANUSCRIPT_UNSTABLE"
            out[name + "_ci_diagnostic"] = logit_ci(r["estimate"], r["se"])
    return out


def _ht_ratio_with_var(num_ind, den_ind, w, pi, pi_ij_obs, obs_slice):
    """Hajek ratio R = (sum w*num)/(sum w*den) over the sampled units, plus a
    Taylor-linearized design variance using pairwise inclusion probs.
    num_ind, den_ind: 0/1 arrays over the sampled units (length 97)."""
    y = num_ind.astype(float)
    x = den_ind.astype(float)
    Y = float((w * y).sum()); X = float((w * x).sum())
    if X <= 0:
        return None
    R = Y / X
    # Linearized residual for a ratio of two HT totals: e_i = (y_i - R x_i)/pi_i,
    # then Var(hat R) = (1/X^2) * sum_i sum_j (pi_ij - pi_i pi_j)/pi_ij * e_i e_j.
    e = (y - R * x) / pi
    m = len(e)
    var = 0.0
    # pi_ij_obs is m x m matrix of pairwise inclusion; diagonal = pi_i.
    for i in range(m):
        for j in range(m):
            pij = pi_ij_obs[i, j]
            if pij <= 0:
                continue
            var += (pij - pi[i] * pi[j]) / pij * e[i] * e[j]
    var = var / (X * X)
    # EXPOSE, do not clamp: a pairwise Horvitz-Thompson variance estimate can be negative for
    # sparse designs. Report the raw value and flag it; se is undefined (None) when var < 0. The
    # readiness decision forbids silently clamping to zero (RDA pre-manuscript audit, 2026-08-18).
    invalid = (var < 0) or (not np.isfinite(var))
    se = None if invalid else float(np.sqrt(var))
    return {"estimate": R, "var": float(var) if np.isfinite(var) else None,
            "se": se, "variance_invalid": bool(invalid)}


def logit_ci(R: float, se, alpha: float = 0.05):
    if se is None or R <= 0 or R >= 1 or se == 0 or not np.isfinite(se):
        return (None, None)
    z = stats.norm.ppf(1 - alpha / 2)
    g = np.log(R / (1 - R))
    dg = se / (R * (1 - R))
    lo, hi = g - z * dg, g + z * dg
    return (float(1 / (1 + np.exp(-lo))), float(1 / (1 + np.exp(-hi))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=1_000_000)
    ap.add_argument("--stability-block", type=int, default=100_000)
    ap.add_argument("--no-pairwise", action="store_true")
    args = ap.parse_args()

    raw = FRAME_CSV.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != FRAME_SHA:
        raise SystemExit(f"Frame SHA mismatch: {sha} != {FRAME_SHA}")
    df = pd.read_csv(FRAME_CSV)
    n_frame = len(df)
    key = df["nct_id"].astype(str) + "|" + df["pmid"].astype(str)

    draws = build_component_draws(df)
    print("Component draws (label, N_eligible, n):")
    for lb, elig, n in draws:
        print(f"  {lb}: N={len(elig)} n={n}")

    # --- verify seed 42 reproduces the observed 97 keys ---
    obs_pos = draw_once(draws, SEED)
    obs_keys = set(key.iloc[obs_pos])
    adj = pd.read_csv(ADJ_CSV)
    adj_keys = set(adj["nct_id"].astype(str) + "|" + adj["pmid"].astype(str))
    if obs_keys != adj_keys:
        raise SystemExit(f"seed 42 reconstruction mismatch: "
                         f"{len(obs_keys)} vs {len(adj_keys)}; "
                         f"sym diff {len(obs_keys ^ adj_keys)}")
    print(f"\nseed 42 reproduces the exact {len(obs_pos)} observed keys ✓")

    # --- Monte Carlo ---
    t0 = time.time()
    counts, co, sizes, obs_incl = monte_carlo(
        draws, n_frame, obs_pos, args.sims, pairwise=not args.no_pairwise)
    mc_secs = time.time() - t0
    pi_mc = counts / args.sims
    print(f"MC ({args.sims:,} sims) done in {mc_secs:.1f}s; "
          f"realized sample size mean={sizes.mean():.2f} [{sizes.min()}-{sizes.max()}]")

    pi_ind = independent_pi(draws, n_frame)

    # stability: second, non-overlapping block — now PAIRWISE so we can recompute the weighted
    # metrics + Taylor variance on an independent block and EXPOSE pairwise-variance instability
    # (readiness decision 2026-08-18: demonstrate, don't hide, the negative-variance case).
    counts2, co2, _, _ = monte_carlo(
        draws, n_frame, obs_pos, args.stability_block, pairwise=not args.no_pairwise,
        seed_offset=args.sims)
    pi_mc_block2 = counts2 / args.stability_block
    obs_mask = np.zeros(n_frame, bool); obs_mask[obs_pos] = True
    max_pi_drift = float(np.abs(pi_mc[obs_mask] - pi_mc_block2[obs_mask]).max())

    # MC standard error of pi (binomial): sqrt(p(1-p)/S)
    mc_se = np.sqrt(np.clip(pi_mc * (1 - pi_mc), 0, None) / args.sims)
    max_mc_se = float(mc_se[obs_mask].max())

    # sanity: all observed units have pi>0, pi_ii==pi_i
    if (pi_mc[obs_pos] <= 0).any():
        raise SystemExit("some observed unit has pi_i = 0 (MC too small)")

    # --- assemble the 97 sampled units with labels ---
    adj["gold_label"] = adj.apply(_gold, axis=1)
    adjkey = adj["nct_id"].astype(str) + "|" + adj["pmid"].astype(str)
    adj = adj.set_index(adjkey)
    order = [key.iloc[p] for p in obs_pos]  # align to obs_pos order
    gold_pos = np.array([adj.loc[k, "gold_label"] == "GENUINE_DISCREPANCY" for k in order])

    sub = df.iloc[obs_pos].reset_index(drop=True)
    P4 = (sub["potential_discrepancy"].astype(str).str.strip().str.upper() == "TRUE").to_numpy()
    P5 = (sub["classification"].astype(str).str.strip().str.upper() != "CONSISTENT").to_numpy()
    mm = sub["match_method"].astype(str).str.lower() if "match_method" in sub else pd.Series([""] * len(sub))
    nct_matched = mm.str.contains("nct", na=False).to_numpy()

    # both reviewers accepted the match
    def _is_false(v):
        return str(v).strip().upper() == "FALSE" or v is False
    wp_a = np.array([_is_false(adj.loc[k, "wrong_paper_match_a"]) for k in order])
    wp_b = np.array([_is_false(adj.loc[k, "wrong_paper_match_b"]) for k in order])
    paper_ok = wp_a & wp_b
    adjudicated = np.array([str(adj.loc[k, "adjudicator_label"]).strip() not in ("", "nan")
                            for k in order])

    pi_obs = pi_mc[obs_pos]
    w_obs = 1.0 / pi_obs
    pi_ij_obs = (co / args.sims) if co is not None else None

    # weighted stability diagnostic (100k non-overlapping block vs primary 1e6): recompute the
    # weighted metrics + Taylor variance on the independent block and expose any invalid (negative)
    # pairwise variance. Point-estimate stability + variance-validity are reported; formal weighted
    # CIs stay suppressed in manuscript tables regardless.
    weighted_stability = None
    if co is not None and co2 is not None:
        pi_obs_b = pi_mc_block2[obs_pos]; w_obs_b = 1.0 / pi_obs_b
        pij_b = co2 / args.stability_block
        allm = np.ones(len(obs_pos), bool)
        weighted_stability = {}
        for qn, flag in [("P4", P4), ("P5", P5)]:
            prim = weighted_metrics(flag[allm], gold_pos[allm], w_obs, pi_obs, pi_ij_obs)
            blk = weighted_metrics(flag[allm], gold_pos[allm], w_obs_b, pi_obs_b, pij_b)
            weighted_stability[qn] = {
                m: {"primary_estimate": prim.get(m), "primary_variance_invalid": prim.get(m + "_variance_invalid"),
                    "block100k_estimate": blk.get(m), "block100k_variance_invalid": blk.get(m + "_variance_invalid")}
                for m in ("precision", "recall", "specificity", "npv", "accuracy")}
        weighted_stability["any_variance_invalid"] = any(
            v.get("primary_variance_invalid") or v.get("block100k_variance_invalid")
            for qn in ("P4", "P5") for m, v in weighted_stability[qn].items() if isinstance(v, dict))

    # independent-draw weights + pairwise (audit sensitivity): off-diagonal pi_ij = pi_i*pi_j,
    # diagonal = pi_i, so the Taylor form reduces to the independence variance automatically.
    pi_ind_obs = pi_ind[obs_pos]
    w_ind_obs = 1.0 / pi_ind_obs
    pij_ind_obs = np.outer(pi_ind_obs, pi_ind_obs)
    np.fill_diagonal(pij_ind_obs, pi_ind_obs)

    ess = float((w_obs.sum() ** 2) / (w_obs ** 2).sum())

    # genuinely-ambiguous endpoint judgments (spec §3 domain 4): either reviewer coded
    # GENUINELY_AMBIGUOUS. Primary result keeps them (adjudicated); this domain excludes them.
    def _su(v):
        return str(v).strip().upper()
    amb = np.array([_su(adj.loc[k, "endpoint_judgment_a"]) == "GENUINELY_AMBIGUOUS"
                    or _su(adj.loc[k, "endpoint_judgment_b"]) == "GENUINELY_AMBIGUOUS"
                    for k in order])

    domains = {
        "all_97": np.ones(len(sub), bool),
        "nct_id_matched": nct_matched,
        "both_reviewers_paper_ok": paper_ok,
        "exclude_genuinely_ambiguous": ~amb,
        "agreed_only_exclude_adjudicated": ~adjudicated,
    }

    rows = []
    for dom, mask in domains.items():
        for qn, flag in [("P4", P4), ("P5", P5)]:
            f = flag[mask]; g = gold_pos[mask]
            uw = unweighted_metrics(f, g)
            rec = {"domain": dom, "estimand": qn, "n_sampled": int(mask.sum()),
                   "gold_pos_sampled": int(g.sum()), **{f"uw_{k}": v for k, v in uw.items()}}
            if pi_ij_obs is not None and mask.sum() > 0:
                # design-weighted (Monte-Carlo pi_ij) — primary weighted estimates
                wm = weighted_metrics(f, g, w_obs[mask], pi_obs[mask],
                                      pi_ij_obs[np.ix_(mask, mask)])
                rec.update({f"w_{k}": v for k, v in wm.items()})
                # independent-draw approximation — audit sensitivity
                wi = weighted_metrics(f, g, w_ind_obs[mask], pi_ind_obs[mask],
                                      pij_ind_obs[np.ix_(mask, mask)])
                rec.update({f"wind_{k}": v for k, v in wi.items()})
            rows.append(rec)
    table = pd.DataFrame(rows)
    table.to_csv(OUT_TABLE, index=False)

    # sampling probabilities file (frame) + component-eligibility indicators (spec §5.1)
    prob_df = pd.DataFrame({
        "key": key, "observed_inclusion": obs_mask.astype(int),
        "pi_i_mc": pi_mc, "pi_i_ind": pi_ind,
        "w_i_mc": np.where(pi_mc > 0, 1 / np.where(pi_mc > 0, pi_mc, np.nan), np.nan),
        "w_i_ind": np.where(pi_ind > 0, 1 / np.where(pi_ind > 0, pi_ind, np.nan), np.nan),
    })
    for lb, elig, _n in draws:
        col = "elig::" + lb
        ind = np.zeros(n_frame, dtype=int); ind[elig] = 1
        prob_df[col] = ind
    prob_df["n_components_eligible"] = prob_df[[c for c in prob_df.columns
                                               if c.startswith("elig::")]].sum(axis=1)
    prob_df.to_csv(OUT_PROB, index=False)

    if pi_ij_obs is not None:
        np.savez_compressed(OUT_PAIR, pi_ij=pi_ij_obs, obs_keys=np.array(order),
                            n_sims=args.sims)

    # weight diagnostics vs independent approximation on observed units
    max_pi_gap = float(np.abs(pi_obs - pi_ind[obs_pos]).max())
    diag = {
        "frame_csv": str(FRAME_CSV), "frame_sha256": sha, "n_frame": n_frame,
        "seed42_reproduces_97": True, "n_observed": int(len(obs_pos)),
        "n_sims": args.sims, "stability_block": args.stability_block,
        "mc_seconds": round(mc_secs, 1),
        "realized_size": {"mean": float(sizes.mean()), "min": int(sizes.min()), "max": int(sizes.max())},
        "max_mc_se_observed_pi": max_mc_se,
        "max_pi_drift_between_blocks": max_pi_drift,
        "weights": {"min": float(w_obs.min()), "median": float(np.median(w_obs)),
                    "max": float(w_obs.max()),
                    "cv": float(w_obs.std() / w_obs.mean()), "ess": ess},
        "max_abs_gap_pi_mc_vs_pi_ind_observed": max_pi_gap,
        "interval_method": ("unweighted: Clopper-Pearson (PRIMARY, manuscript). weighted: Taylor "
                            "linearization; formal weighted CIs are SUPPRESSED from manuscript tables "
                            "(negative pairwise variance demonstrated); weighted point estimates are "
                            "supplementary robustness only."),
        "weighted_stability_100k": weighted_stability,
        "descriptive_kappa_all_97": {
            "P4_vs_gold": _cohen_kappa_binary(P4, gold_pos),
            "P5_vs_gold": _cohen_kappa_binary(P5, gold_pos),
            "note": "Descriptive only (unweighted); not design-based. No interval reported.",
        },
        "sparse_positive_warning": (
            f"Only {int(gold_pos.sum())} reference-positive cases in the 97-case sample. "
            "Precision/recall point estimates and especially the design-weighted normal/logit "
            "intervals are unstable; the transparent UNWEIGHTED Clopper-Pearson confusion table "
            "is the primary evidentiary display. Weighted (HT/Hajek) results are supplementary "
            "robustness checks only."),
        "notes": "Weighted estimates supplementary; unweighted exact intervals are primary "
                 "(sparse positive class). Seeds treated as uniform = reconstructed "
                 "pseudo-randomization distribution, not a prospective survey design. "
                 "Domains include the genuinely-ambiguous-exclusion sensitivity (spec §3.4) "
                 "and the agreed-only-vs-adjudicated sensitivity (spec §3.5); both weighted "
                 "estimates use full-frame pi_i (Monte-Carlo primary, independent-draw as audit).",
    }
    OUT_DIAG.write_text(json.dumps(diag, indent=2, default=str))

    print(f"\nESS={ess:.1f}  weights CV={diag['weights']['cv']:.2f} "
          f"min/med/max={w_obs.min():.2f}/{np.median(w_obs):.2f}/{w_obs.max():.2f}")
    print(f"max |pi_mc - pi_ind| (observed) = {max_pi_gap:.4f}")
    print(f"max MC SE (observed) = {max_mc_se:.5f}; max block drift = {max_pi_drift:.5f}")
    print("\nUnweighted P4/P5 over all_97:")
    print(table[table.domain == "all_97"][["estimand", "uw_TP", "uw_FP", "uw_FN", "uw_TN",
                                           "uw_precision", "uw_recall"]].to_string(index=False))
    print(f"\nWrote:\n  {OUT_TABLE}\n  {OUT_PROB}\n  {OUT_PAIR}\n  {OUT_DIAG}")


if __name__ == "__main__":
    main()

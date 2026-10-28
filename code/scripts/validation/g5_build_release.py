#!/usr/bin/env python3
"""G5 — deterministic publication/release package builder (P0 build, RDA 2026-08-18).

Consumes the IMMUTABLE authorized run and its frozen reference extract ONLY (read-only) and writes
derived, manuscript-facing tables to a NEW directory. It does not edit any frozen-unit or run file and
makes no model calls. All model outputs are aggregated — no per-call provider response/request IDs, no
abstracts, and no raw prompts enter the release.

Deliverables (RDA order):
  1. primary_effects.csv          — per model, all-97 Arm-1/Arm-2 correctness, paired diff, frozen CI, improved/regressed
  2. mechanism_by_human_gate_a.csv — per model x human_reference_gate_a (45/47/5) Arm-1 vs Arm-2 correctness + diff
  3. gate_a_and_conditional_d.csv  — Gate-A agreement/coverage + conditional-Gate-D + false-reject sensitivity
  4. status_coverage.csv           — per model/arm status counts, content-failure counts, determinate coverage
  5. CAPTIONS.md + DATA_DICTIONARY.md — mechanism-led captions; explicit human_reference_gate_a vs arm1_model_gate_a
  6. results_manifest.json         — sha256 of every immutable source + every derived release artifact

Presentation revisions (COORD_MANUSCRIPT_REVIEW_BUILD_WORK_ORDER.md). Values never change; only the explanatory
presentation is versioned:
  r1 — the historical 2026-08-18 release (``g5_release/``). Retained solely so its bytes can be reproduced into
       an isolated directory; its Table-2 caption is superseded.
  r2 — current. Table-2 caption states the empirical wrong-paper finding instead of a categorical claim, and
       Table 5 (manuscript Supplementary Table S4B) adds the Arm-2 response categories among the 47
       human-reference WRONG_PAPER cases, reconciled against the public-safe cell file. The manifest records
       which historical files it supersedes and which are byte-identical.

The historical directory is never a destination: ``--out`` is required and must be a fresh directory. The r2
revision was created once (2026-10-04) in ``data/validation/g5/g5_release_presentation_r2/`` and is preserved; verify
it (or r1 against ``g5_release/``) by rebuilding into a fresh temporary directory and comparing:

    uv run python scripts/validation/g5_build_release.py --run-dir data/validation/g5/g5-reference-20260818-v1 \
        --out "$(mktemp -d)/g5_release_presentation_r2"      # then: diff -r <that dir> data/validation/g5/g5_release_presentation_r2
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import g5_analyze as ga  # derive_bottom_line, readers, MODEL_ALIASES (single source of truth)

HUMAN_GATE_A_ORDER = ["RIGHT_PAPER", "WRONG_PAPER", "UNASSESSABLE"]
FROZEN_HUMAN_GATE_A_COUNTS = {"RIGHT_PAPER": 45, "WRONG_PAPER": 47, "UNASSESSABLE": 5}
MODELS_ACCESS_NOTE = ("model aliases accessed via GitHub Copilot on 2026-08-18 (GPT-5.4 GA, "
                      "Claude Opus 4.6 GA, Gemini 3.1 Pro public preview); NOT native-provider builds")
IMMUTABLE_SOURCES = ["attempts.jsonl", "completion.json", "manifest.json",
                     "g5_reference_extract.csv", "g5_analysis.json", "spec.json"]

ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_RELEASE = ROOT / "data" / "validation" / "g5" / "g5_release"
HISTORICAL_FILES = ["CAPTIONS.md", "DATA_DICTIONARY.md", "gate_a_and_conditional_d.csv",
                    "mechanism_by_human_gate_a.csv", "primary_effects.csv", "status_coverage.csv"]
# Public-safe categorical cells (release/benchmark): the reconciliation target for the wrong-paper panel.
PUBLIC_CELLS = ROOT / "release" / "benchmark" / "g5_cells_source_text_free.csv"
PUBLIC_CELLS_SHA256 = "f764862e153884c713fd94b23fc84e0819464b1883e4c15b18d97109699571b0"
CURRENT_REVISION = "r2"

# Wrong-paper Arm-2 response panel (S4B). Invalid (non-OK) is decided FIRST, whatever D was partially parsed;
# a valid response must be one of exactly three (Gate D, derived disposition) pairs or the build fails.
INVALID_STATUSES = ("SCHEMA_FAIL", "SEMANTIC_FAIL", "TRANSPORT_FAIL")
VALID_RESPONSE_CATEGORIES = {"MATERIAL_CHANGE": ("valid_material_change", "GENUINE_DISCREPANCY"),
                             "NO_MATERIAL_CHANGE": ("valid_no_material_change", "NO_DISCREPANCY"),
                             "UNASSESSABLE": ("valid_unassessable", "AMBIGUOUS")}
RESPONSE_COLUMNS = ["valid_material_change", "valid_no_material_change", "valid_unassessable", "invalid"]
WRONG_PAPER_PANEL_COLUMNS = (["model", "human_reference_gate_a", "arm", "n_cases"] + RESPONSE_COLUMNS
                             + ["invalid_schema_fail", "invalid_semantic_fail", "invalid_transport_fail"])
PUBLIC_CELL_RENAME = {"model_identifier": "model", "terminal_status": "status", "model_gate_a": "gate_a",
                      "model_gate_d": "gate_d", "derived_disposition": "bl",
                      "human_reference_gate_a": "ref_gate_a", "human_reference_label": "ref_bottom_line"}


class ReleaseInputError(Exception):
    """Inputs violate the frozen contract or the destination policy; nothing was written."""


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "MISSING"


def _labelled_cells(run_dir: Path) -> pd.DataFrame:
    cells = ga.cells_from_attempts(run_dir / "attempts.jsonl")
    ref = pd.read_csv(run_dir / "g5_reference_extract.csv")[["case_id", "ref_gate_a", "ref_bottom_line"]]
    df = cells.merge(ref, on="case_id", how="left")
    df["bl"] = [ga.derive_bottom_line(a, s, ga_, gd)
                for a, s, ga_, gd in zip(df.arm, df.status, df.gate_a, df.gate_d)]
    df["correct"] = (df.bl == df.ref_bottom_line).astype(int)
    return df


def table_primary_effects(analysis: dict) -> pd.DataFrame:
    rows = []
    for r in analysis["primary_contrast_arm1_vs_arm2"]:
        ci = r["diff_ci95_bootstrap"]
        rows.append({"model": r["model"], "n_paired": r["n_paired"],
                     "arm1_correct": r["arm1_correct"], "arm2_correct": r["arm2_correct"],
                     "arm1_correctness": round(r["arm1_correct"] / r["n_paired"], 4),
                     "arm2_correctness": round(r["arm2_correct"] / r["n_paired"], 4),
                     "paired_diff_arm1_minus_arm2": round(r["paired_diff_arm1_minus_arm2"], 4),
                     "diff_ci95_lo": round(ci[0], 4), "diff_ci95_hi": round(ci[1], 4),
                     "improved": r["improved_regressed_unchanged"]["improved"],
                     "regressed": r["improved_regressed_unchanged"]["regressed"],
                     "unchanged": r["improved_regressed_unchanged"]["unchanged"]})
    return pd.DataFrame(rows)


def table_mechanism_by_human_gate_a(df: pd.DataFrame) -> pd.DataFrame:
    """The mechanism: split Arm-1-vs-Arm-2 correctness by the HUMAN reference Gate-A stratum. The
    all-case improvement concentrates in WRONG_PAPER (Arm 1's explicit identity step recovers the reference
    disposition, while Arm 2 classified only 0-1 of 47 such cases correctly per model, its responses mostly
    unassessable or invalid), not in RIGHT_PAPER. Stratum sizes must equal the frozen 45/47/5."""
    sizes = df.drop_duplicates("case_id").groupby("ref_gate_a").size().to_dict()  # per CASE, not per cell
    for k, v in FROZEN_HUMAN_GATE_A_COUNTS.items():
        if sizes.get(k) != v:
            raise SystemExit(f"human_reference_gate_a stratum {k}={sizes.get(k)} != frozen {v}")
    rows = []
    for model in ga.MODEL_ALIASES:
        for stratum in HUMAN_GATE_A_ORDER:
            sub = df[(df.model == model) & (df.ref_gate_a == stratum)]
            a1 = sub[sub.arm == 1]; a2 = sub[sub.arm == 2]
            n = len(a1)
            rows.append({"model": model, "human_reference_gate_a": stratum, "n_cases": n,
                         "arm1_correct": int(a1.correct.sum()), "arm2_correct": int(a2.correct.sum()),
                         "arm1_correctness": round(a1.correct.mean(), 4) if n else None,
                         "arm2_correctness": round(a2.correct.mean(), 4) if n else None,
                         "diff_arm1_minus_arm2": round(a1.correct.mean() - a2.correct.mean(), 4) if n else None})
    return pd.DataFrame(rows)


def table_gate_a_and_conditional_d(analysis: dict) -> pd.DataFrame:
    rows = []
    cd = {(x["model"], x["arm"]): x for x in analysis["conditional_gate_d_and_false_reject_sensitivity"]}
    for r in analysis["gate_a_agreement"]:
        b = r["primary_binary_wrong_paper"]
        c1 = cd.get((r["model"], 1), {})
        rows.append({"model": r["model"],
                     "gate_a_n_human_eligible": b["n_human_eligible"],
                     "gate_a_n_model_determinate": b["n_model_determinate"],
                     "gate_a_coverage": b["coverage_among_eligible"],
                     "gate_a_raw_agreement": b["raw_agreement"], "gate_a_kappa": b["kappa"],
                     "cond_gate_d_n_eligible_arm1": c1.get("conditional_n_eligible"),
                     "cond_gate_d_correctness_arm1": c1.get("conditional_correctness"),
                     "false_reject_sensitivity_arm1": c1.get("correctness_counting_false_reject_as_incorrect")})
    return pd.DataFrame(rows)


def table_status_coverage(df: pd.DataFrame, analysis: dict) -> pd.DataFrame:
    cov = {(m["model"], m["arm"]): m for m in analysis["per_model_arm_metrics"]}
    rows = []
    for model in ga.MODEL_ALIASES:
        for arm in (1, 2):
            sub = df[(df.model == model) & (df.arm == arm)]
            sc = sub.status.value_counts().to_dict()
            m = cov.get((model, arm), {})
            rows.append({"model": model, "arm": arm, "n": len(sub),
                         "OK": sc.get("OK", 0), "SCHEMA_FAIL": sc.get("SCHEMA_FAIL", 0),
                         "SEMANTIC_FAIL": sc.get("SEMANTIC_FAIL", 0), "TRANSPORT_FAIL": sc.get("TRANSPORT_FAIL", 0),
                         "content_failures": int(sub.status.isin(["SCHEMA_FAIL", "SEMANTIC_FAIL"]).sum()),
                         "determinate_coverage": m.get("coverage")})
    return pd.DataFrame(rows)


def classify_arm2_response(status, gate_d, disposition) -> str:
    """One Arm-2 cell -> exactly one S4B category. Non-OK is invalid FIRST, even with a parsed MATERIAL_CHANGE."""
    if status != "OK":
        if status not in INVALID_STATUSES:
            raise ReleaseInputError(f"unknown terminal status {status!r}")
        return "invalid"
    cat = VALID_RESPONSE_CATEGORIES.get(gate_d)
    if cat is None or disposition != cat[1]:
        raise ReleaseInputError(f"unexpected valid Arm-2 category: gate_d={gate_d!r}, disposition={disposition!r}")
    return cat[0]


def table_wrong_paper_arm2_responses(df: pd.DataFrame) -> pd.DataFrame:
    """S4B: Arm-2 response categories per model among the HUMAN-reference WRONG_PAPER cases (n=47 each).

    ``df`` needs case_id, model, arm, status, gate_d, bl (derived disposition) and ref_gate_a (human reference).
    The stratum comes from the human reference only; model Gate-A calls are never consulted. Fails closed on
    unknown models, duplicate or missing cells, a stratum size other than the frozen 47, or an unexpected valid
    category, so no response is silently dropped."""
    models = set(df.model.unique())
    if models != set(ga.MODEL_ALIASES):
        raise ReleaseInputError(f"models must be exactly {ga.MODEL_ALIASES}; got {sorted(map(str, models))}")
    dup = df.duplicated(["case_id", "model", "arm"], keep=False)
    if dup.any():
        raise ReleaseInputError("duplicate cells: "
                                f"{df.loc[dup, ['case_id', 'model', 'arm']].drop_duplicates().values.tolist()}")
    if df.groupby("case_id").ref_gate_a.nunique(dropna=False).max() > 1:
        raise ReleaseInputError("a case carries more than one human reference Gate-A label")
    ref = df.drop_duplicates("case_id")
    wrong = set(ref.loc[ref.ref_gate_a == "WRONG_PAPER", "case_id"])
    n_wrong = FROZEN_HUMAN_GATE_A_COUNTS["WRONG_PAPER"]
    if len(wrong) != n_wrong:
        raise ReleaseInputError(f"human WRONG_PAPER stratum has {len(wrong)} cases, frozen {n_wrong}")
    rows = []
    for model in ga.MODEL_ALIASES:
        sub = df[(df.model == model) & (df.arm == 2) & df.case_id.isin(wrong)]
        missing = wrong - set(sub.case_id)
        if missing:
            raise ReleaseInputError(f"{model}: missing Arm-2 cells for {len(missing)} WRONG_PAPER cases")
        cats = [classify_arm2_response(st, gd, bl) for st, gd, bl in zip(sub.status, sub.gate_d, sub.bl)]
        row = {"model": model, "human_reference_gate_a": "WRONG_PAPER", "arm": 2, "n_cases": len(sub)}
        row.update({c: cats.count(c) for c in RESPONSE_COLUMNS})
        row.update({f"invalid_{s.lower()}": int((sub.status == s).sum()) for s in INVALID_STATUSES})
        if sum(row[c] for c in RESPONSE_COLUMNS) != n_wrong or \
                sum(row[f"invalid_{s.lower()}"] for s in INVALID_STATUSES) != row["invalid"]:
            raise ReleaseInputError(f"{model}: response categories do not partition the {n_wrong} cases")
        rows.append(row)
    return pd.DataFrame(rows, columns=WRONG_PAPER_PANEL_COLUMNS)


def public_cells_frame(path: Path = PUBLIC_CELLS, expected_sha256: str | None = PUBLIC_CELLS_SHA256) -> pd.DataFrame:
    """The public-safe categorical cell file under the panel's column names (sha-pinned by default)."""
    if expected_sha256 is not None and _sha(path) != expected_sha256:
        raise ReleaseInputError(f"public cell file {path} sha256 {_sha(path)} != pinned {expected_sha256}")
    return pd.read_csv(path, dtype={"model_gate_a": str, "model_gate_d": str}).rename(columns=PUBLIC_CELL_RENAME)


def reconcile_wrong_paper_panel(panel: pd.DataFrame, public_cells: pd.DataFrame, mechanism: pd.DataFrame) -> dict:
    """The panel derived from the immutable attempts must equal the panel derived from the public-safe cells, and
    the valid no-material column must equal Arm-2 correct in the human WRONG_PAPER stratum (Table 2 and the
    public cells' own correct flags)."""
    if not table_wrong_paper_arm2_responses(public_cells).equals(panel):
        raise ReleaseInputError("wrong-paper panel from attempts != panel from the public-safe cell file")
    wp = mechanism[mechanism.human_reference_gate_a == "WRONG_PAPER"].set_index("model")
    pub = public_cells[(public_cells.arm == 2) & (public_cells.ref_gate_a == "WRONG_PAPER")]
    pub_correct = pub.groupby("model").correct.sum().to_dict()
    for r in panel.itertuples():
        if not (int(wp.loc[r.model, "arm2_correct"]) == int(pub_correct.get(r.model, -1))
                == int(r.valid_no_material_change)) or int(wp.loc[r.model, "n_cases"]) != int(r.n_cases):
            raise ReleaseInputError(f"{r.model}: no-material count does not reconcile with Arm-2 correct")
    return {"panel_from_attempts_equals_panel_from_public_cells": True,
            "valid_no_material_change_equals_arm2_correct_in_human_wrong_paper_stratum": True}


CAPTIONS_R1 = """# G5 release — manuscript captions (mechanism-led)

**Table 1 (primary_effects).** Adding an explicit publication-identity (Gate A) step before the endpoint
comparison is the operative change: each model's case-level agreement with the adjudicated human bottom
line rises substantially from Arm 2 (endpoint-only) to Arm 1 (identity-then-endpoint). The paired
Arm-1-minus-Arm-2 differences (bootstrap 95% intervals) are the prespecified primary contrast. The
magnitudes (≈49.5–52.6 percentage points) are the **enriched-set** effect on the stratified 97-case
reference sample, not a population estimate.

**Table 2 (mechanism_by_human_gate_a).** The improvement is a *wrong-paper* mechanism: within the human
WRONG_PAPER stratum, Arm 1 recovers the correct disposition that Arm 2 (which cannot reject a wrong paper)
misses; within the human RIGHT_PAPER stratum, Arm-1 and Arm-2 performance is essentially unchanged. The
gain therefore reflects task specification (a missing gate), not improved semantic-equivalence judgment.

**Table 3 (gate_a_and_conditional_d).** When the models perform the Gate-A step, agreement with the human
wrong-paper judgment is high; conditional Gate-D correctness (right-paper cases only) and the
false-Gate-A-rejection sensitivity are reported with explicit eligibility denominators.

**Table 4 (status_coverage).** Response validity is retained, not hidden: per-model/arm OK vs
schema/semantic content failures and determinate coverage. Content failures are concentrated in one model
alias and are counted as not-correct (never coerced to a label).

Models are named aliases accessed via GitHub Copilot on 2026-08-18; this is not native-provider
performance and model availability may change. Positive-class (GENUINE_DISCREPANCY) precision/recall rest
on 7 reference positives and are fragile.
"""

DATA_DICTIONARY_R1 = """# G5 release — data dictionary

CRITICAL DISTINCTION — two different Gate-A axes, never conflate:
- `human_reference_gate_a` — the ADJUDICATED HUMAN reference publication-identity label per case
  (RIGHT_PAPER / WRONG_PAPER / UNASSESSABLE; frozen counts 45 / 47 / 5). Used to STRATIFY the mechanism
  (Table 2). Source: the frozen `g5_reference_extract.csv` (from `error_cascade.csv` Gate A).
- `arm1_model_gate_a` — the MODEL's own Step-1 identity call in Arm 1 (a model output, not reference).
  Reported in `g5_analysis.json:primary_contrast_arm1_vs_arm2[].stratified_by_arm1_gate_a`. Do NOT use it
  as a reference stratum.

Table columns:
- primary_effects: arm{1,2}_correct(ness) = case-level agreement with the adjudicated human bottom line
  over all 97; paired_diff = Arm1-minus-Arm2; diff_ci95 = frozen case-resampling bootstrap; improved/
  regressed/unchanged = per-case transition counts.
- mechanism_by_human_gate_a: per model × human_reference_gate_a stratum, Arm-1/Arm-2 correctness + diff.
- gate_a_and_conditional_d: binary Gate-A agreement (model WRONG_PAPER vs human), coverage among
  human-eligible {RIGHT,WRONG}, kappa; conditional Gate-D (right-paper eligible) + false-rejection
  sensitivity.
- status_coverage: OK / SCHEMA_FAIL / SEMANTIC_FAIL / TRANSPORT_FAIL counts, content_failures, and
  determinate_coverage per model/arm.

Bottom-line mapping and consensus rules are defined in `COORD_G5_freeze_appendix.md` §5/§6. AMBIGUOUS,
INDETERMINATE, and NO_CONSENSUS are distinct from NO_DISCREPANCY and count as not-correct.
Excluded from this public package: abstracts, raw prompts, provider response/request IDs, and the
contaminated pre-freeze pilot artifacts.
"""

# r2 (current presentation): Table 2 states the empirical wrong-paper finding and Table 5 (S4B) is added.
CAPTIONS_R2 = CAPTIONS_R1.replace(
    """**Table 2 (mechanism_by_human_gate_a).** The improvement is a *wrong-paper* mechanism: within the human
WRONG_PAPER stratum, Arm 1 recovers the correct disposition that Arm 2 (which cannot reject a wrong paper)
misses; within the human RIGHT_PAPER stratum, Arm-1 and Arm-2 performance is essentially unchanged. The
gain therefore reflects task specification (a missing gate), not improved semantic-equivalence judgment.""",
    """**Table 2 (mechanism_by_human_gate_a).** The improvement is a *wrong-paper* mechanism: within the human
WRONG_PAPER stratum, Arm 1 recovers the reference disposition in 45–47 of the 47 cases per model, whereas
Arm 2 classified only 0–1 of the 47 correctly per model; its responses there were mostly unassessable or
invalid (Table 5). Within the human RIGHT_PAPER stratum, Arm-1 and Arm-2 performance is essentially
unchanged. Both arms received identical inputs under the same rubric and neither was given a replacement
paper, so the gain reflects task specification (a missing gate), not improved semantic-equivalence
judgment.""").replace(
    """Models are named aliases""",
    """**Table 5 (wrong_paper_arm2_responses; manuscript Supplementary Table S4B).** Arm-2 responses among the
47 human-reference WRONG_PAPER cases, per model, in four mutually exclusive categories: valid material-change
classification; valid no-material-change classification; valid but unassessable (status OK, Gate D
UNASSESSABLE, derived AMBIGUOUS); and invalid (non-OK terminal status), assigned first regardless of any
partially parsed Gate-D value and never promoted to a label. Invalid responses are split by terminal status.
The no-material count equals Arm-2 correct in this stratum (Table 2) under the reference convention; a
correct classification does not establish that Arm 2 recognized the identity error. The panel is derived
from the immutable run and reconciled exactly against the public-safe categorical cell file.

Models are named aliases""")
if CAPTIONS_R2.count("**Table") != CAPTIONS_R1.count("**Table") + 1 or "cannot reject" in CAPTIONS_R2:
    raise RuntimeError("r2 caption revision did not apply")

DATA_DICTIONARY_R2 = DATA_DICTIONARY_R1.replace(
    """  determinate_coverage per model/arm.
""",
    """  determinate_coverage per model/arm.
- wrong_paper_arm2_responses (r2): per model, Arm 2 among the human_reference_gate_a = WRONG_PAPER cases
  (n_cases = 47). valid_material_change / valid_no_material_change / valid_unassessable = status OK with
  Gate D MATERIAL_CHANGE / NO_MATERIAL_CHANGE / UNASSESSABLE (derived GENUINE_DISCREPANCY / NO_DISCREPANCY /
  AMBIGUOUS); invalid = any non-OK terminal status, decided first and never promoted to a label;
  invalid_{schema,semantic,transport}_fail split the invalid count. The four response columns sum to n_cases.
""")
if DATA_DICTIONARY_R2 == DATA_DICTIONARY_R1:
    raise RuntimeError("r2 data-dictionary revision did not apply")

PRESENTATIONS = {
    "r1": {"captions": CAPTIONS_R1, "data_dictionary": DATA_DICTIONARY_R1, "wrong_paper_panel": False},
    "r2": {"captions": CAPTIONS_R2, "data_dictionary": DATA_DICTIONARY_R2, "wrong_paper_panel": True},
}
CAPTIONS, DATA_DICTIONARY = CAPTIONS_R2, DATA_DICTIONARY_R2   # current presentation


def check_destination(out: Path, historical: Path = HISTORICAL_RELEASE) -> None:
    """The historical derived directory is never a destination, and no existing output is overwritten."""
    if out.resolve() == historical.resolve():
        raise ReleaseInputError(f"refusing to write into the historical release {out}; choose a fresh directory")
    if out.exists() and any(out.iterdir()):
        raise ReleaseInputError(f"refusing to overwrite the non-empty directory {out}; choose a fresh directory")


def supersedes_record(out: Path, historical: Path = HISTORICAL_RELEASE) -> dict:
    """What a revised build supersedes, verified against the historical manifest (which is never edited)."""
    hm_path = historical / "results_manifest.json"
    pinned = json.loads(hm_path.read_text())["derived_release_sha256"]
    for f in HISTORICAL_FILES:
        if _sha(historical / f) != pinned.get(f):
            raise ReleaseInputError(f"historical {f} no longer matches its pinned manifest")
    identical = sorted(f for f in HISTORICAL_FILES if _sha(out / f) == pinned[f])
    return {"historical_release": "data/validation/g5/g5_release",
            "historical_presentation_revision": "r1",
            "historical_results_manifest_sha256": _sha(hm_path),
            "superseded_files_sha256": {f: pinned[f] for f in sorted(set(HISTORICAL_FILES) - set(identical))},
            "byte_identical_to_historical": identical,
            "reason": "Table-2 caption replaced the categorical claim that Arm 2 'cannot reject a wrong paper' "
                      "with the empirical finding; Table 5 (S4B wrong-paper Arm-2 responses) added. "
                      "No value changed."}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out", required=True, help="fresh destination; never the historical g5_release/")
    ap.add_argument("--presentation-revision", choices=sorted(PRESENTATIONS), default=CURRENT_REVISION)
    ap.add_argument("--public-cells", default=str(PUBLIC_CELLS))
    args = ap.parse_args()
    build(Path(args.run_dir), Path(args.out), args.presentation_revision, Path(args.public_cells))


def build(run_dir: Path, out: Path, revision: str = CURRENT_REVISION, public_cells: Path = PUBLIC_CELLS,
          public_cells_sha256: str | None = PUBLIC_CELLS_SHA256, historical: Path = HISTORICAL_RELEASE) -> dict:
    pres = PRESENTATIONS[revision]
    check_destination(out, historical)
    analysis = json.loads((run_dir / "g5_analysis.json").read_text())
    df = _labelled_cells(run_dir)
    t2 = table_mechanism_by_human_gate_a(df)
    if pres["wrong_paper_panel"]:   # derive and reconcile before anything is written
        t5 = table_wrong_paper_arm2_responses(df)
        reconciliation = reconcile_wrong_paper_panel(t5, public_cells_frame(public_cells, public_cells_sha256), t2)
    out.mkdir(parents=True, exist_ok=True)

    t1 = table_primary_effects(analysis); t1.to_csv(out / "primary_effects.csv", index=False)
    t2.to_csv(out / "mechanism_by_human_gate_a.csv", index=False)
    t3 = table_gate_a_and_conditional_d(analysis); t3.to_csv(out / "gate_a_and_conditional_d.csv", index=False)
    t4 = table_status_coverage(df, analysis); t4.to_csv(out / "status_coverage.csv", index=False)
    if pres["wrong_paper_panel"]:
        t5.to_csv(out / "wrong_paper_arm2_responses.csv", index=False)
    (out / "CAPTIONS.md").write_text(pres["captions"])
    (out / "DATA_DICTIONARY.md").write_text(pres["data_dictionary"])

    manifest = {
        "run_id": run_dir.name, "built_utc": "deterministic-no-timestamp",
        "models_access_note": MODELS_ACCESS_NOTE,
        "immutable_source_sha256": {f: _sha(run_dir / f) for f in IMMUTABLE_SOURCES},
        "derived_release_sha256": {f.name: _sha(f) for f in sorted(out.glob("*")) if f.name != "results_manifest.json"},
        "excluded_from_public_package": ["abstracts", "raw_prompts", "provider_response_request_ids",
                                         "contaminated_pre_freeze_pilots"],
    }
    if revision != "r1":   # r1 reproduces the historical manifest byte-for-byte; later revisions say what changed
        manifest.update({
            "presentation_revision": revision,
            "values_changed": False,
            "supersedes": supersedes_record(out, historical),
            "wrong_paper_panel_reconciliation": {"public_cells": "release/benchmark/g5_cells_source_text_free.csv",
                                                 "public_cells_sha256": _sha(public_cells), **reconciliation},
        })
    (out / "results_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Release ({revision}) written to {out}")
    print("primary effects:\n", t1.to_string(index=False))
    print("\nmechanism by human_reference_gate_a:\n", t2.to_string(index=False))
    if pres["wrong_paper_panel"]:
        print("\nwrong-paper Arm-2 responses:\n", t5.to_string(index=False))
    return manifest


if __name__ == "__main__":
    main()

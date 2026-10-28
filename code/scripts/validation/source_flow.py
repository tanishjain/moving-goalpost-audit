"""Deterministic source-cohort flow with explicit record units (COORD_G3_FINAL_PACKAGE_WORK_ORDER.md §2).

Derived from the saved stage CSVs, whose hashes are checked against the existing reproduction manifest; the
historical manifest is never regenerated and no records are fetched. Corrects two inherited unit errors:
stage-1 rows are registered primary-endpoint records (not trials), and stage-3 rows are matched publications
with an abstract (not successful extractions).
"""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
REPRO = PROCESSED / "repro_manifest_latest.json"
COHORT_CACHE = ROOT / "data" / "raw" / "ctgov" / "search_cancer_PHASE3_COMPLETED_2018-01-01_2023-12-31_max5000.json"
COHORT_CACHE_SHA256 = "3e591d7443a02f9575d1788515130f338d32c881e9a65bc69d35d669999112fa"
STAGES = {
    "stage1": "stage1_trials_with_endpoints.csv",
    "stage2_all": "stage2_all_trial_publication_pairs.csv",
    "stage2_matched": "stage2_matched_pairs.csv",
    "stage2_unmatched": "stage2_unmatched_trials.csv",
    "stage3": "stage3_extracted_endpoints.csv",
    "stage4": "stage4_comparison_results.csv",
    "stage5": "stage5_final_results.csv",
}


class FlowError(Exception):
    """A stage file, its hash, or a unit/nesting invariant failed; no flow is reported."""


def _sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _nonblank(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip() != ""


def published_endpoint(stage3: pd.DataFrame) -> pd.Series:
    """The pipeline's stage-3 rule (pipeline.py): LLM extraction when nonblank, otherwise the regex result."""
    llm = stage3["llm_extracted_endpoints"].fillna("").astype(str).str.strip()
    regex = stage3["regex_extracted_endpoints"].fillna("").astype(str).str.strip()
    return llm.where(llm.astype(bool), regex)


def derive_flow(processed: Path = PROCESSED, repro: Path = REPRO, cache: Path | None = COHORT_CACHE,
                cache_sha256: str | None = COHORT_CACHE_SHA256) -> dict:
    manifest = json.loads(Path(repro).read_text())["artifacts"]
    frames = {}
    for key, name in STAGES.items():
        p = Path(processed) / name
        if not p.exists():
            raise FlowError(f"stage file missing: {name}")
        if name not in manifest or _sha(p) != manifest[name]["sha256"]:
            raise FlowError(f"stage file hash does not match the reproduction manifest: {name}")
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
        if len(df) != manifest[name]["rows"]:
            raise FlowError(f"row count differs from the reproduction manifest: {name}")
        frames[key] = df
    s1, s2, m, u, s3, s4, s5 = (frames[k] for k in STAGES)

    trials = set(s1.nct_id)
    for key in ("stage2_all", "stage2_matched", "stage2_unmatched", "stage3"):
        if frames[key].nct_id.duplicated().any():
            raise FlowError(f"{key} is not unique by trial")
    if set(s2.nct_id) != trials:
        raise FlowError("stage-2 trial set differs from stage-1")
    if set(m.nct_id) & set(u.nct_id) or set(m.nct_id) | set(u.nct_id) != trials:
        raise FlowError("matched/unmatched do not partition the retrieved trials")
    if (u.pmid.str.strip() != "").any() or (m.pmid.str.strip() == "").any():
        raise FlowError("matched/unmatched publication identifiers inconsistent")
    if not set(zip(s3.nct_id, s3.pmid)) <= set(zip(m.nct_id, m.pmid)):
        raise FlowError("stage-3 records are not a subset of matched records")
    if not _nonblank(s3.abstract).all():
        raise FlowError("a stage-3 record lacks an abstract")
    missing_abstract = m[~_nonblank(m.abstract)]
    if set(zip(missing_abstract.nct_id, missing_abstract.pmid)) != set(zip(m.nct_id, m.pmid)) - set(zip(s3.nct_id, s3.pmid)):
        raise FlowError("matched records missing from stage 3 are not exactly those without an abstract")
    pub = published_endpoint(s3)
    if not (pub == s3.published_endpoint.fillna("").astype(str).str.strip()).all():
        raise FlowError("stage-3 published_endpoint does not follow the LLM-then-regex fallback rule")
    has_pub = pub != ""
    if not _nonblank(s3.registered_endpoint_measures).all():
        raise FlowError("a stage-3 record lacks registered endpoint text")
    keys4, keys5 = set(zip(s4.nct_id, s4.pmid)), set(zip(s5.nct_id, s5.pmid))
    if len(keys4) != len(s4) or keys4 != keys5 or keys4 != set(zip(s3.nct_id[has_pub], s3.pmid[has_pub])):
        raise FlowError("stage-4/5 records are not exactly the stage-3 records with extracted endpoint text")
    llm_nonblank = s3.llm_extracted_endpoints.fillna("").astype(str).str.strip() != ""

    flow = {
        "retrieved_trials": len(trials),
        "registered_primary_endpoint_records": len(s1),
        "publication_matched_trials": len(m),
        "no_publication_found": len(u),
        "matched_without_abstract": len(missing_abstract),
        "abstract_available": len(s3),
        "extracted_endpoint_text_available": int(has_pub.sum()),
        "without_extracted_endpoint_text": int((~has_pub).sum()),
        "extracted_by_llm": int((has_pub & llm_nonblank).sum()),
        "extracted_by_regex_fallback": int((has_pub & ~llm_nonblank).sum()),
        "compared_and_classified": len(s5),
    }
    out = {"flow": flow, "stage_sha256": {name: manifest[name]["sha256"] for name in STAGES.values()}}
    if cache is not None:
        if _sha(cache) != cache_sha256:
            raise FlowError("cohort cache hash drift")
        records = json.loads(Path(cache).read_text())
        ids = [r["nct_id"] for r in records]
        if len(ids) != len(set(ids)) or set(ids) != trials:
            raise FlowError("cohort cache trial set differs from stage 1")
        per = collections.Counter(s1.nct_id)
        if any(per[r["nct_id"]] != len(r["primary_endpoints"]) for r in records):
            raise FlowError("stage-1 endpoint records do not match the cached primary endpoints")
        phases = collections.Counter(r["phase"] if isinstance(r["phase"], str) else ", ".join(r["phase"])
                                     for r in records)
        out["registered_phase"] = dict(sorted(phases.items()))
        out["cohort_cache_sha256"] = cache_sha256
    return out


if __name__ == "__main__":
    print(json.dumps(derive_flow(), indent=2))

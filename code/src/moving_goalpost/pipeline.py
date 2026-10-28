"""Main pipeline orchestrator.

Runs the full Moving Goalpost detection pipeline end-to-end:
    1. Fetch completed trials from ClinicalTrials.gov
    2. Match each trial to its PubMed publication
    3. Extract primary endpoints from abstracts (regex + LLM)
    4. Compute semantic similarity (embeddings + LLM judge)
    5. Classify discrepancies

Each stage reads/writes from data/processed/ CSVs, so stages can be
run independently or resumed after interruption.
"""

import logging
import sys
from datetime import datetime

import pandas as pd
from tqdm import tqdm

from moving_goalpost.config import PipelineConfig, SimilarityThresholds, PROCESSED_DIR
from moving_goalpost.data.ctgov import search_completed_trials
from moving_goalpost.data.matching import match_trials_batch, pairs_to_dataframe
from moving_goalpost.extraction.regex_extractor import extract_endpoints_regex
from moving_goalpost.extraction.llm_extractor import extract_endpoints_llm
from moving_goalpost.comparison.embeddings import compare_endpoints_embedding, compare_endpoints_embedding_batch
from moving_goalpost.comparison.llm_judge import compare_endpoints_llm_judge
from moving_goalpost.comparison.classifier import classify_discrepancy
from moving_goalpost.utils.io import save_processed_csv, load_processed_csv

logger = logging.getLogger(__name__)
CHECKPOINT_EVERY = 25


def _load_stage_if_exists(filename: str) -> pd.DataFrame | None:
    try:
        return load_processed_csv(filename)
    except FileNotFoundError:
        return None


def _is_missing(series: pd.Series) -> pd.Series:
    return series.isna() | (series.astype(str).str.strip() == "")


def _require_columns(df: pd.DataFrame, required: list[str], stage_name: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{stage_name} requires columns {required}; missing columns: {missing}")


def _trial_id_set_from_stage1() -> set[str] | None:
    stage1_df = _load_stage_if_exists("stage1_trials_with_endpoints.csv")
    if stage1_df is None or "nct_id" not in stage1_df.columns:
        return None
    return set(stage1_df["nct_id"].dropna().astype(str))


# Columns set on non-flagged (CONSISTENT) rows in Stage 5.
_STAGE5_DEFAULTS: dict[str, str] = {
    "classification": "CONSISTENT",
    "classification_explanation": "",
    "specific_changes": "",
    "classification_model_deployment": "",
    "classification_model_id": "",
}


def _prepare_non_flagged(df: pd.DataFrame) -> pd.DataFrame:
    """Return non-flagged rows with default classification columns (R1-4)."""
    mask = df["potential_discrepancy"].astype(str).str.strip().str.upper() != "TRUE"
    non_flagged = df[mask].copy()
    for col, default in _STAGE5_DEFAULTS.items():
        if col not in non_flagged.columns:
            non_flagged[col] = default
        else:
            non_flagged[col] = non_flagged[col].fillna("").replace("", default)
    return non_flagged


def _attach_existing_values(
    base_df: pd.DataFrame,
    existing_df: pd.DataFrame | None,
    key_cols: list[str],
    value_cols: list[str],
) -> pd.DataFrame:
    """Attach values from previous stage output to support resumability."""
    if existing_df is None:
        return base_df
    if any(col not in base_df.columns for col in key_cols):
        return base_df
    if any(col not in existing_df.columns for col in key_cols):
        return base_df

    available_value_cols = [c for c in value_cols if c in existing_df.columns]
    if not available_value_cols:
        return base_df

    dedup_existing = existing_df[key_cols + available_value_cols].drop_duplicates(subset=key_cols, keep="last")
    merged = base_df.merge(dedup_existing, on=key_cols, how="left", suffixes=("", "__existing"))

    for col in available_value_cols:
        existing_col = f"{col}__existing" if f"{col}__existing" in merged.columns else col
        if col in merged.columns:
            missing_mask = _is_missing(merged[col])
            merged.loc[missing_mask, col] = merged.loc[missing_mask, existing_col]
        else:
            merged[col] = merged[existing_col]
        if existing_col != col:
            merged = merged.drop(columns=[existing_col])

    return merged


def setup_logging(level: int = logging.INFO) -> None:
    """Configure project-wide logging."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = PROCESSED_DIR / f"pipeline_run_{ts}.log"
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
        force=True,
    )
    logger.info("Pipeline logs will also be written to %s", log_path)


# ======================================================================
# Stage 1: Fetch trials
# ======================================================================


def stage_1_fetch_trials(config: PipelineConfig) -> pd.DataFrame:
    """Fetch completed trials from ClinicalTrials.gov.

    Note: output is endpoint-level (one row per registered endpoint) for auditability.
    Stage 2 matches at trial-level and uses Stage 1 NCT IDs to constrain the cohort.
    """
    logger.info("=== Stage 1: Fetching trials ===")
    trials = search_completed_trials(config)
    logger.info("Fetched %d trials with registered primary endpoints", len(trials))

    rows = []
    for t in trials:
        for ep in t.primary_endpoints:
            rows.append(
                {
                    "nct_id": t.nct_id,
                    "trial_title": t.title,
                    "condition": ", ".join(t.conditions),
                    "intervention": ", ".join(t.interventions),
                    "sponsor": t.sponsor,
                    "sponsor_type": t.sponsor_type,
                    "endpoint_measure": ep.measure,
                    "endpoint_description": ep.description,
                    "endpoint_timeframe": ep.timeframe,
                    "completion_date": t.completion_date,
                }
            )

    df = pd.DataFrame(rows)
    save_processed_csv(df, "stage1_trials_with_endpoints.csv")
    return df


# ======================================================================
# Stage 2: Match trials to publications
# ======================================================================


def stage_2_match_publications(config: PipelineConfig) -> pd.DataFrame:
    """Match trials to their PubMed publications at trial-level.

    If Stage 1 output exists, Stage 2 restricts matching to that exact NCT cohort.
    """
    logger.info("=== Stage 2: Matching trials to publications ===")
    trials = search_completed_trials(config)
    stage1_ids = _trial_id_set_from_stage1()
    if stage1_ids is not None:
        trials = [t for t in trials if t.nct_id in stage1_ids]
        logger.info(
            "Restricted Stage 2 to Stage 1 trial IDs: %d trials",
            len(trials),
        )
    else:
        logger.info("Stage 1 trial IDs unavailable; matching all fetched trials.")

    pairs = match_trials_batch(trials, config)
    df = pairs_to_dataframe(pairs)

    matched_df = df[df["match_method"] != "not_found"].copy()
    unmatched_df = df[df["match_method"] == "not_found"].copy()

    save_processed_csv(df, "stage2_all_trial_publication_pairs.csv")
    save_processed_csv(matched_df, "stage2_matched_pairs.csv")
    save_processed_csv(unmatched_df, "stage2_unmatched_trials.csv")

    logger.info(
        "Matched: %d/%d (%.0f%%). Unmatched: %d",
        len(matched_df),
        len(df),
        100 * len(matched_df) / len(df) if len(df) > 0 else 0,
        len(unmatched_df),
    )
    return matched_df


# ======================================================================
# Stage 3: Extract endpoints from abstracts
# ======================================================================


def stage_3_extract_endpoints(config: PipelineConfig) -> pd.DataFrame:
    """Extract primary endpoints from publication abstracts."""
    logger.info("=== Stage 3: Extracting endpoints from abstracts ===")
    df = load_processed_csv("stage2_matched_pairs.csv")
    _require_columns(df, ["nct_id", "pmid", "abstract"], "Stage 3")

    has_abstract = df["abstract"].notna() & (df["abstract"].str.strip() != "")
    df_with_abstract = df[has_abstract].copy()
    existing_stage3 = _load_stage_if_exists("stage3_extracted_endpoints.csv")
    df_with_abstract = _attach_existing_values(
        df_with_abstract,
        existing_stage3,
        key_cols=["nct_id", "pmid"],
        value_cols=[
            "regex_extracted_endpoints",
            "regex_confidence",
            "regex_pattern",
            "llm_extracted_endpoints",
            "llm_confidence",
            "llm_extraction_evidence",
            "extraction_model_deployment",
            "extraction_model_id",
        ],
    )
    logger.info("%d/%d matched pairs have abstracts", len(df_with_abstract), len(df))

    # Regex extraction (fast baseline)
    logger.info("Running regex extraction...")
    for col in ["regex_extracted_endpoints", "regex_confidence", "regex_pattern"]:
        if col not in df_with_abstract.columns:
            df_with_abstract[col] = ""

    regex_mask = _is_missing(df_with_abstract["regex_extracted_endpoints"])
    logger.info("Regex extraction required for %d/%d rows", regex_mask.sum(), len(df_with_abstract))
    regex_outcomes: list[str] = []
    regex_confidences: list[str] = []
    regex_patterns: list[str] = []

    for _, row in tqdm(
        df_with_abstract[regex_mask].iterrows(),
        total=int(regex_mask.sum()),
        desc="Regex extraction",
    ):
        result = extract_endpoints_regex(row["abstract"])
        regex_outcomes.append(" | ".join(result.primary_outcomes))
        regex_confidences.append(result.confidence)
        regex_patterns.append(result.matched_pattern)

    df_with_abstract.loc[regex_mask, "regex_extracted_endpoints"] = regex_outcomes
    df_with_abstract.loc[regex_mask, "regex_confidence"] = regex_confidences
    df_with_abstract.loc[regex_mask, "regex_pattern"] = regex_patterns

    # LLM extraction
    logger.info("Running LLM extraction...")
    for col in ["llm_extracted_endpoints", "llm_confidence", "llm_extraction_evidence"]:
        if col not in df_with_abstract.columns:
            df_with_abstract[col] = ""

    llm_mask = _is_missing(df_with_abstract["llm_extracted_endpoints"])
    logger.info("LLM extraction required for %d/%d rows", llm_mask.sum(), len(df_with_abstract))
    llm_indices = df_with_abstract[llm_mask].index.tolist()
    for i, idx in enumerate(tqdm(llm_indices, total=len(llm_indices), desc="LLM extraction"), start=1):
        row = df_with_abstract.loc[idx]
        result = extract_endpoints_llm(row["abstract"], config)
        df_with_abstract.at[idx, "llm_extracted_endpoints"] = " | ".join(result.primary_outcomes)
        df_with_abstract.at[idx, "llm_confidence"] = result.confidence
        df_with_abstract.at[idx, "llm_extraction_evidence"] = result.extraction_evidence
        df_with_abstract.at[idx, "extraction_model_deployment"] = result.model_deployment
        df_with_abstract.at[idx, "extraction_model_id"] = result.model_id

        if i % CHECKPOINT_EVERY == 0:
            save_processed_csv(df_with_abstract, "stage3_extracted_endpoints.csv")
            logger.info(
                "Stage 3 checkpoint saved (%d/%d LLM rows)",
                i,
                len(llm_indices),
            )

    # Use LLM as primary, regex as fallback (vectorized — R1-3)
    llm_col = df_with_abstract["llm_extracted_endpoints"].fillna("").astype(str).str.strip()
    regex_col = df_with_abstract["regex_extracted_endpoints"].fillna("").astype(str).str.strip()
    has_llm = llm_col.astype(bool)
    df_with_abstract["published_endpoint"] = llm_col.where(has_llm, regex_col)
    df_with_abstract["extraction_method_used"] = has_llm.map({True: "llm", False: "regex"})

    save_processed_csv(df_with_abstract, "stage3_extracted_endpoints.csv")
    return df_with_abstract


# ======================================================================
# Stage 4: Semantic comparison
# ======================================================================


def stage_4_compare_endpoints(config: PipelineConfig) -> pd.DataFrame:
    """Compare registered vs. published endpoints."""
    logger.info("=== Stage 4: Comparing endpoints ===")
    df = load_processed_csv("stage3_extracted_endpoints.csv")
    _require_columns(
        df,
        ["nct_id", "pmid", "registered_endpoint_measures", "published_endpoint"],
        "Stage 4",
    )

    has_both = (
        df["registered_endpoint_measures"].notna()
        & (df["registered_endpoint_measures"].str.strip() != "")
        & df["published_endpoint"].notna()
        & (df["published_endpoint"].str.strip() != "")
    )
    df_compare = df[has_both].copy()
    existing_stage4 = _load_stage_if_exists("stage4_comparison_results.csv")
    df_compare = _attach_existing_values(
        df_compare,
        existing_stage4,
        key_cols=["nct_id", "pmid"],
        value_cols=[
            "embedding_similarity",
            "needs_review",
            "llm_judge_score",
            "llm_judge_explanation",
            "llm_judge_same_concept",
            "potential_discrepancy",
            "judge_model_deployment",
            "judge_model_id",
        ],
    )
    logger.info("%d pairs ready for comparison", len(df_compare))

    # Cast numeric columns that may have been loaded as strings from CSV during resume
    for _num_col in ["embedding_similarity", "llm_judge_score"]:
        if _num_col in df_compare.columns:
            df_compare[_num_col] = pd.to_numeric(df_compare[_num_col], errors="coerce")

    thresholds = config.similarity

    # Embedding similarity (batch)
    logger.info("Computing embedding similarities...")
    if "embedding_similarity" not in df_compare.columns:
        df_compare["embedding_similarity"] = None
    emb_mask = df_compare["embedding_similarity"].isna()
    logger.info("Embedding computation required for %d/%d rows", emb_mask.sum(), len(df_compare))

    if emb_mask.sum() > 0:
        reg_texts = df_compare.loc[emb_mask, "registered_endpoint_measures"].tolist()
        pub_texts = df_compare.loc[emb_mask, "published_endpoint"].tolist()
        batch_results = compare_endpoints_embedding_batch(reg_texts, pub_texts)
        emb_scores = [r.cosine_similarity for r in batch_results]
        df_compare.loc[emb_mask, "embedding_similarity"] = emb_scores

    df_compare["needs_review"] = df_compare["embedding_similarity"] < thresholds.high_similarity

    n_review = df_compare["needs_review"].sum()
    logger.info("%d/%d pairs flagged for LLM judge review", n_review, len(df_compare))

    # LLM judge for flagged cases
    logger.info("Running LLM judge on flagged cases...")
    for col, default in [
        ("llm_judge_score", None),
        ("llm_judge_explanation", ""),
        ("llm_judge_same_concept", None),
    ]:
        if col not in df_compare.columns:
            df_compare[col] = default

    judge_mask = df_compare["needs_review"] & df_compare["llm_judge_score"].isna()
    logger.info("LLM judge required for %d/%d rows", judge_mask.sum(), len(df_compare))
    judge_indices = df_compare[judge_mask].index.tolist()
    for i, idx in enumerate(tqdm(judge_indices, total=len(judge_indices), desc="LLM judge"), start=1):
        row = df_compare.loc[idx]
        result = compare_endpoints_llm_judge(
            registered_endpoint=row["registered_endpoint_measures"],
            registered_timeframe=row.get("registered_endpoint_timeframes", ""),
            published_endpoint=row["published_endpoint"],
            config=config,
        )
        df_compare.at[idx, "llm_judge_score"] = result.similarity_score
        df_compare.at[idx, "llm_judge_explanation"] = result.explanation
        df_compare.at[idx, "llm_judge_same_concept"] = result.same_concept
        df_compare.at[idx, "judge_model_deployment"] = result.model_deployment
        df_compare.at[idx, "judge_model_id"] = result.model_id

        if i % CHECKPOINT_EVERY == 0:
            df_compare["potential_discrepancy"] = (df_compare["embedding_similarity"] < thresholds.low_similarity) | (
                df_compare["llm_judge_score"].notna()
                & (df_compare["llm_judge_score"] <= thresholds.llm_judge_discrepancy_threshold)
            )
            save_processed_csv(df_compare, "stage4_comparison_results.csv")
            logger.info(
                "Stage 4 checkpoint saved (%d/%d judge rows)",
                i,
                len(judge_indices),
            )

    df_compare["potential_discrepancy"] = (df_compare["embedding_similarity"] < thresholds.low_similarity) | (
        df_compare["llm_judge_score"].notna()
        & (df_compare["llm_judge_score"] <= thresholds.llm_judge_discrepancy_threshold)
    )

    save_processed_csv(df_compare, "stage4_comparison_results.csv")
    logger.info(
        "Potential discrepancies: %d/%d (%.0f%%)",
        df_compare["potential_discrepancy"].sum(),
        len(df_compare),
        100 * df_compare["potential_discrepancy"].mean(),
    )
    return df_compare


# ======================================================================
# Stage 5: Classify discrepancies
# ======================================================================


def stage_5_classify(config: PipelineConfig) -> pd.DataFrame:
    """Classify the type of each flagged discrepancy."""
    logger.info("=== Stage 5: Classifying discrepancies ===")
    df = load_processed_csv("stage4_comparison_results.csv")
    _require_columns(
        df,
        ["nct_id", "pmid", "potential_discrepancy", "registered_endpoint_measures", "published_endpoint"],
        "Stage 5",
    )
    existing_stage5 = _load_stage_if_exists("stage5_final_results.csv")
    df = _attach_existing_values(
        df,
        existing_stage5,
        key_cols=["nct_id", "pmid"],
        value_cols=[
            "classification",
            "classification_explanation",
            "specific_changes",
            "classification_model_deployment",
            "classification_model_id",
        ],
    )

    flagged = df[df["potential_discrepancy"].astype(str).str.strip().str.upper() == "TRUE"].copy()
    logger.info("Classifying %d flagged discrepancies", len(flagged))

    for col in ["classification", "classification_explanation", "specific_changes"]:
        if col not in flagged.columns:
            flagged[col] = ""
    classify_mask = _is_missing(flagged["classification"])
    logger.info("LLM classification required for %d/%d flagged rows", classify_mask.sum(), len(flagged))

    classify_indices = flagged[classify_mask].index.tolist()
    for i, idx in enumerate(tqdm(classify_indices, total=len(classify_indices), desc="Classification"), start=1):
        row = flagged.loc[idx]
        result = classify_discrepancy(
            registered_endpoints=row["registered_endpoint_measures"],
            registered_timeframe=row.get("registered_endpoint_timeframes", ""),
            published_endpoints=row["published_endpoint"],
            config=config,
        )
        flagged.at[idx, "classification"] = result.classification.value
        flagged.at[idx, "classification_explanation"] = result.explanation
        flagged.at[idx, "specific_changes"] = " | ".join(result.specific_changes)
        flagged.at[idx, "classification_model_deployment"] = result.model_deployment
        flagged.at[idx, "classification_model_id"] = result.model_id

        if i % CHECKPOINT_EVERY == 0:
            checkpoint_df = pd.concat([flagged, _prepare_non_flagged(df)], ignore_index=True)
            checkpoint_df = checkpoint_df.sort_values("nct_id").reset_index(drop=True)
            save_processed_csv(checkpoint_df, "stage5_final_results.csv")
            logger.info(
                "Stage 5 checkpoint saved (%d/%d classification rows)",
                i,
                len(classify_indices),
            )

    non_flagged = _prepare_non_flagged(df)

    full_df = pd.concat([flagged, non_flagged], ignore_index=True)
    full_df = full_df.sort_values("nct_id").reset_index(drop=True)

    save_processed_csv(full_df, "stage5_final_results.csv")

    counts = full_df["classification"].value_counts()
    logger.info("Classification summary:\n%s", counts.to_string())

    return full_df


# ======================================================================
# Run full pipeline
# ======================================================================


def run_full_pipeline(config: PipelineConfig | None = None) -> pd.DataFrame:
    """Run the complete pipeline end-to-end."""
    if config is None:
        config = PipelineConfig()

    setup_logging()
    logger.info("Starting Moving Goalpost pipeline")
    logger.info("Config: therapeutic_area=%s, max_trials=%d", config.therapeutic_area, config.max_trials)

    stage_1_fetch_trials(config)
    stage_2_match_publications(config)
    stage_3_extract_endpoints(config)
    stage_4_compare_endpoints(config)
    df = stage_5_classify(config)

    logger.info("Pipeline complete. Final results: %d rows", len(df))
    return df


if __name__ == "__main__":
    run_full_pipeline()

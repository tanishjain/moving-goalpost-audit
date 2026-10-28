#!/usr/bin/env python3
"""
Create a reproducible manual adjudication sample for endpoint discrepancy analysis.
"""

from pathlib import Path

import pandas as pd

from moving_goalpost.config import PROCESSED_DIR, VALIDATION_DIR


TARGET_SAMPLE_SIZE = 100
RANDOM_SEED = 42
DISCREPANCY_CLASSES = [
    "MODIFIED",
    "MULTIPLE_CHANGES",
    "ADDED",
    "COMPOSITE_SUBSET",
    "TIMEFRAME_CHANGE",
    "UNREPORTED_IN_ABSTRACT",
]
ADJUDICATION_LABELS = [
    "GENUINE_DISCREPANCY",
    "NO_DISCREPANCY",
    "UNCLEAR",
]


def _safe_sample(df: pd.DataFrame, n: int, random_state: int = RANDOM_SEED) -> pd.DataFrame:
    if df.empty or n <= 0:
        return df.iloc[0:0].copy()
    return df.sample(n=min(n, len(df)), random_state=random_state)


def create_validation_sample(
    input_csv: str = str(PROCESSED_DIR / "stage5_final_results.csv"),
    output_csv: str = str(VALIDATION_DIR / "manual_validation_sample.csv"),
) -> pd.DataFrame:
    df = pd.read_csv(input_csv)

    validation_samples: list[pd.DataFrame] = []

    # 1) Ensure representation across discrepancy classes.
    for classification in DISCREPANCY_CLASSES:
        subset = df[df["classification"] == classification]
        if len(subset) == 0:
            continue
        n_samples = min(max(1, int(len(subset) * 0.15)), 20 if classification == "MODIFIED" else 10)
        validation_samples.append(_safe_sample(subset, n_samples))

    # 2) Add CONSISTENT cases as negatives.
    consistent_subset = df[df["classification"] == "CONSISTENT"]
    if not consistent_subset.empty:
        validation_samples.append(_safe_sample(consistent_subset, 15))

    # 3) Oversample likely positives for precision estimation.
    #    Lower judge scores = lower similarity = higher confidence that discrepancy is real.
    #    Score <= 2: high confidence discrepancy; Score == 3: medium confidence (borderline).
    is_flagged = df["potential_discrepancy"].astype(str).str.strip().str.upper() == "TRUE"
    judge_score_numeric = pd.to_numeric(df["llm_judge_score"], errors="coerce")
    high_confidence = df[(judge_score_numeric <= 2) & is_flagged]
    if not high_confidence.empty:
        validation_samples.append(_safe_sample(high_confidence, 20))

    medium_confidence = df[(judge_score_numeric == 3) & is_flagged]
    if not medium_confidence.empty:
        validation_samples.append(_safe_sample(medium_confidence, 15))

    if not validation_samples:
        raise ValueError("No rows available to sample from stage5 results.")

    validation_df = pd.concat(validation_samples, ignore_index=True).drop_duplicates(subset=["nct_id", "pmid"])
    if len(validation_df) > TARGET_SAMPLE_SIZE:
        validation_df = _safe_sample(validation_df, TARGET_SAMPLE_SIZE)

    # Two-reviewer adjudication template. Keep labels blank until real review is complete.
    validation_df["reviewer_a_label"] = ""
    validation_df["reviewer_a_notes"] = ""
    validation_df["reviewer_a_id"] = ""
    validation_df["reviewer_a_date"] = ""
    validation_df["reviewer_b_label"] = ""
    validation_df["reviewer_b_notes"] = ""
    validation_df["reviewer_b_id"] = ""
    validation_df["reviewer_b_date"] = ""
    validation_df["adjudicator_label"] = ""
    validation_df["adjudicator_notes"] = ""
    validation_df["adjudicator_id"] = ""
    validation_df["adjudication_date"] = ""

    # Keep legacy columns for backwards compatibility, but do not prefill.
    validation_df["manual_validation_status"] = ""
    validation_df["manual_validation_notes"] = ""
    validation_df["reviewer"] = ""
    validation_df["validation_date"] = ""

    key_columns = [
        "nct_id",
        "trial_title",
        "registered_endpoint_measures",
        "registered_endpoint_descriptions",
        "published_endpoint",
        "extraction_method_used",
        "classification",
        "classification_explanation",
        "llm_judge_score",
        "llm_judge_explanation",
        "potential_discrepancy",
        "pmid",
        "pub_title",
        "abstract",
        "doi",
        "reviewer_a_label",
        "reviewer_a_notes",
        "reviewer_a_id",
        "reviewer_a_date",
        "reviewer_b_label",
        "reviewer_b_notes",
        "reviewer_b_id",
        "reviewer_b_date",
        "adjudicator_label",
        "adjudicator_notes",
        "adjudicator_id",
        "adjudication_date",
        "manual_validation_status",
        "manual_validation_notes",
        "reviewer",
        "validation_date",
    ]

    for col in key_columns:
        if col not in validation_df.columns:
            validation_df[col] = ""

    final_df = validation_df[key_columns].copy()
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    final_df.to_csv(output_csv, index=False)

    print(f"Created validation adjudication sample with {len(final_df)} cases")
    print(f"Allowed reviewer labels: {ADJUDICATION_LABELS}")
    print("Classification distribution in sample:")
    print(final_df["classification"].value_counts())
    print("\nLLM judge score distribution:")
    print(final_df["llm_judge_score"].value_counts())
    n_flagged = (final_df["potential_discrepancy"].astype(str).str.strip().str.upper() == "TRUE").sum()
    print(f"\nPotential discrepancies in sample: {int(n_flagged)}")
    return final_df


if __name__ == "__main__":
    create_validation_sample()

"""Manual validation helpers.

Generates validation samples and tracking sheets for human review.
"""

import logging

import pandas as pd
import numpy as np

from moving_goalpost.config import VALIDATION_DIR

logger = logging.getLogger(__name__)


def generate_validation_sample(
    df: pd.DataFrame,
    n_sample: int = 50,
    stratify_by: str | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate a random sample for manual validation."""
    rng = np.random.default_rng(seed)

    if stratify_by and stratify_by in df.columns:
        groups = df.groupby(stratify_by)
        samples = []
        for name, group_df in groups:
            n_group = max(1, round(n_sample * len(group_df) / len(df)))
            n_group = min(n_group, len(group_df))
            idx = rng.choice(group_df.index, size=n_group, replace=False)
            samples.append(df.loc[idx])
        sample_df = pd.concat(samples)
        # Shuffle before truncating to avoid alphabetical bias from groupby ordering
        sample_df = sample_df.sample(frac=1, random_state=seed).head(n_sample)
    else:
        idx = rng.choice(df.index, size=min(n_sample, len(df)), replace=False)
        sample_df = df.loc[idx]

    sample_df = sample_df.copy()

    return sample_df


def save_validation_sheet(df: pd.DataFrame, filename: str = "validation_sample.csv") -> str:
    """Save validation sample as a CSV for manual review."""
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    path = VALIDATION_DIR / filename
    df.to_csv(path, index=False)
    logger.info("Saved validation sample (%d rows) -> %s", len(df), path)
    return str(path)


def compute_agreement(validation_df: pd.DataFrame) -> dict:
    """Compute agreement metrics between system and manual annotations."""
    df = validation_df.dropna(subset=["classification", "manual_classification"]).copy()
    df["classification_norm"] = df["classification"].astype(str).str.strip().str.upper()
    df["manual_classification_norm"] = df["manual_classification"].astype(str).str.strip().str.upper()
    df = df[df["manual_classification_norm"] != ""]

    if len(df) == 0:
        return {"error": "No manual annotations found"}

    system = df["classification_norm"].values
    manual = df["manual_classification_norm"].values

    accuracy = np.mean(system == manual)

    system_disc = (system != "CONSISTENT").astype(int)
    manual_disc = (manual != "CONSISTENT").astype(int)

    tp = np.sum((system_disc == 1) & (manual_disc == 1))
    fp = np.sum((system_disc == 1) & (manual_disc == 0))
    fn = np.sum((system_disc == 0) & (manual_disc == 1))
    tn = np.sum((system_disc == 0) & (manual_disc == 0))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    p_o = (tp + tn) / len(df) if len(df) > 0 else 0
    p_e = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (len(df) ** 2) if len(df) > 0 else 0
    kappa = (p_o - p_e) / (1 - p_e) if (1 - p_e) > 0 else 0.0

    return {
        "n_validated": len(df),
        "accuracy_exact": accuracy,
        "binary_precision": precision,
        "binary_recall": recall,
        "binary_f1": f1,
        "binary_cohens_kappa": kappa,
        "tp": int(tp),
        "fp": int(fp),
        "fn": int(fn),
        "tn": int(tn),
    }

"""Statistical analysis: prevalence, stratified analysis, association tests."""

import logging

import pandas as pd
import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


def compute_prevalence(
    df: pd.DataFrame,
    discrepancy_col: str = "classification",
    consistent_value: str = "CONSISTENT",
) -> dict:
    """Compute overall and by-type discrepancy prevalence."""
    n_total = len(df)
    n_discrepant = len(df[df[discrepancy_col] != consistent_value])
    rate = n_discrepant / n_total if n_total > 0 else 0.0

    ci_low, ci_high = _wilson_ci(n_discrepant, n_total) if n_total > 0 else (0.0, 0.0)

    type_counts = df[discrepancy_col].value_counts().to_dict()
    type_rates = {k: v / n_total for k, v in type_counts.items()}

    return {
        "n_total": n_total,
        "n_discrepant": n_discrepant,
        "discrepancy_rate": rate,
        "ci_95_lower": ci_low,
        "ci_95_upper": ci_high,
        "by_type_counts": type_counts,
        "by_type_rates": type_rates,
    }


def stratified_analysis(
    df: pd.DataFrame,
    stratify_col: str,
    discrepancy_col: str = "classification",
    consistent_value: str = "CONSISTENT",
) -> pd.DataFrame:
    """Compute discrepancy rates stratified by a grouping variable."""
    rows = []
    for group, group_df in df.groupby(stratify_col):
        n = len(group_df)
        n_disc = len(group_df[group_df[discrepancy_col] != consistent_value])
        rate = n_disc / n if n > 0 else 0.0
        ci_low, ci_high = _wilson_ci(n_disc, n) if n > 0 else (0.0, 0.0)
        rows.append(
            {
                "group": group,
                "n": n,
                "n_discrepant": n_disc,
                "discrepancy_rate": rate,
                "ci_95_lower": ci_low,
                "ci_95_upper": ci_high,
            }
        )

    return pd.DataFrame(rows).sort_values("discrepancy_rate", ascending=False)


def test_sponsor_association(
    df: pd.DataFrame,
    discrepancy_col: str = "classification",
    consistent_value: str = "CONSISTENT",
    sponsor_col: str = "sponsor_type",
) -> dict:
    """Chi-square test for association between sponsor type and discrepancy."""
    df = df.copy()
    df["is_discrepant"] = (df[discrepancy_col] != consistent_value).astype(int)
    df["is_industry"] = (df[sponsor_col] == "INDUSTRY").astype(int)

    table = pd.crosstab(df["is_industry"], df["is_discrepant"])

    if table.shape != (2, 2):
        logger.warning("Cannot compute chi-square: table is not 2x2. Shape: %s", table.shape)
        return {"error": "Insufficient groups for chi-square test"}

    chi2, p_value, dof, expected = stats.chi2_contingency(table)

    # table rows: is_industry (0=non-industry, 1=industry)
    # table cols: is_discrepant (0=consistent, 1=discrepant)
    a = table.loc[1, 1]  # industry & discrepant
    b = table.loc[1, 0]  # industry & consistent
    c = table.loc[0, 1]  # non-industry & discrepant
    d = table.loc[0, 0]  # non-industry & consistent
    odds_ratio = (a * d) / (b * c) if (b * c) > 0 else None

    return {
        "chi2": chi2,
        "p_value": p_value,
        "dof": dof,
        "odds_ratio_industry": odds_ratio,
        "contingency_table": table.to_dict(),
        "industry_discrepancy_rate": a / (a + b) if (a + b) > 0 else 0,
        "non_industry_discrepancy_rate": c / (c + d) if (c + d) > 0 else 0,
    }


def _wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return 0.0, 0.0
    p_hat = successes / n
    denom = 1 + z**2 / n
    center = (p_hat + z**2 / (2 * n)) / denom
    margin = z * np.sqrt((p_hat * (1 - p_hat) + z**2 / (4 * n)) / n) / denom
    return max(0.0, center - margin), min(1.0, center + margin)

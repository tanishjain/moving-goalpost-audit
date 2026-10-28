"""Trial-to-publication matching logic.

Matches ClinicalTrials.gov records to their corresponding PubMed publications
using a tiered strategy: NCT ID -> title keywords -> condition+intervention.
"""

import json
import logging
import re
from enum import Enum

import pandas as pd
from pydantic import BaseModel

from moving_goalpost.data.ctgov import TrialRecord
from moving_goalpost.data.pubmed import PubMedArticle, search_by_nct_id, search_by_keywords
from moving_goalpost.config import PipelineConfig

logger = logging.getLogger(__name__)
ENDPOINT_TEXT_SEPARATOR = " <SEP> "

# Generic intervention terms excluded from relevance matching.
_GENERIC_INTERVENTIONS: frozenset[str] = frozenset(
    {
        "placebo",
        "saline",
        "standard therapy",
        "standard of care",
        "chemotherapy",
        "radiotherapy",
        "radiation",
        "surgery",
        "exercise",
        "supportive care",
        "best supportive care",
        "observation",
        "no treatment",
        "sham",
    }
)


class MatchMethod(str, Enum):
    """How a trial was matched to a publication."""

    NCT_ID = "nct_id"
    TITLE_KEYWORDS = "title_keywords"
    CONDITION_INTERVENTION = "condition_intervention"
    NOT_FOUND = "not_found"


class TrialPublicationPair(BaseModel):
    """A matched trial-publication pair with match metadata."""

    nct_id: str
    trial_title: str
    registered_endpoints: list[dict]
    sponsor: str
    sponsor_type: str
    completion_date: str

    pmid: str = ""
    pub_title: str = ""
    abstract: str = ""
    pub_date: str = ""
    doi: str = ""
    pmc_id: str = ""
    journal: str = ""

    match_method: MatchMethod = MatchMethod.NOT_FOUND
    match_confidence: str = "none"  # high, medium, low, none
    nct_in_abstract: bool | None = None
    intervention_in_abstract: bool | None = None
    secondary_publication: bool | None = None


# ---------------------------------------------------------------------------
# Module-level helper functions (previously closures inside
# match_trial_to_publication; refactored for direct testability — R1-5/R1-6).
# ---------------------------------------------------------------------------


def _normalize_text(text: str) -> str:
    """Lowercase and strip non-alphanumeric characters (except whitespace)."""
    return re.sub(r"[^a-z0-9\s]+", " ", text.lower())


def _extract_title_keywords(title: str, max_words: int = 6) -> str:
    """Extract key terms from a trial title for PubMed search."""
    stopwords = {
        "a",
        "an",
        "the",
        "of",
        "in",
        "for",
        "and",
        "or",
        "to",
        "with",
        "study",
        "trial",
        "randomized",
        "randomised",
        "controlled",
        "double-blind",
        "double",
        "blind",
        "open-label",
        "open",
        "label",
        "phase",
        "multicenter",
        "multicentre",
        "prospective",
        "compared",
        "comparison",
        "patients",
        "subjects",
        "participants",
        "iii",
        "ii",
        "iv",
        "3",
        "2",
        "4",
    }
    words = title.lower().split()
    keywords = [w for w in words if w not in stopwords and len(w) > 2]
    return " ".join(keywords[:max_words])


def _intervention_terms(interventions: list[str]) -> list[str]:
    """Extract meaningful intervention terms, filtering generic comparators."""
    terms: set[str] = set()
    for raw in interventions:
        if not raw:
            continue
        clean = _normalize_text(raw)
        if not clean.strip():
            continue
        if clean.strip() in _GENERIC_INTERVENTIONS:
            continue
        # Split on separators and capture both phrases and tokens
        parts = re.split(r"[;,/\\+]+", clean)
        for part in parts:
            part = part.strip()
            if not part or part in _GENERIC_INTERVENTIONS:
                continue
            if len(part) >= 4:
                terms.add(part)
            for token in part.split():
                if len(token) >= 4 and token not in _GENERIC_INTERVENTIONS:
                    terms.add(token)
    return sorted(terms)


def _mentions_intervention(
    article: PubMedArticle,
    interventions: list[str],
) -> bool:
    """Check whether *article* text mentions at least one intervention term."""
    terms = _intervention_terms(interventions)
    if not terms:
        return True  # No reliable intervention terms to check
    text = _normalize_text(f"{article.title} {article.abstract}")
    for term in terms:
        if re.search(rf"\b{re.escape(term)}\b", text):
            return True
    return False


def _is_secondary_publication(article: PubMedArticle) -> bool:
    """Heuristic check for secondary/non-primary publications."""
    title_text = _normalize_text(article.title)
    abstract_text = _normalize_text(article.abstract)
    combined_text = f"{title_text} {abstract_text}"

    # Strong title-level signals for secondary/non-primary publications.
    secondary_title_flags = [
        "secondary analysis",
        "post hoc analysis",
        "pooled analysis",
        "systematic review",
        "meta analysis",
        "study protocol",
        "trial protocol",
        "design and rationale",
        "rationale and design",
        "ancillary study",
        "subgroup analysis",
        "retrospective analysis",
        "cost effectiveness",
        "economic evaluation",
    ]
    if any(flag in title_text for flag in secondary_title_flags):
        return True

    # Require more explicit phrasing in abstracts to avoid over-filtering.
    secondary_abstract_flags = [
        "this secondary analysis",
        "in this secondary analysis",
        "post hoc analysis",
        "pooled analysis",
        "systematic review",
        "meta analysis",
        "retrospective analysis",
        "ancillary study",
        "subgroup analysis",
        "exploratory analysis",
        "biomarker analysis",
        "correlative analysis",
    ]

    primary_signals = [
        "primary analysis",
        "primary endpoint",
        "primary endpoints",
        "primary results",
        "phase 3 trial",
        "randomized phase",
    ]

    # Positive primary signals override weak abstract-only secondary hints.
    if any(signal in combined_text for signal in primary_signals):
        return False

    return any(flag in abstract_text for flag in secondary_abstract_flags)


def _select_best_article(
    articles: list[PubMedArticle],
    *,
    nct_id: str,
    interventions: list[str],
    require_intervention: bool,
    exclude_secondary: bool,
    require_nct_mention: bool,
) -> PubMedArticle | None:
    """Score and select the best-matching article from *articles*."""
    if not articles:
        return None
    candidates = [a for a in articles if a.abstract.strip()] or articles
    scored: list[tuple[int, PubMedArticle]] = []
    for article in candidates:
        if exclude_secondary and _is_secondary_publication(article):
            logger.debug("Rejecting PMID %s as secondary/pooled analysis", article.pmid)
            continue
        if require_nct_mention and nct_id.lower() not in (article.abstract + article.title).lower():
            logger.debug("Rejecting PMID %s due to missing NCT mention", article.pmid)
            continue
        if require_intervention and not _mentions_intervention(article, interventions):
            logger.debug("Rejecting PMID %s due to missing intervention in abstract/title", article.pmid)
            continue
        score = 0
        if article.abstract.strip():
            score += 1
        if nct_id.lower() in (article.abstract + article.title).lower():
            score += 2
        if _mentions_intervention(article, interventions):
            score += 2
        scored.append((score, article))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _fill_pair(
    pair: TrialPublicationPair,
    article: PubMedArticle,
    *,
    nct_id: str,
    interventions: list[str],
) -> None:
    """Populate *pair* fields from a matched *article*."""
    pair.pmid = article.pmid
    pair.pub_title = article.title
    pair.abstract = article.abstract
    pair.pub_date = article.pub_date
    pair.doi = article.doi
    pair.pmc_id = article.pmc_id
    pair.journal = article.journal
    pair.nct_in_abstract = nct_id.lower() in (article.abstract + article.title).lower()
    pair.intervention_in_abstract = _mentions_intervention(article, interventions)
    pair.secondary_publication = _is_secondary_publication(article)


# ---------------------------------------------------------------------------
# Main matching entry point
# ---------------------------------------------------------------------------


def match_trial_to_publication(
    trial: TrialRecord,
    config: PipelineConfig | None = None,
) -> TrialPublicationPair:
    """Try to match a single trial to its publication using tiered search."""
    if config is None:
        config = PipelineConfig()

    base_pair = TrialPublicationPair(
        nct_id=trial.nct_id,
        trial_title=trial.title,
        registered_endpoints=[ep.model_dump() for ep in trial.primary_endpoints],
        sponsor=trial.sponsor,
        sponsor_type=trial.sponsor_type,
        completion_date=trial.completion_date,
    )

    has_terms = bool(_intervention_terms(trial.interventions))

    def _best(articles: list[PubMedArticle], *, exclude_secondary: bool) -> PubMedArticle | None:
        return _select_best_article(
            articles,
            nct_id=trial.nct_id,
            interventions=trial.interventions,
            require_intervention=has_terms,
            exclude_secondary=exclude_secondary,
            require_nct_mention=False,
        )

    def _try_match(articles: list[PubMedArticle]) -> PubMedArticle | None:
        best = _best(articles, exclude_secondary=True)
        if not best:
            best = _best(articles, exclude_secondary=False)
        return best

    # --- Strategy 1: NCT ID search ---
    articles = search_by_nct_id(trial.nct_id)
    best = _try_match(articles)
    if best:
        _fill_pair(base_pair, best, nct_id=trial.nct_id, interventions=trial.interventions)
        base_pair.match_method = MatchMethod.NCT_ID
        base_pair.match_confidence = "high"
        logger.debug("%s matched by NCT ID -> PMID %s", trial.nct_id, best.pmid)
        return base_pair

    # --- Strategy 2: Title keywords ---
    title_kw = _extract_title_keywords(trial.title)
    condition = trial.conditions[0] if trial.conditions else ""
    if title_kw:
        articles = search_by_keywords(title_keywords=title_kw, condition=condition, max_results=5)
        best = _try_match(articles)
        if best:
            _fill_pair(base_pair, best, nct_id=trial.nct_id, interventions=trial.interventions)
            base_pair.match_method = MatchMethod.TITLE_KEYWORDS
            base_pair.match_confidence = "medium"
            logger.debug("%s matched by title keywords -> PMID %s", trial.nct_id, best.pmid)
            return base_pair

    # --- Strategy 3: Condition + intervention + year ---
    intervention = trial.interventions[0] if trial.interventions else ""
    year = trial.completion_date[:4] if trial.completion_date else ""
    if condition and intervention:
        articles = search_by_keywords(
            title_keywords="",
            condition=condition,
            intervention=intervention,
            year=year,
            max_results=5,
        )
        best = _try_match(articles)
        if best:
            _fill_pair(base_pair, best, nct_id=trial.nct_id, interventions=trial.interventions)
            base_pair.match_method = MatchMethod.CONDITION_INTERVENTION
            base_pair.match_confidence = "low"
            logger.debug("%s matched by condition+intervention -> PMID %s", trial.nct_id, best.pmid)
            return base_pair

    logger.debug("%s: no publication found", trial.nct_id)
    return base_pair


def match_trials_batch(
    trials: list[TrialRecord],
    config: PipelineConfig | None = None,
) -> list[TrialPublicationPair]:
    """Match a batch of trials to publications."""
    pairs = []
    for i, trial in enumerate(trials):
        logger.info("Matching trial %d/%d: %s", i + 1, len(trials), trial.nct_id)
        pair = match_trial_to_publication(trial, config)
        pairs.append(pair)

    matched = sum(1 for p in pairs if p.match_method != MatchMethod.NOT_FOUND)
    by_method = {}
    for p in pairs:
        by_method[p.match_method] = by_method.get(p.match_method, 0) + 1

    logger.info(
        "Matching complete: %d/%d matched (%.0f%%). Methods: %s",
        matched,
        len(pairs),
        100 * matched / len(pairs) if pairs else 0,
        by_method,
    )
    return pairs


def pairs_to_dataframe(pairs: list[TrialPublicationPair]) -> pd.DataFrame:
    """Convert a list of TrialPublicationPair to a flat DataFrame."""
    rows = []
    for p in pairs:
        endpoint_measures = ENDPOINT_TEXT_SEPARATOR.join(ep["measure"] for ep in p.registered_endpoints)
        endpoint_descriptions = ENDPOINT_TEXT_SEPARATOR.join(ep.get("description", "") for ep in p.registered_endpoints)
        endpoint_timeframes = ENDPOINT_TEXT_SEPARATOR.join(ep.get("timeframe", "") for ep in p.registered_endpoints)

        rows.append(
            {
                "nct_id": p.nct_id,
                "trial_title": p.trial_title,
                "registered_endpoint_measures": endpoint_measures,
                "registered_endpoint_descriptions": endpoint_descriptions,
                "registered_endpoint_timeframes": endpoint_timeframes,
                "registered_endpoints_json": json.dumps(p.registered_endpoints, ensure_ascii=False),
                "num_registered_endpoints": len(p.registered_endpoints),
                "sponsor": p.sponsor,
                "sponsor_type": p.sponsor_type,
                "completion_date": p.completion_date,
                "pmid": p.pmid,
                "pub_title": p.pub_title,
                "abstract": p.abstract,
                "pub_date": p.pub_date,
                "doi": p.doi,
                "pmc_id": p.pmc_id,
                "journal": p.journal,
                "match_method": p.match_method.value,
                "match_confidence": p.match_confidence,
                "nct_in_abstract": p.nct_in_abstract,
                "intervention_in_abstract": p.intervention_in_abstract,
                "secondary_publication": p.secondary_publication,
            }
        )

    return pd.DataFrame(rows)

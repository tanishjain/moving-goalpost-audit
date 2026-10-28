"""ClinicalTrials.gov v2 API client.

Fetches completed trials and their registered endpoints.
Caches all raw API responses to data/raw/ctgov/.
"""

import logging
import time
from typing import Any

import requests
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from moving_goalpost.config import PipelineConfig, RAW_DIR
from moving_goalpost.utils.io import load_cached_json, save_cached_json

logger = logging.getLogger(__name__)

CTGOV_BASE_URL = "https://clinicaltrials.gov/api/v2"
CACHE_DIR = RAW_DIR / "ctgov"


def _log_retry(retry_state) -> None:
    logger.warning(
        "Retrying CT.gov request (attempt %d) after %s",
        retry_state.attempt_number,
        type(retry_state.outcome.exception()).__name__,
    )


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class RegisteredEndpoint(BaseModel):
    """A primary outcome measure as registered on ClinicalTrials.gov."""

    measure: str
    description: str = ""
    timeframe: str = ""


class TrialRecord(BaseModel):
    """Core fields we extract from a ClinicalTrials.gov study."""

    nct_id: str
    title: str
    status: str
    phase: str
    conditions: list[str] = []
    interventions: list[str] = []
    sponsor: str = ""
    sponsor_type: str = ""  # INDUSTRY, FED, OTHER, NETWORK, INDIV
    primary_endpoints: list[RegisteredEndpoint] = []
    completion_date: str = ""
    results_first_post_date: str = ""
    enrollment: int | None = None
    first_posted_date: str = ""
    last_update_posted_date: str = ""


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


@retry(
    retry=retry_if_exception_type(
        (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError)
    ),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    stop=stop_after_attempt(3),  # matches PipelineConfig.max_retries default
    before_sleep=_log_retry,
)
def _ctgov_get(path: str, params: dict[str, Any] | None = None) -> dict:
    """Make a GET request to the CT.gov v2 API with rate limiting."""
    url = f"{CTGOV_BASE_URL}/{path}"
    response = requests.get(url, params=params, timeout=30)
    if response.status_code == 429:
        raise requests.exceptions.HTTPError(f"Rate limited (429) by CT.gov", response=response)
    response.raise_for_status()
    return response.json()


def _parse_trial(study: dict) -> TrialRecord:
    """Parse a CT.gov API study response into a TrialRecord."""
    protocol = study.get("protocolSection", {})
    ident = protocol.get("identificationModule", {})
    status_module = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
    outcomes_module = protocol.get("outcomesModule", {})
    conditions_module = protocol.get("conditionsModule", {})
    interventions_module = protocol.get("armsInterventionsModule", {})

    # Parse primary endpoints
    primary_endpoints = []
    for outcome in outcomes_module.get("primaryOutcomes", []):
        primary_endpoints.append(
            RegisteredEndpoint(
                measure=outcome.get("measure", ""),
                description=outcome.get("description", ""),
                timeframe=outcome.get("timeFrame", ""),
            )
        )

    lead_sponsor = sponsor_module.get("leadSponsor", {})
    phases = design.get("phases", [])
    phase_str = ", ".join(phases) if phases else ""
    conditions = conditions_module.get("conditions", [])
    interventions_raw = interventions_module.get("interventions", [])
    interventions = [i.get("name", "") for i in interventions_raw]
    enrollment_info = design.get("enrollmentInfo", {})
    enrollment = enrollment_info.get("count")

    return TrialRecord(
        nct_id=ident.get("nctId", ""),
        title=ident.get("officialTitle", "") or ident.get("briefTitle", ""),
        status=status_module.get("overallStatus", ""),
        phase=phase_str,
        conditions=conditions,
        interventions=interventions,
        sponsor=lead_sponsor.get("name", ""),
        sponsor_type=lead_sponsor.get("class", ""),
        primary_endpoints=primary_endpoints,
        completion_date=status_module.get("completionDateStruct", {}).get("date", ""),
        results_first_post_date=status_module.get("resultsFirstPostDateStruct", {}).get("date", ""),
        enrollment=enrollment,
        first_posted_date=status_module.get("studyFirstPostDateStruct", {}).get("date", ""),
        last_update_posted_date=status_module.get("lastUpdatePostDateStruct", {}).get("date", ""),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_completed_trials(
    config: PipelineConfig | None = None,
) -> list[TrialRecord]:
    """Search CT.gov for completed Phase III trials matching config criteria.

    Paginates through all results, caching each page.

    Returns:
        List of TrialRecord objects.
    """
    if config is None:
        config = PipelineConfig()

    params: dict[str, Any] = {
        "format": "json",
        "pageSize": 100,
        "filter.overallStatus": ",".join(config.status),
        "query.cond": config.therapeutic_area,
    }

    advanced_clauses: list[str] = []
    if config.phase:
        phase_terms = " OR ".join([f"AREA[Phase]{phase}" for phase in config.phase])
        advanced_clauses.append(f"({phase_terms})")
    if config.date_range_start and config.date_range_end:
        advanced_clauses.append(f"AREA[CompletionDate]RANGE[{config.date_range_start},{config.date_range_end}]")
    if advanced_clauses:
        params["filter.advanced"] = " AND ".join(advanced_clauses)

    phase_key = "+".join(sorted(config.phase)) if config.phase else "none"
    status_key = "+".join(sorted(config.status)) if config.status else "none"
    cache_key = (
        f"search_{config.therapeutic_area}_{phase_key}_{status_key}_"
        f"{config.date_range_start}_{config.date_range_end}_max{config.max_trials}"
    )
    cached = load_cached_json(CACHE_DIR, cache_key)
    if cached is not None:
        logger.info("Loaded %d cached trials for '%s'", len(cached), config.therapeutic_area)
        return [TrialRecord(**t) for t in cached]

    all_trials: list[TrialRecord] = []
    page_token: str | None = None
    page = 0
    parse_failures = 0
    total_studies = 0

    while True:
        if page_token:
            params["pageToken"] = page_token

        logger.info("Fetching CT.gov page %d (have %d trials so far)...", page, len(all_trials))
        data = _ctgov_get("studies", params)

        studies = data.get("studies", [])
        for study in studies:
            total_studies += 1
            try:
                trial = _parse_trial(study)
                if trial.primary_endpoints:
                    all_trials.append(trial)
            except Exception:
                parse_failures += 1
                logger.warning("Failed to parse study", exc_info=True)

        # Guard against systematic parsing failures (e.g., API schema change)
        if total_studies > 0 and parse_failures / total_studies > 0.10:
            raise RuntimeError(
                f"Parse failure rate {parse_failures}/{total_studies} "
                f"({parse_failures / total_studies:.0%}) exceeds 10% threshold. "
                "This may indicate an API schema change."
            )

        if len(all_trials) >= config.max_trials:
            all_trials = all_trials[: config.max_trials]
            break

        page_token = data.get("nextPageToken")
        if not page_token:
            break

        page += 1
        time.sleep(config.request_delay_seconds)

    save_cached_json(CACHE_DIR, cache_key, [t.model_dump() for t in all_trials])
    logger.info("Fetched and cached %d trials for '%s'", len(all_trials), config.therapeutic_area)

    return all_trials


def get_trial_detail(nct_id: str) -> TrialRecord:
    """Fetch detailed information for a single trial by NCT ID."""
    cached = load_cached_json(CACHE_DIR, f"detail_{nct_id}")
    if cached is not None:
        return TrialRecord(**cached)

    data = _ctgov_get(f"studies/{nct_id}", {"format": "json"})
    # Defensive unwrap: some API responses wrap in {"study": {...}}
    if "protocolSection" not in data:
        data = data.get("study", data)
    trial = _parse_trial(data)

    save_cached_json(CACHE_DIR, f"detail_{nct_id}", trial.model_dump())
    return trial

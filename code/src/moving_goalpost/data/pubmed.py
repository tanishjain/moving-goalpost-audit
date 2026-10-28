"""PubMed / NCBI E-utilities client.

Searches for publications matching clinical trials and retrieves abstracts.
Caches all raw API responses to data/raw/pubmed/.
"""

import logging
import time
import hashlib
from typing import Any
from xml.etree import ElementTree

import requests
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from moving_goalpost.config import NCBIConfig, PipelineConfig, RAW_DIR
from moving_goalpost.utils.io import load_cached_json, save_cached_json

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CACHE_DIR = RAW_DIR / "pubmed"


def _log_retry(retry_state) -> None:
    logger.warning(
        "Retrying PubMed request (attempt %d) after %s",
        retry_state.attempt_number,
        type(retry_state.outcome.exception()).__name__,
    )


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class PubMedArticle(BaseModel):
    """Core fields extracted from a PubMed article."""

    pmid: str
    title: str = ""
    abstract: str = ""
    journal: str = ""
    pub_date: str = ""
    doi: str = ""
    authors: list[str] = []
    pmc_id: str = ""


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _get_ncbi_params() -> dict[str, str]:
    """Common NCBI params (API key, email) from config."""
    try:
        config = NCBIConfig()
        params: dict[str, str] = {}
        if config.api_key:
            params["api_key"] = config.api_key
        if config.email:
            params["email"] = config.email
        return params
    except Exception:
        return {}


@retry(
    retry=retry_if_exception_type(
        (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError)
    ),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    stop=stop_after_attempt(3),  # align with PipelineConfig.max_retries
    before_sleep=_log_retry,
)
def _esearch(query: str, max_results: int = 20) -> list[str]:
    """Search PubMed and return a list of PMIDs."""
    params = {
        **_get_ncbi_params(),
        "db": "pubmed",
        "term": query,
        "retmax": str(max_results),
        "retmode": "json",
    }
    response = requests.get(f"{EUTILS_BASE}/esearch.fcgi", params=params, timeout=30)
    if response.status_code == 429:
        raise requests.exceptions.HTTPError("Rate limited (429) by NCBI", response=response)
    response.raise_for_status()
    data = response.json()
    return data.get("esearchresult", {}).get("idlist", [])


@retry(
    retry=retry_if_exception_type(
        (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError)
    ),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    stop=stop_after_attempt(3),  # align with PipelineConfig.max_retries
    before_sleep=_log_retry,
)
def _efetch_abstracts(pmids: list[str]) -> list[dict[str, Any]]:
    """Fetch article metadata and abstracts for a list of PMIDs."""
    if not pmids:
        return []

    params = {
        **_get_ncbi_params(),
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "xml",
        "retmode": "xml",
    }
    response = requests.get(f"{EUTILS_BASE}/efetch.fcgi", params=params, timeout=60)
    if response.status_code == 429:
        raise requests.exceptions.HTTPError("Rate limited (429) by NCBI", response=response)
    response.raise_for_status()

    articles = []
    root = ElementTree.fromstring(response.content)

    for article_elem in root.findall(".//PubmedArticle"):
        try:
            articles.append(_parse_pubmed_xml(article_elem))
        except Exception:
            logger.warning("Failed to parse PubMed article XML", exc_info=True)

    return articles


def _parse_pubmed_xml(article_elem: ElementTree.Element) -> dict[str, Any]:
    """Parse a single PubmedArticle XML element into a dict."""
    medline = article_elem.find("MedlineCitation")
    if medline is None:
        return {}

    pmid_elem = medline.find("PMID")
    pmid = pmid_elem.text if pmid_elem is not None else ""

    article = medline.find("Article")
    if article is None:
        return {"pmid": pmid}

    # Title
    title_elem = article.find("ArticleTitle")
    title = "".join(title_elem.itertext()) if title_elem is not None else ""

    # Abstract
    abstract_parts = []
    abstract_elem = article.find("Abstract")
    if abstract_elem is not None:
        for text_elem in abstract_elem.findall("AbstractText"):
            label = text_elem.get("Label", "")
            full_text = "".join(text_elem.itertext())
            if label:
                abstract_parts.append(f"{label}: {full_text}")
            else:
                abstract_parts.append(full_text)
    abstract = "\n".join(abstract_parts)

    # Journal
    journal_elem = article.find(".//Journal/Title")
    journal = journal_elem.text if journal_elem is not None else ""

    # Publication date
    pub_date_elem = article.find(".//PubDate")
    pub_date = ""
    if pub_date_elem is not None:
        year = pub_date_elem.findtext("Year", "")
        month = pub_date_elem.findtext("Month", "")
        pub_date = f"{year}-{month}" if month else year

    # DOI (ArticleId elements live under PubmedData, not Article)
    doi = ""
    pubmed_data = article_elem.find("PubmedData")
    if pubmed_data is not None:
        for id_elem in pubmed_data.findall(".//ArticleId"):
            if id_elem.get("IdType") == "doi":
                doi = id_elem.text or ""
                break

    # PMC ID
    pmc_id = ""
    if pubmed_data is not None:
        for id_elem in pubmed_data.findall(".//ArticleId"):
            if id_elem.get("IdType") == "pmc":
                pmc_id = id_elem.text or ""
                break

    # Authors
    authors = []
    author_list = article.find("AuthorList")
    if author_list is not None:
        for author_elem in author_list.findall("Author"):
            last = author_elem.findtext("LastName", "")
            first = author_elem.findtext("ForeName", "")
            if last:
                authors.append(f"{last} {first}".strip())

    return {
        "pmid": pmid,
        "title": title,
        "abstract": abstract,
        "journal": journal,
        "pub_date": pub_date,
        "doi": doi,
        "authors": authors,
        "pmc_id": pmc_id,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_by_nct_id(nct_id: str, delay: float = 0.4) -> list[PubMedArticle]:
    """Search PubMed for publications mentioning a specific NCT ID."""
    cache_key = f"search_nctid_{nct_id}"
    cached = load_cached_json(CACHE_DIR, cache_key)
    if cached is not None:
        return [PubMedArticle(**a) for a in cached]

    pmids = _esearch(nct_id, max_results=10)
    time.sleep(delay)

    articles_raw = _efetch_abstracts(pmids) if pmids else []
    articles = [PubMedArticle(**a) for a in articles_raw]

    save_cached_json(CACHE_DIR, cache_key, [a.model_dump() for a in articles])
    return articles


def search_by_keywords(
    title_keywords: str,
    pi_lastname: str = "",
    condition: str = "",
    intervention: str = "",
    year: str = "",
    max_results: int = 5,
    delay: float = 0.4,
) -> list[PubMedArticle]:
    """Search PubMed using trial metadata for fuzzy matching."""
    parts = []
    if title_keywords:
        parts.append(f"({title_keywords})")
    if pi_lastname:
        parts.append(f"{pi_lastname}[Author]")
    if condition:
        parts.append(f"({condition})")
    if intervention:
        parts.append(f"({intervention})")
    if year:
        parts.append(f"{year}[Date - Publication]")

    query = " AND ".join(parts)
    if not query:
        return []

    query_digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
    cache_key = f"search_kw_{query_digest}"
    cached = load_cached_json(CACHE_DIR, cache_key)
    if cached is not None:
        return [PubMedArticle(**a) for a in cached]

    pmids = _esearch(query, max_results=max_results)
    time.sleep(delay)

    articles_raw = _efetch_abstracts(pmids) if pmids else []
    articles = [PubMedArticle(**a) for a in articles_raw]

    save_cached_json(CACHE_DIR, cache_key, [a.model_dump() for a in articles])
    return articles


def fetch_article_by_pmid(pmid: str, delay: float = 0.4) -> PubMedArticle | None:
    """Fetch a single article by PMID."""
    cache_key = f"article_{pmid}"
    cached = load_cached_json(CACHE_DIR, cache_key)
    if cached is not None:
        return PubMedArticle(**cached)

    articles_raw = _efetch_abstracts([pmid])
    time.sleep(delay)

    if not articles_raw:
        return None

    article = PubMedArticle(**articles_raw[0])
    save_cached_json(CACHE_DIR, cache_key, article.model_dump())
    return article

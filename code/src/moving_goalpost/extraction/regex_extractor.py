"""Rule-based (regex) endpoint extraction from abstracts.

Provides a fast, interpretable, non-LLM baseline for extracting
primary endpoints from publication abstracts.
"""

import re
import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RegexExtractionResult(BaseModel):
    """Result from regex-based endpoint extraction."""
    primary_outcomes: list[str]
    confidence: str  # high, medium, low
    extraction_method: str = "regex"
    matched_pattern: str = ""


_PRIMARY_OUTCOME_PATTERNS = [
    (r"(?i)primary\s+(?:end\s*point|outcome|outcome\s+measure)[s]?\s*(?:was|were|:)\s*(.+?)(?:\.|;|\n)", "explicit_label"),
    (r"(?i)the\s+primary\s+(?:end\s*point|outcome|efficacy\s+end\s*point)\s+(?:was|were|included)\s+(.+?)(?:\.|;|\n)", "the_primary"),
    (r"(?i)main\s+outcome\s+measure[s]?\s*(?:was|were|:)\s*(.+?)(?:\.|;|\n)", "main_outcome"),
    (r"(?i)primary\s+efficacy\s+(?:end\s*point|outcome|variable)\s*(?:was|were|:)\s*(.+?)(?:\.|;|\n)", "primary_efficacy"),
    (r"(?i)(?:PRIMARY\s+)?OUTCOME[S]?\s*(?:AND\s+MEASURE[S]?)?\s*[:]\s*(.+?)(?:\n|RESULTS|METHODS)", "structured_section"),
    (r"(?i)MAIN\s+OUTCOME[S]?\s*(?:AND\s+MEASURE[S]?)?\s*[:]\s*(.+?)(?:\n|RESULTS|METHODS)", "structured_main"),
]

_FALLBACK_PATTERNS = [
    (r"(?i)(?:we\s+)?(?:assessed|evaluated|measured|examined|compared)\s+(.+?)\s+as\s+(?:the\s+)?primary", "assessed_as_primary"),
    (r"(?i)primary\s+(?:end\s*point|outcome)\s+of\s+(.+?)(?:\.|;|\n|,\s+which)", "primary_of"),
]


def extract_endpoints_regex(abstract: str) -> RegexExtractionResult:
    """Extract primary endpoints from an abstract using regex patterns."""
    if not abstract or not abstract.strip():
        return RegexExtractionResult(
            primary_outcomes=[], confidence="low", matched_pattern="empty_abstract",
        )

    for pattern, pattern_name in _PRIMARY_OUTCOME_PATTERNS:
        matches = re.findall(pattern, abstract)
        if matches:
            outcomes = [_clean_extracted_text(m) for m in matches if m.strip()]
            if outcomes:
                return RegexExtractionResult(
                    primary_outcomes=outcomes,
                    confidence="high" if pattern_name.startswith(("explicit", "the_primary")) else "medium",
                    matched_pattern=pattern_name,
                )

    for pattern, pattern_name in _FALLBACK_PATTERNS:
        matches = re.findall(pattern, abstract)
        if matches:
            outcomes = [_clean_extracted_text(m) for m in matches if m.strip()]
            if outcomes:
                return RegexExtractionResult(
                    primary_outcomes=outcomes, confidence="low", matched_pattern=pattern_name,
                )

    return RegexExtractionResult(
        primary_outcomes=[], confidence="low", matched_pattern="no_match",
    )


def _clean_extracted_text(text: str) -> str:
    """Clean up extracted endpoint text."""
    text = text.strip()
    text = re.sub(r"\s+(?:and|or|with)\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

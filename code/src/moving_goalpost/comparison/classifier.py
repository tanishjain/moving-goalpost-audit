"""Discrepancy type classification."""

import json
import logging
from enum import Enum

from pydantic import BaseModel

from moving_goalpost.config import PipelineConfig
from moving_goalpost.utils.azure_openai import chat_completion_json
from moving_goalpost.utils.io import load_prompt

logger = logging.getLogger(__name__)


class DiscrepancyType(str, Enum):
    """Types of endpoint discrepancies."""

    CONSISTENT = "CONSISTENT"
    MODIFIED = "MODIFIED"
    TIMEFRAME_CHANGE = "TIMEFRAME_CHANGE"
    COMPOSITE_SUBSET = "COMPOSITE_SUBSET"
    UNREPORTED_IN_ABSTRACT = "UNREPORTED_IN_ABSTRACT"
    ADDED = "ADDED"
    MULTIPLE_CHANGES = "MULTIPLE_CHANGES"


class ClassificationResult(BaseModel):
    """Result from discrepancy classification."""

    classification: DiscrepancyType
    confidence: int  # 1-5
    explanation: str
    registered_summary: str = ""
    published_summary: str = ""
    specific_changes: list[str] = []
    classification_method: str = "llm"
    model_deployment: str = ""
    model_id: str = ""


def classify_discrepancy(
    registered_endpoints: str,
    registered_timeframe: str,
    published_endpoints: str,
    config: PipelineConfig | None = None,
) -> ClassificationResult:
    """Classify the type of discrepancy between registered and published endpoints."""
    if config is None:
        config = PipelineConfig()

    # Guard against empty inputs — cannot classify without both endpoint texts
    registered_endpoints = "" if registered_endpoints is None else str(registered_endpoints)
    published_endpoints = "" if published_endpoints is None else str(published_endpoints)
    if not registered_endpoints.strip() or not published_endpoints.strip():
        return ClassificationResult(
            classification=DiscrepancyType.MODIFIED,
            confidence=1,
            explanation="One or both endpoint texts are empty; cannot classify.",
            specific_changes=["Empty endpoint input"],
        )

    registered_timeframe = "" if registered_timeframe is None else str(registered_timeframe)
    prompt_template = load_prompt("classify_discrepancy")
    # Use explicit token replacement because prompt templates contain literal braces for JSON examples.
    prompt = (
        prompt_template.replace("{registered_endpoints}", registered_endpoints)
        .replace("{registered_timeframe}", registered_timeframe)
        .replace("{published_endpoints}", published_endpoints)
    )

    try:
        result = chat_completion_json(
            prompt=prompt,
            system_message="You are a clinical trials methodology expert classifying endpoint discrepancies.",
            model_alias=config.classification_model,
            temperature=0.0,
        )
    except json.JSONDecodeError:
        logger.warning("Discrepancy classification JSON parse failed; defaulting to MODIFIED for manual review")
        return ClassificationResult(
            classification=DiscrepancyType.MODIFIED,
            confidence=1,
            explanation="LLM classification parse failed; defaulted to MODIFIED for manual review.",
            specific_changes=[],
        )
    except Exception:
        logger.warning(
            "Discrepancy classification call failed; defaulting to MODIFIED for manual review", exc_info=True
        )
        return ClassificationResult(
            classification=DiscrepancyType.MODIFIED,
            confidence=1,
            explanation="LLM classification call failed; defaulted to MODIFIED for manual review.",
            specific_changes=[],
        )

    provenance = result.pop("_provenance", {})

    raw_classification = result.get("classification", "MODIFIED").upper().replace(" ", "_")
    try:
        disc_type = DiscrepancyType(raw_classification)
    except ValueError:
        logger.warning("Unknown classification '%s', defaulting to MODIFIED for manual review", raw_classification)
        disc_type = DiscrepancyType.MODIFIED

    return ClassificationResult(
        classification=disc_type,
        confidence=result.get("confidence", 1),
        explanation=result.get("explanation", ""),
        registered_summary=result.get("registered_summary", ""),
        published_summary=result.get("published_summary", ""),
        specific_changes=result.get("specific_changes", []),
        model_deployment=provenance.get("model_deployment", ""),
        model_id=provenance.get("model_id", ""),
    )

"""LLM-based endpoint extraction from abstracts.

Uses Azure OpenAI to extract primary endpoints from publication abstracts.
More accurate than regex but slower and more expensive.
"""

import json
import logging

from pydantic import BaseModel

from moving_goalpost.config import PipelineConfig
from moving_goalpost.utils.azure_openai import chat_completion_json
from moving_goalpost.utils.io import load_prompt

logger = logging.getLogger(__name__)


class LLMExtractionResult(BaseModel):
    """Result from LLM-based endpoint extraction."""
    primary_outcomes: list[str]
    confidence: str
    extraction_evidence: str = ""
    extraction_method: str = "llm"
    model_deployment: str = ""
    model_id: str = ""


def extract_endpoints_llm(
    abstract: str,
    config: PipelineConfig | None = None,
) -> LLMExtractionResult:
    """Extract primary endpoints from an abstract using an LLM."""
    if config is None:
        config = PipelineConfig()

    if not abstract or not abstract.strip():
        return LLMExtractionResult(
            primary_outcomes=[], confidence="low", extraction_evidence="",
        )

    prompt_template = load_prompt("extract_endpoint")
    # Use explicit token replacement because prompt templates contain literal braces for JSON examples.
    prompt = prompt_template.replace("{abstract_text}", abstract)

    try:
        result = chat_completion_json(
            prompt=prompt,
            system_message="You are a clinical trials methodology expert. You extract primary endpoints from abstracts with precision.",
            model_alias=config.extraction_model,
            temperature=0.0,
        )
    except json.JSONDecodeError:
        logger.warning("LLM extraction JSON parse failed; using empty extraction fallback")
        return LLMExtractionResult(
            primary_outcomes=[],
            confidence="low",
            extraction_evidence="LLM output parse failed",
        )
    except Exception:
        logger.warning("LLM extraction call failed; using empty extraction fallback", exc_info=True)
        return LLMExtractionResult(
            primary_outcomes=[],
            confidence="low",
            extraction_evidence="LLM extraction call failed",
        )

    provenance = result.pop("_provenance", {})

    return LLMExtractionResult(
        primary_outcomes=result.get("primary_outcomes", []),
        confidence=result.get("confidence", "low"),
        extraction_evidence=result.get("extraction_evidence", ""),
        model_deployment=provenance.get("model_deployment", ""),
        model_id=provenance.get("model_id", ""),
    )

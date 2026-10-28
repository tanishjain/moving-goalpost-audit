"""LLM-as-judge for endpoint semantic comparison."""

import json
import logging

from pydantic import BaseModel

from moving_goalpost.config import PipelineConfig
from moving_goalpost.utils.azure_openai import chat_completion_json
from moving_goalpost.utils.io import load_prompt

logger = logging.getLogger(__name__)


class LLMJudgeResult(BaseModel):
    """Result from LLM-as-judge endpoint comparison."""

    similarity_score: int  # 1-5
    same_concept: bool
    same_measurement: bool
    same_timeframe: bool
    key_differences: list[str]
    explanation: str
    comparison_method: str = "llm_judge"
    model_deployment: str = ""
    model_id: str = ""


def compare_endpoints_llm_judge(
    registered_endpoint: str,
    registered_timeframe: str,
    published_endpoint: str,
    config: PipelineConfig | None = None,
) -> LLMJudgeResult:
    """Use an LLM to judge whether two endpoints are the same."""
    if config is None:
        config = PipelineConfig()

    registered_timeframe = "" if registered_timeframe is None else str(registered_timeframe)
    if not registered_endpoint.strip() or not published_endpoint.strip():
        return LLMJudgeResult(
            similarity_score=1,
            same_concept=False,
            same_measurement=False,
            same_timeframe=False,
            key_differences=["One or both endpoints are empty"],
            explanation="Cannot compare empty endpoints.",
        )

    prompt_template = load_prompt("judge_similarity")
    # Use explicit token replacement because prompt templates contain literal braces for JSON examples.
    prompt = (
        prompt_template.replace("{registered_endpoint}", registered_endpoint)
        .replace("{registered_timeframe}", registered_timeframe)
        .replace("{published_endpoint}", published_endpoint)
    )

    try:
        result = chat_completion_json(
            prompt=prompt,
            system_message="You are a clinical trials methodology expert comparing registered and published endpoints.",
            model_alias=config.judge_model,
            temperature=0.0,
        )
    except json.JSONDecodeError:
        logger.warning("LLM judge JSON parse failed; using conservative discrepancy fallback")
        return LLMJudgeResult(
            similarity_score=1,
            same_concept=False,
            same_measurement=False,
            same_timeframe=False,
            key_differences=["LLM output parse failed"],
            explanation="LLM judge parse failed; marked for manual review.",
        )
    except Exception:
        logger.warning("LLM judge call failed; using conservative discrepancy fallback", exc_info=True)
        return LLMJudgeResult(
            similarity_score=1,
            same_concept=False,
            same_measurement=False,
            same_timeframe=False,
            key_differences=["LLM judge call failed"],
            explanation="LLM judge call failed; marked for manual review.",
        )

    provenance = result.pop("_provenance", {})

    raw_score = result.get("similarity_score", 1)
    clamped_score = max(1, min(5, int(raw_score))) if isinstance(raw_score, (int, float)) else 1

    return LLMJudgeResult(
        similarity_score=clamped_score,
        same_concept=result.get("same_concept", False),
        same_measurement=result.get("same_measurement", False),
        same_timeframe=result.get("same_timeframe", False),
        key_differences=result.get("key_differences", []),
        explanation=result.get("explanation", ""),
        model_deployment=provenance.get("model_deployment", ""),
        model_id=provenance.get("model_id", ""),
    )

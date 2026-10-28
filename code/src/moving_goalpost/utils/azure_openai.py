"""Azure OpenAI client wrapper with retry logic and structured output support."""

import os
import json
import logging
from typing import Any

from openai import AzureOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import RateLimitError, APITimeoutError, APIConnectionError

from dotenv import load_dotenv

from moving_goalpost.config import AzureOpenAIConfig, PROJECT_ROOT

logger = logging.getLogger(__name__)

# Ensure .env is loaded for Langfuse/OpenAI environment variables
load_dotenv(PROJECT_ROOT / ".env", override=False)

# Optional Langfuse tracking (set LANGFUSE_* env vars to enable)
try:
    from langfuse import Langfuse
except Exception:  # pragma: no cover - optional dependency
    Langfuse = None

# Lazy singleton
_client: AzureOpenAI | None = None
_config: AzureOpenAIConfig | None = None
_langfuse: "Langfuse | None" = None


def _log_retry(retry_state) -> None:
    logger.warning(
        "Retrying Azure OpenAI call (attempt %d) after %s",
        retry_state.attempt_number,
        type(retry_state.outcome.exception()).__name__,
    )


def _get_client() -> tuple[AzureOpenAI, AzureOpenAIConfig]:
    """Get or create the Azure OpenAI client singleton."""
    global _client, _config
    if _client is None:
        _config = AzureOpenAIConfig()
        _client = AzureOpenAI(
            azure_endpoint=_config.endpoint,
            api_key=_config.api_key,
            api_version=_config.api_version,
        )
        logger.info("Azure OpenAI client initialized (endpoint=%s)", _config.endpoint)
    return _client, _config


def _get_langfuse() -> "Langfuse | None":
    """Return a Langfuse client if configured, otherwise None."""
    global _langfuse
    if Langfuse is None:
        return None
    if _langfuse is None:
        try:
            _langfuse = Langfuse()
            logger.info("Langfuse client initialized")
        except Exception:
            logger.warning("Langfuse initialization failed", exc_info=True)
            _langfuse = None
    return _langfuse


def _trace_name(name: str) -> str:
    return f"moving_goalpost:{name}"


def _assert_gpt4o_allowed(model_alias: str) -> None:
    """Prevent using GPT-4o unless explicitly allowed."""
    if model_alias != "gpt4o":
        return
    allowed = os.getenv("ALLOW_GPT4O", "").strip().lower() in {"1", "true", "yes"}
    if not allowed:
        raise RuntimeError("GPT-4o is disabled by policy. Please confirm and set ALLOW_GPT4O=1 in .env to proceed.")


def get_deployment_name(model_alias: str) -> str:
    """Map a config alias (e.g., 'gpt4o') to the actual Azure deployment name."""
    _, config = _get_client()
    mapping = {
        "gpt4o": config.gpt4o_deployment,
        "gpt4o_mini": config.gpt4o_mini_deployment,
        "embedding": config.embedding_deployment,
    }
    if model_alias not in mapping:
        raise ValueError(f"Unknown model alias '{model_alias}'. Valid: {list(mapping.keys())}")
    return mapping[model_alias]


@retry(
    retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIConnectionError)),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(3),  # align with PipelineConfig.max_retries
    before_sleep=_log_retry,
)
def chat_completion_json(
    prompt: str,
    system_message: str = "You are a helpful clinical trials expert.",
    model_alias: str = "gpt4o_mini",
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Call Azure OpenAI chat completion and parse the JSON response.

    Args:
        prompt: The user message.
        system_message: System prompt.
        model_alias: Config alias for the deployment ('gpt4o', 'gpt4o_mini').
        temperature: Sampling temperature.

    Returns:
        Parsed JSON dict from the model response.

    Raises:
        json.JSONDecodeError: If the response is not valid JSON.
    """
    _assert_gpt4o_allowed(model_alias)
    client, _ = _get_client()
    deployment = get_deployment_name(model_alias)

    trace = None
    langfuse = _get_langfuse()
    if langfuse is not None:
        try:
            trace = langfuse.trace(
                name=_trace_name("chat_completion_json"),
                input={"prompt": prompt, "system_message": system_message, "model_alias": model_alias},
                metadata={"deployment": deployment},
            )
        except Exception:
            logger.debug("Langfuse trace creation failed", exc_info=True)
            trace = None

    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    if content is None:
        raise ValueError(f"Azure OpenAI returned null content (possible content filter). Deployment: {deployment}")
    logger.debug("LLM response (%s): %s", deployment, content[:200])

    result = json.loads(content)

    if trace is not None:
        try:
            usage = response.usage
            usage_payload = {
                "input": getattr(usage, "prompt_tokens", None),
                "output": getattr(usage, "completion_tokens", None),
                "total": getattr(usage, "total_tokens", None),
            }
            trace.generation(
                name=_trace_name("azure_openai_chat"),
                model=deployment,
                input=prompt,
                output=content,
                usage=usage_payload,
                metadata={"system_message": system_message, "model_alias": model_alias},
            )
        except Exception:
            logger.debug("Langfuse generation logging failed", exc_info=True)

    # Attach provenance metadata
    result["_provenance"] = {
        "model_deployment": deployment,
        "model_id": response.model,
        "usage": {
            "prompt_tokens": getattr(response.usage, "prompt_tokens", None) if response.usage else None,
            "completion_tokens": getattr(response.usage, "completion_tokens", None) if response.usage else None,
        },
    }
    return result


@retry(
    retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIConnectionError)),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(3),  # align with PipelineConfig.max_retries
    before_sleep=_log_retry,
)
def compute_embedding(text: str) -> list[float]:
    """Compute an embedding vector for a piece of text."""
    client, _ = _get_client()
    deployment = get_deployment_name("embedding")
    trace = None
    langfuse = _get_langfuse()
    if langfuse is not None:
        try:
            trace = langfuse.trace(
                name=_trace_name("compute_embedding"),
                input={"text": text[:500]},
                metadata={"deployment": deployment},
            )
        except Exception:
            logger.debug("Langfuse trace creation failed", exc_info=True)
    response = client.embeddings.create(model=deployment, input=text)
    embedding = response.data[0].embedding
    if trace is not None:
        try:
            usage = response.usage
            usage_payload = {
                "input": getattr(usage, "prompt_tokens", None),
                "total": getattr(usage, "total_tokens", None),
            }
            trace.generation(
                name=_trace_name("azure_openai_embedding"),
                model=deployment,
                input={"text_preview": text[:500]},
                output={"embedding_dim": len(embedding)},
                usage=usage_payload,
            )
        except Exception:
            logger.debug("Langfuse generation logging failed", exc_info=True)
    return embedding


@retry(
    retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIConnectionError)),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(3),  # align with PipelineConfig.max_retries
    before_sleep=_log_retry,
)
def _create_embedding_batch(client: AzureOpenAI, deployment: str, batch: list[str]):
    return client.embeddings.create(model=deployment, input=batch)


def compute_embeddings_batch(texts: list[str], batch_size: int = 100) -> list[list[float]]:
    """Compute embeddings for a batch of texts."""
    if not texts:
        return []
    client, _ = _get_client()
    deployment = get_deployment_name("embedding")

    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = _create_embedding_batch(client, deployment, batch)
        sorted_items = sorted(response.data, key=lambda item: item.index)
        batch_embeddings = [item.embedding for item in sorted_items]
        all_embeddings.extend(batch_embeddings)
        logger.debug("Embedded batch %d-%d / %d", i, i + len(batch), len(texts))
        langfuse = _get_langfuse()
        if langfuse is not None:
            try:
                trace = langfuse.trace(
                    name=_trace_name("compute_embeddings_batch"),
                    input={"batch_size": len(batch)},
                    metadata={"deployment": deployment},
                )
                usage = response.usage
                usage_payload = {
                    "input": getattr(usage, "prompt_tokens", None),
                    "total": getattr(usage, "total_tokens", None),
                }
                trace.generation(
                    name=_trace_name("azure_openai_embedding_batch"),
                    model=deployment,
                    input={"batch_count": len(batch)},
                    output={"embedding_dim": len(batch_embeddings[0]) if batch_embeddings else 0},
                    usage=usage_payload,
                )
            except Exception:
                logger.debug("Langfuse generation logging failed", exc_info=True)

    return all_embeddings

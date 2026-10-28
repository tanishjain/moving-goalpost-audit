"""
Central configuration for the Moving Goalpost Tracker.

All configurable values live here — thresholds, model names, paths, batch sizes.
Nothing should be hardcoded in pipeline code.
"""

from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
VALIDATION_DIR = DATA_DIR / "validation"
PROMPTS_DIR = PROJECT_ROOT / "prompts"


class AzureOpenAIConfig(BaseSettings):
    """Azure OpenAI connection settings. Loaded from .env."""

    endpoint: str = Field(alias="AZURE_OPENAI_ENDPOINT")
    api_key: str = Field(alias="AZURE_OPENAI_API_KEY")
    api_version: str = Field(default="2024-02-01", alias="AZURE_OPENAI_API_VERSION")

    # Deployment names (map to your Azure deployments)
    gpt4o_deployment: str = Field(default="gpt-4o", alias="AZURE_OPENAI_GPT4O_DEPLOYMENT")
    gpt4o_mini_deployment: str = Field(default="gpt-4o-mini", alias="AZURE_OPENAI_GPT4O_MINI_DEPLOYMENT")
    embedding_deployment: str = Field(default="text-embedding-3-large", alias="AZURE_OPENAI_EMBEDDING_DEPLOYMENT")

    model_config = {"env_file": str(PROJECT_ROOT / ".env"), "extra": "ignore"}


class NCBIConfig(BaseSettings):
    """NCBI/PubMed API settings."""

    api_key: str | None = Field(default=None, alias="NCBI_API_KEY")
    email: str | None = Field(default=None, alias="NCBI_EMAIL")

    model_config = {"env_file": str(PROJECT_ROOT / ".env"), "extra": "ignore"}


class SimilarityThresholds(BaseSettings):
    """
    Similarity score thresholds for flagging discrepancies.

    These should be calibrated empirically from the gold-standard validation
    set using precision-recall curves once manual adjudication is complete.
    """

    high_similarity: float = 0.85  # Above this → likely consistent
    low_similarity: float = 0.60  # Below this → likely discrepancy
    # Between low and high → needs review

    llm_judge_discrepancy_threshold: int = 3  # LLM judge score <= this → flagged


class PipelineConfig(BaseSettings):
    """Pipeline execution parameters."""

    # Data collection
    therapeutic_area: str = "cancer"
    phase: list[str] = ["PHASE3"]
    status: list[str] = ["COMPLETED"]
    date_range_start: str = "2018-01-01"
    date_range_end: str = "2023-12-31"
    max_trials: int = 5000

    # API behavior
    request_delay_seconds: float = 0.5  # Politeness delay between API calls
    max_retries: int = 3
    cache_api_responses: bool = True

    # LLM
    extraction_model: str = "gpt4o_mini"  # Which deployment to use for extraction
    judge_model: str = "gpt4o_mini"  # Which deployment to use for comparison
    classification_model: str = "gpt4o"  # Which deployment to use for classification

    # Thresholds
    similarity: SimilarityThresholds = SimilarityThresholds()

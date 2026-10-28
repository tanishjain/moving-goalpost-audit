"""I/O utilities: prompt loading, data caching, CSV helpers."""

import json
import logging
import os
from pathlib import Path

import pandas as pd

from moving_goalpost.config import PROMPTS_DIR, RAW_DIR, PROCESSED_DIR

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


def load_prompt(name: str) -> str:
    """Load a prompt template from the prompts/ directory.

    Args:
        name: Filename without extension (e.g., "extract_endpoint").

    Returns:
        The prompt template string with {placeholders} intact.
    """
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# JSON cache helpers
# ---------------------------------------------------------------------------


def cache_path(directory: Path, key: str) -> Path:
    """Return the cache file path for a given key inside a directory."""
    safe_key = key.replace("/", "_").replace(":", "_").replace(" ", "_")
    return directory / f"{safe_key}.json"


def load_cached_json(directory: Path, key: str) -> dict | list | None:
    """Load a cached JSON file if it exists, else return None."""
    path = cache_path(directory, key)
    if path.exists():
        logger.debug("Cache hit: %s", path)
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def save_cached_json(directory: Path, key: str, data: dict | list) -> Path:
    """Save data as a cached JSON file. Creates parent dirs as needed."""
    path = cache_path(directory, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.debug("Cached: %s", path)
    return path


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------


def save_processed_csv(df: pd.DataFrame, filename: str) -> Path:
    """Save a DataFrame to data/processed/ with a descriptive name.

    Uses atomic write (write to .tmp then rename) to prevent corruption
    if the process is interrupted mid-write.
    """
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = PROCESSED_DIR / filename
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp_path, index=False)
    os.replace(tmp_path, path)
    logger.info("Saved %d rows -> %s", len(df), path)
    return path


def load_processed_csv(filename: str) -> pd.DataFrame:
    """Load a DataFrame from data/processed/."""
    path = PROCESSED_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Processed data not found: {path}")
    df = pd.read_csv(path)
    logger.info("Loaded %d rows <- %s", len(df), path)
    return df

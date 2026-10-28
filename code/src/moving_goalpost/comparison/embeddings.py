"""Embedding-based semantic similarity for endpoint comparison."""

import logging

import numpy as np
from pydantic import BaseModel

from moving_goalpost.utils.azure_openai import compute_embedding, compute_embeddings_batch

logger = logging.getLogger(__name__)


class EmbeddingSimilarityResult(BaseModel):
    """Result from embedding similarity comparison."""

    cosine_similarity: float
    registered_text: str
    published_text: str
    comparison_method: str = "embedding"


def cosine_sim(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    dot = np.dot(a_arr, b_arr)
    norm = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def compare_endpoints_embedding(
    registered_endpoint: str,
    published_endpoint: str,
) -> EmbeddingSimilarityResult:
    """Compare two endpoint descriptions using embedding cosine similarity."""
    if not registered_endpoint.strip() or not published_endpoint.strip():
        return EmbeddingSimilarityResult(
            cosine_similarity=0.0,
            registered_text=registered_endpoint,
            published_text=published_endpoint,
        )

    try:
        emb_reg = compute_embedding(registered_endpoint)
        emb_pub = compute_embedding(published_endpoint)
    except Exception:
        logger.warning("Embedding computation failed; returning similarity 0.0 for manual review", exc_info=True)
        return EmbeddingSimilarityResult(
            cosine_similarity=0.0,
            registered_text=registered_endpoint,
            published_text=published_endpoint,
        )
    similarity = cosine_sim(emb_reg, emb_pub)

    return EmbeddingSimilarityResult(
        cosine_similarity=similarity,
        registered_text=registered_endpoint,
        published_text=published_endpoint,
    )


def compare_endpoints_embedding_batch(
    registered_endpoints: list[str],
    published_endpoints: list[str],
) -> list[EmbeddingSimilarityResult]:
    """Compare multiple endpoint pairs using batch embedding."""
    if len(registered_endpoints) != len(published_endpoints):
        raise ValueError("registered_endpoints and published_endpoints must have equal length")

    n = len(registered_endpoints)
    if n == 0:
        return []

    all_texts = registered_endpoints + published_endpoints
    all_embeddings = compute_embeddings_batch(all_texts)

    reg_embeddings = all_embeddings[:n]
    pub_embeddings = all_embeddings[n:]

    results = []
    for i in range(n):
        similarity = cosine_sim(reg_embeddings[i], pub_embeddings[i])
        results.append(
            EmbeddingSimilarityResult(
                cosine_similarity=similarity,
                registered_text=registered_endpoints[i],
                published_text=published_endpoints[i],
            )
        )

    return results

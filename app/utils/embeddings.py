"""Embedding utilities — lazy-loaded sentence-transformers model.

The model (~22 MB, 384-dim) downloads on first use and caches in
~/.cache/huggingface/. All functions are synchronous — call from
a thread or use asyncio.to_thread() in async contexts.

Usage:
    from app.utils.embeddings import embed, embed_batch
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Lazy-load the embedding model. Cached after first call."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(_MODEL_NAME)


def embed(text: str) -> np.ndarray:
    """Embed a single text string. Returns shape (384,) float32 array."""
    model = _get_model()
    return model.encode(text, convert_to_numpy=True, show_progress_bar=False)


def embed_batch(texts: list[str], batch_size: int = 64) -> np.ndarray:
    """Embed multiple texts. Returns shape (N, 384) float32 array."""
    if not texts:
        return np.empty((0, _EMBEDDING_DIM), dtype=np.float32)
    model = _get_model()
    return model.encode(texts, batch_size=batch_size, convert_to_numpy=True, show_progress_bar=False)

"""Embedding utilities — lazy-loaded sentence-transformers model.

The model (~22 MB, 384-dim) downloads on first use and caches in
~/.cache/huggingface/. All functions are synchronous — call from
a thread or use asyncio.to_thread() in async contexts.

Usage:
    from app.utils.embeddings import embed, embed_batch
"""

from __future__ import annotations

from functools import lru_cache
from importlib.util import find_spec
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Lazy-load the embedding model. Cached after first call."""
    if not embeddings_available():
        raise ImportError('Local embeddings are optional. Install with poetry install -E embeddings, then restart YAPOC.')
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


def embeddings_available() -> bool:
    return find_spec('sentence_transformers') is not None


def embed_optional(text: str) -> np.ndarray | None:
    """Missing optional ML dependencies select keyword search, not fake vectors."""
    return embed(text) if embeddings_available() else None


def embed_batch_optional(texts: list[str]):
    """Continue indexing searchable text without downloading any model."""
    return embed_batch(texts) if embeddings_available() else [None] * len(texts)


def backfill_embeddings(batch_size: int = 64) -> int:
    """Explicitly embed existing keyword-only rows after installing the extra."""
    from app.utils.db import get_db
    if not embeddings_available():
        raise ImportError('Install the embeddings extra first: poetry install -E embeddings')
    db = get_db()
    total = 0
    while rows := db.execute('SELECT id, content FROM memory_entries WHERE embedding IS NULL ORDER BY id LIMIT ?', (batch_size,)).fetchall():
        vectors = embed_batch([row['content'] for row in rows])
        db.executemany('UPDATE memory_entries SET embedding=? WHERE id=? AND embedding IS NULL',
                       [(vector.astype(np.float32).tobytes(), row['id']) for row, vector in zip(rows, vectors)])
        db.commit()
        total += len(rows)
    return total

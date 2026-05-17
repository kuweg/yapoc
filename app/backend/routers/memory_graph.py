"""Memory graph + search router.

- GET /memory/graph?agent=&source=&limit=500
  PCA + k-means cluster visualization over stored embeddings.

- GET /memory/search?q=&agent=&top_k=10
  Hybrid (semantic + keyword) ranked retrieval over the same store.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from typing import Annotated

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from app.utils.db import get_db

router = APIRouter()

_CLUSTER_COLORS = [
    "#FFB633", "#3FB950", "#F78166", "#D2A8FF",
    "#FFA657", "#79C0FF", "#56D364", "#FF7B72",
]

_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "in", "of", "is", "was", "i",
    "it", "for", "on", "at", "with", "this", "that", "from", "by", "are",
    "be", "as", "had", "have", "has", "not", "but", "they", "their",
    "my", "we", "you", "your", "its", "into", "which", "will", "can",
    "been", "were", "would", "could", "should", "he", "she", "also",
    "all", "more", "when", "there", "if", "than", "so", "out", "about",
    "up", "some", "then", "no", "do", "did", "just", "now", "new",
}


def _pca_2d(embeddings: np.ndarray) -> np.ndarray:
    """Reduce N×384 embeddings to N×2 via PCA (numpy SVD, no external deps)."""
    X = embeddings - embeddings.mean(axis=0)
    _, _, Vt = np.linalg.svd(X, full_matrices=False)
    coords = X @ Vt[:2].T  # (N, 2)
    for i in range(2):
        r = float(np.abs(coords[:, i]).max()) or 1.0
        coords[:, i] /= r
    return coords


def _cluster_label(contents: list[str]) -> str:
    """Top 3 frequent non-stopword words joined by ' / '."""
    words = [
        w.lower().strip(".,;:!?\"'()[]")
        for c in contents
        for w in c.split()
        if len(w) > 3
        and w.lower().strip(".,;:!?\"'()[]") not in _STOPWORDS
    ]
    top = Counter(words).most_common(3)
    return " / ".join(w for w, _ in top) or "cluster"


@router.get("/memory/graph")
async def get_memory_graph(
    agent: Annotated[str, Query()] = "",
    source: Annotated[str, Query()] = "",
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> dict:
    """Return PCA-reduced 2D scatter plot data with k-means cluster assignments."""
    from sklearn.cluster import KMeans  # transitive dep of sentence-transformers

    db = get_db()

    conditions = ["embedding IS NOT NULL"]
    params: list = []
    if agent:
        conditions.append("agent = ?")
        params.append(agent)
    if source:
        conditions.append("source = ?")
        params.append(source)
    params.append(limit)

    where = " AND ".join(conditions)
    rows = db.execute(
        f"SELECT id, agent, source, content, timestamp, embedding"
        f" FROM memory_entries WHERE {where} ORDER BY id DESC LIMIT ?",
        params,
    ).fetchall()

    total = db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]

    if not rows:
        return {"points": [], "clusters": [], "total": total}

    embeddings = np.stack([
        np.frombuffer(row["embedding"], dtype=np.float32)
        for row in rows
    ])

    coords = _pca_2d(embeddings)

    n_clusters = min(8, len(rows))
    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
    labels: list[int] = km.fit_predict(embeddings).tolist()

    cluster_contents: dict[int, list[str]] = {i: [] for i in range(n_clusters)}
    for i, row in enumerate(rows):
        cluster_contents[labels[i]].append(row["content"])

    clusters = [
        {
            "id": cid,
            "label": _cluster_label(contents),
            "color": _CLUSTER_COLORS[cid % len(_CLUSTER_COLORS)],
            "count": len(contents),
        }
        for cid, contents in sorted(cluster_contents.items())
        if contents
    ]

    points = [
        {
            "id": row["id"],
            "agent": row["agent"],
            "source": row["source"],
            "content": row["content"],
            "timestamp": row["timestamp"],
            "x": float(round(float(coords[i, 0]), 4)),
            "y": float(round(float(coords[i, 1]), 4)),
            "cluster": labels[i],
        }
        for i, row in enumerate(rows)
    ]

    return {"points": points, "clusters": clusters, "total": total}


@router.get("/memory/search")
async def search_memory(
    q: Annotated[str, Query(min_length=1, max_length=500)],
    agent: Annotated[str, Query()] = "",
    top_k: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict:
    """Hybrid (RRF: keyword + cosine) ranked search over indexed memory.

    Mirrors the `search_memory` agent tool so the UI can query the same
    index the agents use. Returns ranked entries with content + agent +
    source + timestamp + score. Embeddings are not returned.
    """
    from app.utils.db import init_schema, search_hybrid
    from app.utils.embeddings import embed

    init_schema()
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
    if total == 0:
        return {"query": q, "results": [], "total_indexed": 0}

    try:
        # Embedding model load can be slow on first call; offload to thread.
        query_vec = await asyncio.to_thread(embed, q)
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Embedding model unavailable: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {exc}") from exc

    rows = search_hybrid(q, query_vec, agent=(agent or None), top_k=top_k)
    results = [
        {
            "id": r.get("id"),
            "agent": r.get("agent", ""),
            "source": r.get("source", ""),
            "content": r.get("content", ""),
            "timestamp": r.get("timestamp", ""),
            "score": r.get("rrf_score", 0),
        }
        for r in rows
    ]
    return {"query": q, "results": results, "total_indexed": total}

"""Phase 2.4 — measurable retrieval quality for the memory system.

`search_hybrid` (FTS5 + cosine, fused with RRF) was documented but never
measured, so there was no way to answer whether a change to indexing, decay or
consolidation made retrieval better or worse. Phase 3.1 (typed memory layers
with promotion and retention rules) cannot be evaluated without this, which is
why the roadmap gates that work on this benchmark.

The benchmark is a fixed corpus plus a fixed query set with known-relevant
documents, checked into the repo. It is deliberately NOT run against live
memory: live memory changes every few minutes, so a score from it is not
comparable across runs and cannot detect a regression.

Embeddings come from the local sentence-transformers model, so a run costs no
API calls and is reproducible for a given model version.

Metrics
-------
recall@k     fraction of a query's relevant docs that appear in the top k
precision@k  fraction of the top k that are relevant
MRR          mean reciprocal rank of the FIRST relevant hit — the metric that
             best reflects "did the agent see the right thing without having to
             read past three irrelevant memories"

Usage
-----
    poetry run python -m app.utils.retrieval_benchmark            # hybrid
    poetry run python -m app.utils.retrieval_benchmark --mode fts --k 5
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "retrieval_benchmark.json"
)

Mode = Literal["fts", "vector", "hybrid"]


@dataclass
class QueryResult:
    query: str
    relevant: list[str]
    retrieved: list[str]
    recall: float
    precision: float
    reciprocal_rank: float

    @property
    def missed(self) -> bool:
        return self.reciprocal_rank == 0.0


@dataclass
class BenchmarkResult:
    mode: str
    k: int
    n_queries: int
    n_documents: int
    recall_at_k: float
    precision_at_k: float
    mrr: float
    per_query: list[QueryResult] = field(default_factory=list)

    @property
    def misses(self) -> list[QueryResult]:
        """Queries where no relevant document was retrieved at all."""
        return [q for q in self.per_query if q.missed]

    def summary(self) -> str:
        return (
            f"mode={self.mode} k={self.k} "
            f"queries={self.n_queries} docs={self.n_documents} | "
            f"recall@{self.k}={self.recall_at_k:.3f} "
            f"precision@{self.k}={self.precision_at_k:.3f} "
            f"MRR={self.mrr:.3f} misses={len(self.misses)}"
        )


def load_fixture(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or DEFAULT_FIXTURE).read_text(encoding="utf-8"))


def _build_corpus_db(documents: list[dict], embed) -> sqlite3.Connection:
    """In-memory DB holding the fixture corpus, indexed the way YAPOC indexes.

    Mirrors the real schema and the real FTS trigger behaviour so the benchmark
    exercises the same query paths as production, not a simplified stand-in.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE memory_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL, source TEXT NOT NULL, content TEXT NOT NULL,
            timestamp TEXT NOT NULL, embedding BLOB,
            tier TEXT NOT NULL DEFAULT 'hot', provenance TEXT NOT NULL DEFAULT '',
            doc_id TEXT NOT NULL DEFAULT '');
        CREATE VIRTUAL TABLE memory_fts USING fts5(
            content, content_rowid='id', tokenize='porter unicode61');
        """
    )
    texts = [d["content"] for d in documents]
    vectors = embed(texts)
    for doc, vec in zip(documents, vectors):
        cur = conn.execute(
            """INSERT INTO memory_entries
               (agent, source, content, timestamp, embedding, tier, provenance, doc_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                doc.get("agent", "builder"),
                doc.get("source", "MEMORY.MD"),
                doc["content"],
                doc.get("timestamp", "2026-09-01T00:00:00Z"),
                np.asarray(vec, dtype=np.float32).tobytes(),
                doc.get("tier", "hot"),
                doc.get("provenance", ""),
                doc["id"],
            ),
        )
        conn.execute(
            "INSERT INTO memory_fts (rowid, content) VALUES (?, ?)",
            (cur.lastrowid, doc["content"]),
        )
    conn.commit()
    return conn


def _fts_ids(conn: sqlite3.Connection, query: str, limit: int) -> list[str]:
    # FTS5 MATCH treats bare punctuation as syntax; quote each term so a natural
    # question ("what broke the deploy?") cannot raise a syntax error.
    safe = " OR ".join(f'"{t}"' for t in query.replace('"', " ").split() if t)
    if not safe:
        return []
    try:
        rows = conn.execute(
            """SELECT m.doc_id FROM memory_fts f
               JOIN memory_entries m ON m.id = f.rowid
               WHERE memory_fts MATCH ? AND m.tier = 'hot'
               ORDER BY rank LIMIT ?""",
            (safe, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r["doc_id"] for r in rows]


def _vector_ids(conn: sqlite3.Connection, q_vec: np.ndarray, limit: int) -> list[str]:
    rows = conn.execute(
        "SELECT doc_id, embedding FROM memory_entries WHERE tier = 'hot'"
    ).fetchall()
    qn = q_vec / (np.linalg.norm(q_vec) or 1.0)
    scored: list[tuple[float, str]] = []
    for r in rows:
        vec = np.frombuffer(r["embedding"], dtype=np.float32)
        denom = np.linalg.norm(vec) or 1.0
        scored.append((float(np.dot(vec / denom, qn)), r["doc_id"]))
    scored.sort(reverse=True)
    return [doc_id for _, doc_id in scored[:limit]]


def _hybrid_ids(
    conn: sqlite3.Connection, query: str, q_vec: np.ndarray, limit: int
) -> list[str]:
    """RRF fusion, mirroring db.search_hybrid (K=60, 3x candidate pool)."""
    K = 60
    scores: dict[str, float] = {}
    for rank, doc_id in enumerate(_fts_ids(conn, query, limit * 3)):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (K + rank + 1)
    for rank, doc_id in enumerate(_vector_ids(conn, q_vec, limit * 3)):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (K + rank + 1)
    return [d for d, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:limit]]


def run_benchmark(
    fixture: dict[str, Any] | None = None,
    mode: Mode = "hybrid",
    k: int = 5,
    embed=None,
) -> BenchmarkResult:
    """Score the retrieval stack against the fixture. Pure function of inputs."""
    fixture = fixture or load_fixture()
    if embed is None:
        from app.utils.embeddings import embed_batch as embed

    documents = fixture["documents"]
    queries = fixture["queries"]
    conn = _build_corpus_db(documents, embed)

    q_vectors = embed([q["query"] for q in queries]) if mode != "fts" else [None] * len(queries)

    per_query: list[QueryResult] = []
    for spec, q_vec in zip(queries, q_vectors):
        text, relevant = spec["query"], list(spec["relevant"])
        if mode == "fts":
            retrieved = _fts_ids(conn, text, k)
        elif mode == "vector":
            retrieved = _vector_ids(conn, np.asarray(q_vec), k)
        else:
            retrieved = _hybrid_ids(conn, text, np.asarray(q_vec), k)

        hits = [d for d in retrieved if d in relevant]
        rr = 0.0
        for i, doc_id in enumerate(retrieved):
            if doc_id in relevant:
                rr = 1.0 / (i + 1)
                break
        per_query.append(
            QueryResult(
                query=text,
                relevant=relevant,
                retrieved=retrieved,
                recall=len(hits) / len(relevant) if relevant else 0.0,
                precision=len(hits) / k if k else 0.0,
                reciprocal_rank=rr,
            )
        )

    conn.close()
    n = len(per_query) or 1
    return BenchmarkResult(
        mode=mode,
        k=k,
        n_queries=len(per_query),
        n_documents=len(documents),
        recall_at_k=round(sum(q.recall for q in per_query) / n, 4),
        precision_at_k=round(sum(q.precision for q in per_query) / n, 4),
        mrr=round(sum(q.reciprocal_rank for q in per_query) / n, 4),
        per_query=per_query,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="YAPOC retrieval benchmark")
    ap.add_argument("--mode", choices=["fts", "vector", "hybrid", "all"], default="all")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--fixture", type=Path, default=None)
    ap.add_argument("--show-misses", action="store_true")
    args = ap.parse_args()

    fixture = load_fixture(args.fixture)
    modes = ["fts", "vector", "hybrid"] if args.mode == "all" else [args.mode]
    for mode in modes:
        result = run_benchmark(fixture, mode=mode, k=args.k)
        print(result.summary())
        if args.show_misses:
            for q in result.misses:
                print(f"    MISS: {q.query!r} -> {q.retrieved}")


if __name__ == "__main__":
    main()

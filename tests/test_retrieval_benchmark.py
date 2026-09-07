"""Phase 2.4 — retrieval quality regression thresholds.

`search_hybrid` was documented but never measured, so no change to indexing,
decay or consolidation could be shown to help or hurt. These thresholds are the
published floor the roadmap asks for; Phase 3.1 (typed memory layers) is gated
on them.

Measured baseline on the checked-in fixture (56 documents / 40 queries, k=5):

    fts     recall@5=0.950  precision@5=0.210  MRR=0.892  misses=1
    vector  recall@5=0.925  precision@5=0.200  MRR=0.912  misses=2
    hybrid  recall@5=0.963  precision@5=0.210  MRR=0.944  misses=1

Thresholds sit below those numbers on purpose: the embedding model is pinned by
name, not by hash, so a model update may move scores slightly. They are tight
enough to catch a real regression and loose enough not to fail on drift.
"""

from __future__ import annotations

import pytest

from app.utils.retrieval_benchmark import load_fixture, run_benchmark


@pytest.fixture(scope="module")
def fixture_data():
    return load_fixture()


@pytest.fixture(scope="module")
def embedder():
    """Local sentence-transformers model, skipped if it cannot be loaded.

    The model is a ~22MB download on first use. A network failure in CI must
    not turn this into a red build for an unrelated reason — a skip states
    honestly that retrieval went unmeasured on that run.
    """
    try:
        from app.utils.embeddings import embed_batch

        embed_batch(["warmup"])
        return embed_batch
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"embedding model unavailable: {exc}")


def test_fixture_is_well_formed(fixture_data):
    """A silently broken fixture would make every threshold below meaningless."""
    docs = fixture_data["documents"]
    queries = fixture_data["queries"]
    ids = [d["id"] for d in docs]

    assert len(ids) == len(set(ids)), "duplicate document ids"
    assert len(queries) >= 40, "the roadmap calls for a ~40-query set"
    assert all(d["content"].strip() for d in docs), "empty document content"

    known = set(ids)
    for q in queries:
        assert q["relevant"], f"query has no relevant docs: {q['query']}"
        unknown = set(q["relevant"]) - known
        assert not unknown, f"query {q['query']!r} references unknown docs {unknown}"

    # The corpus must contain the low-signal noise that dominates real memory,
    # or the benchmark measures an easier problem than the one that exists.
    assert sum(1 for i in ids if i.startswith("noise-")) >= 20


def test_hybrid_retrieval_meets_threshold(fixture_data, embedder):
    result = run_benchmark(fixture_data, mode="hybrid", k=5, embed=embedder)
    assert result.recall_at_k >= 0.90, result.summary()
    assert result.mrr >= 0.88, result.summary()
    assert len(result.misses) <= 3, (
        f"{len(result.misses)} queries returned nothing relevant: "
        f"{[q.query for q in result.misses]}"
    )


def test_hybrid_beats_each_single_ranker(fixture_data, embedder):
    """RRF fusion has to earn its complexity.

    If hybrid ever stops beating both rankers it fuses, the fusion is costing
    two searches for nothing and should be reconsidered rather than kept out of
    habit. Measured: hybrid MRR 0.944 vs fts 0.892 and vector 0.912.
    """
    hybrid = run_benchmark(fixture_data, mode="hybrid", k=5, embed=embedder)
    fts = run_benchmark(fixture_data, mode="fts", k=5, embed=embedder)
    vector = run_benchmark(fixture_data, mode="vector", k=5, embed=embedder)

    assert hybrid.mrr >= fts.mrr, f"hybrid {hybrid.mrr} < fts {fts.mrr}"
    assert hybrid.mrr >= vector.mrr, f"hybrid {hybrid.mrr} < vector {vector.mrr}"
    assert hybrid.recall_at_k >= max(fts.recall_at_k, vector.recall_at_k)


def test_keyword_only_retrieval_still_works(fixture_data, embedder):
    """FTS is the fallback when embeddings are unavailable; it must not rot."""
    result = run_benchmark(fixture_data, mode="fts", k=5, embed=embedder)
    assert result.recall_at_k >= 0.85, result.summary()


def test_recall_improves_with_larger_k(fixture_data, embedder):
    """Sanity check on the metric itself — recall must be monotonic in k."""
    small = run_benchmark(fixture_data, mode="hybrid", k=3, embed=embedder)
    large = run_benchmark(fixture_data, mode="hybrid", k=10, embed=embedder)
    assert large.recall_at_k >= small.recall_at_k


def test_repetitive_noise_can_still_crowd_out_signal(fixture_data, embedder):
    """Documents a KNOWN weakness rather than pretending it is fixed.

    'security audit findings' returns five `model_audit: N agents scanned`
    entries instead of the two real security findings: the word "audit" appears
    in dozens of near-identical low-signal rows, and sheer repetition outranks
    the specific match. This is the concrete evidence for Phase 3.1 — retention
    and demotion rules should collapse repetitive entries like these.

    When 3.1 lands, this test should start failing. That is the point: it flips
    to a passing assertion and the weakness is retired.
    """
    result = run_benchmark(fixture_data, mode="hybrid", k=5, embed=embedder)
    by_query = {q.query: q for q in result.per_query}
    crowded = by_query["security audit findings"]
    noise_hits = [d for d in crowded.retrieved if d.startswith("noise-")]
    assert noise_hits, (
        "repetitive-noise crowding appears to be FIXED — good. Update this "
        "test to assert the correct documents are retrieved, and note the "
        "improvement against the Phase 3.1 baseline."
    )

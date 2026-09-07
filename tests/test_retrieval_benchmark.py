"""Phase 2.4 — retrieval quality regression thresholds.

`search_hybrid` was documented but never measured, so no change to indexing,
decay or consolidation could be shown to help or hurt. These thresholds are the
published floor the roadmap asks for; Phase 3.1 (typed memory layers) is gated
on them.

Measured baseline on the checked-in fixture (56 documents / 40 queries, k=5),
with and without the Phase 3.1 repetition collapse:

                      recall@5   MRR    misses
    fts                 0.950   0.892     1
    fts + collapse      0.963   0.900     0
    vector              0.912   0.912     2
    vector + collapse   0.963   0.927     0
    hybrid              0.950   0.944     1
    hybrid + collapse   0.975   0.963     0

Collapse improves every mode and eliminates every miss. That is the evidence
Phase 3.1 was gated on.

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


def test_collapse_fixes_the_noise_crowding_that_2_4_found(fixture_data, embedder):
    """The Phase 2.4 finding, now closed.

    "security audit findings" used to return five `model_audit: N agents
    scanned` rows and none of the two real security findings — recall 0.0, a
    total miss, because dozens of near-identical low-signal entries outranked
    the specific match on repetition alone.

    With the Phase 3.1 collapse the same query retrieves both relevant
    documents. This test previously asserted the weakness still existed, with
    a note to flip it when 3.1 landed. This is that flip.
    """
    before = run_benchmark(fixture_data, mode="hybrid", k=5, embed=embedder)
    after = run_benchmark(
        fixture_data, mode="hybrid", k=5, embed=embedder, collapse=True
    )

    q_before = {q.query: q for q in before.per_query}["security audit findings"]
    q_after = {q.query: q for q in after.per_query}["security audit findings"]

    assert q_before.recall == 0.0, (
        "the pre-collapse miss no longer reproduces — if retrieval improved for "
        "another reason, re-baseline this test rather than deleting it"
    )
    assert q_after.recall == 1.0, f"still missing: {q_after.retrieved}"
    assert not any(d.startswith("noise-") and d != q_after.retrieved[0]
                   for d in q_after.retrieved[1:3])


def test_collapse_improves_every_retrieval_mode(fixture_data, embedder):
    """Collapse must not buy hybrid's gain at another mode's expense."""
    for mode in ("fts", "vector", "hybrid"):
        plain = run_benchmark(fixture_data, mode=mode, k=5, embed=embedder)
        collapsed = run_benchmark(
            fixture_data, mode=mode, k=5, embed=embedder, collapse=True
        )
        assert collapsed.recall_at_k >= plain.recall_at_k, (
            f"{mode}: recall regressed {plain.recall_at_k} -> {collapsed.recall_at_k}"
        )
        assert collapsed.mrr >= plain.mrr, (
            f"{mode}: MRR regressed {plain.mrr} -> {collapsed.mrr}"
        )
        assert len(collapsed.misses) <= len(plain.misses)


def test_collapse_leaves_no_query_unanswered(fixture_data, embedder):
    """The published 3.1 result: zero total misses in every mode."""
    for mode in ("fts", "vector", "hybrid"):
        result = run_benchmark(
            fixture_data, mode=mode, k=5, embed=embedder, collapse=True
        )
        assert not result.misses, (
            f"{mode} still misses: {[q.query for q in result.misses]}"
        )

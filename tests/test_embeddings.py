"""Tests for app.utils.embeddings — embedding model interface."""

import numpy as np
import pytest

from app.utils.embeddings import embed, embed_batch, _EMBEDDING_DIM


def test_embed_returns_correct_shape():
    vec = embed("hello world")
    assert vec.shape == (_EMBEDDING_DIM,)
    assert vec.dtype == np.float32


def test_embed_batch_returns_correct_shape():
    vecs = embed_batch(["hello", "world", "test"])
    assert vecs.shape == (3, _EMBEDDING_DIM)
    assert vecs.dtype == np.float32


def test_embed_batch_empty():
    vecs = embed_batch([])
    assert vecs.shape == (0, _EMBEDDING_DIM)
    assert vecs.dtype == np.float32


def test_embed_similar_texts_have_high_similarity():
    v1 = embed("the cat sat on the mat")
    v2 = embed("a cat is sitting on a mat")
    v3 = embed("quantum computing research paper")

    # Cosine similarity
    def cos_sim(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    sim_similar = cos_sim(v1, v2)
    sim_different = cos_sim(v1, v3)

    assert sim_similar > sim_different
    assert sim_similar > 0.5  # similar texts should be reasonably close

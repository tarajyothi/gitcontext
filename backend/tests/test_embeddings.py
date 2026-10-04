import httpx
import numpy as np
import pytest

from app.embeddings import EmbeddingError, HashingEmbedder, OpenAICompatEmbedder


def test_hashing_deterministic_normalised_shape():
    e = HashingEmbedder()
    a, b = e.embed(["def apply_discount(x): pass", "other"]), e.embed(["def apply_discount(x): pass", "other"])
    assert a.shape == (2, 384) and a.dtype == np.float32 and np.array_equal(a, b)
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0, atol=1e-5)
    assert not np.any(e.embed([""]))  # empty text -> zero vector, no crash


def test_hashing_ranks_relevant_chunk_first():
    e = HashingEmbedder()
    docs = ["def apply_discount(amount, coupon=None): rate = COUPONS.get(coupon)",
            "class EmptyCartError(Exception): raised when checkout is attempted with no items",
            "def render_template(html, context): return html.format(**context)"]
    m = e.embed(docs + ["apply discount coupon", "empty cart checkout error", "applyDiscount"])
    sims = m[3:] @ m[:3].T
    assert sims[0].argmax() == 0 and sims[1].argmax() == 1
    assert sims[2].argmax() == 0  # camelCase query matches snake_case identifier


def _transport(status=200, calls=None):
    def handler(req: httpx.Request):
        if calls is not None:
            calls.append(req)
        if status != 200:
            return httpx.Response(status)
        n = len(__import__("json").loads(req.content)["input"])
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [3.0, 4.0, 0.0]} for i in reversed(range(n))]})
    return httpx.MockTransport(handler)


def test_openai_compat_request_and_normalisation():
    calls = []
    e = OpenAICompatEmbedder("sk-test", "m", "https://x.test/v1/", _transport(calls=calls))
    out = e.embed(["a", "b"])
    assert calls[0].url == "https://x.test/v1/embeddings" and calls[0].headers["authorization"] == "Bearer sk-test"
    assert out.shape == (2, 3) and np.allclose(out[0], [0.6, 0.8, 0.0])
    assert e.name == "openai:m"


def test_openai_compat_errors():
    with pytest.raises(EmbeddingError):
        OpenAICompatEmbedder("", "m", "https://x.test/v1")
    with pytest.raises(EmbeddingError):
        OpenAICompatEmbedder("k", "m", "https://x.test/v1", _transport(401)).embed(["a"])

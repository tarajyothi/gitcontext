"""Embedding providers. All return L2-normalised float32 matrices (n, dim)."""
import hashlib
import math
import re
import time
from collections import Counter
from typing import Protocol

import httpx
import numpy as np

from .config import get_settings


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


_STOP = {"self", "def", "return", "the", "import", "from", "if", "else", "for", "in", "is", "not", "and",
         "or", "none", "true", "false", "class", "var", "let", "const", "function", "this", "new", "to", "of", "a"}


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def _features(text: str) -> Counter:
    feats: Counter = Counter()
    for ident in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
        parts = [p.lower() for p in re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", ident).replace("_", " ").split() if p]
        whole = ident.lower()
        if len(parts) > 1:
            feats[whole] += 1  # exact identifier match (e.g. apply_discount) is a strong signal
        for p in parts:
            if p not in _STOP and len(p) > 1:
                feats[_stem(p)] += 1
    return feats


class HashingEmbedder:
    """Deterministic, offline, identifier-aware feature-hashing embedder.

    NOT a neural model: it captures lexical overlap of identifiers/words (camelCase/snake_case aware),
    not paraphrase-level semantics. Use the OpenAI-compatible provider for neural embeddings.
    """
    dim = 384
    name = "hashing-v1-384"

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for r, t in enumerate(texts):
            for tok, cnt in _features(t).items():
                h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
                out[r, h % self.dim] += (1.0 if (h >> 40) & 1 else -1.0) * (1 + math.log(cnt))
            n = np.linalg.norm(out[r])
            if n:
                out[r] /= n
        return out


class OpenAICompatEmbedder:
    """Any OpenAI-compatible POST {base_url}/embeddings endpoint."""

    def __init__(self, api_key: str, model: str, base_url: str, transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise EmbeddingError("EMBEDDING_API_KEY is not set")
        self.name = f"openai:{model}"
        self._model, self._url = model, base_url.rstrip("/") + "/embeddings"
        self._client = httpx.Client(timeout=30, transport=transport, headers={"Authorization": f"Bearer {api_key}"})

    def embed(self, texts: list[str]) -> np.ndarray:
        last = None
        for attempt in range(3):
            try:
                r = self._client.post(self._url, json={"model": self._model, "input": texts})
                if r.status_code == 429 or r.status_code >= 500:
                    last = f"HTTP {r.status_code}"
                    time.sleep(0.5 * (attempt + 1))
                    continue
                if r.status_code != 200:
                    raise EmbeddingError(f"Embedding API returned HTTP {r.status_code}")
                data = sorted(r.json()["data"], key=lambda d: d["index"])
                m = np.asarray([d["embedding"] for d in data], dtype=np.float32)
                n = np.linalg.norm(m, axis=1, keepdims=True)
                return m / np.where(n == 0, 1, n)
            except httpx.HTTPError as e:
                last = type(e).__name__
                time.sleep(0.5 * (attempt + 1))
        raise EmbeddingError(f"Embedding API unavailable ({last})")


def get_embedder() -> Embedder:
    s = get_settings()
    if s.embedding_provider == "openai":
        return OpenAICompatEmbedder(s.embedding_api_key, s.embedding_model, s.embedding_base_url)
    return HashingEmbedder()

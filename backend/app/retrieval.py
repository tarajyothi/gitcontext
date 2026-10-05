"""Hybrid code retrieval.

Channels (each ranks chunks independently):
  * vector  - cosine similarity of stored embeddings
  * bm25    - lexical match; identifiers are split (camelCase / snake_case) and symbol/path terms are boosted
  * ident   - exact match of identifiers mentioned in the query against chunk symbols
Fusion: weighted Reciprocal Rank Fusion -> dedupe overlapping chunks -> heuristic rerank.
The reranker is a transparent feature-based heuristic (not a trained cross-encoder); its effect is measured
in benchmarks/run_benchmark.py.
"""
import math
import re
import threading
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .embeddings import _STOP, Embedder, _stem
from .models import Chunk, ChunkEmbedding

RRF_K = 60
CANDIDATES = 50
W_VECTOR, W_BM25, W_IDENT = 1.0, 1.0, 1.0
# reranker feature weights (tuned on the dev split only; see docs/benchmarks/retrieval.md)
RERANK = {"sym": 0.25, "exact": 0.30, "kind": 0.05, "test": 0.30, "doc": 0.25, "tiny": 0.05, "src": 0.10}
QSTOP = {"how", "what", "where", "which", "when", "why", "who", "does", "do", "did", "is", "are", "was", "were", "can",
         "could", "should", "would", "i", "me", "my", "we", "you", "your", "it", "its", "this", "that", "there", "these",
         "those", "by", "on", "at", "as", "be", "been", "if", "then", "than", "so", "into", "out", "up", "about", "use",
         "used", "using", "get", "gets", "work", "works", "find", "code", "defined", "implemented", "happens", "happen",
         "with", "after", "all", "any", "an", "has", "have", "some", "like", "per", "via"}
DOC_WORDS = {"doc", "docs", "documentation", "readme", "changelog", "tutorial", "guide", "example", "examples"}
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec)(/|$)|(^|/)test_[^/]*$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$")


def split_ident(ident: str) -> list[str]:
    return [p.lower() for p in re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", ident).replace("_", " ").split() if p]


def tokenize(text: str) -> list[str]:
    """Terms for BM25: whole multi-part identifiers + stemmed sub-words (stop words removed)."""
    out = []
    for ident in _TOKEN.findall(text):
        parts = split_ident(ident)
        if len(parts) > 1:
            out.append(ident.lower())
        out.extend(_stem(p) for p in parts if p not in _STOP and len(p) > 1)
    return out


def is_test_path(path: str) -> bool:
    return bool(_TEST_PATH.search(path.lower()))


def is_doc(path: str, language: str | None) -> bool:
    p = path.lower()
    return language == "markdown" or p.endswith((".md", ".rst", ".txt")) or p.startswith(("docs/", "doc/", "examples/", "example/"))


class BM25Index:
    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.n, self.k1, self.b = len(docs), k1, b
        self.len = np.array([len(d) for d in docs], dtype=np.float32)
        self.avg = float(self.len.mean()) if self.n else 1.0
        self.post: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, d in enumerate(docs):
            for t, f in Counter(d).items():
                self.post[t].append((i, f))
        self.idf = {t: math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.post.items()}

    def scores(self, terms: list[str]) -> np.ndarray:
        s = np.zeros(self.n, dtype=np.float32)
        for t in set(terms):
            for i, f in self.post.get(t, ()):
                s[i] += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
        return s


@dataclass
class Rec:
    id: int
    file_path: str
    symbol: str | None
    kind: str | None
    language: str | None
    start_line: int
    end_line: int
    content: str
    base: str  # symbol without ' (part N)'
    last: str  # last dotted segment, lowercased


@dataclass
class Corpus:
    recs: list[Rec]
    matrix: np.ndarray
    bm25: BM25Index
    sym_full: dict[str, list[int]]
    sym_last: dict[str, list[int]]
    is_test: np.ndarray
    is_doc: np.ndarray


_cache: "OrderedDict[tuple, Corpus]" = OrderedDict()
_lock = threading.Lock()


def invalidate(repo_id: int) -> None:
    """Drop cached search indexes for a repository (called on re-index and delete)."""
    with _lock:
        for k in [k for k in _cache if k[0] == repo_id]:
            del _cache[k]


def get_corpus(session: Session, repo_id: int, embedder: Embedder) -> Corpus:
    # SQLite reuses row ids after deletes, so ids alone are not a safe version stamp: add the newest insert time.
    n, mx, stamp = session.execute(select(func.count(), func.max(Chunk.id), func.max(Chunk.created_at))
                                   .where(Chunk.repository_id == repo_id)).one()
    key = (repo_id, n, mx, str(stamp), embedder.name)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    rows = session.execute(
        select(Chunk.id, Chunk.file_path, Chunk.symbol, Chunk.symbol_kind, Chunk.language, Chunk.start_line,
               Chunk.end_line, Chunk.content, ChunkEmbedding.vector)
        .join(ChunkEmbedding, (ChunkEmbedding.chunk_id == Chunk.id) & (ChunkEmbedding.model == embedder.name), isouter=True)
        .where(Chunk.repository_id == repo_id).order_by(Chunk.id)).all()
    if not rows:
        return None  # type: ignore[return-value]
    recs, vecs, docs = [], [], []
    dim = next((len(r[8]) // 4 for r in rows if r[8]), 0)
    for r in rows:
        base = re.sub(r" \(part \d+\)$", "", r[2] or "")
        recs.append(Rec(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], base, base.split(".")[-1].lower()))
        vecs.append(np.frombuffer(r[8], dtype=np.float32) if r[8] else np.zeros(dim, dtype=np.float32))
        docs.append(tokenize(r[7]) + tokenize(base) * 3 + tokenize(r[1]) * 2)
    sym_full, sym_last = defaultdict(list), defaultdict(list)
    for i, rc in enumerate(recs):
        if rc.base and rc.base not in ("<module>", "<intro>"):
            sym_full[rc.base.lower()].append(i)
            sym_last[rc.last].append(i)
    c = Corpus(recs, np.vstack(vecs) if dim else np.zeros((len(recs), 1), dtype=np.float32), BM25Index(docs),
               dict(sym_full), dict(sym_last), np.array([is_test_path(r.file_path) for r in recs]),
               np.array([is_doc(r.file_path, r.language) for r in recs]))
    with _lock:
        _cache[key] = c
        while len(_cache) > 4:
            _cache.popitem(last=False)
    return c


# ---------------------------------------------------------------- query analysis
_STRONG = [re.compile(p) for p in (r"`([^`]+)`", r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", r"\b_?[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b",
                                    r"\b_[A-Za-z]\w*", r"\b[A-Za-z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b")]


def query_terms(query: str) -> list[str]:
    return [t for t in tokenize(query) if t not in QSTOP]


def ident_scores(query: str, c: Corpus) -> dict[int, float]:
    """Chunk index -> score for chunks whose symbol is named in the query (qualified 2.0, strong 1.5, weak 0.5)."""
    found: dict[int, float] = {}

    def add(idxs, s):
        for i in idxs:
            found[i] = max(found.get(i, 0.0), s)

    strong = set()
    for rx in _STRONG:
        for m in rx.finditer(query):
            strong.add((m.group(1) if m.groups() else m.group(0)).strip("`").lower())
    for tok in strong:
        if tok in c.sym_full:
            add(c.sym_full[tok], 2.0)
        last = tok.split(".")[-1]
        if last in c.sym_last:
            add(c.sym_last[last], 1.5)
    words = query.split()
    for pos, raw in enumerate(words):  # capitalised class-like word in the middle of a sentence, e.g. "the Context class"
        w = raw.strip("?.,;:!\"'()")
        if pos and w[:1].isupper() and w.lower() not in QSTOP and w.lower() in c.sym_last:
            add(c.sym_last[w.lower()], 1.5)
    for raw in words:  # plain word equal to a (rare) symbol name: weak signal, ignored when ambiguous
        w = raw.strip("?.,;:!\"'()").lower()
        for cand in {w, _stem(w)}:
            if len(cand) >= 4 and cand not in QSTOP and cand in c.sym_last and len(c.sym_last[cand]) <= 3:
                add(c.sym_last[cand], 0.5)
    return found


def rank_of(scores: np.ndarray, mask: np.ndarray, limit: int, positive_only: bool = False) -> dict[int, int]:
    s = np.where(mask, scores, -np.inf)
    order = np.argsort(-s)[:limit]
    return {int(i): r + 1 for r, i in enumerate(order) if np.isfinite(s[i]) and (not positive_only or s[i] > 0)}


def overlaps(a: Rec, b: Rec) -> bool:
    if a.file_path != b.file_path:
        return False
    inter = min(a.end_line, b.end_line) - max(a.start_line, b.start_line) + 1
    return inter > 0 and inter / min(a.end_line - a.start_line + 1, b.end_line - b.start_line + 1) >= 0.5


def build_mask(c: Corpus, f: dict | None) -> np.ndarray:
    mask = np.ones(len(c.recs), dtype=bool)
    if not f:
        return mask
    langs = {x.lower() for x in f.get("language") or []}
    kinds = set(f.get("kinds") or [])
    prefix = f.get("path_prefix")
    for i, r in enumerate(c.recs):
        if (langs and (r.language or "").lower() not in langs) or (kinds and r.kind not in kinds) \
                or (prefix and not r.file_path.startswith(prefix)):
            mask[i] = False
    if f.get("exclude_tests"):
        mask &= ~c.is_test
    if f.get("exclude_docs"):
        mask &= ~c.is_doc
    return mask


def rerank_adjust(r: Rec, i: int, c: Corpus, terms: set[str], strong_hit: float, q_lower: str) -> float:
    w = RERANK
    adj = 0.0
    name_terms = set(tokenize(r.base)) | set(tokenize(r.file_path))
    if terms:
        adj += w["sym"] * len(terms & name_terms) / len(terms)
    if strong_hit >= 1.5:
        adj += w["exact"]
    adj += w["kind"] if r.kind in ("function", "method", "class") else -w["kind"]
    if c.is_test[i] and "test" not in q_lower:
        adj -= w["test"]
    if c.is_doc[i] and not (DOC_WORDS & set(re.findall(r"[a-z]+", q_lower))):
        adj -= w["doc"]
    if r.end_line - r.start_line < 2:
        adj -= w["tiny"]
    if r.file_path.startswith(("src/", "lib/")):  # implementation directories
        adj += w["src"]
    return adj


def search(session: Session, repo_id: int, query: str, k: int, embedder: Embedder, mode: str = "hybrid",
           filters: dict | None = None, rerank: bool = True) -> list[dict] | None:
    """Returns ranked hits, or None when the repository has no indexed chunks."""
    c = get_corpus(session, repo_id, embedder)
    if c is None:
        return None
    mask = build_mask(c, filters)
    if not mask.any():
        return []
    terms = query_terms(query)
    v_rank = rank_of(c.matrix @ embedder.embed([query])[0], mask, CANDIDATES) if mode in ("hybrid", "vector") else {}
    b_rank = rank_of(c.bm25.scores(terms), mask, CANDIDATES, positive_only=True) if mode in ("hybrid", "bm25") else {}
    ident = {i: s for i, s in ident_scores(query, c).items() if mask[i]} if mode == "hybrid" else {}
    i_rank = {i: r + 1 for r, (i, _) in enumerate(sorted(ident.items(), key=lambda kv: -kv[1]))}

    fused: dict[int, float] = defaultdict(float)
    if mode == "vector":
        for i, r in v_rank.items():
            fused[i] = 1.0 / r
    elif mode == "bm25":
        for i, r in b_rank.items():
            fused[i] = 1.0 / r
    else:
        for i, r in v_rank.items():
            fused[i] += W_VECTOR * getattr(embedder, "retrieval_weight", 1.0) / (RRF_K + r)
        for i, r in b_rank.items():
            fused[i] += W_BM25 / (RRF_K + r)
        for i, r in i_rank.items():
            fused[i] += W_IDENT * ident[i] / (RRF_K + r)
    ordered = sorted(fused, key=lambda i: -fused[i])

    kept: list[int] = []  # dedupe overlapping chunks of the same file, keeping the better-ranked one
    for i in ordered:
        if not any(overlaps(c.recs[i], c.recs[j]) for j in kept):
            kept.append(i)
        if len(kept) >= max(k, 30):
            break

    final = {i: fused[i] for i in kept}
    adj: dict[int, float] = {}
    if mode == "hybrid" and rerank and kept:
        top = max(fused[i] for i in kept) or 1.0
        q_lower, tset = query.lower(), set(terms)
        for i in kept:
            adj[i] = rerank_adjust(c.recs[i], i, c, tset, ident.get(i, 0.0), q_lower)
            final[i] = fused[i] / top + adj[i]
    out = []
    for i in sorted(kept, key=lambda i: -final[i])[:k]:
        r = c.recs[i]
        out.append({"chunk_id": r.id, "file_path": r.file_path, "symbol": r.symbol, "kind": r.kind, "language": r.language,
                    "start_line": r.start_line, "end_line": r.end_line, "content": r.content, "score": round(float(final[i]), 4),
                    "signals": {"vector_rank": v_rank.get(i), "bm25_rank": b_rank.get(i), "identifier": ident.get(i),
                                "rerank_adjustment": round(adj[i], 4) if i in adj else None}})
    return out

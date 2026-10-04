"""Grid-search retrieval weights on the DEV split only (in-process; reads the benchmark repo already indexed in the DB).
Usage: python benchmarks/tune.py <repo_id>   (the held-out test split is never touched here)"""
import itertools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import retrieval  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.embeddings import HashingEmbedder  # noqa: E402

rid = int(sys.argv[1])
Q = [q for q in json.loads((Path(__file__).parent / "click_questions.json").read_text())["questions"] if q["split"] == "dev"]
emb = HashingEmbedder()


def run(vec_w, **w):
    HashingEmbedder.retrieval_weight = vec_w
    retrieval.RERANK.update(w)
    ranks = []
    with SessionLocal() as s:
        for q in Q:
            hits = retrieval.search(s, rid, q["question"], 10, emb, "hybrid", None, True)
            ok = lambda h: any(h["file_path"] == e["file"] and re.sub(r" \(part \d+\)$", "", h["symbol"] or "") in e["symbols"] for e in q["expected"])
            ranks.append(next((i + 1 for i, h in enumerate(hits) if ok(h)), None))
    n = len(ranks)
    return {"R@1": sum(r == 1 for r in ranks) / n, "R@5": sum(bool(r and r <= 5) for r in ranks) / n, "MRR": sum(1 / r for r in ranks if r) / n}


rows = []
for vec_w, test, doc, sym, src in itertools.product([1.0, 0.6, 0.3, 0.15], [0.15, 0.3, 0.5], [0.1, 0.25, 0.4], [0.25, 0.5], [0.0, 0.1]):
    rows.append(((vec_w, test, doc, sym, src), run(vec_w, test=test, doc=doc, sym=sym, src=src)))
rows.sort(key=lambda r: (-r[1]["MRR"], -r[1]["R@5"]))
print("vec_w  test  doc   sym   src |  R@1   R@5   MRR   (DEV split, top 10 of", len(rows), "configs)")
for (v, t, d, s, c), m in rows[:10]:
    print(f"{v:<6} {t:<5} {d:<5} {s:<5} {c:<4}| {m['R@1']:.2f}  {m['R@5']:.2f}  {m['MRR']:.3f}")
base = next(m for k, m in rows if k == (1.0, 0.15, 0.1, 0.25, 0.0))
print("\nuntuned (vec 1.0, test .15, doc .1, sym .25, src 0):", {k: round(v, 3) for k, v in base.items()})
# plateau check: how many configs are within 0.02 MRR of the best (a wide plateau = not a lucky point)
best = rows[0][1]["MRR"]
print("configs within 0.02 MRR of best:", sum(1 for _, m in rows if m["MRR"] >= best - 0.02), "/", len(rows))

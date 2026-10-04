"""Retrieval benchmark against the real API.

Usage: python benchmarks/run_benchmark.py --api http://localhost:8000 --split dev [--failures] [--write-docs]
A hit is correct if the retrieved chunk's file matches AND its symbol (minus ' (part N)') is listed as acceptable.
"""
import argparse
import json
import re
import statistics
import time
from pathlib import Path

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--api", default="http://localhost:8000")
ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
ap.add_argument("--failures", action="store_true", help="print the top results for missed questions")
ap.add_argument("--write-docs", action="store_true")
a = ap.parse_args()

B = json.loads((Path(__file__).parent / "click_questions.json").read_text())
Q = [q for q in B["questions"] if a.split == "all" or q["split"] == a.split]
CONFIGS = [("vector only", {"mode": "vector"}), ("bm25 only", {"mode": "bm25"}),
           ("hybrid (RRF + dedupe)", {"mode": "hybrid", "rerank": False}), ("hybrid + rerank", {"mode": "hybrid", "rerank": True})]

c = httpx.Client(base_url=a.api, timeout=300)
email = f"bench-{int(time.time())}@example.com"
assert c.post("/auth/signup", json={"email": email, "password": "correct-horse-1"}).status_code == 201
rid = c.post("/repositories", json={"url": B["repository"]}).json()["id"]
for _ in range(600):
    repo = c.get(f"/repositories/{rid}").json()
    if repo["status"] in ("ready", "failed"):
        break
    time.sleep(0.5)
assert repo["status"] == "ready" and repo["commit_sha"].startswith(B["commit"]), f"repo not ready/pinned: {repo['status']} {repo.get('commit_sha')}"
c.post(f"/repositories/{rid}/search", json={"query": "warm up", "k": 1})  # builds the in-memory index (excluded from latency)


def correct(hit, q):
    base = re.sub(r" \(part \d+\)$", "", hit["symbol"] or "")
    return any(hit["file_path"] == e["file"] and base in e["symbols"] for e in q["expected"])


def evaluate(extra):
    rows = []
    for q in Q:
        t0 = time.perf_counter()
        hits = c.post(f"/repositories/{rid}/search", json={"query": q["question"], "k": 10, **extra}).json()
        dt = (time.perf_counter() - t0) * 1000
        rank = next((i + 1 for i, h in enumerate(hits) if correct(h, q)), None)
        rows.append({"id": q["id"], "type": q["type"], "split": q["split"], "rank": rank, "ms": dt, "hits": hits, "q": q})
    return rows


def metrics(rows):
    n = len(rows)
    r = lambda k: sum(1 for x in rows if x["rank"] and x["rank"] <= k) / n
    return {"n": n, "R@1": r(1), "R@3": r(3), "R@5": r(5), "R@10": r(10),
            "MRR": sum(1 / x["rank"] for x in rows if x["rank"]) / n,
            "p50_ms": statistics.median(x["ms"] for x in rows), "p95_ms": sorted(x["ms"] for x in rows)[int(0.95 * (n - 1))]}


results = {name: evaluate(extra) for name, extra in CONFIGS}
print(f"\nRepository {B['repository']} @ {B['commit']} | chunks={repo['chunk_count']} | questions={len(Q)} ({a.split})\n")
print(f"{'configuration':<24}{'R@1':>7}{'R@3':>7}{'R@5':>7}{'R@10':>7}{'MRR':>7}{'p50 ms':>9}{'p95 ms':>9}")
summary = {}
for name, rows in results.items():
    m = metrics(rows)
    summary[name] = m
    print(f"{name:<24}{m['R@1']:>7.2f}{m['R@3']:>7.2f}{m['R@5']:>7.2f}{m['R@10']:>7.2f}{m['MRR']:>7.2f}{m['p50_ms']:>9.0f}{m['p95_ms']:>9.0f}")
best = results["hybrid + rerank"]
print("\nby question type (hybrid + rerank):")
for t in ("identifier", "concept", "behavior"):
    sub = [x for x in best if x["type"] == t]
    if sub:
        m = metrics(sub)
        print(f"  {t:<11} n={m['n']:<3} R@1={m['R@1']:.2f} R@5={m['R@5']:.2f} MRR={m['MRR']:.2f}")
if a.failures:
    print("\nmissed in top-5 (hybrid + rerank):")
    for x in best:
        if not x["rank"] or x["rank"] > 5:
            print(f"- {x['id']} [{x['type']}] {x['q']['question']}\n    rank={x['rank']}  expected={[(e['file'].split('/')[-1], e['symbols'][:3]) for e in x['q']['expected']]}")
            for h in x["hits"][:3]:
                print(f"      got {h['file_path'].split('/')[-1]}:{h['start_line']} {h['symbol']}")
json.dump({"split": a.split, "summary": summary, "per_question": {n: [{"id": x["id"], "rank": x["rank"]} for x in r] for n, r in results.items()}},
          open("benchmark_report.json", "w"), indent=1)

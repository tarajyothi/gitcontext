"""Verify chunking + embeddings against a real repo through the live API.

Usage: python scripts/verify_chunks.py https://github.com/pallets/click [--api http://localhost:8000]
Checks: (1) every chunk's line range reproduces the file content exactly (Python and `sed`),
(2) one embedding per chunk, (3) prints a diverse sample for manual inspection, (4) sample searches.
"""
import json
import random
import subprocess
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.chunking import split_lines  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.ingest.service import workspace_path  # noqa: E402
from app.models import Chunk, ChunkEmbedding, Repository  # noqa: E402

url = sys.argv[1]
api = sys.argv[sys.argv.index("--api") + 1] if "--api" in sys.argv else "http://localhost:8000"
c = httpx.Client(base_url=api, timeout=300)
repo = c.post("/repositories", json={"url": url}).json()
rid = repo["id"]
stats = c.post(f"/repositories/{rid}/index").json()
print("INDEX STATS:", json.dumps(stats))

bad, sed_bad, sed_n = 0, 0, 0
with SessionLocal() as db:
    r = db.get(Repository, rid)
    root = workspace_path(r.id, r.owner, r.name)
    chunks = db.query(Chunk).filter_by(repository_id=rid).order_by(Chunk.file_path, Chunk.start_line).all()
    n_emb = db.query(ChunkEmbedding).filter_by(repository_id=rid).count()
    cache = {}
    for ch in chunks:
        lines = cache.setdefault(ch.file_path, split_lines((root / ch.file_path).read_bytes().decode("utf-8", "replace")))
        if ch.content != "\n".join(lines[ch.start_line - 1:ch.end_line]):
            bad += 1
    sample_for_sed = random.Random(7).sample(chunks, min(300, len(chunks)))
    for ch in sample_for_sed:  # independent check with sed (handles LF files; skip CRLF)
        raw = (root / ch.file_path).read_bytes()
        if b"\r" in raw:
            continue
        out = subprocess.run(["sed", "-n", f"{ch.start_line},{ch.end_line}p", str(root / ch.file_path)],
                             capture_output=True, text=True).stdout.rstrip("\n")
        sed_n += 1
        sed_bad += out != ch.content.rstrip("\n")
    wrong_dim = sum(1 for e in db.query(ChunkEmbedding).filter_by(repository_id=rid) if len(e.vector) != e.dim * 4)
    kinds = {}
    for ch in chunks:
        kinds.setdefault(ch.symbol_kind, []).append(ch)

print(f"CHUNKS={len(chunks)} EMBEDDINGS={n_emb} wrong_dim={wrong_dim}")
print(f"LINE-RANGE CHECK (python, all chunks): {len(chunks) - bad}/{len(chunks)} exact")
print(f"LINE-RANGE CHECK (sed, sampled):       {sed_n - sed_bad}/{sed_n} exact")

rnd = random.Random(3)
picks = []
for kind in ("function", "method", "class", "module", "section", "block"):
    pool = kinds.get(kind, [])
    picks += rnd.sample(pool, min(3 if kind in ("function", "method") else 2, len(pool)))
sample = []
for i, ch in enumerate(picks, 1):
    head = "\n".join(ch.content.splitlines()[:5])
    print(f"\n--- [{i}] {ch.file_path}:{ch.start_line}-{ch.end_line}  {ch.symbol_kind} {ch.symbol!r} ({ch.language})\n{head}")
    sample.append({"file": ch.file_path, "symbol": ch.symbol, "kind": ch.symbol_kind, "start": ch.start_line,
                   "end": ch.end_line, "head": head})
print(f"\nMANUALLY INSPECTED: {len(picks)} chunks")

queries = ["where are command line options parsed", "how does the Context object work",
           "echo function that prints colored output", "BadParameter error handling"]
searches = []
for q in queries:
    hits = c.post(f"/repositories/{rid}/search", json={"query": q, "k": 3}).json()
    print(f"\nQ: {q}")
    for h in hits:
        print(f"   {h['score']:.3f}  {h['file_path']}:{h['start_line']}-{h['end_line']}  {h['symbol']}")
    searches.append({"q": q, "hits": [{k: h[k] for k in ("score", "file_path", "start_line", "end_line", "symbol")} for h in hits]})
json.dump({"stats": stats, "chunks": len(chunks), "bad": bad, "sed_n": sed_n, "sed_bad": sed_bad,
           "sample": sample, "searches": searches, "url": url}, open("verify_report.json", "w"))
sys.exit(1 if bad or sed_bad or wrong_dim or n_emb != len(chunks) else 0)

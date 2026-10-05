"""Sweep the evidence-gate threshold on the DEV split only (in-process). Usage: python benchmarks/tune_gate.py <repo_id>
Reports, per threshold: share of unanswerable questions correctly refused vs answerable questions wrongly refused."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.answering import assess  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.embeddings import HashingEmbedder  # noqa: E402
from app.retrieval import search  # noqa: E402

rid, here = int(sys.argv[1]), Path(__file__).parent
ans = [q for q in json.loads((here / "click_questions.json").read_text())["questions"] if q["split"] == "dev"]
una = [q for q in json.loads((here / "unanswerable_questions.json").read_text())["questions"] if q["split"] == "dev"]
emb, rows = HashingEmbedder(), []
with SessionLocal() as s:
    for kind, qs in (("answerable", ans), ("unanswerable", una)):
        for q in qs:
            hits = search(s, rid, q["question"], 8, emb) or []
            g = assess(s, rid, q["question"], hits, emb)
            ident = any((h["signals"].get("identifier") or 0) >= 1.5 for h in hits[:3])
            rows.append((kind, q["id"], g["coverage"], ident, q["question"][:60]))
for kind in ("answerable", "unanswerable"):
    cov = sorted(r[2] for r in rows if r[0] == kind)
    print(f"{kind:<13} n={len(cov)} coverage min={cov[0]:.2f} median={cov[len(cov)//2]:.2f} max={cov[-1]:.2f}")
print("\nlowest-coverage ANSWERABLE:", [(r[1], r[2], r[3]) for r in sorted((r for r in rows if r[0] == 'answerable'), key=lambda r: r[2])[:5]])
print("highest-coverage UNANSWERABLE:", [(r[1], r[2], r[3]) for r in sorted((r for r in rows if r[0] == 'unanswerable'), key=lambda r: -r[2])[:5]])
print("\n tau  correct_refusal  false_refusal  balanced")
for tau in [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
    ref = lambda kind, tau=tau: [not (r[2] >= tau or r[3]) for r in rows if r[0] == kind]
    cr, fr = sum(ref("unanswerable")) / len(una), sum(ref("answerable")) / len(ans)
    print(f" {tau:.1f}   {cr:>10.2f}     {fr:>10.2f}     {(cr + 1 - fr) / 2:>8.2f}")

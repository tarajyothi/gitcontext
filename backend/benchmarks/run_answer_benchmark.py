"""End-to-end answer benchmark through POST /repositories/{id}/ask.
Answerable set (click_questions.json): the system should answer AND cite a correct source.
Unanswerable set (unanswerable_questions.json): the system must refuse (status=insufficient_evidence).
Usage: python benchmarks/run_answer_benchmark.py --split dev|test|all [--failures]   (server needs DAILY_QUESTION_LIMIT >= 60)"""
import argparse
import json
import re
import time
from pathlib import Path

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--api", default="http://localhost:8000")
ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
ap.add_argument("--failures", action="store_true")
a = ap.parse_args()
here = Path(__file__).parent
A = json.loads((here / "click_questions.json").read_text())
U = json.loads((here / "unanswerable_questions.json").read_text())
keep = lambda qs: [q for q in qs if a.split == "all" or q["split"] == a.split]

c = httpx.Client(base_url=a.api, timeout=300)
assert c.post("/auth/signup", json={"email": f"ans-{int(time.time())}@example.com", "password": "correct-horse-1"}).status_code == 201
rid = c.post("/repositories", json={"url": A["repository"]}).json()["id"]
while (repo := c.get(f"/repositories/{rid}").json())["status"] not in ("ready", "failed"):
    time.sleep(0.5)
assert repo["status"] == "ready", repo
inv = set()
for off in range(0, repo["chunk_count"] + 500, 500):
    inv |= {(x["file_path"], re.sub(r" \(part \d+\)$", "", x["symbol"] or "")) for x in c.get(f"/repositories/{rid}/chunks?limit=500&offset={off}").json()}
AQ = [q for q in keep(A["questions"]) if any((e["file"], s) in inv for e in q["expected"] for s in e["symbols"])]
UQ = keep(U["questions"])


def ask(q):
    r = c.post(f"/repositories/{rid}/ask", json={"question": q["question"]})
    assert r.status_code == 200, r.text
    return r.json()


def cited_ok(res, q):
    return any(ct["file_path"] == e["file"] and re.sub(r" \(part \d+\)$", "", ct["symbol"] or "") in e["symbols"]
               for ct in res["citations"] for e in q["expected"])


ares = [(q, ask(q)) for q in AQ]
ures = [(q, ask(q)) for q in UQ]
n_a, n_u = len(ares), len(ures)
answered = sum(r["status"] == "answered" for _, r in ares)
cited = sum(r["status"] == "answered" and cited_ok(r, q) for q, r in ares)
refused = sum(r["status"] == "insufficient_evidence" for _, r in ures)
bad_cite = sum(1 for _, r in ares + ures for ct in r["citations"] if not ct["snippet"] or ct["start_line"] > ct["end_line"])
print(f"\nsplit={a.split} | repo @ {repo['commit_sha'][:7]} | answerable n={n_a} | unanswerable n={n_u} | gate threshold from server config")
print(f"  correct refusals on unanswerable : {refused}/{n_u} = {refused / n_u:.2f}")
print(f"  false refusals on answerable     : {n_a - answered}/{n_a} = {(n_a - answered) / n_a:.2f}")
print(f"  answered with a correct source cited (of all answerable): {cited}/{n_a} = {cited / n_a:.2f}")
print(f"  answered but cited sources were wrong: {answered - cited}/{answered}")
print(f"  malformed citations: {bad_cite}")
if a.failures:
    print("\nfalse refusals:")
    for q, r in ares:
        if r["status"] != "answered":
            print(f"  {q['id']} cov={r['evidence_coverage']} {q['question']}")
    print("wrongly answered unanswerable:")
    for q, r in ures:
        if r["status"] == "answered":
            print(f"  {q['id']} cov={r['evidence_coverage']} {q['question']}")
json.dump({"split": a.split, "n_answerable": n_a, "n_unanswerable": n_u, "correct_refusal": refused / n_u, "false_refusal": (n_a - answered) / n_a,
           "cited_correct": cited / n_a, "wrongly_cited": answered - cited}, open("answer_report.json", "w"))

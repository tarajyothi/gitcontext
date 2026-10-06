"""Post-deploy smoke test. Run against the LIVE URL after every deploy.
  python scripts/smoke_test.py https://app.example.com [--insecure] [--repo https://github.com/pallets/click]
Creates a throw-away account (smoke-*@example.com), indexes a public repo, asks two questions, then removes the repo.
Exit code 0 = all checks passed."""
import argparse
import sys
import time

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("base")
ap.add_argument("--insecure", action="store_true", help="accept self-signed certificates (local testing only)")
ap.add_argument("--repo", default="https://github.com/pallets/click")
a = ap.parse_args()
base, https = a.base.rstrip("/"), a.base.startswith("https://")
ok_all = True


def check(name, cond, detail=""):
    global ok_all
    ok_all &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


c = httpx.Client(base_url=base, timeout=120, verify=not a.insecure, follow_redirects=False)
r = c.get("/")
h = {k.lower(): v for k, v in r.headers.items()}
check("landing page loads", r.status_code == 200)
check("security headers on pages", h.get("x-content-type-options") == "nosniff" and h.get("x-frame-options") == "DENY"
      and "frame-ancestors 'none'" in h.get("content-security-policy", ""), h.get("content-security-policy", "")[:60])
if https:
    check("HSTS on HTTPS", "max-age" in h.get("strict-transport-security", ""))
r = c.get("/api/health")
check("API health + database", r.status_code == 200 and r.json().get("database") == "ok", r.text[:80])
check("API docs are not exposed", c.get("/api/docs").status_code == 404 and c.get("/api/openapi.json").status_code == 404)
check("protected API rejects anonymous", c.get("/api/repositories").status_code == 401)
r = c.get("/dashboard")
loc = r.headers.get("location", "")
check("protected page redirects anonymous to /login on the SAME scheme/host", r.status_code in (307, 308) and (loc.startswith("/login") or loc.startswith(base + "/login")), loc)
email = f"smoke-{int(time.time())}@example.com"
r = c.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
cookie = " ".join(r.headers.get_list("set-cookie")).lower()
check("signup works", r.status_code == 201)
check("session cookie flags", "httponly" in cookie and "samesite=lax" in cookie and (not https or "secure" in cookie), cookie[:90])
r = c.post("/api/repositories", json={"url": a.repo})
rid = r.json().get("id")
check("repository accepted (pending)", r.status_code == 202 and r.json()["status"] == "pending")
t0, seen = time.time(), []
while time.time() - t0 < 240:
    repo = c.get(f"/api/repositories/{rid}").json()
    tag = repo["status"] + (":" + repo["stage"] if repo["stage"] else "")
    if not seen or seen[-1] != tag:
        seen.append(tag)
    if repo["status"] in ("ready", "failed"):
        break
    time.sleep(0.3)
check("indexing reaches ready", repo["status"] == "ready" and repo["chunk_count"] > 0, " -> ".join(seen) + f" | {repo.get('file_count')} files, {repo.get('chunk_count')} chunks")
hits = c.post(f"/api/repositories/{rid}/search", json={"query": "confirmation prompt yes no", "k": 3}).json()
check("search returns cited chunks", isinstance(hits, list) and len(hits) == 3 and all(x["start_line"] >= 1 for x in hits), hits[0]["file_path"] if hits else "")
ans = c.post(f"/api/repositories/{rid}/ask", json={"question": "How do I ask the user a yes or no confirmation question?"}).json()
check("answerable question -> cited answer", ans.get("status") == "answered" and ans["citations"], f"{ans.get('generation')} | {ans['citations'][0]['file_path']}" if ans.get("citations") else str(ans)[:100])
ref = c.post(f"/api/repositories/{rid}/ask", json={"question": "How are Stripe payments processed?"}).json()
check("unanswerable question -> refusal, no citations", ref.get("status") == "insufficient_evidence" and ref["citations"] == [], ref.get("answer", "")[:70])
other = httpx.Client(base_url=base, timeout=30, verify=not a.insecure)
other.post("/api/auth/signup", json={"email": "x-" + email, "password": "correct-horse-1"})
check("another account cannot see the repository", other.get(f"/api/repositories/{rid}").status_code == 404)
check("delete repository", c.delete(f"/api/repositories/{rid}").status_code == 204)
c.post("/api/auth/logout")
check("logout invalidates session", c.get("/api/repositories").status_code == 401)
print("\nSMOKE TEST " + ("PASSED" if ok_all else "FAILED"))
sys.exit(0 if ok_all else 1)

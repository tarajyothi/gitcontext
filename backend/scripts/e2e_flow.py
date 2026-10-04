"""End-to-end flow over HTTP through the Next.js proxy (same path the browser uses).
Usage: python scripts/e2e_flow.py http://localhost:3000 https://github.com/pallets/click
"""
import json
import sys
import time

import httpx

base, repo_url = sys.argv[1], sys.argv[2]
email = f"e2e-{int(time.time())}@example.com"
log, ok_all = [], True


def check(name, cond, extra=""):
    global ok_all
    ok_all &= bool(cond)
    log.append({"step": name, "ok": bool(cond), "detail": str(extra)[:160]})
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


c = httpx.Client(base_url=base, timeout=60, follow_redirects=False)
check("1 open app (landing renders)", c.get("/").status_code == 200)
r = c.get("/dashboard")
check("1b protected page without session redirects to /login", r.status_code in (307, 308) and "/login" in r.headers.get("location", ""), r.headers.get("location"))
check("1c protected API without session -> 401", c.get("/api/repositories").status_code == 401)
r = c.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
check("2 create account", r.status_code == 201, r.json().get("email"))
cookie = [h for h in r.headers.get_list("set-cookie") if "gc_session" in h][0].lower()
check("2b cookie is HttpOnly + SameSite=Lax", "httponly" in cookie and "samesite=lax" in cookie)
c.cookies.clear()
r = c.post("/api/auth/login", json={"email": email, "password": "correct-horse-1"})
check("3 log in", r.status_code == 200)
check("4 'refresh': session survives (/auth/me) and dashboard page loads", c.get("/api/auth/me").json()["email"] == email and c.get("/dashboard").status_code == 200)

r = c.post("/api/repositories", json={"url": repo_url})
rid = r.json()["id"]
check("5 connect real public repo -> 202 pending", r.status_code == 202 and r.json()["status"] == "pending", r.json()["status"])
seen, t0 = [], time.time()
while time.time() - t0 < 180:
    s = c.get(f"/api/repositories/{rid}").json()
    tag = s["status"] + (f":{s['stage']}" if s["stage"] else "")
    if not seen or seen[-1] != tag:
        seen.append(tag)
    if s["status"] in ("ready", "failed"):
        break
    time.sleep(0.15)
check("6 observed REAL state transitions", len(seen) >= 2 and seen[-1] == "ready", " -> ".join(seen))
check("8 READY with metadata", s["status"] == "ready" and s["file_count"] > 50 and s["chunk_count"] > 100 and len(s["commit_sha"]) == 40,
      f"files={s['file_count']} chunks={s['chunk_count']} branch={s['default_branch']}")
check("9 open repository workspace page", c.get(f"/repositories/{rid}").status_code == 200)
check("10-11 refresh: state persists", c.get(f"/api/repositories/{rid}").json()["chunk_count"] == s["chunk_count"])
hits = c.post(f"/api/repositories/{rid}/search", json={"query": "echo colored output", "k": 3}).json()
check("11b retrieval works on the indexed repo", len(hits) == 3 and hits[0]["start_line"] >= 1, hits[0]["file_path"] + ":" + str(hits[0]["start_line"]))

bad = c.post("/api/repositories", json={"url": "https://example.com/x/y"})
check("12a invalid URL -> clear 422", bad.status_code == 422 and "GitHub URL" in bad.json()["error"]["message"])
dup = c.post("/api/repositories", json={"url": repo_url})
check("12b duplicate -> 409", dup.status_code == 409, dup.json()["error"]["message"])
nf = c.post("/api/repositories", json={"url": "https://github.com/octocat/this-repo-does-not-exist-gitcontext-xyz"})
nid = nf.json()["id"]
for _ in range(100):
    f = c.get(f"/api/repositories/{nid}").json()
    if f["status"] in ("ready", "failed"):
        break
    time.sleep(0.2)
check("12c inaccessible repo -> failed with user-readable error", f["status"] == "failed" and "not found or private" in f["error_message"], f["error_message"])
check("12d failed repo has retry path", c.post(f"/api/repositories/{nid}/reindex").status_code == 202)
c.delete(f"/api/repositories/{nid}")

c.post("/api/auth/logout")
check("13a after logout: API 401", c.get("/api/repositories").status_code == 401 and c.get(f"/api/repositories/{rid}").status_code == 401)
r = c.get(f"/repositories/{rid}")
check("13b after logout: protected page redirects", r.status_code in (307, 308), r.headers.get("location"))
r = c.post("/api/auth/login", json={"email": email, "password": "correct-horse-1"})
check("14 log back in", r.status_code == 200)
lst = c.get("/api/repositories").json()
check("15 repository still exists after logout/login", any(x["id"] == rid and x["status"] == "ready" for x in lst))

other = httpx.Client(base_url=base, timeout=30)
other.post("/api/auth/signup", json={"email": "intruder-" + email, "password": "correct-horse-1"})
check("16 another user cannot see/open/delete it", other.get(f"/api/repositories/{rid}").status_code == 404
      and other.delete(f"/api/repositories/{rid}").status_code == 404 and other.get("/api/repositories").json() == [])
json.dump({"email": email, "states": seen, "steps": log, "repo": {k: s[k] for k in ("owner", "name", "file_count", "chunk_count", "total_bytes", "default_branch", "commit_sha", "languages")}},
          open("e2e_report.json", "w"))
print("\nALL PASSED" if ok_all else "\nSOME FAILED")
sys.exit(0 if ok_all else 1)

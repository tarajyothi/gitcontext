"""Measure incremental indexing on two real snapshots of a repository.
  python scripts/incremental_demo.py --old /path/to/checkout-A --new /path/to/checkout-B
Indexes A (full), re-indexes B (incremental), then forces a full rebuild of B for comparison."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--old", required=True)
ap.add_argument("--new", required=True)
a = ap.parse_args()
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite:///{tmp}/demo.db", WORKSPACE_DIR=f"{tmp}/ws", GIT_ALLOW_PROTOCOL="https:file",
                  RATE_WRITE_PER_MIN="1000", LOG_LEVEL="WARNING")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.ingest.cloner import clone_repo  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Repository  # noqa: E402
from app.routes import get_cloner  # noqa: E402

source = {"dir": a.old}
app.dependency_overrides[get_cloner] = lambda: (lambda url, dest: clone_repo("file://" + source["dir"], dest))
rev = lambda d: subprocess.run(["git", "-C", d, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()


def wait(c, rid):
    while (r := c.get(f"/repositories/{rid}").json())["status"] not in ("ready", "failed"):
        time.sleep(0.1)
    assert r["status"] == "ready", r
    return r


with TestClient(app) as c:
    c.post("/auth/signup", json={"email": "demo@example.com", "password": "correct-horse-1"})
    rid = c.post("/repositories", json={"url": "https://github.com/pallets/click"}).json()["id"]
    first = wait(c, rid)["last_index"]
    source["dir"] = a.new
    c.post(f"/repositories/{rid}/reindex")
    inc = wait(c, rid)["last_index"]
    with SessionLocal() as db:  # force a full rebuild of the same snapshot for an apples-to-apples comparison
        db.get(Repository, rid).index_signature = None
        db.commit()
    c.post(f"/repositories/{rid}/reindex")
    full = wait(c, rid)["last_index"]
print(f"snapshot A {rev(a.old)} -> snapshot B {rev(a.new)}\n")
for name, r in (("first index of A (full)", first), ("A -> B  INCREMENTAL", inc), ("B again, forced FULL", full)):
    print(f"{name:<26} files={r['files']:<4} new={r['new']:<3} changed={r['changed']:<3} removed={r['removed']:<3} unchanged={r['unchanged']:<4} "
          f"chunks reprocessed={r['chunks_reprocessed']:<5} reused={r['chunks_reused']:<5} index time={r['seconds']}s")
print(f"\nembedding work avoided: {inc['chunks_reused']} of {inc['chunks_total']} chunks ({100 * inc['chunks_reused'] / inc['chunks_total']:.1f}%)")
print(json.dumps({"incremental_seconds": inc["seconds"], "full_seconds": full["seconds"]}))

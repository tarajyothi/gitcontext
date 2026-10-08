"""Day-6 DEMO backend: the real application, but the 'GitHub clone' is served from a local fixture repository so that
secrets, symlinks and incremental changes can be shown in the real UI. Not for production use.
  python scripts/make_demo_repo.py /tmp/demo-repo && python scripts/demo_server.py /tmp/demo-repo"""
import os
import sys
import tempfile
from pathlib import Path

fixture = sys.argv[1]
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite:///{tmp}/demo.db", WORKSPACE_DIR=f"{tmp}/ws", GIT_ALLOW_PROTOCOL="https:file",
                  RATE_ASK_PER_MIN="3", LOG_LEVEL="WARNING")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn  # noqa: E402

from app.ingest.cloner import clone_repo  # noqa: E402
from app.main import app  # noqa: E402
from app.routes import get_cloner  # noqa: E402

app.dependency_overrides[get_cloner] = lambda: (lambda url, dest: clone_repo("file://" + fixture, dest))
uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

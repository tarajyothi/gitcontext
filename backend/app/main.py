"""GitContext API entrypoint."""
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import get_settings
from .db import SessionLocal, init_db
from .answering import LLMError
from .embeddings import EmbeddingError
from .ingest.errors import IngestError
from .auth import router as auth_router
from .models import Repository
from .routes import router, usage_router

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("gitcontext")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as s:  # a restart kills background jobs: never leave repos stuck in pending/indexing
        stuck = s.query(Repository).filter(Repository.status.in_(("pending", "indexing"))).all()
        for r in stuck:
            r.status, r.stage, r.error_message = "failed", None, "Indexing was interrupted by a server restart. Please retry."
        s.commit()
    log.info("database initialised (%d interrupted repositories marked failed)", len(stuck))
    yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


def error_body(code: str, message: str, request_id: str, details=None) -> dict:
    body = {"error": {"code": code, "message": message, "request_id": request_id}}
    if details is not None:
        body["error"]["details"] = details
    return body


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


@app.exception_handler(IngestError)
async def ingest_exc(request: Request, exc: IngestError):
    return JSONResponse(error_body(exc.code, exc.message, request.state.request_id), status_code=exc.status)


@app.exception_handler(EmbeddingError)
async def embedding_exc(request: Request, exc: EmbeddingError):
    return JSONResponse(error_body("embedding_unavailable", str(exc), request.state.request_id), status_code=502)


@app.exception_handler(LLMError)
async def llm_exc(request: Request, exc: LLMError):
    return JSONResponse(error_body("llm_unavailable", "The answer service is not available right now.", request.state.request_id), status_code=503)


@app.exception_handler(StarletteHTTPException)
async def http_exc(request: Request, exc: StarletteHTTPException):
    return JSONResponse(error_body("http_error", str(exc.detail), request.state.request_id), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exc(request: Request, exc: RequestValidationError):
    details = [{"field": ".".join(str(p) for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse(error_body("validation_error", "Invalid request", request.state.request_id, details), status_code=422)


@app.exception_handler(Exception)
async def unhandled_exc(request: Request, exc: Exception):
    # Log full detail server-side; never leak internals to the client.
    log.exception("unhandled error request_id=%s", request.state.request_id)
    return JSONResponse(error_body("internal_error", "Internal server error", request.state.request_id), status_code=500)


app.include_router(auth_router)
app.include_router(router)
app.include_router(usage_router)


@app.get("/health", tags=["system"])
def health():
    """Liveness + database connectivity check."""
    db_ok = True
    try:
        with SessionLocal() as s:
            s.execute(text("SELECT 1"))
    except Exception:
        log.exception("health check: database unreachable")
        db_ok = False
    body = {
        "status": "ok" if db_ok else "degraded",
        "service": settings.app_name,
        "version": settings.app_version,
        "database": "ok" if db_ok else "unreachable",
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)

"""GitContext API entrypoint (app factory)."""
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .answering import LLMError
from .auth import router as auth_router
from .config import Settings, get_settings, validate_production
from .db import SessionLocal, engine, init_db
from .embeddings import EmbeddingError
from .ingest.errors import IngestError
from .models import Repository
from .routes import router, usage_router

log = logging.getLogger("gitcontext")
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                    "Cache-Control": "no-store"}


def error_body(code: str, message: str, request_id: str, details=None) -> dict:
    body = {"error": {"code": code, "message": message, "request_id": request_id}}
    if details is not None:
        body["error"]["details"] = details
    return body


def create_app(s: Settings | None = None) -> FastAPI:
    s = s or get_settings()
    prod = s.environment == "production"
    logging.basicConfig(level=s.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if prod:
            problems = validate_production(s)
            if problems:
                raise RuntimeError("Refusing to start in production: " + "; ".join(problems))
            if "alembic_version" not in inspect(engine).get_table_names():
                raise RuntimeError("Database is not migrated. Run: alembic upgrade head")
        else:
            init_db()
        with SessionLocal() as db:  # a restart kills background jobs: never leave repos stuck in pending/indexing
            stuck = db.query(Repository).filter(Repository.status.in_(("pending", "indexing"))).all()
            for r in stuck:
                r.status, r.stage, r.error_message = "failed", None, "Indexing was interrupted by a server restart. Please retry."
            db.commit()
        log.info("started env=%s (%d interrupted repositories marked failed)", s.environment, len(stuck))
        yield

    app = FastAPI(title=s.app_name, version=s.app_version, lifespan=lifespan,
                  docs_url=None if prod else "/docs", redoc_url=None, openapi_url=None if prod else "/openapi.json")
    if s.allowed_hosts.strip():
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=[h.strip() for h in s.allowed_hosts.split(",") if h.strip()])
    if not prod and s.cors_origin_list:  # production is same-origin behind the proxy: no CORS at all
        app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=True,
                           allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])

    @app.middleware("http")
    async def edge(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        t0 = time.perf_counter()
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > s.max_body_bytes:
            response = JSONResponse(error_body("payload_too_large", "Request body is too large.", rid), status_code=413)
        else:
            response = await call_next(request)
        response.headers["x-request-id"] = rid
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if s.cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.url.path != "/health":  # path only: never log query strings, cookies or bodies
            log.info("%s %s -> %d %.0fms rid=%s", request.method, request.url.path, response.status_code,
                     (time.perf_counter() - t0) * 1000, rid)
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
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
        except Exception:
            log.exception("health check: database unreachable")
            db_ok = False
        body = {"status": "ok" if db_ok else "degraded", "service": s.app_name, "version": s.app_version,
                "database": "ok" if db_ok else "unreachable"}
        return JSONResponse(body, status_code=200 if db_ok else 503)

    return app


app = create_app()

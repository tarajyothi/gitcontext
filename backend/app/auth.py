"""Authentication routes + FastAPI dependencies (current user / workspace / owned repository)."""
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_session
from .ingest.errors import IngestError
from .models import AuthSession, Repository, User, Workspace, utcnow
from .security import DUMMY_HASH, hash_password, login_limiter, new_token, rate_limiter, token_hash, verify_password

COOKIE = "gc_session"
router = APIRouter(prefix="/auth", tags=["auth"])
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


class SignupBody(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginBody(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


def _norm(email: str) -> str:
    e = email.strip().lower()
    if not _EMAIL.match(e):
        raise IngestError("invalid_email", "Enter a valid email address.", 422)
    return e


def _login_response(session: Session, user: User, response: Response, status: int = 200) -> dict:
    s = get_settings()
    token = new_token()
    session.add(AuthSession(user_id=user.id, token_hash=token_hash(token),
                            expires_at=utcnow() + timedelta(days=s.session_days)))
    session.commit()
    response.status_code = status
    response.set_cookie(COOKIE, token, max_age=s.session_days * 86400, httponly=True, samesite="lax",
                        secure=s.cookie_secure, path="/")
    return user_dict(session, user)


def user_dict(session: Session, user: User) -> dict:
    ws = session.scalar(select(Workspace).where(Workspace.owner_id == user.id))
    return {"id": user.id, "email": user.email, "workspace": {"id": ws.id, "name": ws.name}}


def too_many(retry_after: int) -> IngestError:
    return IngestError("rate_limited", f"Too many requests. Try again in {retry_after} seconds.", 429, {"Retry-After": str(retry_after)})


@router.post("/signup")
def signup(body: SignupBody, request: Request, response: Response, session: Session = Depends(get_session)):
    wait = rate_limiter.hit(f"signup:{request.client.host if request.client else '?'}", get_settings().rate_signup_per_hour, 3600)
    if wait:
        raise too_many(wait)
    email = _norm(body.email)
    if session.scalar(select(User).where(User.email == email)):
        raise IngestError("email_taken", "An account with this email already exists. Try logging in.", 409)
    user = User(email=email, password_hash=hash_password(body.password))
    session.add(user)
    session.flush()
    session.add(Workspace(owner_id=user.id, name=f"{email.split('@')[0]}'s workspace"))
    session.commit()
    return _login_response(session, user, response, 201)


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, session: Session = Depends(get_session)):
    email = body.email.strip().lower()
    key = f"{request.client.host if request.client else '?'}|{email}"
    if login_limiter.blocked(key):
        raise IngestError("too_many_attempts", "Too many failed attempts. Try again in a few minutes.", 429)
    user = session.scalar(select(User).where(User.email == email))
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not (user and ok):
        login_limiter.fail(key)
        raise IngestError("invalid_credentials", "Invalid email or password.", 401)
    login_limiter.reset(key)
    return _login_response(session, user, response)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, session: Session = Depends(get_session)):
    token = request.cookies.get(COOKIE)
    if token:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        session.commit()
    response.delete_cookie(COOKIE, path="/")
    response.status_code = 204
    return response


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise IngestError("not_authenticated", "Please log in to continue.", 401)
    row = session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
    if row is None:
        raise IngestError("not_authenticated", "Please log in to continue.", 401)
    if row.expires_at.replace(tzinfo=row.expires_at.tzinfo or utcnow().tzinfo) < utcnow():
        session.delete(row)
        session.commit()
        raise IngestError("session_expired", "Your session has expired. Please log in again.", 401)
    return session.get(User, row.user_id)


@router.get("/me")
def me(user: User = Depends(current_user), session: Session = Depends(get_session)):
    return user_dict(session, user)


def get_workspace(user: User = Depends(current_user), session: Session = Depends(get_session)) -> Workspace:
    return session.scalar(select(Workspace).where(Workspace.owner_id == user.id))


def owned_repo(repo_id: int, ws: Workspace = Depends(get_workspace), session: Session = Depends(get_session)) -> Repository:
    """Server-side ownership check. Foreign or missing IDs both return 404 (no ID enumeration)."""
    repo = session.scalar(select(Repository).where(Repository.id == repo_id, Repository.workspace_id == ws.id))
    if repo is None:
        raise HTTPException(404, "Repository not found")
    return repo


def limited(setting: str, window_s: int = 60):
    """Per-user rate limit dependency; the limit is read from settings at request time."""
    def dep(user: User = Depends(current_user)) -> None:
        wait = rate_limiter.hit(f"{setting}:{user.id}", getattr(get_settings(), setting), window_s)
        if wait:
            raise too_many(wait)
    return dep

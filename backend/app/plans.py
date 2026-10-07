"""Plan entitlements (Free / Pro / Team). No billing here: a payment webhook would call set_plan().
Free-plan numbers come from settings; paid plans are fixed multiples, so limits stay in one place."""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .config import get_settings
from .models import Workspace

MULTIPLIER = {"free": 1, "pro": 5, "team": 20}


@dataclass(frozen=True)
class Limits:
    plan: str
    repos: int
    daily_questions: int
    max_indexed_bytes: int


def limits_for(plan: str | None) -> Limits:
    s = get_settings()
    name = plan if plan in MULTIPLIER else "free"
    m = MULTIPLIER[name]
    return Limits(name, s.max_repos_per_workspace * m, s.daily_question_limit * m, s.max_indexed_bytes * m)


def set_plan(session: Session, ws: Workspace, plan: str) -> None:
    """The single integration point for a future billing provider."""
    if plan not in MULTIPLIER:
        raise ValueError(f"unknown plan {plan!r}")
    ws.plan = plan
    session.commit()

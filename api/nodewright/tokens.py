"""Personal access tokens: how an MCP client acts as a user.

Only `/mcp` accepts them; the REST API stays cookie-only, so a leaked token
can draw diagrams but cannot mint more tokens or change the style guide.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AccessToken, User, utcnow

PREFIX = "nwp_"
MAX_PER_USER = 20
TOUCH_EVERY = timedelta(minutes=1)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(s: Session, user: User, name: str) -> tuple[AccessToken, str]:
    raw = PREFIX + secrets.token_urlsafe(32)
    row = AccessToken(user_id=user.id, name=name.strip()[:100] or "token",
                      token_hash=_hash(raw), prefix=raw[:12])
    s.add(row)
    s.flush()
    return row, raw


def count(s: Session, user: User) -> int:
    return len(list(s.scalars(select(AccessToken.id).where(AccessToken.user_id == user.id))))


def verify(s: Session, raw: str) -> AccessToken | None:
    if not raw.startswith(PREFIX) or len(raw) > 100:
        return None
    row = s.scalar(select(AccessToken).where(AccessToken.token_hash == _hash(raw)))
    if row is None:
        return None
    now = utcnow()
    last = row.last_used_at
    if last is None or (last if last.tzinfo else last.replace(tzinfo=now.tzinfo)) < now - TOUCH_EVERY:
        row.last_used_at = now
    return row


def bearer(header: str | None) -> str:
    if not header:
        return ""
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def out(row: AccessToken) -> dict:
    return {"id": row.id, "name": row.name, "prefix": row.prefix,
            "created_at": row.created_at.isoformat(),
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None}

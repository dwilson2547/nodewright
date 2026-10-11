"""Edit leases: one writer per canvas at a time (design §11.3).

Every write takes or renews the lease for its holder, so nothing has to
remember to lock. A browser tab holds it briefly after each save; an agent
holds it longer, renewed by each tool call, or explicitly via lock_canvas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import events
from .models import CanvasLease, User, utcnow

UI_TTL = timedelta(seconds=30)
AGENT_TTL = timedelta(minutes=2)
MAX_AGENT_LOCK = timedelta(minutes=15)


@dataclass(frozen=True)
class Holder:
    kind: str           # ui | agent
    user: User
    client: str         # browser tab id, or access token id
    label: str

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.user.id}:{self.client}"[:128]

    @property
    def ttl(self) -> timedelta:
        return UI_TTL if self.kind == "ui" else AGENT_TTL


class Locked(Exception):
    def __init__(self, lease: CanvasLease):
        super().__init__(describe(lease)["message"])
        self.lease = lease


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def active(s: Session, canvas_id: str) -> CanvasLease | None:
    row = s.get(CanvasLease, canvas_id)
    if row is not None and _aware(row.expires_at) <= utcnow():
        return None
    return row


def describe(row: CanvasLease | None) -> dict | None:
    if row is None:
        return None
    left = max(0, int((_aware(row.expires_at) - utcnow()).total_seconds()))
    return {"holder": row.holder, "kind": row.kind, "label": row.label,
            "expires_at": _aware(row.expires_at).isoformat(), "seconds_left": left,
            "message": f"locked by {row.label}; free in {left} s unless renewed"}


def take(s: Session, canvas_id: str, who: Holder, ttl: timedelta | None = None,
         force: bool = False) -> CanvasLease:
    """Take or renew. Raises Locked if someone else holds a live lease."""
    expires = utcnow() + (ttl or who.ttl)
    row = s.get(CanvasLease, canvas_id)
    fresh = row is None or row.holder != who.key or _aware(row.expires_at) <= utcnow()
    if row is not None and row.holder != who.key and _aware(row.expires_at) > utcnow() \
            and not force:
        raise Locked(row)
    if row is None:
        row = CanvasLease(canvas_id=canvas_id, holder=who.key, kind=who.kind,
                          user_id=who.user.id, label=who.label[:160], expires_at=expires)
        try:
            with s.begin_nested():
                s.add(row)
        except IntegrityError:
            # Another writer created it between our read and insert.
            s.expire_all()
            raced = active(s, canvas_id)
            if raced is not None and raced.holder != who.key:
                raise Locked(raced) from None
            return take(s, canvas_id, who, ttl, force)
    else:
        row.holder, row.kind, row.user_id = who.key, who.kind, who.user.id
        row.label, row.expires_at = who.label[:160], expires
    if fresh:
        events.queue(s, canvas_id, {"type": "lease", "lease": describe(row)})
    return row


def release(s: Session, canvas_id: str, who: Holder | None = None) -> bool:
    """Drop the lease; with `who`, only if they hold it."""
    row = s.get(CanvasLease, canvas_id)
    if row is None or (who is not None and row.holder != who.key):
        return False
    s.delete(row)
    events.queue(s, canvas_id, {"type": "lease", "lease": None})
    return True

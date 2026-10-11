"""Versions (design §14): a tab's revision history, named versions and restore.

Every save is already a row in canvas_revisions. A named version is a
revision with a `label`; naming one never changes the document, so it needs
edit rights but not the edit lease. Restoring is a normal save of an old
document (source "restore", `restored_from` set): history is only appended to,
and the restore is itself one undo away.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Canvas, CanvasRevision, User

MAX_LABEL = 200
LIST_LIMIT = 100


class VersionError(Exception):
    def __init__(self, what: str, status: int = 422):
        super().__init__(what)
        self.status = status


def _out(r: CanvasRevision, by: str | None) -> dict:
    return {"revision": r.revision, "source": r.source, "created_at": r.created_at.isoformat(),
            "by": by, "label": r.label, "restored_from": r.restored_from}


def listing(s: Session, c: Canvas, before: int | None = None, named: bool = False,
            limit: int = LIST_LIMIT) -> dict:
    """Newest first, `limit` at a time; pass the last revision seen as `before`
    for the next page."""
    q = (select(CanvasRevision, User.username)
         .outerjoin(User, User.id == CanvasRevision.user_id)
         .where(CanvasRevision.canvas_id == c.id)
         .order_by(CanvasRevision.revision.desc())
         .limit(limit + 1))
    if before is not None:
        q = q.where(CanvasRevision.revision < before)
    if named:
        q = q.where(CanvasRevision.label.is_not(None))
    rows = s.execute(q).all()
    return {"current": c.revision, "revisions": [_out(r, by) for r, by in rows[:limit]],
            "more": len(rows) > limit}


def _row(s: Session, c: Canvas, revision: int) -> CanvasRevision:
    r = s.scalar(select(CanvasRevision).where(CanvasRevision.canvas_id == c.id,
                                              CanvasRevision.revision == revision))
    if r is None:
        raise VersionError(f"this tab has no revision {revision}", 404)
    return r


def get(s: Session, c: Canvas, revision: int) -> dict:
    r = _row(s, c, revision)
    by = s.scalar(select(User.username).where(User.id == r.user_id)) if r.user_id else None
    return {**_out(r, by), "data": r.data}


def name(s: Session, c: Canvas, revision: int | None, label) -> dict:
    """Name (or with an empty/None label, unname) a revision; the current one
    when `revision` is None."""
    if label is not None and not isinstance(label, str):
        raise VersionError("label must be text")
    label = (label or "").strip()[:MAX_LABEL] or None
    r = _row(s, c, c.revision if revision is None else revision)
    r.label = label
    s.flush()
    by = s.scalar(select(User.username).where(User.id == r.user_id)) if r.user_id else None
    return _out(r, by)

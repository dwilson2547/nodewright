"""Read-only share links (design §9): create, list, revoke, and resolve a
token to what it may show."""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Canvas, ShareLink

MAX_PER_CANVAS = 20


class ShareError(Exception):
    def __init__(self, what: str, status: int = 404):
        super().__init__(what)
        self.status = status


def out(link: ShareLink, public_url: str) -> dict:
    return {"id": link.id, "canvas_id": link.canvas_id, "all_tabs": link.all_tabs,
            "url": f"{public_url.rstrip('/')}/s/{link.token}",
            "created_at": link.created_at.isoformat()}


def for_canvas(s: Session, canvas_id: str) -> list[ShareLink]:
    return list(s.scalars(select(ShareLink).where(ShareLink.canvas_id == canvas_id)
                          .order_by(ShareLink.created_at)))


def create(s: Session, canvas: Canvas, user_id: str, all_tabs: bool) -> ShareLink:
    if len(for_canvas(s, canvas.id)) >= MAX_PER_CANVAS:
        raise ShareError(f"a canvas can have at most {MAX_PER_CANVAS} share links", 422)
    link = ShareLink(token=secrets.token_urlsafe(24), canvas_id=canvas.id,
                     all_tabs=all_tabs, created_by=user_id)
    s.add(link)
    s.flush()
    return link


def resolve(s: Session, token: str) -> tuple[ShareLink, Canvas]:
    link = s.scalar(select(ShareLink).where(ShareLink.token == token)) if token else None
    canvas = s.get(Canvas, link.canvas_id) if link else None
    if link is None or canvas is None:
        raise ShareError("this link doesn't exist or was revoked")
    return link, canvas


def visible(s: Session, token: str, canvas_id: str) -> tuple[ShareLink, Canvas, list[Canvas]]:
    """The canvas a viewer asked for, if the link covers it, plus the tabs the
    viewer may see (just the shared one unless all_tabs)."""
    link, shared = resolve(s, token)
    if not link.all_tabs:
        if canvas_id != shared.id:
            raise ShareError("not part of this share")
        return link, shared, [shared]
    tabs = list(s.scalars(select(Canvas).where(Canvas.workspace_id == shared.workspace_id)
                          .order_by(Canvas.position)))
    hit = next((c for c in tabs if c.id == canvas_id), None)
    if hit is None:
        raise ShareError("not part of this share")
    return link, hit, tabs

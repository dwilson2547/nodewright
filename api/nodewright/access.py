"""Every permission decision (design §11.1).

Routes and MCP tools call authorize(); none of them compare owner ids
themselves. Today only owners exist in practice, but members and roles are
already read here, so sharing and organisations later change this module,
not every endpoint.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Canvas, User, Workspace, WorkspaceMember

READ = "workspace.read"
MANAGE = "workspace.manage"          # rename, delete
CANVAS_CREATE = "canvas.create"
CANVAS_EDIT = "canvas.edit"
CANVAS_DELETE = "canvas.delete"
LEASE_BREAK = "lease.break"
MEMBERS_MANAGE = "members.manage"

ROLES: dict[str, frozenset[str]] = {
    "owner": frozenset({READ, MANAGE, CANVAS_CREATE, CANVAS_EDIT, CANVAS_DELETE, LEASE_BREAK,
                        MEMBERS_MANAGE}),
    "editor": frozenset({READ, CANVAS_CREATE, CANVAS_EDIT, CANVAS_DELETE, LEASE_BREAK}),
    "viewer": frozenset({READ}),
}


class Denied(Exception):
    """Not found or not allowed; the two are deliberately indistinguishable
    to the caller unless it can at least read the workspace."""

    def __init__(self, what: str, status: int = 404):
        super().__init__(what)
        self.status = status


def role_on(s: Session, user: User, ws: Workspace) -> str | None:
    if ws.owner_id == user.id:
        return "owner"
    return s.scalar(select(WorkspaceMember.role).where(
        WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == user.id))


def can(s: Session, user: User, ws: Workspace, action: str) -> bool:
    role = role_on(s, user, ws)
    return role is not None and action in ROLES.get(role, frozenset())


def workspace(s: Session, user: User, ws_id: str, action: str = READ) -> Workspace:
    ws = s.get(Workspace, ws_id)
    role = role_on(s, user, ws) if ws is not None else None
    if role is None:
        raise Denied("workspace not found")
    if action not in ROLES.get(role, frozenset()):
        raise Denied("you can't do that in this workspace", 403)
    return ws


def canvas(s: Session, user: User, canvas_id: str, action: str = READ) -> Canvas:
    c = s.get(Canvas, canvas_id)
    if c is None:
        raise Denied("canvas not found")
    try:
        workspace(s, user, c.workspace_id, action)
    except Denied as exc:
        raise Denied("canvas not found" if exc.status == 404 else str(exc), exc.status) from None
    return c


def visible_workspaces(s: Session, user: User) -> list[Workspace]:
    member_of = select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)
    return list(s.scalars(select(Workspace)
                          .where(or_(Workspace.owner_id == user.id, Workspace.id.in_(member_of)))
                          .order_by(Workspace.created_at)))


def http(exc: Denied) -> HTTPException:
    return HTTPException(exc.status, str(exc))

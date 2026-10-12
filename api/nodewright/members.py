"""Workspace members (design §11.1): who besides the owner can open a
workspace, and with which role.

The owner is `workspaces.owner_id` and never has a row here. Owners add an
existing user by exact username (they must have signed in once), change their
role, or remove them; any member may remove themselves (leave). Permission
checks stay in access.py.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import access, leases
from .models import Canvas, CanvasLease, User, Workspace, WorkspaceFolder, WorkspaceMember

ASSIGNABLE = ("editor", "viewer")
MAX_PER_WORKSPACE = 100


class MemberError(Exception):
    def __init__(self, what: str, status: int = 422):
        super().__init__(what)
        self.status = status


def out(user: User, role: str) -> dict:
    return {"user_id": user.id, "username": user.username, "role": role}


def listing(s: Session, ws: Workspace) -> list[dict]:
    """The owner first (a personal workspace's; an org's workspace has none,
    its org admins act as owners), then members by username."""
    rows = s.execute(select(User, WorkspaceMember.role)
                     .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
                     .where(WorkspaceMember.workspace_id == ws.id)
                     .order_by(User.username)).all()
    head = [out(ws.owner, "owner")] if ws.org_id is None else []
    return head + [out(u, r) for u, r in rows]


def _role(role: str) -> str:
    if role not in ASSIGNABLE:
        raise MemberError(f"role must be one of: {', '.join(ASSIGNABLE)}")
    return role


def _row(s: Session, ws: Workspace, user_id: str) -> WorkspaceMember:
    m = s.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id,
                                               WorkspaceMember.user_id == user_id))
    if m is None:
        raise MemberError("not a member of this workspace", 404)
    return m


def add(s: Session, ws: Workspace, username: str, role: str) -> dict:
    role = _role(role)
    user = s.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None:
        raise MemberError("no user with that username; they need to sign in to nodewright once", 404)
    if ws.org_id is None and user.id == ws.owner_id:
        raise MemberError("that's the workspace owner")
    existing = s.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id,
                                                      WorkspaceMember.user_id == user.id))
    if existing is not None:
        raise MemberError(f"{user.username} is already a member ({existing.role})", 409)
    count = len(s.scalars(select(WorkspaceMember.id)
                          .where(WorkspaceMember.workspace_id == ws.id)).all())
    if count >= MAX_PER_WORKSPACE:
        raise MemberError(f"a workspace can have at most {MAX_PER_WORKSPACE} members")
    s.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=role))
    s.flush()
    return out(user, role)


def set_role(s: Session, ws: Workspace, user_id: str, role: str) -> dict:
    m = _row(s, ws, user_id)
    m.role = _role(role)
    return out(s.get(User, user_id), m.role)


def remove(s: Session, ws: Workspace, user_id: str) -> None:
    """Drop a member, their filing of the workspace in their own folders, and
    any edit leases they hold in it, so nobody waits out a lock they can't release."""
    s.delete(_row(s, ws, user_id))
    held = s.scalars(select(CanvasLease.canvas_id).join(Canvas, Canvas.id == CanvasLease.canvas_id)
                     .where(CanvasLease.user_id == user_id, Canvas.workspace_id == ws.id)).all()
    for canvas_id in held:
        leases.release(s, canvas_id)
    s.execute(delete(WorkspaceFolder).where(WorkspaceFolder.workspace_id == ws.id,
                                            WorkspaceFolder.user_id == user_id))
    s.flush()


def may_remove(s: Session, actor: User, ws: Workspace, user_id: str) -> bool:
    """Owners remove anyone; everyone else only themselves."""
    return actor.id == user_id or access.can(s, actor, ws, access.MEMBERS_MANAGE)

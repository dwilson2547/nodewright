"""Every permission decision (design §11.1, §19).

Routes and MCP tools call these; none of them compare owner ids themselves.
A user's role on a workspace is the highest of:
- owner: the owner of a personal workspace, or an admin of the org that owns it;
- the workspace's org_access (viewer/editor) for any member of its org;
- their own row in workspace_members.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Canvas, OrgMember, User, Workspace, WorkspaceMember

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


RANK = {"viewer": 1, "editor": 2, "owner": 3}
ORG_ROLES = ("admin", "member")
ORG_ACCESS = ("none", "viewer", "editor")


class Denied(Exception):
    """Not found or not allowed; the two are deliberately indistinguishable
    to the caller unless it can at least read the workspace."""

    def __init__(self, what: str, status: int = 404):
        super().__init__(what)
        self.status = status


def org_role(s: Session, user: User, org_id: str) -> str | None:
    """admin, member, or None if the user isn't in the org."""
    return s.scalar(select(OrgMember.role).where(OrgMember.org_id == org_id,
                                                 OrgMember.user_id == user.id))


def role_on(s: Session, user: User, ws: Workspace) -> str | None:
    if ws.org_id is None:
        if ws.owner_id == user.id:
            return "owner"
        via_org = None
    else:
        in_org = org_role(s, user, ws.org_id)
        if in_org == "admin":
            return "owner"
        via_org = ws.org_access if in_org and ws.org_access in RANK else None
    own = s.scalar(select(WorkspaceMember.role).where(
        WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == user.id))
    roles = [r for r in (via_org, own) if r]
    return max(roles, key=RANK.get) if roles else None


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
    admin_of = select(OrgMember.org_id).where(OrgMember.user_id == user.id, OrgMember.role == "admin")
    in_org = select(OrgMember.org_id).where(OrgMember.user_id == user.id)
    return list(s.scalars(select(Workspace).where(or_(
        (Workspace.owner_id == user.id) & Workspace.org_id.is_(None),
        Workspace.id.in_(member_of),
        Workspace.org_id.in_(admin_of),
        Workspace.org_id.in_(in_org) & (Workspace.org_access != "none"),
    )).order_by(Workspace.created_at)))


def http(exc: Denied) -> HTTPException:
    return HTTPException(exc.status, str(exc))

"""Organisations (design §19): who is in an org, with which role, and which
workspaces it owns. Permission checks on workspaces stay in access.py.

Org roles: admin (owner rights on every org workspace, manages the org) and
member (gets each org workspace's org_access role). Anyone signed in may
create an org and becomes its admin. Admins add existing users by exact
username, as for workspace members. An org always keeps at least one admin,
and can only be deleted once it owns no workspaces.

Memberships with source "authentik" come from ORG_GROUPS (config.py) at each
sign-in (sync_groups) and are only changed that way.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import access, leases
from .models import Canvas, CanvasLease, Org, OrgMember, User, Workspace, WorkspaceFolder, WorkspaceMember

log = logging.getLogger("nodewright.orgs")

MAX_MEMBERS = 500
MANUAL, AUTHENTIK = "manual", "authentik"


class OrgError(Exception):
    def __init__(self, what: str, status: int = 422):
        super().__init__(what)
        self.status = status


def _name(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > 200:
        raise OrgError("an org name is 1-200 characters")
    return name


def _role(role: str) -> str:
    if role not in access.ORG_ROLES:
        raise OrgError(f"role must be one of: {', '.join(access.ORG_ROLES)}")
    return role


def out(org: Org, role: str | None, managed: set[str] = frozenset()) -> dict:
    """managed: org names ORG_GROUPS refers to (renaming one would break the mapping)."""
    return {"id": org.id, "name": org.name, "role": role, "managed": org.name in managed}


def mine(s: Session, user: User) -> list[tuple[Org, str]]:
    return list(s.execute(select(Org, OrgMember.role).join(OrgMember, OrgMember.org_id == Org.id)
                          .where(OrgMember.user_id == user.id).order_by(Org.name)).all())


def get(s: Session, user: User, org_id: str, admin: bool = False) -> tuple[Org, str]:
    """The org and the user's role in it; 404 if they aren't in it, 403 if
    admin is required and they aren't one."""
    org = s.get(Org, org_id)
    role = access.org_role(s, user, org_id) if org else None
    if role is None:
        raise OrgError("org not found", 404)
    if admin and role != "admin":
        raise OrgError("only an org admin can do that", 403)
    return org, role


def create(s: Session, user: User, name: str) -> Org:
    name = _name(name)
    if s.scalar(select(Org.id).where(Org.name == name)):
        raise OrgError("an org with that name already exists", 409)
    org = Org(name=name)
    s.add(org)
    s.flush()
    s.add(OrgMember(org_id=org.id, user_id=user.id, role="admin"))
    s.flush()
    return org


def rename(s: Session, org: Org, name: str, managed: set[str]) -> None:
    if org.name in managed:
        raise OrgError("this org is named in the server's authentik group mapping; "
                       "rename it there first", 409)
    name = _name(name)
    if name != org.name and s.scalar(select(Org.id).where(Org.name == name)):
        raise OrgError("an org with that name already exists", 409)
    org.name = name


def remove_org(s: Session, org: Org) -> None:
    if s.scalar(select(func.count()).select_from(Workspace).where(Workspace.org_id == org.id)):
        raise OrgError("move or delete this org's workspaces first", 409)
    s.delete(org)
    s.flush()


# --- members --------------------------------------------------------------------

def listing(s: Session, org: Org) -> list[dict]:
    rows = s.execute(select(User, OrgMember).join(OrgMember, OrgMember.user_id == User.id)
                     .where(OrgMember.org_id == org.id)
                     .order_by(OrgMember.role, User.username)).all()
    return [{"user_id": u.id, "username": u.username, "role": m.role, "source": m.source}
            for u, m in rows]


def _row(s: Session, org: Org, user_id: str) -> OrgMember:
    m = s.scalar(select(OrgMember).where(OrgMember.org_id == org.id, OrgMember.user_id == user_id))
    if m is None:
        raise OrgError("not a member of this org", 404)
    return m


def _admins(s: Session, org: Org) -> int:
    return s.scalar(select(func.count()).select_from(OrgMember)
                    .where(OrgMember.org_id == org.id, OrgMember.role == "admin"))


def _manual(m: OrgMember) -> None:
    if m.source == AUTHENTIK:
        raise OrgError("this membership comes from an authentik group; change it there", 409)


def add(s: Session, org: Org, username: str, role: str) -> dict:
    role = _role(role)
    user = s.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None:
        raise OrgError("no user with that username; they need to sign in to nodewright once", 404)
    if access.org_role(s, user, org.id):
        raise OrgError(f"{user.username} is already in this org", 409)
    if s.scalar(select(func.count()).select_from(OrgMember).where(OrgMember.org_id == org.id)) >= MAX_MEMBERS:
        raise OrgError(f"an org can have at most {MAX_MEMBERS} members")
    s.add(OrgMember(org_id=org.id, user_id=user.id, role=role))
    s.flush()
    return {"user_id": user.id, "username": user.username, "role": role, "source": MANUAL}


def set_role(s: Session, org: Org, user_id: str, role: str) -> dict:
    m = _row(s, org, user_id)
    _manual(m)
    role = _role(role)
    if m.role == "admin" and role != "admin" and _admins(s, org) == 1:
        raise OrgError("an org needs at least one admin; make someone else admin first", 409)
    m.role = role
    s.flush()
    user = s.get(User, user_id)
    return {"user_id": user.id, "username": user.username, "role": role, "source": m.source}


def remove(s: Session, org: Org, user_id: str, *, synced: bool = False) -> None:
    """Take someone out of the org. They keep any workspace they were added
    to by name; edit locks and folder filings for the rest go."""
    m = _row(s, org, user_id)
    if not synced:
        _manual(m)
        if m.role == "admin" and _admins(s, org) == 1:
            raise OrgError("an org needs at least one admin; make someone else admin first", 409)
    s.delete(m)
    s.flush()
    lost_access(s, s.get(User, user_id), org.id)


def lost_access(s: Session, user: User, org_id: str) -> None:
    """After a user's access to org workspaces shrank: release their edit
    locks and folder filings wherever they can no longer read."""
    for ws in s.scalars(select(Workspace).where(Workspace.org_id == org_id)):
        if access.role_on(s, user, ws) is not None:
            continue
        held = s.scalars(select(CanvasLease.canvas_id).join(Canvas, Canvas.id == CanvasLease.canvas_id)
                         .where(CanvasLease.user_id == user.id, Canvas.workspace_id == ws.id)).all()
        for canvas_id in held:
            leases.release(s, canvas_id)
        s.execute(delete(WorkspaceFolder).where(WorkspaceFolder.workspace_id == ws.id,
                                                WorkspaceFolder.user_id == user.id))
    s.flush()


# --- workspaces -------------------------------------------------------------------

def set_access(ws: Workspace, value: str) -> None:
    if ws.org_id is None:
        raise OrgError("only an org's workspace has org access")
    if value not in access.ORG_ACCESS:
        raise OrgError(f"org access must be one of: {', '.join(access.ORG_ACCESS)}")
    ws.org_access = value


def move(s: Session, actor: User, ws: Workspace, org_id: str | None, owner: str | None) -> None:
    """Into an org the actor belongs to, or out of an org to a member's
    personal space. The caller has checked the actor may manage `ws`."""
    was = ws.org_id
    if org_id is not None:
        if not access.org_role(s, actor, org_id):
            raise OrgError("you can only move a workspace into an org you're in", 403)
        if org_id == ws.org_id:
            return
        ws.org_id = org_id
    else:
        if ws.org_id is None:
            raise OrgError("this workspace is already personal")
        name = (owner or actor.username).strip().lower()
        user = s.scalar(select(User).where(User.username == name))
        if user is None or not access.org_role(s, user, ws.org_id):
            raise OrgError("the new owner must be a member of the org", 404)
        ws.org_id, ws.owner_id = None, user.id
        # The owner never has a member row (members.py).
        s.execute(delete(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id,
                                                WorkspaceMember.user_id == user.id))
    s.flush()
    if was is not None:
        for (uid,) in s.execute(select(OrgMember.user_id).where(OrgMember.org_id == was)).all():
            lost_access(s, s.get(User, uid), was)


# --- authentik groups -------------------------------------------------------------

def sync_groups(s: Session, user: User, groups: list[str], mapping: dict[str, tuple[str, str]]) -> None:
    """Make the user's authentik-sourced memberships match their groups.
    mapping is ORG_GROUPS: authentik group -> (org name, role). Orgs it names
    are created when first needed. Only those orgs are touched, and only
    rows that came from authentik: a membership an admin added by hand stays."""
    if not mapping:
        return
    want: dict[str, str] = {}
    for g in set(groups or []):
        if g in mapping:
            org_name, role = mapping[g]
            if want.get(org_name) != "admin":
                want[org_name] = role
    for org_name in {name for name, _ in mapping.values()}:
        org = s.scalar(select(Org).where(Org.name == org_name))
        if org is None and org_name not in want:
            continue
        if org is None:
            org = Org(name=org_name)
            s.add(org)
            s.flush()
            log.warning("orgs: created %s from ORG_GROUPS", org_name)
        m = s.scalar(select(OrgMember).where(OrgMember.org_id == org.id, OrgMember.user_id == user.id))
        role = want.get(org_name)
        if role and m is None:
            s.add(OrgMember(org_id=org.id, user_id=user.id, role=role, source=AUTHENTIK))
            log.warning("orgs: %s joins %s as %s (authentik)", user.username, org_name, role)
        elif role and m.source == AUTHENTIK and m.role != role:
            log.warning("orgs: %s in %s %s -> %s (authentik)", user.username, org_name, m.role, role)
            m.role = role
        elif not role and m is not None and m.source == AUTHENTIK:
            log.warning("orgs: %s leaves %s (authentik)", user.username, org_name)
            remove(s, org, user.id, synced=True)
    s.flush()

"""Org-shared libraries (design §20): who sees, edits and shares templates and icons.

A template or icon belongs to its author (owner_id). With org_id set it's
shared with that org instead:
- every org member sees and uses it;
- its author (while still in the org) and the org's admins edit or delete it;
- only its author moves it, into another org they're in or back to their own.
An author who leaves the org leaves it with the org.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import access
from .models import Org, OrgMember, User


class LibraryError(Exception):
    def __init__(self, what: str, status: int = 422):
        super().__init__(what)
        self.status = status


def visible_filter(model, user: User):
    """SQL condition: the user's own unshared items, and their orgs' items."""
    my_orgs = select(OrgMember.org_id).where(OrgMember.user_id == user.id)
    return or_((model.owner_id == user.id) & model.org_id.is_(None), model.org_id.in_(my_orgs))


def can_see(s: Session, user: User, item) -> bool:
    if item.org_id is None:
        return item.owner_id == user.id
    return access.org_role(s, user, item.org_id) is not None


def can_edit(s: Session, user: User, item) -> bool:
    if item.org_id is None:
        return item.owner_id == user.id
    role = access.org_role(s, user, item.org_id)
    return role == "admin" or (role is not None and item.owner_id == user.id)


def share(s: Session, user: User, item, org_id: str | None) -> None:
    """Move an item into one of the author's orgs, or back to just them."""
    if item.owner_id != user.id or not can_see(s, user, item):
        raise LibraryError("only its author can share or unshare it", 403)
    if org_id is not None and access.org_role(s, user, org_id) is None:
        raise LibraryError("you can only share with an org you're in", 403)
    item.org_id = org_id


def check_org(s: Session, user: User, org_id: str | None) -> None:
    """For creating an item straight into an org."""
    if org_id is not None and access.org_role(s, user, org_id) is None:
        raise LibraryError("org not found", 404)


def describe(s: Session, user: User, item, names: dict[str, str] | None = None) -> dict:
    """The fields every listed item carries: its org and whether you may edit it."""
    org = None
    if item.org_id is not None:
        name = (names or {}).get(item.org_id) or s.get(Org, item.org_id).name
        org = {"id": item.org_id, "name": name}
    return {"org": org, "can_edit": can_edit(s, user, item), "mine": item.owner_id == user.id}


def org_names(s: Session, user: User) -> dict[str, str]:
    return {o.id: o.name for o in s.scalars(
        select(Org).join(OrgMember, OrgMember.org_id == Org.id).where(OrgMember.user_id == user.id))}

"""Folders: a user's own tree for organising workspaces (design §11.2).

Folders belong to one user and only that user sees them. A workspace is
filed per user (workspace_folders), so when workspaces are shared each person
keeps their own arrangement. Filing needs only read access to the workspace.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import access
from .models import Folder, User, WorkspaceFolder

MAX_DEPTH = 8
MAX_FOLDERS = 500


class FolderError(Exception):
    def __init__(self, what: str, status: int = 422):
        super().__init__(what)
        self.status = status


def out(f: Folder) -> dict:
    return {"id": f.id, "name": f.name, "parent_id": f.parent_id}


def all_for(s: Session, user: User) -> list[Folder]:
    return list(s.scalars(select(Folder).where(Folder.owner_id == user.id)
                          .order_by(Folder.name, Folder.created_at)))


def placements(s: Session, user: User) -> dict[str, str]:
    """workspace id -> folder id, for workspaces this user has filed."""
    return dict(s.execute(select(WorkspaceFolder.workspace_id, WorkspaceFolder.folder_id)
                          .where(WorkspaceFolder.user_id == user.id)).all())


def get(s: Session, user: User, folder_id: str) -> Folder:
    f = s.get(Folder, folder_id)
    if f is None or f.owner_id != user.id:
        raise FolderError("folder not found", 404)
    return f


def _depth(s: Session, f: Folder | None) -> int:
    n = 0
    while f is not None:
        n += 1
        f = s.get(Folder, f.parent_id) if f.parent_id else None
    return n


def _subtree_height(s: Session, f: Folder) -> int:
    kids = s.scalars(select(Folder).where(Folder.parent_id == f.id)).all()
    return 1 + max((_subtree_height(s, k) for k in kids), default=0)


def create(s: Session, user: User, name: str, parent_id: str | None) -> Folder:
    if len(all_for(s, user)) >= MAX_FOLDERS:
        raise FolderError(f"you can have at most {MAX_FOLDERS} folders")
    parent = get(s, user, parent_id) if parent_id else None
    if _depth(s, parent) >= MAX_DEPTH:
        raise FolderError(f"folders nest at most {MAX_DEPTH} deep")
    f = Folder(owner_id=user.id, parent_id=parent.id if parent else None, name=name.strip())
    s.add(f)
    s.flush()
    return f


def move(s: Session, user: User, f: Folder, parent_id: str | None) -> None:
    parent = get(s, user, parent_id) if parent_id else None
    p = parent
    while p is not None:
        if p.id == f.id:
            raise FolderError("a folder can't go inside itself")
        p = s.get(Folder, p.parent_id) if p.parent_id else None
    if _depth(s, parent) + _subtree_height(s, f) > MAX_DEPTH:
        raise FolderError(f"folders nest at most {MAX_DEPTH} deep")
    f.parent_id = parent.id if parent else None


def remove(s: Session, user: User, f: Folder) -> None:
    """Delete a folder and its subfolders; their workspaces go back to the
    top level (the placement rows cascade away)."""
    ids, frontier = [f.id], [f.id]
    while frontier:
        frontier = list(s.scalars(select(Folder.id).where(Folder.parent_id.in_(frontier))))
        ids += frontier
    # Explicit, so it doesn't depend on SQLite having foreign keys switched on.
    s.execute(delete(WorkspaceFolder).where(WorkspaceFolder.folder_id.in_(ids)))
    for fid in reversed(ids):
        s.delete(s.get(Folder, fid))
    s.flush()


def file(s: Session, user: User, workspace_id: str, folder_id: str | None) -> None:
    """Put a workspace in one of the user's folders, or back at the top level."""
    access.workspace(s, user, workspace_id)
    row = s.get(WorkspaceFolder, (user.id, workspace_id))
    if folder_id is None:
        if row is not None:
            s.delete(row)
        return
    f = get(s, user, folder_id)
    if row is None:
        s.add(WorkspaceFolder(user_id=user.id, workspace_id=workspace_id, folder_id=f.id))
    else:
        row.folder_id = f.id

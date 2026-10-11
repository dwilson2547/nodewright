"""Database schema.

Changes go through Alembic (nodewright/migrations; the app upgrades itself at
start-up, db.Database.migrate). After editing a model, from api/:
  DATABASE_URL=sqlite:////tmp/nw-mig.db alembic upgrade head
  DATABASE_URL=sqlite:////tmp/nw-mig.db alembic revision --autogenerate --rev-id NNNN -m "..."
then read the generated file before committing it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

Json = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    identities: Mapped[list["UserIdentity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    sessions: Mapped[list["SessionToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    workspaces: Mapped[list["Workspace"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", passive_deletes=True)


class UserIdentity(Base):
    """An authentik identity (issuer + sub) linked to a local user."""
    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    issuer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="identities")


class SessionToken(Base):
    """A browser session. Only the SHA-256 of the token is stored, so a
    database leak hands out nothing usable, and signing out is a row delete."""
    __tablename__ = "session_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[User] = relationship(back_populates="workspaces")
    canvases: Mapped[list["Canvas"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", passive_deletes=True,
        order_by="Canvas.position")


class Canvas(Base):
    """One tab: a JSON Canvas document. `data` is the current document;
    `revision` increments on every save and every save is kept in
    canvas_revisions."""
    __tablename__ = "canvases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(Json)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    workspace: Mapped[Workspace] = relationship(back_populates="canvases")


class CanvasRevision(Base):
    __tablename__ = "canvas_revisions"
    __table_args__ = (UniqueConstraint("canvas_id", "revision"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    canvas_id: Mapped[str] = mapped_column(
        ForeignKey("canvases.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(Json)
    source: Mapped[str] = mapped_column(String(16), default="ui")
    """Who made the change: ui | import | mcp."""
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkspaceMember(Base):
    """Someone other than the owner with a role on a workspace (design §11.1).
    The owner is `workspaces.owner_id` and has no row here. Nothing writes these
    yet; access.authorize() already reads them, so sharing adds rows, not checks."""
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccessToken(Base):
    """A personal access token for MCP clients. Stored hashed like sessions;
    `prefix` is the visible start of the token so a user can tell them apart."""
    __tablename__ = "access_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()


class CanvasLease(Base):
    """Who may write a canvas right now (design §11.3). Expiry, not release, is
    the safety net: a crashed agent's lease just lapses."""
    __tablename__ = "canvas_leases"

    canvas_id: Mapped[str] = mapped_column(
        ForeignKey("canvases.id", ondelete="CASCADE"), primary_key=True)
    holder: Mapped[str] = mapped_column(String(128))
    """kind:user_id:client — one browser tab or one access token."""
    kind: Mapped[str] = mapped_column(String(8))
    """ui | agent"""
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(160))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StyleGuide(Base):
    """A user's "how I like my diagrams" notes, handed to agents (design §11.4)."""
    __tablename__ = "style_guides"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OAuthClient(Base):
    """An MCP client that registered itself (RFC 7591). `info` is the SDK's
    OAuthClientInformationFull as JSON, secret included: the SDK compares it
    in plain text, and PKCE is what actually protects the code exchange."""
    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    info: Mapped[dict] = mapped_column(Json)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OAuthRequest(Base):
    """An /authorize request waiting on the consent page. `user_id` and
    `nonce` are filled when the page is shown, so only that signed-in user's
    form submission can approve it."""
    __tablename__ = "oauth_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE"))
    params: Mapped[dict] = mapped_column(Json)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    nonce: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthCode(Base):
    __tablename__ = "oauth_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    params: Mapped[dict] = mapped_column(Json)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthGrant(Base):
    """One connected app for one user: the current access and refresh token,
    rotated in place on refresh. Deleting the row disconnects the app."""
    __tablename__ = "oauth_grants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), index=True)
    client_name: Mapped[str] = mapped_column(String(100))
    scopes: Mapped[str] = mapped_column(String(200), default="")
    resource: Mapped[str | None] = mapped_column(String(300), nullable=True)
    access_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()


class Template(Base):
    """A user's reusable piece of canvas (design §4): a JSON Canvas document
    whose coordinates start at (0, 0). kind: stencil (one node), fragment
    (several, dropped as a unit) or page (a whole starting canvas)."""
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))
    data: Mapped[dict] = mapped_column(Json)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserPrefs(Base):
    """Per-user settings that don't belong on the users row (which would need
    a migration to grow)."""
    __tablename__ = "user_prefs"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    default_page: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Attachment(Base):
    """A file uploaded into a workspace; the bytes live in the object store
    under `key`. A file node refers to it as "attachments/<id>/<name>"."""
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    uploader_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def key(self) -> str:
        return f"attachments/{self.workspace_id}/{self.id}"


class Folder(Base):
    """A user's folder for organising workspaces (design §11.2). Folders are
    personal: they nest (parent_id) and hold workspaces through
    workspace_folders, so a shared workspace can sit in a different folder for
    each person who sees it. Deleting a folder deletes its subfolders and puts
    their workspaces back at the top level; it never deletes a workspace."""
    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("folders.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkspaceFolder(Base):
    """Which of a user's folders a workspace is filed in; no row = top level."""
    __tablename__ = "workspace_folders"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    folder_id: Mapped[str] = mapped_column(
        ForeignKey("folders.id", ondelete="CASCADE"), index=True)


class ShareLink(Base):
    """A read-only, public link to one canvas (design §9): anyone holding the
    token can view it at /s/<token> without signing in. `all_tabs` also lets
    the viewer open the workspace's other tabs, so tab links keep working.
    The token is stored as is so its owner can copy the link again; it guards
    nothing that isn't in this same database. Revoking deletes the row."""
    __tablename__ = "share_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    canvas_id: Mapped[str] = mapped_column(
        ForeignKey("canvases.id", ondelete="CASCADE"), index=True)
    all_tabs: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

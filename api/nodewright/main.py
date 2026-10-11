"""HTTP app: auth routes, workspaces, canvases (tabs) and the built UI."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
from urllib.parse import quote, unquote, urlsplit
from datetime import datetime

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, RedirectResponse,
                               StreamingResponse)
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from mcp.server.auth.routes import create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from pydantic import AnyHttpUrl, BaseModel, ConfigDict
from starlette.routing import Route

from . import (__version__, access, attachments, auth, canvas_format, events, leases,
               mcp_server, oauth, oidc, render, storage, styleguide, templates, tokens)
from .config import Settings
from .db import Database
from .models import (AccessToken, Attachment, Canvas, CanvasRevision, OAuthGrant, StyleGuide, Template, User,
                     Workspace, utcnow)

log = logging.getLogger("nodewright")

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
REVISION_LIST_LIMIT = 100
CLIENT_HEADER = "x-nodewright-client"
SSE_PING_S = 20.0
SWEEP_FIRST, SWEEP_EVERY = 300.0, 6 * 3600.0  # attachment sweep: after start, then every
NEXT_COOKIE = "nw_next"


class NameIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CanvasCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    data: dict | None = None
    template: str | None = Field(default=None, max_length=64)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(pattern="^(stencil|fragment|page)$")
    data: dict


class DefaultPageIn(BaseModel):
    template: str = Field(min_length=1, max_length=64)


class StyleGuideIn(BaseModel):
    text: str = Field(max_length=styleguide.MAX_CHARS)


class CanvasPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    position: int | None = Field(default=None, ge=0, le=10_000)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ws_out(ws: Workspace) -> dict:
    return {"id": ws.id, "name": ws.name, "updated_at": _iso(ws.updated_at)}


def _canvas_meta(c: Canvas) -> dict:
    return {"id": c.id, "workspace_id": c.workspace_id, "name": c.name, "position": c.position,
            "revision": c.revision, "updated_at": _iso(c.updated_at)}


def _filename(name: str) -> str:
    return (re.sub(r"[^A-Za-z0-9 _.-]", "", name).strip() or "canvas") + ".canvas"


class _Issuer(BaseModel):
    # RFC 8414 clients compare the issuer exactly; keep it free of a trailing slash.
    model_config = ConfigDict(url_preserve_empty_path=True)
    u: AnyHttpUrl


def create_app(settings: Settings | None = None, provider: oidc.Provider | None = None,
               store: storage.Store | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = store or storage.from_settings(settings)
    broker = events.Broker()
    db = Database(settings.database_url, broker)
    db.create_schema()
    if provider is None and settings.oidc_enabled:
        provider = oidc.Provider(settings)
    if settings.dev_login and not settings.dev_login_enabled:
        log.warning("DEV_LOGIN ignored: PUBLIC_URL is https")

    tickets = render.Tickets()
    mcp, mcp_app = mcp_server.build(db, settings, store, tickets)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        sweeper = None
        if store is not None and settings.attachment_keep_days > 0:
            sweeper = asyncio.create_task(sweep_attachments_forever())
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            if sweeper:
                sweeper.cancel()

    def sweep_attachments() -> int:
        with db.session() as s:
            keys = attachments.sweep(s, utcnow(), settings.attachment_keep_days)
        drop_objects(keys)
        if keys:
            log.info("attachments: deleted %d unused", len(keys))
        return len(keys)

    async def sweep_attachments_forever():
        await asyncio.sleep(SWEEP_FIRST)
        while True:
            try:
                await asyncio.to_thread(sweep_attachments)
            except Exception:  # noqa: BLE001
                log.exception("attachments: sweep failed")
            await asyncio.sleep(SWEEP_EVERY)

    app = FastAPI(title="nodewright", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.settings, app.state.db, app.state.broker = settings, db, broker
    app.state.store, app.state.tickets = store, tickets
    app.state.sweep_attachments = sweep_attachments

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    def session():
        with db.session() as s:
            yield s

    def user_dep(request: Request, s: Session = Depends(session)) -> User:
        return auth.require_user(s, request, settings)

    def workspace_for(s: Session, user: User, ws_id: str,
                      action: str = access.READ) -> Workspace:
        try:
            return access.workspace(s, user, ws_id, action)
        except access.Denied as exc:
            raise access.http(exc) from None

    def canvas_for(s: Session, user: User, canvas_id: str, action: str = access.READ) -> Canvas:
        try:
            return access.canvas(s, user, canvas_id, action)
        except access.Denied as exc:
            raise access.http(exc) from None

    def ui_holder(request: Request, user: User) -> leases.Holder:
        client = re.sub(r"[^A-Za-z0-9_-]", "", request.headers.get(CLIENT_HEADER, ""))[:40]
        return leases.Holder("ui", user, client or "browser", user.username)

    def locked(exc: leases.Locked) -> JSONResponse:
        return JSONResponse(status_code=423, content={
            "detail": str(exc), "lease": leases.describe(exc.lease)})

    async def json_body(request: Request) -> dict:
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_canvas_bytes:
            raise HTTPException(413, "canvas is too large")
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > settings.max_canvas_bytes:
                raise HTTPException(413, "canvas is too large")
        try:
            return json.loads(raw)
        except ValueError:
            raise HTTPException(400, "body is not valid JSON") from None

    def checked(data) -> dict:
        try:
            return canvas_format.validate(data)
        except canvas_format.CanvasError as exc:
            raise HTTPException(422, f"not a valid JSON Canvas: {exc}") from None

    # --- meta and auth ------------------------------------------------------

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/api/config")
    def public_config():
        return {"oidc": provider is not None, "dev_login": settings.dev_login_enabled,
                "max_canvas_bytes": settings.max_canvas_bytes, "version": __version__,
                "attachments": store is not None,
                "max_attachment_bytes": settings.max_attachment_bytes}

    @app.get("/api/me")
    def me(user: User = Depends(user_dep)):
        return {"id": user.id, "username": user.username}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, s: Session = Depends(session)):
        if request.headers.get(auth.CSRF_HEADER) != "1":
            raise HTTPException(403, "missing X-Nodewright header")
        auth.end_session(s, request, settings, response)
        return {"ok": True}

    def safe_next(value: str) -> str:
        # Only the OAuth consent page needs a way back after sign-in.
        return value if value.startswith(oauth.CONSENT_PATH + "?") and len(value) < 300 else ""

    @app.get(oidc.FLOW_PATH + "/login")
    def oidc_login(next: str = ""):
        if provider is None:
            raise HTTPException(404, "sign-in is not set up on this server")
        try:
            url, flow = oidc.begin(provider, settings)
        except Exception as exc:  # noqa: BLE001
            log.warning("oidc: discovery failed: %s", exc)
            raise HTTPException(502, "cannot reach the sign-in server") from None
        res = RedirectResponse(url, status_code=302)
        res.set_cookie(oidc.FLOW_COOKIE, flow, max_age=oidc.FLOW_TTL_S, path=oidc.FLOW_PATH,
                       httponly=True, secure=settings.secure, samesite="lax")
        if safe_next(next):
            res.set_cookie(NEXT_COOKIE, next, max_age=oidc.FLOW_TTL_S, path=oidc.FLOW_PATH,
                           httponly=True, secure=settings.secure, samesite="lax")
        return res

    @app.get(oidc.FLOW_PATH + "/callback")
    def oidc_callback(request: Request, code: str = "", state: str = "", error: str = "",
                      s: Session = Depends(session)):
        if provider is None:
            raise HTTPException(404, "sign-in is not set up on this server")
        res = RedirectResponse(safe_next(request.cookies.get(NEXT_COOKIE, "")) or "/",
                               status_code=302)
        res.delete_cookie(oidc.FLOW_COOKIE, path=oidc.FLOW_PATH)
        res.delete_cookie(NEXT_COOKIE, path=oidc.FLOW_PATH)
        if error:
            return RedirectResponse("/?signin_error=" + re.sub(r"[^a-z_]", "", error)[:40], 302)
        try:
            claims = oidc.finish(provider, settings, request.cookies.get(oidc.FLOW_COOKIE, ""),
                                 code, state)
            user = oidc.resolve_user(s, claims)
            auth.start_session(s, user, settings, res)
        except oidc.SignInRefused:
            return RedirectResponse("/?signin_error=refused", 302)
        except Exception:  # noqa: BLE001
            log.exception("oidc: callback failed")
            return RedirectResponse("/?signin_error=failed", 302)
        return res

    if settings.dev_login_enabled:
        @app.post("/api/auth/dev-login")
        def dev_login(body: NameIn, request: Request, response: Response,
                      s: Session = Depends(session)):
            if request.headers.get(auth.CSRF_HEADER) != "1":
                raise HTTPException(403, "missing X-Nodewright header")
            name = auth.USERNAME_RE.sub("", body.name.lower())[:60] or "dev"
            user = s.scalar(select(User).where(User.username == name)) or auth.create_user(s, name)
            auth.start_session(s, user, settings, response)
            return {"id": user.id, "username": user.username}

    # --- workspaces ---------------------------------------------------------

    @app.get("/api/workspaces")
    def list_workspaces(user: User = Depends(user_dep), s: Session = Depends(session)):
        return [_ws_out(w) for w in access.visible_workspaces(s, user)]

    @app.post("/api/workspaces", status_code=201)
    def create_workspace(body: NameIn, user: User = Depends(user_dep),
                         s: Session = Depends(session)):
        ws = Workspace(owner_id=user.id, name=body.name.strip())
        s.add(ws)
        s.flush()
        s.add(Canvas(workspace_id=ws.id, name="Untitled", position=0, revision=1,
                     data=templates.page_data(s, user, None)))
        return _ws_out(ws)

    @app.patch("/api/workspaces/{ws_id}")
    def rename_workspace(ws_id: str, body: NameIn, user: User = Depends(user_dep),
                         s: Session = Depends(session)):
        ws = workspace_for(s, user, ws_id, access.MANAGE)
        ws.name, ws.updated_at = body.name.strip(), utcnow()
        return _ws_out(ws)

    @app.delete("/api/workspaces/{ws_id}", status_code=204)
    def delete_workspace(ws_id: str, tasks: BackgroundTasks, user: User = Depends(user_dep),
                         s: Session = Depends(session)):
        ws = workspace_for(s, user, ws_id, access.MANAGE)
        files = s.scalars(select(Attachment).where(Attachment.workspace_id == ws.id)).all()
        keys = [a.key for a in files]
        for a in files:
            s.delete(a)
        s.delete(ws)
        if store and keys:
            tasks.add_task(drop_objects, keys)
        return Response(status_code=204)

    # --- canvases (tabs) ----------------------------------------------------

    @app.get("/api/workspaces/{ws_id}/canvases")
    def list_canvases(ws_id: str, user: User = Depends(user_dep), s: Session = Depends(session)):
        return [_canvas_meta(c) for c in workspace_for(s, user, ws_id).canvases]

    @app.post("/api/workspaces/{ws_id}/canvases", status_code=201)
    def create_canvas(ws_id: str, body: CanvasCreate, user: User = Depends(user_dep),
                      s: Session = Depends(session)):
        ws = workspace_for(s, user, ws_id, access.CANVAS_CREATE)
        if body.data is not None:
            data = checked(body.data)
        else:
            try:
                data = templates.page_data(s, user, body.template)
            except templates.TemplateError as exc:
                raise HTTPException(404, str(exc)) from None
        if len(json.dumps(data)) > settings.max_canvas_bytes:
            raise HTTPException(413, "canvas is too large")
        last = s.scalar(select(func.max(Canvas.position)).where(Canvas.workspace_id == ws.id))
        c = Canvas(workspace_id=ws.id, name=body.name.strip(), revision=1, data=data,
                   position=(last + 1) if last is not None else 0)
        s.add(c)
        s.flush()
        s.add(CanvasRevision(canvas_id=c.id, revision=1, data=data, user_id=user.id,
                             source="import" if body.data is not None else "ui"))
        ws.updated_at = utcnow()
        return _canvas_meta(c)

    @app.get("/api/canvases/{canvas_id}")
    def get_canvas(canvas_id: str, user: User = Depends(user_dep), s: Session = Depends(session)):
        c = canvas_for(s, user, canvas_id)
        return {**_canvas_meta(c), "data": c.data,
                "lease": leases.describe(leases.active(s, c.id)),
                "can_edit": access.can(s, user, c.workspace, access.CANVAS_EDIT)}

    @app.put("/api/canvases/{canvas_id}")
    async def save_canvas(canvas_id: str, request: Request, user: User = Depends(user_dep),
                          s: Session = Depends(session)):
        body = await json_body(request)
        if not isinstance(body, dict) or not isinstance(body.get("base_revision"), int):
            raise HTTPException(400, "expected {base_revision, data}")
        data = checked(body.get("data"))
        c = canvas_for(s, user, canvas_id, access.CANVAS_EDIT)
        who = ui_holder(request, user)
        try:
            leases.take(s, c.id, who)
        except leases.Locked as exc:
            return locked(exc)
        base = body["base_revision"]
        # Compare-and-swap in one statement: of two concurrent saves from the same
        # base, exactly one matches the WHERE and the other gets the 409.
        now = utcnow()
        done = s.execute(update(Canvas)
                         .where(Canvas.id == c.id, Canvas.revision == base)
                         .values(revision=base + 1, data=data, updated_at=now)
                         .execution_options(synchronize_session=False)).rowcount
        if done != 1:
            s.refresh(c)
            return JSONResponse(status_code=409, content={
                "detail": "the canvas changed since you loaded it",
                "current": {**_canvas_meta(c), "data": c.data}})
        s.add(CanvasRevision(canvas_id=c.id, revision=base + 1, data=data, user_id=user.id,
                             source="ui"))
        c.workspace.updated_at = now
        events.queue(s, c.id, {"type": "revision", "revision": base + 1, "source": "ui",
                               "by": user.username, "client": who.key})
        return {"id": c.id, "revision": base + 1, "updated_at": _iso(now)}

    @app.patch("/api/canvases/{canvas_id}")
    def patch_canvas(canvas_id: str, body: CanvasPatch, user: User = Depends(user_dep),
                     s: Session = Depends(session)):
        c = canvas_for(s, user, canvas_id, access.CANVAS_EDIT)
        if body.name is not None:
            c.name = body.name.strip()
        if body.position is not None:
            tabs = [t for t in c.workspace.canvases if t.id != c.id]
            tabs.insert(min(body.position, len(tabs)), c)
            for i, t in enumerate(tabs):
                t.position = i
        return _canvas_meta(c)

    @app.delete("/api/canvases/{canvas_id}", status_code=204)
    def delete_canvas(canvas_id: str, user: User = Depends(user_dep),
                      s: Session = Depends(session)):
        s.delete(canvas_for(s, user, canvas_id, access.CANVAS_DELETE))
        return Response(status_code=204)

    @app.get("/api/canvases/{canvas_id}/revisions")
    def list_revisions(canvas_id: str, user: User = Depends(user_dep),
                       s: Session = Depends(session)):
        c = canvas_for(s, user, canvas_id)
        rows = s.execute(select(CanvasRevision.revision, CanvasRevision.source,
                                CanvasRevision.created_at)
                         .where(CanvasRevision.canvas_id == c.id)
                         .order_by(CanvasRevision.revision.desc()).limit(REVISION_LIST_LIMIT))
        return [{"revision": r, "source": src, "created_at": _iso(at)} for r, src, at in rows]

    @app.get("/api/canvases/{canvas_id}/export")
    def export_canvas(canvas_id: str, user: User = Depends(user_dep),
                      s: Session = Depends(session)):
        c = canvas_for(s, user, canvas_id)
        return Response(json.dumps(c.data, indent="\t"), media_type="application/json",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{_filename(c.name)}"'})

    # --- edit lease ----------------------------------------------------------

    @app.get("/api/canvases/{canvas_id}/lease")
    def get_lease(canvas_id: str, user: User = Depends(user_dep), s: Session = Depends(session)):
        c = canvas_for(s, user, canvas_id)
        return {"lease": leases.describe(leases.active(s, c.id))}

    @app.post("/api/canvases/{canvas_id}/lease")
    def take_lease(canvas_id: str, request: Request, force: bool = False,
                   user: User = Depends(user_dep), s: Session = Depends(session)):
        """Take (or with force=true, take over) the edit lease for this tab."""
        c = canvas_for(s, user, canvas_id, access.LEASE_BREAK if force else access.CANVAS_EDIT)
        try:
            row = leases.take(s, c.id, ui_holder(request, user), force=force)
        except leases.Locked as exc:
            return locked(exc)
        return {"lease": leases.describe(row)}

    @app.delete("/api/canvases/{canvas_id}/lease")
    def drop_lease(canvas_id: str, request: Request, user: User = Depends(user_dep),
                   s: Session = Depends(session)):
        c = canvas_for(s, user, canvas_id)
        return {"released": leases.release(s, c.id, ui_holder(request, user))}

    # --- live updates --------------------------------------------------------

    @app.get("/api/canvases/{canvas_id}/events")
    async def canvas_events(canvas_id: str, request: Request):
        with db.session() as s:
            user = auth.require_user(s, request, settings)
            c = canvas_for(s, user, canvas_id)
            lease = leases.describe(leases.active(s, c.id))
            revision = c.revision
        q = broker.subscribe(canvas_id)

        async def stream():
            try:
                hello = {"type": "hello", "revision": revision, "lease": lease}
                yield f"data: {json.dumps(hello)}\n\n"
                while True:
                    try:
                        ev = await asyncio.wait_for(q.get(), SSE_PING_S)
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            return
                        yield ": ping\n\n"
                        continue
                    yield f"data: {json.dumps(ev)}\n\n"
            finally:
                broker.unsubscribe(canvas_id, q)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store",
                                          "X-Accel-Buffering": "no"})

    # --- access tokens and style guide (cookie session only) -----------------

    @app.get("/api/tokens")
    def list_tokens(user: User = Depends(user_dep), s: Session = Depends(session)):
        rows = s.scalars(select(AccessToken).where(AccessToken.user_id == user.id)
                         .order_by(AccessToken.created_at))
        return [tokens.out(r) for r in rows]

    @app.post("/api/tokens", status_code=201)
    def create_token(body: NameIn, user: User = Depends(user_dep), s: Session = Depends(session)):
        if tokens.count(s, user) >= tokens.MAX_PER_USER:
            raise HTTPException(409, f"at most {tokens.MAX_PER_USER} tokens; revoke one first")
        row, raw = tokens.create(s, user, body.name)
        return {**tokens.out(row), "token": raw,
                "mcp_url": settings.public_url.rstrip("/") + "/mcp"}

    @app.delete("/api/tokens/{token_id}", status_code=204)
    def revoke_token(token_id: str, user: User = Depends(user_dep),
                     s: Session = Depends(session)):
        row = s.get(AccessToken, token_id)
        if row is None or row.user_id != user.id:
            raise HTTPException(404, "token not found")
        s.delete(row)
        return Response(status_code=204)

    @app.get("/api/style-guide")
    def get_style_guide(user: User = Depends(user_dep), s: Session = Depends(session)):
        text, default = styleguide.get(s, user)
        return {"text": text, "is_default": default}

    @app.put("/api/style-guide")
    def put_style_guide(body: StyleGuideIn, user: User = Depends(user_dep),
                        s: Session = Depends(session)):
        row = s.get(StyleGuide, user.id)
        if not body.text.strip():
            if row is not None:
                s.delete(row)
            return {"text": styleguide.DEFAULT, "is_default": True}
        if row is None:
            s.add(StyleGuide(user_id=user.id, text=body.text))
        else:
            row.text, row.updated_at = body.text, utcnow()
        return {"text": body.text, "is_default": False}

    # --- templates (templates.py) ------------------------------------------

    @app.get("/api/templates")
    def list_templates(user: User = Depends(user_dep), s: Session = Depends(session)):
        return {"templates": list(templates.BUILTIN.values())
                + [templates.out(t) for t in templates.mine(s, user)],
                "default_page": templates.default_page_id(s, user)}

    @app.post("/api/templates", status_code=201)
    def create_template(body: TemplateIn, user: User = Depends(user_dep),
                        s: Session = Depends(session)):
        try:
            return templates.out(templates.create(s, user, body.name, body.kind, body.data))
        except templates.TemplateError as exc:
            raise HTTPException(422, str(exc)) from None

    def own_template(s: Session, user: User, tid: str) -> Template:
        t = s.get(Template, tid)
        if t is None or t.owner_id != user.id:
            raise HTTPException(404, "template not found")
        return t

    @app.patch("/api/templates/{tid}")
    def rename_template(tid: str, body: NameIn, user: User = Depends(user_dep),
                        s: Session = Depends(session)):
        t = own_template(s, user, tid)
        t.name, t.updated_at = body.name.strip(), utcnow()
        return templates.out(t)

    @app.delete("/api/templates/{tid}", status_code=204)
    def delete_template(tid: str, user: User = Depends(user_dep), s: Session = Depends(session)):
        s.delete(own_template(s, user, tid))
        return Response(status_code=204)

    @app.put("/api/templates-default-page")
    def put_default_page(body: DefaultPageIn, user: User = Depends(user_dep),
                         s: Session = Depends(session)):
        try:
            templates.set_default_page(s, user, body.template)
        except templates.TemplateError as exc:
            raise HTTPException(422, str(exc)) from None
        return {"default_page": body.template}

    # --- attachments (attachments.py, storage.py) -----------------------------

    def drop_objects(keys: list[str]) -> None:
        for k in keys:
            try:
                store.delete(k)
            except Exception:  # noqa: BLE001
                log.warning("attachments: could not delete %s", k, exc_info=True)

    def need_store() -> storage.Store:
        if store is None:
            raise HTTPException(404, "attachments are not set up on this server")
        return store

    @app.get("/api/workspaces/{ws_id}/attachments")
    def list_attachments(ws_id: str, user: User = Depends(user_dep),
                         s: Session = Depends(session)):
        ws = workspace_for(s, user, ws_id)
        rows = s.scalars(select(Attachment).where(Attachment.workspace_id == ws.id)
                         .order_by(Attachment.created_at.desc())).all()
        return {"attachments": [attachments.out(a) for a in rows]}

    @app.post("/api/workspaces/{ws_id}/attachments", status_code=201)
    async def upload_attachment(ws_id: str, request: Request, user: User = Depends(user_dep),
                                s: Session = Depends(session)):
        st = need_store()
        ws = workspace_for(s, user, ws_id, access.CANVAS_EDIT)
        limit = settings.max_attachment_bytes
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            raise HTTPException(413, f"files are limited to {limit // (1024 * 1024)} MB")
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, f"files are limited to {limit // (1024 * 1024)} MB")
            chunks.append(chunk)
        data = b"".join(chunks)
        if not data:
            raise HTTPException(422, "the file is empty")
        a = Attachment(workspace_id=ws.id, uploader_id=user.id, size=len(data),
                       name=attachments.clean_name(unquote(request.headers.get("x-filename", ""))),
                       content_type=attachments.content_type(
                           data, request.headers.get("content-type")))
        s.add(a)
        s.flush()
        try:
            await asyncio.to_thread(st.put, a.key, data, a.content_type)
        except Exception:  # noqa: BLE001
            log.exception("attachments: upload to the store failed")
            raise HTTPException(502, "couldn't store the file; try again") from None
        return attachments.out(a)

    @app.get("/api/attachments/{att_id}")
    def get_attachment(att_id: str, user: User = Depends(user_dep),
                       s: Session = Depends(session)):
        a = s.get(Attachment, att_id)
        if a is None:
            raise HTTPException(404, "no such attachment")
        workspace_for(s, user, a.workspace_id)
        return serve_attachment(a)

    # --- render view (render.py): read-only, by ticket instead of cookie -------

    def ticket_for(canvas_id: str, t: str | None) -> render.Ticket:
        ticket = tickets.get(t)
        if ticket is None or ticket.canvas_id != canvas_id:
            raise HTTPException(404, "no such render")
        return ticket

    @app.get("/api/render/{canvas_id}")
    def render_canvas_data(canvas_id: str, t: str | None = None, s: Session = Depends(session)):
        ticket_for(canvas_id, t)
        c = s.get(Canvas, canvas_id)
        if c is None:
            raise HTTPException(404, "no such render")
        tabs = s.scalars(select(Canvas).where(Canvas.workspace_id == c.workspace_id)
                         .order_by(Canvas.position)).all()
        return {"id": c.id, "name": c.name, "data": c.data,
                "tabs": [_canvas_meta(x) for x in tabs]}

    @app.get("/api/render/{canvas_id}/attachments/{att_id}")
    def render_attachment(canvas_id: str, att_id: str, t: str | None = None,
                          s: Session = Depends(session)):
        ticket = ticket_for(canvas_id, t)
        a = s.get(Attachment, att_id)
        if a is None or a.workspace_id != ticket.workspace_id:
            raise HTTPException(404, "no such attachment")
        return serve_attachment(a)

    def serve_attachment(a: Attachment) -> StreamingResponse:
        st = need_store()
        try:
            body = st.get(a.key)
        except KeyError:
            raise HTTPException(404, "the file is missing from storage") from None
        inline = a.content_type in attachments.INLINE
        disposition = ("inline" if inline else "attachment") + "; filename*=UTF-8''" + quote(a.name)
        return StreamingResponse(body, media_type=a.content_type if inline else
                                 "application/octet-stream", headers={
            "Content-Disposition": disposition, "Content-Length": str(a.size),
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, max-age=31536000, immutable"})

    @app.delete("/api/attachments/{att_id}", status_code=204)
    def delete_attachment(att_id: str, tasks: BackgroundTasks, user: User = Depends(user_dep),
                          s: Session = Depends(session)):
        need_store()
        a = s.get(Attachment, att_id)
        if a is None:
            raise HTTPException(404, "no such attachment")
        workspace_for(s, user, a.workspace_id, access.CANVAS_EDIT)
        tasks.add_task(drop_objects, [a.key])
        s.delete(a)
        return Response(status_code=204)

    # --- OAuth for MCP clients (oauth.py) ------------------------------------

    @app.get("/api/oauth/grants")
    def list_grants(user: User = Depends(user_dep), s: Session = Depends(session)):
        rows = s.scalars(select(OAuthGrant).where(OAuthGrant.user_id == user.id)
                         .order_by(OAuthGrant.created_at.desc()))
        return {"grants": [oauth.grant_out(g) for g in rows]}

    @app.delete("/api/oauth/grants/{grant_id}", status_code=204)
    def revoke_grant(grant_id: str, user: User = Depends(user_dep),
                     s: Session = Depends(session)):
        g = s.get(OAuthGrant, grant_id)
        if g is None or g.user_id != user.id:
            raise HTTPException(404, "not found")
        s.delete(g)

    def consent_page(body: str, status: int = 200, redirect_to: str | None = None) -> HTMLResponse:
        csp = CSP
        if redirect_to:
            csp = CSP.replace("form-action 'self'",
                              f"form-action 'self' {oauth.form_action_source(redirect_to)}")
        return HTMLResponse(body, status_code=status, headers={
            "Content-Security-Policy": csp, "Cache-Control": "no-store",
            "X-Frame-Options": "DENY"})

    @app.get(oauth.CONSENT_PATH)
    def consent(request: Request, req: str = "", s: Session = Depends(session)):
        try:
            row, info = oauth.pending(s, req)
        except oauth.ConsentError as exc:
            return consent_page(oauth.error_html(str(exc)), 400)
        user = auth.user_for_request(s, request, settings)
        if user is None:
            if provider is None:
                return consent_page(oauth.error_html(
                    "Sign in to nodewright in this browser first, then reload this page."), 401)
            back = f"{oauth.CONSENT_PATH}?req={req}"
            return RedirectResponse(f"{oidc.FLOW_PATH}/login?next={quote(back, safe='')}", 302)
        try:
            nonce = oauth.show(s, row, user)
        except oauth.ConsentError as exc:
            return consent_page(oauth.error_html(str(exc)), 403)
        return consent_page(oauth.consent_html(info, row.params, user, req, nonce),
                            redirect_to=row.params["redirect_uri"])

    @app.post(oauth.CONSENT_PATH)
    async def consent_decide(request: Request):
        form = await request.form()
        req, nonce = str(form.get("req") or ""), str(form.get("nonce") or "")
        approve = form.get("decision") == "allow"
        with db.session() as s:
            user = auth.user_for_request(s, request, settings)
            try:
                row, _ = oauth.pending(s, req)
                if user is None:
                    raise oauth.ConsentError("You are no longer signed in. Start again.")
                url = oauth.decide(s, row, user, nonce, approve)
            except oauth.ConsentError as exc:
                return consent_page(oauth.error_html(str(exc)), 400)
        return RedirectResponse(url, status_code=303)

    # RFC 8414 wants an https issuer; plain http is only allowed on loopback.
    if settings.secure or urlsplit(settings.public_url).hostname in ("localhost", "127.0.0.1"):
        issuer = _Issuer(u=settings.public_url).u
        app.router.routes.extend(create_auth_routes(
            oauth.Provider(db, settings.public_url), issuer_url=issuer,
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=[oauth.SCOPE], default_scopes=[oauth.SCOPE]),
            revocation_options=RevocationOptions(enabled=True)))
        resource_routes = create_protected_resource_routes(
            resource_url=AnyHttpUrl(settings.public_url + "/mcp"), authorization_servers=[issuer],
            scopes_supported=[oauth.SCOPE], resource_name="nodewright")
        app.router.routes.extend(resource_routes)
        # Some clients look for the metadata without the resource path.
        app.router.routes.append(Route("/.well-known/oauth-protected-resource",
                                       endpoint=resource_routes[0].endpoint, methods=["GET", "OPTIONS"]))
    else:
        log.warning("MCP OAuth disabled: PUBLIC_URL is neither https nor localhost")

    # MCP endpoint (bearer tokens, not cookies); must come before the catch-alls.
    app.router.routes.append(Route("/mcp", endpoint=mcp_app, methods=["GET", "POST", "DELETE"]))

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_not_found(rest: str):
        raise HTTPException(404, "not found")

    # --- the built UI -------------------------------------------------------

    static = settings.static_dir
    if static and os.path.isdir(static):
        root = os.path.realpath(static)

        @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        def ui(path: str):
            target = os.path.realpath(os.path.join(root, path))
            if path and target.startswith(root + os.sep) and os.path.isfile(target):
                cache = ("public, max-age=31536000, immutable" if path.startswith("assets/")
                         else "no-cache")
                return FileResponse(target, headers={"Cache-Control": cache})
            # Client-side routes fall back to the app shell.
            return FileResponse(os.path.join(root, "index.html"),
                                headers={"Cache-Control": "no-cache"})

    return app

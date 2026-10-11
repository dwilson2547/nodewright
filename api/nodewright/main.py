"""HTTP app: auth routes, workspaces, canvases (tabs) and the built UI."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import __version__, auth, canvas_format, oidc
from .config import Settings
from .db import Database
from .models import Canvas, CanvasRevision, User, Workspace, utcnow

log = logging.getLogger("nodewright")

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
REVISION_LIST_LIMIT = 100


class NameIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CanvasCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    data: dict | None = None


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


def create_app(settings: Settings | None = None, provider: oidc.Provider | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.database_url)
    db.create_schema()
    if provider is None and settings.oidc_enabled:
        provider = oidc.Provider(settings)
    if settings.dev_login and not settings.dev_login_enabled:
        log.warning("DEV_LOGIN ignored: PUBLIC_URL is https")

    app = FastAPI(title="nodewright", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.settings, app.state.db = settings, db

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

    def own_workspace(s: Session, user: User, ws_id: str) -> Workspace:
        ws = s.get(Workspace, ws_id)
        # Someone else's id answers exactly like a missing one.
        if ws is None or ws.owner_id != user.id:
            raise HTTPException(404, "workspace not found")
        return ws

    def own_canvas(s: Session, user: User, canvas_id: str) -> Canvas:
        c = s.get(Canvas, canvas_id)
        if c is None or c.workspace.owner_id != user.id:
            raise HTTPException(404, "canvas not found")
        return c

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
                "max_canvas_bytes": settings.max_canvas_bytes, "version": __version__}

    @app.get("/api/me")
    def me(user: User = Depends(user_dep)):
        return {"id": user.id, "username": user.username}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, s: Session = Depends(session)):
        if request.headers.get(auth.CSRF_HEADER) != "1":
            raise HTTPException(403, "missing X-Nodewright header")
        auth.end_session(s, request, settings, response)
        return {"ok": True}

    @app.get(oidc.FLOW_PATH + "/login")
    def oidc_login():
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
        return res

    @app.get(oidc.FLOW_PATH + "/callback")
    def oidc_callback(request: Request, code: str = "", state: str = "", error: str = "",
                      s: Session = Depends(session)):
        if provider is None:
            raise HTTPException(404, "sign-in is not set up on this server")
        res = RedirectResponse("/", status_code=302)
        res.delete_cookie(oidc.FLOW_COOKIE, path=oidc.FLOW_PATH)
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
        rows = s.scalars(select(Workspace).where(Workspace.owner_id == user.id)
                         .order_by(Workspace.created_at))
        return [_ws_out(w) for w in rows]

    @app.post("/api/workspaces", status_code=201)
    def create_workspace(body: NameIn, user: User = Depends(user_dep),
                         s: Session = Depends(session)):
        ws = Workspace(owner_id=user.id, name=body.name.strip())
        s.add(ws)
        s.flush()
        s.add(Canvas(workspace_id=ws.id, name="Untitled", position=0, revision=1,
                     data=canvas_format.empty()))
        return _ws_out(ws)

    @app.patch("/api/workspaces/{ws_id}")
    def rename_workspace(ws_id: str, body: NameIn, user: User = Depends(user_dep),
                         s: Session = Depends(session)):
        ws = own_workspace(s, user, ws_id)
        ws.name, ws.updated_at = body.name.strip(), utcnow()
        return _ws_out(ws)

    @app.delete("/api/workspaces/{ws_id}", status_code=204)
    def delete_workspace(ws_id: str, user: User = Depends(user_dep),
                         s: Session = Depends(session)):
        s.delete(own_workspace(s, user, ws_id))
        return Response(status_code=204)

    # --- canvases (tabs) ----------------------------------------------------

    @app.get("/api/workspaces/{ws_id}/canvases")
    def list_canvases(ws_id: str, user: User = Depends(user_dep), s: Session = Depends(session)):
        return [_canvas_meta(c) for c in own_workspace(s, user, ws_id).canvases]

    @app.post("/api/workspaces/{ws_id}/canvases", status_code=201)
    def create_canvas(ws_id: str, body: CanvasCreate, user: User = Depends(user_dep),
                      s: Session = Depends(session)):
        ws = own_workspace(s, user, ws_id)
        data = checked(body.data) if body.data is not None else canvas_format.empty()
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
        c = own_canvas(s, user, canvas_id)
        return {**_canvas_meta(c), "data": c.data}

    @app.put("/api/canvases/{canvas_id}")
    async def save_canvas(canvas_id: str, request: Request, user: User = Depends(user_dep),
                          s: Session = Depends(session)):
        body = await json_body(request)
        if not isinstance(body, dict) or not isinstance(body.get("base_revision"), int):
            raise HTTPException(400, "expected {base_revision, data}")
        data = checked(body.get("data"))
        c = own_canvas(s, user, canvas_id)
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
        return {"id": c.id, "revision": base + 1, "updated_at": _iso(now)}

    @app.patch("/api/canvases/{canvas_id}")
    def patch_canvas(canvas_id: str, body: CanvasPatch, user: User = Depends(user_dep),
                     s: Session = Depends(session)):
        c = own_canvas(s, user, canvas_id)
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
        s.delete(own_canvas(s, user, canvas_id))
        return Response(status_code=204)

    @app.get("/api/canvases/{canvas_id}/revisions")
    def list_revisions(canvas_id: str, user: User = Depends(user_dep),
                       s: Session = Depends(session)):
        c = own_canvas(s, user, canvas_id)
        rows = s.execute(select(CanvasRevision.revision, CanvasRevision.source,
                                CanvasRevision.created_at)
                         .where(CanvasRevision.canvas_id == c.id)
                         .order_by(CanvasRevision.revision.desc()).limit(REVISION_LIST_LIMIT))
        return [{"revision": r, "source": src, "created_at": _iso(at)} for r, src, at in rows]

    @app.get("/api/canvases/{canvas_id}/export")
    def export_canvas(canvas_id: str, user: User = Depends(user_dep),
                      s: Session = Depends(session)):
        c = own_canvas(s, user, canvas_id)
        return Response(json.dumps(c.data, indent="\t"), media_type="application/json",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{_filename(c.name)}"'})

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_not_found(rest: str):
        raise HTTPException(404, "not found")

    # --- the built UI -------------------------------------------------------

    static = settings.static_dir
    if static and os.path.isdir(static):
        root = os.path.realpath(static)

        @app.get("/{path:path}", include_in_schema=False)
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

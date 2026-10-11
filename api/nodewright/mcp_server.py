"""The MCP server: what an agent sees (design §7).

Streamable HTTP at /mcp, stateless, JSON responses. Every request carries a
personal access token as `Authorization: Bearer nwp_...`; McpAuth rejects
anything else before the SDK sees it, and each tool resolves the token again
to find whose canvases it may touch.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any, Callable, Literal

from pydantic import Field
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp
from mcp.server.transport_security import TransportSecuritySettings

from . import __version__, access, canvas_format, leases, ops, styleguide, tokens
from .config import Settings
from .db import Database
from .models import Canvas, User, Workspace

INSTRUCTIONS = """\
nodewright is a diagram editor; its documents are JSON Canvas files ("canvases"),
grouped as tabs in workspaces. You are acting for the signed-in user who made your token.

- Call get_style_guide before drawing anything: it says how this user likes diagrams.
- Prefer omitting x/y/width/height: add_elements places and sizes nodes for you, next
  to whatever they connect to. Give nodes your own ids so edges in the same call can
  refer to them. Use `group` to put nodes inside a group node.
- Edits are operations applied to the latest revision, so you never overwrite the
  user's concurrent work. Every write is a revision the user can see.
- Writing takes a short lock on the canvas so you and the user don't fight. If a
  canvas is locked by someone else, wait or ask the user; don't retry in a loop.
  For a long series of edits call lock_canvas first and unlock_canvas when done.
- The user sees your changes live in their browser.
"""

Direction = Literal["TB", "LR"]


class McpAuth:
    """Bearer-token gate in front of the SDK's ASGI app."""

    def __init__(self, inner: ASGIApp, db: Database, public_url: str):
        self.inner, self.db, self.public_url = inner, db, public_url.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            raw = tokens.bearer(dict(scope["headers"]).get(b"authorization", b"").decode("latin-1"))
            ok = False
            if raw:
                with self.db.session() as s:
                    ok = tokens.verify(s, raw) is not None
            if not ok:
                res = JSONResponse(
                    {"error": "invalid_token",
                     "error_description": "send Authorization: Bearer <token>; create a token "
                                          f"in nodewright settings at {self.public_url}"},
                    status_code=401, headers={"WWW-Authenticate": 'Bearer realm="nodewright"'})
                await res(scope, receive, send)
                return
        await self.inner(scope, receive, send)


def build(db: Database, settings: Settings) -> tuple[MCPServer, ASGIApp]:
    server = MCPServer(name="nodewright", version=__version__, instructions=INSTRUCTIONS,
                       website_url=settings.public_url)

    def run(ctx: Context, fn: Callable[[Session, User, leases.Holder], Any]) -> Any:
        raw = tokens.bearer((ctx.headers or {}).get("authorization"))
        with db.session() as s:
            tok = tokens.verify(s, raw) if raw else None
            if tok is None:
                raise ToolError("not signed in: the access token is missing or revoked")
            user = tok.user
            who = leases.Holder("agent", user, tok.id, f"{user.username}'s agent ({tok.name})")
            try:
                return fn(s, user, who)
            except access.Denied as exc:
                raise ToolError(str(exc)) from None
            except leases.Locked as exc:
                raise ToolError(f"canvas is locked: {exc}. Wait for it to free up or ask the "
                                "user; they can also take over from the browser.") from None
            except (ops.OpError, canvas_format.CanvasError) as exc:
                raise ToolError(str(exc)) from None

    def write(ctx: Context, canvas_id: str, op) -> dict:
        def go(s, user, who):
            c, result = ops.mutate(s, user, canvas_id, who, op, settings.max_canvas_bytes)
            return {**result, "revision": c.revision}
        return run(ctx, go)

    @server.tool()
    def list_workspaces(ctx: Context) -> list[dict]:
        """Workspaces you can see, each with its canvases (tabs): ids, names,
        revisions and node/edge counts."""
        def go(s, user, who):
            return [{"id": ws.id, "name": ws.name,
                     "canvases": [ops.summary(c) for c in ws.canvases]}
                    for ws in access.visible_workspaces(s, user)]
        return run(ctx, go)

    @server.tool()
    def create_workspace(ctx: Context, name: Annotated[str, Field(min_length=1, max_length=200)]
                         ) -> dict:
        """Create a workspace with one empty canvas."""
        def go(s, user, who):
            ws = Workspace(owner_id=user.id, name=name.strip())
            s.add(ws)
            s.flush()
            c = Canvas(workspace_id=ws.id, name="Untitled", position=0, revision=1,
                       data=canvas_format.empty())
            s.add(c)
            s.flush()
            return {"workspace_id": ws.id, "canvas_id": c.id}
        return run(ctx, go)

    @server.tool()
    def create_canvas(ctx: Context, workspace_id: str,
                      name: Annotated[str, Field(min_length=1, max_length=200)]) -> dict:
        """Add an empty canvas (a new tab) to a workspace."""
        def go(s, user, who):
            from sqlalchemy import func, select
            ws = access.workspace(s, user, workspace_id, access.CANVAS_CREATE)
            last = s.scalar(select(func.max(Canvas.position))
                            .where(Canvas.workspace_id == ws.id))
            c = Canvas(workspace_id=ws.id, name=name.strip(), revision=1,
                       data=canvas_format.empty(), position=(last + 1) if last is not None else 0)
            s.add(c)
            s.flush()
            return {"canvas_id": c.id, "url": f"{settings.public_url}/?canvas={c.id}"}
        return run(ctx, go)

    @server.tool()
    def get_canvas(ctx: Context, canvas_id: str) -> dict:
        """The canvas document (JSON Canvas 1.0: nodes and edges), its revision,
        and who holds the edit lock, if anyone."""
        def go(s, user, who):
            c = access.canvas(s, user, canvas_id)
            return {"id": c.id, "name": c.name, "workspace_id": c.workspace_id,
                    "revision": c.revision, "lock": leases.describe(leases.active(s, c.id)),
                    "data": c.data}
        return run(ctx, go)

    @server.tool()
    def add_elements(ctx: Context, canvas_id: str,
                     nodes: Annotated[list[dict], Field(
                         description="Nodes to add. type: text (default; `text` is Markdown), "
                                     "link (`url`), file (`file`) or group (`label`). Optional: "
                                     "id, color ('1'-'6' or '#rrggbb'), group (id of a group "
                                     "node to put it in), x/y/width/height (omit to auto-place "
                                     "and auto-size).")] = [],  # noqa: B006
                     edges: Annotated[list[dict], Field(
                         description="Edges to add: fromNode, toNode (ids, existing or from "
                                     "`nodes`). Optional: id, label, color, fromEnd/toEnd "
                                     "('none'|'arrow', default toEnd arrow), fromSide/toSide "
                                     "(top|right|bottom|left; omit to let the editor choose).")
                     ] = [],  # noqa: B006
                     direction: Direction = "TB") -> dict:
        """Add nodes and edges. Unpositioned nodes are laid out as a block in
        `direction`, beside the existing nodes they connect to (or beside the
        drawing if they connect to nothing). Returns the new ids."""
        if not nodes and not edges:
            raise ToolError("nothing to add")
        return write(ctx, canvas_id, ops.add_elements(nodes, edges, direction))

    @server.tool()
    def update_elements(ctx: Context, canvas_id: str,
                        updates: Annotated[list[dict], Field(
                            description="[{id, set: {key: value, other_key: null}, fit?: bool}] "
                                        "— null removes a key; fit:true resizes a node to its "
                                        "text. id and type can't change.")]) -> dict:
        """Change existing nodes or edges: text, colour, label, geometry, ends, sides."""
        return write(ctx, canvas_id, ops.update_elements(updates))

    @server.tool()
    def delete_elements(ctx: Context, canvas_id: str, ids: list[str]) -> dict:
        """Delete nodes and edges by id. Edges attached to a deleted node are removed;
        a deleted group's contents stay."""
        return write(ctx, canvas_id, ops.delete_elements(ids))

    @server.tool()
    def layout(ctx: Context, canvas_id: str, node_ids: list[str] | None = None,
               direction: Direction = "TB") -> dict:
        """Tidy nodes into a layered layout following the edges (all nodes by
        default). Groups move with their contents and are refitted."""
        return write(ctx, canvas_id, ops.relayout(node_ids, direction))

    @server.tool()
    def lock_canvas(ctx: Context, canvas_id: str,
                    minutes: Annotated[int, Field(ge=1, le=15)] = 5) -> dict:
        """Hold the edit lock for a series of edits (each write also renews it for
        2 minutes). The user can still take over from the browser."""
        def go(s, user, who):
            access.canvas(s, user, canvas_id, access.CANVAS_EDIT)
            row = leases.take(s, canvas_id, who, timedelta(minutes=minutes))
            return {"lock": leases.describe(row)}
        return run(ctx, go)

    @server.tool()
    def unlock_canvas(ctx: Context, canvas_id: str) -> dict:
        """Release your edit lock when you're done."""
        def go(s, user, who):
            access.canvas(s, user, canvas_id)
            return {"released": leases.release(s, canvas_id, who)}
        return run(ctx, go)

    @server.tool()
    def get_style_guide(ctx: Context) -> dict:
        """How this user likes their diagrams. Read it before drawing."""
        def go(s, user, who):
            text, default = styleguide.get(s, user)
            return {"style_guide": text, "is_default": default}
        return run(ctx, go)

    host = settings.public_url.split("://", 1)[-1].split("/", 1)[0]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[host, "localhost", "localhost:*", "127.0.0.1:*", "testserver"],
        allowed_origins=[settings.public_url.rstrip("/"), "http://localhost:*",
                         "http://127.0.0.1:*"])
    server.streamable_http_app(streamable_http_path="/mcp", json_response=True,
                               stateless_http=True, transport_security=security)
    return server, McpAuth(StreamableHTTPASGIApp(server.session_manager), db,
                           settings.public_url)

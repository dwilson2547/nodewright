"""The MCP server: what an agent sees (design §7).

Streamable HTTP at /mcp, stateless, JSON responses. Every request carries a
bearer token, either a personal access token or one issued through OAuth
(oauth.py). McpAuth rejects anything else before the SDK sees it, and each
tool resolves the token again to find whose canvases it may touch.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any, Callable, Literal

from pydantic import Field
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.mcpserver import Context, Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp
from mcp.server.transport_security import TransportSecuritySettings

from . import (__version__, access, attachments, canvas_format, folders, icons, leases, ops, render, storage,
               styleguide, styles, templates, tokens, versions)
from .config import Settings
from .db import Database
from .models import Attachment, Canvas, User, Workspace

INSTRUCTIONS = """\
nodewright is a diagram editor; its documents are JSON Canvas files ("canvases"),
grouped as tabs in workspaces. You are acting for the signed-in user who connected you.

- Call get_style_guide before drawing anything: it says how this user likes diagrams.
- Prefer omitting x/y/width/height: add_elements places and sizes nodes for you, next
  to whatever they connect to. Give nodes your own ids so edges in the same call can
  refer to them. Use `group` to put nodes inside a group node.
- Edits are operations applied to the latest revision, so you never overwrite the
  user's concurrent work. Every write is a revision the user can see. Before a large
  restructure, save_version names the current state so the user can restore it.
- Writing takes a short lock on the canvas so you and the user don't fight. If a
  canvas is locked by someone else, wait or ask the user; don't retry in a loop.
  For a long series of edits call lock_canvas first and unlock_canvas when done.
- Shapes and line styles are `styleAttributes` on nodes and edges (add_elements lists the
  values): e.g. a decision is a text node with {"shape": "diamond", "textAlign": "center"},
  an optional dependency an edge with {"path": "short-dashed"}.
- list_templates shows ready-made stencils, fragments and pages (the user's own and
  built-ins); apply_template drops one onto a canvas. Prefer the user's templates when they
  fit. save_template keeps part of a canvas for reuse.
- To link one tab to another (e.g. an overview whose boxes open detail diagrams), add a
  file node with {"file": "<tab name>.canvas"} and optionally {"subpath": "#<node id>"}
  to land on a node; the user clicks it to open that tab. Tab names come from
  list_workspaces; links follow the name, so rename the link if you rename the tab.
- Files the user uploaded (screenshots, logos, PDFs) are listed by list_attachments; show
  one with a file node whose `file` is the attachment's `file` value. Images render inline.
- The user sees your changes live in their browser. If render_canvas is available, use it
  to look at your result and fix what reads wrong before you finish.
"""

NODE_STYLE = ("styleAttributes (optional object; omit a key for the default): "
              + styles.describe(styles.NODE) + ". shape and textAlign apply to text nodes.")
EDGE_STYLE = ("styleAttributes (optional object; omit a key for the default, a solid curved "
              "2px line with a filled triangle): " + styles.describe(styles.EDGE)
              + ". path is the dash pattern, pathfindingMethod the routing (default curves, "
              "switching to a rounded detour if the curve would cross a node; direct = straight, "
              "always; square = sharp right angles around nodes; a-star = rounded right angles "
              "around nodes), cornerRadius the rounding in px of every bend on a right-angle "
              "route or detour (default: square 0, otherwise 12; no effect on direct or plain "
              "curves), arrow the arrowhead shape on whichever ends have one.")

Direction = Literal["TB", "LR"]
SCHEME = "Bearer"
RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"


class McpAuth:
    """Bearer-token gate in front of the SDK's ASGI app. A 401 points the
    client at the protected-resource metadata (RFC 9728), which is how an
    OAuth-capable client discovers it can sign the user in from a browser."""

    def __init__(self, inner: ASGIApp, db: Database, public_url: str):
        self.inner, self.db, self.public_url = inner, db, public_url.rstrip("/")
        self.metadata_url = self.public_url + RESOURCE_METADATA_PATH

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            raw = tokens.bearer(dict(scope["headers"]).get(b"authorization", b"").decode("latin-1"))
            ok = False
            if raw:
                with self.db.session() as s:
                    ok = tokens.principal(s, raw) is not None
            if not ok:
                challenge = (f'{SCHEME} error="invalid_token", '
                             f'resource_metadata="{self.metadata_url}"')
                res = JSONResponse(
                    {"error": "invalid_token",
                     "error_description": "sign in through your MCP client, or send an access "
                                          f"token created under Agents at {self.public_url}"},
                    status_code=401, headers={"WWW-Authenticate": challenge})
                await res(scope, receive, send)
                return
        await self.inner(scope, receive, send)


def build(db: Database, settings: Settings, store: storage.Store | None = None,
          tickets: render.Tickets | None = None) -> tuple[MCPServer, ASGIApp]:
    server = MCPServer(name="nodewright", version=__version__, instructions=INSTRUCTIONS,
                       website_url=settings.public_url)

    def run(ctx: Context, fn: Callable[[Session, User, leases.Holder], Any]) -> Any:
        raw = tokens.bearer((ctx.headers or {}).get("authorization"))
        with db.session() as s:
            who_is = tokens.principal(s, raw)
            if who_is is None:
                raise ToolError("not signed in: the token is missing, expired or revoked")
            user = who_is.user
            who = leases.Holder("agent", user, who_is.client, who_is.label)
            try:
                return fn(s, user, who)
            except access.Denied as exc:
                raise ToolError(str(exc)) from None
            except leases.Locked as exc:
                raise ToolError(f"canvas is locked: {exc}. Wait for it to free up, or ask "
                                "the user.") from None
            except (ops.OpError, canvas_format.CanvasError, folders.FolderError,
                    versions.VersionError) as exc:
                raise ToolError(str(exc)) from None

    def write(ctx: Context, canvas_id: str, op=None, *, make=None) -> dict:
        """Apply an ops function, or the one `make(session)` returns."""
        def go(s, user, who):
            fn = make(s) if make is not None else op
            c, result = ops.mutate(s, user, canvas_id, who, fn, settings.max_canvas_bytes)
            return {**result, "revision": c.revision}
        return run(ctx, go)

    @server.tool()
    def list_workspaces(ctx: Context) -> dict:
        """Workspaces you can see, each with its canvases (tabs): ids, names,
        revisions and node/edge counts, and your role (owner, editor, viewer);
        plus the user's folders (folder_id null = top level)."""
        def go(s, user, who):
            filed = folders.placements(s, user)
            return {"folders": [folders.out(f) for f in folders.all_for(s, user)],
                    "workspaces": [{"id": ws.id, "name": ws.name, "folder_id": filed.get(ws.id),
                                    "role": access.role_on(s, user, ws),
                                    "canvases": [ops.summary(c) for c in ws.canvases]}
                                   for ws in access.visible_workspaces(s, user)]}
        return run(ctx, go)

    @server.tool()
    def create_folder(ctx: Context, name: Annotated[str, Field(min_length=1, max_length=200)],
                      parent_id: str | None = None) -> dict:
        """Create a folder for organising workspaces, optionally inside another."""
        return run(ctx, lambda s, user, who: folders.out(folders.create(s, user, name, parent_id)))

    @server.tool()
    def file_workspace(ctx: Context, workspace_id: str, folder_id: str | None) -> dict:
        """Move a workspace into one of the user's folders (null = top level)."""
        def go(s, user, who):
            folders.file(s, user, workspace_id, folder_id)
            return {"workspace_id": workspace_id, "folder_id": folder_id}
        return run(ctx, go)

    @server.tool()
    def create_workspace(ctx: Context, name: Annotated[str, Field(min_length=1, max_length=200)],
                         folder_id: str | None = None) -> dict:
        """Create a workspace with one empty canvas, optionally in a folder."""
        def go(s, user, who):
            if folder_id:
                folders.get(s, user, folder_id)
            ws = Workspace(owner_id=user.id, name=name.strip())
            s.add(ws)
            s.flush()
            if folder_id:
                folders.file(s, user, ws.id, folder_id)
            c = Canvas(workspace_id=ws.id, name="Untitled", position=0, revision=1,
                       data=templates.page_data(s, user, None))
            s.add(c)
            s.flush()
            return {"workspace_id": ws.id, "canvas_id": c.id}
        return run(ctx, go)

    @server.tool()
    def create_canvas(ctx: Context, workspace_id: str,
                      name: Annotated[str, Field(min_length=1, max_length=200)],
                      template: Annotated[str | None, Field(
                          description="Page template id to start from (list_templates). "
                                      "Omit for the user's default page.")] = None) -> dict:
        """Add a canvas (a new tab) to a workspace, starting from a page template."""
        def go(s, user, who):
            from sqlalchemy import func, select
            ws = access.workspace(s, user, workspace_id, access.CANVAS_CREATE)
            try:
                data = templates.page_data(s, user, template)
            except templates.TemplateError as exc:
                raise ToolError(str(exc)) from None
            last = s.scalar(select(func.max(Canvas.position))
                            .where(Canvas.workspace_id == ws.id))
            c = Canvas(workspace_id=ws.id, name=name.strip(), revision=1,
                       data=data, position=(last + 1) if last is not None else 0)
            s.add(c)
            s.flush()
            return {"canvas_id": c.id, "url": f"{settings.public_url}/?canvas={c.id}"}
        return run(ctx, go)

    @server.tool()
    def get_canvas(ctx: Context, canvas_id: str, revision: Annotated[int | None, Field(
            description="An earlier revision to read instead of the current document "
                        "(see list_versions)")] = None) -> dict:
        """The canvas document (JSON Canvas 1.0: nodes and edges), its revision,
        and who holds the edit lock, if anyone."""
        def go(s, user, who):
            c = access.canvas(s, user, canvas_id)
            out = {"id": c.id, "name": c.name, "workspace_id": c.workspace_id,
                   "revision": c.revision, "lock": leases.describe(leases.active(s, c.id)),
                   "data": c.data}
            if revision is not None and revision != c.revision:
                old = versions.get(s, c, revision)
                out |= {"revision": revision, "current_revision": c.revision, "data": old["data"]}
            return out
        return run(ctx, go)

    @server.tool()
    def list_versions(ctx: Context, canvas_id: str, named_only: bool = False,
                      before: int | None = None) -> dict:
        """The tab's history, newest first, 100 at a time (pass the last revision
        seen as `before` for more): who changed it, when, from where (ui, mcp,
        import, restore), and the name of each named version."""
        def go(s, user, who):
            return versions.listing(s, access.canvas(s, user, canvas_id), before, named_only)
        return run(ctx, go)

    @server.tool()
    def save_version(ctx: Context, canvas_id: str,
                     name: Annotated[str, Field(min_length=1, max_length=200)],
                     revision: int | None = None) -> dict:
        """Name the current revision (or `revision`) as a version the user can find
        and restore from the History panel, e.g. before a large restructure.
        Doesn't change the document."""
        def go(s, user, who):
            c = access.canvas(s, user, canvas_id, access.CANVAS_EDIT)
            return versions.name(s, c, revision, name)
        return run(ctx, go)

    @server.tool()
    def add_elements(ctx: Context, canvas_id: str,
                     nodes: Annotated[list[dict], Field(
                         description="Nodes to add. type: text (default; `text` is Markdown), "
                                     "link (`url`), file (`file`; '<tab name>.canvas' links to that tab "
                                     "of the workspace, with optional subpath '#<node id>') or "
                                     "group (`label`). Optional: "
                                     "id, color ('1'-'6' or '#rrggbb'), group (id of a group "
                                     "node to put it in), x/y/width/height (omit to auto-place "
                                     "and auto-size), ports ([{id, side: top|right|bottom|left, "
                                     "at: 0-1 along that side from its top/left end, label?}]: "
                                     "named connection points that replace the four side "
                                     "handles), icon (a `file` from list_icons, shown above a "
                                     "text node's text), schema (avro|protobuf|json|yaml|sql: "
                                     "the text node's `text` is that schema's source; it is "
                                     "shown highlighted, sized to fit, and every field gets a "
                                     "port per side, '<field path>' on the right and "
                                     "'<field path>@left' on the left, e.g. 'orders.customer_id'; "
                                     "the result lists each schema's fields). " + NODE_STYLE)] = [],  # noqa: B006
                     edges: Annotated[list[dict], Field(
                         description="Edges to add: fromNode, toNode (ids, existing or from "
                                     "`nodes`). Optional: id, label, color, fromEnd/toEnd "
                                     "('none'|'arrow', default toEnd arrow), fromSide/toSide "
                                     "(top|right|bottom|left; omit to let the editor choose), "
                                     "fromPort/toPort (a port id on that node; the side then "
                                     "follows the port). "
                                     + EDGE_STYLE)
                     ] = [],  # noqa: B006
                     direction: Direction = "TB") -> dict:
        """Add nodes and edges. Unpositioned nodes are laid out as a block in
        `direction`, beside the existing nodes they connect to (or beside the
        drawing if they connect to nothing). Returns the new ids, each new
        node's box (x, y, width, height) and `overlaps`: pairs of node ids
        whose boxes now collide, which you should fix."""
        if not nodes and not edges:
            raise ToolError("nothing to add")
        return write(ctx, canvas_id, make=lambda s: ops.add_elements(
            nodes, edges, direction, lambda f: icons.ports_of(s, f)))

    @server.tool()
    def update_elements(ctx: Context, canvas_id: str,
                        updates: Annotated[list[dict], Field(
                            description="[{id, set: {key: value, other_key: null}, fit?: bool}] "
                                        "— null removes a key; fit:true resizes a node to its "
                                        "text. id and type can't change. styleAttributes is "
                                        "merged: {styleAttributes: {shape: 'diamond'}} changes "
                                        "only the shape, {styleAttributes: {path: null}} resets "
                                        "one attribute.")]) -> dict:
        """Change existing nodes or edges: text, colour, label, geometry, ends, sides,
        ports, fromPort/toPort, styleAttributes (see add_elements for the values).
        Setting a node's ports replaces the whole list; edges on a port that no
        longer exists keep their side."""
        return write(ctx, canvas_id, make=lambda s: ops.update_elements(
            updates, lambda f: icons.ports_of(s, f)))

    @server.tool()
    def delete_elements(ctx: Context, canvas_id: str, ids: list[str]) -> dict:
        """Delete nodes and edges by id. Edges attached to a deleted node are removed;
        a deleted group's contents stay."""
        return write(ctx, canvas_id, ops.delete_elements(ids))

    @server.tool()
    def layout(ctx: Context, canvas_id: str, node_ids: list[str] | None = None,
               direction: Direction = "TB") -> dict:
        """Tidy nodes into a layered layout following the edges (all nodes by
        default). Groups move with their contents and are refitted. Returns each
        moved node's box and any `overlaps`."""
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
    def list_icons(ctx: Context) -> dict:
        """Icons you can put on text nodes: the user's own, built-in Lucide line
        icons (server, database, cloud, user, lock, inbox/send, ...) and
        schematic symbols (resistor, capacitor, diode, npn, nmos, op-amp, logic
        gates, ground, supply, junction, ...). Show one by setting a text
        node's `icon` to its `file`; the text becomes a caption, so give it a
        square-ish size (e.g. 120x120).

        Icons with `ports` (pins) are symbols: add_elements gives the node
        those ports, a square size and no border, and its text is shown under
        it (a designator/value such as "R1 10k"). Wire pins with edges'
        fromPort/toPort. styleAttributes rotate ("90"/"180"/"270", clockwise)
        and mirror ("horizontal") turn a symbol and move its ports with it.
        A junction (sym-junction) joins three or more wires; a net label is a
        text node with styleAttributes {"shape": "net"} (its port "net" is
        added for you; mirror "horizontal" points it right), and labels with
        the same text are the same net. Edges from pin to pin between these
        parts are drawn as wires: routed at right angles around every part,
        hopping where they cross, so don't set a pathfindingMethod for them."""
        def go(s, user, who):
            brief = lambda i: {k: i[k] for k in ("id", "name", "file", "ports")}  # noqa: E731
            every = icons.builtins().values()
            return {"mine": [brief(icons.out(i)) for i in icons.mine(s, user)],
                    "builtin": [brief(icons.out(b)) for b in every if not icons.is_symbol(b["id"])],
                    "symbols": [brief(icons.out(b)) | {"category": b["category"]}
                                for b in every if icons.is_symbol(b["id"])]}
        return run(ctx, go)

    @server.tool()
    def list_templates(ctx: Context) -> dict:
        """Templates you can use: stencil (one styled node), fragment (a few
        connected nodes) and page (a whole starting canvas). The user's own come
        first. Returns ids, names, kinds and node counts; pass an id to
        apply_template or create_canvas."""
        def go(s, user, who):
            def brief(t):
                d = t["data"]
                return {"id": t["id"], "name": t["name"], "kind": t["kind"],
                        "builtin": t["builtin"], "nodes": len(d["nodes"]),
                        "texts": [n.get("text") or n.get("label") for n in d["nodes"]][:6]}
            mine = [brief(templates.out(t)) for t in templates.mine(s, user)]
            return {"templates": mine + [brief(t) for t in templates.BUILTIN.values()],
                    "default_page": templates.default_page_id(s, user)}
        return run(ctx, go)

    @server.tool()
    def apply_template(ctx: Context, canvas_id: str, template_id: str,
                       x: int | None = None, y: int | None = None) -> dict:
        """Drop a template's nodes onto a canvas with fresh ids, its top-left at
        (x, y), or beside the existing drawing if omitted. Returns the new ids,
        their boxes and any `overlaps`; edit their text with update_elements."""
        def go(s, user, who):
            t = templates.get(s, user, template_id)
            if t is None:
                raise ToolError(f"no template {template_id!r}; see list_templates")
            c, result = ops.mutate(s, user, canvas_id, who, ops.insert(t["data"], x, y),
                                   settings.max_canvas_bytes)
            return {**result, "revision": c.revision}
        return run(ctx, go)

    @server.tool()
    def save_template(ctx: Context, canvas_id: str, node_ids: list[str],
                      name: Annotated[str, Field(min_length=1, max_length=200)],
                      kind: Literal["stencil", "fragment", "page"] = "fragment") -> dict:
        """Save nodes from a canvas (with the contents of any chosen group, and
        the edges between them) as one of the user's templates. Ask the user
        before saving templates they didn't ask for."""
        def go(s, user, who):
            c = access.canvas(s, user, canvas_id)
            try:
                t = templates.create(s, user, name, kind, ops.extract(c.data, node_ids))
            except templates.TemplateError as exc:
                raise ToolError(str(exc)) from None
            return {"template_id": t.id, "kind": t.kind, "nodes": len(t.data["nodes"])}
        return run(ctx, go)

    if settings.browserless_url and tickets is not None:
        @server.tool()
        def render_canvas(ctx: Context, canvas_id: str,
                          node_ids: Annotated[list[str] | None, Field(
                              description="Zoom to just these nodes (and what lies between "
                                          "them); omit for the whole canvas.")] = None
                          ) -> list[Image | str]:
            """A PNG of the canvas exactly as the editor draws it (shapes, routed
            edges, labels, images). Look at it after building or changing a
            diagram and fix what reads wrong: edges crossing nodes, labels on
            top of lines, overlaps, cramped or lopsided layout. Up to 1600 px a
            side; a big canvas is scaled down, so pass node_ids to inspect an
            area closely."""
            def go(s, user, who):
                c = access.canvas(s, user, canvas_id)
                if node_ids:
                    known = {n["id"] for n in c.data.get("nodes", [])}
                    missing = sorted(set(node_ids) - known)
                    if missing:
                        raise ToolError(f"no such nodes: {missing[:10]}")
                return c.workspace_id, render.viewport(c.data, node_ids), c.revision
            ws_id, size, revision = run(ctx, go)
            token = tickets.issue(canvas_id, ws_id)
            try:
                url = render.page_url(settings.render_base_url or settings.public_url,
                                      canvas_id, token, node_ids)
                png = render.screenshot(settings.browserless_url, url, size)
            except render.RenderError as exc:
                raise ToolError(str(exc)) from None
            finally:
                tickets.revoke(token)
            return [Image(data=png, format="png"),
                    f"revision {revision}, {size[0]}x{size[1]} px"]

    @server.tool()
    def list_attachments(ctx: Context, workspace_id: str) -> dict:
        """Files uploaded to a workspace (images and others). To show one, add a
        file node with `file` set to its `file` value; size an image node to
        roughly its aspect ratio."""
        if store is None:
            return {"attachments": [], "note": "attachments are not set up on this server"}

        def go(s, user, who):
            from sqlalchemy import select
            ws = access.workspace(s, user, workspace_id)
            rows = s.scalars(select(Attachment).where(Attachment.workspace_id == ws.id)
                             .order_by(Attachment.created_at.desc())).all()
            return {"attachments": [{k: v for k, v in attachments.out(a).items() if k != "url"}
                                    for a in rows]}
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

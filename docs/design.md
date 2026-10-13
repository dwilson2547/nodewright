# nodewright — design

Status markers (CONVENTIONS §10): ✅ verified · 📐 planned (a decision, not yet built) ·
⚠ unverified (believed, not checked — confirm before building on it).

## 1. Goals

1. Interactive editor for JSON Canvas documents that is pleasant to use: snap-to-grid, connector
   styling, shape/node templates, default pages. 📐
2. Workspaces holding multiple canvases shown as tabs, with links between documents. 📐
3. Sign-in via the cluster's authentik (OIDC). 📐
4. An MCP server through which an agent reads and edits a user's diagrams, with the edits appearing
   live in any open browser tab. 📐

Non-goals for v1: real-time multi-user co-editing (CRDT), vector PDF export, Visio file import.

## 2. Why build rather than self-host draw.io

draw.io already covers most of the editor feature list. The reason to build is the **file format**:
everything is stored and exported as JSON Canvas so a workspace exports as a folder of `.canvas`
files that opens as an Obsidian vault. If that stops mattering, revisit this decision.

## 3. Document format

### 3.1 What the spec provides ✅ (jsoncanvas.org/spec/1.0, fetched 2026-10-10)

- Top level: `nodes`, `edges` arrays. Node array order is z-order.
- Node types: `text`, `file` (`file`, optional `subpath` starting with `#`), `link` (`url`),
  `group` (`label`, `background`, `backgroundStyle`). All nodes have integer `x/y/width/height`,
  optional `color`.
- Edges: `id`, `fromNode`, `toNode`, optional `fromSide`/`toSide` (top/right/bottom/left),
  `fromEnd`/`toEnd` (`none` | `arrow`; defaults `none` / `arrow`), `color`, `label`.
- Colour: hex string or preset `"1"`–`"6"`.

The spec has **no** line style, line width, waypoints, routing mode, or node shape.

### 3.2 Extensions ✅ (0.4.0)

Extra styling lives in additional keys on nodes/edges, never by repurposing spec fields, so every
file stays a valid JSON Canvas document. Keys and values are the Obsidian *Advanced Canvas*
plugin's `styleAttributes` (✅ verified against its `style-config.ts` at commit 4b8630c), so styled
files render in Obsidian with that plugin. ⚠ unverified: whether stock Obsidian (without the
plugin) preserves unknown keys when it re-saves a canvas.

| Element | `styleAttributes` key | Values (absent = default) |
|---|---|---|
| Node | `shape` | pill, diamond, parallelogram, circle, predefined-process, document, database |
| Node | `border` | dashed, dotted, invisible |
| Node | `textAlign` | center, right |
| Edge | `path` | dotted, short-dashed, long-dashed |
| Edge | `arrow` | triangle-outline, thin-triangle, halved-triangle, diamond, diamond-outline, circle, circle-outline, blunt |
| Edge | `pathfindingMethod` | direct (straight, never rerouted), square (sharp right angles around nodes), a-star (rounded right angles around nodes); absent = curved, switching to a rounded detour when the curve would cross a node (0.5.0) |
| Edge | `lineWidth` | 1, 2, 3, 4, 6, 8 — nodewright's own; the plugin has none |
| Edge | `cornerRadius` | 0, 4, 8, 12, 16, 24, 32, 48 (px) — nodewright's own (0.10.0). Rounds every bend of a right-angle route or a curved edge's detour; absent = square 0, otherwise 12 (8 on the fallback step path when no route is found). No effect on `direct` or a plain curve. A bend never rounds past half its shorter neighbouring segment |

Loading only checks `styleAttributes` is an object of strings, so newer plugin values still load;
agent writes are checked strictly against the table. Snap and grid size are a per-browser editor
preference, not stored in the canvas. Manual edge waypoints: §18 (0.19.0), an extra `waypoints`
key on the edge.

### 3.3 Documents and links ✅ (0.4.0; zip export 0.9.0)

- A **workspace** is a folder; each **tab** is one `.canvas` document in it.
- Links between documents use spec `file` nodes: `file: "<tab name>.canvas"`, optional
  `subpath: "#<node id>"`. Clicking opens that tab and selects the node. Matching is by tab name
  (exact, then case-insensitive, then last path segment), as in Obsidian, so **renaming a tab
  breaks links to it**. Link nodes (`url`) remain for external links.
- **Attachments** are `file` nodes with `file: "attachments/<id>/<name>"`, stored in AIStor under
  `attachments/<workspace>/<id>`. Images (sniffed by magic bytes) render inline; anything else is
  a download. Deleting the node doesn't delete the file, since undo and revisions may still point
  at it; a sweep (at start-up + 5 min, then every 6 h) deletes attachments that no canvas, no
  template and no revision from the last `ATTACHMENT_KEEP_DAYS` (30) uses, once they are that
  old (0.7.0). Deleting the workspace deletes them all. A single-tab `.canvas` export doesn't
  embed them; the workspace zip does.
- **Workspace zip export** ✅ (0.9.0, `bundle.py`, `GET /api/workspaces/{id}/export`, any member):
  `<tab name>.canvas` per tab, `attachments/<id>/<name>` for each attachment a current tab shows,
  and `.nodewright/workspace.json` (workspace name, tab order, version, attachments missing from
  storage). Canvases are written unchanged, since file and tab-link paths are already
  vault-relative, so the unpacked folder opens as an Obsidian vault. Tab names are reduced to
  filename-safe characters and repeats get " (2)"; a tab link whose name lost characters to that
  no longer matches its file. Built in a spooled temp file (memory to 8 MB, then disk). The UI
  saves pending edits before downloading. Not built: zip import, which the manifest is for.

## 4. Templates ✅ (0.4.0)

A template is a JSON Canvas fragment with coordinates relative to its own origin, stored per user.

- **Node templates / stencils:** single styled nodes (a "database" cylinder, a "decision" diamond)
  in a side palette.
- **Fragment templates:** multi-node groups dropped as one unit.
- **Page templates:** a whole canvas; the "default page" for a new tab is the user's chosen page
  template. Ship a small built-in set.

Insertion = offset coordinates, regenerate ids, snap to grid. Built: built-in stencils, snippets
and pages; user templates of each kind; per-user default page applied to new workspaces and tabs;
palette insert by click (nearest free grid slot to the view centre) or drag; MCP
`list_templates` / `apply_template` / `save_template`.

## 5. Architecture 📐

Monorepo (CONVENTIONS §1a), deployed by its own Helm chart at `helm/nodewright/` (§6).

```
nodewright/
  api/      backend: REST + live-update channel + MCP endpoint
  ui/       editor SPA
  helm/nodewright/
  docs/
```

- **Frontend:** React + React Flow (xyflow, MIT). It already provides node/edge model, handles,
  snap-to-grid, custom edge renderers, minimap. JSON Canvas ↔ React Flow is a thin mapping layer
  that must round-trip without loss (unknown keys preserved). tldraw rejected (licence).
- **Backend:** Python FastAPI, matching other workspace services. Stores each canvas as a JSON
  document plus metadata; keeps a revision history (every save is a row) for undo-across-sessions
  and to recover from bad agent edits.
- **Storage:** cluster Postgres (`infra/cluster-config/postgres`). ⚠ unverified: capacity/ops
  conventions for adding a database there — read cluster-config docs first.
- **Attachments** (images and other files referenced by `file` nodes): AIStor object storage
  (✅ user decision 2026-10-10), in a dedicated `nodewright` bucket. Follows the dxf-converter
  pattern (`infra/cluster-config/example-secrets/dxf-converter/secret.yml`): AIStor on TrueNAS,
  S3 API at `http://192.168.0.10:30320` (the console on `:30321` is not the API); endpoint and
  bucket go in the chart's `values.yaml`, only the access keys in a hand-applied Secret.
  The browser never talks to AIStor directly — the API proxies or presigns, so the bucket stays
  private and LAN-only.
- **Live updates:** server pushes canvas changes over SSE or WebSocket so an open tab shows agent
  edits as they happen. Writes carry the base revision; conflicting writes are rejected (optimistic
  concurrency) rather than merged.
- **Layout engine:** ELK (elkjs) or dagre, used by the editor ("tidy up") and by the MCP
  `layout` tool.

## 6. Auth 📐

### 6.1 Browser

authentik OIDC confidential client, authorization-code flow, following the DanWiki blueprint
(`infra/cluster-config/authentik/blueprints/danwiki.yaml`): authentik answers *who*; nodewright keeps
its own users table keyed by the `sub` claim and issues its own session. Group claims can gate
"may sign in" if wanted.

### 6.2 MCP clients

The MCP authorization spec makes the MCP server an OAuth resource server; clients discover the
authorization server via protected-resource metadata and expect to register themselves
(dynamic client registration or client-ID metadata documents). ⚠ unverified: whether authentik
supports either; and the exact current MCP auth spec revision — re-read it before implementing.

Plan, in order:
1. ✅ (0.2.0) **Personal access tokens** (v1): created in the nodewright UI, scoped to the user, sent as
   `Authorization: Bearer`. Works with any MCP client that accepts static headers.
2. ✅ (0.3.0) **Full MCP OAuth**: nodewright acts as the authorization server for MCP clients
   and delegates the actual login to authentik — the same "authentik for identity, app issues
   tokens" split as 6.1. Built on the MCP SDK's `mcp.server.auth` handlers (metadata, RFC 7591
   registration, PKCE S256, token, revoke); `api/nodewright/oauth.py` stores clients, pending
   requests, codes and grants, and renders the consent page. Verified with the SDK's
   `OAuthClientProvider` against a local server and with a browser click-through of the
   consent page (2026-10-11). ⚠ unverified: Claude Code, VS Code and Copilot CLI against prod.
   - Registration is open (that's how MCP clients work), so redirect URIs must be https,
     http on loopback, or an app scheme; clients never approved are pruned after a day; the
     consent page shows the redirect host because the client name is self-asserted.
   - Access tokens `nwo_` live 1 h, refresh tokens `nwr_` 60 days, rotated together on refresh.
     One `oauth_grants` row per connected app; deleting it disconnects the app.
   - The consent form posts to self and 303s to the client; browsers apply CSP `form-action`
     to that redirect, so the consent response widens `form-action` to the redirect origin.

## 7. MCP server 📐

Streamable-HTTP endpoint on the API (same process, same auth). Tools operate at the semantic level
so an agent never has to invent pixel coordinates:

Built in 0.2.0 (✅ verified with the MCP Python SDK client against a local server):

| Tool | Purpose |
|---|---|
| `list_workspaces` | Discovery: workspaces with their canvases, plus the user's folders (0.7.0) |
| `create_workspace`, `create_canvas` | New workspace (optionally into a folder) / tab (returns a `/?canvas=` link) |
| `create_folder`, `file_workspace` | Organise workspaces into the user's folders, §11.2 (0.7.0) |
| `get_canvas` | Full JSON Canvas + revision + current lock; `revision` reads an earlier one (0.15.0) |
| `list_versions`, `save_version` | The tab's history and named versions, §14 (0.15.0) |
| `add_elements` | Nodes and edges in one call; agent-chosen ids; `group` to nest; positions optional |
| `update_elements`, `delete_elements` | Batch edit by id (`null` removes a key; `fit` resizes to text) |
| `layout` | Re-place all or some nodes; groups move with their contents and refit |
| `lock_canvas`, `unlock_canvas` | Explicit lease for long builds (§11.3) |
| `get_style_guide` | The user's style guide (§11.4) |
| `render_canvas` | PNG of the canvas (or `node_ids` and their surroundings) as the editor draws it, so an agent can check its work (0.6.0) |

Still planned: `apply_template` (§4), `link_canvases` (§3.3).

Layout is our own (`api/nodewright/layout.py`), not ELK/dagre: a layered layout (cycle breaking,
longest-path layers, barycentre ordering, least-squares packing) with groups as compound nodes,
snapped to a 20 px grid. Unpositioned new nodes are laid out as one block and anchored below/right
of the existing nodes they connect to. An edge that skips layers gets a placeholder in each layer
it crosses, so those layers leave a lane open for it (0.5.0).

Edges without waypoints (§18) are routed where they are drawn: `ui/src/routing.ts`
is an orthogonal A* over a sparse grid of lines 20 px outside every node, with a bend penalty
(0.5.0). The server does not route; placing ops instead return each placed node's box and any
`overlaps` (pairs of colliding node ids) so an agent can check its work without `get_canvas`.

Agent feedback 2026-10-11 (from a web Claude session using the MCP): wanted a `render_canvas` tool
returning an image so an agent can see its result. Built in 0.6.0 on the real editor in headless
Chromium rather than a second, server-side SVG renderer, so the picture always matches what the
user sees, routing included. The tool issues a one-time ticket (in memory, 60 s, revoked when the
call returns) scoped to that canvas and its workspace's attachments, and asks the cluster's
browserless (`browserless.scrape-stack.svc:3000`, shared with the scrapers) to screenshot
`/render?canvas=&t=` through the in-cluster service. That page is a read-only, chrome-free
React Flow view that sets `#nw-render[data-ready]` once nodes are measured, the view is fitted and
images have loaded. The viewport is the drawing's size plus padding, at most 1600 px a side. The
tool is only registered when `BROWSERLESS_URL` is set. Tickets in process memory assume the single
replica the chart already pins.

Key rule: nodes added without coordinates are placed by the layout engine. Every tool call is one
revision, so a bad agent edit is one undo away.

## 8. Phases 📐

Revised 2026-10-11 (proposed): the agent integration is the main appeal (✅ user), so MCP moves ahead
of editor polish.

1. ✅ Skeleton: API + Postgres, authentik login, workspaces/tabs, load/save, snap-to-grid, basic edge
   styling, import/export.
2. ✅ (0.2.0) **Agents:** personal access tokens, the §7 tool set, layout engine, live push to open tabs (SSE),
   edit leases (§11.3), style guides (§11.4).
3. ✅ (0.4.0) **Editor:** shapes and edge line styles (§3.2), templates and default pages (§4),
   tab links and attachments (§3.3). Folders (§11.2) followed in 0.7.0 with Alembic (✅ user
   approved the migration).
4. **Sharing:** ✅ (0.7.0) read-only share links (§9) and folders (§11.2); ✅ (0.8.0) workspace
   members (§11.1). Organisations were built and then removed (§19).
5. **Next, in order** (✅ user, 2026-10-11): ✅ workspace zip export (0.9.0) → ✅ edge corner radius (0.10.0) →
   ✅ node ports (0.11.0) → ✅ icons and built-in set (0.12.0) → ✅ icon creator (0.13.0) →
   ✅ schema nodes (0.14.0) → ✅ versions (0.15.0, §14; ✅ user: per tab, not per schema or per
   workspace) → ✅ schematic symbols, junctions and net labels (0.16.0, §15) → ✅ schematic wiring
   (0.17.0, §16) → ✅ colour by net (0.18.0, §17) → ✅ manual edge waypoints (0.19.0, §18) →
   organisations (built in 0.20.0-0.21.0, removed in 0.22.0, §19).
6. **Stretch:** marketplace (§11.5), custom roles.

Full MCP OAuth (§6.2) was pulled forward and shipped as 0.3.0 (✅ user asked for browser sign-in).

Each phase ends deployed to the cluster. Biggest risk is editor polish being bottomless; each phase
needs an explicit stop line.

## 9. Open questions

Resolved 2026-10-10 (✅ user):

- **Public** at `https://nodewright.danwils.com`. Who may sign up is controlled in authentik.
- **Attachments** in AIStor (§5).
- **Read-only share links** are rendered by nodewright itself (same renderer as the editor, so style
  extensions and cross-canvas links work), behind an unguessable, revocable token. Not via
  `meta/canvas-viewer`: its CSP (`connect-src 'self'`) only loads files from its own origin and it
  does not understand the §3.2 extensions. canvas-viewer stays the simple tool for loose `.canvas`
  files. Built in 0.7.0 (`api/nodewright/shares.py`, `ui/src/Share.tsx`): a link is to one tab, or
  with `all_tabs` to every tab of its workspace so tab links work; only owners (`workspace.manage`)
  create, list or revoke links; revoking deletes the row. Tokens are stored as is so the link can be
  copied again (they guard nothing outside the same database). Attachments are served by token too,
  and a single-tab link only serves files that tab shows. No agent tool creates links: making
  something public stays a deliberate human act.

## 10. Status

Phase 1 ✅ deployed 2026-10-11 as 0.1.0; phase 2 ✅ as 0.2.0, MCP OAuth sign-in as 0.3.0, editor
phase as 0.4.0 (see `CHANGELOG.md`): MCP server, access tokens, auto-layout, edit leases, SSE live
updates, style guides, shapes and line styles, templates, tab links, attachments, and
`authorize()` with a members table (no sharing UI). 0.7.0 added folders, read-only share links,
Alembic migrations, CI and the unused-attachment sweep. 0.8.0 added workspace members, 0.9.0 workspace zip
export, 0.10.0 edge corner radius, 0.11.0 node ports, 0.12.0 icons, 0.13.0 icon creator, 0.14.0
schema nodes, 0.15.0 versions, 0.16.0 schematic symbols, 0.17.0 schematic wiring, 0.18.0 colour
by net, 0.19.0 manual edge waypoints; 0.20.0-0.21.0 organisations, removed again in 0.22.0 (§19).
Not yet: zip import. Live updates are in-process, so the chart must stay at
one replica until `events.py` moves to Postgres LISTEN/NOTIFY.

## 11. Future: collaboration and community 📐

User direction 2026-10-11 (✅ user): sharing and collaboration on the same document. Organisations
and fine-grained permissions were later dropped (✅ user, 2026-10-12, §19). Folders,
a public marketplace for template packs and agent instruction sets, and a server-side lock so
several people's agents don't fight over one document.

### 11.1 Ownership and permissions — leave room now, build later

- Every access check goes through **one function**, `authorize(user, resource, action)`, with
  actions as strings (`canvas.read`, `canvas.edit`, `canvas.delete`, `workspace.manage`,
  `members.manage`, ...). Today it answers "owner may do everything". Routes and MCP tools never
  check ownership themselves, so orgs and roles later change one function, not every endpoint.
- **Membership table** ✅ (0.8.0, `members.py`) `workspace_members(workspace_id, user_id, role)`.
  An org-group principal is still open; it would add a `principal_type` column. A role is a named
  set of actions (`access.ROLES`).
  - Built-in roles: owner (`workspaces.owner_id`, never a member row), editor, viewer. A commenter
    role waits for comments to exist.
  - Owners add an existing user by exact username (✅ user: no pending invites, so no email and no
    invites table), change their role, or remove them; any member may leave. Removal also drops
    their folder filing of the workspace and releases edit leases they hold in it. The UI's
    **Share** dialog lists people for every role and read-only links for owners only; the header,
    tabs and sidebar hide what a member's role can't do.
- **Organisations** and custom roles: not wanted (§19).
- Schema changes are Alembic migrations (`api/nodewright/migrations/`, 0.7.0). `db.migrate()` runs
  at startup; a database made by the old `create_all` is stamped at the `0001` baseline first.

### 11.2 Folders ✅ (0.7.0)

Built differently from the first sketch (folders of canvases inside a workspace): folders hold
**workspaces**, and each user has their own tree. A workspace's tabs already group its canvases, so
the missing layer was above the workspace, and per-user placement stays correct once workspaces are
shared: a member files a shared workspace wherever they like without moving it for the owner.

- `folders(id, owner_id, parent_id → folders ON DELETE CASCADE, name, created_at)`;
  `workspace_folders(user_id, workspace_id, folder_id ON DELETE CASCADE)`, primary key
  (user, workspace). No row means top level. Migration `0002_folders`.
- Deleting a folder deletes its subfolders; the workspaces in them go back to the top level and are
  never deleted. Moves reject cycles. Limits: depth 8, 500 folders per user.
- Folders carry no permissions; access stays at the workspace (avoids ACL inheritance). Filing a
  workspace needs read access to it.
- REST: `GET/POST /api/folders`, `PATCH/DELETE /api/folders/{id}`, `PUT /api/workspaces/{id}/folder`;
  `GET /api/workspaces` includes each workspace's `folder_id`. MCP: `list_workspaces` returns the
  folders, plus `create_folder`, `file_workspace`, and `create_workspace(folder_id=)`.
- UI: a collapsible left sidebar replaces the header workspace picker. Drag a workspace or folder
  onto a folder to file it, or onto the sidebar header/background for the top level.

### 11.3 Edit leases (server-side lock)

Compare-and-swap revisions already stop silent overwrites. A lease stops two agents from wasting
work by colliding in the first place.

- `canvas_leases(canvas_id PK, holder_user, holder_kind ui|agent, client_label, expires_at)`.
- **TTL 2 min, renewed by activity.** Each MCP write renews it; the browser renews it by heartbeat
  while the tab has unsaved or active edits.
- **Agents:** write tools take the lease implicitly. A held lease returns a clear "locked by X
  (agent of dan), expires in 90 s" error so the agent can wait or move on. Explicit `lock_canvas` /
  `unlock_canvas` tools are available for long multi-step builds.
- **Browser:** shows "Claude (dan) is editing" and goes read-only, with live updates streaming in.
  The owner or an editor can break a lease.
- **Expiry, not explicit release, is the safety net:** a crashed agent's lease simply lapses.

As built (0.2.0): `canvas_leases(canvas_id PK, holder, kind, user_id, label, expires_at)`, holder =
`kind:user:client` (a browser tab id or an access-token id). Each browser save takes/renews a 30 s
lease (no heartbeat); each agent write 2 min; `lock_canvas` 1–15 min. Leaving a tab releases it.
Conflicts are HTTP 423 for the browser and a tool error for agents. Breaking a lease needs the
`lease.break` permission (owner, editor).

### 11.4 Agent style guides

A per-user (later per-org) markdown "how I like my diagrams" document plus structured defaults
(direction, spacing, colours per node kind, preferred templates). Exposed to agents as an MCP
resource/prompt and returned by `get_canvas`, so agents follow it without being told each time.

As built (0.2.0): free-text markdown only, per user, via the `get_style_guide` tool (the server
instructions tell agents to call it first) and edited in the Agents dialog; a built-in default is
returned until the user saves one. Structured defaults and per-org guides are not built.
A style guide is also the unit the marketplace shares (§11.5).

### 11.5 Marketplace (stretch)

Public listings of **template packs** and **style guides**: versioned, with author, licence field
and install count. Installing copies the item into the user's library, so later edits by the author
don't change installed copies; updates are explicit. Being public, it needs reporting and the ability
for an admin to unlist items before it is opened up. ⚠ unverified: no abuse/moderation design yet.

## 12. Schema nodes ✅ (0.14.0, `schemas.py`, `ui/src/schema.ts`, `nodes.tsx` SchemaBody)

User direction 2026-10-11 (✅ user): architecture diagrams often link to the schema of a connection
between apps; nodewright should store that schema **in** the diagram, visible and syntax
highlighted. Formats to start: Avro, Protobuf, JSON (incl. JSON Schema), YAML, and SQL
(✅ user, added the same day). A typed node with a parser that reads those files into the element.

Agreed 2026-10-11 (✅ user): ports on both sides of every field; dropped `.json`/`.yaml` files
become schema nodes. Built as below; parsers cover Avro records (nested records, unions,
arrays/maps of records), JSON Schema `properties` / `$defs` / `definitions` / OpenAPI
`components.schemas` (else a plain document's keys), Protobuf messages (nested, `oneof`, one-line
blocks) and SQL `CREATE TABLE` columns (types with commas, several columns per line). Field cap
400. `POST /api/schemas/parse` serves the editor; signed-out pages (share, render) show the
format without the schema name.

- **Stored as a text node** with `schema: "avro"|"protobuf"|"json"|"yaml"|"sql"` and `text` holding
  the source as a fenced code block (```` ```avro ````). Obsidian shows it as a highlighted code
  block, so the file degrades well and stays valid JSON Canvas.
- **Shown** as a header (format and the schema's name: Avro record, first Protobuf message, first
  SQL table, JSON Schema `title`) above the highlighted source with fixed metrics (monospace,
  fixed line height). Height always fits the source; only the width is resizable, so a line's y
  position is known. Highlighting: highlight.js (json for Avro, yaml, protobuf, sql), bundled.
- **Parsed on the server** (`schemas.py`, one parser for UI and agents) into fields
  `{path, name, type, line}`: Avro record fields (nested records → `a.b`), JSON Schema
  `properties` (or a plain JSON/YAML example's keys), Protobuf message fields, SQL
  `CREATE TABLE` columns (`table.column`). JSON, Avro and YAML are read with a YAML composer for
  exact line numbers. PyYAML is a new dependency.
- **A port per field on each side**: `<path>` on the right and `<path>@left` on the left, at that
  field's line (§13.1). They are written into the node's `ports`, so share links, render, Obsidian
  round trips and agents see ordinary ports. The UI calls `POST /api/schemas/parse` after an
  edit; agent writes with `schema` are parsed on the server. A parse error shows in the node and
  leaves the ports empty, so lines on fields go dangling (flagged) until it's fixed, not deleted.
- **Creating:** a `+ Schema` menu with a sample per format, or drop a schema file (`.avsc`,
  `.proto`, `.json`, `.yaml`/`.yml`, `.sql`) onto the canvas to get a schema node instead of an
  attachment. Double-click edits the source.
- **MCP:** `add_elements` takes `schema` + `text` (plain or fenced); fields come back so an agent
  can connect `fromPort: "orders.customer_id"` to `toPort: "customers.id@left"`.

## 13. Node ports and custom icons 📐

Proposed 2026-10-11 and agreed the same day (✅ user): ports before icons; SVG uploads checked
against an element/attribute allowlist; a built-in icon set; and an icon creator for basic shapes,
wanted for schematics. User direction (✅ user): connection points are attributes
with locations, and the user sets their number and placement in the editor; uploaded SVGs are
scanned before import to verify they carry no script.

### 13.1 Ports ✅ (0.11.0, `ports.py`, `ui/src/ports.ts`, `PortsPanel.tsx`)

Built as below, except: ports are edited from a **Ports** panel (toolbar button on one selected
node) with presets and per-port id, label, side and a position slider, not by dragging handles
along the side yet. Renaming a port in the panel carries its lines along. Port labels are drawn
inside the node and can overlap its text. Agent writes must name existing ports; canvas saves
from the editor may name missing ones (dangling).

- **Node:** an extension key `ports`, an array of `{id, side, at, label?}`. `side` is
  top/right/bottom/left; `at` is the fraction along that side (0 = top/left end, 1 = bottom/right
  end), so ports follow a resize. Side plus fraction rather than free x/y because the router needs
  an exit direction, and schematic pins and schema fields always sit on a boundary.
- **Edge:** `fromPort` / `toPort` name a port id. The edge also keeps `fromSide` / `toSide` set to
  that port's side, so Obsidian and older nodewright still draw it on the right side of the node.
- **Rendering:** a node with `ports` shows those handles instead of the four side-centre handles. A
  node without `ports` behaves exactly as today. The router already takes a start point and a
  side, so ports feed it unchanged; no routing change.
- **Editor:** selecting one node adds a Ports control: presets (none, 1 per side, 2 left / 2 right,
  ...), plus add, drag along a side, label and delete. Labels render inside the node next to the
  port.
- **Dangling references:** an edge whose port no longer exists falls back to its side and is
  flagged in the editor. Nothing is deleted.
- **Derived ports:** a node type may compute its ports instead of storing them. Schema nodes (§12)
  derive one port per field (`id` = the field path), so an edge can point at a single field.
- **MCP:** `add_elements` / `update_elements` accept `ports` on nodes and `fromPort` / `toPort` on
  edges, checked against the node's ports. `get_canvas` returns them.
- No migration: everything lives in the canvas JSON. `canvas_format` already leaves unknown keys
  alone; ports get a shape check like `styleAttributes`.

### 13.2 Icons ✅ (0.12.0, `icons.py`, `svgsafe.py`, `ui/src/icons.ts`; icon creator 0.13.0)

Built as below, with these specifics:
- Validation: `defusedxml` (no DTD/entities), element and attribute allowlists, `style`
  attributes converted into checked presentation attributes, a `<style>` element rejected, editor
  namespaces and `<metadata>` dropped. 256 KB / 5000 elements / depth 32. All 1539 Lucide 0.460.0
  icons pass.
- Built-in set: 73 Lucide 0.460.0 icons in `api/nodewright/builtin_icons/` with its ISC LICENSE
  (✅ verified from the package's LICENSE file); ids `lucide-<name>`.
- Library: `icons` table (migration `0004`), per user, at most 500. `GET /api/icons/<id>.svg`
  serves any icon by id without sign-in, so members and share-link viewers see icons they don't
  own.
- Node: `icon: "icons/<id>/<name>.svg"` on a text node; `styleAttributes.iconColors = "original"`
  draws it in its own colours, otherwise it is a mask filled with the node colour. The default
  comes from the icon's `tinted` flag when placed.
- Palette **Icons** section: search, click to add a 120x120 icon node (or to put the icon on the
  selected text box if it has none), drag to place, upload SVG, delete your own. An icon's ports
  are copied to a node that has none.
- MCP `list_icons`; `add_elements` takes `icon`. Zip export writes `icons/<id>/<name>.svg`.

- **Upload with validation.** Parse the SVG with a hardened XML parser (no DTDs or entities). Then
  check every element and attribute against an **allowlist** of drawing elements (svg, g, path,
  basic shapes, text, gradients, clipPath, mask, symbol, use, title, desc) and presentation
  attributes. Reject the upload and name what was found. An allowlist rather than a script scan,
  because script also gets in through `on*` handlers, `javascript:` hrefs, `foreignObject`,
  external `href`/`url()` references and CSS. What is stored is re-serialised from the parsed
  tree, never the uploaded bytes. Size and element-count caps.
- **Rendered as images, never inline markup,** so even a validator miss can't run script.
  Monochrome icons are drawn with CSS `mask-image` filled with the node's colour, so they recolour
  like everything else. Full-colour icons use `<img>`. The user picks which kind at upload.
- **Library:** an `icons` table (owner, name, svg, monochrome, default ports) beside templates; an
  Alembic migration. Per user now, per organisation once those exist. Plus a small built-in set
  for architecture diagrams (server, database, queue, cache, user, cloud, lock, ...). The source
  of that set (e.g. Lucide) and its licence are ⚠ unverified until chosen.
- **In a canvas:** a text node with an extension key `icon: "icons/<id>/<name>.svg"`. The icon is
  drawn above the text, and the text becomes the caption. In Obsidian it degrades to the caption.
  Zip export (§3.3) adds `icons/<id>/<name>.svg`.
- **Icons carry default ports**, so a dropped symbol arrives with its pins (a resistor with two).
  This is what schematics are built from.
- **Icon creator** ✅ (0.13.0, `IconCreator.tsx`, `iconDraw.ts`; ✅ user asked for it): a 100x100
  box on a 5-unit snap grid; tools select/move, rect (corner radius), ellipse, line, polyline
  (open/closed), arc (drag the chord, then the middle handle or a Bend slider; bulge −1..1 of half
  the chord), text, and pin (snaps to the nearest box edge; becomes a port). Per-shape stroke,
  fill and colour; undo/redo, arrow-key nudge, Delete. Saves `toSvg()` output through the same
  validator, with the pins as ports and the drawing as `source` (nullable `icons.source`,
  migration `0005`), so icons made here reopen for editing (palette ✎). No raw SVG source view.
- **Symbols:** an icon with ports is placed as an 80x80 node with no caption and an invisible
  border, and its icon fills the node, so pins on the node's sides meet the drawing's edges.
  This holds while the node stays square.
- Icon SVGs are served with an ETag and `no-cache`, so an edited icon shows at once.

### 13.3 Proposed order

1. Ports (format, rendering, editor, MCP). No migration. Unblocks schemas.
2. Icons: upload validation, library + migration, built-in set, icon on text nodes, zip export.
3. Default ports on icons, then schema nodes (§12) with derived field ports.
4. The icon creator.

## 14. Versions ✅ (0.15.0, `versions.py`, `ui/src/HistoryPanel.tsx`, `Editor.tsx`)

Per tab (✅ user, 2026-10-11): a tab is the diagram, and every save was already a full row in
`canvas_revisions`. Workspace-wide snapshots were considered and deferred; they would need their
own table, and a cross-tab restore while others edit those tabs.

- **History panel** (header → History): the tab's revisions newest first, 100 per page
  (`GET /api/canvases/{id}/revisions?before=&named=`). Autosave makes many revisions, so a run of
  unnamed revisions by the same person from the same source, each within 15 minutes of the next,
  collapses into one row ("▸ 14 saves"). Rows say who, when, and whether an agent, an import or a
  restore made them.
- **Named versions** are a revision with a `label` (`PATCH .../revisions/{n}`, edit rights; the
  edit lease isn't needed, since naming doesn't change the document). "Save version…" flushes
  unsaved edits and names the revision that results. Any later cleanup of old revisions must keep
  labelled ones; there is no cleanup today.
- **Preview** (`GET .../revisions/{n}`) draws the old document read-only in place of the editor,
  outlining nodes a restore would bring back (green) or change (amber), with a one-line summary
  of what restoring would do. Closing the panel ends the preview.
- **Restore** puts the old document into the editor as an ordinary edit: one Ctrl+Z away, saved
  as a new revision with `source: "restore"` and `restored_from`. History is only ever appended.
  Viewers browse and preview but don't restore or name.
- **Agents:** `list_versions`, `save_version` (e.g. before a large restructure) and
  `get_canvas(revision=)`. There is no agent restore; an agent can read an old revision and write
  it back with the normal tools if asked.

Not done: version history in the zip export, a visual diff of lines, workspace-wide snapshots,
revision cleanup.

## 15. Schematics ✅ (0.16.0, `symbols.py`, `ports.py` orientation, `nodes.tsx` SymbolNode)

✅ user, 2026-10-11: symbol library, junctions and net labels now; a schematic-only wiring mode is
to be discussed once these are in use (it would touch the edge router, which stays as is).

- **Symbols** are built-in icons with pins (`symbols.py`, ids `sym-<name>`): 36 in five groups
  (passive, semiconductors, sources and power, logic and ICs, switches and other). Each is drawn
  in a 100x100 box with its leads running to the box edge, so a pin `{side, at}` is exactly where
  a lead ends. `GET /api/icons` lists them under `symbols` with `category` and `size`.
- A **symbol node** is any text node whose `icon` has ports. It is square (the drawing fills it;
  the resizer keeps the aspect ratio), borderless, and shows its text under the box as a
  caption ("R1 10k"), so the caption never moves the pins. Pin handles have no size of their own
  (React Flow ends a line at the outer edge of a handle's box), so wires meet the leads; a
  pseudo-element is the visible square and the grab area, shown on hover or selection.
- **Orientation:** `styleAttributes.rotate` (90/180/270, clockwise) and `mirror` ("horizontal",
  applied before rotating). The stored `ports` are always where the pins are drawn; changing the
  orientation moves them (`ports.reorient` / `ports.ts` `turned`, `flipped`), and edge sides
  follow. So anything that reads ports, Obsidian included, needs no knowledge of rotation. The
  drawing is turned with a CSS transform `rotate(r) scaleX(-1)`.
- **Junction** (`sym-junction`): a 16 px dot with a pin per side; three or more wires meet there.
- **Net labels:** a text node with `shape: "net"`, drawn as a tag whose point is its one port
  `net` (left; flipped, right). Labels with the same text (trimmed, case-insensitive) are the
  same net: selecting one outlines the others and the toolbar counts them. Nothing else treats
  them as connected yet.
- **Agents:** `list_icons` returns `symbols`; `add_elements` turns a node whose `icon` has pins
  into a symbol (ports in the node's orientation, square size, no border) unless it is given
  ports or a size; `update_elements` moves ports when rotate/mirror change; a `shape: "net"` node
  gets its port.

Not done: a wiring mode (orthogonal routing that never crosses its own parts, wire-to-wire joins,
splitting a wire with a junction), net-aware export, multi-unit parts and pin numbers.

## 16. Schematic wiring ✅ (0.17.0, `ui/src/wires.ts`)

✅ user, 2026-10-11: no strict no-crossing rule (dense circuits would become unroutable). The
user's idea of colouring crossing wires differently was weighed against hops: recolouring would
overwrite meaningful colours, change as parts move (and land in history), and needs more colours
than the presets in dense areas. Hops were chosen; colour by net (stable, meaningful) is the
follow-up.

- **What's a wire:** an edge whose two ends name ports on schematic parts (symbols, junctions,
  net labels), unless its `pathfindingMethod` is `direct`. Every other edge keeps the §3.2 router
  unchanged (`routing.ts` only gained exports).
- **Routed together:** `RoutedEdge` reads its path from `wiresFor(wireKey(store))`, one pass
  over all wires per canvas state (cached by key). Shortest wires first; each is an orthogonal A*
  (`wireRoute`) on lines 10 px outside every part *including its own two* and every symbol
  caption, with a cost per bend (60), per crossing of another net's wire (100, about 100 px of
  detour) and for running along one (2000, effectively barred, since it would look connected).
  Wires of the same net may share a trunk. Blocked steps and costs are precomputed on the grid
  per wire. Measured 2026-10-11 in the dev build: 60 resistors with 100 random wires, a
  20-step drag plus the drop's full re-route, produced no task over 50 ms (the first version,
  which checked every part and wire at each search step, took ~1.5 s per pass).
- **While dragging,** wires not on a moving part keep their last settled routes; the drop
  re-routes everything.
- **Nets** (union-find): a wire joins its two pins, a junction joins all its pins, net labels
  with the same name are one net.
- **Hops:** where wires of different nets cross, the horizontal one jumps the vertical with a
  5 px arc.
- **Dots:** wires leaving the same pin share their first leg; where they part, a dot is drawn.
  A junction symbol is its own dot.
- **Captions** go on the first side of a symbol without pins (below, right, left, above), so a
  vertical part's caption sits beside it.
- New wires (editor or agent) default to no arrowhead. Automatic routes aren't stored: Obsidian
  draws the same edges its own way. A wire with waypoints (§18) is drawn through them and placed
  before the rest, which route around it; it still hops and gets dots.

Not done: wire-to-wire joins (attaching a wire to the middle of another), and stored routes for
other readers.

## 17. Colour by net ✅ (0.18.0, `wires.ts` colours, `edges.tsx` NetColours)

A document setting, top-level `"colorByNet": true` (kept by `canvas_format` like any unknown
top-level key), so share links, version previews and agent screenshots match the editor. The
editor's **Net colours** toggle (shown when the tab has wires) is one undoable edit.

- A wire with its own `color` keeps it; the rest take their net's colour.
- A net's name (`wires.ts` nets): a net label's name if it has one, `gnd` if it reaches a ground
  symbol (drawn in the default grey), else its alphabetically first pin. So colours hold while
  unrelated wires change.
- Ten colours. Nets are taken in name order; each gets the colour its name hashes to, or the next
  one no other net on the canvas has, repeating only when all ten are in use. Adding a net can
  shift a later net's colour; that trade was taken over same-coloured neighbours.

Not done: agents can't toggle it (no tool sets top-level keys); a legend of nets and colours.

## 18. Manual edge waypoints ✅ (0.19.0, `routing.ts` orthoLegs/curveThrough, `edges.tsx` WaypointHandles)

✅ user (2026-10-12): waypoints stay put when a node moves, for now.

- **Stored** as `"waypoints": [{"x", "y"}, …]` on the edge, in canvas coordinates. It's an extra
  key, so Obsidian ignores it and draws its own route. `canvas_format` rounds the points to
  integers and allows at most 100 per edge.
- **Drawn** through the waypoints in the edge's own style, skipping the router: straight segments
  for `direct`, right angles for `square`/`a-star` (each leg bends once, carrying on the way it
  was going unless that doubles back; corner radius applies), and a Catmull-Rom curve for the
  default, leaving and arriving square to the node's side. Edges without waypoints route exactly
  as before.
- **Wires** (§16) with waypoints get right angles, are placed first, and the automatic wires
  route around them; hops and dots work as before.
- **Editing:** a selected line shows a handle per waypoint and a "+" in the middle of each leg
  (a quarter of the way along when there are no waypoints and the line has a label). Drag a
  handle to move it, snapped to the grid when snap is on. Drag a "+" to add a waypoint (a plain
  click does nothing). Double-click a handle to remove it. **Reset route** clears them all.
  Handles sit in React Flow's edge label layer, raised above a selected edge.
- **Moving nodes:** waypoints stay put, except on lines whose both ends move in the same drag
  (a multi-selection, or the contents of a dragged group); those move with it.
- **Agents** set `waypoints` on `add_elements`/`update_elements` (null clears them). `layout`
  clears them on edges touching a node it moved and reports `routes_cleared`. Templates store
  them relative to the fragment and offset them when inserted (server and editor).

Not done: waypoints following their nodes; the "+" can sit on a label at the middle of a leg.

## 19. Organisations: removed (0.22.0)

Built in 0.20.0 (orgs owning workspaces, org access, an authentik group mapping) and 0.21.0
(org-shared templates, icons and style guides), then removed in 0.22.0 (✅ user, 2026-10-12): too many
permission layers for a tool used personally and by a few friends, and webdoc, which nodewright will
integrate with closely, dropped orgs too. Sharing stays as §11.1: personal workspaces, members by
name (editor/viewer), read-only links. Migration `0009` drops the org schema; `0007`/`0008` stay
because production ran them. Don't re-propose orgs or more role machinery.


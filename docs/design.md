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

Loading only checks `styleAttributes` is an object of strings, so newer plugin values still load;
agent writes are checked strictly against the table. Snap and grid size are a per-browser editor
preference, not stored in the canvas. Manual edge waypoints: not built.

### 3.3 Documents and links ✅ (0.4.0, except zip export)

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
  old (0.7.0). Deleting the workspace deletes them all. Exports don't embed them yet.
- Not built: export a workspace as a zip of `.canvas` files + attachments; import the same.

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
| `get_canvas` | Full JSON Canvas + revision + current lock |
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

Edges are routed where they are drawn, since JSON Canvas edges have no waypoints: `ui/src/routing.ts`
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
4. **Sharing:** ✅ (0.7.0) read-only share links (§9) and folders (§11.2); next workspace members,
   then organisations with built-in roles (§11.1).
5. **Stretch:** marketplace (§11.5), custom roles, workspace zip import/export.

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
Alembic migrations, CI and the unused-attachment sweep. Not yet: workspace members UI,
organisations, zip export. Live updates are in-process, so the chart must stay at
one replica until `events.py` moves to Postgres LISTEN/NOTIFY.

## 11. Future: collaboration and community 📐

User direction 2026-10-11 (✅ user): sharing and collaboration on the same document is the point of
organisations; fine-grained permissions are a stretch goal that must not be designed out. Folders,
a public marketplace for template packs and agent instruction sets, and a server-side lock so
several people's agents don't fight over one document.

### 11.1 Ownership and permissions — leave room now, build later

- Every access check goes through **one function**, `authorize(user, resource, action)`, with
  actions as strings (`canvas.read`, `canvas.edit`, `canvas.delete`, `workspace.manage`,
  `members.manage`, ...). Today it answers "owner may do everything". Routes and MCP tools never
  check ownership themselves, so orgs and roles later change one function, not every endpoint.
- **Membership table** `workspace_members(workspace_id, principal_type, principal_id, role)`, where
  a principal is a user or (later) an org group. A role is a named set of actions.
  - Built-in roles: owner, editor, commenter, viewer.
  - Custom roles later: a `roles` table holding an action set per org. Org admins pick built-ins or
    define their own.
- **Organisations** later: `orgs`, `org_members(org, user, org_role)`, and workspaces owned by an
  org. Optional mapping from an authentik group claim to org membership/role at sign-in, the same
  way dxf-converter maps its admin group.
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

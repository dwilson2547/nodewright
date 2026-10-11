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

### 3.2 Extensions 📐

Extra styling lives in additional keys on nodes/edges, never by repurposing spec fields, so every
file stays a valid JSON Canvas document. Adopt the key names of the Obsidian *Advanced Canvas*
plugin (`styleAttributes` object: edge path style, path routing, arrow shapes; node shape) so those
files render with that plugin installed. ⚠ unverified: exact Advanced Canvas key names/values, and
whether stock Obsidian preserves unknown keys when it re-saves a canvas. Check both before freezing
the schema; if Obsidian strips unknown keys, the extensions are lost on an Obsidian round-trip and
that must be documented, not hidden.

Planned extension surface:

| Element | Extension | Notes |
|---|---|---|
| Edge | line style (solid/dashed/dotted), width, routing (bezier/straight/orthogonal), extra end shapes | Orthogonal routing is computed, not stored as waypoints |
| Edge | manual waypoints | Only if routing proves insufficient; nodewright-only key |
| Node | shape (rect, rounded, diamond, ellipse, cylinder, …) | Visio-style stencils |
| Canvas | grid size, snap on/off | Editor preference, stored per canvas |

### 3.3 Documents and links 📐

- A **workspace** is a folder; each **tab** is one `.canvas` document in it.
- Links between documents use spec `file` nodes: `file: "other.canvas"`, optional `subpath`
  targeting a node. Clicking opens/focuses that tab. Link nodes (`url`) remain for external links.
- Export a workspace as a zip of `.canvas` files (+ attachments); import the same.

## 4. Templates 📐

A template is a JSON Canvas fragment with coordinates relative to its own origin, stored per user.

- **Node templates / stencils:** single styled nodes (a "database" cylinder, a "decision" diamond)
  in a side palette.
- **Fragment templates:** multi-node groups dropped as one unit.
- **Page templates:** a whole canvas; the "default page" for a new tab is the user's chosen page
  template. Ship a small built-in set.

Insertion = offset coordinates, regenerate ids, snap to grid.

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
1. **Personal access tokens** (v1): created in the nodewright UI, scoped to the user, sent as
   `Authorization: Bearer`. Works with any MCP client that accepts static headers.
2. **Full MCP OAuth** (later): nodewright acts as the authorization server for MCP clients
   (handles registration, issues its own tokens) and delegates the actual login to authentik — the
   same "authentik for identity, app issues tokens" split as 6.1.

## 7. MCP server 📐

Streamable-HTTP endpoint on the API (same process, same auth). Tools operate at the semantic level
so an agent never has to invent pixel coordinates:

| Tool | Purpose |
|---|---|
| `list_workspaces`, `list_canvases` | Discovery |
| `get_canvas` | Full JSON Canvas + revision |
| `create_canvas` | New tab, optionally from a page template |
| `add_nodes`, `add_edges` | Batch add; positions optional |
| `update_elements`, `delete_elements` | Batch edit by id |
| `layout` | Auto-place nodes (all or a subset) with ELK/dagre |
| `apply_template` | Insert a template at a position or near a node |
| `link_canvases` | Add a file node pointing at another canvas |

Key rule: nodes added without coordinates are placed by the layout engine. Every tool call is one
revision, so a bad agent edit is one undo away.

## 8. Phases 📐

Revised 2026-10-11 (proposed): the agent integration is the main appeal (✅ user), so MCP moves ahead
of editor polish.

1. ✅ Skeleton: API + Postgres, authentik login, workspaces/tabs, load/save, snap-to-grid, basic edge
   styling, import/export.
2. **Agents:** personal access tokens, the §7 tool set, layout engine, live push to open tabs (SSE),
   edit leases (§11.3), style guides (§11.4).
3. **Editor:** shapes and edge line styles (§3.2), templates and default pages (§4), folders (§11.2),
   attachments (AIStor).
4. **Sharing:** read-only share links, workspace members, organisations with built-in roles (§11.1).
5. **Stretch:** marketplace (§11.5), custom roles, full MCP OAuth, workspace zip import/export.

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
  files. Not built yet.

## 10. Status

Phase 1 ✅ deployed 2026-10-11 as 0.1.0 (see `CHANGELOG.md`). Beyond the phase-1 line it already has
snap-to-grid (10/20/40 px), edge colour/arrow ends/labels, undo/redo and `.canvas` import/export.
Not yet: shapes and edge line styles (§3.2), templates (§4), share links, MCP, attachments, Alembic
(schema is `create_all` at startup, so the first schema change needs migrations set up).

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
- Additive tables only, so `create_all` still works until Alembic is introduced. The first
  *changed* column (not a new table) is the trigger to set up Alembic.

### 11.2 Folders

A workspace holds a tree of folders (`folders(id, workspace_id, parent_id, name, position)`), and a
canvas gets a nullable `folder_id`. Tabs become "open canvases" rather than "every canvas in the
workspace". Permissions stay at the workspace level, not per folder (avoids ACL inheritance).

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

### 11.4 Agent style guides

A per-user (later per-org) markdown "how I like my diagrams" document plus structured defaults
(direction, spacing, colours per node kind, preferred templates). Exposed to agents as an MCP
resource/prompt and returned by `get_canvas`, so agents follow it without being told each time.
A style guide is also the unit the marketplace shares (§11.5).

### 11.5 Marketplace (stretch)

Public listings of **template packs** and **style guides**: versioned, with author, licence field
and install count. Installing copies the item into the user's library, so later edits by the author
don't change installed copies; updates are explicit. Being public, it needs reporting and the ability
for an admin to unlist items before it is opened up. ⚠ unverified: no abuse/moderation design yet.

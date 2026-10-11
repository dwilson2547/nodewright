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

1. Skeleton: monorepo, API + Postgres, authentik login, workspaces/tabs, load/save JSON Canvas.
2. Editor: React Flow mapping with lossless round-trip, snap-to-grid, edge styling, shapes,
   templates/default pages.
3. MCP: PAT auth, the tool set above, live push to the browser, layout engine.
4. Full MCP OAuth, cross-document links, workspace zip import/export.

Each phase ends deployed to the cluster. Biggest risk is editor polish being bottomless; each phase
needs an explicit stop line.

## 9. Open questions

- Public instance (like canvas-viewer's `*.danwils.com`) or LAN-only? Affects who may sign up.
- Sharing: per-canvas read-only links, and should they reuse canvas-viewer?
- Attachment/image storage for file nodes (Postgres blobs vs. object storage).

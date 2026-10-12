# Changelog

## 0.19.0 - 2026-10-12

### Added
- **Waypoints** on lines: select a line and drag the "+" in the middle of a leg to bend it there.
  Drag a waypoint to move it, double-click it to remove it, or use **Reset route** to go back to
  automatic routing. The line is drawn through its waypoints in its own style: straight, right
  angles, or a smooth curve. Schematic wires with waypoints keep their right angles, and the
  other wires route around them.
- Waypoints stay put when you move a node. Lines with both ends in a dragged selection or group
  move with it.
- Agents can set or clear `waypoints` on lines. The layout tool clears them on lines whose nodes
  it moves. Templates keep a line's waypoints.

## 0.18.0 - 2026-10-11

### Added
- **Net colours** (editor toolbar, shown when a tab has wires): each wire takes its net's colour.
  Net labels name a net, ground nets stay grey, and other nets keep their colour as you edit.
  Neighbouring nets get different colours until all ten are in use. A wire you colour yourself
  keeps its colour. Saved with the tab, so share links and previews show it too.

## 0.17.0 - 2026-10-11

### Added
- Schematic wiring: lines from pin to pin between symbols, junctions and net labels are routed
  as wires, all together. Right angles only, clear of every part (including the two they join)
  and of symbol captions, avoiding crossings where a short detour does it and never running
  along another net's wire.
- Where wires of different nets cross, the horizontal one hops over the vertical one.
- A dot where wires leaving the same pin split.
- New wires have no arrowhead.

### Changed
- A symbol's caption goes on a side without pins (a vertical resistor's sits to its right).
- The shape and text-alignment pickers no longer show for symbols.

### Fixed
- An agent-created net label that starts flipped had its pin on the wrong side.

## 0.16.0 - 2026-10-11

### Added
- **Symbols** in the palette: 36 schematic symbols in five groups (resistors, capacitors,
  inductors, diodes, LEDs, BJTs, MOSFETs, sources, ground and supply, op-amp, logic gates,
  switches, lamp, motor, antenna, terminal). Click or drag to place; each pin is a connection
  point where its lead ends, so wires meet the drawing.
- A symbol's text shows under it as a caption (designator and value, e.g. "R1 10k");
  double-click to edit.
- **⟳ Rotate** and **⇋ Flip** for selected symbols; pins and their wires move with the drawing.
- Junction dots, and **+ Net label**: a tag-shaped label with one pin. Selecting one outlines
  the other labels with the same name and counts them. Net labels can be flipped to point right.
- MCP: `list_icons` lists `symbols`; agents place a symbol by its `icon` and get its pins as
  ports, and can rotate/mirror it with `styleAttributes`.

### Changed
- `GET /api/icons` returns symbols separately (`symbols`) from the Lucide icons (`builtin`).
- New styleAttributes for nodes: `rotate`, `mirror`; new shape `net`.

## 0.15.0 - 2026-10-11

### Added
- **History** (header): every saved change to the tab, newest first. Runs of autosaves by one
  person collapse into one row; agent edits, imports and restores are marked.
- Named versions: **Save version…** names the current state, and ✎ names, renames or unnames any
  revision. **Named versions only** filters the list.
- Click a revision to preview it read-only, with the nodes a restore would bring back or change
  outlined and a summary of what it would do. **Restore** applies it as a normal edit, so Ctrl+Z
  undoes it, and records which revision it came from.
- MCP: `list_versions`, `save_version`, and `get_canvas` takes `revision` to read an earlier one.

### Changed
- Database migration `0006` adds `canvas_revisions.label` and `restored_from`.
- `GET /api/canvases/{id}/revisions` returns `{current, revisions, more}` (was a bare list) and
  takes `before` and `named`.
- Share links use the same read-only view component as the preview (`ReadOnlyFlow.tsx`).

## 0.14.0 - 2026-10-11

### Added
- Schema nodes: **+ Schema** adds an Avro, Protobuf, JSON / JSON Schema, YAML / OpenAPI or SQL
  schema, shown syntax-highlighted under a header with its name. Dropping a `.avsc`, `.proto`,
  `.json`, `.yaml`/`.yml` or `.sql` file onto the canvas makes one too. Double-click to edit
  (Ctrl+Enter or click away to finish).
- Every field gets a connection point on each side, level with its line, so lines can join a
  field in one schema to a field in another: `orders.customer_id` on the right,
  `orders.customer_id@left` on the left. A schema that stops parsing shows the error in its header
  and its lines are flagged, not deleted, until it's fixed.
- Stored as a text node with `schema` and the source in a fenced code block, so Obsidian shows it
  as highlighted code.
- MCP: `add_elements` / `update_elements` take `schema` and return each schema's fields.

## 0.13.0 - 2026-10-11

### Added
- Icon creator (palette → **Create icon…**): draw an icon from rectangles, ellipses, lines,
  polylines, arcs and text on a snap grid, and put pins on its edges; pins become the icon's
  ports. Per-shape stroke width, fill and colour, undo/redo, arrow-key nudging. Icons you draw
  reopen for editing (✎ on the palette icon).
- Icons with ports are placed as symbols: square, no caption, no border, the drawing filling the
  node so lines from its pins meet its leads. The groundwork for schematics.

### Changed
- Database migration `0005` adds `icons.source` (the creator's drawing).
- Icons are revalidated by ETag instead of cached for 5 minutes, so edits show at once.

## 0.12.0 - 2026-10-11

### Added
- Icons: the palette has an **Icons** section with 73 built-in Lucide line icons and your own.
  Click one to add an icon node (its text becomes the caption), or drag it onto the canvas;
  clicking with a plain text box selected puts the icon on that box. Icons take the node's colour,
  or keep their own colours (toolbar: icon colours). **Remove icon** keeps the text.
- Upload SVG icons. Every upload is checked against an allowlist of drawing elements and
  attributes: script, event handlers, embedded HTML, external links and `<style>` are rejected
  with the reason; Inkscape metadata is dropped and `style` attributes become plain attributes.
  What's stored is rebuilt from the checked drawing, and icons are only ever shown as images.
- Icons can carry ports, which a node gets when the icon is placed on it.
- MCP: `list_icons`; `add_elements` takes `icon` on text nodes. Zip export includes the icons a
  workspace uses.

### Changed
- Database migration `0004` adds the `icons` table (runs at startup).

## 0.11.0 - 2026-10-11

### Added
- Node ports: named connection points at chosen places on a node's sides. Select one node and
  open **Ports** to apply a preset (1–3 in/out, top/bottom, 2 per side) or add, label, move and
  delete ports. A node with ports shows those pins instead of its four side handles; lines drawn
  from a pin remember it (`fromPort` / `toPort`) and follow it when it moves or is renamed. A line
  whose port was removed falls back to its side and is marked with a red dashed band. Files stay
  valid JSON Canvas: each line also keeps the plain side, so Obsidian draws it on the right side.
- MCP: `add_elements` / `update_elements` take `ports` on nodes and `fromPort` / `toPort` on
  edges; ports an agent names must exist, and the edge's side follows the port.

## 0.10.1 - 2026-10-11

### Fixed
- Lines crossing a group couldn't be clicked: groups are nodes, and React Flow draws every node
  above every edge, so a group's body covered them. Edges now sit above group bodies and still
  pass under other nodes.
- A selected line now shows an accent halo and is drawn above everything while selected, so it's
  clear which line you're editing and you can grab it where it runs under a node.

## 0.10.0 - 2026-10-11

### Added
- Edge corner radius: a new `cornerRadius` style (0–48 px) rounds the bends of right-angle routes
  and of a curved edge's detour around a node. Set it from the edge toolbar's corners picker or
  through MCP `styleAttributes`. Edges without it look exactly as before.

## 0.9.0 - 2026-10-11

### Added
- Workspace zip export: **Export ▾ → Whole workspace (.zip)** downloads every tab as a `.canvas`
  plus the attachments they show, laid out so the unzipped folder opens as an Obsidian vault.
  Includes `.nodewright/workspace.json` (tab order, workspace name) for a later import.
  `GET /api/workspaces/{id}/export`.

### Fixed
- Images in the editor showed as missing since 0.7.0: the share-link page set the attachment URL
  when its module loaded, which happens on every page, so the editor asked the share route with an
  empty token. Share and render pages now set it only when they render.

## 0.8.0 - 2026-10-11

### Added
- Workspace members: **Share** now lists who has access. Owners add someone by username (they must
  have signed in once) as an editor or viewer, change their role or remove them; members can leave.
  Shared workspaces show in a member's sidebar, marked with the owner; viewers get a read-only
  editor and no rename, delete, import or new-tab controls. Workspaces carry `role` and `owner`
  in the API and MCP `list_workspaces`.

### Changed
- Removing a member releases any edit lease they hold in that workspace, so others can edit at
  once.

## 0.7.0 - 2026-10-11

### Added
- Read-only share links: **Share** in the header makes a link to the open tab that anyone can view
  at `/s/<token>` without signing in, optionally with the workspace's other tabs so tab links work.
  Links always show the latest version and can be revoked; only a workspace's owner manages them.
- Folders: a collapsible sidebar replaces the workspace picker. Folders nest, are personal to each
  user, and take workspaces or other folders by drag and drop. Deleting a folder never deletes a
  workspace. MCP: `list_workspaces` returns folders; new `create_folder` and `file_workspace`;
  `create_workspace` takes `folder_id`.
- Attachments nothing uses any more are deleted after `attachments.keepDays` (30): not on any
  current canvas, template, or revision from that window.
- CI (GitHub Actions): tests, lint and build on every push; on `main` the image is pushed to Docker
  Hub, including `:<version>` the first time a version appears.

### Changed
- Schema changes are Alembic migrations, run at startup. An existing database is stamped at the
  0.6.0 baseline first, then upgraded.

### Fixed
- Edges keep clear of group titles, and labels move along their edge to avoid sitting on a node or
  a group's border.

## 0.6.0 - 2026-10-11

### Added
- `render_canvas` MCP tool: returns a PNG of the canvas, or of chosen nodes and their
  surroundings, drawn by the real editor in the cluster's headless Chromium (browserless). Agents
  can check their own work instead of waiting for a screenshot from the user. Enabled by
  `render.browserlessUrl` in the chart.

## 0.5.0 - 2026-10-11

From agent feedback after testing the MCP against prod.

### Added
- Edges route around nodes. `a-star` and `square` edges take right-angle paths that keep clear of
  every other node (rounded and sharp corners); default curved edges switch to a rounded detour
  only when the curve would cross a node; `direct` stays straight. Labels sit on the path's
  midpoint on a solid background.
- `add_elements`, `layout` and `apply_template` return each placed node's box
  (`nodes: [{id, x, y, width, height}]`) and `overlaps`, so an agent can check its work without
  calling `get_canvas`.

### Changed
- Auto-layout reserves a lane in every layer an edge skips, so a node no longer sits in the path of
  an edge between its neighbours.

## 0.4.1 - 2026-10-11

### Fixed
- An agent write no longer shortens its own `lock_canvas` lock: the implicit 2-minute renewal
  now keeps the later expiry, so `lock_canvas(minutes=10)` followed by edits holds for 10.

## 0.4.0 - 2026-10-11

### Added
- Node shapes (pill, diamond, parallelogram, circle, predefined process, document, database),
  dashed/dotted/invisible borders and text alignment; edge dash patterns, line widths, routing
  (curved, straight, right-angle) and arrowhead shapes. Stored as Advanced Canvas
  `styleAttributes` so styled files render in Obsidian with that plugin; `lineWidth` is ours.
- Templates: built-in stencils, snippets and pages plus user templates ("Save as template",
  "Save this canvas as a page"). A palette inserts by click (nearest free grid slot) or drag.
  New workspaces and tabs start from the user's default page. MCP: `list_templates`,
  `apply_template`, `save_template`.
- Tab links: spec `file` nodes pointing at `<tab name>.canvas` (optional `#<node id>` subpath)
  open that tab and select the node. "+ Tab link…" in the toolbar; agents can add them too.
- Attachments: drop, paste or "+ File" to upload images and files (20 MB each) to AIStor.
  Images render inline; other files are download cards. MCP: `list_attachments`.

### Security
- Attachments are served inline only when the bytes sniff as PNG/JPEG/GIF/WEBP/AVIF (never SVG);
  everything else downloads as `application/octet-stream`. All responses carry
  `Content-Security-Policy: default-src 'none'; sandbox`.

## [0.3.1]

### Fixed
- OAuth issuer in authorization-server metadata no longer has a trailing slash (RFC 8414 exact match).

## 0.3.0 - 2026-10-11

### Added
- Browser sign-in for MCP clients (MCP authorization spec): nodewright is the OAuth
  authorization server for `/mcp`, with protected-resource and authorization-server metadata,
  dynamic client registration, PKCE, refresh-token rotation and revocation (the MCP SDK's
  handlers; storage and consent in `oauth.py`). Login itself is still authentik.
- Consent page at `/oauth/consent`, bound to the signed-in user with a one-time nonce; shows where
  the user will be sent back to. Its CSP allows the form redirect to that origin only.
- Agents dialog: "Connect an agent" with token-free setup, and "Connected apps" with Disconnect.
- `/api/auth/oidc/login?next=` returns to the consent page after sign-in (only that path).

### Changed
- `/mcp` 401s carry `WWW-Authenticate: Bearer resource_metadata=…` so clients can discover sign-in.
- Personal access tokens remain for clients without browser sign-in.

## 0.2.0 - 2026-10-11

### Added
- Phase 2 "Agents": MCP server at `/mcp` (streamable HTTP, stateless) with `list_workspaces`,
  `create_workspace`, `create_canvas`, `get_canvas`, `add_elements`, `update_elements`,
  `delete_elements`, `layout`, `lock_canvas`, `unlock_canvas`, `get_style_guide`.
- Server-side layered auto-layout with groups as compound nodes; nodes without coordinates are
  placed next to what they connect to and sized to their text.
- Personal access tokens (Agents dialog; shown once; hashed at rest; MCP only, not a REST credential).
- Edit leases: every write takes a short per-canvas lease (browser tab 30 s, agent 2 min,
  `lock_canvas` up to 15 min). Other holders get 423 / a "locked" tool error; the browser goes
  view-only with a banner and "Take over".
- Live updates: open tabs follow other writers over SSE (`/api/canvases/{id}/events`).
- Per-user agent style guide with a built-in default.
- `authorize()` as the single permission check, with a `workspace_members` table and
  owner/editor/viewer roles (no sharing UI yet).
- `/?canvas=<id>` deep links.

### Fixed
- Group nodes drew a second border (React Flow's built-in `group` styling).
- uvicorn graceful shutdown capped at 5 s so open event streams can't stall a rollout.

## 0.1.0 - 2026-10-11

### Added
- Phase 1: authentik OIDC sign-in (cookie sessions, CSRF header), workspaces with tabs, JSON Canvas
  load/save with compare-and-swap revisions and a revision log, lossless import/export (unknown keys kept).
- Editor (React Flow): text/group/link/file nodes, markdown text, connect any side, snap-to-grid,
  edge colour/arrows/labels, node colours, undo/redo, autosave, conflict banner.
- Image `dwilson2547/nodewright:0.1.0`, Helm chart, deployed at https://nodewright.danwils.com.

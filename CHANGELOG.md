# Changelog

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

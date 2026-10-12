---
tier: system
domain: apps
---

# nodewright

A web diagram editor ("budget web Visio") whose document format is
[JSON Canvas](https://jsoncanvas.org), so diagrams stay openable in Obsidian. It ships an MCP server so
an agent can build diagrams on a user's behalf, and signs users in through the cluster's authentik.

Status: **0.17.0 live** at https://nodewright.danwils.com — editor with shapes, line styles and corner radius, node ports, icons (built-in Lucide set,
SVG upload and an icon creator), schema nodes (Avro, Protobuf, JSON, YAML, SQL) with a
connection point per field, per-tab history with named versions, preview and restore, schematic symbols with junctions and
net labels and right-angle wiring with hops at crossings,
edges that route around nodes, a `render_canvas` tool so agents can see what they drew,
folders for workspaces, workspace members (editor/viewer), read-only share links,
snap-to-grid, templates and default pages, links between tabs, image/file attachments;
workspaces and tabs, autosave with conflict detection, `.canvas` import/export, workspace zip
export, and the MCP server: agents build diagrams with
server-side auto-layout, open tabs update live, and a per-canvas edit lease stops people and agents
overwriting each other. Design and roadmap: [`docs/design.md`](docs/design.md).

## Connect an agent

1. Add the server to your MCP client; no token needed:
   - Claude Code: `claude mcp add --transport http nodewright https://nodewright.danwils.com/mcp`
   - `mcpServers`-style clients (VS Code, Copilot CLI, Cursor):
     `{"mcpServers": {"nodewright": {"type": "http", "url": "https://nodewright.danwils.com/mcp"}}}`
2. On first use the client opens a browser: sign in (authentik) and **Allow** it. It then holds a
   1-hour access token that it refreshes itself; disconnect it under **Agents → Connected apps**.
3. Ask it to "draw X in nodewright". **Agents** also holds the style guide agents read first.

Clients that can't do the browser sign-in can use a personal access token instead: **Agents →
Access tokens**, sent as `Authorization: Bearer nwp_…` (`--header` for Claude Code, `headers` in
`mcpServers`). Tokens of either kind only work at `/mcp`.

## Layout

- `api/` — FastAPI (`nodewright/`), SQLAlchemy on Postgres (SQLite locally), authentik OIDC login.
  `access.py` permissions, `leases.py` edit locks, `events.py` SSE fan-out, `ops.py` + `layout.py`
  the agent edit operations, `mcp_server.py` the MCP tools,
  `oauth.py` OAuth sign-in for MCP clients, `styles.py` shape/line-style keys, `templates.py`,
  `storage.py` + `attachments.py` uploads (S3/AIStor, or a directory with `ATTACHMENTS_DIR`).
- `ui/` — Vite + React + React Flow (`@xyflow/react`). Built into the image and served by the API.
- `helm/nodewright/` — chart, deployed by Argo from `infra/cluster-config/argocd/nodewright.yaml`.

## Develop

```bash
cd api && uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements.txt pytest
.venv/bin/python -m pytest -q
DEV_LOGIN=1 .venv/bin/uvicorn --factory nodewright.main:create_app --port 8080   # SQLite, dev sign-in
cd ../ui && npm ci && npm run dev    # proxies /api to :8080
```

`DEV_LOGIN` is refused when `PUBLIC_URL` is https. Other settings: `api/nodewright/config.py`.

## Release

```bash
docker build -t dwilson2547/nodewright:X.Y.Z . && docker push dwilson2547/nodewright:X.Y.Z
```

then bump `image.tag` in `helm/nodewright/values.yaml` and push; Argo rolls it. No CI yet — the repo
has `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` Actions secrets ready for it.

Secrets (`nodewright-db`, `nodewright-oidc`, `authentik-nodewright-oidc`,
`nodewright-bucket-credentials`) are hand-applied; template in
`infra/cluster-config/example-secrets/nodewright/secret.yml`.

Successor in spirit to `meta/canvas-viewer`, which stays as the zero-dependency, read-only share
viewer; nodewright does not replace or modify it.

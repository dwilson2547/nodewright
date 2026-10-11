---
tier: system
domain: apps
---

# nodewright

A web diagram editor ("budget web Visio") whose document format is
[JSON Canvas](https://jsoncanvas.org), so diagrams stay openable in Obsidian. It ships an MCP server so
an agent can build diagrams on a user's behalf, and signs users in through the cluster's authentik.

Status: **phase 2 live** at https://nodewright.danwils.com — editor, workspaces and tabs, autosave
with conflict detection, `.canvas` import/export, and the MCP server: agents build diagrams with
server-side auto-layout, open tabs update live, and a per-canvas edit lease stops people and agents
overwriting each other. Design and roadmap: [`docs/design.md`](docs/design.md).

## Connect an agent

1. Sign in, open **Agents**, create a token. It is shown once, with ready-to-paste config.
2. Claude Code:
   `claude mcp add --transport http nodewright https://nodewright.danwils.com/mcp --header "Authorization: Bearer nwp_…"`
3. Copilot CLI (`~/.copilot/mcp-config.json`) and other `mcpServers`-style clients:
   `{"mcpServers": {"nodewright": {"type": "http", "url": "https://nodewright.danwils.com/mcp",
   "headers": {"Authorization": "Bearer nwp_…"}}}}`
4. Ask it to "draw X in nodewright". The **Agents** dialog also holds the style guide agents read
   before drawing.

Tokens only work at `/mcp`; revoke them from the same dialog.

## Layout

- `api/` — FastAPI (`nodewright/`), SQLAlchemy on Postgres (SQLite locally), authentik OIDC login.
  `access.py` permissions, `leases.py` edit locks, `events.py` SSE fan-out, `ops.py` + `layout.py`
  the agent edit operations, `mcp_server.py` the MCP tools.
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

Secrets (`nodewright-db`, `nodewright-oidc`, `authentik-nodewright-oidc`) are hand-applied; template in
`infra/cluster-config/example-secrets/nodewright/secret.yml`.

Successor in spirit to `meta/canvas-viewer`, which stays as the zero-dependency, read-only share
viewer; nodewright does not replace or modify it.

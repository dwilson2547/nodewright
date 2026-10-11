---
tier: system
domain: apps
---

# nodewright

A web diagram editor ("budget web Visio") whose document format is
[JSON Canvas](https://jsoncanvas.org), so diagrams stay openable in Obsidian. It ships an MCP server so
an agent can build diagrams on a user's behalf, and signs users in through the cluster's authentik.

Status: **design only** — no code yet. See [`docs/design.md`](docs/design.md).

Successor in spirit to `meta/canvas-viewer`, which stays as the zero-dependency, read-only share
viewer; nodewright does not replace or modify it.

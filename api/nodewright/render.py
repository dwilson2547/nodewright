"""Canvas snapshots for agents (render_canvas, design §7).

The image comes from the real editor, so it shows exactly what the user sees,
edge routing included: a headless Chromium (browserless) loads the UI's
/render view, which draws one canvas read-only and marks the page ready.

That page is fetched by the browser, not the user, so it can't use a session
cookie. Instead the server mints a ticket: an unguessable token good for
reading one canvas (and its workspace's attachments) for TICKET_TTL. Tickets
live in this process's memory, which is fine at one replica (the chart
already requires one for live updates), and are dropped once the shot is taken.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

TICKET_TTL = 60.0
PAD = 40
MIN_W, MIN_H = 480, 320
MAX_SIDE = 1600
READY = '#nw-render[data-ready]'


@dataclass(frozen=True)
class Ticket:
    canvas_id: str
    workspace_id: str
    expires: float


class Tickets:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live: dict[str, Ticket] = {}

    def issue(self, canvas_id: str, workspace_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._live = {k: t for k, t in self._live.items() if t.expires > now}
            self._live[token] = Ticket(canvas_id, workspace_id, now + TICKET_TTL)
        return token

    def get(self, token: str | None) -> Ticket | None:
        if not token:
            return None
        with self._lock:
            t = self._live.get(token)
        return t if t is not None and t.expires > time.monotonic() else None

    def revoke(self, token: str) -> None:
        with self._lock:
            self._live.pop(token, None)


def viewport(data: dict, node_ids: list[str] | None = None) -> tuple[int, int]:
    """Browser window size: the drawing's own size (so text is shown at 100%
    when it fits), clamped to MIN..MAX_SIDE keeping the aspect ratio."""
    nodes = [n for n in data.get("nodes", []) if all(k in n for k in ("x", "y", "width", "height"))]
    if node_ids:
        nodes = [n for n in nodes if n["id"] in set(node_ids)]
    if not nodes:
        return MIN_W, MIN_H
    w = max(n["x"] + n["width"] for n in nodes) - min(n["x"] for n in nodes) + 2 * PAD
    h = max(n["y"] + n["height"] for n in nodes) - min(n["y"] for n in nodes) + 2 * PAD
    scale = min(1.0, MAX_SIDE / w, MAX_SIDE / h)
    return max(MIN_W, round(w * scale)), max(MIN_H, round(h * scale))


def page_url(base: str, canvas_id: str, token: str, node_ids: list[str] | None) -> str:
    q = {"canvas": canvas_id, "t": token}
    if node_ids:
        q["focus"] = ",".join(node_ids)
    return f"{base.rstrip('/')}/render?{urlencode(q)}"


class RenderError(Exception):
    pass


def screenshot(browserless_url: str, url: str, size: tuple[int, int],
               timeout: float = 30.0) -> bytes:
    """PNG of `url` from browserless's /screenshot API (v1 and v2 accept this body)."""
    body = {
        "url": url,
        "viewport": {"width": size[0], "height": size[1], "deviceScaleFactor": 1},
        "gotoOptions": {"waitUntil": "networkidle0", "timeout": int(timeout * 1000)},
        "waitFor": READY,
        "options": {"type": "png", "fullPage": False},
    }
    try:
        r = httpx.post(f"{browserless_url.rstrip('/')}/screenshot", json=body,
                       timeout=timeout + 10)
    except httpx.HTTPError as exc:
        raise RenderError(f"the renderer is unreachable: {exc}") from None
    if r.status_code != 200 or not r.content.startswith(b"\x89PNG"):
        raise RenderError(f"the renderer failed ({r.status_code}): {r.text[:200]}")
    return r.content

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

TICKET_TTL = 120.0
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


# Image export ("Export > Image"): the drawing at 100% zoom, so text is the
# size it is in the editor, times a device pixel ratio. Chromium can't
# capture a side past 16384 px, and the pixel cap keeps one export well inside
# the shared browserless pod's memory limit.
EXPORT_SCALES = (1.0, 2.0, 3.0, 4.0)
AUTO_SCALES = (2.0, 1.5, 1.0)
MAX_EXPORT_SIDE = 16384
MAX_EXPORT_PIXELS = 60_000_000


def _bounds(data: dict) -> tuple[float, float]:
    nodes = [n for n in data.get("nodes", []) if all(k in n for k in ("x", "y", "width", "height"))]
    if not nodes:
        return 0.0, 0.0
    return (max(n["x"] + n["width"] for n in nodes) - min(n["x"] for n in nodes) + 2 * PAD,
            max(n["y"] + n["height"] for n in nodes) - min(n["y"] for n in nodes) + 2 * PAD)


def _fits(w: float, h: float, ratio: float) -> bool:
    return w * ratio <= MAX_EXPORT_SIDE and h * ratio <= MAX_EXPORT_SIDE \
        and w * h * ratio * ratio <= MAX_EXPORT_PIXELS


def export_plan(data: dict, scale: float | None) -> tuple[tuple[int, int], float, float]:
    """((window w, h), device pixel ratio, effective scale) for an image export.

    scale None is auto: the largest of AUTO_SCALES that fits, so text comes out
    at least as large as in the editor at 100% and crisp at 2x. An explicit
    scale that doesn't fit is lowered to the largest that does. Only a drawing
    too big for 100% even at 1x goes below it: the window then shrinks and the
    render page zooms the drawing out to fit (effective scale < 1)."""
    w, h = _bounds(data)
    w, h = max(w, MIN_W), max(h, MIN_H)
    wanted = AUTO_SCALES if scale is None else (scale,)
    for ratio in wanted:
        if _fits(w, h, ratio):
            return (round(w), round(h)), ratio, ratio
    for ratio in (4.0, 3.0, 2.0, 1.5, 1.0):
        if ratio < wanted[0] and _fits(w, h, ratio):
            return (round(w), round(h)), ratio, ratio
    zoom = min(MAX_EXPORT_SIDE / w, MAX_EXPORT_SIDE / h, (MAX_EXPORT_PIXELS / (w * h)) ** 0.5)
    return (int(w * zoom), int(h * zoom)), 1.0, zoom


def page_url(base: str, canvas_id: str, token: str, node_ids: list[str] | None,
             export: bool = False) -> str:
    q = {"canvas": canvas_id, "t": token}
    if node_ids:
        q["focus"] = ",".join(node_ids)
    if export:
        q["export"] = "1"
    return f"{base.rstrip('/')}/render?{urlencode(q)}"


class RenderError(Exception):
    pass


def screenshot(browserless_url: str, url: str, size: tuple[int, int],
               timeout: float = 30.0, ratio: float = 1.0) -> bytes:
    """PNG of `url` from browserless v2's /screenshot API. v2 rejects any key
    it doesn't know with a 400 ("must NOT have additional properties"), so
    this must stay in v2's shape: v1's `waitFor` is `waitForSelector` here."""
    body = {
        "url": url,
        "viewport": {"width": size[0], "height": size[1], "deviceScaleFactor": ratio},
        "gotoOptions": {"waitUntil": "networkidle0", "timeout": int(timeout * 1000)},
        "waitForSelector": {"selector": READY, "timeout": int(timeout * 1000)},
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

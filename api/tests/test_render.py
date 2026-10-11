"""render_canvas: tickets, the render view's data routes and the MCP tool."""

from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from nodewright import render
from nodewright.main import create_app
from nodewright.storage import MemoryStore

from .conftest import H, FakeProvider, sign_in
from .test_editor import PNG
from .test_phase2 import first_canvas, make_token

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture
def rig(settings, monkeypatch):
    s = replace(settings, browserless_url="http://browserless:3000",
                render_base_url="http://nodewright.internal")
    provider = FakeProvider(s)
    app = create_app(s, provider, store=MemoryStore())
    web = sign_in(app, provider, "alice")
    browser = TestClient(app)  # no cookie, like the headless browser
    shots = []

    def fake_screenshot(base, url, size, timeout=30.0):
        parts = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        assert base == "http://browserless:3000"
        assert url.startswith("http://nodewright.internal/render?")
        page = browser.get(f"/api/render/{q['canvas']}", params={"t": q["t"]})
        shots.append({"q": q, "size": size, "page": page})
        return FAKE_PNG

    monkeypatch.setattr(render, "screenshot", fake_screenshot)
    tok = make_token(web)["token"]

    def call(**args):
        r = mcp_http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": "render_canvas", "arguments": args}},
                      headers={"Authorization": f"Bearer {tok}",
                               "Accept": "application/json, text/event-stream"})
        assert r.status_code == 200, r.text
        return r.json()["result"]

    with TestClient(app) as mcp_http:
        yield app, web, browser, shots, call


def test_render_canvas_returns_png_via_one_time_ticket(rig):
    app, web, browser, shots, call = rig
    ws, tab = first_canvas(web)
    doc = {"nodes": [{"id": "a", "type": "text", "text": "A", "x": 0, "y": 0, "width": 2000,
                      "height": 100}], "edges": []}
    assert web.put(f"/api/canvases/{tab['id']}", json={"base_revision": 1, "data": doc},
                   headers=H).status_code == 200
    res = call(canvas_id=tab["id"])
    assert not res.get("isError"), res
    img, text = res["content"]
    assert img["type"] == "image" and img["mimeType"] == "image/png"
    import base64
    assert base64.b64decode(img["data"]) == FAKE_PNG
    assert "revision 2" in text["text"]
    shot = shots[0]
    page = shot["page"]
    assert page.status_code == 200 and page.json()["data"] == doc
    assert [t["id"] for t in page.json()["tabs"]] == [tab["id"]]
    # 2080 px wide scaled to fit 1600, aspect kept, floor on the height.
    assert shot["size"] == (1600, 320)
    # The ticket is gone once the shot is taken.
    r = browser.get(f"/api/render/{tab['id']}", params={"t": shot["q"]["t"]})
    assert r.status_code == 404


def test_render_ticket_is_scoped_to_its_canvas_and_workspace(rig):
    app, web, browser, shots, call = rig
    ws, tab = first_canvas(web)
    att = web.post(f"/api/workspaces/{ws['id']}/attachments", content=PNG,
                   headers={**H, "Content-Type": "image/png", "X-Filename": "x.png"}).json()
    other_ws = web.post("/api/workspaces", json={"name": "other"}, headers=H).json()
    other_att = web.post(f"/api/workspaces/{other_ws['id']}/attachments", content=PNG,
                         headers={**H, "Content-Type": "image/png", "X-Filename": "y.png"}).json()
    t = app.state.tickets.issue(tab["id"], ws["id"])
    assert browser.get(f"/api/render/{tab['id']}/attachments/{att['id']}",
                       params={"t": t}).content == PNG
    assert browser.get(f"/api/render/{tab['id']}/attachments/{other_att['id']}",
                       params={"t": t}).status_code == 404
    other_tab = web.get(f"/api/workspaces/{other_ws['id']}/canvases").json()[0]
    assert browser.get(f"/api/render/{other_tab['id']}", params={"t": t}).status_code == 404
    assert browser.get(f"/api/render/{tab['id']}", params={"t": "nope"}).status_code == 404
    assert browser.get(f"/api/render/{tab['id']}").status_code == 404


def test_render_canvas_checks_access_and_node_ids(rig):
    app, web, browser, shots, call = rig
    ws, tab = first_canvas(web)
    assert call(canvas_id="missing")["isError"]
    res = call(canvas_id=tab["id"], node_ids=["ghost"])
    assert res["isError"] and "no such nodes" in res["content"][0]["text"]
    assert shots == []


def test_render_canvas_tool_absent_without_browserless(app_and_provider):
    app, provider = app_and_provider
    web = sign_in(app, provider, "alice")
    tok = make_token(web)["token"]
    with TestClient(app) as http:
        r = http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                      headers={"Authorization": f"Bearer {tok}",
                               "Accept": "application/json, text/event-stream"})
    assert "render_canvas" not in [t["name"] for t in r.json()["result"]["tools"]]


def test_viewport_sizes():
    assert render.viewport({"nodes": []}) == (render.MIN_W, render.MIN_H)
    n = lambda i, x, y, w, h: {"id": i, "x": x, "y": y, "width": w, "height": h}  # noqa: E731
    assert render.viewport({"nodes": [n("a", 0, 0, 800, 600)]}) == (880, 680)
    assert render.viewport({"nodes": [n("a", 0, 0, 160, 60), n("b", 5000, 5000, 160, 60)]},
                           ["a"]) == (render.MIN_W, render.MIN_H)

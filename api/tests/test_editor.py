"""Phase 3 (editor): style extensions, templates, attachments, links."""

import pytest

from nodewright import canvas_format, ops

from .test_phase2 import first_canvas, mcp  # noqa: F401  (fixture)


def doc():
    return {"nodes": [], "edges": []}


# --- style extensions --------------------------------------------------------

def test_style_attributes_must_be_strings_but_values_are_open():
    d = {"nodes": [{"id": "a", "type": "text", "text": "", "x": 0, "y": 0, "width": 9, "height": 9,
                    "styleAttributes": {"shape": "some-future-shape", "x": None}}], "edges": []}
    canvas_format.validate(d)
    d["nodes"][0]["styleAttributes"] = {"shape": 3}
    with pytest.raises(canvas_format.CanvasError):
        canvas_format.validate(d)
    d["nodes"][0]["styleAttributes"] = "diamond"
    with pytest.raises(canvas_format.CanvasError):
        canvas_format.validate(d)


def test_agent_styles_are_checked_and_shapes_grow():
    d = doc()
    ops.add_elements([{"id": "q", "text": "Ready?", "styleAttributes": {"shape": "diamond"}},
                      {"id": "p", "text": "Ready?"}],
                     [{"fromNode": "q", "toNode": "p",
                       "styleAttributes": {"path": "short-dashed", "lineWidth": 4, "arrow": None}}])(d)
    by = {n["id"]: n for n in d["nodes"]}
    q, p = by["q"], by["p"]
    assert q["styleAttributes"] == {"shape": "diamond"}
    assert q["width"] > p["width"] and q["height"] > p["height"]
    assert d["edges"][0]["styleAttributes"] == {"path": "short-dashed", "lineWidth": "4"}
    canvas_format.validate(d)

    with pytest.raises(ops.OpError, match="shape must be one of"):
        ops.add_elements([{"text": "x", "styleAttributes": {"shape": "hexagon"}}], [])(doc())
    with pytest.raises(ops.OpError, match="unknown key"):
        ops.add_elements([{"text": "x", "styleAttributes": {"path": "dotted"}}], [])(doc())


def test_agent_edges_take_a_corner_radius():
    d = doc()
    ops.add_elements([{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                     [{"fromNode": "a", "toNode": "b",
                       "styleAttributes": {"pathfindingMethod": "square", "cornerRadius": 16}}])(d)
    assert d["edges"][0]["styleAttributes"] == {"pathfindingMethod": "square", "cornerRadius": "16"}
    with pytest.raises(ops.OpError, match="cornerRadius must be one of"):
        ops.add_elements([{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                         [{"fromNode": "a", "toNode": "b",
                           "styleAttributes": {"cornerRadius": "7"}}])(doc())


def test_update_merges_style_attributes():
    d = doc()
    ops.add_elements([{"id": "a", "text": "A", "styleAttributes": {"shape": "pill",
                                                                   "border": "dashed"}}], [])(d)
    d["nodes"][0]["styleAttributes"]["future"] = "kept"
    ops.update_elements([{"id": "a", "set": {"styleAttributes": {"shape": "database",
                                                                 "border": None}}}])(d)
    assert d["nodes"][0]["styleAttributes"] == {"shape": "database", "future": "kept"}
    with pytest.raises(ops.OpError):
        ops.update_elements([{"id": "a", "set": {"styleAttributes": {"shape": "star"}}}])(d)
    ops.update_elements([{"id": "a", "set": {"styleAttributes": {"shape": None, "future": None}}}])(d)
    assert "styleAttributes" not in d["nodes"][0]


def test_mcp_documents_styles(mcp):  # noqa: F811
    m, _ = mcp
    tools = {t["name"]: t for t in m.rpc("tools/list").json()["result"]["tools"]}
    schema = str(tools["add_elements"]["inputSchema"])
    assert "predefined-process" in schema and "short-dashed" in schema


# --- templates ---------------------------------------------------------------

H = {"X-Nodewright": "1"}


def test_builtin_templates_are_valid_and_instantiate_fresh():
    from nodewright import templates
    kinds = {t["kind"] for t in templates.BUILTIN.values()}
    assert kinds == {"stencil", "fragment", "page"}
    for t in templates.BUILTIN.values():
        canvas_format.validate(t["data"])
        if t["data"]["nodes"]:
            assert min(n["x"] for n in t["data"]["nodes"]) == 0
            assert min(n["y"] for n in t["data"]["nodes"]) == 0
    src = templates.BUILTIN["builtin:yes-no"]["data"]
    a = templates.instantiate(src, 100, 200, set())
    b = templates.instantiate(src, 0, 0, set())
    assert {n["id"] for n in a["nodes"]}.isdisjoint({n["id"] for n in b["nodes"]})
    assert a["nodes"][0]["x"] == src["nodes"][0]["x"] + 100
    assert {e["fromNode"] for e in a["edges"]} <= {n["id"] for n in a["nodes"]}
    assert src["nodes"][0]["id"] == "q"  # the source is untouched


def test_user_templates_and_default_page(client):
    r = client.get("/api/templates")
    assert r.json()["default_page"] == "builtin:blank"
    page = {"nodes": [{"id": "t", "type": "text", "text": "Title", "x": 400, "y": 300,
                       "width": 200, "height": 60}], "edges": []}
    r = client.post("/api/templates", json={"name": "My page", "kind": "page", "data": page},
                    headers=H)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["data"]["nodes"][0]["x"] == 0 and t["data"]["nodes"][0]["y"] == 0
    bad = client.post("/api/templates", json={"name": "x", "kind": "stencil",
                                              "data": {"nodes": [], "edges": []}}, headers=H)
    assert bad.status_code == 422
    assert client.put("/api/templates-default-page", json={"template": "builtin:process"},
                      headers=H).status_code == 422
    assert client.put("/api/templates-default-page", json={"template": t["id"]},
                      headers=H).status_code == 200

    ws, _ = first_canvas(client)
    tab = client.post(f"/api/workspaces/{ws['id']}/canvases", json={"name": "New"},
                      headers=H).json()
    data = client.get(f"/api/canvases/{tab['id']}").json()["data"]
    assert [n["text"] for n in data["nodes"]] == ["Title"] and data["nodes"][0]["id"] != "t"
    tab = client.post(f"/api/workspaces/{ws['id']}/canvases",
                      json={"name": "Flow", "template": "builtin:flowchart"}, headers=H).json()
    assert len(client.get(f"/api/canvases/{tab['id']}").json()["data"]["edges"]) == 5
    assert client.post(f"/api/workspaces/{ws['id']}/canvases",
                       json={"name": "x", "template": "nope"}, headers=H).status_code == 404

    client.delete(f"/api/templates/{t['id']}", headers=H)
    assert client.get("/api/templates").json()["default_page"] == "builtin:blank"


def test_templates_are_private(app_and_provider, client):
    from .conftest import sign_in
    app, provider = app_and_provider
    t = client.post("/api/templates", json={"name": "Mine", "kind": "stencil", "data": {
        "nodes": [{"id": "a", "type": "text", "text": "", "x": 0, "y": 0, "width": 9,
                   "height": 9}], "edges": []}}, headers=H).json()
    bob = sign_in(app, provider, "bob")
    assert all(x["id"] != t["id"] for x in bob.get("/api/templates").json()["templates"])
    assert bob.delete(f"/api/templates/{t['id']}", headers=H).status_code == 404
    ws, _ = first_canvas(bob)
    assert bob.post(f"/api/workspaces/{ws['id']}/canvases",
                    json={"name": "x", "template": t["id"]}, headers=H).status_code == 404


def test_mcp_templates(mcp):  # noqa: F811
    m, web = mcp
    tab = m.call("list_workspaces")["workspaces"][0]["canvases"][0]
    listed = m.call("list_templates")
    assert any(t["id"] == "builtin:decision" for t in listed["templates"])
    one = m.call("apply_template", canvas_id=tab["id"], template_id="builtin:three-tier")
    assert len(one["node_ids"]) == 3 and one["at"] == [0, 0]
    two = m.call("apply_template", canvas_id=tab["id"], template_id="builtin:three-tier")
    assert two["at"][0] > 600
    saved = m.call("save_template", canvas_id=tab["id"], node_ids=one["node_ids"][:2],
                   name="Client+API")
    assert saved["nodes"] == 2
    tpl = [t for t in web.get("/api/templates").json()["templates"] if t["id"] == saved["template_id"]][0]
    assert len(tpl["data"]["edges"]) == 1
    assert "no template" in m.error("apply_template", canvas_id=tab["id"], template_id="x")
    c = m.call("create_canvas", workspace_id=m.call("list_workspaces")["workspaces"][0]["id"],
               name="Arch", template="builtin:architecture")
    assert len(m.call("get_canvas", canvas_id=c["canvas_id"])["data"]["nodes"]) == 9


# --- cross-canvas links --------------------------------------------------------

def test_mcp_tab_links(mcp):  # noqa: F811
    m, _ = mcp
    ws = m.call("list_workspaces")["workspaces"][0]
    tab = ws["canvases"][0]
    detail = m.call("create_canvas", workspace_id=ws["id"], name="Detail", template="builtin:blank")
    m.call("add_elements", canvas_id=detail["canvas_id"], nodes=[{"id": "db", "text": "DB"}])
    m.call("add_elements", canvas_id=tab["id"],
           nodes=[{"id": "go", "type": "file", "file": "Detail.canvas", "subpath": "#db"}])
    node = [n for n in m.call("get_canvas", canvas_id=tab["id"])["data"]["nodes"] if n["id"] == "go"][0]
    assert node["file"] == "Detail.canvas" and node["subpath"] == "#db"
    assert node["width"] > 0 and node["height"] > 0
    tools = {t["name"]: t for t in m.rpc("tools/list").json()["result"]["tools"]}
    assert "<tab name>.canvas" in str(tools["add_elements"]["inputSchema"])


# --- attachments ---------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64


@pytest.fixture
def files(settings, tmp_path):
    from dataclasses import replace

    from nodewright.main import create_app
    from nodewright.storage import MemoryStore

    from .conftest import FakeProvider, sign_in

    st = MemoryStore()
    s2 = replace(settings, max_attachment_bytes=1000)
    provider = FakeProvider(s2)
    app = create_app(s2, provider, store=st)
    return app, provider, st, sign_in


def test_attachments_upload_serve_and_delete(files):
    app, provider, st, sign_in = files
    alice = sign_in(app, provider, "alice")
    ws = alice.get("/api/workspaces").json()[0]["id"]
    up = lambda body, name, ctype="application/octet-stream": alice.post(  # noqa: E731
        f"/api/workspaces/{ws}/attachments", content=body,
        headers={**H, "Content-Type": ctype, "X-Filename": name})

    assert alice.get("/api/config").json()["attachments"] is True
    # Declared as text, but the bytes are a PNG: it is an image.
    img = up(PNG, "diagram%20%E2%9C%93.png", "text/html").json()
    assert img["image"] and img["content_type"] == "image/png"
    assert img["file"] == f"attachments/{img['id']}/diagram ✓.png"
    r = alice.get(img["url"])
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"].startswith("inline;")
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"

    # Anything else downloads, whatever it claims to be; names are sanitised.
    html = up(b"<script>alert(1)</script>", "..%2F..%2Fevil.html", "text/html").json()
    assert not html["image"] and html["name"] == "evil.html"
    r = alice.get(html["url"])
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment;")
    svg = up(b"<svg xmlns='http://www.w3.org/2000/svg'/>", "x.svg", "image/svg+xml").json()
    assert not svg["image"]

    assert up(b"x" * 1001, "big.bin").status_code == 413
    assert up(b"", "empty.bin").status_code == 422
    assert alice.post(f"/api/workspaces/{ws}/attachments", content=PNG).status_code == 403

    listed = alice.get(f"/api/workspaces/{ws}/attachments").json()["attachments"]
    assert {a["id"] for a in listed} == {img["id"], html["id"], svg["id"]}

    bob = sign_in(app, provider, "bob")
    assert bob.get(img["url"]).status_code == 404
    assert bob.get(f"/api/workspaces/{ws}/attachments").status_code == 404
    assert bob.post(f"/api/workspaces/{ws}/attachments", content=PNG, headers=H).status_code == 404

    assert alice.delete(img["url"], headers=H).status_code == 204
    assert alice.get(img["url"]).status_code == 404
    assert len(st.objects) == 2
    assert alice.delete(f"/api/workspaces/{ws}", headers=H).status_code == 204
    assert st.objects == {}


def test_attachments_off_without_a_store(client):
    assert client.get("/api/config").json()["attachments"] is False
    ws = client.get("/api/workspaces").json()[0]["id"]
    r = client.post(f"/api/workspaces/{ws}/attachments", content=PNG, headers=H)
    assert r.status_code == 404


def test_attachment_names_and_sniffing():
    from nodewright import attachments as at
    assert at.clean_name("C:\\Users\\me\\photo.jpg") == "photo.jpg"
    assert at.clean_name('a<b>"c".txt') == "abc.txt"
    assert at.clean_name("...") == "file" and at.clean_name(None) == "file"
    assert at.sniff(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp"
    assert at.sniff(b"\0\0\0\x1cftypavif") == "image/avif"
    assert at.content_type(b"%PDF-1.7", "application/pdf; x=y") == "application/pdf"
    assert at.content_type(b"x", "not a type") == "application/octet-stream"
    assert at.attachment_id("attachments/" + "a" * 32 + "/x.png") == "a" * 32
    assert at.attachment_id("notes/x.png") is None


def test_mcp_lists_attachments(mcp):  # noqa: F811
    m, web = mcp
    ws = m.call("list_workspaces")["workspaces"][0]["id"]
    assert m.call("list_attachments", workspace_id=ws)["attachments"] == []


def test_unused_attachments_are_swept(files):
    from datetime import timedelta

    from sqlalchemy import update

    from nodewright.models import Attachment, CanvasRevision, utcnow

    app, provider, st, sign_in = files
    alice = sign_in(app, provider, "alice")
    ws = alice.get("/api/workspaces").json()[0]["id"]
    cid = alice.get(f"/api/workspaces/{ws}/canvases").json()[0]["id"]
    up = lambda name: alice.post(f"/api/workspaces/{ws}/attachments", content=PNG,  # noqa: E731
                                 headers={**H, "X-Filename": name}).json()
    used, history, unused, fresh = up("used.png"), up("history.png"), up("unused.png"), up("new.png")
    node = lambda a: {"id": a["id"][:8], "type": "file", "file": a["file"],  # noqa: E731
                      "x": 0, "y": 0, "width": 100, "height": 100}

    def save(nodes):
        rev = alice.get(f"/api/canvases/{cid}").json()["revision"]
        r = alice.put(f"/api/canvases/{cid}", headers=H,
                      json={"base_revision": rev, "data": {"nodes": nodes, "edges": []}})
        assert r.status_code == 200, r.text

    save([node(used), node(history)])
    save([node(used)])

    db, now = app.state.db, utcnow()
    with db.session() as s:
        s.execute(update(Attachment).where(Attachment.id != fresh["id"])
                  .values(created_at=now - timedelta(days=40)))
    assert app.state.sweep_attachments() == 1          # only "unused"; history is recent
    ids = {a["id"] for a in alice.get(f"/api/workspaces/{ws}/attachments").json()["attachments"]}
    assert ids == {used["id"], history["id"], fresh["id"]}

    with db.session() as s:                            # the revision ages out of the window
        s.execute(update(CanvasRevision).values(created_at=now - timedelta(days=40)))
    assert app.state.sweep_attachments() == 1
    ids = {a["id"] for a in alice.get(f"/api/workspaces/{ws}/attachments").json()["attachments"]}
    assert ids == {used["id"], fresh["id"]}
    assert len(st.objects) == 2

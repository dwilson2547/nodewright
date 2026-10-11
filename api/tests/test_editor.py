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

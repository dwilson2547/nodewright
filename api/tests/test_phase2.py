"""Phase 2: access checks, tokens, leases, live events, ops, layout and MCP."""

import json

import pytest
from fastapi.testclient import TestClient

from nodewright import layout, ops
from nodewright.models import WorkspaceMember

from .conftest import H, sign_in


def first_canvas(client):
    ws = client.get("/api/workspaces").json()[0]
    return ws, client.get(f"/api/workspaces/{ws['id']}/canvases").json()[0]


def make_token(client, name="laptop"):
    r = client.post("/api/tokens", json={"name": name}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()


class Mcp:
    def __init__(self, http: TestClient, token: str):
        self.http, self.token, self.n = http, token, 0

    def rpc(self, method, params=None, token=None):
        self.n += 1
        return self.http.post("/mcp", json={"jsonrpc": "2.0", "id": self.n, "method": method,
                                            "params": params or {}},
                              headers={"Authorization": f"Bearer {token or self.token}",
                                       "Accept": "application/json, text/event-stream"})

    def call(self, tool, **args):
        r = self.rpc("tools/call", {"name": tool, "arguments": args})
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        if res.get("isError"):
            raise AssertionError(res["content"][0]["text"])
        if res.get("structuredContent") is not None:
            sc = res["structuredContent"]
            return sc.get("result", sc) if set(sc) == {"result"} else sc
        return json.loads(res["content"][0]["text"])

    def error(self, tool, **args) -> str:
        r = self.rpc("tools/call", {"name": tool, "arguments": args})
        res = r.json()["result"]
        assert res.get("isError"), res
        return res["content"][0]["text"]


@pytest.fixture
def mcp(app_and_provider):
    app, provider = app_and_provider
    web = sign_in(app, provider, "alice")
    tok = make_token(web)["token"]
    with TestClient(app) as http:
        yield Mcp(http, tok), web


# --- access -------------------------------------------------------------------

def test_member_roles_are_enforced(app_and_provider):
    app, provider = app_and_provider
    alice, bob = sign_in(app, provider, "alice"), sign_in(app, provider, "bob")
    ws, tab = first_canvas(alice)
    assert bob.get(f"/api/canvases/{tab['id']}").status_code == 404
    bob_id = bob.get("/api/me").json()["id"]
    with app.state.db.session() as s:
        s.add(WorkspaceMember(workspace_id=ws["id"], user_id=bob_id, role="viewer"))
    assert ws["id"] in [w["id"] for w in bob.get("/api/workspaces").json()]
    got = bob.get(f"/api/canvases/{tab['id']}").json()
    assert got["can_edit"] is False
    r = bob.put(f"/api/canvases/{tab['id']}", json={"base_revision": 1, "data": got["data"]},
                headers=H)
    assert r.status_code == 403
    assert bob.delete(f"/api/workspaces/{ws['id']}", headers=H).status_code == 403
    with app.state.db.session() as s:
        m = s.query(WorkspaceMember).one()
        m.role = "editor"
    r = bob.put(f"/api/canvases/{tab['id']}", json={"base_revision": 1, "data": got["data"]},
                headers=H)
    assert r.status_code == 200
    assert bob.delete(f"/api/workspaces/{ws['id']}", headers=H).status_code == 403


# --- tokens -------------------------------------------------------------------

def test_tokens_are_shown_once_and_revocable(client):
    t = make_token(client)
    assert t["token"].startswith("nwp_") and t["mcp_url"] == "http://testserver/mcp"
    listed = client.get("/api/tokens").json()
    assert [x["id"] for x in listed] == [t["id"]] and "token" not in listed[0]
    assert client.delete(f"/api/tokens/{t['id']}", headers=H).status_code == 204
    assert client.get("/api/tokens").json() == []


def test_token_is_not_a_rest_credential(app_and_provider):
    app, provider = app_and_provider
    tok = make_token(sign_in(app, provider, "alice"))["token"]
    r = TestClient(app).get("/api/workspaces", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


# --- style guide --------------------------------------------------------------

def test_style_guide_default_set_and_reset(client):
    g = client.get("/api/style-guide").json()
    assert g["is_default"] and g["text"].startswith("# Diagram style guide")
    assert client.put("/api/style-guide", json={"text": "use LR"}, headers=H).json() == {
        "text": "use LR", "is_default": False}
    assert client.get("/api/style-guide").json()["text"] == "use LR"
    assert client.put("/api/style-guide", json={"text": " "}, headers=H).json()["is_default"]


# --- leases -------------------------------------------------------------------

def save(c, tab_id, rev, data, client_id):
    return c.put(f"/api/canvases/{tab_id}", json={"base_revision": rev, "data": data},
                 headers={**H, "X-Nodewright-Client": client_id})


def test_ui_save_takes_lease_and_other_tab_gets_423(client):
    _, tab = first_canvas(client)
    doc = {"nodes": [], "edges": []}
    assert save(client, tab["id"], 1, doc, "tab1").status_code == 200
    r = save(client, tab["id"], 2, doc, "tab2")
    assert r.status_code == 423 and r.json()["lease"]["label"] == "alice"
    assert save(client, tab["id"], 2, doc, "tab1").status_code == 200
    r = client.post(f"/api/canvases/{tab['id']}/lease?force=true",
                    headers={**H, "X-Nodewright-Client": "tab2"})
    assert r.status_code == 200
    assert save(client, tab["id"], 3, doc, "tab2").status_code == 200
    assert save(client, tab["id"], 4, doc, "tab1").status_code == 423
    assert client.delete(f"/api/canvases/{tab['id']}/lease",
                         headers={**H, "X-Nodewright-Client": "tab2"}).json()["released"]
    assert client.get(f"/api/canvases/{tab['id']}").json()["lease"] is None


def test_agent_lock_blocks_ui_until_released(mcp):
    m, web = mcp
    _, tab = first_canvas(web)
    lock = m.call("lock_canvas", canvas_id=tab["id"], minutes=5)["lock"]
    assert lock["kind"] == "agent" and "alice's agent (laptop)" == lock["label"]
    r = save(web, tab["id"], 1, {"nodes": [], "edges": []}, "tab1")
    assert r.status_code == 423
    assert m.call("unlock_canvas", canvas_id=tab["id"]) == {"released": True}
    assert save(web, tab["id"], 1, {"nodes": [], "edges": []}, "tab1").status_code == 200
    assert "locked" in m.error("add_elements", canvas_id=tab["id"], nodes=[{"text": "x"}])


def test_expired_lease_is_ignored(client, app_and_provider):
    app, _ = app_and_provider
    _, tab = first_canvas(client)
    save(client, tab["id"], 1, {"nodes": [], "edges": []}, "tab1")
    from datetime import timedelta

    from nodewright.models import CanvasLease, utcnow
    with app.state.db.session() as s:
        s.get(CanvasLease, tab["id"]).expires_at = utcnow() - timedelta(seconds=1)
    assert save(client, tab["id"], 2, {"nodes": [], "edges": []}, "tab2").status_code == 200


# --- events -------------------------------------------------------------------

def test_events_publish_after_commit_only(app_and_provider):
    import asyncio

    from nodewright import events
    app, _ = app_and_provider
    db, broker = app.state.db, app.state.broker

    async def go():
        q = broker.subscribe("c1")
        try:
            with db.session() as s:
                events.queue(s, "c1", {"type": "x"})
                raise RuntimeError
        except RuntimeError:
            pass
        with db.session() as s:
            events.queue(s, "c1", {"type": "y"})
        await asyncio.sleep(0)
        got = []
        while not q.empty():
            got.append(q.get_nowait())
        broker.unsubscribe("c1", q)
        return got

    assert asyncio.run(go()) == [{"type": "y"}]
    assert broker.subscriber_count("c1") == 0


# --- layout and ops -----------------------------------------------------------

def test_layered_layout_orders_by_edges_on_grid():
    sizes = {k: (160, 60) for k in "abcd"}
    pos, (w, h) = layout.layered(list("abcd"), sizes, [("a", "b"), ("a", "c"), ("b", "d"),
                                                       ("c", "d"), ("d", "a")])
    assert pos["a"][1] < pos["b"][1] == pos["c"][1] < pos["d"][1]
    assert pos["b"][0] != pos["c"][0]
    assert all(x % 20 == 0 and y % 20 == 0 for x, y in pos.values())
    lr, _ = layout.layered(list("ab"), sizes, [("a", "b")], "LR")
    assert lr["a"][0] < lr["b"][0] and lr["a"][1] == lr["b"][1]


def test_add_elements_places_groups_and_children():
    data = {"nodes": [], "edges": []}
    out = ops.add_elements(
        [{"id": "g", "type": "group", "label": "VPC"},
         {"id": "api", "text": "API", "group": "g"},
         {"id": "db", "text": "Postgres", "group": "g"},
         {"id": "user", "text": "User"}],
        [{"fromNode": "user", "toNode": "api"}, {"fromNode": "api", "toNode": "db"}])(data)
    assert out["node_ids"] == ["g", "api", "db", "user"] and len(out["edge_ids"]) == 2
    n = {x["id"]: x for x in data["nodes"]}
    assert data["nodes"][0]["id"] == "g"
    for k in ("api", "db"):
        assert ops._inside(n[k], n["g"])
    assert not ops._inside(n["user"], n["g"])
    assert n["api"]["y"] < n["db"]["y"]
    assert "group" not in n["api"]
    from nodewright import canvas_format
    canvas_format.validate(data)


def test_add_elements_anchors_new_block_below_what_it_connects_to():
    data = {"nodes": [{"id": "a", "type": "text", "text": "A", "x": 1000, "y": 1000,
                       "width": 200, "height": 60}], "edges": []}
    ops.add_elements([{"id": "b", "text": "B"}], [{"fromNode": "a", "toNode": "b"}])(data)
    b = next(x for x in data["nodes"] if x["id"] == "b")
    assert b["y"] >= 1060 + 60 and abs((b["x"] + b["width"] / 2) - 1100) <= 20


def test_update_and_delete_elements():
    data = {"nodes": [{"id": "a", "type": "text", "text": "A", "x": 0, "y": 0, "width": 200,
                       "height": 60, "color": "1"},
                      {"id": "b", "type": "text", "text": "B", "x": 0, "y": 200, "width": 200,
                       "height": 60}],
            "edges": [{"id": "e", "fromNode": "a", "toNode": "b"}]}
    ops.update_elements([{"id": "a", "set": {"text": "x" * 80, "color": None}, "fit": True},
                         {"id": "e", "set": {"label": "calls"}}])(data)
    assert "color" not in data["nodes"][0] and data["nodes"][0]["width"] == 360
    assert data["edges"][0]["label"] == "calls"
    with pytest.raises(ops.OpError):
        ops.update_elements([{"id": "a", "set": {"id": "z"}}])(data)
    assert ops.delete_elements(["a"])(data) == {"deleted": 1, "edges_removed": 1}


def test_relayout_moves_group_contents_together():
    data = {"nodes": [{"id": "g", "type": "group", "x": 0, "y": 0, "width": 1000, "height": 1000},
                      {"id": "a", "type": "text", "text": "A", "x": 500, "y": 900, "width": 160,
                       "height": 60},
                      {"id": "b", "type": "text", "text": "B", "x": 40, "y": 40, "width": 160,
                       "height": 60}],
            "edges": [{"id": "e", "fromNode": "a", "toNode": "b"}]}
    ops.relayout(None)(data)
    n = {x["id"]: x for x in data["nodes"]}
    assert ops._inside(n["a"], n["g"]) and ops._inside(n["b"], n["g"])
    assert n["a"]["y"] < n["b"]["y"] and n["g"]["width"] < 1000


# --- MCP over HTTP ------------------------------------------------------------

def test_mcp_requires_a_token(app_and_provider):
    app, _ = app_and_provider
    with TestClient(app) as http:
        r = http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer")
        r = Mcp(http, "nwp_nope").rpc("tools/list")
        assert r.status_code == 401


def test_mcp_lists_tools(mcp):
    m, _ = mcp
    r = m.rpc("tools/list")
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert {"list_workspaces", "get_canvas", "add_elements", "update_elements",
            "delete_elements", "layout", "lock_canvas", "unlock_canvas",
            "get_style_guide", "create_canvas", "create_workspace"} <= names


def test_mcp_builds_a_diagram_the_ui_can_load(mcp):
    m, web = mcp
    ws = m.call("list_workspaces")[0]
    tab = ws["canvases"][0]
    assert "style guide" in m.call("get_style_guide")["style_guide"].lower()
    out = m.call("add_elements", canvas_id=tab["id"],
                 nodes=[{"id": "web", "text": "## Web"}, {"id": "api", "text": "API"}],
                 edges=[{"fromNode": "web", "toNode": "api", "label": "REST"}], direction="LR")
    assert out["revision"] == 2 and out["node_ids"] == ["web", "api"]
    got = web.get(f"/api/canvases/{tab['id']}").json()
    assert got["revision"] == 2 and len(got["data"]["nodes"]) == 2
    assert got["lease"]["kind"] == "agent"
    revs = web.get(f"/api/canvases/{tab['id']}/revisions").json()
    assert revs[0]["source"] == "mcp"
    assert "already used" in m.error("add_elements", canvas_id=tab["id"],
                                     nodes=[{"id": "web", "text": "dup"}])
    m.call("layout", canvas_id=tab["id"], direction="TB")
    assert m.call("get_canvas", canvas_id=tab["id"])["revision"] == 3


def test_mcp_cannot_touch_other_users_canvases(app_and_provider, mcp):
    app, provider = app_and_provider
    m, _ = mcp
    _, bobs = first_canvas(sign_in(app, provider, "bob"))
    assert "not found" in m.error("get_canvas", canvas_id=bobs["id"])
    assert "not found" in m.error("add_elements", canvas_id=bobs["id"], nodes=[{"text": "x"}])


def test_mcp_create_workspace_and_canvas(mcp):
    m, web = mcp
    made = m.call("create_workspace", name="Agent work")
    c = m.call("create_canvas", workspace_id=made["workspace_id"], name="Second")
    assert c["url"].endswith(c["canvas_id"])
    tabs = web.get(f"/api/workspaces/{made['workspace_id']}/canvases").json()
    assert [t["name"] for t in tabs] == ["Untitled", "Second"]

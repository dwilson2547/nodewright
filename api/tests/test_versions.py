"""Versions (design §14): history listing, named versions and restore."""

from .conftest import H, sign_in
from .test_phase2 import Mcp, first_canvas, make_token, mcp  # noqa: F401


def doc(text):
    return {"nodes": [{"id": "a", "type": "text", "text": text, "x": 0, "y": 0,
                       "width": 100, "height": 60}], "edges": []}


def saves(client, url, n, start=1):
    for i in range(n):
        r = client.put(url, json={"base_revision": start + i, "data": doc(f"v{i}")}, headers=H)
        assert r.status_code == 200, r.text


def test_history_names_and_restore(app_and_provider, client):
    app, provider = app_and_provider
    ws, tab = first_canvas(client)
    url = f"/api/canvases/{tab['id']}"
    saves(client, url, 5)  # revisions 2..6, text v0..v4

    h = client.get(url + "/revisions").json()
    assert h["current"] == 6 and not h["more"]
    assert [r["revision"] for r in h["revisions"]] == [6, 5, 4, 3, 2]
    assert h["revisions"][0] | {"created_at": None} == {
        "revision": 6, "source": "ui", "created_at": None, "by": "alice", "label": None,
        "restored_from": None}

    # Paging: `before` continues where the last page stopped.
    p1 = client.get(url + "/revisions?before=4").json()
    assert [r["revision"] for r in p1["revisions"]] == [3, 2]

    # One revision, with its document.
    r3 = client.get(url + "/revisions/3").json()
    assert r3["data"]["nodes"][0]["text"] == "v1" and r3["by"] == "alice"
    assert client.get(url + "/revisions/99").status_code == 404

    # Naming: trimmed, renamable, clearable; only named ones with ?named=1.
    named = client.patch(url + "/revisions/3", json={"label": "  first draft "}, headers=H).json()
    assert named["label"] == "first draft"
    client.patch(url + "/revisions/5", json={"label": "review"}, headers=H)
    assert [r["label"] for r in client.get(url + "/revisions?named=true").json()["revisions"]] == [
        "review", "first draft"]
    client.patch(url + "/revisions/5", json={"label": ""}, headers=H)
    assert [r["revision"] for r in client.get(url + "/revisions?named=true").json()["revisions"]] == [3]
    assert client.patch(url + "/revisions/99", json={"label": "x"}, headers=H).status_code == 404

    # Restore is a normal save that records where it came from.
    r = client.put(url, json={"base_revision": 6, "data": r3["data"], "restored_from": 3}, headers=H)
    assert r.status_code == 200 and r.json()["revision"] == 7
    top = client.get(url + "/revisions").json()["revisions"][0]
    assert top["source"] == "restore" and top["restored_from"] == 3
    assert client.get(url).json()["data"]["nodes"][0]["text"] == "v1"
    assert client.put(url, json={"base_revision": 7, "data": doc("x"), "restored_from": "3"},
                      headers=H).status_code == 400

    # A viewer reads history but can't name versions.
    bob = sign_in(app, provider, "bob")
    client.post(f"/api/workspaces/{ws['id']}/members", json={"username": "bob", "role": "viewer"},
                headers=H)
    assert bob.get(url + "/revisions").status_code == 200
    assert bob.get(url + "/revisions/3").status_code == 200
    assert bob.patch(url + "/revisions/3", json={"label": "mine"}, headers=H).status_code == 403
    # Strangers see nothing.
    carol = sign_in(app, provider, "carol")
    assert carol.get(url + "/revisions").status_code == 404
    assert carol.get(url + "/revisions/3").status_code == 404


def test_listing_pages(client):
    from nodewright import versions
    from nodewright.models import Canvas
    _, tab = first_canvas(client)
    url = f"/api/canvases/{tab['id']}"
    saves(client, url, 5)
    with client.app.state.db.session() as s:
        c = s.get(Canvas, tab["id"])
        p1 = versions.listing(s, c, limit=2)
        assert [r["revision"] for r in p1["revisions"]] == [6, 5] and p1["more"]
        p3 = versions.listing(s, c, before=3, limit=2)
        assert [r["revision"] for r in p3["revisions"]] == [2] and not p3["more"]


def test_agent_versions(mcp):  # noqa: F811
    m, web = mcp
    tab = m.call("list_workspaces")["workspaces"][0]["canvases"][0]["id"]
    m.call("add_elements", canvas_id=tab, nodes=[{"id": "a", "text": "one"}])
    saved = m.call("save_version", canvas_id=tab, name="before restructure")
    assert saved["revision"] == 2 and saved["label"] == "before restructure"
    m.call("update_elements", canvas_id=tab, updates=[{"id": "a", "set": {"text": "two"}}])
    listed = m.call("list_versions", canvas_id=tab)
    assert listed["current"] == 3 and listed["revisions"][0]["source"] == "mcp"
    assert [r["label"] for r in m.call("list_versions", canvas_id=tab, named_only=True)["revisions"]] == [
        "before restructure"]
    old = m.call("get_canvas", canvas_id=tab, revision=2)
    assert old["revision"] == 2 and old["current_revision"] == 3
    assert old["data"]["nodes"][0]["text"] == "one"
    assert "no revision 42" in m.error("get_canvas", canvas_id=tab, revision=42)
    assert web.get(f"/api/canvases/{tab}/revisions?named=true").json()["revisions"][0]["by"] == "alice"

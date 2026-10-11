import io
import json
import zipfile

from .conftest import H, sign_in

SQUARE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'


def test_icon_library_upload_serve_and_delete(app_and_provider, client):
    listed = client.get("/api/icons").json()
    assert listed["mine"] == [] and len(listed["builtin"]) > 50
    server = next(i for i in listed["builtin"] if i["id"] == "lucide-server")
    assert server["file"] == "icons/lucide-server/Server.svg" and server["tinted"]
    r = client.get(server["url"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in r.headers["content-security-policy"]
    again = client.get(server["url"], headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304

    bad = client.post("/api/icons", json={"name": "x", "svg": SQUARE.replace("<rect", "<script/><rect")},
                      headers=H)
    assert bad.status_code == 422 and "<script>" in bad.json()["detail"]
    ports = [{"id": "a", "side": "left", "at": 0.5}, {"id": "b", "side": "right"}]
    icon = client.post("/api/icons", json={"name": "Resistor", "svg": SQUARE, "tinted": False,
                                           "ports": ports}, headers=H).json()
    assert icon["file"] == f"icons/{icon['id']}/Resistor.svg" and icon["tinted"] is False
    assert icon["ports"][1] == {"id": "b", "side": "right", "at": 0.5}
    # Served by id to anyone, e.g. a share-link viewer; rebuilt, not the uploaded bytes.
    from fastapi.testclient import TestClient
    app, provider = app_and_provider
    anon = TestClient(app).get(icon["url"])
    assert anon.status_code == 200 and anon.text.startswith('<svg xmlns="http://www.w3.org/2000/svg"')

    bob = sign_in(app, provider, "bob")
    assert bob.get("/api/icons").json()["mine"] == []
    assert bob.patch(f"/api/icons/{icon['id']}", json={"name": "x"}, headers=H).status_code == 404
    assert bob.delete(f"/api/icons/{icon['id']}", headers=H).status_code == 404

    r = client.patch(f"/api/icons/{icon['id']}", json={"name": "R1", "tinted": True}, headers=H).json()
    assert r["name"] == "R1" and r["tinted"] and r["ports"] == icon["ports"]
    assert client.patch(f"/api/icons/{icon['id']}", json={"svg": "<html/>"}, headers=H).status_code == 422
    assert client.delete(f"/api/icons/{icon['id']}", headers=H).status_code == 204
    assert client.get(icon["url"]).status_code == 404


def test_icons_on_nodes_and_in_zip_export(client):
    from nodewright import canvas_format, ops
    import pytest
    d = {"nodes": [], "edges": []}
    ops.add_elements([{"id": "s", "text": "API", "icon": "icons/lucide-server/Server.svg",
                       "styleAttributes": {"iconColors": "original"}}], [])(d)
    canvas_format.validate(d)
    with pytest.raises(ops.OpError, match="list_icons"):
        ops.add_elements([{"text": "x", "icon": "../../etc/passwd"}], [])(d)
    with pytest.raises(ops.OpError, match="text node"):
        ops.add_elements([{"type": "group", "icon": "icons/lucide-server/Server.svg"}], [])(d)

    ws = client.get("/api/workspaces").json()[0]["id"]
    tab = client.get(f"/api/workspaces/{ws}/canvases").json()[0]
    assert client.put(f"/api/canvases/{tab['id']}", json={"base_revision": tab["revision"], "data": d},
                      headers=H).status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(client.get(f"/api/workspaces/{ws}/export").content))
    assert "icons/lucide-server/Server.svg" in zf.namelist()
    assert zf.read("icons/lucide-server/Server.svg").startswith(b"<svg")
    assert json.loads(zf.read("Untitled.canvas"))["nodes"][0]["icon"] == "icons/lucide-server/Server.svg"


def test_creator_source_round_trips(client):
    src = {"version": 1, "shapes": [{"kind": "rect", "x": 10, "y": 10, "w": 80, "h": 40}], "pins": []}
    icon = client.post("/api/icons", json={"name": "Box", "svg": SQUARE, "source": src}, headers=H).json()
    assert icon["editable"] is True
    got = client.get(f"/api/icons/{icon['id']}").json()
    assert got["source"] == src
    src["shapes"].append({"kind": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 1})
    client.patch(f"/api/icons/{icon['id']}", json={"source": src, "svg": SQUARE}, headers=H)
    assert len(client.get(f"/api/icons/{icon['id']}").json()["source"]["shapes"]) == 2
    up = client.post("/api/icons", json={"name": "Up", "svg": SQUARE}, headers=H).json()
    assert up["editable"] is False
    assert all(not i["editable"] for i in client.get("/api/icons").json()["builtin"])
    big = {"x": "y" * 300_000}
    assert client.post("/api/icons", json={"name": "Big", "svg": SQUARE, "source": big},
                       headers=H).status_code == 422

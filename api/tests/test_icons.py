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

import io
import json
import zipfile

from .conftest import H
from .test_editor import PNG, files  # noqa: F401  (fixture)


def test_workspace_exports_as_a_zip_with_its_attachments(files):  # noqa: F811
    app, provider, st, sign_in = files
    alice = sign_in(app, provider, "alice")
    ws = alice.get("/api/workspaces").json()[0]["id"]
    up = lambda body, name: alice.post(  # noqa: E731
        f"/api/workspaces/{ws}/attachments", content=body,
        headers={**H, "Content-Type": "application/octet-stream", "X-Filename": name}).json()
    img, unused, lost = up(PNG, "logo.png"), up(b"unused", "unused.bin"), up(PNG, "lost.png")

    first = alice.get(f"/api/workspaces/{ws}/canvases").json()[0]
    doc = {"nodes": [
        {"id": "a", "type": "file", "file": img["file"], "x": 0, "y": 0, "width": 80, "height": 80},
        {"id": "b", "type": "file", "file": lost["file"], "x": 100, "y": 0, "width": 80, "height": 80},
        {"id": "c", "type": "file", "file": "Design: v2.canvas", "x": 200, "y": 0,
         "width": 80, "height": 80}], "edges": []}
    assert alice.put(f"/api/canvases/{first['id']}", json={"base_revision": first["revision"],
                                                          "data": doc}, headers=H).status_code == 200
    for name in ("Design: v2", "Design v2"):
        assert alice.post(f"/api/workspaces/{ws}/canvases", json={"name": name},
                          headers=H).status_code == 201
    st.objects.pop(next(k for k in st.objects if lost["id"] in k))

    r = alice.get(f"/api/workspaces/{ws}/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "My%20workspace.zip" in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(zf.namelist()) == sorted([
        ".nodewright/workspace.json", "Untitled.canvas", "Design v2.canvas",
        "Design v2 (2).canvas", img["file"]])
    assert json.loads(zf.read("Untitled.canvas")) == doc
    assert zf.read(img["file"]) == PNG
    manifest = json.loads(zf.read(".nodewright/workspace.json"))
    assert manifest["workspace"] == "My workspace"
    assert [t["name"] for t in manifest["tabs"]] == ["Untitled", "Design: v2", "Design v2"]
    assert manifest["missing_attachments"] == [lost["id"]]
    assert unused["id"] not in json.dumps(zf.namelist())

    bob = sign_in(app, provider, "bob")
    assert bob.get(f"/api/workspaces/{ws}/export").status_code == 404


def test_export_without_attachment_storage(client):
    ws = client.get("/api/workspaces").json()[0]["id"]
    r = client.get(f"/api/workspaces/{ws}/export")
    assert sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist()) == [
        ".nodewright/workspace.json", "Untitled.canvas"]

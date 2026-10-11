from .conftest import H
from .test_phase2 import mcp  # noqa: F401  (fixture)


def test_folders_nest_file_and_delete(app_and_provider, client):
    from .conftest import sign_in
    ws = client.get("/api/workspaces").json()[0]["id"]
    assert client.get("/api/workspaces").json()[0]["folder_id"] is None
    a = client.post("/api/folders", json={"name": "Work"}, headers=H).json()
    b = client.post("/api/folders", json={"name": "Infra", "parent_id": a["id"]}, headers=H).json()
    assert b["parent_id"] == a["id"]
    # No cycles.
    r = client.patch(f"/api/folders/{a['id']}", json={"parent_id": b["id"]}, headers=H)
    assert r.status_code == 422
    assert client.put(f"/api/workspaces/{ws}/folder", json={"folder_id": b["id"]},
                      headers=H).status_code == 200
    assert client.get("/api/workspaces").json()[0]["folder_id"] == b["id"]
    # Rename leaves the parent alone; parent_id: null moves to the top.
    r = client.patch(f"/api/folders/{b['id']}", json={"name": "Cluster"}, headers=H).json()
    assert r == {"id": b["id"], "name": "Cluster", "parent_id": a["id"]}
    r = client.patch(f"/api/folders/{b['id']}", json={"parent_id": None}, headers=H).json()
    assert r["parent_id"] is None

    # Folders are private; someone else's folder can't be used or seen.
    app, provider = app_and_provider
    bob = sign_in(app, provider, "bob")
    assert bob.get("/api/folders").json()["folders"] == []
    bws = bob.get("/api/workspaces").json()[0]["id"]
    assert bob.put(f"/api/workspaces/{bws}/folder", json={"folder_id": a["id"]},
                   headers=H).status_code == 404
    assert bob.put(f"/api/workspaces/{ws}/folder", json={"folder_id": None},
                   headers=H).status_code == 404
    assert bob.delete(f"/api/folders/{a['id']}", headers=H).status_code == 404

    # Deleting a folder un-files its workspaces but never deletes them.
    r = client.patch(f"/api/folders/{b['id']}", json={"parent_id": a["id"]}, headers=H)
    assert client.delete(f"/api/folders/{a['id']}", headers=H).status_code == 204
    assert client.get("/api/folders").json()["folders"] == []
    assert client.get("/api/workspaces").json()[0] == {**client.get("/api/workspaces").json()[0],
                                                       "id": ws, "folder_id": None}


def test_mcp_folders(mcp):  # noqa: F811
    mcp, _ = mcp
    f = mcp.call("create_folder", name="Diagrams")
    w = mcp.call("create_workspace", name="Filed", folder_id=f["id"])
    listed = mcp.call("list_workspaces")
    assert listed["folders"] == [f]
    assert {x["id"]: x["folder_id"] for x in listed["workspaces"]}[w["workspace_id"]] == f["id"]
    mcp.call("file_workspace", workspace_id=w["workspace_id"], folder_id=None)
    listed = mcp.call("list_workspaces")
    assert {x["id"]: x["folder_id"] for x in listed["workspaces"]}[w["workspace_id"]] is None

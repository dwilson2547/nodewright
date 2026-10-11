from .conftest import H, sign_in


def _canvas(c, ws):
    return c.get(f"/api/workspaces/{ws}/canvases").json()[0]["id"]


def test_members_add_change_role_remove_and_leave(app_and_provider, client):
    app, provider = app_and_provider
    bob = sign_in(app, provider, "bob")
    carol = sign_in(app, provider, "carol")
    ws = client.get("/api/workspaces").json()[0]
    assert ws["role"] == "owner" and ws["owner"] == "alice"
    ws = ws["id"]
    tab = _canvas(client, ws)
    url = f"/api/workspaces/{ws}/members"

    # Strangers see nothing; unknown usernames and bad roles are refused.
    assert bob.get(url).status_code == 404
    assert client.post(url, json={"username": "nobody"}, headers=H).status_code == 404
    assert client.post(url, json={"username": "bob", "role": "owner"}, headers=H).status_code == 422
    assert client.post(url, json={"username": "alice"}, headers=H).status_code == 422

    r = client.post(url, json={"username": "Bob", "role": "viewer"}, headers=H)
    assert r.status_code == 201 and r.json()["role"] == "viewer"
    bob_id = r.json()["user_id"]
    assert client.post(url, json={"username": "bob"}, headers=H).status_code == 409
    carol_id = client.post(url, json={"username": "carol"}, headers=H).json()["user_id"]

    # A viewer sees the workspace and its members, reads but can't edit or manage.
    shared = next(w for w in bob.get("/api/workspaces").json() if w["id"] == ws)
    assert shared["role"] == "viewer" and shared["owner"] == "alice"
    listed = bob.get(url).json()
    assert [(m["username"], m["role"]) for m in listed["members"]] == [
        ("alice", "owner"), ("bob", "viewer"), ("carol", "editor")]
    assert listed["can_manage"] is False and client.get(url).json()["can_manage"] is True
    assert bob.get(f"/api/canvases/{tab}").json()["can_edit"] is False
    save = {"base_revision": 1, "data": {"nodes": [], "edges": []}}
    assert bob.put(f"/api/canvases/{tab}", json=save, headers=H).status_code == 403
    assert bob.post(url, json={"username": "carol"}, headers=H).status_code == 403
    assert bob.delete(f"{url}/{carol_id}", headers=H).status_code == 403
    assert bob.patch(f"/api/workspaces/{ws}", json={"name": "x"}, headers=H).status_code == 403

    # Promoted to editor, bob can edit but still not manage.
    assert client.patch(f"{url}/{bob_id}", json={"role": "editor"},
                        headers=H).json()["role"] == "editor"
    assert bob.get(f"/api/canvases/{tab}").json()["can_edit"] is True
    assert bob.delete(f"/api/workspaces/{ws}", headers=H).status_code == 403

    # An editor's lease goes when they're removed, so others needn't wait it out.
    assert bob.post(f"/api/canvases/{tab}/lease", headers=H).status_code == 200
    assert client.get(f"/api/canvases/{tab}/lease").json()["lease"] is not None

    # Members file the shared workspace in their own folders; leaving drops that.
    f = bob.post("/api/folders", json={"name": "Shared"}, headers=H).json()["id"]
    assert bob.put(f"/api/workspaces/{ws}/folder", json={"folder_id": f},
                   headers=H).status_code == 200
    assert bob.delete(f"{url}/{bob_id}", headers=H).status_code == 204
    assert client.get(f"/api/canvases/{tab}/lease").json()["lease"] is None
    assert all(w["id"] != ws for w in bob.get("/api/workspaces").json())
    assert bob.get(f"/api/canvases/{tab}").status_code == 404

    # The owner removes carol; removing a non-member is a 404.
    assert client.delete(f"{url}/{carol_id}", headers=H).status_code == 204
    assert carol.get(url).status_code == 404
    assert client.delete(f"{url}/{carol_id}", headers=H).status_code == 404
    assert [m["username"] for m in client.get(url).json()["members"]] == ["alice"]

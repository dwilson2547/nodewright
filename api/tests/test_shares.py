from .conftest import H
from .test_editor import PNG, files  # noqa: F401  (fixture)


def test_share_links_are_public_read_only_and_revocable(files):  # noqa: F811
    from nodewright.models import WorkspaceMember

    app, provider, st, sign_in = files
    alice = sign_in(app, provider, "alice")
    ws = alice.get("/api/workspaces").json()[0]["id"]
    first = alice.get(f"/api/workspaces/{ws}/canvases").json()[0]["id"]
    second = alice.post(f"/api/workspaces/{ws}/canvases", json={"name": "Two"}, headers=H).json()["id"]
    shown = alice.post(f"/api/workspaces/{ws}/attachments", content=PNG,
                       headers={**H, "X-Filename": "a.png"}).json()["id"]
    elsewhere = alice.post(f"/api/workspaces/{ws}/attachments", content=PNG,
                           headers={**H, "X-Filename": "b.png"}).json()["id"]
    doc = {"nodes": [{"id": "f", "type": "file", "file": f"attachments/{shown}/a.png",
                      "x": 0, "y": 0, "width": 100, "height": 100}], "edges": []}
    rev = alice.get(f"/api/canvases/{first}").json()["revision"]
    assert alice.put(f"/api/canvases/{first}", json={"base_revision": rev, "data": doc},
                     headers=H).status_code == 200

    one = alice.post(f"/api/canvases/{first}/shares", json={}, headers=H).json()
    every = alice.post(f"/api/canvases/{first}/shares", json={"all_tabs": True}, headers=H).json()
    assert one["url"].startswith("http") and "/s/" in one["url"] and not one["all_tabs"]
    assert [x["id"] for x in alice.get(f"/api/canvases/{first}/shares").json()["shares"]] == \
        [one["id"], every["id"]]
    t1, ta = one["url"].rsplit("/", 1)[1], every["url"].rsplit("/", 1)[1]

    # Anyone with the link, signed in or not.
    from fastapi.testclient import TestClient
    anon = TestClient(app)
    got = anon.get(f"/api/s/{t1}").json()
    assert got["id"] == first and got["data"] == doc and [t["id"] for t in got["tabs"]] == [first]
    assert anon.get(f"/api/s/{t1}/canvases/{second}").status_code == 404
    assert anon.get(f"/api/s/{t1}/attachments/{shown}").content == PNG
    assert anon.get(f"/api/s/{t1}/attachments/{elsewhere}").status_code == 404
    # all_tabs opens the other tabs and any of the workspace's files.
    assert [t["id"] for t in anon.get(f"/api/s/{ta}").json()["tabs"]] == [first, second]
    assert anon.get(f"/api/s/{ta}/canvases/{second}").json()["name"] == "Two"
    assert anon.get(f"/api/s/{ta}/attachments/{elsewhere}").status_code == 200
    assert anon.get("/api/s/nope").status_code == 404
    # Nothing to write through a share.
    assert anon.put(f"/api/s/{t1}", json={}).status_code in (404, 405)

    # Only someone who can manage the workspace creates, lists or revokes.
    bob = sign_in(app, provider, "bob")
    bob_id = bob.get("/api/me").json()["id"]
    with app.state.db.session() as s:
        s.add(WorkspaceMember(workspace_id=ws, user_id=bob_id, role="editor"))
    assert bob.post(f"/api/canvases/{first}/shares", json={}, headers=H).status_code == 403
    assert bob.get(f"/api/canvases/{first}/shares").status_code == 403
    assert bob.delete(f"/api/shares/{one['id']}", headers=H).status_code == 403

    assert alice.delete(f"/api/shares/{one['id']}", headers=H).status_code == 204
    assert anon.get(f"/api/s/{t1}").status_code == 404
    assert anon.get(f"/api/s/{t1}/attachments/{shown}").status_code == 404
    # Deleting the canvas takes its links with it.
    assert alice.delete(f"/api/canvases/{first}", headers=H).status_code == 204
    assert anon.get(f"/api/s/{ta}").status_code == 404

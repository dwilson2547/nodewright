from fastapi.testclient import TestClient

from nodewright.config import Settings
from nodewright.main import create_app

from .conftest import H, sign_in

DOC = {"nodes": [{"id": "a", "type": "text", "text": "hi", "x": 0, "y": 0, "width": 200,
                  "height": 60}], "edges": []}


def first_canvas(client):
    ws = client.get("/api/workspaces").json()[0]
    return ws, client.get(f"/api/workspaces/{ws['id']}/canvases").json()[0]


def test_new_user_gets_a_workspace_and_a_tab(client):
    assert client.get("/api/me").json()["username"] == "alice"
    ws, tab = first_canvas(client)
    assert ws["name"] == "My workspace" and tab["name"] == "Untitled" and tab["revision"] == 1


def test_same_identity_signs_into_same_account(app_and_provider):
    app, provider = app_and_provider
    a = sign_in(app, provider, "alice").get("/api/me").json()
    b = sign_in(app, provider, "alice").get("/api/me").json()
    assert a == b


def test_signin_with_wrong_state_is_refused(app_and_provider):
    app, provider = app_and_provider
    c = TestClient(app)
    c.get("/api/auth/oidc/login", follow_redirects=False)
    provider.subjects["code-x"] = "x"
    r = c.get("/api/auth/oidc/callback?code=code-x&state=forged", follow_redirects=False)
    assert r.headers["location"] == "/?signin_error=refused"
    assert c.get("/api/me").status_code == 401


def test_anonymous_is_401(app_and_provider):
    assert TestClient(app_and_provider[0]).get("/api/workspaces").status_code == 401


def test_writes_need_the_csrf_header(client):
    r = client.post("/api/workspaces", json={"name": "x"})
    assert r.status_code == 403
    assert client.post("/api/workspaces", json={"name": "x"}, headers=H).status_code == 201


def test_logout_ends_the_session(client):
    assert client.post("/api/auth/logout", headers=H).status_code == 200
    assert client.get("/api/me").status_code == 401


def test_save_and_conflict(client):
    _, tab = first_canvas(client)
    url = f"/api/canvases/{tab['id']}"
    r = client.put(url, json={"base_revision": 1, "data": DOC}, headers=H)
    assert r.status_code == 200 and r.json()["revision"] == 2
    stale = client.put(url, json={"base_revision": 1, "data": {"nodes": []}}, headers=H)
    assert stale.status_code == 409
    assert stale.json()["current"]["data"]["nodes"][0]["text"] == "hi"
    revs = client.get(url + "/revisions").json()
    assert [r["revision"] for r in revs] == [2]  # the initial empty tab isn't a recorded save
    assert client.get(url).json()["revision"] == 2


def test_invalid_and_oversized_canvas(client):
    _, tab = first_canvas(client)
    url = f"/api/canvases/{tab['id']}"
    bad = {"nodes": [], "edges": [{"id": "e", "fromNode": "a", "toNode": "b"}]}
    assert client.put(url, json={"base_revision": 1, "data": bad}, headers=H).status_code == 422
    big = {"nodes": [], "pad": "x" * 30_000}
    assert client.put(url, json={"base_revision": 1, "data": big}, headers=H).status_code == 413


def test_other_users_cannot_see_or_touch(app_and_provider, client):
    app, provider = app_and_provider
    ws, tab = first_canvas(client)
    bob = sign_in(app, provider, "bob")
    assert bob.get(f"/api/canvases/{tab['id']}").status_code == 404
    assert bob.put(f"/api/canvases/{tab['id']}", json={"base_revision": 1, "data": DOC},
                   headers=H).status_code == 404
    assert bob.delete(f"/api/workspaces/{ws['id']}", headers=H).status_code == 404
    assert bob.get(f"/api/workspaces/{ws['id']}/canvases").status_code == 404
    assert len(bob.get("/api/workspaces").json()) == 1


def test_tabs_import_reorder_export_delete(client):
    ws, first = first_canvas(client)
    base = f"/api/workspaces/{ws['id']}/canvases"
    second = client.post(base, json={"name": "Imported", "data": DOC}, headers=H).json()
    assert second["position"] == 1
    client.patch(f"/api/canvases/{second['id']}", json={"position": 0}, headers=H)
    assert [t["name"] for t in client.get(base).json()] == ["Imported", "Untitled"]
    r = client.get(f"/api/canvases/{second['id']}/export")
    assert r.headers["content-disposition"] == 'attachment; filename="Imported.canvas"'
    assert r.json() == DOC
    assert client.delete(f"/api/canvases/{second['id']}", headers=H).status_code == 204
    assert [t["name"] for t in client.get(base).json()] == ["Untitled"]


def test_deleting_a_workspace_removes_its_tabs(client):
    ws = client.post("/api/workspaces", json={"name": "Temp"}, headers=H).json()
    tab = client.get(f"/api/workspaces/{ws['id']}/canvases").json()[0]
    assert client.delete(f"/api/workspaces/{ws['id']}", headers=H).status_code == 204
    assert client.get(f"/api/canvases/{tab['id']}").status_code == 404


def test_dev_login_is_refused_on_https(tmp_path):
    s = Settings(database_url=f"sqlite:///{tmp_path}/d.db", public_url="https://x.example",
                 dev_login=True)
    c = TestClient(create_app(s))
    assert c.post("/api/auth/dev-login", json={"name": "a"}, headers=H).status_code == 404
    assert c.get("/api/config").json()["dev_login"] is False


def test_security_headers_and_static(tmp_path):
    (tmp_path / "ui" / "assets").mkdir(parents=True)
    (tmp_path / "ui" / "index.html").write_text("<html>shell</html>")
    (tmp_path / "ui" / "assets" / "a.js").write_text("x")
    (tmp_path / "secret.txt").write_text("nope")
    s = Settings(database_url=f"sqlite:///{tmp_path}/s.db", static_dir=str(tmp_path / "ui"))
    c = TestClient(create_app(s))
    r = c.get("/some/route")
    assert "shell" in r.text and "script-src 'self'" in r.headers["content-security-policy"]
    assert c.get("/assets/a.js").headers["cache-control"].startswith("public")
    assert "shell" in c.get("/../secret.txt").text
    assert "shell" in c.get("/%2e%2e/secret.txt").text
    assert c.get("/api/nope").status_code == 404

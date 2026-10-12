"""Org-shared libraries (design §20): templates, icons and style guides."""

from .conftest import H, sign_in
from .test_phase2 import mcp  # noqa: F401

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2 2h20v20H2z"/></svg>'
DOC = {"nodes": [{"id": "a", "type": "text", "text": "A", "x": 0, "y": 0, "width": 100, "height": 50}],
       "edges": []}


def _setup(app, provider, alice):
    bob, carol, dave = (sign_in(app, provider, n) for n in ("bob", "carol", "dave"))
    oid = alice.post("/api/orgs", json={"name": "Acme"}, headers=H).json()["id"]
    for name in ("bob", "carol"):
        alice.post(f"/api/orgs/{oid}/members", json={"username": name, "role": "member"}, headers=H)
    return oid, bob, carol, dave


def _tpl(c, name):
    return next((t for t in c.get("/api/templates").json()["templates"] if t["name"] == name), None)


def test_templates_shared_with_an_org(app_and_provider, client):
    app, provider = app_and_provider
    alice = client
    oid, bob, carol, dave = _setup(app, provider, alice)

    # Bob saves a template straight into the org; members see it, outsiders don't.
    t = bob.post("/api/templates", json={"name": "Team box", "kind": "stencil", "data": DOC, "org_id": oid},
                 headers=H).json()
    assert t["org"] == {"id": oid, "name": "Acme"} and t["can_edit"] and t["mine"]
    seen = _tpl(carol, "Team box")
    assert seen["org"]["name"] == "Acme" and not seen["can_edit"] and not seen["mine"]
    assert _tpl(dave, "Team box") is None
    assert dave.post("/api/templates", json={"name": "X", "kind": "stencil", "data": DOC, "org_id": oid},
                     headers=H).status_code == 422
    # Members use it (as a page too); only its author or an admin changes it.
    assert carol.post("/api/workspaces/" + carol.get("/api/workspaces").json()[0]["id"] + "/canvases",
                      json={"name": "From team", "template": t["id"]}, headers=H).status_code == 201
    assert carol.patch(f"/api/templates/{t['id']}", json={"name": "Mine now"}, headers=H).status_code == 403
    assert carol.delete(f"/api/templates/{t['id']}", headers=H).status_code == 403
    assert alice.patch(f"/api/templates/{t['id']}", json={"name": "Team card"}, headers=H).json()["name"] == "Team card"
    # Only the author shares or unshares; an admin can't take it into their own library.
    assert alice.patch(f"/api/templates/{t['id']}", json={"org_id": None}, headers=H).status_code == 403
    back = bob.patch(f"/api/templates/{t['id']}", json={"org_id": None}, headers=H).json()
    assert back["org"] is None and _tpl(carol, "Team card") is None
    assert bob.patch(f"/api/templates/{t['id']}", json={"org_id": "nope"}, headers=H).status_code == 403
    bob.patch(f"/api/templates/{t['id']}", json={"org_id": oid}, headers=H)

    # An author who leaves keeps nothing: the template stays with the org.
    bob_id = next(m["user_id"] for m in alice.get(f"/api/orgs/{oid}/members").json()["members"]
                  if m["username"] == "bob")
    bob.delete(f"/api/orgs/{oid}/members/{bob_id}", headers=H)
    assert _tpl(bob, "Team card") is None and _tpl(carol, "Team card") is not None
    assert alice.delete(f"/api/templates/{t['id']}", headers=H).status_code == 204


def test_icons_shared_with_an_org(app_and_provider, client):
    app, provider = app_and_provider
    alice = client
    oid, bob, carol, dave = _setup(app, provider, alice)
    icon = bob.post("/api/icons", json={"name": "Logo", "svg": SVG}, headers=H).json()
    assert icon["org"] is None
    shared = bob.patch(f"/api/icons/{icon['id']}", json={"org_id": oid}, headers=H).json()
    assert shared["org"]["name"] == "Acme"
    assert [i["name"] for i in carol.get("/api/icons").json()["mine"]] == ["Logo"]
    assert dave.get("/api/icons").json()["mine"] == []
    assert carol.patch(f"/api/icons/{icon['id']}", json={"name": "X"}, headers=H).status_code == 403
    assert alice.patch(f"/api/icons/{icon['id']}", json={"name": "Acme logo"}, headers=H).json()["name"] == "Acme logo"
    assert alice.get(f"/api/icons/{icon['id']}").status_code == 200
    assert dave.get(f"/api/icons/{icon['id']}").status_code == 404
    assert alice.post("/api/icons", json={"name": "Y", "svg": SVG, "org_id": "nope"}, headers=H).status_code == 404


def test_org_style_guide(app_and_provider, client):
    app, provider = app_and_provider
    alice = client
    oid, bob, carol, dave = _setup(app, provider, alice)
    assert bob.get(f"/api/orgs/{oid}/style-guide").json() == {"text": "", "can_edit": False}
    assert bob.put(f"/api/orgs/{oid}/style-guide", json={"text": "x"}, headers=H).status_code == 403
    assert dave.get(f"/api/orgs/{oid}/style-guide").status_code == 404
    got = alice.put(f"/api/orgs/{oid}/style-guide", json={"text": "Use green for our services."}, headers=H)
    assert got.json()["text"] == "Use green for our services."
    assert bob.get(f"/api/orgs/{oid}/style-guide").json()["text"] == "Use green for our services."


def test_agents_get_org_guides_and_templates(mcp):  # noqa: F811
    m, web = mcp
    oid = web.post("/api/orgs", json={"name": "Acme"}, headers=H).json()["id"]
    web.put(f"/api/orgs/{oid}/style-guide", json={"text": "Acme: left to right."}, headers=H)
    personal = m.call("list_workspaces")["workspaces"][0]
    org_ws = m.call("create_workspace", name="Team", org_id=oid)

    everything = m.call("get_style_guide")
    assert everything["org_guides"] == [{"org": "Acme", "text": "Acme: left to right."}]
    assert m.call("get_style_guide", canvas_id=org_ws["canvas_id"])["org_guides"][0]["org"] == "Acme"
    assert m.call("get_style_guide", canvas_id=personal["canvases"][0]["id"])["org_guides"] == []

    m.call("add_elements", canvas_id=org_ws["canvas_id"], nodes=[{"id": "n", "text": "Box"}])
    m.call("unlock_canvas", canvas_id=org_ws["canvas_id"])
    saved = m.call("save_template", canvas_id=org_ws["canvas_id"], node_ids=["n"], name="Acme box",
                   kind="stencil", org_id=oid)
    listed = {t["id"]: t for t in m.call("list_templates")["templates"]}
    assert listed[saved["template_id"]]["org"] == "Acme"

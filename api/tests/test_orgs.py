"""Organisations (design §19): org roles, org access to workspaces, moving
workspaces, the last-admin rule, and authentik group sync."""

import dataclasses

import pytest

from nodewright.config import parse_org_groups
from nodewright.main import create_app

from .conftest import H, FakeProvider, sign_in


def _ws(c, name):
    return next(w for w in c.get("/api/workspaces").json() if w["name"] == name)


def test_org_members_get_org_access_and_admins_own(app_and_provider, client):
    app, provider = app_and_provider
    bob, carol, dave = (sign_in(app, provider, n) for n in ("bob", "carol", "dave"))
    alice = client

    org = alice.post("/api/orgs", json={"name": "Acme"}, headers=H).json()
    assert org["role"] == "admin"
    assert alice.post("/api/orgs", json={"name": "Acme"}, headers=H).status_code == 409
    oid = org["id"]
    for name, role in (("bob", "member"), ("carol", "admin")):
        assert alice.post(f"/api/orgs/{oid}/members", json={"username": name, "role": role},
                          headers=H).status_code == 201
    # Only admins manage members; members can see the list.
    assert bob.post(f"/api/orgs/{oid}/members", json={"username": "dave", "role": "member"},
                    headers=H).status_code == 403
    got = bob.get(f"/api/orgs/{oid}/members").json()
    assert {m["username"]: m["role"] for m in got["members"]} == {"alice": "admin", "bob": "member", "carol": "admin"}
    assert got["can_manage"] is False
    assert dave.get(f"/api/orgs/{oid}/members").status_code == 404

    # A member creates an org workspace: every member gets its org access (editor).
    ws = bob.post("/api/workspaces", json={"name": "Plans", "org_id": oid}, headers=H).json()
    assert ws["org"]["name"] == "Acme" and ws["role"] == "editor" and ws["owner"] == "Acme"
    assert dave.post("/api/workspaces", json={"name": "X", "org_id": oid}, headers=H).status_code == 404
    assert _ws(alice, "Plans")["role"] == "owner" and _ws(carol, "Plans")["role"] == "owner"
    assert "Plans" not in [w["name"] for w in dave.get("/api/workspaces").json()]
    # Its creator may rename it, but nothing more than any member.
    assert ws["can_rename"] is True and _ws(carol, "Plans")["can_rename"] is True
    renamed = bob.patch(f"/api/workspaces/{ws['id']}", json={"name": "Plans"}, headers=H)
    assert renamed.status_code == 200 and renamed.json()["can_rename"] is True
    assert bob.patch(f"/api/workspaces/{ws['id']}", json={"name": "Plans", "org_access": "none"},
                     headers=H).status_code == 403
    assert bob.delete(f"/api/workspaces/{ws['id']}", headers=H).status_code == 403
    erin = sign_in(app, provider, "erin")
    alice.post(f"/api/orgs/{oid}/members", json={"username": "erin", "role": "member"}, headers=H)
    assert _ws(erin, "Plans")["can_rename"] is False
    assert erin.patch(f"/api/workspaces/{ws['id']}", json={"name": "X"}, headers=H).status_code == 403

    # Viewer access for the org; a guest from outside added by name; explicit beats org access.
    assert alice.patch(f"/api/workspaces/{ws['id']}", json={"org_access": "viewer"}, headers=H).json()["role"] == "owner"
    assert _ws(bob, "Plans")["role"] == "viewer"
    alice.post(f"/api/workspaces/{ws['id']}/members", json={"username": "bob", "role": "editor"}, headers=H)
    alice.post(f"/api/workspaces/{ws['id']}/members", json={"username": "dave", "role": "viewer"}, headers=H)
    assert _ws(bob, "Plans")["role"] == "editor" and _ws(dave, "Plans")["role"] == "viewer"
    members = alice.get(f"/api/workspaces/{ws['id']}/members").json()
    assert members["org"] == {"id": oid, "name": "Acme", "access": "viewer"}
    assert [m["username"] for m in members["members"]] == ["bob", "dave"]  # no owner row
    assert alice.patch(f"/api/workspaces/{ws['id']}", json={"org_access": "admin"}, headers=H).status_code == 422

    # No org access: only admins and people added by name see it.
    alice.patch(f"/api/workspaces/{ws['id']}", json={"org_access": "none"}, headers=H)
    alice.delete(f"/api/workspaces/{ws['id']}/members/{_uid(alice, ws['id'], 'bob')}", headers=H)
    assert "Plans" not in [w["name"] for w in bob.get("/api/workspaces").json()]

    # The last admin can't step down or leave; another admin can remove them.
    alice.delete(f"/api/orgs/{oid}/members/{_org_uid(alice, oid, 'carol')}", headers=H)
    me = _org_uid(alice, oid, "alice")
    assert "at least one admin" in alice.patch(f"/api/orgs/{oid}/members/{me}", json={"role": "member"},
                                               headers=H).json()["detail"]
    assert alice.delete(f"/api/orgs/{oid}/members/{me}", headers=H).status_code == 409
    # Members may leave.
    assert bob.delete(f"/api/orgs/{oid}/members/{_org_uid(alice, oid, 'bob')}", headers=H).status_code == 204

    # An org can't be deleted while it owns workspaces.
    assert alice.delete(f"/api/orgs/{oid}", headers=H).status_code == 409
    assert alice.delete(f"/api/workspaces/{ws['id']}", headers=H).status_code == 204
    assert alice.delete(f"/api/orgs/{oid}", headers=H).status_code == 204
    assert alice.get("/api/orgs").json()["orgs"] == []


def _uid(c, ws_id, name):
    return next(m["user_id"] for m in c.get(f"/api/workspaces/{ws_id}/members").json()["members"]
                if m["username"] == name)


def _org_uid(c, oid, name):
    return next(m["user_id"] for m in c.get(f"/api/orgs/{oid}/members").json()["members"]
                if m["username"] == name)


def test_moving_workspaces_in_and_out(app_and_provider, client):
    app, provider = app_and_provider
    bob = sign_in(app, provider, "bob")
    alice = client
    oid = alice.post("/api/orgs", json={"name": "Acme"}, headers=H).json()["id"]
    other = bob.post("/api/orgs", json={"name": "Bobco"}, headers=H).json()["id"]
    alice.post(f"/api/orgs/{oid}/members", json={"username": "bob", "role": "member"}, headers=H)
    ws = alice.get("/api/workspaces").json()[0]

    # Only into an org you're in.
    assert alice.post(f"/api/workspaces/{ws['id']}/move", json={"org_id": other}, headers=H).status_code == 403
    moved = alice.post(f"/api/workspaces/{ws['id']}/move", json={"org_id": oid}, headers=H).json()
    assert moved["org"]["id"] == oid and moved["role"] == "owner"
    assert _ws(bob, ws["name"])["role"] == "editor"
    # Members can't move it; admins can hand it to a member's personal space.
    assert bob.post(f"/api/workspaces/{ws['id']}/move", json={"org_id": None}, headers=H).status_code == 403
    assert alice.post(f"/api/workspaces/{ws['id']}/move", json={"org_id": None, "owner": "nobody"},
                      headers=H).status_code == 404
    out = alice.post(f"/api/workspaces/{ws['id']}/move", json={"org_id": None, "owner": "bob"}, headers=H).json()
    assert out["org"] is None and out["can_see"] is False
    assert _ws(bob, ws["name"])["role"] == "owner"
    assert ws["name"] not in [w["name"] for w in alice.get("/api/workspaces").json()]


def test_org_groups_config():
    assert parse_org_groups("") == {}
    assert parse_org_groups('{"g": {"org": " Acme "}}') == {"g": ("Acme", "member")}
    for bad in ("[]", '{"g": {}}', '{"g": {"org": "A", "role": "owner"}}', "{"):
        with pytest.raises(ValueError):
            parse_org_groups(bad)


class GroupProvider(FakeProvider):
    """Also sends a groups claim, per subject (None = no claim at all)."""

    groups: dict[str, list[str] | None] = {}

    def verify(self, id_token, nonce):
        claims = super().verify(id_token, nonce)
        g = self.groups.get(claims["sub"])
        return claims if g is None else {**claims, "groups": g}


def test_authentik_groups_sync_org_membership(settings):
    settings = dataclasses.replace(settings, org_groups={
        "acme-staff": ("Acme", "member"), "acme-admins": ("Acme", "admin")})
    provider = GroupProvider(settings)
    provider.groups = {}
    app = create_app(settings, provider)

    provider.groups["erin"] = ["acme-staff", "acme-admins", "unrelated"]
    erin = sign_in(app, provider, "erin")
    orgs = erin.get("/api/orgs").json()["orgs"]
    assert [(o["name"], o["role"], o["managed"]) for o in orgs] == [("Acme", "admin", True)]
    oid = orgs[0]["id"]
    # A managed org can't be renamed (the mapping names it), synced rows can't be edited by hand.
    assert erin.patch(f"/api/orgs/{oid}", json={"name": "Other"}, headers=H).status_code == 409
    provider.groups["frank"] = ["acme-staff"]
    frank = sign_in(app, provider, "frank")
    fid = _org_uid(erin, oid, "frank")
    assert erin.patch(f"/api/orgs/{oid}/members/{fid}", json={"role": "admin"}, headers=H).status_code == 409
    assert [m["source"] for m in erin.get(f"/api/orgs/{oid}/members").json()["members"]] == ["authentik", "authentik"]

    # A hand-added member is left alone by the sync.
    sign_in(app, provider, "gina")
    erin.post(f"/api/orgs/{oid}/members", json={"username": "gina", "role": "member"}, headers=H)
    provider.groups["gina"] = []
    gina = sign_in(app, provider, "gina")
    assert [o["name"] for o in gina.get("/api/orgs").json()["orgs"]] == ["Acme"]

    # Group changes apply at the next sign-in: demoted, then removed.
    provider.groups["erin"] = ["acme-staff"]
    sign_in(app, provider, "erin")
    assert {m["username"]: m["role"] for m in frank.get(f"/api/orgs/{oid}/members").json()["members"]}["erin"] == "member"
    provider.groups["frank"] = []
    frank = sign_in(app, provider, "frank")
    assert frank.get("/api/orgs").json()["orgs"] == []
    # No groups claim at all: nothing is removed.
    provider.groups["erin"] = None
    erin = sign_in(app, provider, "erin")
    assert [o["name"] for o in erin.get("/api/orgs").json()["orgs"]] == ["Acme"]


def test_agents_see_orgs_and_create_org_workspaces(mcp):  # noqa: F811
    m, web = mcp
    oid = web.post("/api/orgs", json={"name": "Acme"}, headers=H).json()["id"]
    listed = m.call("list_workspaces")
    assert listed["orgs"] == [{"id": oid, "name": "Acme", "role": "admin"}]
    made = m.call("create_workspace", name="Team board", org_id=oid)
    ws = next(w for w in m.call("list_workspaces")["workspaces"] if w["id"] == made["workspace_id"])
    assert ws["org"] == {"id": oid, "name": "Acme"} and ws["role"] == "owner"
    assert "org not found" in m.error("create_workspace", name="X", org_id="nope")


from .test_phase2 import mcp  # noqa: E402,F401

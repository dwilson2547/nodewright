"""Schematic symbols (design §15): the built-in set, agent placement, orientation, net labels."""

from nodewright import icons, ports, svgsafe, symbols

from .test_phase2 import Mcp, mcp  # noqa: F401


def test_every_symbol_is_safe_and_pinned():
    defs = symbols.definitions()
    assert len({d["id"] for d in defs}) == len(defs) >= 30
    for d in defs:
        svgsafe.clean(d["svg"].encode())
        assert ports.check(d["ports"], d["id"]) == d["ports"] and d["ports"], d["id"]
        assert d["size"] > 0 and d["category"]


def test_symbols_listed_and_served(client):
    got = client.get("/api/icons").json()
    syms = {s["id"]: s for s in got["symbols"]}
    assert "sym-resistor" in syms and all(not b["id"].startswith("sym-") for b in got["builtin"])
    r = syms["sym-resistor"]
    assert r["category"] == "Passive" and r["size"] == 80 and [p["id"] for p in r["ports"]] == ["1", "2"]
    assert syms["sym-junction"]["size"] == 16
    svg = client.get(r["url"])
    assert svg.status_code == 200 and svg.text.startswith("<svg")


def test_reorient_round_trips():
    pins = icons.builtins()["sym-npn"]["ports"]
    for r in (0, 90, 180, 270):
        for m in (False, True):
            there = ports.reorient(pins, (0, False), (r, m))
            assert ports.reorient(there, (r, m), (0, False)) == pins
    assert ports.reorient(pins, (0, False), (90, False))[0] == {"id": "B", "side": "top", "at": 0.5}
    # Mirrored, the collector at top 0.7 moves to top 0.3.
    assert ports.reorient(pins, (0, False), (0, True))[1] == {"id": "C", "side": "top", "at": 0.3}


def test_agent_builds_a_circuit(mcp):  # noqa: F811
    m, web = mcp
    tab = m.call("list_workspaces")["workspaces"][0]["canvases"][0]["id"]
    listed = m.call("list_icons")
    file = {s["id"]: s["file"] for s in listed["symbols"]}
    assert any(s["category"] == "Logic and ICs" for s in listed["symbols"])

    m.call("add_elements", canvas_id=tab, nodes=[
        {"id": "q1", "icon": file["sym-npn"], "text": "Q1"},
        {"id": "r1", "icon": file["sym-resistor"], "text": "R1 10k",
         "styleAttributes": {"rotate": "90"}},
        {"id": "j", "icon": file["sym-junction"]},
        {"id": "vcc", "text": "VCC", "styleAttributes": {"shape": "net"}},
    ], edges=[
        {"fromNode": "r1", "fromPort": "2", "toNode": "q1", "toPort": "C"},
        {"fromNode": "vcc", "fromPort": "net", "toNode": "r1", "toPort": "1"},
    ])
    doc = {n["id"]: n for n in m.call("get_canvas", canvas_id=tab)["data"]["nodes"]}
    q1, r1 = doc["q1"], doc["r1"]
    assert (q1["width"], q1["height"]) == (80, 80) and q1["styleAttributes"]["border"] == "invisible"
    assert [p["id"] for p in q1["ports"]] == ["B", "C", "E"]
    # Turned a quarter: pin 1 (left) is now on top, pin 2 at the bottom.
    assert [(p["id"], p["side"]) for p in r1["ports"]] == [("1", "top"), ("2", "bottom")]
    assert (doc["j"]["width"], doc["j"]["height"]) == (16, 16) and len(doc["j"]["ports"]) == 4
    assert doc["vcc"]["ports"] == [{"id": "net", "side": "left", "at": 0.5}]

    # Turning the transistor moves its pins and the wire on C follows.
    m.call("update_elements", canvas_id=tab, updates=[{"id": "q1", "set": {"styleAttributes": {"rotate": "270"}}}])
    data = m.call("get_canvas", canvas_id=tab)["data"]
    q1 = next(n for n in data["nodes"] if n["id"] == "q1")
    assert {p["id"]: p["side"] for p in q1["ports"]} == {"B": "bottom", "C": "left", "E": "right"}
    wire = next(e for e in data["edges"] if e.get("toPort") == "C")
    assert wire["toSide"] == "left"
    # Back to upright, mirrored: B on the right.
    m.call("update_elements", canvas_id=tab, updates=[
        {"id": "q1", "set": {"styleAttributes": {"rotate": None, "mirror": "horizontal"}}}])
    q1 = next(n for n in m.call("get_canvas", canvas_id=tab)["data"]["nodes"] if n["id"] == "q1")
    assert {p["id"]: (p["side"], p["at"]) for p in q1["ports"]} == {
        "B": ("right", 0.5), "C": ("top", 0.3), "E": ("bottom", 0.3)}

    # Explicit ports win over the icon's pins.
    m.call("add_elements", canvas_id=tab, nodes=[
        {"id": "d1", "icon": file["sym-diode"], "ports": [{"id": "x", "side": "top"}], "width": 40, "height": 40}])
    d1 = next(n for n in m.call("get_canvas", canvas_id=tab)["data"]["nodes"] if n["id"] == "d1")
    assert [p["id"] for p in d1["ports"]] == ["x"] and d1["width"] == 40

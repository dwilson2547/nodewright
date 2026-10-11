import pytest

from nodewright import canvas_format, ops


def _doc():
    return {"nodes": [], "edges": []}


PORTS = [{"id": "in", "side": "left", "at": 0.5, "label": "in"},
         {"id": "out1", "side": "right", "at": 0.25}, {"id": "out2", "side": "right", "at": 0.75}]


def test_ports_validate_and_normalise():
    d = {"nodes": [{"id": "a", "type": "text", "text": "", "x": 0, "y": 0, "width": 9, "height": 9,
                    "ports": [{"id": "p", "side": "top", "at": 1}, {"id": "q", "side": "left"}]}],
         "edges": [{"id": "e", "fromNode": "a", "toNode": "a", "fromPort": "gone"}]}
    out = canvas_format.validate(d)
    # `at` defaults to the middle; a dangling port name is allowed (the editor flags it).
    assert out["nodes"][0]["ports"] == [{"id": "p", "side": "top", "at": 1.0},
                                        {"id": "q", "side": "left", "at": 0.5}]
    for bad in ([{"id": "p", "side": "middle"}], [{"id": "p", "side": "top", "at": 2}],
                [{"id": "p", "side": "top"}, {"id": "p", "side": "left"}], "p", [{"side": "top"}]):
        d["nodes"][0]["ports"] = bad
        with pytest.raises(canvas_format.CanvasError):
            canvas_format.validate(d)
    d["nodes"][0]["ports"] = []
    d["edges"][0]["fromPort"] = 3
    with pytest.raises(canvas_format.CanvasError, match="fromPort"):
        canvas_format.validate(d)


def test_agent_edges_attach_to_ports_and_follow_them():
    d = _doc()
    r = ops.add_elements(
        [{"id": "a", "text": "A", "ports": PORTS}, {"id": "b", "text": "B", "ports": PORTS}],
        [{"id": "e", "fromNode": "a", "fromPort": "out2", "toNode": "b", "toPort": "in"}])(d)
    assert r["edge_ids"] == ["e"]
    e = d["edges"][0]
    assert (e["fromSide"], e["toSide"]) == ("right", "left")
    canvas_format.validate(d)

    with pytest.raises(ops.OpError, match="no port 'nope'"):
        ops.add_elements([], [{"fromNode": "a", "fromPort": "nope", "toNode": "b"}])(d)
    with pytest.raises(ops.OpError, match="side must be one of"):
        ops.add_elements([{"text": "x", "ports": [{"id": "p", "side": "up"}]}], [])(d)

    # Moving a port moves the edge's side with it.
    moved = [{**p, "side": "bottom"} if p["id"] == "out2" else p for p in PORTS]
    ops.update_elements([{"id": "a", "set": {"ports": moved}}])(d)
    assert d["edges"][0]["fromSide"] == "bottom"
    # Dropping it leaves the edge on its last side, still naming the port.
    ops.update_elements([{"id": "a", "set": {"ports": PORTS[:1]}}])(d)
    assert d["edges"][0]["fromPort"] == "out2" and d["edges"][0]["fromSide"] == "bottom"
    # An edge on a removed port can still be edited otherwise.
    ops.update_elements([{"id": "e", "set": {"label": "flow"}}])(d)
    # Re-pointing an edge checks the port exists.
    with pytest.raises(ops.OpError, match="no port 'out1'"):
        ops.update_elements([{"id": "e", "set": {"fromPort": "out1"}}])(d)
    ops.update_elements([{"id": "e", "set": {"fromPort": "in"}}])(d)
    assert d["edges"][0]["fromSide"] == "left"

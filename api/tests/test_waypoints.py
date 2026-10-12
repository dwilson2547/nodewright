"""Manual edge waypoints (design §18): validation, agent edits, layout and templates."""

import pytest

from nodewright import canvas_format, templates

from .test_phase2 import Mcp, mcp  # noqa: F401


def _doc(**edge):
    return {"nodes": [{"id": "a", "type": "text", "text": "A", "x": 0, "y": 0, "width": 100, "height": 60},
                      {"id": "b", "type": "text", "text": "B", "x": 400, "y": 200, "width": 100, "height": 60}],
            "edges": [{"id": "e", "fromNode": "a", "toNode": "b", **edge}]}


def test_waypoints_are_rounded_and_checked():
    got = canvas_format.validate(_doc(waypoints=[{"x": 10.4, "y": 20.6}, {"x": 300, "y": 20}]))
    assert got["edges"][0]["waypoints"] == [{"x": 10, "y": 21}, {"x": 300, "y": 20}]
    for bad in ("x", [{"x": 1}], [{"x": "1", "y": 2}], [[1, 2]],
                [{"x": 0, "y": 0}] * (canvas_format.MAX_WAYPOINTS + 1)):
        with pytest.raises(canvas_format.CanvasError):
            canvas_format.validate(_doc(waypoints=bad))


def test_templates_carry_waypoints_with_their_nodes():
    doc = _doc(waypoints=[{"x": 250, "y": 30}])
    for n in doc["nodes"]:
        n["x"] += 1000
        n["y"] += 500
    doc["edges"][0]["waypoints"] = [{"x": 1250, "y": 530}]
    norm = templates.normalize(doc, "fragment")
    assert norm["edges"][0]["waypoints"] == [{"x": 250, "y": 30}]
    placed = templates.instantiate(norm, 40, 80, set())
    assert placed["edges"][0]["waypoints"] == [{"x": 290, "y": 110}]


def test_agent_sets_clears_and_layout_drops_waypoints(mcp):  # noqa: F811
    m, _ = mcp
    tab = m.call("list_workspaces")["workspaces"][0]["canvases"][0]["id"]
    m.call("add_elements", canvas_id=tab, nodes=[
        {"id": "a", "text": "A", "x": 0, "y": 0}, {"id": "b", "text": "B", "x": 400, "y": 200},
        {"id": "c", "text": "C", "x": 0, "y": 400}, {"id": "d", "text": "D", "x": 400, "y": 600},
    ], edges=[
        {"id": "ab", "fromNode": "a", "toNode": "b", "waypoints": [{"x": 300, "y": 30.2}]},
        {"id": "cd", "fromNode": "c", "toNode": "d", "waypoints": [{"x": 300, "y": 430}]},
    ])
    edges = {e["id"]: e for e in m.call("get_canvas", canvas_id=tab)["data"]["edges"]}
    assert edges["ab"]["waypoints"] == [{"x": 300, "y": 30}]

    m.call("update_elements", canvas_id=tab, updates=[
        {"id": "ab", "set": {"waypoints": [{"x": 200, "y": 30}, {"x": 200, "y": 230}]}}])
    edges = {e["id"]: e for e in m.call("get_canvas", canvas_id=tab)["data"]["edges"]}
    assert len(edges["ab"]["waypoints"]) == 2
    assert "waypoints go on edges" in m.error("update_elements", canvas_id=tab, updates=[
        {"id": "a", "set": {"waypoints": [{"x": 0, "y": 0}]}}])
    assert "waypoints" in m.error("add_elements", canvas_id=tab, edges=[
        {"fromNode": "a", "toNode": "c", "waypoints": [{"x": "far"}]}])

    # Moving a node by hand (or by agent) leaves the route alone ...
    m.call("update_elements", canvas_id=tab, updates=[{"id": "b", "set": {"x": 600}}])
    edges = {e["id"]: e for e in m.call("get_canvas", canvas_id=tab)["data"]["edges"]}
    assert len(edges["ab"]["waypoints"]) == 2
    # ... but layout clears it on lines whose ends it moved, and only those.
    out = m.call("layout", canvas_id=tab, node_ids=["a", "b"])
    assert out["routes_cleared"] == 1
    edges = {e["id"]: e for e in m.call("get_canvas", canvas_id=tab)["data"]["edges"]}
    assert "waypoints" not in edges["ab"] and edges["cd"]["waypoints"] == [{"x": 300, "y": 430}]

    m.call("update_elements", canvas_id=tab, updates=[{"id": "cd", "set": {"waypoints": None}}])
    edges = {e["id"]: e for e in m.call("get_canvas", canvas_id=tab)["data"]["edges"]}
    assert "waypoints" not in edges["cd"]

"""Phase 3 (editor): style extensions, templates, attachments, links."""

import pytest

from nodewright import canvas_format, ops

from .test_phase2 import first_canvas, mcp  # noqa: F401  (fixture)


def doc():
    return {"nodes": [], "edges": []}


# --- style extensions --------------------------------------------------------

def test_style_attributes_must_be_strings_but_values_are_open():
    d = {"nodes": [{"id": "a", "type": "text", "text": "", "x": 0, "y": 0, "width": 9, "height": 9,
                    "styleAttributes": {"shape": "some-future-shape", "x": None}}], "edges": []}
    canvas_format.validate(d)
    d["nodes"][0]["styleAttributes"] = {"shape": 3}
    with pytest.raises(canvas_format.CanvasError):
        canvas_format.validate(d)
    d["nodes"][0]["styleAttributes"] = "diamond"
    with pytest.raises(canvas_format.CanvasError):
        canvas_format.validate(d)


def test_agent_styles_are_checked_and_shapes_grow():
    d = doc()
    ops.add_elements([{"id": "q", "text": "Ready?", "styleAttributes": {"shape": "diamond"}},
                      {"id": "p", "text": "Ready?"}],
                     [{"fromNode": "q", "toNode": "p",
                       "styleAttributes": {"path": "short-dashed", "lineWidth": 4, "arrow": None}}])(d)
    by = {n["id"]: n for n in d["nodes"]}
    q, p = by["q"], by["p"]
    assert q["styleAttributes"] == {"shape": "diamond"}
    assert q["width"] > p["width"] and q["height"] > p["height"]
    assert d["edges"][0]["styleAttributes"] == {"path": "short-dashed", "lineWidth": "4"}
    canvas_format.validate(d)

    with pytest.raises(ops.OpError, match="shape must be one of"):
        ops.add_elements([{"text": "x", "styleAttributes": {"shape": "hexagon"}}], [])(doc())
    with pytest.raises(ops.OpError, match="unknown key"):
        ops.add_elements([{"text": "x", "styleAttributes": {"path": "dotted"}}], [])(doc())


def test_update_merges_style_attributes():
    d = doc()
    ops.add_elements([{"id": "a", "text": "A", "styleAttributes": {"shape": "pill",
                                                                   "border": "dashed"}}], [])(d)
    d["nodes"][0]["styleAttributes"]["future"] = "kept"
    ops.update_elements([{"id": "a", "set": {"styleAttributes": {"shape": "database",
                                                                 "border": None}}}])(d)
    assert d["nodes"][0]["styleAttributes"] == {"shape": "database", "future": "kept"}
    with pytest.raises(ops.OpError):
        ops.update_elements([{"id": "a", "set": {"styleAttributes": {"shape": "star"}}}])(d)
    ops.update_elements([{"id": "a", "set": {"styleAttributes": {"shape": None, "future": None}}}])(d)
    assert "styleAttributes" not in d["nodes"][0]


def test_mcp_documents_styles(mcp):  # noqa: F811
    m, _ = mcp
    tools = {t["name"]: t for t in m.rpc("tools/list").json()["result"]["tools"]}
    schema = str(tools["add_elements"]["inputSchema"])
    assert "predefined-process" in schema and "short-dashed" in schema

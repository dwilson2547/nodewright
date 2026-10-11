import pytest

from nodewright.canvas_format import CanvasError, validate


def node(i, **kw):
    return {"id": i, "type": "text", "text": "", "x": 0, "y": 0, "width": 100, "height": 50, **kw}


def test_unknown_keys_survive_and_geometry_is_rounded():
    doc = {"nodes": [node("a", x=10.6, styleAttributes={"shape": "diamond"})],
           "edges": [], "extra": {"keep": True}}
    out = validate(doc)
    assert out["nodes"][0]["x"] == 11
    assert out["nodes"][0]["styleAttributes"] == {"shape": "diamond"}
    assert out["extra"] == {"keep": True}


def test_missing_arrays_are_allowed():
    assert validate({}) == {"nodes": [], "edges": []}


@pytest.mark.parametrize("doc,msg", [
    ([], "JSON object"),
    ({"nodes": [node("a"), node("a")]}, "duplicate"),
    ({"nodes": [node("a", type="shape")]}, "type"),
    ({"nodes": [node("a", x="1")]}, "number"),
    ({"nodes": [node("a", width=0)]}, "positive"),
    ({"nodes": [node("a", x=float("nan"))]}, "finite"),
    ({"nodes": [{**node("a"), "text": 5}]}, "string"),
    ({"nodes": [node("a")], "edges": [{"id": "e", "fromNode": "a", "toNode": "b"}]}, "does not exist"),
    ({"nodes": [node("a")], "edges": [{"id": "a", "fromNode": "a", "toNode": "a"}]}, "unique"),
    ({"nodes": [node("a")], "edges": [{"id": "e", "fromNode": "a", "toNode": "a", "toEnd": "dot"}]}, "toEnd"),
])
def test_rejects(doc, msg):
    with pytest.raises(CanvasError, match=msg):
        validate(doc)

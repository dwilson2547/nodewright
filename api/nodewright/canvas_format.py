"""JSON Canvas 1.0 validation (https://jsoncanvas.org/spec/1.0/).

Checks what would make a document unusable — missing ids, dangling edges,
non-numeric geometry — and leaves everything else alone. Unknown keys on the
document, nodes and edges are kept untouched: that is where style extensions
live (design §3.2), and dropping them would lose data on every save.
"""

from __future__ import annotations

NODE_TYPES = {"text", "file", "link", "group"}
SIDES = {"top", "right", "bottom", "left"}
ENDS = {"none", "arrow"}
GEOMETRY = ("x", "y", "width", "height")
MAX_NODES = 20_000
MAX_EDGES = 40_000


class CanvasError(ValueError):
    pass


def _int(value, where: str) -> int:
    # The spec says integer; editors produce floats while dragging, so round
    # rather than reject. bool is an int subclass and is not a coordinate.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CanvasError(f"{where} must be a number")
    if value != value or value in (float("inf"), float("-inf")):
        raise CanvasError(f"{where} must be finite")
    return int(round(value))


def _str(obj: dict, key: str, where: str, required: bool = False) -> None:
    if key not in obj:
        if required:
            raise CanvasError(f"{where}.{key} is required")
        return
    if not isinstance(obj[key], str):
        raise CanvasError(f"{where}.{key} must be a string")


def _style(obj: dict, where: str) -> None:
    sa = obj.get("styleAttributes")
    if sa is None:
        return
    if not isinstance(sa, dict) or not all(isinstance(v, (str, type(None))) for v in sa.values()):
        raise CanvasError(f"{where}.styleAttributes must be an object of strings")


def validate(doc) -> dict:
    """Return a normalized copy of doc (geometry rounded to integers) or raise
    CanvasError naming the first problem."""
    if not isinstance(doc, dict):
        raise CanvasError("a canvas must be a JSON object")
    out = dict(doc)
    nodes = doc.get("nodes", [])
    edges = doc.get("edges", [])
    if not isinstance(nodes, list):
        raise CanvasError("nodes must be an array")
    if not isinstance(edges, list):
        raise CanvasError("edges must be an array")
    if len(nodes) > MAX_NODES or len(edges) > MAX_EDGES:
        raise CanvasError("canvas is too large")

    ids: set[str] = set()
    out_nodes = []
    for i, node in enumerate(nodes):
        where = f"nodes[{i}]"
        if not isinstance(node, dict):
            raise CanvasError(f"{where} must be an object")
        _str(node, "id", where, required=True)
        _str(node, "type", where, required=True)
        if not node["id"]:
            raise CanvasError(f"{where}.id is empty")
        if node["id"] in ids:
            raise CanvasError(f"duplicate id {node['id']!r}")
        ids.add(node["id"])
        if node["type"] not in NODE_TYPES:
            raise CanvasError(f"{where}.type {node['type']!r} is not one of {sorted(NODE_TYPES)}")
        n = dict(node)
        for key in GEOMETRY:
            if key not in node:
                raise CanvasError(f"{where}.{key} is required")
            n[key] = _int(node[key], f"{where}.{key}")
        if n["width"] < 1 or n["height"] < 1:
            raise CanvasError(f"{where} must have a positive size")
        _str(node, "color", where)
        _style(node, where)
        if node["type"] == "text":
            _str(node, "text", where, required=True)
        elif node["type"] == "file":
            _str(node, "file", where, required=True)
            _str(node, "subpath", where)
        elif node["type"] == "link":
            _str(node, "url", where, required=True)
        elif node["type"] == "group":
            _str(node, "label", where)
            _str(node, "background", where)
            _str(node, "backgroundStyle", where)
        out_nodes.append(n)

    edge_ids: set[str] = set()
    for i, edge in enumerate(edges):
        where = f"edges[{i}]"
        if not isinstance(edge, dict):
            raise CanvasError(f"{where} must be an object")
        for key in ("id", "fromNode", "toNode"):
            _str(edge, key, where, required=True)
        if not edge["id"] or edge["id"] in ids or edge["id"] in edge_ids:
            raise CanvasError(f"{where}.id is empty or not unique")
        edge_ids.add(edge["id"])
        for key in ("fromNode", "toNode"):
            if edge[key] not in ids:
                raise CanvasError(f"{where}.{key} points at a node that does not exist")
        for key in ("fromSide", "toSide"):
            if key in edge and edge[key] not in SIDES:
                raise CanvasError(f"{where}.{key} must be one of {sorted(SIDES)}")
        for key in ("fromEnd", "toEnd"):
            if key in edge and edge[key] not in ENDS:
                raise CanvasError(f"{where}.{key} must be one of {sorted(ENDS)}")
        _str(edge, "color", where)
        _str(edge, "label", where)
        _style(edge, where)

    out["nodes"] = out_nodes
    out["edges"] = list(edges)
    return out


def empty() -> dict:
    return {"nodes": [], "edges": []}

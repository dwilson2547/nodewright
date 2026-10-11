"""Node ports (design §13.1): named connection points on a node's boundary.

A node may carry `ports: [{id, side, at, label?}]`, where `at` is the
fraction along that side (0 = top/left end, 1 = bottom/right end). An edge
names one with `fromPort` / `toPort` and keeps `fromSide` / `toSide` equal to
that port's side, so readers that don't know ports still attach it to the
right side. An edge whose port has gone keeps the name and falls back to its
side; the editor flags it.
"""

from __future__ import annotations

SIDES = ("top", "right", "bottom", "left")
MAX_PORTS = 64
MAX_ID = 64
MAX_LABEL = 100
ENDS = (("fromNode", "fromPort", "fromSide"), ("toNode", "toPort", "toSide"))


def check(value, where: str) -> list[dict]:
    """A normalised copy of a node's `ports`, or ValueError naming the problem."""
    if not isinstance(value, list):
        raise ValueError(f"{where}.ports must be an array")
    if len(value) > MAX_PORTS:
        raise ValueError(f"{where}.ports has more than {MAX_PORTS} ports")
    out, seen = [], set()
    for i, p in enumerate(value):
        w = f"{where}.ports[{i}]"
        if not isinstance(p, dict):
            raise ValueError(f"{w} must be an object")
        pid = p.get("id")
        if not isinstance(pid, str) or not pid or len(pid) > MAX_ID:
            raise ValueError(f"{w}.id must be a non-empty string of at most {MAX_ID} characters")
        if pid in seen:
            raise ValueError(f"{w}.id {pid!r} is used twice")
        seen.add(pid)
        if p.get("side") not in SIDES:
            raise ValueError(f"{w}.side must be one of {list(SIDES)}")
        at = p.get("at", 0.5)
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not 0 <= at <= 1:
            raise ValueError(f"{w}.at must be a number from 0 to 1")
        port = {"id": pid, "side": p["side"], "at": round(float(at), 4)}
        label = p.get("label")
        if label is not None:
            if not isinstance(label, str) or len(label) > MAX_LABEL:
                raise ValueError(f"{w}.label must be a string of at most {MAX_LABEL} characters")
            if label:
                port["label"] = label
        out.append(port)
    return out


def check_edge(edge: dict, where: str) -> None:
    for _, key, _ in ENDS:
        if key in edge and (not isinstance(edge[key], str) or not edge[key]):
            raise ValueError(f"{where}.{key} must be a non-empty string")


def find(node: dict | None, port_id: str) -> dict | None:
    if not node:
        return None
    return next((p for p in node.get("ports") or [] if p.get("id") == port_id), None)


def require(edge: dict, nodes: dict[str, dict]) -> None:
    """Agent writes: every port an edge names must exist on its node."""
    for node_key, key, _ in ENDS:
        if key in edge and find(nodes.get(edge[node_key]), edge[key]) is None:
            raise ValueError(f"node {edge[node_key]!r} has no port {edge[key]!r}")


def sync(data: dict) -> None:
    """Set each edge's side to the side of the port it names, where that port exists."""
    nodes = {n["id"]: n for n in data["nodes"]}
    for e in data["edges"]:
        for node_key, key, side_key in ENDS:
            port = find(nodes.get(e.get(node_key)), e[key]) if key in e else None
            if port is not None:
                e[side_key] = port["side"]

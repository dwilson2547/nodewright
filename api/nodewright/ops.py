"""Canvas edits as operations, for agents (design §7).

An agent never sends a whole document. It sends "add these", "change that",
"lay these out", and the server applies it to whatever the current revision
is. So an agent cannot clobber a concurrent edit by writing a stale copy, and
it never has to invent coordinates: nodes without x/y are placed by layout.py.
"""

from __future__ import annotations

import copy
import json
import math
import secrets
from typing import Callable

from sqlalchemy import update
from sqlalchemy.orm import Session

from . import access, canvas_format, events, leases, layout
from .layout import GRID, GROUP_PAD, NODE_GAP, RANK_GAP, snap
from .models import Canvas, CanvasRevision, User, utcnow

RETRIES = 3
CHAR_W = 8
LINE_H = 24
MIN_W, MAX_W = 160, 360
MIN_H = 60
GROUP_MIN = (200, 120)
IMMUTABLE = {"id", "type"}


class OpError(ValueError):
    """The request was understood but can't be applied; the message is for the agent."""


def new_id() -> str:
    return secrets.token_hex(8)


# --- sizing -------------------------------------------------------------------

def _text_of(node: dict) -> str:
    t = node.get("type", "text")
    if t == "text":
        return node.get("text", "")
    if t == "link":
        return node.get("url", "")
    if t == "file":
        return node.get("file", "")
    return node.get("label", "")


def auto_size(node: dict) -> tuple[int, int]:
    """A size that fits the node's text at the UI's default font, on the grid."""
    if node.get("type") == "group":
        return GROUP_MIN
    lines = _text_of(node).split("\n") or [""]
    longest = max(len(line) for line in lines)
    w = min(MAX_W, max(MIN_W, longest * CHAR_W + 40))
    per_line = max(1, (w - 40) // CHAR_W)
    rows = sum(max(1, math.ceil(len(line) / per_line)) for line in lines)
    h = max(MIN_H, rows * LINE_H + 36)
    return int(math.ceil(w / GRID) * GRID), int(math.ceil(h / GRID) * GRID)


# --- geometry -----------------------------------------------------------------

def _box(n: dict) -> tuple[int, int, int, int]:
    return n["x"], n["y"], n["x"] + n["width"], n["y"] + n["height"]


def _inside(inner: dict, outer: dict) -> bool:
    a, b = _box(inner), _box(outer)
    return a[0] >= b[0] and a[1] >= b[1] and a[2] <= b[2] and a[3] <= b[3]


def containment(nodes: list[dict]) -> dict[str, str]:
    """child id -> innermost group containing it, judged by geometry (JSON
    Canvas has no parent field; Obsidian decides membership the same way)."""
    groups = sorted((n for n in nodes if n.get("type") == "group"),
                    key=lambda g: g["width"] * g["height"])
    parent: dict[str, str] = {}
    for n in nodes:
        for g in groups:
            if g["id"] != n["id"] and _inside(n, g) and not (
                    n.get("type") == "group" and g["width"] * g["height"]
                    <= n["width"] * n["height"]):
                parent[n["id"]] = g["id"]
                break
    return parent


def _bbox(nodes: list[dict]) -> tuple[int, int, int, int] | None:
    if not nodes:
        return None
    return (min(n["x"] for n in nodes), min(n["y"] for n in nodes),
            max(n["x"] + n["width"] for n in nodes), max(n["y"] + n["height"] for n in nodes))


def _shift(nodes: list[dict], dx: int, dy: int) -> None:
    for n in nodes:
        n["x"] += dx
        n["y"] += dy


def _fit_group(group: dict, nodes: list[dict]) -> None:
    """Grow `group` (never shrink it) to contain `nodes` with padding."""
    bb = _bbox(nodes)
    if bb is None:
        return
    x0, y0 = min(group["x"], bb[0] - GROUP_PAD), min(group["y"], bb[1] - GROUP_PAD)
    x1 = max(group["x"] + group["width"], bb[2] + GROUP_PAD)
    y1 = max(group["y"] + group["height"], bb[3] + GROUP_PAD)
    group["x"], group["y"], group["width"], group["height"] = x0, y0, x1 - x0, y1 - y0


# --- the write path -----------------------------------------------------------

def mutate(s: Session, user: User, canvas_id: str, who: leases.Holder,
           fn: Callable[[dict], object], max_bytes: int,
           action: str = access.CANVAS_EDIT) -> tuple[Canvas, object]:
    """Apply `fn` to a copy of the current document and save it as a new
    revision, retrying if someone else saved in between. Takes or renews the
    caller's lease first, so a locked canvas fails before any work is done."""
    for _ in range(RETRIES):
        c = access.canvas(s, user, canvas_id, action)
        leases.take(s, canvas_id, who)
        base = c.revision
        data = copy.deepcopy(c.data)
        result = fn(data)
        try:
            data = canvas_format.validate(data)
        except canvas_format.CanvasError as exc:
            raise OpError(f"that would make the canvas invalid: {exc}") from None
        if len(json.dumps(data)) > max_bytes:
            raise OpError("that would make the canvas too large")
        now = utcnow()
        done = s.execute(update(Canvas)
                         .where(Canvas.id == c.id, Canvas.revision == base)
                         .values(revision=base + 1, data=data, updated_at=now)
                         .execution_options(synchronize_session=False)).rowcount
        if done == 1:
            s.add(CanvasRevision(canvas_id=c.id, revision=base + 1, data=data, user_id=user.id,
                                 source="mcp"))
            c.workspace.updated_at = now
            events.queue(s, c.id, {"type": "revision", "revision": base + 1, "source": "mcp",
                                   "by": who.label, "client": who.key})
            s.flush()
            s.refresh(c)
            return c, result
        s.expire_all()
    raise OpError("the canvas is being edited too quickly; try again")


# --- operations (each is fn(data) for mutate) ---------------------------------

def _clean_node(raw: dict, ids: set[str]) -> dict:
    if not isinstance(raw, dict):
        raise OpError("each node must be an object")
    n = {k: v for k, v in raw.items() if v is not None}
    n.setdefault("type", "text")
    if n["type"] not in canvas_format.NODE_TYPES:
        raise OpError(f"node type must be one of {sorted(canvas_format.NODE_TYPES)}")
    if n["type"] == "text":
        n.setdefault("text", "")
    if "id" in n:
        if not isinstance(n["id"], str) or not n["id"] or n["id"] in ids:
            raise OpError(f"node id {n.get('id')!r} is empty or already used")
    else:
        n["id"] = new_id()
    ids.add(n["id"])
    return n


def _clean_edge(raw: dict, ids: set[str]) -> dict:
    if not isinstance(raw, dict):
        raise OpError("each edge must be an object")
    e = {k: v for k, v in raw.items() if v is not None}
    for k in ("fromNode", "toNode"):
        if k not in e:
            raise OpError(f"edge needs {k}")
    if "id" in e:
        if not isinstance(e["id"], str) or not e["id"] or e["id"] in ids:
            raise OpError(f"edge id {e.get('id')!r} is empty or already used")
    else:
        e["id"] = new_id()
    ids.add(e["id"])
    return e


def add_elements(nodes: list[dict], edges: list[dict], direction: str = "TB"):
    """Op: add nodes and edges. Nodes may name a `group` (a new or existing
    group node id) to be placed inside it. Unpositioned nodes are laid out."""
    tb = direction.upper() != "LR"

    def op(data: dict) -> dict:
        existing = data["nodes"]
        by_id = {n["id"]: n for n in existing}
        ids = set(by_id) | {e["id"] for e in data["edges"]}
        new = [_clean_node(n, ids) for n in nodes]
        new_edges = [_clean_edge(e, ids) for e in edges]
        new_by_id = {n["id"]: n for n in new}

        parent: dict[str, str] = {}
        for n in new:
            g = n.pop("group", None)
            if g is None:
                continue
            target = new_by_id.get(g) or by_id.get(g)
            if target is None or target.get("type") != "group":
                raise OpError(f"group {g!r} is not a group node")
            if g == n["id"]:
                raise OpError("a node can't be inside itself")
            parent[n["id"]] = g

        for n in new:
            if "width" not in n or "height" not in n:
                w, h = auto_size(n)
                n.setdefault("width", w)
                n.setdefault("height", h)

        placed = [n for n in new if "x" in n and "y" in n]
        unplaced = {n["id"] for n in new if n not in placed}
        children: dict[str, list[str]] = {}
        for c, g in parent.items():
            if c in unplaced and g in new_by_id and g in unplaced:
                children.setdefault(g, []).append(c)
        # Blocks to place: by container (None = canvas root, else an existing
        # or already-positioned group).
        blocks: dict[str | None, list[str]] = {}
        for n in new:
            i = n["id"]
            if i not in unplaced:
                continue
            g = parent.get(i)
            if g is not None and g in unplaced:
                continue  # placed with its group
            blocks.setdefault(g, []).append(i)

        sizes = {n["id"]: (n["width"], n["height"]) for n in new}
        pairs = [(e["fromNode"], e["toNode"]) for e in new_edges]
        all_nodes = existing + placed

        for container, top in blocks.items():
            boxes, (bw, bh) = layout.compound(top, children, sizes, pairs, direction)
            ox, oy = _anchor(container, top, children, boxes, (bw, bh), all_nodes,
                             {**by_id, **new_by_id}, new_edges + data["edges"], tb)
            placed_now = []
            for i, (x, y, w, h) in boxes.items():
                n = new_by_id[i]
                n["x"], n["y"], n["width"], n["height"] = ox + x, oy + y, w, h
                placed_now.append(n)
            all_nodes = all_nodes + placed_now
            if container is not None:
                group = by_id.get(container) or new_by_id[container]
                _fit_group(group, placed_now)

        # Positioned nodes inside a positioned group: grow the group to fit.
        for c, g in parent.items():
            if c not in unplaced or g not in unplaced:
                grp = by_id.get(g) or new_by_id[g]
                _fit_group(grp, [new_by_id[c]])

        # Groups go first so they render beneath what they contain.
        new_groups = [n for n in new if n["type"] == "group"]
        others = [n for n in new if n["type"] != "group"]
        data["nodes"] = new_groups + existing + others
        data["edges"] = data["edges"] + new_edges
        return {"node_ids": [n["id"] for n in new], "edge_ids": [e["id"] for e in new_edges]}

    return op


def _anchor(container, top, children, boxes, block, all_nodes, every, edges, tb):
    """Where the block's top-left goes."""
    bw, bh = block
    if container is not None:
        grp = every[container]
        if "x" not in grp:
            raise OpError(f"group {container!r} has no position")
        inside = [n for n in all_nodes if n["id"] != container and "x" in n and _inside(n, grp)]
        bb = _bbox(inside)
        x = grp["x"] + GROUP_PAD
        y = (bb[3] + NODE_GAP) if bb else grp["y"] + GROUP_PAD
        if not tb and bb:
            x, y = bb[2] + NODE_GAP, grp["y"] + GROUP_PAD
        return snap(x), snap(y)

    members = set(boxes)
    linked = []
    for e in edges:
        a, b = e["fromNode"], e["toNode"]
        other = b if a in members else a if b in members else None
        if other is not None and other not in members:
            n = every.get(other)
            if n is not None and "x" in n:
                linked.append(n)
    if linked:
        bb = _bbox(linked)
        if tb:
            return snap((bb[0] + bb[2]) / 2 - bw / 2), snap(bb[3] + RANK_GAP)
        return snap(bb[2] + RANK_GAP), snap((bb[1] + bb[3]) / 2 - bh / 2)
    bb = _bbox([n for n in all_nodes if "x" in n])
    if bb is None:
        return 0, 0
    if tb:
        return snap(bb[2] + RANK_GAP * 2), snap(bb[1])
    return snap(bb[0]), snap(bb[3] + RANK_GAP * 2)


def update_elements(updates: list[dict]):
    """Op: set or remove (null) keys on existing nodes and edges."""

    def op(data: dict) -> dict:
        index = {n["id"]: n for n in data["nodes"]} | {e["id"]: e for e in data["edges"]}
        changed = []
        for u in updates:
            if not isinstance(u, dict) or not isinstance(u.get("set"), dict):
                raise OpError("each update is {id, set: {key: value or null}}")
            target = index.get(u.get("id"))
            if target is None:
                raise OpError(f"no node or edge with id {u.get('id')!r}")
            for k, v in u["set"].items():
                if k in IMMUTABLE:
                    raise OpError(f"{k} can't be changed; delete and re-add instead")
                if v is None:
                    target.pop(k, None)
                else:
                    target[k] = v
            if u.get("fit") and "type" in target and target["type"] != "group":
                target["width"], target["height"] = auto_size(target)
            changed.append(target["id"])
        return {"updated": changed}

    return op


def delete_elements(ids: list[str]):
    """Op: delete nodes and edges; edges touching a deleted node go too.
    Deleting a group leaves its contents where they are."""

    def op(data: dict) -> dict:
        gone = set(ids)
        known = {n["id"] for n in data["nodes"]} | {e["id"] for e in data["edges"]}
        missing = gone - known
        if missing:
            raise OpError(f"no such ids: {sorted(missing)[:10]}")
        data["nodes"] = [n for n in data["nodes"] if n["id"] not in gone]
        before = len(data["edges"])
        data["edges"] = [e for e in data["edges"] if e["id"] not in gone
                         and e["fromNode"] not in gone and e["toNode"] not in gone]
        return {"deleted": len(gone), "edges_removed": before - len(data["edges"])}

    return op


def relayout(node_ids: list[str] | None, direction: str = "TB"):
    """Op: re-place the given nodes (default: all), keeping the block's
    top-left where it was. Selecting a group brings its contents along;
    groups are resized to fit."""

    def op(data: dict) -> dict:
        nodes = data["nodes"]
        by_id = {n["id"]: n for n in nodes}
        parent = containment(nodes)
        kids: dict[str, list[str]] = {}
        for c, g in parent.items():
            kids.setdefault(g, []).append(c)
        chosen = set(by_id) if not node_ids else set(node_ids)
        unknown = chosen - set(by_id)
        if unknown:
            raise OpError(f"no such nodes: {sorted(unknown)[:10]}")
        stack = list(chosen)
        while stack:
            for k in kids.get(stack.pop(), []):
                if k not in chosen:
                    chosen.add(k)
                    stack.append(k)
        top = [i for i in by_id if i in chosen and parent.get(i) not in chosen]
        children = {g: [k for k in ks if k in chosen] for g, ks in kids.items() if g in chosen}
        # A group with contents is refitted from scratch; anything else keeps its size.
        sizes = {i: ((MIN_W, MIN_H) if children.get(i)
                     else (by_id[i]["width"], by_id[i]["height"])) for i in chosen}
        pairs = [(e["fromNode"], e["toNode"]) for e in data["edges"]]
        before = _bbox([by_id[i] for i in chosen])
        boxes, _ = layout.compound(top, children, sizes, pairs, direction)
        ox, oy = snap(before[0]), snap(before[1])
        for i, (x, y, w, h) in boxes.items():
            n = by_id[i]
            n["x"], n["y"], n["width"], n["height"] = ox + x, oy + y, w, h
        return {"laid_out": len(boxes)}

    return op


def summary(c: Canvas) -> dict:
    nodes = c.data.get("nodes", [])
    return {"id": c.id, "name": c.name, "revision": c.revision, "nodes": len(nodes),
            "edges": len(c.data.get("edges", []))}

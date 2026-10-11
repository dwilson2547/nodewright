"""Templates (design §4): built-in and per-user canvas pieces.

A template's data is a JSON Canvas document whose bounding box starts at
(0, 0). Inserting one copies it with fresh ids, offset to where it's dropped.
Built-in ids start with "builtin:" and live here, not in the database.
"""

from __future__ import annotations

import copy
import json
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import canvas_format
from .models import Template, User, UserPrefs, utcnow

KINDS = ("stencil", "fragment", "page")
BUILTIN_PREFIX = "builtin:"
MAX_PER_USER = 300
MAX_BYTES = 512 * 1024
BLANK = BUILTIN_PREFIX + "blank"


class TemplateError(ValueError):
    pass


# --- built-ins ---------------------------------------------------------------

def _n(id, x, y, w, h, text, shape=None, color=None, align="center", **extra):
    node = {"id": id, "type": "text", "text": text, "x": x, "y": y, "width": w, "height": h}
    sa = {}
    if shape:
        sa["shape"] = shape
    if align:
        sa["textAlign"] = align
    if sa:
        node["styleAttributes"] = sa
    if color:
        node["color"] = color
    node.update(extra)
    return node


def _g(id, x, y, w, h, label, color=None):
    node = {"id": id, "type": "group", "label": label, "x": x, "y": y, "width": w, "height": h}
    if color:
        node["color"] = color
    return node


def _e(id, a, b, label=None, fs=None, ts=None, **sa):
    edge = {"id": id, "fromNode": a, "toNode": b}
    if label:
        edge["label"] = label
    if fs:
        edge["fromSide"] = fs
    if ts:
        edge["toSide"] = ts
    if sa:
        edge["styleAttributes"] = sa
    return edge


def _doc(nodes, edges=()):
    return {"nodes": list(nodes), "edges": list(edges)}


_BUILTIN = [
    # stencils
    ("process", "Process", "stencil", _doc([_n("n", 0, 0, 200, 80, "Process")])),
    ("decision", "Decision", "stencil", _doc([_n("n", 0, 0, 220, 140, "Decision?", "diamond")])),
    ("terminal", "Start / end", "stencil", _doc([_n("n", 0, 0, 180, 60, "Start", "pill")])),
    ("io", "Input / output", "stencil",
     _doc([_n("n", 0, 0, 220, 80, "Input / output", "parallelogram")])),
    ("database", "Database", "stencil", _doc([_n("n", 0, 0, 160, 120, "Database", "database")])),
    ("document", "Document", "stencil", _doc([_n("n", 0, 0, 200, 100, "Document", "document")])),
    ("subroutine", "Subroutine", "stencil",
     _doc([_n("n", 0, 0, 220, 80, "Subroutine", "predefined-process")])),
    ("actor", "Actor / service", "stencil", _doc([_n("n", 0, 0, 160, 100, "Service", "circle")])),
    ("note", "Sticky note", "stencil",
     _doc([_n("n", 0, 0, 240, 120, "Note", None, "3", None,
              styleAttributes={"border": "invisible"})])),
    ("group", "Group", "stencil", _doc([_g("n", 0, 0, 400, 260, "Group")])),
    # fragments
    ("yes-no", "Yes / no branch", "fragment", _doc(
        [_n("q", 120, 0, 220, 140, "Condition?", "diamond"),
         _n("y", 0, 220, 200, 80, "Then"),
         _n("n", 260, 220, 200, 80, "Otherwise")],
        [_e("e1", "q", "y", "Yes", "bottom", "top", pathfindingMethod="square"),
         _e("e2", "q", "n", "No", "bottom", "top", pathfindingMethod="square")])),
    ("three-tier", "Client → API → database", "fragment", _doc(
        [_n("c", 0, 20, 180, 80, "Client"),
         _n("a", 280, 20, 180, 80, "API"),
         _n("d", 560, 0, 160, 120, "Database", "database")],
        [_e("e1", "c", "a", "HTTPS", "right", "left"),
         _e("e2", "a", "d", "SQL", "right", "left")])),
    ("lanes", "Two swimlanes", "fragment", _doc(
        [_g("a", 0, 0, 900, 220, "Lane A", "5"), _g("b", 0, 260, 900, 220, "Lane B", "4")])),
    # pages
    ("blank", "Blank", "page", _doc([])),
    ("flowchart", "Flowchart", "page", _doc(
        [_n("s", 30, 0, 180, 60, "Start", "pill", "4"),
         _n("p", 20, 140, 200, 80, "Do the thing"),
         _n("q", 10, 300, 220, 140, "Did it work?", "diamond"),
         _n("f", 340, 330, 200, 80, "Fix it"),
         _n("e", 30, 520, 180, 60, "End", "pill", "1")],
        [_e("e1", "s", "p", None, "bottom", "top"),
         _e("e2", "p", "q", None, "bottom", "top"),
         _e("e3", "q", "e", "Yes", "bottom", "top"),
         _e("e4", "q", "f", "No", "right", "left"),
         _e("e5", "f", "p", None, "top", "right", pathfindingMethod="square")])),
    ("architecture", "System architecture", "page", _doc(
        [_g("gc", 0, 0, 260, 340, "Clients", "6"),
         _n("web", 40, 40, 180, 80, "Web app"),
         _n("cli", 40, 200, 180, 80, "Agents (MCP)"),
         _g("gs", 340, 0, 260, 340, "Services", "5"),
         _n("api", 380, 40, 180, 80, "API"),
         _n("wrk", 380, 200, 180, 80, "Worker"),
         _g("gd", 680, 0, 260, 340, "Data", "4"),
         _n("db", 730, 30, 160, 120, "Postgres", "database"),
         _n("obj", 730, 190, 160, 120, "Object store", "database")],
        [_e("e1", "web", "api", None, "right", "left"),
         _e("e2", "cli", "api", None, "right", "left"),
         _e("e3", "api", "db", None, "right", "left"),
         _e("e4", "wrk", "obj", None, "right", "left"),
         _e("e5", "api", "wrk", "jobs", "bottom", "top", path="short-dashed")])),
    ("mindmap", "Mind map", "page", _doc(
        [_n("c", 300, 180, 220, 80, "Central idea", "pill", "6"),
         _n("a", 0, 0, 200, 70, "Branch"), _n("b", 620, 0, 200, 70, "Branch"),
         _n("d", 0, 370, 200, 70, "Branch"), _n("f", 620, 370, 200, 70, "Branch")],
        [_e("e1", "c", "a", None, "left", "right"),
         _e("e2", "c", "b", None, "right", "left"),
         _e("e3", "c", "d", None, "left", "right"),
         _e("e4", "c", "f", None, "right", "left")])),
]



# --- user templates ------------------------------------------------------------

def normalize(data, kind: str) -> dict:
    """Validate a fragment and move it so its bounding box starts at (0, 0)."""
    if kind not in KINDS:
        raise TemplateError(f"kind must be one of {list(KINDS)}")
    try:
        doc = canvas_format.validate(data)
    except canvas_format.CanvasError as exc:
        raise TemplateError(str(exc)) from None
    doc = {"nodes": doc["nodes"], "edges": doc["edges"]}
    if kind != "page" and not doc["nodes"]:
        raise TemplateError("a template needs at least one node")
    if kind == "stencil" and len(doc["nodes"]) != 1:
        raise TemplateError("a stencil is one node; use a fragment for several")
    if doc["nodes"]:
        x0 = min(n["x"] for n in doc["nodes"])
        y0 = min(n["y"] for n in doc["nodes"])
        for n in doc["nodes"]:
            n["x"] -= x0
            n["y"] -= y0
    if len(json.dumps(doc)) > MAX_BYTES:
        raise TemplateError("template is too large")
    return doc


BUILTIN: dict[str, dict] = {
    BUILTIN_PREFIX + key: {"id": BUILTIN_PREFIX + key, "name": name, "kind": kind,
                           "builtin": True, "data": normalize(data, kind)}
    for key, name, kind, data in _BUILTIN
}


def out(t: Template | dict, with_data: bool = True) -> dict:
    if isinstance(t, dict):
        res = {k: v for k, v in t.items() if with_data or k != "data"}
    else:
        res = {"id": t.id, "name": t.name, "kind": t.kind, "builtin": False,
               "updated_at": t.updated_at.isoformat()}
        if with_data:
            res["data"] = t.data
    return res


def mine(s: Session, user: User) -> list[Template]:
    return list(s.scalars(select(Template).where(Template.owner_id == user.id)
                          .order_by(Template.kind, Template.name)))


def get(s: Session, user: User, tid: str) -> dict | None:
    if tid in BUILTIN:
        return BUILTIN[tid]
    t = s.get(Template, tid)
    if t is None or t.owner_id != user.id:
        return None
    return out(t)


def create(s: Session, user: User, name: str, kind: str, data) -> Template:
    if s.query(Template).filter(Template.owner_id == user.id).count() >= MAX_PER_USER:
        raise TemplateError(f"you can keep at most {MAX_PER_USER} templates")
    t = Template(owner_id=user.id, name=name.strip(), kind=kind, data=normalize(data, kind))
    s.add(t)
    s.flush()
    return t


def default_page_id(s: Session, user: User) -> str:
    p = s.get(UserPrefs, user.id)
    tid = p.default_page if p else None
    if tid and (tid in BUILTIN or get(s, user, tid) is not None):
        return tid
    return BLANK


def set_default_page(s: Session, user: User, tid: str) -> None:
    t = get(s, user, tid)
    if t is None or t["kind"] != "page":
        raise TemplateError("that is not one of your page templates")
    p = s.get(UserPrefs, user.id)
    if p is None:
        p = UserPrefs(user_id=user.id)
        s.add(p)
    p.default_page, p.updated_at = tid, utcnow()


def page_data(s: Session, user: User, tid: str | None) -> dict:
    """A fresh canvas document from a page template (the user's default if
    tid is None). Any template kind works: a stencil gives a one-node page."""
    t = get(s, user, tid or default_page_id(s, user))
    if t is None:
        raise TemplateError("no such template")
    return instantiate(t["data"], 0, 0, set())


def instantiate(data: dict, x: int, y: int, taken: set[str]) -> dict:
    """A copy of data with fresh ids (not in `taken`), offset by (x, y)."""
    doc = copy.deepcopy(data)
    ids: dict[str, str] = {}

    def fresh() -> str:
        while True:
            i = secrets.token_hex(8)
            if i not in taken:
                taken.add(i)
                return i

    for n in doc["nodes"]:
        new = fresh()
        ids[n["id"]] = new
        n["id"] = new
        n["x"] += x
        n["y"] += y
    for e in doc["edges"]:
        e["id"] = fresh()
        e["fromNode"], e["toNode"] = ids[e["fromNode"]], ids[e["toNode"]]
    return doc

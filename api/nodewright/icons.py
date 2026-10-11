"""Icons (design §13.2): built-in and user-uploaded SVGs that text nodes show.

A node refers to one as `icon: "icons/<id>/<name>.svg"`, a vault-relative
path like attachments, so a zip export can carry the file and Obsidian finds
it. Built-ins are a curated Lucide subset shipped in builtin_icons/ (ISC,
see its LICENSE); their ids are `lucide-<name>`. User icons live in the
`icons` table, each owned by one user. Every SVG passes svgsafe.clean()
before it is stored or served.

`tinted` is how an icon is drawn by default when placed: as a mask filled
with the node's colour (one-colour line icons), or in its own colours. A
node can override it with styleAttributes.iconColors = "original".
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import ports, svgsafe
from .models import Icon, User, utcnow

BUILTIN_DIR = Path(__file__).with_name("builtin_icons")
BUILTIN_PREFIX = "lucide-"
REF_RE = re.compile(r"^icons/([a-z0-9-]{1,64})/[^/]{1,200}\.svg$")
MAX_PER_USER = 500
MAX_NAME = 100
MAX_SOURCE = 200_000  # bytes of JSON: the icon creator's drawing


class IconError(Exception):
    def __init__(self, what: str, status: int = 422):
        super().__init__(what)
        self.status = status


def _file_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _.()-]", "", name).strip(" .")[:80] or "icon"


def ref(icon_id: str, name: str) -> str:
    return f"icons/{icon_id}/{_file_name(name)}.svg"


def id_of(file: str) -> str | None:
    m = REF_RE.match(file or "")
    return m.group(1) if m else None


@cache
def builtins() -> dict[str, dict]:
    out = {}
    for f in sorted(BUILTIN_DIR.glob("*.svg")):
        icon_id = BUILTIN_PREFIX + f.stem
        name = f.stem.replace("-", " ").capitalize()
        out[icon_id] = {"id": icon_id, "name": name, "svg": svgsafe.clean(f.read_bytes()),
                        "tinted": True, "ports": [], "builtin": True}
    return out


def out(icon: Icon | dict) -> dict:
    if isinstance(icon, dict):
        i, name, tinted, p, builtin = icon["id"], icon["name"], icon["tinted"], icon["ports"], True
    else:
        i, name, tinted, p, builtin = icon.id, icon.name, icon.tinted, icon.ports or [], False
    return {"id": i, "name": name, "file": ref(i, name), "url": f"/api/icons/{i}.svg",
            "tinted": tinted, "ports": p, "builtin": builtin,
            "editable": not builtin and icon.source is not None}


def _source(value) -> dict | None:
    """The creator's drawing is the UI's own format: stored as given, only
    shape- and size-checked. The SVG it produced is what's validated and shown."""
    if value is None:
        return None
    if not isinstance(value, dict) or len(json.dumps(value)) > MAX_SOURCE:
        raise IconError(f"source must be an object of at most {MAX_SOURCE // 1000} KB of JSON")
    return value


def mine(s: Session, user: User) -> list[Icon]:
    return list(s.scalars(select(Icon).where(Icon.owner_id == user.id)
                          .order_by(Icon.name, Icon.created_at)))


def svg_for(s: Session, icon_id: str) -> str | None:
    """Anyone holding an icon's id may fetch its SVG: canvases shared with
    members or by link show icons their viewers don't own."""
    b = builtins().get(icon_id)
    if b is not None:
        return b["svg"]
    row = s.get(Icon, icon_id) if re.fullmatch(r"[0-9a-f]{32}", icon_id) else None
    return row.svg if row else None


def _name(name) -> str:
    if not isinstance(name, str) or not name.strip():
        raise IconError("an icon needs a name")
    return name.strip()[:MAX_NAME]


def _ports(value) -> list[dict]:
    try:
        return ports.check(value or [], "icon")
    except ValueError as exc:
        raise IconError(str(exc)) from None


def create(s: Session, user: User, name, svg: str, tinted: bool, port_list=None,
           source=None) -> Icon:
    count = s.scalar(select(func.count()).select_from(Icon).where(Icon.owner_id == user.id))
    if count >= MAX_PER_USER:
        raise IconError(f"you can keep at most {MAX_PER_USER} icons")
    try:
        clean = svgsafe.clean(svg.encode())
    except svgsafe.SvgRejected as exc:
        raise IconError(str(exc)) from None
    icon = Icon(owner_id=user.id, name=_name(name), svg=clean, tinted=bool(tinted),
                ports=_ports(port_list), source=_source(source))
    s.add(icon)
    s.flush()
    return icon


def get_own(s: Session, user: User, icon_id: str) -> Icon:
    icon = s.get(Icon, icon_id)
    if icon is None or icon.owner_id != user.id:
        raise IconError("no such icon", 404)
    return icon


def update(icon: Icon, fields: dict) -> Icon:
    if "name" in fields:
        icon.name = _name(fields["name"])
    if "tinted" in fields:
        icon.tinted = bool(fields["tinted"])
    if "ports" in fields:
        icon.ports = _ports(fields["ports"])
    if "source" in fields:
        icon.source = _source(fields["source"])
    if "svg" in fields:
        try:
            icon.svg = svgsafe.clean(str(fields["svg"]).encode())
        except svgsafe.SvgRejected as exc:
            raise IconError(str(exc)) from None
    icon.updated_at = utcnow()
    return icon

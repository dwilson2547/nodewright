"""Attachments: files uploaded into a workspace and shown by `file` nodes.

A node refers to one as {"type": "file", "file": "attachments/<id>/<name>"}:
a path, as JSON Canvas expects, that still reads sensibly in Obsidian (where
the file is simply missing). Only sniffed raster images are served inline;
everything else downloads, so an upload can never run as a page here.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Attachment, Canvas, CanvasRevision, Template

PREFIX = "attachments/"
NODE_RE = re.compile(r"^attachments/([0-9a-f]{32})(?:/|$)")

# Raster images only: SVG can carry script, so it downloads like any other file.
_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
]
INLINE = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif"}


def sniff(data: bytes) -> str | None:
    """The image type the bytes really are, or None."""
    for magic, kind in _MAGIC:
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    return None


def content_type(data: bytes, declared: str | None) -> str:
    """Stored type: the sniffed image type, else what the client declared
    (informational only; it is never served as-is)."""
    image = sniff(data)
    if image:
        return image
    declared = (declared or "").split(";")[0].strip().lower()
    if re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", declared) and len(declared) <= 100:
        return declared
    return "application/octet-stream"


def clean_name(raw: str | None) -> str:
    name = unicodedata.normalize("NFC", raw or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*')
    name = name.strip(" .")[:200]
    return name or "file"


def node_file(a: Attachment) -> str:
    return f"{PREFIX}{a.id}/{a.name}"


def attachment_id(file: str) -> str | None:
    m = NODE_RE.match(file or "")
    return m.group(1) if m else None


REF_RE = re.compile(r"attachments/([0-9a-f]{32})")


def _refs(data) -> set[str]:
    return set(REF_RE.findall(json.dumps(data)))


def sweep(s: Session, now: datetime, keep_days: int) -> list[str]:
    """Delete attachments nothing points at any more and return their object
    keys. Kept: anything a canvas or a template uses, anything a revision from
    the last `keep_days` uses (so undo and restoring a recent revision still
    find their files), and anything uploaded in that window."""
    cutoff = now - timedelta(days=keep_days)
    old = s.scalars(select(Attachment).where(Attachment.created_at < cutoff)).all()
    if not old:
        return []
    by_ws: dict[str, list[Attachment]] = {}
    for a in old:
        by_ws.setdefault(a.workspace_id, []).append(a)
    used: set[str] = set()
    for data in s.scalars(select(Template.data)):
        used |= _refs(data)
    keys = []
    for ws_id, rows in by_ws.items():
        wanted = {a.id for a in rows} - used
        canvas_ids = s.scalars(select(Canvas.id).where(Canvas.workspace_id == ws_id)).all()
        for data in s.scalars(select(Canvas.data).where(Canvas.workspace_id == ws_id)):
            wanted -= _refs(data)
        if wanted and canvas_ids:
            recent = (select(CanvasRevision.data)
                      .where(CanvasRevision.canvas_id.in_(canvas_ids),
                             CanvasRevision.created_at >= cutoff)
                      .execution_options(yield_per=50))
            for data in s.scalars(recent):
                wanted -= _refs(data)
                if not wanted:
                    break
        for a in rows:
            if a.id in wanted:
                keys.append(a.key)
                s.delete(a)
    return keys


def out(a: Attachment) -> dict:
    return {"id": a.id, "name": a.name, "content_type": a.content_type, "size": a.size,
            "image": a.content_type in INLINE, "file": node_file(a),
            "url": f"/api/attachments/{a.id}", "created_at": a.created_at.isoformat()}

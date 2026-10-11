"""Attachments: files uploaded into a workspace and shown by `file` nodes.

A node refers to one as {"type": "file", "file": "attachments/<id>/<name>"}:
a path, as JSON Canvas expects, that still reads sensibly in Obsidian (where
the file is simply missing). Only sniffed raster images are served inline;
everything else downloads, so an upload can never run as a page here.
"""

from __future__ import annotations

import re
import unicodedata

from .models import Attachment

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


def out(a: Attachment) -> dict:
    return {"id": a.id, "name": a.name, "content_type": a.content_type, "size": a.size,
            "image": a.content_type in INLINE, "file": node_file(a),
            "url": f"/api/attachments/{a.id}", "created_at": a.created_at.isoformat()}

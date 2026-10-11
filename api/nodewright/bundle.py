"""Workspace zip export (design §3.3).

The zip is laid out so that, unpacked, the folder opens as an Obsidian vault:

    <tab name>.canvas                       one per tab, in tab order
    attachments/<id>/<name>                 every attachment a tab shows
    .nodewright/workspace.json              name, tab order, version (for a later import)

Canvases are written unchanged: file nodes already point at
`attachments/<id>/<name>` and tab links at `<tab name>.canvas`, both
vault-relative, so they resolve without rewriting.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import zipfile
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import __version__, attachments
from .models import Attachment, Canvas, Workspace
from .storage import Store

log = logging.getLogger("nodewright.bundle")

MANIFEST = ".nodewright/workspace.json"
SPOOL_BYTES = 8 * 1024 * 1024
CHUNK = 64 * 1024


def safe_name(name: str, fallback: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _.()-]", "", name).strip(" .") or fallback


def tab_files(tabs: list[Canvas]) -> list[str]:
    """`<name>.canvas` per tab; a repeated name gets " (2)", " (3)", ..."""
    seen: dict[str, int] = {}
    out = []
    for c in tabs:
        base = safe_name(c.name, "canvas")
        n = seen.get(base.lower(), 0) + 1
        seen[base.lower()] = n
        out.append(f"{base}.canvas" if n == 1 else f"{base} ({n}).canvas")
    return out


def build(s: Session, ws: Workspace, store: Store | None) -> Iterator[bytes]:
    """The zip, as chunks. Built into a spooled temp file first (memory up to
    SPOOL_BYTES, then disk) so a large export never sits whole in memory."""
    tabs = list(s.scalars(select(Canvas).where(Canvas.workspace_id == ws.id)
                          .order_by(Canvas.position, Canvas.created_at)))
    names = tab_files(tabs)
    used: set[str] = set()
    for c in tabs:
        used |= attachments._refs(c.data)
    files = [] if store is None or not used else list(s.scalars(
        select(Attachment).where(Attachment.workspace_id == ws.id, Attachment.id.in_(used))
        .order_by(Attachment.created_at)))

    buf = tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES)
    missing = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for c, name in zip(tabs, names):
            zf.writestr(name, json.dumps(c.data, indent="\t", ensure_ascii=False))
        for a in files:
            try:
                chunks = store.get(a.key)
            except KeyError:
                missing.append(a.id)
                continue
            # Images and most uploads are compressed already.
            with zf.open(zipfile.ZipInfo(attachments.node_file(a)), "w") as out:
                for chunk in chunks:
                    out.write(chunk)
        zf.writestr(MANIFEST, json.dumps({
            "nodewright": __version__, "workspace": ws.name,
            "tabs": [{"name": c.name, "file": n} for c, n in zip(tabs, names)],
            "missing_attachments": missing,
        }, indent="\t", ensure_ascii=False))
    if missing:
        log.warning("export of workspace %s: %d attachment(s) missing from storage",
                    ws.id, len(missing))

    def stream() -> Iterator[bytes]:
        try:
            buf.seek(0)
            while chunk := buf.read(CHUNK):
                yield chunk
        finally:
            buf.close()
    return stream()

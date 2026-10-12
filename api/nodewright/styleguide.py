"""Diagram style guides handed to agents: the user's own (design §11.4) and
their orgs' (design §20), which admins write."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Org, OrgStyleGuide, StyleGuide, User, Workspace, utcnow

MAX_CHARS = 20_000

DEFAULT = """\
# Diagram style guide (nodewright default)

- Prefer omitting x/y/width/height: nodewright places and sizes nodes for you.
  Pass `direction` ("TB" top-to-bottom, or "LR" left-to-right) to choose the flow.
- One idea per node. Node text is Markdown; keep it short — a title line, then at
  most a few bullets. Put detail in a separate node or a linked canvas.
- Use groups for boundaries (a service, a network, a team). Give every group a label.
- Label edges only when the relationship isn't obvious ("reads", "publishes to").
- Colours: "1" red, "2" orange, "3" yellow, "4" green, "5" cyan, "6" purple, or "#rrggbb".
  Use them for meaning (e.g. red = external, green = ours), not decoration, and say
  what they mean in a small legend node if you use more than two.
- Build large diagrams in a few add_elements calls, one area at a time, then call
  `layout` once if the result looks crowded.
- Don't delete or move things the user drew unless asked.
"""


def get(s: Session, user: User) -> tuple[str, bool]:
    row = s.get(StyleGuide, user.id)
    return (row.text, False) if row is not None else (DEFAULT, True)


def org_get(s: Session, org_id: str) -> str:
    row = s.get(OrgStyleGuide, org_id)
    return row.text if row is not None else ""


def org_put(s: Session, org_id: str, text: str) -> str:
    """Empty text removes the org's guide."""
    row = s.get(OrgStyleGuide, org_id)
    if not text.strip():
        if row is not None:
            s.delete(row)
        return ""
    if row is None:
        s.add(OrgStyleGuide(org_id=org_id, text=text))
    else:
        row.text, row.updated_at = text, utcnow()
    return text


def for_agent(s: Session, user: User, orgs: list[Org], ws: Workspace | None) -> dict:
    """What get_style_guide returns: the user's guide plus org guides, only
    that workspace's org when one is given."""
    text, default = get(s, user)
    if ws is not None:
        orgs = [o for o in orgs if o.id == ws.org_id]
    guides = [{"org": o.name, "text": t} for o in orgs if (t := org_get(s, o.id))]
    return {"style_guide": text, "is_default": default, "org_guides": guides}

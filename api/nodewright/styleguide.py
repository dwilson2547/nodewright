"""Per-user diagram style guide handed to agents (design §11.4)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import StyleGuide, User

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

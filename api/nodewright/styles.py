"""Style extensions (design §3.2), shared with ui/src/styles.ts.

Keys and values are the Obsidian Advanced Canvas plugin's `styleAttributes`
(checked at its commit 4b8630c), so styled documents also render there.
`lineWidth` and `cornerRadius` are nodewright's own. An absent key means the default.

canvas_format only checks the shape (an object of strings), so documents from
newer plugin versions with values we don't know still load. Agent writes are
checked strictly against these lists so a typo fails loudly.
"""

from __future__ import annotations

NODE = {
    "shape": {"pill", "diamond", "parallelogram", "circle", "predefined-process", "document",
              "database"},
    "border": {"dashed", "dotted", "invisible"},
    "textAlign": {"center", "right"},
}
EDGE = {
    "path": {"dotted", "short-dashed", "long-dashed"},
    "arrow": {"triangle-outline", "thin-triangle", "halved-triangle", "diamond",
              "diamond-outline", "circle", "circle-outline", "blunt"},
    "pathfindingMethod": {"direct", "square", "a-star"},
    "lineWidth": {"1", "2", "3", "4", "6", "8"},
    "cornerRadius": {"0", "4", "8", "12", "16", "24", "32", "48"},
}

KEY = "styleAttributes"


def describe(table: dict[str, set[str]]) -> str:
    return "; ".join(f"{k}: {'|'.join(sorted(v))}" for k, v in table.items())


def check(value, table: dict[str, set[str]], where: str) -> dict:
    """Return a cleaned styleAttributes object (nulls dropped) or raise
    ValueError naming the bad key/value."""
    if not isinstance(value, dict):
        raise ValueError(f"{where}.{KEY} must be an object")
    out = {}
    for k, v in value.items():
        if v is None or v == "":
            continue
        if k not in table:
            raise ValueError(f"{where}.{KEY} has unknown key {k!r}; known: {sorted(table)}")
        v = str(v) if isinstance(v, int) and not isinstance(v, bool) else v
        if v not in table[k]:
            raise ValueError(f"{where}.{KEY}.{k} must be one of {sorted(table[k])} "
                             "(omit it for the default)")
        out[k] = v
    return out

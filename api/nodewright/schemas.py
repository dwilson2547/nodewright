"""Schema nodes (design §12): a text node with `schema: <format>` whose text
is the schema source in a fenced code block. The source is parsed here (one
parser for the editor and agents) into fields, and each field gets a port on
each side at its line: `<path>` on the right, `<path>@left` on the left.

The editor draws the source with fixed metrics (HEADER, PAD, LINE below and
ui/src/schema.ts), so a line's height in the node is known and the node's
height always fits its source.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import yaml

FORMATS = ("avro", "protobuf", "json", "yaml", "sql")
HEADER, PAD, LINE = 28, 8, 18  # px; must match ui/src/schema.ts
MIN_WIDTH = 220
MAX_SOURCE = 100_000
MAX_FIELDS = 400
MAX_DEPTH = 8
LEFT = "@left"

_FENCE_RE = re.compile(r"^\s*```[\w-]*[ \t]*\n(.*?)\n?```\s*$", re.S)


@dataclass
class Field:
    path: str
    name: str
    type: str
    line: int  # 0-based, in the source


class SchemaError(ValueError):
    pass


def fence(fmt: str, source: str) -> str:
    return f"```{fmt}\n{source.rstrip()}\n```"


def unfence(text: str) -> str:
    m = _FENCE_RE.match(text or "")
    return m.group(1) if m else (text or "")


def line_count(source: str) -> int:
    return max(1, len(source.rstrip("\n").split("\n")))


def height(source: str) -> int:
    return HEADER + 2 * PAD + line_count(source) * LINE


def port_at(line: int, h: int) -> float:
    return round((HEADER + PAD + (line + 0.5) * LINE) / h, 4)


# --- YAML-composed formats (Avro, JSON, YAML): nodes carry line numbers -------

def _compose(source: str):
    try:
        # Tabs aren't YAML indentation; JSON allows them. Line numbers don't move.
        return yaml.compose(source.replace("\t", "    "), Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark else ""
        problem = getattr(exc, "problem", None) or str(exc).split("\n")[0]
        raise SchemaError(f"can't parse{where}: {problem}") from None


def _get(node, key: str):
    if isinstance(node, yaml.MappingNode):
        for k, v in node.value:
            if isinstance(k, yaml.ScalarNode) and k.value == key:
                return v
    return None


def _str(node) -> str | None:
    return node.value if isinstance(node, yaml.ScalarNode) else None


def _items(node):
    return node.value if isinstance(node, yaml.MappingNode) else []


class _Out:
    def __init__(self):
        self.fields: list[Field] = []

    def add(self, path: str, name: str, type_: str, line: int) -> None:
        if len(self.fields) < MAX_FIELDS:
            self.fields.append(Field(path, name, type_, line))


def _avro_type(t) -> str:
    if isinstance(t, yaml.ScalarNode):
        return t.value
    if isinstance(t, yaml.SequenceNode):
        return "|".join(_avro_type(x) for x in t.value)
    kind = _str(_get(t, "type")) or "?"
    if kind in ("record", "enum", "fixed"):
        return _str(_get(t, "name")) or kind
    if kind == "array":
        return f"array<{_avro_type(_get(t, 'items'))}>"
    if kind == "map":
        return f"map<{_avro_type(_get(t, 'values'))}>"
    return kind


def _avro_records(t):
    """Records nested in a field's type (direct, in a union, or as array items / map values)."""
    if isinstance(t, yaml.SequenceNode):
        for x in t.value:
            yield from _avro_records(x)
    elif isinstance(t, yaml.MappingNode):
        kind = _str(_get(t, "type"))
        if kind == "record":
            yield t
        elif kind == "array":
            yield from _avro_records(_get(t, "items"))
        elif kind == "map":
            yield from _avro_records(_get(t, "values"))


def _avro_fields(rec, prefix: str, out: _Out, depth: int) -> None:
    fields = _get(rec, "fields")
    if not isinstance(fields, yaml.SequenceNode) or depth > MAX_DEPTH:
        return
    for f in fields.value:
        name_node = _get(f, "name")
        name = _str(name_node)
        if not name:
            continue
        path = f"{prefix}{name}"
        t = _get(f, "type")
        out.add(path, name, _avro_type(t) if t is not None else "?", name_node.start_mark.line)
        for nested in _avro_records(t):
            _avro_fields(nested, path + ".", out, depth + 1)


def _avro(source: str) -> tuple[str, list[Field]]:
    root = _compose(source)
    records = root.value if isinstance(root, yaml.SequenceNode) else [root]
    records = [r for r in records if _str(_get(r, "type")) == "record"]
    if not records:
        raise SchemaError("no Avro record found (expected {\"type\": \"record\", ...})")
    out = _Out()
    many = len(records) > 1
    for r in records:
        _avro_fields(r, (_str(_get(r, "name")) + ".") if many else "", out, 0)
    return _str(_get(records[0], "name")) or "record", out.fields


def _js_type(v) -> str:
    if isinstance(v, yaml.MappingNode):
        ref = _str(_get(v, "$ref"))
        if ref:
            return ref.rsplit("/", 1)[-1]
        t = _get(v, "type")
        if isinstance(t, yaml.SequenceNode):
            return "|".join(x.value for x in t.value if isinstance(x, yaml.ScalarNode))
        kind = _str(t) or ("object" if _get(v, "properties") else "any")
        if kind == "array":
            return f"array<{_js_type(_get(v, 'items'))}>"
        fmt = _str(_get(v, "format"))
        return f"{kind} ({fmt})" if fmt else kind
    return "any"


def _js_props(schema, prefix: str, out: _Out, depth: int) -> None:
    if depth > MAX_DEPTH:
        return
    for k, v in _items(_get(schema, "properties")):
        name = _str(k)
        if not name:
            continue
        path = f"{prefix}{name}"
        out.add(path, name, _js_type(v), k.start_mark.line)
        _js_props(v, path + ".", out, depth + 1)
        items = _get(v, "items")
        if items is not None:
            _js_props(items, path + ".", out, depth + 1)


def _example(node, prefix: str, out: _Out, depth: int) -> None:
    """A plain JSON/YAML document: its keys are the fields."""
    if depth > MAX_DEPTH:
        return
    if isinstance(node, yaml.SequenceNode):
        if node.value:
            _example(node.value[0], prefix, out, depth + 1)
        return
    for k, v in _items(node):
        name = _str(k)
        if not name:
            continue
        path = f"{prefix}{name}"
        if isinstance(v, yaml.MappingNode):
            kind = "object"
        elif isinstance(v, yaml.SequenceNode):
            kind = "array"
        else:
            kind = {"tag:yaml.org,2002:int": "integer", "tag:yaml.org,2002:float": "number",
                    "tag:yaml.org,2002:bool": "boolean", "tag:yaml.org,2002:null": "null"}.get(v.tag, "string")
        out.add(path, name, kind, k.start_mark.line)
        _example(v, path + ".", out, depth + 1)


def _json_like(source: str) -> tuple[str, list[Field]]:
    root = _compose(source)
    if root is None:
        raise SchemaError("the document is empty")
    out = _Out()
    title = _str(_get(root, "title"))
    is_schema = isinstance(root, yaml.MappingNode) and (
        _get(root, "properties") is not None or _get(root, "$schema") is not None
        or _get(root, "$defs") is not None or _get(root, "definitions") is not None
        or _get(_get(root, "components"), "schemas") is not None)
    if not is_schema:
        _example(root, "", out, 0)
        return title or "document", out.fields
    _js_props(root, "", out, 0)
    first = None
    for defs in (_get(root, "$defs"), _get(root, "definitions"), _get(_get(root, "components"), "schemas")):
        for k, v in _items(defs):
            name = _str(k)
            if name:
                first = first or name
                _js_props(v, name + ".", out, 1)
    return title or first or "schema", out.fields


# --- Protobuf and SQL: line scanners -----------------------------------------

_PB_FIELD = re.compile(
    r"^\s*(?:repeated\s+|optional\s+|required\s+)?(map\s*<[^>]+>|[A-Za-z_][\w.]*)\s+([A-Za-z_]\w*)\s*=\s*\d+")
_PB_BLOCK = re.compile(r"^\s*(message|enum|oneof|service|extend)\s+([A-Za-z_][\w.]*)\s*\{")


def _strip_comments(source: str) -> list[str]:
    no_block = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), source, flags=re.S)
    return [re.sub(r"//.*$", "", ln) for ln in no_block.split("\n")]


def _protobuf(source: str) -> tuple[str, list[Field]]:
    out = _Out()
    stack: list[tuple[str, str]] = []  # (kind, name) of open blocks
    first = None
    for i, ln in enumerate(_strip_comments(source)):
        b = _PB_BLOCK.match(ln)
        rest = ln
        if b:
            kind, name = b.groups()
            if kind == "message":
                first = first or name
            stack.append((kind, name))
            rest = ln[b.end():]  # a one-line block's fields follow its "{"
        if stack and stack[-1][0] in ("message", "oneof"):
            for stmt in rest.split(";"):
                f = _PB_FIELD.match(stmt.lstrip("{} \t"))
                if f and f.group(1) not in ("option", "reserved", "extensions"):
                    msgs = [n for k, n in stack if k == "message"]
                    out.add(".".join([*msgs, f.group(2)]), f.group(2), re.sub(r"\s+", "", f.group(1)), i)
        # Braces other than the block opener (option literals and the like) nest too.
        for _ in range(ln.count("{") - (1 if b else 0)):
            stack.append(("other", ""))
        for _ in range(ln.count("}")):
            if stack:
                stack.pop()
    if first is None:
        raise SchemaError("no Protobuf message found")
    return first, out.fields


_SQL_CREATE = re.compile(
    r"create\s+(?:or\s+replace\s+)?(?:temp(?:orary)?\s+)?table\s+(?:if\s+not\s+exists\s+)?"
    r"((?:[\"`\[]?[\w$]+[\"`\]]?\.)?[\"`\[]?[\w$]+[\"`\]]?)\s*\(", re.I)
_SQL_COLUMN = re.compile(r"^\s*([\"`\[]?[\w$]+[\"`\]]?)\s+(.+?)\s*$", re.S)
_SQL_NOT_COLUMN = {"constraint", "primary", "foreign", "unique", "check", "key", "index", "exclude",
                   "like", "period"}
_SQL_TYPE_END = re.compile(r"\s+(not\s+null|null|primary|references|default|unique|check|constraint|"
                           r"generated|collate|auto_increment|identity)\b.*$", re.I | re.S)


def _unquote(name: str) -> str:
    return name.strip('"`[]')


def _sql(source: str) -> tuple[str, list[Field]]:
    """Columns of each CREATE TABLE: its body split at top-level commas, each
    item's line taken from where it starts."""
    text = re.sub(r"--[^\n]*", lambda m: " " * len(m.group(0)), source)
    out = _Out()
    first = None
    pos = 0
    while (m := _SQL_CREATE.search(text, pos)):
        table = _unquote(m.group(1).split(".")[-1])
        first = first or table
        depth, start, i = 1, m.end(), m.end()
        items: list[tuple[int, str]] = []
        while i < len(text) and depth > 0:
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if (ch == "," and depth == 1) or depth == 0:
                items.append((start, text[start:i]))
                start = i + 1
            i += 1
        for off, item in items:
            lead = len(item) - len(item.lstrip())
            c = _SQL_COLUMN.match(item.strip())
            if c and _unquote(c.group(1)).lower() not in _SQL_NOT_COLUMN:
                col = _unquote(c.group(1))
                typ = re.sub(r"\s+", " ", _SQL_TYPE_END.sub("", c.group(2))).strip()
                out.add(f"{table}.{col}", col, typ, text.count("\n", 0, off + lead))
        pos = i
    if first is None:
        raise SchemaError("no CREATE TABLE found")
    return first, out.fields


_PARSERS = {"avro": _avro, "protobuf": _protobuf, "json": _json_like, "yaml": _json_like, "sql": _sql}


def parse(fmt: str, source: str) -> dict:
    """{name, fields, error}; a parse error comes back as `error` with no fields."""
    if fmt not in FORMATS:
        raise SchemaError(f"schema must be one of {list(FORMATS)}")
    if len(source) > MAX_SOURCE:
        raise SchemaError(f"the schema is longer than {MAX_SOURCE // 1000} KB")
    try:
        name, fields = _PARSERS[fmt](source)
        return {"name": name, "fields": [asdict(f) for f in fields], "error": None}
    except SchemaError as exc:
        return {"name": None, "fields": [], "error": str(exc)}


def ports_for(fields: list[dict], h: int) -> list[dict]:
    seen, out = set(), []
    for f in fields:
        if f["path"] in seen:
            continue
        seen.add(f["path"])
        at = port_at(f["line"], h)
        out += [{"id": f["path"], "side": "right", "at": at},
                {"id": f["path"] + LEFT, "side": "left", "at": at}]
    return out[: 2 * MAX_FIELDS]


def derive(node: dict) -> dict:
    """Normalise a schema node in place (fenced text, height, ports) and
    return the parse result."""
    fmt = node["schema"]
    source = unfence(node.get("text", ""))
    result = parse(fmt, source)
    node["text"] = fence(fmt, source)
    node["height"] = height(source)
    node["width"] = max(int(node.get("width") or 0), MIN_WIDTH)
    node["ports"] = ports_for(result["fields"], node["height"])
    return result

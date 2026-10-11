"""SVG icon validation (design §13.2).

An uploaded SVG is parsed with a hardened parser (no DTDs, no entities) and
every element and attribute is checked against an allowlist of drawing
features. Anything else (script, event handlers, foreignObject, style,
external references, ...) rejects the upload with a list of what was found.
The stored SVG is rebuilt from the checked tree, never the uploaded bytes.

A `style` attribute is turned into the equivalent presentation attributes,
each checked like any other; a <style> element is rejected.

Editor metadata that Inkscape and similar tools add (their own namespaces and
<metadata>) is dropped rather than rejected, so ordinary exports go through.
Icons are only ever shown as images (mask or <img>), so a miss here still
can't run script; this is the first of two layers.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
XML = "http://www.w3.org/XML/1998/namespace"
# Editors' private namespaces: dropped silently.
EDITOR_NS = {
    "http://www.inkscape.org/namespaces/inkscape",
    "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://creativecommons.org/ns#",
    "http://purl.org/dc/elements/1.1/",
    "http://ns.adobe.com/AdobeIllustrator/10.0/",
    "http://ns.adobe.com/SaveForWeb/1.0/",
    "http://www.bohemiancoding.com/sketch/ns",
}

MAX_BYTES = 256 * 1024
MAX_ELEMENTS = 5000
MAX_DEPTH = 32

ELEMENTS = {
    "svg", "g", "defs", "title", "desc", "symbol", "use", "path", "rect", "circle", "ellipse",
    "line", "polyline", "polygon", "text", "tspan", "linearGradient", "radialGradient", "stop",
    "clipPath", "mask", "pattern", "marker",
}
TEXT_ELEMENTS = {"title", "desc", "text", "tspan"}
ATTRIBUTES = {
    "id", "class", "version", "viewBox", "preserveAspectRatio", "transform", "x", "y", "width",
    "height", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "fx", "fy", "fr", "d", "points",
    "pathLength", "fill", "fill-opacity", "fill-rule", "clip-rule", "stroke", "stroke-width",
    "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray",
    "stroke-dashoffset", "stroke-opacity", "opacity", "color", "visibility", "display",
    "vector-effect", "paint-order", "shape-rendering", "offset", "stop-color", "stop-opacity",
    "gradientUnits", "gradientTransform", "spreadMethod", "clip-path", "clipPathUnits", "mask",
    "maskUnits", "maskContentUnits", "patternUnits", "patternContentUnits", "patternTransform",
    "markerWidth", "markerHeight", "markerUnits", "refX", "refY", "orient", "marker-start",
    "marker-mid", "marker-end", "font-family", "font-size", "font-weight", "font-style",
    "text-anchor", "dominant-baseline", "alignment-baseline", "baseline-shift", "letter-spacing",
    "word-spacing", "dx", "dy", "rotate", "textLength", "lengthAdjust", "href",
}
# Attributes a `style` declaration may become: presentation ones, not geometry.
STYLE_PROPS = {a for a in ATTRIBUTES if "-" in a or a in {
    "fill", "stroke", "opacity", "color", "visibility", "display", "mask"}} - {"href"}
URL_RE = re.compile(r"url\s*\(", re.I)
LOCAL_URL_RE = re.compile(r"^url\(\s*#[A-Za-z_][\w.:-]*\s*\)$")
BAD_VALUE_RE = re.compile(r"javascript:|data:|expression\s*\(|@import|<", re.I)
NUMBER_RE = re.compile(r"^\s*([0-9.]+)\s*(px)?\s*$")


class SvgRejected(ValueError):
    """The upload isn't an SVG we can accept; str() says why."""


def _split(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        ns, _, local = tag[1:].partition("}")
        return ns, local
    return "", tag


def clean(data: bytes) -> str:
    """The checked SVG as text, or SvgRejected listing every problem found."""
    if len(data) > MAX_BYTES:
        raise SvgRejected(f"the file is larger than {MAX_BYTES // 1024} KB")
    try:
        root = fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException:
        raise SvgRejected("the file declares a DTD or entities, which aren't allowed") from None
    except ET.ParseError as exc:
        raise SvgRejected(f"the file isn't valid XML ({exc})") from None
    ns, local = _split(root.tag)
    if local != "svg" or ns not in (SVG, ""):
        raise SvgRejected("the file isn't an SVG (its root element must be <svg>)")

    problems: list[str] = []
    count = 0

    def copy(src: ET.Element, depth: int) -> ET.Element | None:
        nonlocal count
        ns, local = _split(src.tag)
        if ns in EDITOR_NS or (ns in (SVG, "") and local == "metadata"):
            return None
        if ns not in (SVG, "") or local not in ELEMENTS:
            problems.append(f"element <{local}>")
            return None
        count += 1
        if count > MAX_ELEMENTS or depth > MAX_DEPTH:
            raise SvgRejected("the drawing is too large or too deeply nested")
        out = ET.Element(f"{{{SVG}}}{local}")
        attrs = dict(src.attrib)
        for decl in attrs.pop("style", "").split(";"):
            prop, sep, val = decl.partition(":")
            prop, val = prop.strip(), val.strip()
            if not sep or not prop:
                continue
            if prop in STYLE_PROPS:
                attrs.setdefault(prop, val)
            elif not prop.startswith(("-inkscape-", "-sodipodi-")):
                problems.append(f"style property {prop!r} on <{local}>")
        for key, value in attrs.items():
            ans, name = _split(key)
            if ans in EDITOR_NS:
                continue
            if ans == XML and name == "space":
                out.set(key, value)
                continue
            if ans not in ("", XLINK) or name not in ATTRIBUTES or (ans == XLINK and name != "href"):
                problems.append(f"attribute {name!r} on <{local}>")
                continue
            if name == "href":
                if not value.startswith("#"):
                    problems.append(f"a link to {value[:40]!r} (only links inside the file are allowed)")
                    continue
                out.set(f"{{{XLINK}}}href" if ans == XLINK else "href", value)
                continue
            if BAD_VALUE_RE.search(value):
                problems.append(f"the value of {name!r} on <{local}>")
                continue
            if URL_RE.search(value) and not LOCAL_URL_RE.match(value.strip()):
                problems.append(f"a url() in {name!r} on <{local}> (only #ids inside the file)")
                continue
            out.set(name, value)
        if local in TEXT_ELEMENTS and src.text and src.text.strip():
            out.text = src.text
        for child in src:
            c = copy(child, depth + 1)
            if c is not None:
                out.append(c)
                if local in TEXT_ELEMENTS and child.tail and child.tail.strip():
                    c.tail = child.tail
        return out

    out = copy(root, 0)
    if problems:
        uniq = list(dict.fromkeys(problems))
        more = f" and {len(uniq) - 8} more" if len(uniq) > 8 else ""
        raise SvgRejected("not allowed in an icon: " + "; ".join(uniq[:8]) + more)
    assert out is not None
    if "viewBox" not in out.attrib:
        w, h = (NUMBER_RE.match(out.get(k, "")) for k in ("width", "height"))
        if not (w and h):
            raise SvgRejected("the SVG needs a viewBox, or a numeric width and height")
        out.set("viewBox", f"0 0 {w.group(1)} {h.group(1)}")
    # Sized by its container: the viewBox keeps the proportions.
    out.attrib.pop("width", None)
    out.attrib.pop("height", None)
    ET.register_namespace("", SVG)
    ET.register_namespace("xlink", XLINK)
    return ET.tostring(out, encoding="unicode")
